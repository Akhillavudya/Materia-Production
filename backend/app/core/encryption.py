import os
from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet is None:
        raw = os.getenv("FIELD_ENCRYPTION_KEY", "")
        if raw:
            _fernet = Fernet(raw.encode())
    return _fernet


def encrypt_value(plaintext: str) -> str:
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(stored: str) -> str:
    f = _get_fernet()
    if f is None:
        return stored
    try:
        return f.decrypt(stored.encode()).decode()
    except (InvalidToken, Exception):
        # Legacy plaintext key stored before encryption was enabled.
        return stored
