"""BYOK key encryption at rest (Step 1) — round-trip correctness (Step 9).

When a Fernet key is configured, a stored API key must be ciphertext on disk and
decrypt back to the exact original. This is what keeps students' pasted Gemini
keys out of the database in the clear.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", key)

    from app.core import encryption

    # Reset the module-level cache so it picks up the freshly-set test key.
    monkeypatch.setattr(encryption, "_fernet", None)

    plaintext = "gsk_super_secret_byok_key"
    token = encryption.encrypt_value(plaintext)

    assert token != plaintext  # actually encrypted, not stored in the clear
    assert encryption.decrypt_value(token) == plaintext

    # Reset again so the cached test Fernet doesn't leak into other tests.
    monkeypatch.setattr(encryption, "_fernet", None)
