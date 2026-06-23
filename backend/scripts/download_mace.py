"""
backend/scripts/download_mace.py
================================
Fetch the official **MACE foundation** checkpoints into the runtime model mount.

The calculator factory advertises four MACE models but ships only
``mace-mp-0b3-medium``; the other three dirs are empty. This script downloads the
missing ``.model`` checkpoints from the canonical ACEsuit foundation-model releases
and drops them where ``_find_checkpoint`` will discover them
(``calculator_factory._MACE_MODEL_PATHS``).

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

from app.services.simulation.calculator_factory import (  # noqa: E402
    _DEFAULT_MODELS_ROOT,
    _MACE_MODEL_PATHS,
)

# Official ACEsuit foundation-model release assets (the same URLs the `mace`
# package's foundations_models loader uses). Short alias → full registry name.
_ALIASES = {
    "mpa":    "mace-mpa-0-medium",
    "omat":   "mace-omat-0-medium",
    "matpes": "MACE-matpes-pbe-omat-ft",
    "mp0b3":  "mace-mp-0b3-medium",
}
_URLS = {
    "mace-mpa-0-medium":
        "https://github.com/ACEsuit/mace-mp/releases/download/mace_mpa_0/"
        "mace-mpa-0-medium.model",
    "mace-omat-0-medium":
        "https://github.com/ACEsuit/mace-mp/releases/download/mace_omat_0/"
        "mace-omat-0-medium.model",
    "MACE-matpes-pbe-omat-ft":
        "https://github.com/ACEsuit/mace-foundations/releases/download/mace_matpes_0/"
        "MACE-matpes-pbe-omat-ft.model",
    "mace-mp-0b3-medium":
        "https://github.com/ACEsuit/mace-mp/releases/download/mace_mp_0b3/"
        "mace-mp-0b3-medium.model",
}
# Models this script will fetch by default (the advertised-but-missing ones).
_DEFAULT_TARGETS = ["mace-mpa-0-medium", "mace-omat-0-medium", "MACE-matpes-pbe-omat-ft"]


def _download_one(model_name: str, force: bool = False) -> int:
    rel = _MACE_MODEL_PATHS[model_name]
    dest_dir = _DEFAULT_MODELS_ROOT / rel
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{model_name}.model"
    url = _URLS[model_name]

    if dest.exists() and dest.stat().st_size > 1_000_000 and not force:
        print(f"Already present: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
        return 0

    print(f"Downloading {model_name}\n  from {url}\n  to   {dest}")
    try:
        import requests
        with requests.get(url, stream=True, timeout=600,
                          headers={"Accept": "application/octet-stream"}) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except Exception as exc:  # noqa: BLE001
        print(f"Download failed for {model_name}: {exc}", file=sys.stderr)
        return 1

    size_mb = dest.stat().st_size / 1e6
    if size_mb < 1:
        print(f"WARNING: {dest.name} is only {size_mb:.2f} MB — likely an HTML "
              f"error page, not the checkpoint. Removing.", file=sys.stderr)
        dest.unlink(missing_ok=True)
        return 1
    print(f"Done: {dest} ({size_mb:.1f} MB).")
    return 0


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
        targets = list(_MACE_MODEL_PATHS.keys())
    else:
        targets = _DEFAULT_TARGETS

    rc = 0
    for name in targets:
        rc |= _download_one(name, force=args.force)
    if rc == 0:
        print("\nAll requested MACE models present. "
              "Verify with: python backend/scripts/test_models.py")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
