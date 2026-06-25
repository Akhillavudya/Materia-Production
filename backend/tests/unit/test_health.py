"""Health endpoint + security headers (Steps 7 & 8) — wired-up smoke test.

A plain ``TestClient`` (no startup events, no DB needed) confirms ``/health`` is
reachable and that the hardening headers + request id ride on every response.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_security_headers_present():
    r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Request-ID")  # request-id middleware stamped it
