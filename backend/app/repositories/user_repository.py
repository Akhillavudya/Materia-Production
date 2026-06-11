"""Persistence for `User` rows."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User


async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    email: str,
    full_name: str | None,
    hashed_password: str,
) -> User:
    user = User(email=email, full_name=full_name, hashed_password=hashed_password)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
