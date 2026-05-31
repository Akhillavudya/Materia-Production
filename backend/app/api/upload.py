import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database.db import get_db, AsyncSessionLocal
from app.database.models import Session
from app.services.file_service import (
    get_upload_dir,
    sanitize_filename,
    is_upload_allowed,
    STORAGE_ROOT,
)

router = APIRouter()


class UploadedFileOut(BaseModel):
    name:       str
    size_kb:    float
    rel_path:   str
    group_name: str = "uploads"


# ── POST /api/sessions/{session_id}/upload ────────────────────────────────────

@router.post('/sessions/{session_id}/upload', response_model=list[UploadedFileOut])
async def upload_files(
    session_id: str,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload one or more files into the session's uploads/ folder.

    Security measures:
    - filename is sanitized to strip path components
    - only allowed file types are accepted
    - files are scoped to the session folder
    - full server path is never returned to frontend
    """

    # verify session exists
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')

    upload_dir = get_upload_dir(session_id)
    uploaded   = []
    errors     = []

    for file in files:
        original_name = file.filename or "unnamed"

        # sanitize the filename — removes path components and dangerous chars
        safe_name = sanitize_filename(original_name)

        # check if this file type is allowed
        if not is_upload_allowed(safe_name):
            errors.append(f"{original_name}: file type not allowed")
            continue

        # write to disk
        dest = upload_dir / safe_name
        try:
            content = await file.read()
            dest.write_bytes(content)

            rel_path = str(dest.relative_to(STORAGE_ROOT))
            size_kb  = round(dest.stat().st_size / 1024, 2)

            uploaded.append(UploadedFileOut(
                name=safe_name,
                size_kb=size_kb,
                rel_path=rel_path,
                group_name="uploads",
            ))

        except Exception as e:
            errors.append(f"{original_name}: {str(e)}")
        finally:
            await file.close()

    # if ALL files failed, return 400
    if not uploaded and errors:
        raise HTTPException(
            status_code=400,
            detail=f"Upload failed: {'; '.join(errors)}"
        )

    return uploaded


# ── POST /api/sessions/create-and-upload ─────────────────────────────────────
# used when no session exists yet (new chat + first action is upload)

@router.post('/sessions/create-and-upload')
async def create_session_and_upload(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new session then upload files into it.
    Used when user uploads before sending their first message.
    """
    # build session title from the first filename
    first_name = files[0].filename if files else "Uploaded files"
    session = Session(
        id=str(uuid.uuid4()),
        title=f"Upload: {first_name[:50]}",
    )
    db.add(session)
    await db.commit()

    # reuse the upload endpoint logic
    upload_dir = get_upload_dir(session.id)
    uploaded   = []

    for file in files:
        safe_name = sanitize_filename(file.filename or "unnamed")
        if not is_upload_allowed(safe_name):
            continue
        dest    = upload_dir / safe_name
        content = await file.read()
        dest.write_bytes(content)
        rel_path = str(dest.relative_to(STORAGE_ROOT))
        uploaded.append({
            "name":       safe_name,
            "size_kb":    round(dest.stat().st_size / 1024, 2),
            "rel_path":   rel_path,
            "group_name": "uploads",
        })
        await file.close()

    return {
        "session_id": session.id,
        "files":      uploaded,
    }