"""T1 — ML-potential accuracy vs Materials Project (docs/VALIDATION_PLAN.md §2).

For each (model, material): pull the MP ground-state reference (relaxed structure,
equilibrium volume, DFT bulk modulus), relax the structure with the ML potential
(same FrechetCellFilter + FIRE path the app uses), fit a Birch–Murnaghan EOS for the
bulk modulus, and compare:

  * % volume deviation        (MLP equilibrium vol/atom  vs  MP vol/atom)
  * bulk-modulus % error      (MLP EOS K_BM             vs  MP K_VRH)

Emits a CSV + a markdown parity table to docs/validation_results/.

Pilot (default):   --models mace            --materials Si,Cu,MgO
Full run example:  --models mace,mace-mpa,mace-omat,mace-matpes,mattersim,mattersim-5m \
                   --materials Si,Al,Cu,Fe,MgO,NaCl,C,GaAs,TiO2,ZnO

Run from backend/:  ../venv/bin/python scripts/validation/t1_mlp_accuracy.py [opts]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))

EV_A3_TO_GPA = 160.21766208  # 1 eV/Å³ in GPa

# Default formulas for the pilot / full set (docs/VALIDATION_PLAN.md §2.1).
PILOT_MATERIALS = ["Si", "Cu", "MgO"]


# ── MP reference pull ─────────────────────────────────────────────────────────

def _mp_key() -> str:
    for line in (_BACKEND / ".env").read_text().splitlines():
        m = re.match(r"\s*MP_API_KEY\s*=\s*(\S+)", line)
        if m:
            return m.group(1)
    raise SystemExit("MP_API_KEY not found in backend/.env")


def fetch_mp_reference(mpr, formula: str, pin_id: str | None = None) -> dict:
    """MP entry for a formula: structure + vol/atom + DFT bulk modulus.

    Picks the ground state (lowest energy_above_hull) unless ``pin_id`` names a
    specific polymorph (e.g. C → diamond mp-66 rather than the graphite ground
    state, which universal MLPs model poorly).
    """
    fields = ["material_id", "formula_pretty", "volume", "nsites",
              "bulk_modulus", "energy_above_hull", "symmetry"]
    if pin_id:
        docs = mpr.materials.summary.search(material_ids=[pin_id], fields=fields)
        if not docs:
            raise ValueError(f"pinned id {pin_id!r} not found for {formula!r}")
        d = docs[0]
    else:
        docs = mpr.materials.summary.search(formula=formula, fields=fields)
        if not docs:
            raise ValueError(f"no MP entry for formula {formula!r}")
        docs.sort(key=lambda d: (d.energy_above_hull
                                 if d.energy_above_hull is not None else 9))
        d = docs[0]
    struct = mpr.get_structure_by_material_id(d.material_id)
    k_vrh = d.bulk_modulus.get("vrh") if isinstance(d.bulk_modulus, dict) else None
    return {
        "material_id": d.material_id,
        "formula": d.formula_pretty,
        "spg": d.symmetry.symbol if d.symmetry else None,
        "vol_per_atom": d.volume / d.nsites,
        "k_vrh_GPa": k_vrh,
        "structure": struct,
    }


# ── ML-potential relax + EOS ──────────────────────────────────────────────────

def relax_and_eos(structure, calc_cfg: dict, fmax: float = 0.02,
                  max_steps: int = 300, eos_strain: float = 0.05,
                  eos_points: int = 7) -> dict:
    """Full cell+position relax, then a Birch–Murnaghan EOS for the bulk modulus."""
    try:
        from ase.filters import FrechetCellFilter
    except ImportError:  # older ASE
        from ase.constraints import ExpCellFilter as FrechetCellFilter
    from ase.eos import EquationOfState
    from ase.optimize import FIRE
    from pymatgen.io.ase import AseAtomsAdaptor

    from app.services.simulation.calculator_factory import get_calculator

    calc = get_calculator(calc_cfg)  # one calculator instance reused throughout
    atoms = AseAtomsAdaptor.get_atoms(structure)
    atoms.calc = calc

    t0 = time.time()
    opt = FIRE(FrechetCellFilter(atoms), logfile=None)
    converged = opt.run(fmax=fmax, steps=max_steps)
    relax_s = time.time() - t0

    n = len(atoms)
    vol_per_atom = atoms.get_volume() / n

    # EOS: isotropically scale the relaxed cell, single-point energies, fit.
    cell0 = atoms.get_cell().copy()
    scales = np.linspace(1 - eos_strain, 1 + eos_strain, eos_points)
    vols, energies = [], []
    for s in scales:
        a = atoms.copy()
        a.set_cell(cell0 * s, scale_atoms=True)  # linear scale → volume × s³
        a.calc = calc
        vols.append(a.get_volume())
        energies.append(float(a.get_potential_energy()))
    k_gpa = None
    try:
        eos = EquationOfState(vols, energies, eos="birchmurnaghan")
        _, _, b_ev_a3 = eos.fit()
        k_gpa = float(b_ev_a3) * EV_A3_TO_GPA
    except Exception as e:  # noqa: BLE001
        print(f"   EOS fit failed: {e}")

    return {
        "vol_per_atom": vol_per_atom,
        "k_gpa": k_gpa,
        "converged": bool(converged),
        "relax_s": round(relax_s, 1),
        "n_atoms": n,
    }


# ── driver ────────────────────────────────────────────────────────────────────

def _pct(pred, ref):
    if ref in (None, 0) or pred is None:
        return None
    return 100.0 * (pred - ref) / ref


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="mace",
                    help="comma list of model aliases (calculator_factory MODEL_ALIASES)")
    ap.add_argument("--materials", default=",".join(PILOT_MATERIALS),
                    help="comma list of chemical formulas")
    ap.add_argument("--out", default=str(_BACKEND.parent / "docs" / "validation_results"))
    args = ap.parse_args()

    from app.services.simulation.calculator_factory import normalize_calculator
    from mp_api.client import MPRester

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    materials = [m.strip() for m in args.materials.split(",") if m.strip()]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"T1 run — models={models} materials={materials}")
    mpr = MPRester(_mp_key())

    refs = {}
    for spec in materials:
        f, _, pin = spec.partition(":")
        try:
            refs[f] = fetch_mp_reference(mpr, f, pin_id=pin or None)
            r = refs[f]
            print(f"  MP {f}: {r['material_id']} ({r['spg']}) "
                  f"vol/atom={r['vol_per_atom']:.3f} K_vrh={r['k_vrh_GPa']}")
        except Exception as e:  # noqa: BLE001
            print(f"  MP {f}: FAILED — {e}")

    rows = []
    for model in models:
        cfg = normalize_calculator(model)
        if cfg.get("unsupported"):
            print(f"  model {model}: unsupported, skipping")
            continue
        for f in refs:
            ref = refs[f]
            print(f"  [{model}] relaxing {f} ...", flush=True)
            try:
                res = relax_and_eos(ref["structure"], cfg)
            except Exception as e:  # noqa: BLE001
                print(f"     FAILED — {e}")
                rows.append({"model": cfg["model"], "material": f, "error": str(e)})
                continue
            vol_dev = _pct(res["vol_per_atom"], ref["vol_per_atom"])
            k_err = _pct(res["k_gpa"], ref["k_vrh_GPa"])
            row = {
                "model": cfg["model"], "material": f, "mp_id": ref["material_id"],
                "mp_vol_per_atom": round(ref["vol_per_atom"], 4),
                "mlp_vol_per_atom": round(res["vol_per_atom"], 4),
                "vol_dev_pct": round(vol_dev, 3) if vol_dev is not None else None,
                "mp_K_vrh_GPa": ref["k_vrh_GPa"],
                "mlp_K_bm_GPa": round(res["k_gpa"], 2) if res["k_gpa"] is not None else None,
                "K_err_pct": round(k_err, 2) if k_err is not None else None,
                "converged": res["converged"], "relax_s": res["relax_s"],
            }
            rows.append(row)
            print(f"     vol/atom {row['mlp_vol_per_atom']} (Δ{row['vol_dev_pct']}%)  "
                  f"K={row['mlp_K_bm_GPa']} GPa (Δ{row['K_err_pct']}%)  "
                  f"{res['relax_s']}s conv={res['converged']}")

    _write_outputs(rows, models, list(refs.keys()), out_dir)


def _write_outputs(rows, models, materials, out_dir: Path) -> None:
    if not rows:
        print("no rows produced")
        return
    keys = ["model", "material", "mp_id", "mp_vol_per_atom", "mlp_vol_per_atom",
            "vol_dev_pct", "mp_K_vrh_GPa", "mlp_K_bm_GPa", "K_err_pct",
            "converged", "relax_s", "error"]
    csv_path = out_dir / "T1_mlp_accuracy.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r.get("vol_dev_pct") is not None]
    mae_vol = np.mean([abs(r["vol_dev_pct"]) for r in ok]) if ok else float("nan")
    okk = [r for r in rows if r.get("K_err_pct") is not None]
    mae_k = np.mean([abs(r["K_err_pct"]) for r in okk]) if okk else float("nan")

    md = [
        "# T1 — ML-potential accuracy vs Materials Project (results)",
        "",
        f"**Date:** {date.today().isoformat()} · **Plan:** `docs/VALIDATION_PLAN.md` §2",
        f"**Harness:** `backend/scripts/validation/t1_mlp_accuracy.py`",
        f"**Models:** {', '.join(models)} · **Materials:** {', '.join(materials)}",
        "",
        f"**Aggregate:** mean |volume deviation| = **{mae_vol:.2f}%** · "
        f"mean |bulk-modulus error| = **{mae_k:.1f}%** (n={len(ok)})",
        "",
        "| Model | Material | MP id | MP vol/atom (Å³) | MLP vol/atom (Å³) | Δvol % | MP K_VRH (GPa) | MLP K_BM (GPa) | ΔK % | conv | s |",
        "|-------|----------|-------|------------------|-------------------|--------|----------------|----------------|------|------|---|",
    ]
    for r in rows:
        if r.get("error"):
            md.append(f"| {r['model']} | {r['material']} | — | — | — | — | — | — | — | ERR | — |")
            continue
        md.append(
            f"| {r['model']} | {r['material']} | {r['mp_id']} | {r['mp_vol_per_atom']} "
            f"| {r['mlp_vol_per_atom']} | {r['vol_dev_pct']} | {r['mp_K_vrh_GPa']} "
            f"| {r['mlp_K_bm_GPa']} | {r['K_err_pct']} | {'✓' if r['converged'] else '✗'} "
            f"| {r['relax_s']} |")
    md += [
        "",
        "**Metrics.** Δvol % = 100·(MLP−MP)/MP equilibrium volume per atom. ΔK % vs MP's "
        "DFT VRH bulk modulus. Context (Masgent): MLPs report < ~1% volume deviation.",
        "",
        "> EOS bulk modulus is a Birch–Murnaghan fit over ±5% isotropic strain (7 points) "
        "of the MLP-relaxed cell.",
    ]
    md_path = out_dir / "T1_mlp_accuracy.md"
    md_path.write_text("\n".join(md) + "\n")
    print(f"\nwrote {csv_path}\nwrote {md_path}")
    print(f"aggregate: mean|Δvol|={mae_vol:.2f}%  mean|ΔK|={mae_k:.1f}%")


if __name__ == "__main__":
    main()
