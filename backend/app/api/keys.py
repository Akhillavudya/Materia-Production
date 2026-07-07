"""API-key manager endpoints.

A user can pool several keys per service; the LLM key-rotation cycles through
them when one hits its rate limit. POST appends, DELETE /{service}/{index}
removes one, DELETE /{service} clears all.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database.db import get_db
from app.database.models import User
from app.schemas.key import ApiKeyIn, ApiKeyOut, KeyHint
from app.services import key_service

router = APIRouter()


async def _service_out(service: str, user_id: int, db: AsyncSession) -> ApiKeyOut:
    """Build the response for one service from its stored key hints."""
    meta = await key_service.list_key_meta(service, user_id, db)
    return ApiKeyOut(
        service=service,
        exists=bool(meta),
        count=len(meta),
        keys=[KeyHint(**m) for m in meta],
    )


@router.post("/keys", response_model=ApiKeyOut)
async def save_api_key(
    body: ApiKeyIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Append a key to the user's pool for a service."""
    service = body.service.strip().lower()
    if not service:
        raise HTTPException(status_code=400, detail="Service is required")
    if not body.key_value.strip():
        raise HTTPException(status_code=400, detail="Key cannot be empty")

    await key_service.add_key(service, body.key_value.strip(), current_user.id, db)
    return await _service_out(service, current_user.id, db)


@router.get("/keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List each service with its pooled key count and masked hints."""
    return [
        await _service_out(svc, current_user.id, db)
        for svc in key_service.KEY_ENV_MAP
    ]


@router.get("/keys/{service}", response_model=ApiKeyOut)
async def check_api_key(
    service: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _service_out(service.strip().lower(), current_user.id, db)


@router.delete("/keys/{service}/{index}", response_model=ApiKeyOut)
async def delete_one_api_key(
    service: str,
    index: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a single key from the pool by its position."""
    service = service.strip().lower()
    await key_service.delete_key_at(service, index, current_user.id, db)
    return await _service_out(service, current_user.id, db)


@router.delete("/keys/{service}", response_model=ApiKeyOut)
async def delete_api_key(
    service: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove every key the user has for a service."""
    service = service.strip().lower()
    await key_service.delete_all(service, current_user.id, db)
    return ApiKeyOut(service=service, exists=False, count=0, keys=[])
