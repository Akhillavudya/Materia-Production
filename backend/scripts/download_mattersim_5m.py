"""
backend/scripts/download_mattersim_5m.py
========================================
Fetch the official **MatterSim large (5M)** checkpoint into the runtime model mount.

MatterSim publishes its pretrained checkpoints in the Microsoft GitHub repo. The
5M model is the "large" variant our registry already references
(``calculator_factory._MATTERSIM_MODEL_PATHS["mattersim-v1.0.0-5M"]`` and the
``"mattersim large"`` alias). We drop the ``.pth`` where ``_find_checkpoint`` will
discover it.

Like POTCAR / the other models, this is a *runtime* download — the checkpoint is
never baked into the image or committed (see PRE_TRAINED_MODELS_DIR convention).

Usage
-----
    python backend/scripts/download_mattersim_5m.py                 # 5M (large)
    python backend/scripts/download_mattersim_5m.py --model 1M      # 1M (small)
    python backend/scripts/download_mattersim_5m.py --all           # both
    PRE_TRAINED_MODELS_DIR=/data/models python backend/scripts/download_mattersim_5m.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.simulation.calculator_factory import (  # noqa: E402
    _DEFAULT_MODELS_ROOT,
    _MATTERSIM_MODEL_PATHS,
)

_GITHUB_PREFIX = (
    "https://raw.githubusercontent.com/microsoft/mattersim/main/pretrained_models/"
)
# Short alias → full model name in the registry.
_ALIASES = {"1M": "mattersim-v1.0.0-1M", "5M": "mattersim-v1.0.0-5M"}


def _download_one(model_name: str, force: bool = False) -> int:
    rel = _MATTERSIM_MODEL_PATHS[model_name]
    dest_dir = _DEFAULT_MODELS_ROOT / rel
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{model_name}.pth"
    url = _GITHUB_PREFIX + f"{model_name}.pth"

    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"Already present: {dest}")
        return 0

    try:
        import requests
        with requests.get(url, stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
    except Exception as exc:  # noqa: BLE001
        print(f"Download failed for {model_name}: {exc}", file=sys.stderr)
        return 1

    size_mb = dest.stat().st_size / 1e6
    if size_mb < 1:
        print(f"WARNING: {dest.name} is only {size_mb:.2f} MB — likely an error "
              f"page, not the checkpoint.", file=sys.stderr)
        return 1
    print(f"Done: {dest} ({size_mb:.1f} MB).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Download MatterSim checkpoint(s).")
    ap.add_argument("--model", default="5M", choices=["1M", "5M"],
                    help="which variant to fetch (default 5M / large)")
    ap.add_argument("--all", action="store_true", help="fetch both 1M and 5M")
    ap.add_argument("--force", action="store_true", help="re-download if present")
    args = ap.parse_args()

    targets = ["1M", "5M"] if args.all else [args.model]
    rc = 0
    for alias in targets:
        rc |= _download_one(_ALIASES[alias], force=args.force)
    if rc == 0:
        print("Verify with: python backend/scripts/test_models.py")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
