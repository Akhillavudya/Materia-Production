"""Shared API dependencies and path-safety helpers.

Centralises the session-ownership and file-path guards that were previously
duplicated across `chat.py` and `upload.py`.
"""

from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Session, User
from app.repositories import session_repository
from app.services.storage.file_service import STORAGE_ROOT


async def get_session_for_user(
    session_id: str,
    current_user: User,
    db: AsyncSession,
) -> Session:
    """Return the session if it exists and is owned by `current_user`."""
    session = await session_repository.get_by_id(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return session


def resolve_owned_file_path(rel_path: str, current_user: User, session: Session) -> Path:
    """Resolve a session-relative path, rejecting traversal and cross-user access."""
    if Path(rel_path).is_absolute():
        raise HTTPException(status_code=403, detail="Access denied")

    full_path = (STORAGE_ROOT / rel_path).resolve()
    storage_root = STORAGE_ROOT.resolve()
    try:
        full_path.relative_to(storage_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Access denied") from exc

    if ".." in Path(rel_path).parts:
        raise HTTPException(status_code=403, detail="Access denied")

    parts = Path(rel_path).parts
    if not parts or parts[0] != session.id or session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return full_path


async def get_session_for_rel_path(
    rel_path: str,
    current_user: User,
    db: AsyncSession,
) -> tuple[Session, Path]:
    """Resolve and authorize a file path, returning its owning session + abs path."""
    if Path(rel_path).is_absolute() or ".." in Path(rel_path).parts:
        raise HTTPException(status_code=403, detail="Access denied")

    parts = Path(rel_path).parts
    if not parts:
        raise HTTPException(status_code=404, detail="File not found")

    session = await get_session_for_user(parts[0], current_user, db)
    return session, resolve_owned_file_path(rel_path, current_user, session)
