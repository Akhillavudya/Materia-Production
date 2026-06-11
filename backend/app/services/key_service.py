"""User-scoped API key loading and resolution."""

import os

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_value
from app.repositories import api_key_repository

KEY_ENV_MAP = {
    "mp": "MP_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


async def load_user_keys_into_env(user_id: int, db: AsyncSession) -> None:
    """Load only the current user's saved API keys into os.environ."""
    keys = await api_key_repository.list_for_user(db, user_id)
    for k in keys:
        env_name = KEY_ENV_MAP.get(k.service)
        if env_name and k.key_value:
            os.environ[env_name] = decrypt_value(k.key_value)


async def get_key(service: str, user_id: int, db: AsyncSession) -> str | None:
    """Return the decrypted key value for one authenticated user, or None."""
    row = await api_key_repository.get(db, user_id=user_id, service=service)
    return decrypt_value(row.key_value) if row else None
