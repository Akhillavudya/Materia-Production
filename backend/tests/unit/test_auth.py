"""Auth primitives — password hashing & JWT issue/verify (Step 9).

These guard the login path: a wrong password must fail, a tampered or expired
token must be rejected. If a refactor ever breaks token signing, this trips first.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)


def test_password_hash_is_not_plaintext_and_verifies():
    secret = "correct horse battery staple"
    hashed = get_password_hash(secret)
    assert hashed != secret
    assert verify_password(secret, hashed)
    assert not verify_password("wrong password", hashed)


def test_jwt_roundtrip_preserves_subject():
    token = create_access_token({"sub": "42"})
    payload = decode_access_token(token)
    assert payload["sub"] == "42"


def test_tampered_jwt_is_rejected():
    token = create_access_token({"sub": "42"})
    with pytest.raises(HTTPException) as exc:
        decode_access_token(token + "tampered")
    assert exc.value.status_code == 401


def test_expired_jwt_is_rejected():
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(HTTPException) as exc:
        decode_access_token(token)
    assert exc.value.status_code == 401
