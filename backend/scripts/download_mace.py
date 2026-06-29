"""
backend/scripts/download_mace.py
================================
Fetch the official **MACE foundation** checkpoints into the runtime model mount.

This is now a thin operator wrapper over ``app.services.model_manager`` — the
download URLs, sizes and destination layout live there (one registry shared with
the desktop first-run UI), so this script just maps short aliases and calls it.

Like POTCAR / MatterSim, this is a *runtime* download — the checkpoints are never
baked into the image or committed (see the PRE_TRAINED_MODELS_DIR convention).

Usage
-----
    python backend/scripts/download_mace.py                  # all missing models
    python backend/scripts/download_mace.py --model mpa      # one variant
    python backend/scripts/download_mace.py --all --force    # re-download everything
    PRE_TRAINED_MODELS_DIR=/data/models python backend/scripts/download_mace.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import model_manager  # noqa: E402

# Short alias → registry model name.
_ALIASES = {
    "mpa":    "mace-mpa-0-medium",
    "omat":   "mace-omat-0-medium",
    "matpes": "MACE-matpes-pbe-omat-ft",
    "mp0b3":  "mace-mp-0b3-medium",
}
_ALL = [n for n, s in model_manager.MODEL_REGISTRY.items() if s.type == "mace"]
# The advertised-but-usually-missing extras (mp-0b3 ships with the spike).
_DEFAULT_TARGETS = ["mace-mpa-0-medium", "mace-omat-0-medium", "MACE-matpes-pbe-omat-ft"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Download MACE foundation checkpoint(s).")
    ap.add_argument("--model", choices=sorted(_ALIASES), default=None,
                    help="fetch a single variant (mpa/omat/matpes/mp0b3)")
    ap.add_argument("--all", action="store_true",
                    help="fetch all four registry models (incl. mp-0b3)")
    ap.add_argument("--force", action="store_true", help="re-download if present")
    args = ap.parse_args()

    if args.model:
        targets = [_ALIASES[args.model]]
    elif args.all:
        targets = _ALL
    else:
        targets = _DEFAULT_TARGETS

    rc = 0
    for name in targets:
        try:
            model_manager.download_sync(name, force=args.force)
        except Exception as exc:  # noqa: BLE001
            print(f"Download failed for {name}: {exc}", file=sys.stderr)
            rc = 1
    if rc == 0:
        print("\nAll requested MACE models present. "
              "Verify with: python backend/scripts/test_models.py")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
