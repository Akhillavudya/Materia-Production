"""Adsorbate placement on surfaces (pymatgen + ASE), with an optional AdsorbML-style
ML-relaxed accurate mode.

Two tiers:

* :func:`place_adsorbate` — fast, geometric. Finds symmetry-reduced adsorption sites
  with pymatgen's ``AdsorbateSiteFinder`` and drops the molecule on one (default: the
  first ``ontop`` site). No energies, returns immediately. This is the default tool path.

* :func:`relax_adsorption` — accurate, slow (runs as a background job). Enumerates
  candidate placements, relaxes each with a universal ML potential (MACE/MatterSim via
  ``calculator_factory``), filters out desorbed/dissociated configurations, and computes
  the adsorption energy

      E_ads = E(slab+adsorbate) − E(clean slab) − E(gas-phase molecule)

  against relaxed clean-slab and gas-phase references, returning the lowest-energy
  configuration. This mirrors the Open Catalyst Project's AdsorbML recipe
  (https://github.com/Open-Catalyst-Project/AdsorbML).

Adsorbate geometries come from ASE's G2 set (``ase.build.molecule``), so common species
(CO2, CO, H2O, O2, N2, NH3, CH4, NO, OH, …) and single atoms (O, H, N, C) are supported
out of the box.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

_SITE_TYPES = ("ontop", "bridge", "hollow")

# Common adsorbates we explicitly advertise; ASE's G2 set covers more, but this list
# drives the friendly error message and keeps the agent honest about what works.
SUPPORTED_ADSORBATES = (
    "CO2", "CO", "H2O", "O2", "H2", "N2", "NO", "NH3", "CH4", "CH3OH",
    "OH", "O", "H", "N", "C",
)


def _build_molecule(formula: str):
    """Return a pymatgen ``Molecule`` for an adsorbate formula via ASE's G2 set.

    Falls back to a single atom for one-element strings. Raises a friendly error
    listing supported species for anything unknown.
    """
    from pymatgen.io.ase import AseAtomsAdaptor

    name = (formula or "").strip()
    if not name:
        raise ValueError("adsorbate molecule is required, e.g. 'CO2'.")

    atoms = None
    try:
        from ase.build import molecule as ase_molecule
        atoms = ase_molecule(name)
    except Exception:  # noqa: BLE001 — not in the G2 set; try a single atom
        try:
            from ase import Atoms
            from ase.data import atomic_numbers
            if name in atomic_numbers:
                atoms = Atoms(name, positions=[[0.0, 0.0, 0.0]])
        except Exception:  # noqa: BLE001
            atoms = None

    if atoms is None:
        raise ValueError(
            f"Unknown adsorbate '{formula}'. Supported examples: "
            f"{', '.join(SUPPORTED_ADSORBATES)}.")
    return AseAtomsAdaptor.get_molecule(atoms)


def _as_site_finder(slab):
    """Wrap a slab Structure/Slab in an ``AdsorbateSiteFinder``.

    The surface must be oriented with the normal along c (make_slab reorients this
    way), so the default z-normal site detection is correct.
    """
    from pymatgen.analysis.adsorption import AdsorbateSiteFinder
    return AdsorbateSiteFinder(slab)


def place_adsorbate(slab, molecule: str, site_type: str = "ontop",
                    distance: float = 2.0, position_index: int = 0):
    """Place ``molecule`` on ``slab`` at an adsorption site (geometric, no relaxation).

    Args:
        slab:           a slab pymatgen ``Structure`` (surface normal along c).
        molecule:       adsorbate formula, e.g. ``"CO2"``.
        site_type:      ``"ontop"`` (default), ``"bridge"`` or ``"hollow"``.
        distance:       height of the adsorbate above the surface site (Å).
        position_index: which site of that type to use, ordered from the topmost
                        surface downward (default 0 = the highest/true top site).

    Returns the combined slab+adsorbate ``Structure``.
    """
    st = str(site_type or "ontop").lower().strip()
    if st not in _SITE_TYPES:
        raise ValueError('site_type must be "ontop", "bridge" or "hollow".')

    mol = _build_molecule(molecule)
    asf = _as_site_finder(slab)
    sites = asf.find_adsorption_sites(
        distance=float(distance), positions=(st,), symm_reduce=0.01)
    coords = sites.get(st) or sites.get("all") or []
    if not coords:
        raise ValueError(
            f"no '{st}' adsorption site found on this surface; try a different "
            "site_type (ontop/bridge/hollow).")
    # Order candidates from the topmost surface down along the c (out-of-plane)
    # normal. A trimmed/asymmetric slab can expose inequivalent top *and* bottom
    # sites; without this, position_index=0 could land on a buried lower-surface
    # site and bury the adsorbate inside the slab. index 0 == the true top site.
    c = slab.lattice.matrix[2]
    normal = c / float(np.linalg.norm(c))
    coords = sorted(coords, key=lambda p: float(np.asarray(p) @ normal), reverse=True)
    idx = max(0, min(int(position_index), len(coords) - 1))
    return asf.add_adsorbate(mol, coords[idx])


# ── Accurate mode (AdsorbML-style) ───────────────────────────────────────────────

def _relax_atoms(atoms, calc, fmax: float, max_steps: int):
    """Relax an ASE Atoms in place with FIRE; return (relaxed_atoms, energy_eV)."""
    from ase.optimize import FIRE
    atoms.calc = calc
    opt = FIRE(atoms, logfile=None)
    opt.run(fmax=fmax, steps=max_steps)
    return atoms, float(atoms.get_potential_energy())


def _min_adsorbate_surface_gap(structure, n_slab_sites: int) -> float:
    """Vertical gap (Å) between the lowest adsorbate atom and the highest slab atom.

    Adsorbate atoms are appended after slab atoms by ``add_adsorbate``/
    ``generate_adsorption_structures``, so the first ``n_slab_sites`` are the slab.
    """
    z = structure.cart_coords[:, 2]
    slab_top = float(z[:n_slab_sites].max())
    ads_bottom = float(z[n_slab_sites:].min())
    return ads_bottom - slab_top


def _is_dissociated(structure, n_slab_sites: int, ref_molecule, tol: float = 1.5) -> bool:
    """True if the adsorbate's internal bonds have stretched well beyond the gas phase.

    Compares the adsorbate's maximum nearest-neighbour distance against the gas-phase
    molecule's; a large increase means the molecule fell apart on relaxation.
    """
    n_ads = len(structure) - n_slab_sites
    if n_ads < 2:
        return False
    ads_coords = structure.cart_coords[n_slab_sites:]

    def _max_nn(coords):
        m = 0.0
        for i in range(len(coords)):
            d = np.linalg.norm(coords - coords[i], axis=1)
            d[i] = np.inf
            m = max(m, float(d.min()))
        return m

    ref_coords = np.array([s.coords for s in ref_molecule.sites])
    ref_nn = _max_nn(ref_coords) if len(ref_coords) > 1 else 1.0
    return _max_nn(ads_coords) > tol * max(ref_nn, 0.5)


def relax_adsorption(
    poscar_path: str,
    molecule: str,
    output_dir: str,
    calculator: Optional[dict] = None,
    distance: float = 2.0,
    site_types=("ontop", "bridge", "hollow"),
    max_configs: int = 6,
    fmax: float = 0.05,
    max_steps: int = 200,
    progress_callback: Optional[Callable[..., None]] = None,
) -> dict:
    """Enumerate, ML-relax and rank adsorbate placements; return the lowest-E config.

    Writes the best configuration as ``CONTCAR`` plus a results JSON / per-config CSV.
    Returns the uniform service result dict (``status``/``message``/``files``) the job
    runner persists.
    """
    try:
        from pymatgen.analysis.adsorption import AdsorbateSiteFinder
        from pymatgen.io.ase import AseAtomsAdaptor
    except ImportError as e:  # noqa: BLE001
        return {"status": "error", "message": f"Missing dependency: {e}"}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    calc_cfg = calculator or {"type": "mace"}

    try:
        from app.services.simulation.calculator_factory import get_calculator
        from pymatgen.core import Structure
    except ImportError as e:  # noqa: BLE001
        return {"status": "error", "message": f"Missing dependency: {e}"}

    # ── Load slab + build candidate placements ────────────────────────────────────
    try:
        slab_struct = Structure.from_file(str(poscar_path))
        n_slab_sites = len(slab_struct)
        mol = _build_molecule(molecule)
        asf = AdsorbateSiteFinder(slab_struct)
        configs = asf.generate_adsorption_structures(
            mol, find_args={"distance": float(distance), "positions": list(site_types)})
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Adsorbate enumeration failed: {e}"}

    if not configs:
        return {"status": "error",
                "message": "no adsorption configurations could be generated for this surface."}
    configs = configs[: max(1, int(max_configs))]
    total = len(configs) + 2  # candidates + clean-slab ref + gas ref

    try:
        calc = get_calculator(calc_cfg)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Calculator error: {e}"}

    def _report(step, msg):
        if progress_callback is not None:
            progress_callback(step=step, total=total, message=msg)

    # ── Reference 1: relaxed clean slab ───────────────────────────────────────────
    try:
        _report(0, "Relaxing clean slab reference")
        slab_atoms = AseAtomsAdaptor.get_atoms(slab_struct)
        _, e_slab = _relax_atoms(slab_atoms, get_calculator(calc_cfg), fmax, max_steps)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Clean-slab reference failed: {e}"}

    # ── Reference 2: gas-phase molecule in a large box ────────────────────────────
    try:
        _report(1, "Relaxing gas-phase molecule reference")
        gas_atoms = AseAtomsAdaptor.get_atoms(mol)
        gas_atoms.set_cell([20.0, 20.0, 20.0])
        gas_atoms.center()
        gas_atoms.pbc = True
        _, e_gas = _relax_atoms(gas_atoms, get_calculator(calc_cfg), fmax, max_steps)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Gas-phase reference failed: {e}"}

    # ── Relax each candidate, compute E_ads, filter unphysical configs ────────────
    t0 = time.time()
    rows: list[dict] = []
    best = None
    for i, cfg in enumerate(configs):
        try:
            _report(i + 2, f"Relaxing configuration {i + 1}/{len(configs)}")
            atoms = AseAtomsAdaptor.get_atoms(cfg)
            atoms, e_total = _relax_atoms(atoms, get_calculator(calc_cfg), fmax, max_steps)
            relaxed = AseAtomsAdaptor.get_structure(atoms)
            gap = _min_adsorbate_surface_gap(relaxed, n_slab_sites)
            dissociated = _is_dissociated(relaxed, n_slab_sites, mol)
            desorbed = gap > 4.0  # adsorbate floated away from the surface
            e_ads = e_total - e_slab - e_gas
            row = {
                "config": i,
                "e_total_eV": round(e_total, 4),
                "e_ads_eV": round(e_ads, 4),
                "ads_surface_gap_A": round(gap, 3),
                "valid": not (dissociated or desorbed),
                "note": ("dissociated" if dissociated else
                         "desorbed" if desorbed else "ok"),
            }
            rows.append(row)
            if row["valid"] and (best is None or e_ads < best[1]):
                best = (relaxed, e_ads, i)
        except Exception as e:  # noqa: BLE001 — skip a bad config, keep going
            rows.append({"config": i, "valid": False, "note": f"error: {e}"})

    if best is None:
        return {"status": "error",
                "message": ("all adsorption configurations were unphysical "
                            "(desorbed or dissociated after relaxation).")}

    best_struct, best_e_ads, best_idx = best
    elapsed = round(time.time() - t0, 1)

    # ── Write outputs ─────────────────────────────────────────────────────────────
    contcar_path = out_dir / "CONTCAR"
    results_path = out_dir / "results.json"
    csv_path = out_dir / "adsorption_configs.csv"
    try:
        from pymatgen.io.vasp import Poscar
        Poscar(best_struct).write_file(str(contcar_path))
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Could not write best structure: {e}"}

    summary = {
        "molecule": molecule,
        "best_config": best_idx,
        "adsorption_energy_eV": round(best_e_ads, 4),
        "e_clean_slab_eV": round(e_slab, 4),
        "e_gas_molecule_eV": round(e_gas, 4),
        "n_configs": len(configs),
        "n_valid": sum(1 for r in rows if r.get("valid")),
        "calculator": calc_cfg,
        "elapsed_s": elapsed,
        "formula": best_struct.composition.reduced_formula,
        "n_sites": len(best_struct),
    }
    try:
        results_path.write_text(json.dumps(summary, indent=2))
    except Exception:  # noqa: BLE001
        results_path = None
    try:
        keys = ["config", "e_total_eV", "e_ads_eV", "ads_surface_gap_A", "valid", "note"]
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    except Exception:  # noqa: BLE001
        csv_path = None

    message = (
        f"Adsorption of {molecule}: best E_ads = {best_e_ads:.3f} eV "
        f"(config {best_idx}, {summary['n_valid']}/{len(configs)} valid). "
        f"time = {elapsed}s."
    )
    return {
        "status": "success",
        "message": message,
        "adsorption_energy_eV": round(best_e_ads, 4),
        "best_config": best_idx,
        "calculator": calc_cfg,
        "files": {
            "contcar": str(contcar_path),
            "results_json": str(results_path) if results_path else None,
            "adsorption_csv": str(csv_path) if csv_path else None,
        },
    }
