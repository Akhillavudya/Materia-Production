"""Production fail-fast guards (Steps 1, 3, 5, 8) — the boot safety net (Step 9).

``_validate_production`` is the function that refuses to start the server with a
weak secret, no Postgres, a wildcard CORS origin, or an unusable signup config.
These tests pin each refusal so a future edit can't silently weaken the gate.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings, _validate_production

_GOOD_JWT = "x" * 40  # non-placeholder, >= 32 chars
_GOOD_FERNET = Fernet.generate_key().decode()
_GOOD_DB = "postgresql://user:pass@host:5432/materia"


def _prod_settings(**overrides) -> Settings:
    base = dict(
        env="production",
        jwt_secret_key=_GOOD_JWT,
        field_encryption_key=_GOOD_FERNET,
        database_url_env=_GOOD_DB,
        signup_mode="closed",
        allowed_origins=["https://materia.example.com"],
    )
    base.update(overrides)
    return Settings(**base)


def test_good_production_config_passes():
    _validate_production(_prod_settings())  # must not raise


def test_weak_jwt_secret_rejected():
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        _validate_production(_prod_settings(jwt_secret_key="key"))


def test_missing_encryption_key_rejected():
    with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY"):
        _validate_production(_prod_settings(field_encryption_key=""))


def test_non_postgres_database_rejected():
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        _validate_production(_prod_settings(database_url_env=None))


def test_wildcard_cors_rejected():
    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        _validate_production(_prod_settings(allowed_origins=["*"]))


def test_invite_mode_without_codes_rejected():
    with pytest.raises(RuntimeError, match="INVITE_CODES"):
        _validate_production(_prod_settings(signup_mode="invite", invite_codes=[]))
