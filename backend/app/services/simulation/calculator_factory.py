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
import re
from pathlib import Path
from typing import Optional

# ── Model root ────────────────────────────────────────────────────────────────
# Matches the pre_trained_models/ folder visible in your project tree.
_DEFAULT_MODELS_ROOT = Path(
    os.environ.get(
        "PRE_TRAINED_MODELS_DIR",
        Path(__file__).resolve().parents[4] / "pre_trained_models",
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

# Supported calculator types and their default model.
SUPPORTED_CALCULATORS: dict[str, str] = {
    "mace":      DEFAULT_MACE_MODEL,
    "mattersim": DEFAULT_MATTERSIM_MODEL,
}

# ── Natural-language aliases → (calculator type, concrete model) ─────────────
# Single source of truth shared by `normalize_calculator` (routing) and
# `list_models` (discovery), so what we advertise is exactly what we accept.
# Keys are matched case-insensitively against a whitespace/underscore-normalised
# form of the user/LLM-supplied string.
MODEL_ALIASES: dict[str, tuple[str, str]] = {
    # MACE
    "mace":                     ("mace", "mace-mp-0b3-medium"),
    "mace mp":                  ("mace", "mace-mp-0b3-medium"),
    "mace-mp":                  ("mace", "mace-mp-0b3-medium"),
    "mace mp 0b3":              ("mace", "mace-mp-0b3-medium"),
    "mace-mp-0b3-medium":       ("mace", "mace-mp-0b3-medium"),
    "mace mpa":                 ("mace", "mace-mpa-0-medium"),
    "mace-mpa":                 ("mace", "mace-mpa-0-medium"),
    "mace-mpa-0-medium":        ("mace", "mace-mpa-0-medium"),
    "mace omat":                ("mace", "mace-omat-0-medium"),
    "mace-omat":                ("mace", "mace-omat-0-medium"),
    "mace-omat-0-medium":       ("mace", "mace-omat-0-medium"),
    "mace matpes":              ("mace", "MACE-matpes-pbe-omat-ft"),
    "mace-matpes":              ("mace", "MACE-matpes-pbe-omat-ft"),
    "mace-matpes-pbe-omat-ft":  ("mace", "MACE-matpes-pbe-omat-ft"),
    # MatterSim
    "mattersim":                ("mattersim", "mattersim-v1.0.0-1M"),
    "mattersim small":          ("mattersim", "mattersim-v1.0.0-1M"),
    "mattersim 1m":             ("mattersim", "mattersim-v1.0.0-1M"),
    "mattersim-v1.0.0-1m":      ("mattersim", "mattersim-v1.0.0-1M"),
    "mattersim large":          ("mattersim", "mattersim-v1.0.0-5M"),
    "mattersim big":            ("mattersim", "mattersim-v1.0.0-5M"),
    "mattersim 5m":             ("mattersim", "mattersim-v1.0.0-5M"),
    "mattersim-v1.0.0-5m":      ("mattersim", "mattersim-v1.0.0-5M"),
}

# Human-friendly alias hints surfaced by list_models, keyed by concrete model name.
MODEL_ALIAS_HINTS: dict[str, list[str]] = {
    "mace-mp-0b3-medium":      ["mace", "mace-mp"],
    "mace-mpa-0-medium":       ["mace-mpa"],
    "mace-omat-0-medium":      ["mace-omat"],
    "MACE-matpes-pbe-omat-ft": ["mace-matpes"],
    "mattersim-v1.0.0-1M":     ["mattersim", "mattersim small", "1m"],
    "mattersim-v1.0.0-5M":     ["mattersim large", "5m"],
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


def _norm_key(s: str) -> str:
    """Collapse whitespace/underscores and lowercase for alias matching."""
    return re.sub(r"[\s_]+", " ", str(s).strip().lower())


# Per-type known model names (for validating an explicit model string).
_MODELS_BY_TYPE: dict[str, dict[str, str]] = {
    "mace":      _MACE_MODEL_PATHS,
    "mattersim": _MATTERSIM_MODEL_PATHS,
}


def normalize_calculator(
    calc_type: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Resolve a (type, model) request into a concrete calculator config.

    Tolerant of natural-language model names ("MatterSim Large", "MACE-MP") and
    always fills a concrete default model so the selection can be surfaced.

    Returns one of:
      - ``{"type": <type>, "model": <model>}`` on success, or
      - ``{"unsupported": True, "requested": <str>, "supported": [...]}`` when the
        requested calculator type is not MACE/MatterSim (caller turns this into a
        friendly message instead of enqueueing a doomed job).
    """
    ctype = (calc_type or "mace").strip()
    ctype_norm = _norm_key(ctype)

    # 1. Try alias lookups, most specific first.
    candidates: list[str] = []
    if model:
        candidates.append(_norm_key(model))
        candidates.append(_norm_key(f"{ctype} {model}"))
    candidates.append(ctype_norm)
    for key in candidates:
        hit = MODEL_ALIASES.get(key)
        if hit:
            return {"type": hit[0], "model": hit[1]}

    # 2. Known base type with an explicit (or missing) model name.
    base = ctype_norm
    if base not in SUPPORTED_CALCULATORS:
        # maybe the type itself is a model name like "mattersim-v1.0.0-5M"
        for t, paths in _MODELS_BY_TYPE.items():
            if ctype in paths:
                base = t
                model = model or ctype
                break

    if base in SUPPORTED_CALCULATORS:
        known = _MODELS_BY_TYPE[base]
        if model and model in known:
            return {"type": base, "model": model}
        # Unknown/blank model for a supported type → fall back to its default.
        return {"type": base, "model": SUPPORTED_CALCULATORS[base]}

    # 3. Unsupported calculator type.
    return {
        "unsupported": True,
        "requested": calc_type,
        "supported": list(SUPPORTED_CALCULATORS.keys()),
    }


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