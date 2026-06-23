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
    climb_fraction:     float          = 0.5,
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
        from ase.io import write
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
    fmax = max(float(fmax), 1e-4)
    # Phase A (no climb) loosens the band; it must leave budget for the climb phase,
    # so cap it at a FRACTION of max_steps instead of a hard-coded step count. This
    # guarantees the climbing image always gets to run (the old fixed 200-step phase
    # ate the whole budget when max_steps <= 200, silently disabling the climb and
    # under-estimating the barrier).
    climb_fraction = min(max(float(climb_fraction), 0.1), 0.9)
    phase_a_steps = max(1, int(max_steps * climb_fraction))
    # Phase A must stop at a LOOSER force than the final target, never tighter.
    eff_climb_threshold = max(float(climb_threshold), fmax)
    optimizers = {"FIRE": FIRE, "BFGS": BFGS, "LBFGS": LBFGS}
    Opt = optimizers.get(str(optimizer).upper(), FIRE)

    # ── 1. Read + validate the two endpoints ──────────────────────────────────
    try:
        initial = _read_structure(poscar_path, AseAtomsAdaptor)
        final = _read_structure(final_poscar_path, AseAtomsAdaptor)
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
    endpoint_converged: dict = {}
    # Per-phase bookkeeping for the convergence report (steps taken / converged).
    phase_stats: list[dict] = []
    # How many phases this run has: each relaxed endpoint + band relax (+ climb).
    n_phases = (2 if relax_endpoints else 0) + (2 if climb else 1)
    _pidx = 0

    try:
        # ── 2. Relax both endpoints (ions only, fixed cell) ───────────────────
        # Each endpoint logs to its OWN file (they used to overwrite one another) and
        # we record whether each actually reached fmax so the summary can warn if an
        # endpoint is not a true minimum (which would make the barrier meaningless).
        if relax_endpoints:
            for label, end_atoms in (("initial", initial), ("final", final)):
                _pidx += 1
                end_atoms.calc = calc
                e_start = float(end_atoms.get_potential_energy())
                end_opt = Opt(
                    end_atoms,
                    logfile=str(out_dir / f"endpoint_{label}_relax.log"),
                )
                _attach_cancel(end_opt, progress_callback, max_steps,
                               phase=f"Relax {label} endpoint",
                               phase_index=_pidx, phase_count=n_phases)
                end_opt.run(fmax=fmax, steps=max_steps)
                try:
                    conv = bool(end_opt.converged())
                except Exception:  # noqa: BLE001
                    conv = None
                endpoint_converged[label] = conv
                phase_stats.append({
                    "name": f"Relax {label} endpoint",
                    "step_budget": max_steps, "steps_taken": int(end_opt.nsteps),
                    "converged": conv, "fmax_target": fmax,
                    "final_fmax": _safe_fmax(end_atoms, np),
                    "energy_start": round(e_start, 6),
                    "energy_end": round(float(end_atoms.get_potential_energy()), 6),
                })

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

        # Attach ONE progress/cancel observer to the band optimizer with a *mutable*
        # phase label — ASE's opt.attach() accumulates observers, so attaching a
        # second one per phase would make both fire every step (label flicker).
        band_phase = ["NEB band", _pidx + 1]
        _attach_cancel_mutable(opt, progress_callback, max_steps,
                               band_phase, n_phases)

        # ── 4. Two-phase climbing image (CatTSunami recipe) ───────────────────
        # Phase A: no climb — relax the band to a loose force OR the phase-A step
        # budget (ASE's run(fmax, steps) returns when EITHER bound is hit).
        # Phase B: turn the climbing image on for the remaining budget so the highest
        # image is pulled exactly onto the saddle point. Because phase_a_steps is a
        # fraction (<= 0.9) of max_steps, there is ALWAYS budget left for phase B.
        if climb:
            _pidx += 1
            band_phase[0], band_phase[1] = "NEB band (relaxing)", _pidx
            opt.run(fmax=eff_climb_threshold, steps=phase_a_steps)
            steps_phase_a = int(opt.nsteps)
            phase_stats.append({
                "name": "NEB band (relaxing, no climb)",
                "step_budget": phase_a_steps, "steps_taken": steps_phase_a,
                "converged": None, "fmax_target": eff_climb_threshold,
                "notes": ["Loosely relaxes the whole band before the climbing image "
                          "is switched on."],
            })
            if opt.nsteps < max_steps:
                neb.climb = True
                climb_used = True
                _pidx += 1
                band_phase[0], band_phase[1] = "NEB band (climbing image)", _pidx
                opt.run(fmax=fmax, steps=max_steps)
                phase_stats.append({
                    "name": "NEB band (climbing image)",
                    "step_budget": max_steps - steps_phase_a,
                    "steps_taken": int(opt.nsteps) - steps_phase_a,
                    "converged": None, "fmax_target": fmax,
                    "notes": ["Climbing image pins the highest image onto the saddle "
                              "point for the true barrier."],
                })
        else:
            _pidx += 1
            band_phase[0], band_phase[1] = "NEB band", _pidx
            opt.run(fmax=fmax, steps=max_steps)
            phase_stats.append({
                "name": "NEB band (no climbing image)",
                "step_budget": max_steps, "steps_taken": int(opt.nsteps),
                "converged": None, "fmax_target": fmax,
            })

        try:
            converged = bool(opt.converged())
        except Exception:  # noqa: BLE001
            converged = opt.nsteps < max_steps
        # The band's convergence verdict belongs to the LAST band phase.
        if phase_stats:
            for p in reversed(phase_stats):
                if p["name"].startswith("NEB band"):
                    p["converged"] = converged
                    break

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

    # ── Sanity warnings (a barrier can be silently meaningless) ────────────────
    warnings: list[str] = []
    if saddle_index in (0, len(energies) - 1):
        warnings.append(
            "The highest-energy point is an endpoint, not an interior image — the "
            "path is barrierless or an endpoint is not a true minimum. Check that "
            "both endpoints are correct, relaxed structures.")
    if not converged:
        warnings.append(
            "The band did not reach the force threshold within max_steps — the "
            "barrier may not be fully converged. Increase max_steps and rerun.")
    if climb and not climb_used:
        warnings.append(
            "The climbing image never activated (no step budget left after phase A) "
            "— the reported barrier is a lower bound. Increase max_steps.")
    for label, ok in endpoint_converged.items():
        if ok is False:
            warnings.append(
                f"The {label} endpoint did not finish relaxing (hit max_steps); its "
                "energy may be unconverged.")

    # ── 6. Write artifacts ────────────────────────────────────────────────────
    files = _write_outputs(
        out_dir, images, energies, rcoord, saddle_index,
        write, AseAtomsAdaptor,
    )

    # ── 6b. Convergence / diagnostics report ──────────────────────────────────
    # The "detail file": phase-by-phase steps + a verdict on whether the barrier is
    # converged or needs more steps. This is what explains the multi-phase run.
    try:
        files.update(_build_report(
            out_dir, formula, calc_cfg, phase_stats, energies, n_atoms,
            barrier_forward, barrier_reverse, reaction_energy, saddle_index,
            converged, climb_used, warnings, max_steps, elapsed,
        ))
    except Exception as e:  # noqa: BLE001
        print(f"[NEB] report generation warning: {e}")

    summary = {
        "status":              "success",
        "formula":             formula,
        "n_atoms":             n_atoms,
        "n_images":            n_images,
        "converged":           converged,
        "climb_used":          climb_used,
        "endpoint_converged":  endpoint_converged,
        "saddle_image_index":  saddle_index,
        "barrier_forward_eV":  round(barrier_forward, 4),
        "barrier_reverse_eV":  round(barrier_reverse, 4),
        "reaction_energy_eV":  round(reaction_energy, 4),
        "energies_eV":         [round(e, 6) for e in energies],
        "warnings":            warnings,
        "elapsed_s":           elapsed,
        "calculator":          calc_cfg,
        "files":               files,
    }
    summary["message"] = _message(formula, barrier_forward, barrier_reverse,
                                  reaction_energy, converged, climb_used, elapsed)
    if warnings:
        summary["message"] += "  ⚠ " + "  ".join(warnings)
    print(f"[NEB] {summary['message']}")
    return summary


# ── Validation + geometry helpers ─────────────────────────────────────────────

def _read_structure(path, AseAtomsAdaptor):
    """Read an endpoint into an ASE Atoms, auto-detecting the format.

    Goes through pymatgen's ``Structure.from_file`` (which recognises POSCAR /
    CONTCAR / CIF / XYZ / JSON …) so an endpoint does not have to be VASP-format —
    the old code forced ``format='vasp'`` and failed on CIF/other inputs.
    """
    from pymatgen.core import Structure
    return AseAtomsAdaptor.get_atoms(Structure.from_file(str(path)))


def _validate_endpoints(initial, final, np) -> Optional[str]:
    """Return an error string if the two endpoints are not a valid NEB pair."""
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
    # Endpoints must actually differ — identical geometry (even from two distinct
    # files) gives a zero-length band and a meaningless "barrier".
    try:
        delta = np.array(final.get_positions()) - np.array(initial.get_positions())
        try:
            from ase.geometry import find_mic
            delta, _ = find_mic(delta, initial.cell, initial.pbc)
        except Exception:  # noqa: BLE001
            pass
        if float(np.linalg.norm(delta)) < 1e-3:
            return ("The initial and final structures are essentially identical "
                    "(no atom moves) — NEB needs two distinct end states.")
    except Exception:  # noqa: BLE001
        pass
    return None


def _safe_fmax(atoms, np) -> Optional[float]:
    """Max per-atom force (eV/Å), or None if forces can't be evaluated."""
    try:
        forces = atoms.get_forces()
        return round(float(np.sqrt((forces ** 2).sum(axis=1).max())), 6)
    except Exception:  # noqa: BLE001
        return None


def _reaction_coordinate(images, np) -> list:
    """Cumulative path length (Å) along the band, image to image.

    Uses the minimum-image convention so an atom that hops across a periodic cell
    boundary contributes its true (short) displacement rather than a spurious
    full-cell jump that would distort the MEP plot's x-axis.
    """
    try:
        from ase.geometry import find_mic
    except Exception:  # noqa: BLE001 — degrade to raw Cartesian if unavailable
        find_mic = None

    rc = [0.0]
    prev = images[0].get_positions()
    for img in images[1:]:
        cur = img.get_positions()
        delta = cur - prev
        if find_mic is not None:
            try:
                delta, _ = find_mic(delta, img.cell, img.pbc)
            except Exception:  # noqa: BLE001
                pass
        rc.append(rc[-1] + float(np.linalg.norm(delta)))
        prev = cur
    return rc


def _attach_cancel(opt, progress_callback, total,
                   phase=None, phase_index=None, phase_count=None):
    """Make an optimizer cancellable + report progress: each step checks status.

    ``phase``/``phase_index``/``phase_count`` label which NEB stage this optimizer
    is (relax-initial, relax-final, band, climb) so the UI shows a meaningful
    "Phase 3/4: NEB band" instead of a bar that silently restarts per optimizer.
    """
    if progress_callback is None:
        return

    def _check():
        progress_callback(step=opt.nsteps, total=total,   # raises if cancelled
                          phase=phase, phase_index=phase_index,
                          phase_count=phase_count)

    opt.attach(_check, interval=1)


def _attach_cancel_mutable(opt, progress_callback, total, phase_holder, phase_count):
    """Like _attach_cancel but reads a mutable ``[label, index]`` holder.

    Attaches ONE observer whose phase label/index can change between optimizer
    runs (the band's no-climb → climbing transition) without stacking observers.
    """
    if progress_callback is None:
        return

    def _check():
        progress_callback(step=opt.nsteps, total=total,   # raises if cancelled
                          phase=phase_holder[0], phase_index=phase_holder[1],
                          phase_count=phase_count)

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


def _build_report(out_dir, formula, calc_cfg, phase_stats, energies, n_atoms,
                  fwd, rev, dE, saddle_index, converged, climb_used, warnings,
                  max_steps, elapsed) -> dict:
    """Assemble + write the NEB convergence report; return its file entries."""
    from app.services.simulation.report import ConvergenceReport, write_report

    report = ConvergenceReport(
        tool="compute_neb",
        title="NEB migration barrier",
        formula=formula,
        calculator=calc_cfg,
        elapsed_s=elapsed,
    )
    for p in phase_stats:
        report.add_phase(
            p["name"],
            step_budget=p.get("step_budget"),
            steps_taken=p.get("steps_taken"),
            converged=p.get("converged"),
            final_fmax=p.get("final_fmax"),
            fmax_target=p.get("fmax_target"),
            energy_start=p.get("energy_start"),
            energy_end=p.get("energy_end"),
            notes=p.get("notes", []),
        )

    report.summary = {
        "Forward barrier (eV)": round(fwd, 4),
        "Reverse barrier (eV)": round(rev, 4),
        "Reaction energy ΔE (eV)": round(dE, 4),
        "Saddle image index": saddle_index,
        "Band converged": converged,
        "Climbing image used": climb_used,
    }

    # Verdict: the plain-language "do I need more steps?" answer.
    verdict: list[str] = []
    if converged:
        verdict.append("The NEB band reached the force threshold — the barrier is "
                       "converged.")
    else:
        verdict.append(
            f"The NEB band did NOT reach the force threshold within max_steps — "
            f"the barrier is a lower bound. Rerun with max_steps = "
            f"{min(max_steps * 2, 5000)} to converge the energy.")
    verdict.extend(warnings)
    report.verdict_lines = verdict

    return write_report(str(out_dir), report)


def _message(formula, fwd, rev, dE, converged, climb_used, elapsed) -> str:
    conv = "converged" if converged else "DID NOT converge (hit step limit)"
    ci = "with climbing image" if climb_used else "no climbing image"
    return (
        f"NEB for {formula}: forward barrier = {fwd:.3f} eV, "
        f"reverse = {rev:.3f} eV, reaction energy ΔE = {dE:.3f} eV "
        f"({conv}, {ci}). time = {elapsed}s."
    )
