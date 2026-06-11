"""Persistence for chat `Message` rows."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Message


async def list_for_session(db: AsyncSession, session_id: str) -> Sequence[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id)
    )
    return result.scalars().all()


async def add(
    db: AsyncSession,
    *,
    session_id: str,
    role: str,
    content: str,
    tool_result: str | None,
) -> Message:
    message = Message(
        session_id=session_id,
        role=role,
        content=content,
        tool_result=tool_result,
    )
    db.add(message)
    await db.commit()
    return message
