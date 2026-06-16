"""File upload endpoints."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session_for_user
from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.database.db import get_db
from app.database.models import User
from app.repositories import session_repository
from app.schemas.upload import UploadedFileOut
from app.services.storage.file_service import (
    STORAGE_ROOT,
    get_upload_dir,
    is_upload_allowed,
    sanitize_filename,
)

router = APIRouter()

_MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024


def _too_large(content: bytes) -> bool:
    return len(content) > _MAX_UPLOAD_BYTES


@router.post("/sessions/{session_id}/upload", response_model=list[UploadedFileOut])
@limiter.limit("30/minute")
async def upload_files(
    request: Request,
    session_id: str,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload one or more files into the session's uploads/ folder."""
    await get_session_for_user(session_id, current_user, db)

    upload_dir = get_upload_dir(session_id)
    uploaded: list[UploadedFileOut] = []
    errors: list[str] = []

    for file in files:
        original_name = file.filename or "unnamed"
        safe_name = sanitize_filename(original_name)

        if not is_upload_allowed(safe_name):
            errors.append(f"{original_name}: file type not allowed")
            continue

        dest = upload_dir / safe_name
        try:
            content = await file.read()
            if _too_large(content):
                errors.append(f"{original_name}: exceeds {settings.max_upload_mb} MB limit")
                continue
            dest.write_bytes(content)
            uploaded.append(UploadedFileOut(
                name=safe_name,
                size_kb=round(dest.stat().st_size / 1024, 2),
                rel_path=str(dest.relative_to(STORAGE_ROOT)),
                group_name="uploads",
            ))
        except Exception as e:
            errors.append(f"{original_name}: {e}")
        finally:
            await file.close()

    if not uploaded and errors:
        raise HTTPException(status_code=400, detail=f"Upload failed: {'; '.join(errors)}")

    return uploaded


@router.post("/sessions/create-and-upload")
@limiter.limit("30/minute")
async def create_session_and_upload(
    request: Request,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new session then upload files into it (used before first message)."""
    first_name = files[0].filename if files else "Uploaded files"
    session = await session_repository.create(
        db,
        session_id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=f"Upload: {first_name[:50]}",
    )

    upload_dir = get_upload_dir(session.id)
    uploaded: list[dict] = []

    for file in files:
        safe_name = sanitize_filename(file.filename or "unnamed")
        if not is_upload_allowed(safe_name):
            continue
        dest = upload_dir / safe_name
        content = await file.read()
        if _too_large(content):
            continue
        dest.write_bytes(content)
        uploaded.append({
            "name": safe_name,
            "size_kb": round(dest.stat().st_size / 1024, 2),
            "rel_path": str(dest.relative_to(STORAGE_ROOT)),
            "group_name": "uploads",
        })
        await file.close()

    return {"session_id": session.id, "files": uploaded}
