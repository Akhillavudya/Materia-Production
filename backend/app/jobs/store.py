"""Synchronous job-state store for the Celery worker.

Celery tasks are synchronous processes, so they cannot use the app's async
SQLAlchemy session. This module owns a small *sync* engine and the state
transitions the worker performs (running → succeeded/failed/cancelled) plus
throttled progress writes. The `jobs` table remains the single source of truth.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.models import Job, Message
from app.domain.jobs import JobStatus

logger = logging.getLogger(__name__)

# A sqlite sync engine must allow cross-thread use; Postgres needs no special args.
_connect_args = (
    {"check_same_thread": False}
    if settings.database_url_sync.startswith("sqlite")
    else {}
)
_engine = create_engine(
    settings.database_url_sync, future=True, connect_args=_connect_args
)
_Session = sessionmaker(bind=_engine, expire_on_commit=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_job(
    *,
    job_id: str,
    user_id: int,
    session_id: str,
    job_type: str,
    spec: dict,
    calculator: dict | None = None,
    spec_hash: str | None = None,
) -> None:
    """Insert a queued job row (sync — called from the agent tool thread)."""
    with _Session() as s:
        s.add(Job(
            id=job_id,
            user_id=user_id,
            session_id=session_id,
            type=job_type,
            status=JobStatus.QUEUED.value,
            spec=spec,
            calculator=calculator,
            spec_hash=spec_hash,
            created_at=_now(),
        ))
        s.commit()


def count_active_for_user(user_id: int) -> int:
    """Number of queued+running jobs a user currently has (for quota checks)."""
    from sqlalchemy import func, select
    with _Session() as s:
        return s.execute(
            select(func.count())
            .select_from(Job)
            .where(
                Job.user_id == user_id,
                Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
            )
        ).scalar_one()


def load_job(job_id: str) -> dict | None:
    """Return the spec/type/calculator needed to run a job, or None if missing."""
    with _Session() as s:
        job = s.get(Job, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "type": job.type,
            "status": job.status,
            "spec": job.spec or {},
            "calculator": job.calculator or {},
        }


def mark_running(job_id: str) -> None:
    with _Session() as s:
        job = s.get(Job, job_id)
        if job and job.status == JobStatus.QUEUED.value:
            job.status = JobStatus.RUNNING.value
            job.started_at = _now()
            s.commit()


def update_progress(job_id: str, progress: dict) -> None:
    with _Session() as s:
        job = s.get(Job, job_id)
        if job:
            job.progress = progress
            s.commit()


def get_status(job_id: str) -> str | None:
    with _Session() as s:
        job = s.get(Job, job_id)
        return job.status if job else None


def mark_succeeded(job_id: str, result: dict, artifacts: list[dict]) -> None:
    with _Session() as s:
        job = s.get(Job, job_id)
        if job:
            job.status = JobStatus.SUCCEEDED.value
            job.result = result
            job.artifacts = artifacts
            job.finished_at = _now()
            _sync_chat_card(s, job, JobStatus.SUCCEEDED.value)
            s.commit()


def mark_cancelled(job_id: str, result: dict | None = None,
                   artifacts: list[dict] | None = None) -> None:
    with _Session() as s:
        job = s.get(Job, job_id)
        if job:
            job.status = JobStatus.CANCELLED.value
            if result is not None:
                job.result = result
            if artifacts is not None:
                job.artifacts = artifacts
            job.finished_at = _now()
            _sync_chat_card(s, job, JobStatus.CANCELLED.value)
            s.commit()


def mark_failed(job_id: str, error: str) -> None:
    with _Session() as s:
        job = s.get(Job, job_id)
        if job:
            job.status = JobStatus.FAILED.value
            job.error = error[:4000]
            job.finished_at = _now()
            _sync_chat_card(s, job, JobStatus.FAILED.value)
            s.commit()


def _sync_chat_card(s, job: Job, status: str) -> None:
    """Rewrite the persisted chat 'job card' status for a finished job.

    A manual async-launch writes an assistant message whose ``tool_result`` card
    carries this ``job_id`` with status "queued" (see api/upload._log_manual_run).
    The live UI overlays real status by polling, but on a fresh page reload the
    DB is the source of truth — so reflect the terminal status here too. Runs in
    the SAME transaction as the status change; best-effort (never fail the job
    over a card update).
    """
    try:
        rows = s.execute(
            select(Message).where(
                Message.session_id == job.session_id,
                Message.tool_result.isnot(None),
                Message.tool_result.like(f"%{job.id}%"),
            )
        ).scalars().all()
        for msg in rows:
            try:
                cards = json.loads(msg.tool_result)
            except (TypeError, ValueError):
                continue
            if not isinstance(cards, list):
                continue
            changed = False
            for c in cards:
                if isinstance(c, dict) and c.get("job_id") == job.id:
                    c["status"] = status
                    changed = True
            if changed:
                msg.tool_result = json.dumps(cards)
    except Exception:  # noqa: BLE001 — never let a card update break job finalize
        logger.exception("Failed to sync chat job card for %s", job.id)
