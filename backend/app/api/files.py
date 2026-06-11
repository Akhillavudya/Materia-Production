"""File operations that are not scientific tools (redesign §3, §13).

File listing / reading / downloading already live in `chat.py`; this router adds
the rename endpoint that was demoted from the agent's `rename_file` tool.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session_for_rel_path
from app.core.security import get_current_user
from app.database.db import get_db
from app.database.models import User
from app.schemas.material import RenameRequest
from app.services.storage.file_service import rel_to_storage

router = APIRouter()


@router.post("/files/{rel_path:path}/rename")
async def rename_file(
    rel_path: str,
    payload: RenameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename a file within its session directory (no path traversal)."""
    _session, full_path = await get_session_for_rel_path(rel_path, current_user, db)

    dst_name = Path(payload.new_name).name
    if not dst_name:
        raise HTTPException(status_code=400, detail="New file name is empty.")

    dst = (full_path.parent / dst_name).resolve()
    try:
        dst.relative_to(full_path.parent.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid new file name.")
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"'{dst_name}' already exists.")

    full_path.rename(dst)
    return {
        "status": "success",
        "message": f"Renamed {full_path.name} to {dst.name}.",
        "name": dst.name,
        "rel_path": rel_to_storage(dst),
    }
