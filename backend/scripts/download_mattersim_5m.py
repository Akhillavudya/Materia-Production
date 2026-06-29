"""
backend/scripts/download_mattersim_5m.py
========================================
Fetch the official **MatterSim** checkpoints into the runtime model mount.

This is now a thin operator wrapper over ``app.services.model_manager`` — the
download URL and destination layout live there (one registry shared with the
desktop first-run UI), so this script just maps the 1M/5M aliases and calls it.

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

from app.services import model_manager  # noqa: E402

# Short alias → registry model name.
_ALIASES = {"1M": "mattersim-v1.0.0-1M", "5M": "mattersim-v1.0.0-5M"}


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
        try:
            model_manager.download_sync(_ALIASES[alias], force=args.force)
        except Exception as exc:  # noqa: BLE001
            print(f"Download failed for {alias}: {exc}", file=sys.stderr)
            rc = 1
    if rc == 0:
        print("Verify with: python backend/scripts/test_models.py")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
