"""Job endpoints (redesign §13).

Jobs are *created* by the agent tools (the single orchestrator), so there is no
public POST to create one. These routes let the dashboard list, inspect, stream,
and cancel jobs the user owns.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import get_current_user
from app.database.db import AsyncSessionLocal, get_db
from app.database.models import Job, User
from app.domain.jobs import JobRecord, TERMINAL_STATUSES
from app.repositories import job_repository

router = APIRouter()
logger = get_logger(__name__)

_TERMINAL = {s.value for s in TERMINAL_STATUSES}


def _to_record(job: Job) -> JobRecord:
    return JobRecord.model_validate(job)


@router.get("/jobs", response_model=list[JobRecord])
async def list_jobs(
    session_id: str | None = Query(None),
    status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    jobs = await job_repository.list_for_user(
        db, current_user.id, session_id=session_id, status=status
    )
    return [_to_record(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await job_repository.get_owned(db, job_id, current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_record(job)


@router.post("/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await job_repository.get_owned(db, job_id, current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in _TERMINAL:
        return {"job_id": job_id, "status": job.status, "message": "Already finished."}
    job = await job_repository.request_cancel(db, job)
    return {"job_id": job_id, "status": job.status, "message": "Cancellation requested."}


@router.get("/jobs/{job_id}/stream")
async def stream_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE: emit progress/status changes until the job reaches a terminal state.

    Polls the `jobs` table (the source of truth) once a second — robust even if
    the Redis pub/sub channel drops an event.
    """
    job = await job_repository.get_owned(db, job_id, current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    user_id = current_user.id

    async def event_stream():
        last_signature = None
        while True:
            async with AsyncSessionLocal() as poll_db:
                current = await job_repository.get_owned(poll_db, job_id, user_id)
            if current is None:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
                return

            signature = (current.status, json.dumps(current.progress, sort_keys=True))
            if signature != last_signature:
                last_signature = signature
                yield (
                    "data: "
                    + json.dumps({
                        "type": "update",
                        "status": current.status,
                        "progress": current.progress,
                    })
                    + "\n\n"
                )

            if current.status in _TERMINAL:
                yield (
                    "data: "
                    + json.dumps({
                        "type": "done",
                        "status": current.status,
                        "result": current.result,
                        "artifacts": current.artifacts,
                        "error": current.error,
                    })
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"
                return

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
