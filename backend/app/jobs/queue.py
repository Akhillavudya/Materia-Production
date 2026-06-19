"""Job queue — Celery app + a backend-agnostic `enqueue` helper.

The web process imports only this module to dispatch work; it sends tasks *by
name* so it never has to import ASE/MACE or the runners. The worker process
imports `app.jobs.runners`, which registers the task implementations.

`JOB_BACKEND=inline` runs the job in a background thread instead of via Celery —
a fallback for local dev without a Redis broker (state still persists to the DB).
"""

from __future__ import annotations

import threading

from celery import Celery

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.jobs import JobType

logger = get_logger(__name__)

# Task names — the contract between web (sender) and worker (registrar).
TASK_NAMES = {
    JobType.OPTIMIZE: "jobs.optimize",
    JobType.MD: "jobs.md",
    JobType.ELASTIC: "jobs.elastic",
    JobType.PHONON: "jobs.phonon",
}

celery_app = Celery(
    "materia",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=settings.max_job_wallclock_s,
    worker_prefetch_multiplier=1,   # one long job at a time per worker process
    task_acks_late=True,
)


def enqueue(job_type: JobType, job_id: str) -> None:
    """Dispatch a job for execution via the configured backend."""
    if settings.job_backend == "inline":
        _run_inline(job_type, job_id)
        return
    celery_app.send_task(TASK_NAMES[job_type], args=[job_id])
    logger.info("Enqueued %s job %s", job_type.value, job_id)


def _run_inline(job_type: JobType, job_id: str) -> None:
    """Dev fallback: run the job in a daemon thread (no broker required)."""
    from app.jobs import runners

    target = {
        JobType.OPTIMIZE: runners.run_optimize_job,
        JobType.MD: runners.run_md_job,
        JobType.ELASTIC: runners.run_elastic_job,
        JobType.PHONON: runners.run_phonon_job,
    }[job_type]
    threading.Thread(target=target, args=(job_id,), daemon=True).start()
    logger.info("Started inline %s job %s (thread)", job_type.value, job_id)
