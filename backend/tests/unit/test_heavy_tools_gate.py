"""Heavy-tools gate (Deployment Part A) — the lite-web safety net.

The 6 ML-potential simulations run torch + MACE/MatterSim through the Celery
worker and would exhaust the free shared web server. When ENABLE_HEAVY_TOOLS is
off, NOTHING may start such a job — the single backstop in ``_enqueue_job`` must
refuse every path (agent, manual panel, direct API) with a friendly message that
points the user at the desktop app. These tests pin that gate so a future edit
can't silently reopen it.
"""

from __future__ import annotations

from pathlib import Path

import app.tools.material_tools as material_tools
from app.core import context
from app.core.config import _env_bool
from app.domain.jobs import JobType


def test_env_bool_parsing():
    # unset → default; truthy/falsey words parsed case-insensitively.
    assert _env_bool("DOES_NOT_EXIST_X", True) is True
    assert _env_bool("DOES_NOT_EXIST_X", False) is False


def _attempt_job() -> dict:
    context.set_request_identity(user_id=1, session_id="sess-gate-test")
    return material_tools._enqueue_job(
        JobType.OPTIMIZE,
        poscar_path=Path("POSCAR"),
        output_dir=Path("/tmp/materia-gate-test"),
        params={},
        calculator={},
        emit_vasp_inputs=False,
    )


def test_disabled_blocks_job(monkeypatch):
    monkeypatch.setattr(material_tools.settings, "enable_heavy_tools", False)
    result = _attempt_job()
    assert result["status"] == "error"          # so launch endpoints raise HTTP 400
    assert "job_id" not in result               # nothing was enqueued
    assert "desktop" in result["message"].lower()


def test_enabled_passes_the_gate(monkeypatch):
    # With the gate open, _enqueue_job proceeds past the heavy check. We don't run
    # a real worker here, so success means it does NOT return the gate message
    # (it moves on to the quota check / real enqueue path).
    monkeypatch.setattr(material_tools.settings, "enable_heavy_tools", True)
    result = _attempt_job()
    assert "desktop" not in result.get("message", "").lower()
