import os
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet is None:
        raw = os.getenv("FIELD_ENCRYPTION_KEY", "")
        if raw:
            _fernet = Fernet(raw.encode())
    return _fernet


def _require_fernet() -> Fernet | None:
    """Return the Fernet, or raise in production if it is not configured.

    In production we must never fall back to plaintext, otherwise users' BYOK
    API keys would be written to the database in the clear. In dev we allow the
    plaintext fallback so local work runs without a key.
    """
    f = _get_fernet()
    if f is None and settings.is_production:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not set in production; refusing to handle API "
            "keys as plaintext. Generate one with: python -c "
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return f


def encrypt_value(plaintext: str) -> str:
    f = _require_fernet()
    if f is None:
        return plaintext  # dev-only fallback
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(stored: str) -> str:
    f = _require_fernet()
    if f is None:
        return stored  # dev-only fallback
    try:
        return f.decrypt(stored.encode()).decode()
    except InvalidToken:
        # Legacy plaintext value stored before encryption was enabled (dev/migration).
        return stored
