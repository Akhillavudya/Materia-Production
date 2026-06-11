"""
backend/app/services/calculator_factory.py
===========================================
Returns an ASE calculator instance given a config dict.

Supported calculators
---------------------
  mace       — MACE-MP universal potential (default: mace-mp-0b3-medium)
  mattersim  — MatterSim universal potential (default: mattersim-v1.0.0-1M)

Usage
-----
    from app.services.calculator_factory import get_calculator

    calc = get_calculator({"type": "mace"})
    calc = get_calculator({"type": "mace", "model": "mace-omat-0-medium"})
    calc = get_calculator({"type": "mattersim"})
    calc = get_calculator({"type": "mattersim", "model": "mattersim-v1.0.0-5M"})

Model paths are resolved relative to the pre_trained_models/ directory
that sits at PRE_TRAINED_MODELS_DIR (env var) or the default below.
"""

import os
from pathlib import Path
from typing import Optional

# ── Model root ────────────────────────────────────────────────────────────────
# Matches the pre_trained_models/ folder visible in your project tree.
_DEFAULT_MODELS_ROOT = Path(
    os.environ.get(
        "PRE_TRAINED_MODELS_DIR",
        Path(__file__).resolve().parents[3] / "pre_trained_models",
    )
)

# ── Default models ────────────────────────────────────────────────────────────
# mace-mp-0b3-medium: latest stable universal potential, best default
# for general materials across the periodic table.
DEFAULT_MACE_MODEL      = "mace-mp-0b3-medium"
DEFAULT_MATTERSIM_MODEL = "mattersim-v1.0.0-1M"

# ── MACE model → relative path inside mace_models/ ───────────────────────────
_MACE_MODEL_PATHS: dict[str, str] = {
    "mace-mp-0b3-medium":      "mace_models/mace-mp-0b3-medium",
    "mace-mpa-0-medium":       "mace_models/mace-mpa-0-medium",
    "mace-omat-0-medium":      "mace_models/mace-omat-0-medium",
    "MACE-matpes-pbe-omat-ft": "mace_models/MACE-matpes-pbe-omat-ft",
}

# ── MatterSim model → relative path inside matterSim_models/ ─────────────────
_MATTERSIM_MODEL_PATHS: dict[str, str] = {
    "mattersim-v1.0.0-1M": "matterSim_models/mattersim-v1.0.0-1M",
    "mattersim-v1.0.0-5M": "matterSim_models/mattersim-v1.0.0-5M",
}


def _resolve_model_path(relative: str) -> Path:
    """Return absolute path; raise if missing."""
    p = _DEFAULT_MODELS_ROOT / relative
    if not p.exists():
        raise FileNotFoundError(
            f"Model not found at {p}. "
            f"Check PRE_TRAINED_MODELS_DIR or model name."
        )
    return p


# ── Public API ────────────────────────────────────────────────────────────────

def get_calculator(config: Optional[dict] = None):
    """
    Build and return an ASE calculator.

    Parameters
    ----------
    config : dict with keys:
        "type"   : "mace" | "mattersim"   (default: "mace")
        "model"  : model name string       (optional, uses DEFAULT_* if omitted)
        "device" : "cpu" | "cuda" | "mps"  (optional, auto-detected if omitted)

    Returns
    -------
    An ASE Calculator instance ready to attach to an Atoms object.

    Raises
    ------
    ValueError         if type is unknown
    FileNotFoundError  if model path does not exist
    ImportError        if required package is missing
    """
    cfg        = config or {}
    calc_type  = cfg.get("type", "mace").lower().strip()
    device     = cfg.get("device") or _auto_device()

    if calc_type == "mace":
        return _make_mace(cfg.get("model", DEFAULT_MACE_MODEL), device)

    elif calc_type == "mattersim":
        return _make_mattersim(cfg.get("model", DEFAULT_MATTERSIM_MODEL), device)

    else:
        raise ValueError(
            f"Unknown calculator type '{calc_type}'. "
            "Supported: mace, mattersim"
        )


def list_available_models() -> dict:
    """Return all model names grouped by type, with existence check."""
    result = {"mace": [], "mattersim": []}

    for name, rel in _MACE_MODEL_PATHS.items():
        p = _DEFAULT_MODELS_ROOT / rel
        result["mace"].append({"name": name, "exists": p.exists(), "path": str(p)})

    for name, rel in _MATTERSIM_MODEL_PATHS.items():
        p = _DEFAULT_MODELS_ROOT / rel
        result["mattersim"].append({"name": name, "exists": p.exists(), "path": str(p)})

    return result


# ── Private builders ──────────────────────────────────────────────────────────

def _make_mace(model_name: str, device: str):
    """Instantiate a MACE-MP calculator from a local checkpoint."""
    try:
        from mace.calculators import MACECalculator
    except ImportError:
        raise ImportError(
            "MACE is not installed. Run: pip install mace-torch"
        )

    rel     = _MACE_MODEL_PATHS.get(model_name)
    if rel is None:
        # Allow passing a raw path or an unrecognised alias
        model_path = Path(model_name)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Unknown MACE model '{model_name}'. "
                f"Available: {list(_MACE_MODEL_PATHS.keys())}"
            )
    else:
        model_path = _resolve_model_path(rel)

    # Locate the .model checkpoint file inside the model directory
    checkpoint = _find_checkpoint(model_path, suffixes=[".model", ".pt", ".ckpt"])

    print(f"[Calculator] MACE  model={model_name}  device={device}  checkpoint={checkpoint}")

    return MACECalculator(
        model_paths=str(checkpoint),
        device=device,
        default_dtype="float32",
    )


def _make_mattersim(model_name: str, device: str):
    """Instantiate a MatterSim calculator from a local checkpoint."""
    try:
        from mattersim.forcefield import MatterSimCalculator
    except ImportError:
        raise ImportError(
            "MatterSim is not installed. "
            "See: https://github.com/microsoft/mattersim"
        )

    rel = _MATTERSIM_MODEL_PATHS.get(model_name)
    if rel is None:
        model_path = Path(model_name)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Unknown MatterSim model '{model_name}'. "
                f"Available: {list(_MATTERSIM_MODEL_PATHS.keys())}"
            )
    else:
        model_path = _resolve_model_path(rel)

    checkpoint = _find_checkpoint(model_path, suffixes=[".pth", ".pt", ".ckpt"])

    print(f"[Calculator] MatterSim  model={model_name}  device={device}  checkpoint={checkpoint}")

    return MatterSimCalculator(
        load_path=str(checkpoint),
        device=device,
    )


def _find_checkpoint(model_dir: Path, suffixes: list[str]) -> Path:
    """
    Find the checkpoint file inside model_dir.
    If model_dir itself is a file, return it directly.
    Otherwise look for the first file matching any of the given suffixes.
    """
    if model_dir.is_file():
        return model_dir

    for suffix in suffixes:
        candidates = sorted(model_dir.rglob(f"*{suffix}"))
        if candidates:
            return candidates[0]

    raise FileNotFoundError(
        f"No checkpoint file ({', '.join(suffixes)}) found in {model_dir}"
    )


def _auto_device() -> str:
    """Detect best available device: cuda > mps > cpu."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"