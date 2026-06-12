"""Synchronous job-state store for the Celery worker.

Celery tasks are synchronous processes, so they cannot use the app's async
SQLAlchemy session. This module owns a small *sync* engine and the state
transitions the worker performs (running → succeeded/failed/cancelled) plus
throttled progress writes. The `jobs` table remains the single source of truth.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.models import Job
from app.domain.jobs import JobStatus

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
            s.commit()


def mark_failed(job_id: str, error: str) -> None:
    with _Session() as s:
        job = s.get(Job, job_id)
        if job:
            job.status = JobStatus.FAILED.value
            job.error = error[:4000]
            job.finished_at = _now()
            s.commit()
