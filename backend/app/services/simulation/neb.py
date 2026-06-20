"""
backend/app/services/simulation/neb.py
======================================
ML-potential NEB (Nudged Elastic Band) migration-barrier service.

What it does (plain language)
-----------------------------
"How much energy does an atom need to hop from A to B?" That energy hump is the
**activation / migration barrier** — it sets how fast ions diffuse, how vacancies
move, how a defect migrates. We answer it the cheap way with the same MACE /
MatterSim potential the optimizer uses, no DFT needed:

  1. Take two end states (e.g. atom in site A → atom in site B), relax both so we
     start from true local minima.
  2. String a chain of intermediate **images** between them (IDPP interpolation,
     so atoms don't overlap on the way).
  3. Run **NEB**: every image feels the ML forces plus a spring to its neighbours,
     so the whole band slides down onto the **minimum-energy path** (MEP).
  4. Turn on the **climbing image** late in the run so the highest image climbs
     exactly to the saddle point — that gives the true barrier height.

Protocol follows the CatTSunami NEB recipe (arXiv:2405.02078): IDPP interpolation,
fixed spring constant, two-phase climbing image (off until the band is loose, then
on), converge on the perpendicular force. We keep Materia's universal MACE /
MatterSim potentials as the force engine (good for bulk diffusion / vacancy hops).

Barrier definitions (E = energy of each image):
  forward  = max(E) - E[initial]
  reverse  = max(E) - E[final]
  reaction = E[final] - E[initial]
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Callable, Optional

from app.domain.jobs import JobCancelled
from app.services.simulation.calculator_factory import get_calculator

# Endpoints must describe the *same* system (same atoms, same box) for an NEB to
# mean anything. We allow a small cell mismatch (Å) from independent relaxations.
_CELL_TOL_A = 0.5


# ── Public API ────────────────────────────────────────────────────────────────

def run_neb(
    poscar_path:        str,
    final_poscar_path:  str,
    output_dir:         str,
    n_images:           int            = 7,
    fmax:               float          = 0.05,
    max_steps:          int            = 300,
    spring_k:           float          = 1.0,
    climb:              bool           = True,
    climb_threshold:    float          = 0.45,
    climb_start_steps:  int            = 200,
    relax_endpoints:    bool           = True,
    optimizer:          str            = "FIRE",
    calculator:         Optional[dict] = None,
    progress_callback:  Optional[Callable[..., None]] = None,
) -> dict:
    """Compute the minimum-energy path + migration barrier between two endpoints.

    Returns the standard ``{status, message, files, ...}`` envelope. Long-running
    (endpoint relaxes + a coupled multi-image optimization), so it honours
    ``progress_callback`` for live progress and cooperative cancellation
    (``JobCancelled``).
    """
    try:
        import numpy as np
        from ase.io import read, write
        from ase.optimize import BFGS, FIRE, LBFGS
        from pymatgen.io.ase import AseAtomsAdaptor
        try:                                  # ASE ≥ 3.23 moved NEB to ase.mep
            from ase.mep import NEB
        except ImportError:                   # older ASE
            from ase.neb import NEB
    except ImportError as e:  # noqa: BLE001
        return {"status": "error", "message": f"Missing dependency: {e}"}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_images = max(int(n_images), 3)          # interior images between the endpoints
    max_steps = max(int(max_steps), 1)
    climb_start_steps = min(max(int(climb_start_steps), 0), max_steps)
    optimizers = {"FIRE": FIRE, "BFGS": BFGS, "LBFGS": LBFGS}
    Opt = optimizers.get(str(optimizer).upper(), FIRE)

    # ── 1. Read + validate the two endpoints ──────────────────────────────────
    try:
        initial = read(str(poscar_path), format="vasp")
        final = read(str(final_poscar_path), format="vasp")
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Failed to read endpoint structures: {e}"}

    err = _validate_endpoints(initial, final, np)
    if err:
        return {"status": "error", "message": err}

    formula = AseAtomsAdaptor.get_structure(initial).composition.reduced_formula
    n_atoms = len(initial)

    try:
        calc_cfg = calculator or {"type": "mace"}
        calc = get_calculator(calc_cfg)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Calculator error: {e}"}

    t0 = time.time()
    cancelled = False
    climb_used = False
    converged = False

    try:
        # ── 2. Relax both endpoints (ions only, fixed cell) ───────────────────
        if relax_endpoints:
            for end_atoms in (initial, final):
                end_atoms.calc = calc
                end_opt = Opt(end_atoms, logfile=str(out_dir / "endpoint_relax.log"))
                _attach_cancel(end_opt, progress_callback, max_steps)
                end_opt.run(fmax=fmax, steps=max_steps)

        # ── 3. Build the band: endpoints + interior images ────────────────────
        images = [initial]
        images += [initial.copy() for _ in range(n_images)]
        images += [final]

        neb = NEB(images, k=float(spring_k), climb=False,
                  allow_shared_calculator=True)

        # IDPP interpolation avoids atomic overlap on the path (linear fallback).
        try:
            neb.interpolate(method="idpp")
        except Exception:  # noqa: BLE001
            neb.interpolate()

        for image in images:
            image.calc = calc

        opt = Opt(neb, logfile=str(out_dir / "neb.log"),
                  trajectory=str(out_dir / "neb.traj"))
        _attach_cancel(opt, progress_callback, max_steps)

        # ── 4. Two-phase climbing image (CatTSunami recipe) ───────────────────
        # Phase A: no climb — let the band relax to a loose force OR a step budget.
        # ASE's run(fmax, steps) returns when EITHER bound is hit, which is exactly
        # the paper's "force < 0.45 eV/Å or 200 steps" trigger.
        if climb:
            opt.run(fmax=climb_threshold, steps=climb_start_steps)
            if opt.nsteps < max_steps:        # budget left → climb to the saddle
                neb.climb = True
                climb_used = True
                opt.run(fmax=fmax, steps=max_steps)
        else:
            opt.run(fmax=fmax, steps=max_steps)

        try:
            converged = bool(opt.converged())
        except Exception:  # noqa: BLE001
            converged = opt.nsteps < max_steps

    except JobCancelled:
        cancelled = True
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"NEB calculation failed: {e}"}

    if cancelled:
        return {"status": "cancelled",
                "message": "NEB calculation was cancelled before completion."}

    # ── 5. Energies, reaction coordinate, barrier ─────────────────────────────
    try:
        energies = [float(img.get_potential_energy()) for img in images]
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Energy evaluation failed: {e}"}

    rcoord = _reaction_coordinate(images, np)
    e0, ef = energies[0], energies[-1]
    saddle_index = int(max(range(len(energies)), key=lambda i: energies[i]))
    e_saddle = energies[saddle_index]
    barrier_forward = e_saddle - e0
    barrier_reverse = e_saddle - ef
    reaction_energy = ef - e0
    elapsed = round(time.time() - t0, 1)

    # ── 6. Write artifacts ────────────────────────────────────────────────────
    files = _write_outputs(
        out_dir, images, energies, rcoord, saddle_index,
        write, AseAtomsAdaptor,
    )

    summary = {
        "status":              "success",
        "formula":             formula,
        "n_atoms":             n_atoms,
        "n_images":            n_images,
        "converged":           converged,
        "climb_used":          climb_used,
        "saddle_image_index":  saddle_index,
        "barrier_forward_eV":  round(barrier_forward, 4),
        "barrier_reverse_eV":  round(barrier_reverse, 4),
        "reaction_energy_eV":  round(reaction_energy, 4),
        "energies_eV":         [round(e, 6) for e in energies],
        "elapsed_s":           elapsed,
        "calculator":          calc_cfg,
        "files":               files,
    }
    summary["message"] = _message(formula, barrier_forward, barrier_reverse,
                                  reaction_energy, converged, climb_used, elapsed)
    print(f"[NEB] {summary['message']}")
    return summary


# ── Validation + geometry helpers ─────────────────────────────────────────────

def _validate_endpoints(initial, final, np) -> Optional[str]:
    """Return an error string if the two endpoints are not the same system."""
    if len(initial) != len(final):
        return (f"Endpoints have different atom counts "
                f"({len(initial)} vs {len(final)}); NEB needs identical systems.")
    if sorted(initial.get_chemical_symbols()) != sorted(final.get_chemical_symbols()):
        return ("Endpoints have different compositions; NEB needs the same atoms "
                "in both the initial and final state.")
    try:
        dcell = float(np.abs(np.array(initial.cell) - np.array(final.cell)).max())
        if dcell > _CELL_TOL_A:
            return (f"Endpoint cells differ by {dcell:.2f} Å (> {_CELL_TOL_A} Å). "
                    "NEB assumes a fixed box — relax both to the same cell first.")
    except Exception:  # noqa: BLE001 — cell check is a guard, not a hard requirement
        pass
    return None


def _reaction_coordinate(images, np) -> list:
    """Cumulative Cartesian path length (Å) from the initial image to each image."""
    rc = [0.0]
    prev = images[0].get_positions()
    for img in images[1:]:
        cur = img.get_positions()
        rc.append(rc[-1] + float(np.linalg.norm(cur - prev)))
        prev = cur
    return rc


def _attach_cancel(opt, progress_callback, total):
    """Make an optimizer cancellable + report progress: each step checks status."""
    if progress_callback is None:
        return

    def _check():
        progress_callback(step=opt.nsteps, total=total)   # raises if cancelled

    opt.attach(_check, interval=1)


# ── Output writing ────────────────────────────────────────────────────────────

def _write_outputs(out_dir, images, energies, rcoord, saddle_index,
                   write, AseAtomsAdaptor) -> dict:
    files: dict = {}
    e0 = energies[0]

    # Path CSV: one row per image (index, reaction coord, energy, ΔE vs initial).
    path_csv = out_dir / "neb_path.csv"
    try:
        with open(path_csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["image", "reaction_coord_A", "energy_eV", "delta_E_eV"])
            for i, (rc, e) in enumerate(zip(rcoord, energies)):
                w.writerow([i, round(rc, 4), round(e, 6), round(e - e0, 6)])
        files["neb_path_csv"] = str(path_csv)
    except Exception:  # noqa: BLE001
        pass

    # Saddle-point structure (the climbing/highest image) as a POSCAR.
    try:
        saddle = out_dir / "POSCAR_saddle"
        write(str(saddle), images[saddle_index], format="vasp", direct=True)
        files["saddle_poscar"] = str(saddle)
    except Exception:  # noqa: BLE001
        pass

    # Trajectory was already streamed to neb.traj by the optimizer.
    traj = out_dir / "neb.traj"
    if traj.exists():
        files["neb_traj"] = str(traj)

    # MEP plot.
    try:
        from app.services.simulation.plots import generate_neb_plot
        plot = generate_neb_plot(str(path_csv), str(out_dir))
        if plot.get("mep_png"):
            files["neb_mep"] = plot["mep_png"]
    except Exception as e:  # noqa: BLE001
        print(f"[NEB] plot generation warning: {e}")

    # Results JSON.
    results_json = out_dir / "neb_results.json"
    try:
        results_json.write_text(json.dumps({
            "energies_eV": [round(e, 6) for e in energies],
            "reaction_coord_A": [round(r, 4) for r in rcoord],
            "saddle_image_index": saddle_index,
        }, indent=2))
        files["results_json"] = str(results_json)
    except Exception:  # noqa: BLE001
        pass

    return files


def _message(formula, fwd, rev, dE, converged, climb_used, elapsed) -> str:
    conv = "converged" if converged else "DID NOT converge (hit step limit)"
    ci = "with climbing image" if climb_used else "no climbing image"
    return (
        f"NEB for {formula}: forward barrier = {fwd:.3f} eV, "
        f"reverse = {rev:.3f} eV, reaction energy ΔE = {dE:.3f} eV "
        f"({conv}, {ci}). time = {elapsed}s."
    )
