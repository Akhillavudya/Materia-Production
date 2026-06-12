"""Persistence for async `Job` rows (async — used by the web app & tools).

The Celery worker writes progress through a *separate sync* session (see
`app.jobs.store`), because Celery tasks are synchronous processes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job
from app.domain.jobs import JobStatus, JobType


async def create(
    db: AsyncSession,
    *,
    job_id: str,
    user_id: int,
    session_id: str,
    job_type: JobType,
    spec: dict,
    calculator: dict | None = None,
    spec_hash: str | None = None,
) -> Job:
    job = Job(
        id=job_id,
        user_id=user_id,
        session_id=session_id,
        type=job_type.value,
        status=JobStatus.QUEUED.value,
        spec=spec,
        calculator=calculator,
        spec_hash=spec_hash,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_owned(db: AsyncSession, job_id: str, user_id: int) -> Job | None:
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_for_user(
    db: AsyncSession,
    user_id: int,
    *,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[Job]:
    stmt = select(Job).where(Job.user_id == user_id)
    if session_id:
        stmt = stmt.where(Job.session_id == session_id)
    if status:
        stmt = stmt.where(Job.status == status)
    stmt = stmt.order_by(Job.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def find_active_duplicate(
    db: AsyncSession, *, user_id: int, spec_hash: str
) -> Job | None:
    """Return a still-active job with the same spec (idempotency / double-submit)."""
    result = await db.execute(
        select(Job).where(
            Job.user_id == user_id,
            Job.spec_hash == spec_hash,
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
        )
    )
    return result.scalars().first()


async def request_cancel(db: AsyncSession, job: Job) -> Job:
    """Mark a job cancelled. A queued job stops before starting; a running job is
    signalled — the worker checks status between steps and exits early."""
    if job.status == JobStatus.QUEUED.value:
        job.status = JobStatus.CANCELLED.value
        job.finished_at = datetime.now(timezone.utc)
    elif job.status == JobStatus.RUNNING.value:
        # Leave a sentinel; the worker transitions RUNNING→CANCELLED itself.
        job.status = JobStatus.CANCELLED.value
    await db.commit()
    await db.refresh(job)
    return job
