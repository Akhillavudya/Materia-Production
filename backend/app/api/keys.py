from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.db import get_db
from app.database.models import ApiKey

router = APIRouter()


class ApiKeyIn(BaseModel):
    service:   str    # "mp", "openai", etc.
    key_value: str


class ApiKeyOut(BaseModel):
    service: str
    exists:  bool     # never send the actual key back to the frontend


# ── POST /api/keys — save or update a key ────────────────────────────────────

@router.post('/keys', response_model=ApiKeyOut)
async def save_api_key(body: ApiKeyIn, db: AsyncSession = Depends(get_db)):
    if not body.key_value.strip():
        raise HTTPException(status_code=400, detail='Key cannot be empty')

    result = await db.execute(
        select(ApiKey).where(ApiKey.service == body.service)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.key_value = body.key_value.strip()
    else:
        db.add(ApiKey(service=body.service, key_value=body.key_value.strip()))

    await db.commit()

    # also set it in the current process env so tools can use it immediately
    import os
    key_env_map = {
        'mp':       'MP_API_KEY',
        'openai':   'OPENAI_API_KEY',
        'anthropic':'ANTHROPIC_API_KEY',
    }
    env_name = key_env_map.get(body.service)
    if env_name:
        os.environ[env_name] = body.key_value.strip()

    return ApiKeyOut(service=body.service, exists=True)


# ── GET /api/keys/{service} — check if a key exists ─────────────────────────

@router.get('/keys/{service}', response_model=ApiKeyOut)
async def check_api_key(service: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiKey).where(ApiKey.service == service)
    )
    existing = result.scalar_one_or_none()
    return ApiKeyOut(service=service, exists=existing is not None)