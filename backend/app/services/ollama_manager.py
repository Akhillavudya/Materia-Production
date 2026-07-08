"""Offline chat-brain (Ollama) manager — desktop Part C.

The MACE/MatterSim checkpoints in ``model_manager`` are the simulation *calculators*.
This module is the parallel manager for the offline *brain*: the local Ollama LLM
(``qwen3:14b``) the agent falls back to when there is no Gemini key / no network.

Unlike an ML checkpoint, the brain is not a file we stream to disk — it lives inside
a separately-installed **Ollama server**. So here we (1) check that server is
reachable, (2) check whether the model is already pulled, and (3) drive
``ollama pull`` in a background thread with pollable progress, exactly like
``model_manager`` so the desktop UI can poll both the same way.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ── Live pull progress (in-memory, single backend process) ────────────────────


@dataclass
class _Progress:
    status: str = "absent"          # absent | downloading | present | error
    downloaded: int = 0             # bytes of the current layer
    total: int = 0                  # 0 until the layer size is known
    phase: str = ""                 # human phase, e.g. "pulling manifest"
    error: Optional[str] = None


_LOCK = threading.Lock()
_PROGRESS = _Progress()


def _client():
    """A sync Ollama client bound to the configured host (import lazily)."""
    from ollama import Client
    return Client(host=settings.ollama_base_url)


def server_reachable() -> tuple[bool, list[str]]:
    """(server_up, [installed model names]). Never raises — a down server is False."""
    try:
        resp = _client().list()
        models = getattr(resp, "models", None) or resp.get("models", [])
        names: list[str] = []
        for m in models:
            n = getattr(m, "model", None) or (m.get("model") if isinstance(m, dict) else None)
            if n:
                names.append(n)
        return True, names
    except Exception as exc:  # noqa: BLE001 — any failure = "not reachable"
        logger.debug("[ollama] server not reachable: %s", exc)
        return False, []


def _model_present(installed: list[str]) -> bool:
    """True if the configured model is pulled. Ollama tags default to ``:latest``,
    so we match on the bare name too (``qwen3`` matches ``qwen3:latest``)."""
    want = settings.ollama_model
    want_base = want.split(":")[0]
    for n in installed:
        if n == want or n.split(":")[0] == want_base:
            return True
    return False


def status() -> dict:
    """Full offline-brain state for the UI: server up, model present, live pull."""
    up, installed = server_reachable()
    with _LOCK:
        p = _PROGRESS
        present = _model_present(installed) if up else False
        # A finished pull or a pre-existing model both read "present".
        if present and p.status != "downloading":
            st = "present"
        elif not up:
            st = "no_server"
        else:
            st = p.status
        return {
            "model": settings.ollama_model,
            "server": up,
            "present": present,
            "status": st,
            "downloaded": p.downloaded,
            "total": p.total,
            "phase": p.phase,
            "error": p.error,
        }


def _run_pull(model: str) -> None:
    """Blocking ``ollama pull`` streamed into the shared progress record."""
    try:
        for prog in _client().pull(model, stream=True):
            st = getattr(prog, "status", None) or (
                prog.get("status") if isinstance(prog, dict) else "")
            completed = getattr(prog, "completed", None) or (
                prog.get("completed") if isinstance(prog, dict) else 0) or 0
            total = getattr(prog, "total", None) or (
                prog.get("total") if isinstance(prog, dict) else 0) or 0
            with _LOCK:
                _PROGRESS.phase = st or _PROGRESS.phase
                _PROGRESS.downloaded = int(completed)
                _PROGRESS.total = int(total)
        with _LOCK:
            _PROGRESS.status = "present"
            _PROGRESS.error = None
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        logger.warning("[ollama] pull failed: %s", exc)
        with _LOCK:
            _PROGRESS.status = "error"
            _PROGRESS.error = str(exc)


def start_pull() -> dict:
    """Kick off ``ollama pull`` in the background; returns the resulting status.

    Refuses when the server is down (nothing to pull into) and is idempotent — a
    double-click while a pull is in flight, or when the model is already present,
    does not spawn a second thread.
    """
    up, installed = server_reachable()
    if not up:
        return {"queued": False, "reason": "no_server", **status()}
    if _model_present(installed):
        with _LOCK:
            _PROGRESS.status = "present"
        return {"queued": False, "reason": "present", **status()}

    with _LOCK:
        if _PROGRESS.status == "downloading":
            return {"queued": False, "reason": "already_downloading", **status()}
        _PROGRESS.status = "downloading"
        _PROGRESS.downloaded = 0
        _PROGRESS.total = 0
        _PROGRESS.phase = "starting"
        _PROGRESS.error = None

    threading.Thread(target=_run_pull, args=(settings.ollama_model,),
                     daemon=True).start()
    return {"queued": True, "reason": "started", **status()}
