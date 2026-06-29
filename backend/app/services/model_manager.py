"""First-run model download manager (desktop Part C / C2).

The desktop app ships *without* the ~700 MB of ML-potential checkpoints — they are
downloaded on first run into ``PRE_TRAINED_MODELS_DIR`` (Electron's userData/models).
This module is the single source of truth for *where each checkpoint comes from* and
runs the downloads in background threads with live, pollable progress.

It deliberately reuses the calculator factory's path maps and ``_has_checkpoint``
verification, so what we download is exactly what the simulations later load. The
two CLI scripts (``download_mace.py`` / ``download_mattersim_5m.py``) are kept as
thin operator tools but the URLs now live here, so there is one registry to maintain.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.services.simulation.calculator_factory import (
    _DEFAULT_MODELS_ROOT,
    _has_checkpoint,
    _MACE_MODEL_PATHS,
    _MATTERSIM_MODEL_PATHS,
)

# ── Download registry ─────────────────────────────────────────────────────────
# Each entry knows its calculator type, the folder the factory looks in, the file
# to write, the canonical release URL, an approximate size for pre-download UI,
# and whether it is part of the trimmed "recommended" default set.


@dataclass(frozen=True)
class ModelSpec:
    name: str
    type: str                # "mace" | "mattersim"
    rel_dir: str             # folder under PRE_TRAINED_MODELS_DIR
    filename: str            # checkpoint file written inside rel_dir
    url: str
    approx_mb: int
    recommended: bool        # part of the trimmed first-run default set
    suffixes: tuple[str, ...]  # for _has_checkpoint verification


_MACE_RELEASE = "https://github.com/ACEsuit/mace-mp/releases/download"
_MACE_FOUND = "https://github.com/ACEsuit/mace-foundations/releases/download"
_MSIM_RAW = "https://raw.githubusercontent.com/microsoft/mattersim/main/pretrained_models"

MODEL_REGISTRY: dict[str, ModelSpec] = {
    "mace-mp-0b3-medium": ModelSpec(
        "mace-mp-0b3-medium", "mace", _MACE_MODEL_PATHS["mace-mp-0b3-medium"],
        "mace-mp-0b3-medium.model",
        f"{_MACE_RELEASE}/mace_mp_0b3/mace-mp-0b3-medium.model",
        80, True, (".model", ".pt", ".ckpt"),
    ),
    "mace-mpa-0-medium": ModelSpec(
        "mace-mpa-0-medium", "mace", _MACE_MODEL_PATHS["mace-mpa-0-medium"],
        "mace-mpa-0-medium.model",
        f"{_MACE_RELEASE}/mace_mpa_0/mace-mpa-0-medium.model",
        80, False, (".model", ".pt", ".ckpt"),
    ),
    "mace-omat-0-medium": ModelSpec(
        "mace-omat-0-medium", "mace", _MACE_MODEL_PATHS["mace-omat-0-medium"],
        "mace-omat-0-medium.model",
        f"{_MACE_RELEASE}/mace_omat_0/mace-omat-0-medium.model",
        80, False, (".model", ".pt", ".ckpt"),
    ),
    "MACE-matpes-pbe-omat-ft": ModelSpec(
        "MACE-matpes-pbe-omat-ft", "mace", _MACE_MODEL_PATHS["MACE-matpes-pbe-omat-ft"],
        "MACE-matpes-pbe-omat-ft.model",
        f"{_MACE_FOUND}/mace_matpes_0/MACE-matpes-pbe-omat-ft.model",
        80, False, (".model", ".pt", ".ckpt"),
    ),
    "mattersim-v1.0.0-1M": ModelSpec(
        "mattersim-v1.0.0-1M", "mattersim", _MATTERSIM_MODEL_PATHS["mattersim-v1.0.0-1M"],
        "mattersim-v1.0.0-1M.pth",
        f"{_MSIM_RAW}/mattersim-v1.0.0-1M.pth",
        20, True, (".pth", ".pt", ".ckpt"),
    ),
    "mattersim-v1.0.0-5M": ModelSpec(
        "mattersim-v1.0.0-5M", "mattersim", _MATTERSIM_MODEL_PATHS["mattersim-v1.0.0-5M"],
        "mattersim-v1.0.0-5M.pth",
        f"{_MSIM_RAW}/mattersim-v1.0.0-5M.pth",
        95, False, (".pth", ".pt", ".ckpt"),
    ),
}


# ── Live progress state (in-memory, single backend process) ───────────────────


@dataclass
class _Progress:
    status: str = "absent"          # absent | downloading | present | error
    downloaded: int = 0
    total: int = 0                  # 0 until Content-Length is known
    error: Optional[str] = None


_LOCK = threading.Lock()
_PROGRESS: dict[str, _Progress] = {}


def _models_root() -> Path:
    """Resolve the models root *at call time* so env changes are honoured.

    ``calculator_factory._DEFAULT_MODELS_ROOT`` is captured at import; on desktop
    the Electron shell sets ``PRE_TRAINED_MODELS_DIR`` before the backend starts,
    so that import-time value is already correct. We keep the indirection here in
    case the env is set later (tests, dev).
    """
    return _DEFAULT_MODELS_ROOT


def _dest_path(spec: ModelSpec) -> Path:
    return _models_root() / spec.rel_dir / spec.filename


def is_present(spec: ModelSpec) -> bool:
    """True only if a real checkpoint file exists (not just an empty dir)."""
    return _has_checkpoint(_models_root() / spec.rel_dir, list(spec.suffixes))


def _download(spec: ModelSpec, progress_cb: Callable[[int, int], None]) -> None:
    """Stream a checkpoint to disk, reporting (downloaded, total) as it goes.

    Writes to a ``.part`` file and renames on success so a crash mid-download
    never leaves a half-file that ``_has_checkpoint`` would treat as present.
    """
    import requests

    dest = _dest_path(spec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    with requests.get(spec.url, stream=True, timeout=600,
                      headers={"Accept": "application/octet-stream"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        progress_cb(done, total)
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                progress_cb(done, total)

    # Guard against an HTML error page masquerading as a checkpoint.
    if tmp.stat().st_size < 1_000_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"downloaded file is only {tmp.stat().st_size} bytes — likely an "
            "error page, not the checkpoint"
        )
    tmp.replace(dest)


def _run_download(name: str) -> None:
    spec = MODEL_REGISTRY[name]

    def cb(done: int, total: int) -> None:
        with _LOCK:
            p = _PROGRESS[name]
            p.downloaded, p.total = done, total

    try:
        _download(spec, cb)
        with _LOCK:
            _PROGRESS[name].status = "present"
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        with _LOCK:
            p = _PROGRESS[name]
            p.status = "error"
            p.error = str(exc)


# ── Public API used by app/api/models.py ──────────────────────────────────────


def download_sync(name: str, force: bool = False) -> bool:
    """Blocking download used by the operator CLI scripts. Returns True if present.

    Prints simple progress to stdout. Skips an already-present checkpoint unless
    ``force``. Shares the exact same registry + writer as the desktop UI path.
    """
    spec = MODEL_REGISTRY[name]
    if is_present(spec) and not force:
        print(f"Already present: {_dest_path(spec)}")
        return True

    last_pct = -1

    def cb(done: int, total: int) -> None:
        nonlocal last_pct
        pct = int(done * 100 / total) if total else 0
        if pct != last_pct:
            mb = done / 1e6
            print(f"  {name}: {pct:3d}%  ({mb:.1f} MB)", end="\r", flush=True)
            last_pct = pct

    print(f"Downloading {name}\n  from {spec.url}\n  to   {_dest_path(spec)}")
    _download(spec, cb)
    print(f"\nDone: {_dest_path(spec)} ({_dest_path(spec).stat().st_size / 1e6:.1f} MB).")
    return True


def list_models() -> list[dict]:
    """Every known model with on-disk availability and live download progress."""
    out: list[dict] = []
    with _LOCK:
        for name, spec in MODEL_REGISTRY.items():
            prog = _PROGRESS.get(name)
            present = is_present(spec)
            # Reconcile: a finished download or a pre-existing file both read present.
            if present and (prog is None or prog.status != "downloading"):
                status = "present"
            elif prog is not None:
                status = prog.status
            else:
                status = "absent"
            out.append({
                "name": name,
                "type": spec.type,
                "recommended": spec.recommended,
                "approx_mb": spec.approx_mb,
                "exists": present,
                "status": status,
                "downloaded": prog.downloaded if prog else 0,
                "total": prog.total if prog else 0,
                "error": prog.error if prog else None,
            })
    return out


def resolve_names(selection) -> list[str]:
    """Map a request body into concrete model names.

    Accepts the literal strings ``"recommended"`` / ``"all"`` or an explicit list
    of model names; unknown names are dropped.
    """
    if selection in ("recommended", ["recommended"]):
        return [n for n, s in MODEL_REGISTRY.items() if s.recommended]
    if selection in ("all", ["all"]):
        return list(MODEL_REGISTRY.keys())
    if isinstance(selection, str):
        selection = [selection]
    return [n for n in (selection or []) if n in MODEL_REGISTRY]


def start_downloads(names: list[str]) -> list[str]:
    """Kick off background downloads for the given models; returns those queued.

    Already-present or already-downloading models are skipped so a double-click or
    a retry can't spawn duplicate threads writing the same file.
    """
    queued: list[str] = []
    with _LOCK:
        for name in names:
            spec = MODEL_REGISTRY[name]
            existing = _PROGRESS.get(name)
            if existing and existing.status == "downloading":
                continue
            if is_present(spec):
                _PROGRESS[name] = _Progress(status="present")
                continue
            _PROGRESS[name] = _Progress(status="downloading")
            queued.append(name)

    for name in queued:
        threading.Thread(target=_run_download, args=(name,), daemon=True).start()
    return queued
