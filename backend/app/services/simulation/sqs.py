"""
backend/app/services/simulation/sqs.py
=======================================
Special Quasi-random Structure (SQS) service via ATAT `mcsqs` (Step 5.7).

What it does (plain language)
-----------------------------
A random alloy (e.g. Li(Ni,Mn,Co)O₂) has atoms mixed randomly on a sublattice.
You can't put "0.8 Ni + 0.1 Mn + 0.1 Co" on one site in a DFT cell — every atom
must be a real element. An **SQS** is a small ordered supercell whose pair/triplet
correlations best mimic the truly random alloy, so a finite cell behaves like the
disordered solid solution.

Pipeline (adapted from the reference notebook, de-interactived):
  1. Read a **disordered CIF** (sites with partial occupancies).
  2. Detect the disordered **sublattices** → parent structure + occupancy spec.
  3. Write ATAT inputs: ``rndstr.in`` (absolute Å lattice) + ``sqscell.out``.
  4. If no cutoff given, recommend one from a **nearest-neighbour shell** analysis.
  5. ``corrdump`` + ``getclus`` to set up the cluster correlations.
  6. Launch **N parallel ``mcsqs``** searches, monitoring the objective function;
     stop at a target objective, a time budget, or job cancellation.
  7. Take the best ``bestsqs`` and **convert it to a POSCAR**.

ATAT binaries (``corrdump``, ``getclus``, ``mcsqs``) must be on PATH — they are
compiled into the Docker image. If absent the service returns a clear error.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from app.core.logging import get_logger
from app.domain.jobs import JobCancelled

logger = get_logger(__name__)

_ATAT_BINARIES = ("corrdump", "getclus", "mcsqs")
_OBJECTIVE_RE = re.compile(r"Objective_function=\s*([-0-9.]+)")


def run_sqs(
    cif_path:          str,
    output_dir:        str,
    target_comp:       Optional[dict] = None,
    supercell:         tuple = (2, 2, 2),
    cutoff:            Optional[float] = None,
    n_parallel:        int   = 4,
    target_objective:  float = -0.99,
    occ_threshold:     float = 0.05,
    time_budget_s:     int   = 600,
    progress_callback: Optional[Callable[..., None]] = None,
) -> dict:
    """Generate an SQS with ATAT mcsqs. Returns the standard result envelope."""
    try:
        import numpy as np
        from pymatgen.core import Structure
    except ImportError as e:
        return {"status": "error", "message": f"Missing dependency: {e}"}

    missing = [b for b in _ATAT_BINARIES if shutil.which(b) is None]
    if missing:
        return {
            "status": "error",
            "message": (
                f"ATAT binaries not found on PATH: {', '.join(missing)}. "
                "SQS generation needs ATAT (corrdump/getclus/mcsqs) compiled into "
                "the worker image."
            ),
        }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Read disordered structure ──────────────────────────────────────────
    try:
        structure = Structure.from_file(str(cif_path))
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Failed to read structure: {e}"}

    # ── 2. Detect disordered sublattices → parent + occupancy spec ────────────
    parent, sqs_info = _build_parent_and_sublattices(
        structure, target_comp, occ_threshold)
    active = {k: v for k, v in sqs_info.items() if len(v["occupancies"]) > 1}
    if not active:
        return {
            "status": "error",
            "message": (
                "No disordered sublattice found. SQS needs a structure with "
                "partial site occupancies (a disordered CIF), optionally guided "
                "by a target composition."
            ),
        }

    (out_dir / "sqs_sublattices.json").write_text(json.dumps(sqs_info, indent=2))
    parent.to(filename=str(out_dir / "parent_structure.cif"))

    # ── 3. ATAT inputs: rndstr.in (absolute Å) + sqscell.out ──────────────────
    _write_rndstr(parent, sqs_info, out_dir / "rndstr.in")
    _write_sqscell(supercell, out_dir / "sqscell.out")

    # ── 4. Recommend a cutoff if none given ───────────────────────────────────
    if cutoff is None:
        cutoff = _recommend_cutoff(parent, sqs_info, supercell, np)
    cutoff = float(cutoff)

    # ── 5. corrdump + getclus ─────────────────────────────────────────────────
    try:
        _run_blocking(
            f"corrdump -l=rndstr.in -ro -noe -nop -clus -2={cutoff:.4f}", out_dir)
        _run_blocking("getclus", out_dir)
    except subprocess.CalledProcessError as e:
        return {"status": "error",
                "message": f"ATAT cluster setup failed ({e.cmd}): {e}"}

    # ── 6. Parallel mcsqs search (monitored, cancellable, time-capped) ────────
    try:
        best_run, best_obj = _run_mcsqs_parallel(
            out_dir, n_parallel, target_objective, time_budget_s,
            progress_callback)
    except JobCancelled:
        _kill_mcsqs()
        return {"status": "cancelled",
                "message": "SQS search was cancelled before completion."}

    best_file = out_dir / f"bestsqs{best_run}.out" if best_run else None
    if not best_file or not best_file.exists():
        # mcsqs writes bestsqs.out (single) when not using -ip; fall back.
        fallback = out_dir / "bestsqs.out"
        best_file = fallback if fallback.exists() else None
    if not best_file:
        return {"status": "error",
                "message": "mcsqs produced no bestsqs output."}

    final_out = out_dir / "bestsqs_final.out"
    shutil.copy(str(best_file), str(final_out))

    # ── 7. Convert best SQS → POSCAR ──────────────────────────────────────────
    try:
        sqs_structure = bestsqs_to_structure(str(final_out), Structure, np)
        poscar_path = out_dir / "POSCAR"
        sqs_structure.to(fmt="poscar", filename=str(poscar_path))
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"bestsqs → POSCAR failed: {e}"}

    files = {
        "contcar":          str(poscar_path),         # the SQS supercell POSCAR
        "bestsqs_out":      str(final_out),
        "rndstr_in":        str(out_dir / "rndstr.in"),
        "sqscell_out":      str(out_dir / "sqscell.out"),
        "parent_cif":       str(out_dir / "parent_structure.cif"),
        "sublattices_json": str(out_dir / "sqs_sublattices.json"),
    }
    for opt in ("bestcorr.out", "mcsqs_progress.csv"):
        p = out_dir / opt
        if p.exists():
            files[opt.replace(".", "_")] = str(p)

    comp = sqs_structure.composition.reduced_formula
    message = (
        f"SQS generated for {comp}: {len(sqs_structure)} atoms "
        f"({supercell[0]}×{supercell[1]}×{supercell[2]} supercell), "
        f"best objective {best_obj:.4f} (run {best_run}), cutoff {cutoff:.3f} Å."
    )
    logger.info("[SQS] %s", message)
    return {
        "status":           "success",
        "message":          message,
        "formula":          comp,
        "n_sites":          len(sqs_structure),
        "supercell":        list(supercell),
        "cutoff_A":         round(cutoff, 4),
        "best_objective":   round(float(best_obj), 4),
        "best_run":         best_run,
        "n_parallel":       n_parallel,
        "files":            files,
    }


# ── Sublattice detection (from notebook In[15]) ───────────────────────────────

def _build_parent_and_sublattices(structure, target_comp, occ_threshold):
    """Detect disordered site types; build the full-occupancy parent + spec.

    Returns (parent_structure, sqs_info) where sqs_info maps "type_i" →
    {sites, parent_species, occupancies}.
    """
    site_types: dict = {}
    site_type_sites = defaultdict(list)

    for i, site in enumerate(structure):
        if site.is_ordered:
            continue
        cleaned = {str(sp): occ for sp, occ in site.species.items()
                   if occ > occ_threshold}
        if not cleaned:
            continue
        total = sum(cleaned.values())
        cleaned = {el: occ / total for el, occ in cleaned.items()}
        key = tuple(sorted(cleaned.items()))
        if key not in site_types:
            site_types[key] = len(site_types)
        site_type_sites[site_types[key]].append(i)

    sqs_info: dict = {}
    for key, type_id in site_types.items():
        occs = dict(key)
        if target_comp:
            picked = {el: target_comp[el] for el in occs if el in target_comp}
            if picked:
                total = sum(picked.values())
                occs = {el: val / total for el, val in picked.items()}
        dominant = max(occs.items(), key=lambda x: x[1])[0]
        sqs_info[f"type_{type_id}"] = {
            "sites": site_type_sites[type_id],
            "parent_species": dominant,
            "occupancies": occs,
        }

    parent = structure.copy()
    for type_id, info in [(int(k.split("_")[1]), v) for k, v in sqs_info.items()]:
        for site_index in site_type_sites[type_id]:
            parent.replace(site_index, info["parent_species"])

    return parent, sqs_info


# ── ATAT input writers (absolute Å; from notebook In[17]) ─────────────────────

def _write_rndstr(parent, sqs_info, path: Path) -> None:
    """Write rndstr.in using the absolute lattice matrix as the coordinate system.

    Coordinate system = the real Å lattice vectors; the unit cell is the identity,
    so atom coordinates are fractional. Keeping it absolute means bestsqs.out comes
    back in Å and the POSCAR converter needs no rescaling.
    """
    lines = []
    for vec in parent.lattice.matrix:
        lines.append(f"{vec[0]:15.10f} {vec[1]:15.10f} {vec[2]:15.10f}")
    lines += ["1 0 0", "0 1 0", "0 0 1"]

    for i, site in enumerate(parent):
        species_string = None
        for sub in sqs_info.values():
            if i in sub["sites"]:
                occ = sub["occupancies"]
                if len(occ) > 1:
                    species_string = ",".join(f"{el}={val:g}" for el, val in occ.items())
                else:
                    species_string = next(iter(occ))
                break
        if species_string is None:
            species_string = site.species_string
        x, y, z = site.frac_coords
        lines.append(f"{x:.10f} {y:.10f} {z:.10f} {species_string}")

    path.write_text("\n".join(lines) + "\n")


def _write_sqscell(supercell, path: Path) -> None:
    a, b, c = (int(supercell[0]), int(supercell[1]), int(supercell[2]))
    path.write_text(f"1\n{a} 0 0\n0 {b} 0\n0 0 {c}\n")


# ── Nearest-neighbour shell cutoff (from notebook In[33]) ─────────────────────

def _recommend_cutoff(parent, sqs_info, supercell, np, n_shells: int = 10,
                      tol: float = 1e-3) -> float:
    """Recommend a pair cutoff (Å): midpoint between the 4th and 5th NN shells."""
    from itertools import product

    active_sites = [s for sub in sqs_info.values()
                    if len(sub["occupancies"]) > 1 for s in sub["sites"]]
    sc = parent.copy()
    sc.make_supercell([[int(supercell[0]), 0, 0],
                       [0, int(supercell[1]), 0],
                       [0, 0, int(supercell[2])]])

    # Active sites repeat once per primitive image in the supercell.
    n_images = int(supercell[0]) * int(supercell[1]) * int(supercell[2])
    n_parent = len(parent)
    active_super = [base + n_parent * k
                    for k in range(n_images) for base in active_sites]
    active_super = [i for i in active_super if i < len(sc)]
    if len(active_super) < 2:
        return 0.5 * max(parent.lattice.abc)

    coords = np.array([sc[i].coords for i in active_super])
    cell = sc.lattice.matrix
    images = np.array(list(product([-1, 0, 1], repeat=3)), dtype=float) @ cell

    dists = []
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            dr = coords[j] - coords[i] + images
            dists.append(float(np.linalg.norm(dr, axis=1).min()))
    dists = np.sort(np.unique(np.round(dists, 6)))

    shells, i = [], 0
    while i < len(dists):
        group = [dists[i]]
        j = i + 1
        while j < len(dists) and abs(dists[j] - dists[i]) < tol:
            group.append(dists[j]); j += 1
        shells.append(float(np.mean(group)))
        i = j

    if len(shells) >= 5:
        return (shells[3] + shells[4]) / 2
    return shells[min(1, len(shells) - 1)] * 1.1


# ── bestsqs.out → pymatgen Structure (the converter the notebook lacked) ──────

def bestsqs_to_structure(bestsqs_path: str, Structure, np):
    """Convert an ATAT bestsqs.out to a pymatgen Structure.

    Layout: 3 coordinate-system vectors, then 3 supercell vectors (in those
    coordinates), then atom lines ``x y z Species`` (also in those coordinates).
    """
    raw = [ln.split() for ln in Path(bestsqs_path).read_text().splitlines()
           if ln.strip()]
    M = np.array([[float(v) for v in raw[k][:3]] for k in range(3)])       # coord system
    S = np.array([[float(v) for v in raw[k][:3]] for k in range(3, 6)])    # supercell

    lattice = S @ M
    species, cart = [], []
    for row in raw[6:]:
        cart.append(np.array([float(row[0]), float(row[1]), float(row[2])]) @ M)
        species.append(row[3])

    return Structure(lattice, species, cart, coords_are_cartesian=True)


# ── ATAT process orchestration ────────────────────────────────────────────────

def _run_blocking(cmd: str, cwd: Path) -> None:
    subprocess.run(cmd, shell=True, check=True, cwd=str(cwd),
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def _latest_objective(logfile: Path) -> Optional[float]:
    if not logfile.exists():
        return None
    obj = None
    for line in logfile.read_text().splitlines():
        m = _OBJECTIVE_RE.search(line)
        if m:
            obj = float(m.group(1))
    return obj


def _kill_mcsqs() -> None:
    for p in _MCSQS_PROCS:
        try:
            p.terminate()
        except Exception:  # noqa: BLE001
            pass


_MCSQS_PROCS: list = []


def _run_mcsqs_parallel(out_dir: Path, n_parallel: int, target_objective: float,
                        time_budget_s: int, progress_callback):
    """Launch N mcsqs runs, poll their objectives, stop on target/time/cancel."""
    global _MCSQS_PROCS
    _MCSQS_PROCS = []
    logs = []
    for i in range(1, n_parallel + 1):
        log = open(out_dir / f"mcsqs{i}.log", "w")
        proc = subprocess.Popen(f"mcsqs -rc -ip={i}", shell=True, cwd=str(out_dir),
                                stdout=log, stderr=subprocess.STDOUT)
        _MCSQS_PROCS.append(proc)
        logs.append(log)

    best_seen: dict = {}
    deadline = time.time() + time_budget_s
    poll_s = 5

    try:
        while True:
            if progress_callback is not None:
                progress_callback(step=1, total=1)   # cancellation check (raises)

            best_obj, best_run, any_alive = None, None, False
            for i, proc in enumerate(_MCSQS_PROCS, start=1):
                obj = _latest_objective(out_dir / f"mcsqs{i}.log")
                if obj is not None:
                    best_seen[i] = min(best_seen.get(i, obj), obj)
                    if best_obj is None or best_seen[i] < best_obj:
                        best_obj, best_run = best_seen[i], i
                if proc.poll() is None:
                    any_alive = True

            if best_obj is not None and best_obj < target_objective:
                break
            if not any_alive or time.time() > deadline:
                break
            time.sleep(poll_s)
    finally:
        _kill_mcsqs()
        for log in logs:
            try:
                log.close()
            except Exception:  # noqa: BLE001
                pass

    if not best_seen:
        return None, float("nan")
    best_run = min(best_seen, key=best_seen.get)
    return best_run, best_seen[best_run]
