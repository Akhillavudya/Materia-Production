"""
backend/scripts/test_models.py
==============================
Real health-check for every ML potential the platform knows about.

Unlike ``list_available_models()`` (which only checks that a model directory
*exists* on disk), this script actually **loads each model and runs a single-point
energy + forces evaluation** on a tiny structure. That is the only way to know a
checkpoint is genuinely usable (right format, right torch/ABI, weights load) before
a user fires off a long simulation with it.

Usage
-----
    python backend/scripts/test_models.py            # test every present model
    python backend/scripts/test_models.py --all      # also try models not on disk
    python backend/scripts/test_models.py --json      # machine-readable output

Exit code is non-zero if any *present* model fails to load+run, so it can gate CI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Make `app...` importable when run from the repo root or backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.simulation.calculator_factory import (  # noqa: E402
    get_calculator,
    list_available_models,
)


def _tiny_structure():
    """A 2-atom bulk Si — cheap, periodic, every universal potential supports it."""
    from ase import Atoms
    a = 5.43
    return Atoms(
        "Si2",
        scaled_positions=[[0, 0, 0], [0.25, 0.25, 0.25]],
        cell=[a, a, a],
        pbc=True,
    )


def test_one(calc_type: str, model_name: str) -> dict:
    """Load a model and run one energy+forces eval. Returns a result row."""
    row = {"type": calc_type, "model": model_name, "ok": False,
           "energy_eV": None, "max_force_eV_A": None, "load_s": None,
           "eval_s": None, "error": None}
    try:
        import numpy as np
        atoms = _tiny_structure()

        t0 = time.time()
        calc = get_calculator({"type": calc_type, "model": model_name})
        row["load_s"] = round(time.time() - t0, 2)

        atoms.calc = calc
        t1 = time.time()
        e = float(atoms.get_potential_energy())
        f = atoms.get_forces()
        row["eval_s"] = round(time.time() - t1, 2)

        row["energy_eV"] = round(e, 4)
        row["max_force_eV_A"] = round(float(np.sqrt((f ** 2).sum(axis=1).max())), 4)
        row["ok"] = True
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="Load + run each ML potential.")
    ap.add_argument("--all", action="store_true",
                    help="also try models whose files are not on disk")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    available = list_available_models()
    rows: list[dict] = []
    for calc_type, models in available.items():
        for m in models:
            if not m["exists"] and not args.all:
                rows.append({"type": calc_type, "model": m["name"], "ok": None,
                             "error": "not on disk (skipped)", "energy_eV": None,
                             "max_force_eV_A": None, "load_s": None, "eval_s": None})
                continue
            rows.append(test_one(calc_type, m["name"]))

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"{'TYPE':<10} {'MODEL':<28} {'STATUS':<8} "
              f"{'E (eV)':>10} {'fmax':>8} {'load s':>7} {'eval s':>7}")
        print("-" * 90)
        for r in rows:
            status = "PASS" if r["ok"] else ("SKIP" if r["ok"] is None else "FAIL")
            print(f"{r['type']:<10} {r['model']:<28} {status:<8} "
                  f"{str(r['energy_eV']):>10} {str(r['max_force_eV_A']):>8} "
                  f"{str(r['load_s']):>7} {str(r['eval_s']):>7}"
                  + (f"   {r['error']}" if r.get('error') and not r['ok'] and r['ok'] is not None else ""))

    # Non-zero exit if any model that IS on disk failed.
    failed = [r for r in rows if r["ok"] is False]
    if failed:
        print(f"\n{len(failed)} model(s) FAILED to load+run.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
