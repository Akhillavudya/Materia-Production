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

Pipeline (SimplySQS-style: start from a NORMAL ordered structure):
  1. Read any structure — **ordered is fine** (POSCAR/CIF/…), or already-disordered.
  2. If the caller passes a **sublattice composition** (e.g. "on the Ti sites put
     Ti0.6 Zr0.4"), inject those partial occupancies onto the matching sublattice —
     this is what turns an ordered parent (SrTiO₃) into the disordered target
     ((Sr,Ba)(Ti,Zr)O₃) the SQS represents.
  3. Detect the disordered **sublattices** → parent structure + occupancy spec.
  4. Write ATAT inputs: ``rndstr.in`` (absolute Å lattice) + ``sqscell.out``.
  5. If no cutoff given, recommend one from a **nearest-neighbour shell** analysis.
  6. ``corrdump`` + ``getclus`` to set up the cluster correlations.
  7. Launch **N parallel ``mcsqs``** searches, monitoring the objective function;
     stop at a target objective, a time budget, or job cancellation.
  8. Take the best ``bestsqs``, **convert it to a POSCAR**, and (optionally)
     **relax it with an ML potential** (MACE by default).

The companion ``list_sublattices()`` reports the symmetry-distinct (Wyckoff)
sites of any structure so the UI / agent can show the user which sublattices are
available to substitute on *before* running the search.

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
    substitutions:     Optional[list] = None,
    sublattice_comp:   Optional[dict] = None,
    supercell:         tuple = (2, 2, 2),
    cutoff:            Optional[float] = None,
    n_parallel:        int   = 4,
    target_objective:  float = -0.99,
    occ_threshold:     float = 0.05,
    time_budget_s:     int   = 600,
    symprec:           float = 0.1,
    relax:             bool  = True,
    calculator:        Optional[dict] = None,
    progress_callback: Optional[Callable[..., None]] = None,
) -> dict:
    """Generate an SQS with ATAT mcsqs. Returns the standard result envelope.

    Accepts a **normal ordered structure** — SQS no longer requires a disordered
    CIF. There are three ways to define the disorder the SQS represents:

    * ``sublattice_comp`` (the SimplySQS way, preferred): a dict mapping a
      sublattice — keyed by the element currently on it (e.g. ``"Ti"``) or a
      Wyckoff id from :func:`list_sublattices` (e.g. ``"Ti(1b)"``) — to a target
      occupancy dict, e.g. ``{"Ti": {"Ti": 0.6, "Zr": 0.4}}``. Every site on that
      sublattice is given those partial occupancies. This turns an ordered parent
      (SrTiO₃) into the disordered target ((Ti,Zr) on the B site) to search.
    * ``substitutions`` (legacy): ``[{"from": "Si", "to": "S", "fraction": 0.25}]``
      — replace 25% of every Si site's occupancy with S.
    * an already-disordered input CIF (partial occupancies baked in).

    ``relax`` (default True): after mcsqs finds the best ordering, relax the SQS
    supercell with an ML potential (``calculator``, MACE by default) so the result
    is a physically reasonable structure, not just the ideal-lattice placement.
    """
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

    # ── 1. Read structure ──────────────────────────────────────────────────────
    try:
        structure = Structure.from_file(str(cif_path))
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Failed to read structure: {e}"}

    # ── 1b. Turn an ordered parent into the disordered target ──────────────────
    # Preferred: a per-sublattice composition ("on the Ti sites put Ti0.6 Zr0.4").
    if sublattice_comp:
        try:
            structure, applied = _apply_sublattice_composition(
                structure, sublattice_comp, symprec)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        logger.info("[SQS] applied sublattice composition: %s", applied)

    # Legacy: fractional element→element substitution ("replace 25% of Si with S").
    if substitutions:
        try:
            structure, applied = _apply_partial_substitutions(structure, substitutions)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        logger.info("[SQS] applied partial substitutions: %s", applied)

    # ── 2. Detect disordered sublattices → parent + occupancy spec ────────────
    parent, sqs_info = _build_parent_and_sublattices(
        structure, target_comp, occ_threshold)
    active = {k: v for k, v in sqs_info.items() if len(v["occupancies"]) > 1}
    if not active:
        # Not a bug: an ordered structure with no composition given simply has
        # nothing to randomise. Tell the user which sublattices they can target.
        subs = list_sublattices(cif_path, symprec=symprec)
        hint = ""
        if subs.get("status") == "success" and subs.get("sublattices"):
            names = ", ".join(
                f'{s["id"]} ({s["element"]}×{s["count"]})'
                for s in subs["sublattices"])
            hint = (
                f" This structure has these sublattices you can substitute on: "
                f"{names}. For example, pass a composition like "
                f'{{"{subs["sublattices"][0]["element"]}": '
                f'{{"{subs["sublattices"][0]["element"]}": 0.6, "X": 0.4}}}} '
                "to make a random alloy on that site.")
        return {
            "status": "error",
            "message": (
                "SQS needs a disordered sublattice to randomise, but every site "
                "in this structure is fully occupied. Give a target composition "
                "for one of the sublattices (e.g. \"Ti=Ti0.6,Zr0.4\")." + hint
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
        "sqs_poscar":       str(poscar_path),          # the ideal-lattice SQS
        "contcar":          str(poscar_path),          # active structure (overwritten by relax below)
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

    # ── 8. Relax the SQS supercell with an ML potential (optional) ────────────
    relax_note, final_energy = "", None
    if relax:
        try:
            from app.services.simulation.optimization import run_optimization
            relax_dir = out_dir / "relax"
            opt = run_optimization(
                poscar_path=str(poscar_path),
                output_dir=str(relax_dir),
                fmax=0.05,
                cell_relax="full",
                calculator=calculator or {"type": "mace"},
                generate_vasp_inputs=False,
                progress_callback=progress_callback,
            )
            if opt.get("status") in ("success", "converged", "not_converged"):
                relaxed = opt.get("files", {}).get("contcar")
                if relaxed and Path(relaxed).exists():
                    files["relaxed_contcar"] = str(relaxed)
                    files["contcar"] = str(relaxed)   # relaxed cell becomes active
                    files["relax_energy_csv"] = opt.get("files", {}).get("energy_csv", "")
                    final_energy = opt.get("final_energy")
                    relax_note = (
                        f" Relaxed with {(calculator or {}).get('type', 'mace')}"
                        + (f" → {final_energy:.3f} eV" if final_energy is not None else "")
                        + "."
                    )
            else:
                relax_note = f" (MLP relaxation skipped: {opt.get('message', 'failed')})"
        except Exception as e:  # noqa: BLE001 — never fail the whole SQS on a relax hiccup
            logger.warning("[SQS] MLP relaxation failed: %s", e)
            relax_note = f" (MLP relaxation skipped: {e})"

    message = (
        f"SQS generated for {comp}: {len(sqs_structure)} atoms "
        f"({supercell[0]}×{supercell[1]}×{supercell[2]} supercell), "
        f"best objective {best_obj:.4f} (run {best_run}), cutoff {cutoff:.3f} Å."
        + relax_note
    )
    logger.info("[SQS] %s", message)
    result = {
        "status":           "success",
        "message":          message,
        "formula":          comp,
        "n_sites":          len(sqs_structure),
        "supercell":        list(supercell),
        "cutoff_A":         round(cutoff, 4),
        "best_objective":   round(float(best_obj), 4),
        "best_run":         best_run,
        "n_parallel":       n_parallel,
        "relaxed":          bool(relax and "relaxed_contcar" in files),
        "files":            files,
    }
    if final_energy is not None:
        result["final_energy"] = float(final_energy)
    return result


# ── Partial substitution: ordered structure → disordered sublattice ───────────

def _apply_partial_substitutions(structure, substitutions):
    """Replace a fraction of one element's sites with partial occupancy of another.

    Each spec is ``{"from": "Si", "to": "S", "fraction": 0.25}``: every ordered
    site whose species is ``from`` becomes ``{from: 1-frac, to: frac}``, creating
    the disordered sublattice SQS needs. Returns (structure, applied_summary).
    Raises ValueError on a bad spec or an element that isn't present.
    """
    applied = []
    for spec in substitutions:
        try:
            frm = str(spec["from"]).strip()
            to = str(spec["to"]).strip()
            frac = float(spec["fraction"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                f"Invalid substitution spec {spec!r}. Expected "
                "{'from': 'Si', 'to': 'S', 'fraction': 0.25}.")
        if not 0.0 < frac < 1.0:
            raise ValueError(
                f"Substitution fraction for {frm}->{to} must be between 0 and 1 "
                f"(got {frac}). A full (100%) swap is an ordered replacement, not SQS.")

        matched = 0
        for i, site in enumerate(structure):
            if site.is_ordered and site.specie.symbol == frm:
                structure.replace(i, {frm: 1.0 - frac, to: frac})
                matched += 1
        if matched == 0:
            present = sorted({el.symbol for el in structure.composition.elements})
            raise ValueError(
                f"Cannot substitute {frm}->{to}: no '{frm}' sites in the structure "
                f"(elements present: {', '.join(present)}).")
        applied.append(f"{frm}->{to} on {matched} site(s) at {frac:g}")
    return structure, applied


# ── Wyckoff sublattice listing (SimplySQS-style pre-flight) ───────────────────

def _sublattice_groups(structure, symprec: float) -> list:
    """Group sites into symmetry-distinct sublattices (Wyckoff positions).

    Returns a list of dicts ``{id, element, wyckoff, count, indices,
    example_frac}``. Falls back to grouping by element if the symmetry finder
    can't analyse the cell (e.g. already-disordered or awkward geometry).
    """
    def _element_of(site) -> str:
        if site.is_ordered:
            return site.specie.symbol
        # disordered site → name it by its dominant species
        return max(site.species.items(), key=lambda kv: kv[1])[0].symbol

    groups: list = []
    try:
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
        sga = SpacegroupAnalyzer(structure, symprec=symprec)
        sym = sga.get_symmetrized_structure()
        for idxs, wyck in zip(sym.equivalent_indices, sym.wyckoff_symbols):
            groups.append({
                "element":      _element_of(structure[idxs[0]]),
                "wyckoff":      wyck,
                "indices":      list(idxs),
            })
    except Exception:  # noqa: BLE001 — fall back to element grouping
        by_el: dict = defaultdict(list)
        for i, site in enumerate(structure):
            by_el[_element_of(site)].append(i)
        groups = [{"element": el, "wyckoff": "", "indices": idxs}
                  for el, idxs in by_el.items()]

    # Give each sublattice a short id; disambiguate repeated elements by Wyckoff.
    el_counts: dict = defaultdict(int)
    for g in groups:
        el_counts[g["element"]] += 1
    out: list = []
    for g in groups:
        el = g["element"]
        gid = el if el_counts[el] == 1 or not g["wyckoff"] else f"{el}({g['wyckoff']})"
        out.append({
            "id":           gid,
            "element":      el,
            "wyckoff":      g["wyckoff"],
            "count":        len(g["indices"]),
            "indices":      g["indices"],
            "example_frac": [round(float(x), 4)
                             for x in structure[g["indices"][0]].frac_coords],
        })
    return out


def list_sublattices(structure_path: str, symprec: float = 0.1) -> dict:
    """List the symmetry-distinct sublattices of a structure (for the UI/agent).

    Lets the user see *which* sites they can substitute on before running SQS —
    e.g. SrTiO₃ → an Sr sublattice, a Ti sublattice, and an O sublattice.
    """
    try:
        from pymatgen.core import Structure
    except ImportError as e:
        return {"status": "error", "message": f"Missing dependency: {e}"}
    try:
        structure = Structure.from_file(str(structure_path))
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Failed to read structure: {e}"}

    subs = _sublattice_groups(structure, symprec)
    return {
        "status":         "success",
        "formula":        structure.composition.reduced_formula,
        "n_sites":        len(structure),
        "n_sublattices":  len(subs),
        "sublattices":    [{k: v for k, v in s.items() if k != "indices"}
                           for s in subs],
        "message": (
            f"{structure.composition.reduced_formula}: {len(subs)} sublattice(s) — "
            + ", ".join(f'{s["id"]} ({s["element"]}×{s["count"]}'
                        + (f", {s['wyckoff']}" if s["wyckoff"] else "") + ")"
                        for s in subs)
        ),
    }


def _apply_sublattice_composition(structure, sublattice_comp: dict, symprec: float):
    """Place a target occupancy on every site of a named sublattice.

    ``sublattice_comp`` maps a sublattice key → occupancy dict, e.g.
    ``{"Ti": {"Ti": 0.6, "Zr": 0.4}}``. A key matches a sublattice by its element
    (``"Ti"``) or by a Wyckoff id from :func:`list_sublattices` (``"Ti(1b)"``).
    Occupancies are normalised to sum to 1. Returns (structure, applied_summary).
    Raises ValueError if a key matches no sublattice or an occupancy is malformed.
    """
    groups = _sublattice_groups(structure, symprec)
    applied: list = []
    for key, occ in sublattice_comp.items():
        key = str(key).strip()
        if not isinstance(occ, dict) or not occ:
            raise ValueError(
                f"Composition for sublattice '{key}' must be an element→fraction "
                f"map like {{'Ti': 0.6, 'Zr': 0.4}} (got {occ!r}).")
        try:
            occ = {str(el).strip(): float(v) for el, v in occ.items()}
        except (TypeError, ValueError):
            raise ValueError(f"Non-numeric occupancy in sublattice '{key}': {occ!r}.")
        total = sum(occ.values())
        if total <= 0:
            raise ValueError(f"Occupancies for sublattice '{key}' sum to {total}.")
        occ = {el: v / total for el, v in occ.items()}

        matched = [g for g in groups if g["id"] == key or g["element"] == key]
        if not matched:
            avail = ", ".join(f'{g["id"]} ({g["element"]})' for g in groups)
            raise ValueError(
                f"No sublattice '{key}' in this structure. Available: {avail}.")
        n_sites = 0
        for g in matched:
            for i in g["indices"]:
                structure.replace(i, occ)
                n_sites += 1
        pretty = ",".join(f"{el}{v:g}" for el, v in occ.items())
        applied.append(f"{key}->{pretty} on {n_sites} site(s)")
    return structure, applied


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
