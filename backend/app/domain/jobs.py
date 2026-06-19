"""Job domain models (redesign §11/§12).

Framework-agnostic vocabulary for the async job system. The ``jobs`` table is the
source of truth for job state; the broker only carries "run job X". These Pydantic
models define the validated spec the agent tools produce and the record the API
projects back to the dashboard.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobType(str, Enum):
    OPTIMIZE = "optimize"
    MD = "md"
    ELASTIC = "elastic"
    PHONON = "phonon"
    SQS = "sqs"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Statuses past which a job no longer changes (used by stream/cancel logic).
TERMINAL_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
)


class JobCancelled(Exception):
    """Raised inside a simulation's progress callback to stop a cancelled job.

    The simulation services catch this and return a partial result; the runner
    marks the job ``cancelled``. Keeps cancellation cooperative without the
    services importing the job system.
    """


class JobSpec(BaseModel):
    """Everything the worker needs to run the job, independent of HTTP/agent.

    ``poscar_path`` is the *resolved absolute path* of the input structure (the
    web process resolves "auto"/CONTCAR-vs-POSCAR before enqueueing, so the
    worker never re-implements session lookup).
    """

    poscar_path: str
    output_dir: str
    params: dict[str, Any] = Field(default_factory=dict)
    calculator: dict[str, Any] = Field(default_factory=dict)
    emit_vasp_inputs: bool = True


class JobProgress(BaseModel):
    step: int = 0
    total: int | None = None
    pct: float | None = None
    energy: float | None = None
    fmax: float | None = None
    temperature: float | None = None
    message: str | None = None


class JobRecord(BaseModel):
    """API projection of a ``jobs`` row (no internal ``spec_hash``)."""

    id: str
    user_id: int
    session_id: str
    type: JobType
    status: JobStatus
    spec: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] | None = None
    error: str | None = None
    calculator: dict[str, Any] | None = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
