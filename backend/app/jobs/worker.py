"""Celery worker entrypoint.

Run a GPU-pinned worker (concurrency=1 so one long simulation runs at a time):

    cd backend
    celery -A app.jobs.worker:celery_app worker --loglevel=info --concurrency=1

Importing `runners` here registers the `jobs.optimize` / `jobs.md` tasks on the
shared `celery_app`.
"""

from app.jobs.queue import celery_app
from app.jobs import runners  # noqa: F401 — side effect: registers Celery tasks

__all__ = ["celery_app"]
