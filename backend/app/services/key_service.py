"""User-scoped API key loading and resolution.

A user may store **several** keys for one service (e.g. multiple free Gemini
keys) to multiply their daily quota. All keys for a service share a single
`api_keys` row: the encrypted tokens are newline-joined in `key_value`. On load
the first key populates the singular env var (``GEMINI_API_KEY``) and the whole
list populates the plural one (``GEMINI_API_KEYS``) that ``agent/providers/
_keypool.py`` rotates through when a key hits its rate limit (429).

Backward compatible: a legacy single-token row unpacks to a one-item list.
"""

import os

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_value, encrypt_value
from app.repositories import api_key_repository

KEY_ENV_MAP = {
    "mp": "MP_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Encrypted tokens are urlsafe-base64 (Fernet) so a newline never collides.
_DELIM = "\n"


def _plural_env(service: str) -> str | None:
    """Env var the key-pool reads for extra keys, e.g. ``GEMINI_API_KEYS``."""
    base = KEY_ENV_MAP.get(service)
    return f"{base}S" if base else None


def _pack(tokens: list[str]) -> str:
    return _DELIM.join(tokens)


def _unpack(packed: str | None) -> list[str]:
    return [t for t in (packed or "").split(_DELIM) if t.strip()]


def _mask(raw: str) -> str:
    """A never-reversible hint so the user can tell their keys apart."""
    tail = raw[-4:] if len(raw) >= 4 else raw
    return f"••••{tail}"


def _inject(service: str, raw_keys: list[str]) -> None:
    """Publish a user's decrypted keys into the process env for this request.

    Singular env = first key (what non-pooled callers like MP read); plural env
    = the full comma-joined pool the LLM key-rotation walks. When the user has
    no keys we only drop the singular and leave any operator-supplied shared
    plural pool intact as a fallback.
    """
    env = KEY_ENV_MAP.get(service)
    if not env:
        return
    plural = _plural_env(service)
    if raw_keys:
        os.environ[env] = raw_keys[0]
        if plural:
            os.environ[plural] = ",".join(raw_keys)
    else:
        os.environ.pop(env, None)


async def _raw_keys(service: str, user_id: int, db: AsyncSession) -> list[str]:
    row = await api_key_repository.get(db, user_id=user_id, service=service)
    return [decrypt_value(t) for t in _unpack(row.key_value)] if row else []


async def load_user_keys_into_env(user_id: int, db: AsyncSession) -> None:
    """Load all of the current user's saved API keys into os.environ."""
    rows = await api_key_repository.list_for_user(db, user_id)
    for r in rows:
        _inject(r.service, [decrypt_value(t) for t in _unpack(r.key_value)])


async def get_key(service: str, user_id: int, db: AsyncSession) -> str | None:
    """Return the user's first decrypted key for a service, or None."""
    keys = await _raw_keys(service, user_id, db)
    return keys[0] if keys else None


async def add_key(service: str, raw_key: str, user_id: int, db: AsyncSession) -> int:
    """Append one key to the user's pool for a service. Returns the new count."""
    row = await api_key_repository.get(db, user_id=user_id, service=service)
    tokens = _unpack(row.key_value) if row else []
    tokens.append(encrypt_value(raw_key))
    await api_key_repository.upsert(
        db, user_id=user_id, service=service, key_value=_pack(tokens))
    _inject(service, [decrypt_value(t) for t in tokens])
    return len(tokens)


async def list_key_meta(service: str, user_id: int, db: AsyncSession) -> list[dict]:
    """Masked hints for each stored key (never the full value)."""
    keys = await _raw_keys(service, user_id, db)
    return [{"index": i, "hint": _mask(k)} for i, k in enumerate(keys)]


async def delete_key_at(service: str, index: int, user_id: int, db: AsyncSession) -> int:
    """Remove one key by its position. Drops the row when the last key goes."""
    row = await api_key_repository.get(db, user_id=user_id, service=service)
    tokens = _unpack(row.key_value) if row else []
    if 0 <= index < len(tokens):
        tokens.pop(index)
    if tokens:
        await api_key_repository.upsert(
            db, user_id=user_id, service=service, key_value=_pack(tokens))
    else:
        await api_key_repository.delete(db, user_id=user_id, service=service)
    _inject(service, [decrypt_value(t) for t in tokens])
    return len(tokens)


async def delete_all(service: str, user_id: int, db: AsyncSession) -> None:
    """Remove every key a user has for a service."""
    await api_key_repository.delete(db, user_id=user_id, service=service)
    _inject(service, [])
