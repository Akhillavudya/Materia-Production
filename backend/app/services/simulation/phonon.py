"""
backend/app/services/simulation/phonon.py
==========================================
ML-potential phonon band-structure + DOS service (Step 5.7).

What it does (plain language)
-----------------------------
"How does this crystal vibrate, and is it dynamically stable?" We use the
finite-displacement method with the same MACE / MatterSim potential the optimizer
uses (no DFPT, no DFT):

  1. Build a **supercell** (default 3×3×3) so we capture long-wavelength modes.
  2. **Displace** atoms by a tiny amount (0.01 Å) in the symmetry-unique ways.
  3. Compute the **forces** on every displaced supercell with the ML potential.
  4. Phonopy turns those forces into **force constants**.
  5. Evaluate them along an automatic high-symmetry **band path** (via seekpath)
     and on a mesh for the **density of states (DOS)**.
  6. Plot band + DOS together; save `phonopy.yaml` and CSVs.

If the lowest frequency is clearly **negative (imaginary)**, the structure is
**dynamically unstable** at that geometry — a key physical signal we report.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Callable, Optional

from app.domain.jobs import JobCancelled
from app.services.simulation.calculator_factory import get_calculator

# Below this (THz) a mode is treated as a genuine imaginary/unstable branch
# rather than numerical noise around the acoustic Γ point.
_IMAGINARY_THRESHOLD_THZ = -0.10


def run_phonon(
    poscar_path:       str,
    output_dir:        str,
    supercell:         tuple = (3, 3, 3),
    disp_distance:     float = 0.01,
    mesh:              int   = 20,
    calculator:        Optional[dict] = None,
    progress_callback: Optional[Callable[..., None]] = None,
) -> dict:
    """Compute phonon band structure + DOS via finite displacements.

    Returns the standard ``{status, message, files, ...}`` envelope. The force
    loop reports progress per displaced supercell and is cancellable.
    """
    try:
        import numpy as np
        from ase import Atoms
        from phonopy import Phonopy
        from pymatgen.core import Structure
        from pymatgen.io.phonopy import get_phonopy_structure
    except ImportError as e:
        return {"status": "error", "message": f"Missing dependency: {e}"}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    nx, ny, nz = (int(supercell[0]), int(supercell[1]), int(supercell[2]))

    # ── 1. Read structure ─────────────────────────────────────────────────────
    try:
        structure = Structure.from_file(str(poscar_path))
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Failed to read structure: {e}"}

    formula = structure.composition.reduced_formula

    # ── 2. Build phonopy object + finite displacements ────────────────────────
    try:
        phonon = Phonopy(
            get_phonopy_structure(structure),
            supercell_matrix=[[nx, 0, 0], [0, ny, 0], [0, 0, nz]],
        )
        phonon.generate_displacements(distance=disp_distance)
        displaced = phonon.supercells_with_displacements
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Displacement generation failed: {e}"}

    n_disp = len(displaced)
    n_sc_atoms = len(displaced[0]) if n_disp else 0

    # ── 3. Forces on every displaced supercell (the heavy loop) ───────────────
    try:
        calc_cfg = calculator or {"type": "mace"}
        calc = get_calculator(calc_cfg)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Calculator error: {e}"}

    t0 = time.time()
    forces = []
    try:
        for i, scell in enumerate(displaced, start=1):
            atoms = Atoms(
                symbols=scell.symbols,
                scaled_positions=scell.scaled_positions,
                cell=scell.cell,
                pbc=True,
            )
            atoms.calc = calc
            forces.append(atoms.get_forces())
            if progress_callback is not None:
                progress_callback(step=i, total=n_disp,   # raises if cancelled
                                  phase="Forces on displaced supercells",
                                  phase_index=1, phase_count=1)
    except JobCancelled:
        return {"status": "cancelled",
                "message": "Phonon calculation was cancelled before completion."}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Force evaluation failed: {e}"}

    # ── 4. Force constants → band + DOS ───────────────────────────────────────
    try:
        phonon.forces = forces
        phonon.produce_force_constants()
        phonon.auto_band_structure()                    # seekpath picks the path
        phonon.run_mesh([mesh, mesh, mesh], is_mesh_symmetry=True)
        phonon.run_total_dos()
        band_dict = phonon.get_band_structure_dict()
        dos_dict = phonon.get_total_dos_dict()
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Phonon post-processing failed: {e}"}

    elapsed = round(time.time() - t0, 1)

    # ── 5. Stability signal ───────────────────────────────────────────────────
    min_freq = float(min(f.min() for f in band_dict["frequencies"]))
    has_imaginary = bool(min_freq < _IMAGINARY_THRESHOLD_THZ)

    # ── 6. Artifacts ──────────────────────────────────────────────────────────
    files = _write_outputs(out_dir, phonon, band_dict, dos_dict, np)

    # ── 6b. Convergence / stability report ────────────────────────────────────
    try:
        from app.services.simulation.report import ConvergenceReport, write_report
        report = ConvergenceReport(
            tool="compute_phonons",
            title="Phonon band structure + DOS",
            formula=formula, calculator=calc_cfg, elapsed_s=elapsed,
        )
        report.add_phase(
            "Forces on displaced supercells",
            step_budget=n_disp, steps_taken=n_disp, converged=True,
            notes=[f"{n_disp} finite displacements on a {nx}×{ny}×{nz} supercell "
                   f"({n_sc_atoms} atoms)."],
        )
        report.summary = {
            "Supercell": f"{nx}×{ny}×{nz}",
            "Min frequency (THz)": round(min_freq, 4),
            "Imaginary modes": has_imaginary,
        }
        if has_imaginary:
            report.verdict_lines = [
                f"Minimum frequency {min_freq:.3f} THz is imaginary — the structure "
                f"is DYNAMICALLY UNSTABLE at this supercell. Re-relax tightly "
                f"(optimize_structure with a small fmax) and/or try a larger "
                f"supercell before concluding instability."]
        else:
            report.verdict_lines = [
                f"Minimum frequency {min_freq:.3f} THz ≥ 0 — the structure is "
                f"dynamically stable. For publication accuracy, confirm with a "
                f"larger supercell."]
        files.update(write_report(str(out_dir), report))
    except Exception as exc:  # noqa: BLE001
        print(f"[Phonon] report generation warning: {exc}")

    message = (
        f"Phonons for {formula} ({nx}×{ny}×{nz} supercell, {n_sc_atoms} atoms, "
        f"{n_disp} displacements): min frequency {min_freq:.3f} THz — "
        f"{'DYNAMICALLY UNSTABLE (imaginary modes)' if has_imaginary else 'dynamically stable'}. "
        f"time = {elapsed}s."
    )
    print(f"[Phonon] {message}")

    return {
        "status":            "success",
        "message":           message,
        "formula":           formula,
        "supercell":         [nx, ny, nz],
        "n_supercell_atoms": n_sc_atoms,
        "n_displacements":   n_disp,
        "mesh":              [mesh, mesh, mesh],
        "min_frequency_THz": round(min_freq, 4),
        "has_imaginary_modes": has_imaginary,
        "elapsed_s":         elapsed,
        "calculator":        calc_cfg,
        "files":             files,
    }


# ── Output writing ────────────────────────────────────────────────────────────

def _write_outputs(out_dir, phonon, band_dict, dos_dict, np) -> dict:
    files: dict = {}

    yaml_path = out_dir / "phonopy.yaml"
    try:
        phonon.save(str(yaml_path))
        files["phonopy_yaml"] = str(yaml_path)
    except Exception:  # noqa: BLE001
        pass

    dos_csv = out_dir / "phonon_dos.csv"
    try:
        freqs = dos_dict["frequency_points"]
        dos = dos_dict["total_dos"]
        with open(dos_csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["frequency_THz", "dos"])
            for fr, d in zip(freqs, dos):
                w.writerow([round(float(fr), 6), round(float(d), 6)])
        files["dos_csv"] = str(dos_csv)
    except Exception:  # noqa: BLE001
        pass

    band_csv = out_dir / "phonon_band.csv"
    try:
        with open(band_csv, "w", newline="") as fh:
            w = csv.writer(fh)
            nbands = band_dict["frequencies"][0].shape[1]
            w.writerow(["distance"] + [f"band_{b}" for b in range(nbands)])
            for dist, freq in zip(band_dict["distances"], band_dict["frequencies"]):
                for q in range(freq.shape[0]):
                    w.writerow([round(float(dist[q]), 6)]
                               + [round(float(freq[q, b]), 6) for b in range(nbands)])
        files["band_csv"] = str(band_csv)
    except Exception:  # noqa: BLE001
        pass

    png_path = _plot_band_dos(out_dir, band_dict, dos_dict)
    if png_path:
        files["phonon_plot"] = png_path

    return files


def _plot_band_dos(out_dir, band_dict, dos_dict) -> Optional[str]:
    """Band structure (left) + DOS (right) into one PNG. Headless (Agg)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return None

    try:
        fig = plt.figure(figsize=(10, 6))
        ax_band = fig.add_axes([0.08, 0.12, 0.62, 0.80])
        ax_dos = fig.add_axes([0.75, 0.12, 0.18, 0.80])

        for dist, freq in zip(band_dict["distances"], band_dict["frequencies"]):
            for b in range(freq.shape[1]):
                ax_band.plot(dist, freq[:, b], color="black", lw=1.2)
        ax_band.axhline(0, color="gray", lw=0.8)
        ax_band.set_ylabel("Frequency (THz)", fontsize=13)
        ax_band.set_xticks([])

        ax_dos.plot(dos_dict["total_dos"], dos_dict["frequency_points"],
                    color="red", lw=1.8)
        ax_dos.fill_betweenx(dos_dict["frequency_points"], 0,
                             dos_dict["total_dos"], color="red", alpha=0.25)
        ax_dos.set_xlabel("DOS", fontsize=12)
        ax_dos.set_ylim(ax_band.get_ylim())
        ax_dos.set_yticks([])

        for ax in (ax_band, ax_dos):
            ax.tick_params(direction="in", top=True, right=True, length=4)

        png = out_dir / "phonon_band_dos.png"
        fig.savefig(str(png), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return str(png)
    except Exception:  # noqa: BLE001
        return None
