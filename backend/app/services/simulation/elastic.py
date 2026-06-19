"""
backend/app/services/simulation/elastic.py
===========================================
ML-potential elastic / mechanical-properties service (Step 5.7).

What it does (plain language)
-----------------------------
"How stiff and how ductile is this material?" We answer it the cheap way — with
the same MACE / MatterSim potential the optimizer uses, no DFT needed:

  1. Relax the cell (shape + volume + ions) so we start from equilibrium.
  2. Symmetry-refine that relaxed cell (clean lattice for consistent strains).
  3. Apply small known **strains** (±0.5 %, ±1 %) one mode at a time, relaxing
     the ions inside each strained box, and read off the **stress**.
  4. stress = C · strain, so the slope (stress vs strain) gives the 6×6 elastic
     tensor **C** [GPa]. Symmetrise it.
  5. From C: Voigt/Reuss/**Hill** averages → bulk **K**, shear **G**, Young's
     **E**, Poisson **ν**, Pugh ratio **K/G** (ductility), universal anisotropy
     **AU**, plus a Born mechanical-stability check.

2D materials
------------
A monolayer sits in a box with a big vacuum gap along one axis. Out-of-plane
elastic constants are then meaningless, so when we detect ~one vacuum axis we:
  - relax the cell **in-plane only** (freeze the vacuum direction),
  - strain only the in-plane modes (xx, yy, xy),
  - report **2D moduli in N/m** (the physically meaningful units for a sheet):
    2D Young's modulus, 2D Poisson ratio, 2D shear & layer (area) modulus.

Voigt order (ASE convention): [xx, yy, zz, yz, xz, xy].
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Callable, Optional

from app.domain.jobs import JobCancelled
from app.services.simulation.calculator_factory import get_calculator

# A cell axis with more than this much empty space is treated as a vacuum
# (i.e. the system is a 2D sheet / slab, not a 3D bulk).
_VACUUM_THRESHOLD_A = 7.5

# ASE Voigt component order and the strain "modes" we drive.
_VOIGT = ["xx", "yy", "zz", "yz", "xz", "xy"]
_VOIGT_INDEX = {name: i for i, name in enumerate(_VOIGT)}
_MODES_3D = ["xx", "yy", "zz", "xy", "xz", "yz"]
_MODES_2D = ["xx", "yy", "xy"]


# ── Public API ────────────────────────────────────────────────────────────────

def run_elastic(
    poscar_path:          str,
    output_dir:           str,
    fmax:                 float          = 0.01,
    strains:              Optional[list] = None,
    max_steps:            int            = 300,
    calculator:           Optional[dict] = None,
    symprec:              float          = 0.01,
    generate_vasp_inputs: bool           = True,
    progress_callback:    Optional[Callable[..., None]] = None,
) -> dict:
    """Compute the elastic tensor + derived mechanical properties.

    Returns the standard ``{status, message, files, ...}`` envelope. Long-running
    (one cell relax + N strained ion-relaxes), so it honours ``progress_callback``
    for live progress and cooperative cancellation (``JobCancelled``).
    """
    try:
        import numpy as np
        from ase.filters import FrechetCellFilter
        from ase.io import read, write
        from ase.optimize import BFGS, FIRE
        from ase.units import GPa
        from pymatgen.core import Lattice
        from pymatgen.io.ase import AseAtomsAdaptor
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    except ImportError as e:
        return {"status": "error", "message": f"Missing dependency: {e}"}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    strain_values = sorted(strains) if strains else [-0.01, -0.005, 0.005, 0.01]

    # ── 1. Read structure + detect dimensionality ─────────────────────────────
    try:
        atoms = read(str(poscar_path), format="vasp")
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Failed to read POSCAR: {e}"}

    structure0 = AseAtomsAdaptor.get_structure(atoms)
    formula = structure0.composition.reduced_formula
    is_2d, vacuum_axis = _detect_2d(structure0, np)
    modes = _MODES_2D if is_2d else _MODES_3D
    n_phases = 1 + len(modes) * len(strain_values)   # cell relax + strained runs
    phase = [0]   # mutable counter shared with the progress helper

    def _bump():
        phase[0] += 1
        if progress_callback is not None:
            progress_callback(step=phase[0], total=n_phases)   # raises if cancelled

    try:
        calc_cfg = calculator or {"type": "mace"}
        calc = get_calculator(calc_cfg)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Calculator error: {e}"}

    t0 = time.time()
    cancelled = False
    spg_symbol, spg_number = "P1", 1

    try:
        # ── 2. Relax the cell (in-plane only for 2D) ──────────────────────────
        relax_atoms = AseAtomsAdaptor.get_atoms(structure0)
        relax_atoms.calc = calc
        cell_filter = FrechetCellFilter(relax_atoms, mask=_cell_mask(is_2d, vacuum_axis))
        opt = FIRE(cell_filter, logfile=str(out_dir / "cell_relax.log"))
        _attach_cancel(opt, progress_callback, phase, n_phases)
        opt.run(fmax=fmax, steps=max_steps)
        _bump()

        relaxed = AseAtomsAdaptor.get_structure(relax_atoms)

        # ── 3. Symmetry-refine the relaxed cell ───────────────────────────────
        try:
            sga = SpacegroupAnalyzer(relaxed, symprec=symprec)
            reference = sga.get_refined_structure()
            spg_symbol = sga.get_space_group_symbol()
            spg_number = sga.get_space_group_number()
        except Exception:  # noqa: BLE001 — refinement is a nicety, not required
            reference = relaxed

        # ── 4. Reference (baseline) stress ────────────────────────────────────
        ref_atoms = AseAtomsAdaptor.get_atoms(reference)
        ref_atoms.calc = calc
        stress0 = ref_atoms.get_stress(voigt=True) / GPa

        # ── 5. Strain → stress for every mode/amplitude ───────────────────────
        rows = []   # (mode, strain, sxx, syy, szz, syz, sxz, sxy)
        for mode in modes:
            for eps in strain_values:
                strained = _apply_strain(reference, mode, eps, np, Lattice)
                s_atoms = AseAtomsAdaptor.get_atoms(strained)
                s_atoms.calc = calc
                ion_opt = BFGS(s_atoms, logfile=None)
                _attach_cancel(ion_opt, progress_callback, phase, n_phases)
                ion_opt.run(fmax=fmax, steps=max_steps)
                stress = s_atoms.get_stress(voigt=True) / GPa - stress0
                rows.append([mode, float(eps), *[float(x) for x in stress]])
                _bump()

    except JobCancelled:
        cancelled = True
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Elastic calculation failed: {e}"}

    if cancelled:
        return {"status": "cancelled",
                "message": "Elastic calculation was cancelled before completion."}

    # ── 6. Fit the elastic tensor ─────────────────────────────────────────────
    C = _fit_tensor(rows, np)
    elapsed = round(time.time() - t0, 1)

    # ── 7. Derived properties (3D vs 2D) ──────────────────────────────────────
    if is_2d:
        props = _properties_2d(C, reference.lattice.abc[vacuum_axis], np)
    else:
        props = _properties_3d(C, np)

    # ── 8. Write artifacts ────────────────────────────────────────────────────
    files = _write_outputs(
        out_dir, reference, C, rows, props, write,
        AseAtomsAdaptor, generate_vasp_inputs,
    )

    summary = {
        "status":         "success",
        "dimensionality": "2D" if is_2d else "3D",
        "formula":        formula,
        "space_group":    f"{spg_symbol} (#{spg_number})",
        "n_sites":        len(reference),
        "elapsed_s":      elapsed,
        "calculator":     calc_cfg,
        "elastic_tensor": [[round(float(C[i, j]), 3) for j in range(6)]
                           for i in range(6)],
        "properties":     props,
        "files":          files,
    }
    summary["message"] = _message(formula, is_2d, props, elapsed)
    print(f"[Elastic] {summary['message']}")
    return summary


# ── Dimensionality + strain helpers ───────────────────────────────────────────

def _detect_2d(structure, np):
    """Return (is_2d, vacuum_axis). 2D ⇔ exactly one axis has a big vacuum gap."""
    fracs = structure.frac_coords
    abc = structure.lattice.abc
    vacuum = []
    for i in range(3):
        span = float(fracs[:, i].max() - fracs[:, i].min()) if len(fracs) else 1.0
        vacuum.append(abc[i] * (1.0 - span))
    big = [i for i, v in enumerate(vacuum) if v > _VACUUM_THRESHOLD_A]
    if len(big) == 1:
        return True, big[0]
    return False, None


def _cell_mask(is_2d: bool, vacuum_axis):
    """FrechetCellFilter Voigt mask (True = relax that strain component)."""
    if not is_2d:
        return [True] * 6
    # Freeze the vacuum direction: drop its normal + the two shears touching it.
    frozen = {
        0: {"xx", "xy", "xz"},
        1: {"yy", "xy", "yz"},
        2: {"zz", "xz", "yz"},
    }[vacuum_axis]
    return [name not in frozen for name in _VOIGT]


def _apply_strain(reference, mode: str, eps: float, np, Lattice):
    """Return a copy of ``reference`` with a single small strain mode applied."""
    s = reference.copy()
    F = np.eye(3)
    if mode == "xx":
        F[0, 0] += eps
    elif mode == "yy":
        F[1, 1] += eps
    elif mode == "zz":
        F[2, 2] += eps
    elif mode == "xy":
        F[0, 1] += eps / 2; F[1, 0] += eps / 2
    elif mode == "xz":
        F[0, 2] += eps / 2; F[2, 0] += eps / 2
    elif mode == "yz":
        F[1, 2] += eps / 2; F[2, 1] += eps / 2
    s.lattice = Lattice(F @ s.lattice.matrix)   # keeps fractional coords
    return s


def _fit_tensor(rows, np):
    """Least-squares fit C[i,j] = d(stress_i)/d(strain) for each driven mode."""
    C = np.zeros((6, 6))
    for mode, j in _VOIGT_INDEX.items():
        subset = [r for r in rows if r[0] == mode]
        if not subset:
            continue
        strain = np.array([r[1] for r in subset])
        for i in range(6):
            stresses = np.array([r[2 + i] for r in subset])
            C[i, j] = np.polyfit(strain, stresses, 1)[0]
    return 0.5 * (C + C.T)   # symmetrise


def _attach_cancel(opt, progress_callback, phase, n_phases):
    """Make an inner optimizer cancellable: each step checks the job status."""
    if progress_callback is None:
        return

    def _check():
        progress_callback(step=phase[0], total=n_phases)   # raises if cancelled

    opt.attach(_check, interval=1)


# ── Property formulas ─────────────────────────────────────────────────────────

def _properties_3d(C, np) -> dict:
    """Voigt/Reuss/Hill moduli + Born stability for a 3D bulk."""
    try:
        S = np.linalg.inv(C)
    except np.linalg.LinAlgError:
        S = np.linalg.pinv(C)

    KV = (C[0, 0] + C[1, 1] + C[2, 2] + 2 * (C[0, 1] + C[0, 2] + C[1, 2])) / 9
    GV = ((C[0, 0] + C[1, 1] + C[2, 2]) - (C[0, 1] + C[0, 2] + C[1, 2])
          + 3 * (C[3, 3] + C[4, 4] + C[5, 5])) / 15
    KR = 1.0 / (S[0, 0] + S[1, 1] + S[2, 2] + 2 * (S[0, 1] + S[0, 2] + S[1, 2]))
    GR = 15.0 / (4 * (S[0, 0] + S[1, 1] + S[2, 2])
                 - 4 * (S[0, 1] + S[0, 2] + S[1, 2])
                 + 3 * (S[3, 3] + S[4, 4] + S[5, 5]))
    KH, GH = (KV + KR) / 2, (GV + GR) / 2
    E = 9 * KH * GH / (3 * KH + GH)
    nu = (3 * KH - 2 * GH) / (2 * (3 * KH + GH))
    pugh = KH / GH if GH else float("nan")
    AU = 5 * (GV / GR) + KV / KR - 6 if (GR and KR) else float("nan")

    eig = np.linalg.eigvalsh(C)
    stable = bool(np.all(eig > 0))

    return {
        "units": "GPa",
        "bulk_modulus_K_GPa":   round(float(KH), 2),
        "shear_modulus_G_GPa":  round(float(GH), 2),
        "young_modulus_E_GPa":  round(float(E), 2),
        "poisson_ratio":        round(float(nu), 4),
        "pugh_ratio_K_over_G":  round(float(pugh), 4),
        "universal_anisotropy_AU": round(float(AU), 4),
        "ductile":              bool(pugh > 1.75),   # Pugh > 1.75 ≈ ductile
        "mechanically_stable":  stable,
    }


def _properties_2d(C, thickness_A: float, np) -> dict:
    """In-plane 2D moduli in N/m. (1 GPa·Å = 0.1 N/m.)"""
    f = thickness_A * 0.1   # GPa → N/m for a sheet of this cell thickness
    C11, C22, C12, C66 = (C[0, 0] * f, C[1, 1] * f, C[0, 1] * f, C[5, 5] * f)

    det = C11 * C22 - C12 ** 2
    Yx = det / C22 if C22 else float("nan")     # 2D Young's modulus along x
    Yy = det / C11 if C11 else float("nan")     # along y
    nu_xy = C12 / C22 if C22 else float("nan")
    K2d = (C11 + C22 + 2 * C12) / 4             # 2D layer (area) modulus
    stable = bool(C11 > 0 and C66 > 0 and det > 0)   # 2D Born criteria

    return {
        "units": "N/m",
        "C11_N_per_m": round(float(C11), 2),
        "C22_N_per_m": round(float(C22), 2),
        "C12_N_per_m": round(float(C12), 2),
        "C66_shear_N_per_m": round(float(C66), 2),
        "young_modulus_2D_x_N_per_m": round(float(Yx), 2),
        "young_modulus_2D_y_N_per_m": round(float(Yy), 2),
        "poisson_ratio_2D": round(float(nu_xy), 4),
        "layer_modulus_2D_N_per_m": round(float(K2d), 2),
        "mechanically_stable": stable,
    }


# ── Output writing ────────────────────────────────────────────────────────────

def _write_outputs(out_dir, reference, C, rows, props, write,
                   AseAtomsAdaptor, gen_vasp) -> dict:
    files: dict = {}

    contcar = out_dir / "CONTCAR"
    try:
        write(str(contcar), AseAtomsAdaptor.get_atoms(reference),
              format="vasp", direct=True)
        files["contcar"] = str(contcar)
    except Exception:  # noqa: BLE001
        pass

    tensor_csv = out_dir / "elastic_tensor.csv"
    try:
        with open(tensor_csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(_VOIGT)
            for i in range(6):
                w.writerow([round(float(C[i, j]), 4) for j in range(6)])
        files["elastic_tensor_csv"] = str(tensor_csv)
    except Exception:  # noqa: BLE001
        pass

    stress_csv = out_dir / "elastic_stress.csv"
    try:
        with open(stress_csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["mode", "strain", "sxx", "syy", "szz", "syz", "sxz", "sxy"])
            w.writerows(rows)
        files["stress_csv"] = str(stress_csv)
    except Exception:  # noqa: BLE001
        pass

    props_json = out_dir / "mechanical_properties.json"
    try:
        props_json.write_text(json.dumps(props, indent=2))
        files["mechanical_json"] = str(props_json)
    except Exception:  # noqa: BLE001
        pass

    if gen_vasp:
        try:
            from app.services.vasp.incar import generate_incar
            from app.services.vasp.kpoints import generate_kpoints
            incar = out_dir / "INCAR"
            kpoints = out_dir / "KPOINTS"
            incar.write_text(generate_incar(reference, task="elastic"))
            kpoints.write_text(generate_kpoints(reference))
            files["incar"] = str(incar)
            files["kpoints"] = str(kpoints)
        except Exception as e:  # noqa: BLE001
            print(f"[Elastic] VASP input generation warning: {e}")

    return files


def _message(formula: str, is_2d: bool, props: dict, elapsed: float) -> str:
    if is_2d:
        return (
            f"Elastic (2D) for {formula}: "
            f"Y2D ≈ {props.get('young_modulus_2D_x_N_per_m')} N/m, "
            f"ν2D = {props.get('poisson_ratio_2D')}, "
            f"{'stable' if props.get('mechanically_stable') else 'UNSTABLE'}. "
            f"time = {elapsed}s."
        )
    return (
        f"Elastic (3D) for {formula}: "
        f"K = {props.get('bulk_modulus_K_GPa')} GPa, "
        f"G = {props.get('shear_modulus_G_GPa')} GPa, "
        f"E = {props.get('young_modulus_E_GPa')} GPa, "
        f"ν = {props.get('poisson_ratio')}, "
        f"K/G = {props.get('pugh_ratio_K_over_G')} "
        f"({'ductile' if props.get('ductile') else 'brittle'}), "
        f"{'stable' if props.get('mechanically_stable') else 'UNSTABLE'}. "
        f"time = {elapsed}s."
    )
