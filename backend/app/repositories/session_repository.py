"""Persistence for chat `Session` rows."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Session


async def get_by_id(db: AsyncSession, session_id: str) -> Session | None:
    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def list_for_user(db: AsyncSession, user_id: int) -> Sequence[Session]:
    result = await db.execute(
        select(Session)
        .where(Session.user_id == user_id)
        .order_by(Session.created_at.desc())
    )
    return result.scalars().all()


async def create(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: int,
    title: str,
) -> Session:
    session = Session(id=session_id, user_id=user_id, title=title)
    db.add(session)
    await db.commit()
    return session
