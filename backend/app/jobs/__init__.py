"""Async job execution (redesign §11).

The web process enqueues jobs (`queue.enqueue`); a separate Celery worker runs
them (`runners`), writing progress and artifacts back to the `jobs` table — the
single source of truth — and publishing live updates to a Redis channel that the
`/api/jobs/{id}/stream` SSE endpoint relays to the dashboard.
"""
