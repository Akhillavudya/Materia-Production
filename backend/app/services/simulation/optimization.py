"""
backend/app/services/optimization_service.py
=============================================
ASE-based geometry optimization service.

Supports:
  - Position-only relaxation (IBRION=2 analog)
  - Cell + position relaxation, volume-fixed (shape only)
  - Full cell + position relaxation (everything)

Optimizers: FIRE, BFGS, LBFGS
Calculators: MACE, MatterSim  (via calculator_factory)

Outputs per run
---------------
  CONTCAR          — optimized structure in VASP POSCAR format
  optimization.log — ASE optimizer log (step, fmax, energy)
  trajectory.traj  — full ASE trajectory (readable by 3Dmol via xyz conversion)
  trajectory.xyz   — multi-frame XYZ (for 3Dmol.js scrubber)
  energy.csv       — step, energy_eV, fmax_eV_A columns
  INCAR            — VASP INCAR (if generate_vasp_inputs=True)
  KPOINTS          — VASP KPOINTS (if generate_vasp_inputs=True)

Usage
-----
    from app.services.optimization_service import run_optimization

    result = run_optimization(
        poscar_path   = "/path/to/POSCAR",
        output_dir    = "/path/to/session_dir",
        fmax          = 0.02,
        cell_relax    = "none",      # "none" | "shape" | "full"
        optimizer     = "FIRE",
        max_steps     = 1000,
        calculator    = {"type": "mace"},
        generate_vasp_inputs = True,
    )
"""

import os
import csv
import time
from pathlib import Path
from typing import Optional

from app.services.simulation.calculator_factory import get_calculator
from app.services.vasp.incar import generate_incar
from app.services.vasp.kpoints import generate_kpoints


# ── Public API ────────────────────────────────────────────────────────────────

def run_optimization(
    poscar_path:          str,
    output_dir:           str,
    fmax:                 float         = 0.02,
    cell_relax:           str           = "none",   # "none" | "shape" | "full"
    optimizer:            str           = "FIRE",
    max_steps:            int           = 1000,
    calculator:           Optional[dict] = None,
    generate_vasp_inputs: bool          = True,
) -> dict:
    """
    Run ASE geometry optimization.

    Parameters
    ----------
    poscar_path          : Path to input POSCAR / CONTCAR file.
    output_dir           : Directory where all output files are written.
    fmax                 : Force convergence threshold [eV/Å]. Default 0.02.
    cell_relax           : "none"  — relax atomic positions only
                           "shape" — relax cell shape + positions (fixed volume)
                           "full"  — relax cell shape, volume + positions
    optimizer            : "FIRE" | "BFGS" | "LBFGS"
    max_steps            : Maximum optimizer steps. Default 1000.
    calculator           : dict passed to get_calculator().
                           e.g. {"type": "mace"} or {"type": "mace", "model": "mace-omat-0-medium"}
                           Defaults to MACE mace-mp-0b3-medium.
    generate_vasp_inputs : If True, also write INCAR + KPOINTS for VASP handoff.

    Returns
    -------
    {
      "status":        "success" | "converged" | "not_converged" | "error",
      "message":       str,
      "converged":     bool,
      "steps":         int,
      "final_energy":  float,     # eV
      "final_fmax":    float,     # eV/Å
      "formula":       str,
      "n_sites":       int,
      "files": {
          "contcar":   str,       # relative path
          "log":       str,
          "trajectory_traj": str,
          "trajectory_xyz":  str,
          "energy_csv":      str,
          "incar":     str | None,
          "kpoints":   str | None,
      }
    }
    """
    try:
        from ase.io import read, write
        from ase.io.trajectory import Trajectory
        from pymatgen.io.ase import AseAtomsAdaptor
        from pymatgen.io.vasp import Poscar
    except ImportError as e:
        return {"status": "error", "message": f"Missing dependency: {e}"}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Read input structure ───────────────────────────────────────────────
    try:
        atoms = read(str(poscar_path), format="vasp")
    except Exception as e:
        return {"status": "error", "message": f"Failed to read POSCAR: {e}"}

    formula = atoms.get_chemical_formula(mode="hill")

    # ── 2. Attach calculator ──────────────────────────────────────────────────
    try:
        calc_cfg = calculator or {"type": "mace"}
        calc     = get_calculator(calc_cfg)
        atoms.calc = calc
    except Exception as e:
        return {"status": "error", "message": f"Calculator error: {e}"}

    # ── 3. Prepare output file paths ──────────────────────────────────────────
    contcar_path   = out_dir / "CONTCAR"
    log_path       = out_dir / "optimization.log"
    traj_path      = out_dir / "trajectory.traj"
    xyz_path       = out_dir / "trajectory.xyz"
    csv_path       = out_dir / "energy.csv"

    # ── 4. Wrap atoms for cell relaxation ─────────────────────────────────────
    opt_atoms = _wrap_for_cell_relax(atoms, cell_relax.lower().strip())

    # ── 5. Build optimizer ────────────────────────────────────────────────────
    try:
        opt = _make_optimizer(
            optimizer_name = optimizer.upper().strip(),
            atoms          = opt_atoms,
            log_path       = str(log_path),
            traj_path      = str(traj_path),
        )
    except Exception as e:
        return {"status": "error", "message": f"Optimizer error: {e}"}

    # ── 6. Energy/fmax logger ─────────────────────────────────────────────────
    energy_log: list[dict] = []

    def _record():
        try:
            e    = opt_atoms.get_potential_energy()
            fmax = _get_fmax(opt_atoms)
            step = len(energy_log)
            energy_log.append({"step": step, "energy_eV": round(e, 6), "fmax_eV_A": round(fmax, 6)})
        except Exception:
            pass

    opt.attach(_record, interval=1)

    # ── 7. Run ────────────────────────────────────────────────────────────────
    t0 = time.time()
    try:
        converged = opt.run(fmax=fmax, steps=max_steps)
    except Exception as e:
        return {"status": "error", "message": f"Optimization failed: {e}"}

    elapsed = round(time.time() - t0, 1)

    # ── 8. Unwrap from FrechetCellFilter if used ──────────────────────────────
    final_atoms = opt_atoms.atoms if hasattr(opt_atoms, "atoms") else opt_atoms

    # ── 9. Write CONTCAR ──────────────────────────────────────────────────────
    try:
        write(str(contcar_path), final_atoms, format="vasp", direct=True)
    except Exception as e:
        return {"status": "error", "message": f"CONTCAR write error: {e}"}

    # ── 10. Write multi-frame XYZ for 3Dmol.js ───────────────────────────────
    try:
        from ase.io import Trajectory as TrajReader
        traj_frames = list(TrajReader(str(traj_path)))
        write(str(xyz_path), traj_frames, format="extxyz")
    except Exception:
        xyz_path = None   # non-fatal

    # ── 11. Write energy CSV ──────────────────────────────────────────────────
    try:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["step", "energy_eV", "fmax_eV_A"])
            writer.writeheader()
            writer.writerows(energy_log)
    except Exception:
        csv_path = None

    # ── 12. VASP input files ──────────────────────────────────────────────────
    incar_path   = None
    kpoints_path = None
    if generate_vasp_inputs:
        try:
            structure = AseAtomsAdaptor.get_structure(final_atoms)
            incar_str   = generate_incar(structure, task="optimization", cell_relax=cell_relax)
            kpoints_str = generate_kpoints(structure)

            incar_path   = out_dir / "INCAR"
            kpoints_path = out_dir / "KPOINTS"

            incar_path.write_text(incar_str)
            kpoints_path.write_text(kpoints_str)
        except Exception as e:
            print(f"[Optimization] VASP input generation warning: {e}")
            incar_path   = None
            kpoints_path = None

    # ── 13. Collect final stats ───────────────────────────────────────────────
    steps        = len(energy_log)
    final_energy = energy_log[-1]["energy_eV"] if energy_log else None
    final_fmax   = energy_log[-1]["fmax_eV_A"] if energy_log else None

    status  = "converged" if converged else "not_converged"
    conv_str = "converged" if converged else f"did not converge in {steps} steps"
    message = (
        f"Optimization {conv_str}. "
        f"Formula: {formula}, E = {final_energy} eV, "
        f"fmax = {final_fmax} eV/Å, "
        f"time = {elapsed}s."
    )

    print(f"[Optimization] {message}")

    return {
        "status":       status,
        "message":      message,
        "converged":    bool(converged),
        "steps":        steps,
        "final_energy": final_energy,
        "final_fmax":   final_fmax,
        "formula":      formula,
        "n_sites":      len(final_atoms),
        "elapsed_s":    elapsed,
        "cell_relax":   cell_relax,
        "optimizer":    optimizer,
        "calculator":   calc_cfg,
        "files": {
            "contcar":          str(contcar_path),
            "log":              str(log_path),
            "trajectory_traj":  str(traj_path),
            "trajectory_xyz":   str(xyz_path)   if xyz_path   else None,
            "energy_csv":       str(csv_path)   if csv_path   else None,
            "incar":            str(incar_path)  if incar_path  else None,
            "kpoints":          str(kpoints_path) if kpoints_path else None,
        },
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _wrap_for_cell_relax(atoms, cell_relax: str):
    """
    Wrap Atoms in ASE filter for cell relaxation.
      "none"  → bare Atoms (positions only)
      "shape" → FrechetCellFilter(hydrostatic_strain=False) — shape + pos, fixed vol
      "full"  → FrechetCellFilter(hydrostatic_strain=True)  — shape + vol + pos
    """
    if cell_relax == "none":
        return atoms

    try:
        from ase.filters import FrechetCellFilter
    except ImportError:
        from ase.constraints import ExpCellFilter as FrechetCellFilter

    if cell_relax == "shape":
        return FrechetCellFilter(atoms, hydrostatic_strain=False)
    elif cell_relax == "full":
        return FrechetCellFilter(atoms, hydrostatic_strain=True)
    else:
        raise ValueError(f"Unknown cell_relax mode '{cell_relax}'. Use: none | shape | full")


def _make_optimizer(optimizer_name: str, atoms, log_path: str, traj_path: str):
    """Instantiate the requested ASE optimizer."""
    from ase.io import Trajectory

    kwargs = {"logfile": log_path}

    if optimizer_name == "FIRE":
        from ase.optimize import FIRE
        opt = FIRE(atoms, **kwargs, trajectory=traj_path)

    elif optimizer_name == "BFGS":
        from ase.optimize import BFGS
        opt = BFGS(atoms, **kwargs, trajectory=traj_path)

    elif optimizer_name == "LBFGS":
        from ase.optimize import LBFGS
        opt = LBFGS(atoms, **kwargs, trajectory=traj_path)

    else:
        raise ValueError(
            f"Unknown optimizer '{optimizer_name}'. Use: FIRE | BFGS | LBFGS"
        )

    return opt


def _get_fmax(atoms) -> float:
    """Compute fmax from forces (or cell stress if FrechetCellFilter)."""
    try:
        import numpy as np
        forces = atoms.get_forces()
        return float(np.sqrt((forces ** 2).sum(axis=1).max()))
    except Exception:
        return float("nan")