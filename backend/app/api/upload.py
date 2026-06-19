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
    get_session_dir,
    get_upload_dir,
    is_upload_allowed,
    sanitize_filename,
)
from app.services.structure.activation import (
    StructureParseError,
    activate_structure,
    is_structure_file,
)

router = APIRouter()

_MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024


def _too_large(content: bytes) -> bool:
    return len(content) > _MAX_UPLOAD_BYTES


def _activate_uploads(session_id: str, items: list[tuple[str, str]]) -> dict:
    """Auto-activate a freshly-uploaded structure (U1).

    - exactly one structure file  → parse it and write the active POSCAR.
    - several structure files      → don't guess; ask the user which to activate.
    - none / unreadable            → just leave them stored (with a reason).
    `items` are (name, rel_path) pairs for the files that were stored.
    """
    structures = [(n, rp) for n, rp in items if is_structure_file(n)]
    if not structures:
        return {"status": "none"}
    if len(structures) > 1:
        return {"status": "multiple", "candidates": [n for n, _ in structures]}

    name, rel_path = structures[0]
    try:
        info = activate_structure(STORAGE_ROOT / rel_path, get_session_dir(session_id))
        return {"status": "activated", "file": name, **info}
    except StructureParseError as e:
        return {"status": "unreadable", "file": name, "error": str(e)}
    except Exception as e:  # noqa: BLE001 — never let activation 500 the upload
        return {"status": "unreadable", "file": name, "error": str(e)}


@router.post("/sessions/{session_id}/upload")
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

    activation = _activate_uploads(session_id, [(u.name, u.rel_path) for u in uploaded])
    return {"files": uploaded, "activation": activation, "errors": errors}


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

    activation = _activate_uploads(
        session.id, [(u["name"], u["rel_path"]) for u in uploaded])
    return {"session_id": session.id, "files": uploaded, "activation": activation}
