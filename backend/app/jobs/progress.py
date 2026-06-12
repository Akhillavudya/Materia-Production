"""ProgressReporter — bridges a simulation's progress callback to the job store.

Throttles writes (DB + Redis publish) so a 10,000-step MD doesn't hammer the
database, and raises `JobCancelled` when the job row has been marked cancelled so
the simulation stops cooperatively.
"""

from __future__ import annotations

import json
import time

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.jobs import JobCancelled, JobStatus
from app.jobs import store

logger = get_logger(__name__)


def channel(job_id: str) -> str:
    return f"job:{job_id}"


def _redis_client():
    try:
        import redis  # local import: web process need not load redis
        return redis.Redis.from_url(settings.redis_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable for progress pub/sub: %s", exc)
        return None


class ProgressReporter:
    def __init__(self, job_id: str, *, min_interval_s: float = 1.0):
        self.job_id = job_id
        self.min_interval_s = min_interval_s
        self._last_emit = 0.0
        self._redis = _redis_client()

    def __call__(self, *, step: int, total: int | None = None,
                 energy: float | None = None, fmax: float | None = None,
                 temperature: float | None = None) -> None:
        """Invoked by the simulation each logged step. Throttled; checks cancel."""
        # Cancellation check runs every call (cheap single-row read); a cancelled
        # job stops promptly rather than waiting for the next throttle window.
        if store.get_status(self.job_id) == JobStatus.CANCELLED.value:
            raise JobCancelled()

        now = time.time()
        if now - self._last_emit < self.min_interval_s:
            return
        self._last_emit = now

        pct = round(100.0 * step / total, 1) if total else None
        payload = {"step": step, "total": total, "pct": pct,
                   "energy": energy, "fmax": fmax, "temperature": temperature}
        store.update_progress(self.job_id, payload)
        self.publish({"type": "progress", **payload})

    def publish(self, event: dict) -> None:
        if not self._redis:
            return
        try:
            self._redis.publish(channel(self.job_id), json.dumps(event))
        except Exception as exc:  # noqa: BLE001 — DB is source of truth; pub is best-effort
            logger.debug("progress publish failed: %s", exc)
