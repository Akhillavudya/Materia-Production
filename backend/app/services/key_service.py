import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.models import ApiKey

# maps service name → environment variable name
KEY_ENV_MAP = {
    'mp':        'MP_API_KEY',
    'openai':    'OPENAI_API_KEY',
    'anthropic': 'ANTHROPIC_API_KEY',
}

async def load_keys_into_env(db: AsyncSession):
    """
    On startup, load all saved API keys from the database
    into os.environ so tools can find them via os.getenv().
    Called once from main.py startup event.
    """
    result = await db.execute(select(ApiKey))
    keys = result.scalars().all()

    for k in keys:
        env_name = KEY_ENV_MAP.get(k.service)
        if env_name and k.key_value:
            os.environ[env_name] = k.key_value
            print(f'[Materia] Loaded API key for service: {k.service}')

async def get_key(service: str, db: AsyncSession) -> str | None:
    """
    Get a key value from the database.
    Returns None if not found.
    """
    result = await db.execute(
        select(ApiKey).where(ApiKey.service == service)
    )
    row = result.scalar_one_or_none()
    return row.key_value if row else None