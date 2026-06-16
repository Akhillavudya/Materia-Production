"""Persistence for user-scoped `ApiKey` rows."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ApiKey


async def get(db: AsyncSession, *, user_id: int, service: str) -> ApiKey | None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.service == service, ApiKey.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_for_user(db: AsyncSession, user_id: int) -> Sequence[ApiKey]:
    result = await db.execute(select(ApiKey).where(ApiKey.user_id == user_id))
    return result.scalars().all()


async def delete(db: AsyncSession, *, user_id: int, service: str) -> bool:
    """Remove a user's key for `service`. Returns True if a row was deleted."""
    existing = await get(db, user_id=user_id, service=service)
    if existing is None:
        return False
    await db.delete(existing)
    await db.commit()
    return True


async def upsert(
    db: AsyncSession,
    *,
    user_id: int,
    service: str,
    key_value: str,
) -> ApiKey:
    """Insert a new key or update the stored value for an existing one."""
    existing = await get(db, user_id=user_id, service=service)
    if existing:
        existing.key_value = key_value
        record = existing
    else:
        record = ApiKey(service=service, key_value=key_value, user_id=user_id)
        db.add(record)
    await db.commit()
    return record
