"""API-key manager endpoints."""

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.encryption import encrypt_value
from app.database.db import get_db
from app.database.models import User
from app.repositories import api_key_repository
from app.schemas.key import ApiKeyIn, ApiKeyOut
from app.services.key_service import KEY_ENV_MAP

router = APIRouter()


@router.post("/keys", response_model=ApiKeyOut)
async def save_api_key(
    body: ApiKeyIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = body.service.strip().lower()
    if not service:
        raise HTTPException(status_code=400, detail="Service is required")
    if not body.key_value.strip():
        raise HTTPException(status_code=400, detail="Key cannot be empty")

    encrypted = encrypt_value(body.key_value.strip())
    await api_key_repository.upsert(db, user_id=current_user.id,
                                    service=service, key_value=encrypted)

    # Inject immediately so same-process tool calls can use it.
    env_name = KEY_ENV_MAP.get(service)
    if env_name:
        os.environ[env_name] = body.key_value.strip()

    return ApiKeyOut(service=service, exists=True)


@router.get("/keys/{service}", response_model=ApiKeyOut)
async def check_api_key(
    service: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = service.strip().lower()
    existing = await api_key_repository.get(db, user_id=current_user.id, service=service)
    return ApiKeyOut(service=service, exists=existing is not None)
