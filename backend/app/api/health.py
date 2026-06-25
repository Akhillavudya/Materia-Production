"""Health & readiness endpoints (Step 7 — the smoke detector).

Two tiny, unauthenticated routes a free uptime monitor (UptimeRobot, BetterStack,
…) can ping every minute:

- ``GET /health`` — *liveness*: "is the web process answering at all?" No external
  dependencies are touched, so it stays green even if the DB blips. Used by the
  container ``HEALTHCHECK`` and the cheapest uptime ping.
- ``GET /ready`` — *readiness*: "can I actually serve a request?" — verifies the
  database and (unless running the inline job backend) Redis are reachable.
  Returns **503** with a per-dependency breakdown when something is down, so the
  alert tells you *what* broke, not just *that* it broke.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import get_logger
from app.database.db import AsyncSessionLocal

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/health")
async def health() -> dict:
    """Liveness probe — no dependencies, always fast."""
    return {"status": "ok", "service": settings.app_name}


async def _check_database() -> tuple[bool, str]:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Readiness: database check failed: %s", exc)
        return False, "unreachable"


async def _check_redis() -> tuple[bool, str]:
    # The inline job backend has no broker, so Redis is simply not required.
    if settings.job_backend == "inline":
        return True, "skipped (inline backend)"
    try:
        import redis.asyncio as aioredis  # lazy: only needed for the broker check

        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Readiness: redis check failed: %s", exc)
        return False, "unreachable"


@router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness probe — green only when the DB and Redis are both reachable."""
    db_ok, db_detail = await _check_database()
    redis_ok, redis_detail = await _check_redis()
    ok = db_ok and redis_ok
    body = {
        "status": "ready" if ok else "degraded",
        "checks": {"database": db_detail, "redis": redis_detail},
    }
    return JSONResponse(status_code=200 if ok else 503, content=body)
