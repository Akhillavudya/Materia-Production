"""
backend/app/tools/material_tools.py
=====================================
The four agent-callable tools (redesign §14). Pure adapters: validate args →
call a service → return a uniform ``status``/``message`` envelope. No ASE, no
HTTP, no SQL here.

  search_materials      — search MP / C2DB / OQMD, return MaterialCards
  generate_vasp_inputs  — POSCAR + INCAR + KPOINTS for a material or session file
  optimize_structure    — ASE geometry optimization (MACE / MatterSim)
  run_md_simulation     — ASE NVT / NPT molecular dynamics
"""

import csv
import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.context import get_session_id, get_user_id
from app.core.logging import get_logger
from app.domain.jobs import JobType
from app.domain.vasp import CellRelax, VaspTask
from app.jobs import store
from app.jobs.queue import enqueue
from app.services.search import MaterialQuery, search_service
from app.services.structure import activation, builder
from app.services.simulation.calculator_factory import (
    DEFAULT_MACE_MODEL,
    DEFAULT_MATTERSIM_MODEL,
    MODEL_ALIAS_HINTS,
    list_available_models,
    normalize_calculator,
)
from app.services.storage.file_service import (
    STORAGE_ROOT,
    find_structure_in_session,
    list_session_files,
    rel_to_storage,
    safe_file_in_session,
    session_dir,
    session_path,
)
from app.services.vasp.kpoints import (
    generate_kpoints_by_accuracy,
    generate_kpoints_explicit,
)
from app.services.vasp.poscar import write_poscar
from app.services.vasp.service import vasp_service

logger = get_logger(__name__)


def _enqueue_job(
    job_type: JobType,
    *,
    poscar_path: Path,
    output_dir: Path,
    params: dict,
    calculator: dict,
    emit_vasp_inputs: bool,
) -> dict:
    """Create a job row (owned by the current user/session) and dispatch it.

    Returns the uniform queued envelope the agent streams back; the actual
    compute runs in a separate worker (redesign §11).
    """
    user_id = get_user_id()
    session_id = get_session_id()
    if not user_id or not session_id:
        return {"status": "error",
                "message": "No authenticated session — cannot start a job."}

    # Heavy-tools gate (Deployment Part A). The single backstop for EVERY path that
    # would start an ML-potential job (agent, manual launch panel, direct API). On
    # the free web server (ENABLE_HEAVY_TOOLS=false) nothing can spin up torch +
    # MACE/MatterSim; instead the user is pointed at the desktop app, which runs the
    # full tool set on their own machine.
    if not settings.enable_heavy_tools:
        return {
            "status": "error",
            "message": (
                f"“{job_type.value.replace('_', ' ')}” is a long-running simulation "
                "that runs on the machine, not in the web app. To run it, install the "
                "**Materia desktop app** — it includes every simulation tool "
                "(optimize, MD, elastic, phonons, NEB, SQS) and computes on your own "
                "CPU/GPU. Everything else here (search, VASP inputs, structure "
                "building, defects, symmetry) works in the browser."
            ),
        }

    # Per-user concurrency quota — protects the shared server from job spam.
    active = store.count_active_for_user(user_id)
    if active >= settings.max_active_jobs_per_user:
        return {
            "status": "error",
            "message": (
                f"You already have {active} job(s) running or queued "
                f"(limit {settings.max_active_jobs_per_user}). "
                "Wait for one to finish before starting another."
            ),
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    spec = {
        "poscar_path": str(poscar_path),
        "output_dir": str(output_dir),
        "params": params,
        "calculator": calculator,
        "emit_vasp_inputs": emit_vasp_inputs,
    }
    spec_hash = hashlib.sha256(
        json.dumps({"s": session_id, "t": job_type.value, "p": params}, sort_keys=True).encode()
    ).hexdigest()[:16]
    job_id = uuid.uuid4().hex

    try:
        store.create_job(
            job_id=job_id, user_id=user_id, session_id=session_id,
            job_type=job_type.value, spec=spec, calculator=calculator,
            spec_hash=spec_hash,
        )
        enqueue(job_type, job_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("Job enqueue failed")
        return {"status": "error", "message": f"Could not start job: {e}"}

    return {
        "status":  "queued",
        "job_id":  job_id,
        "type":    job_type.value,
        "track":   f"/api/jobs/{job_id}",
        "message": (
            f"Started {job_type.value} job — tracking as {job_id[:8]}. "
            "Live progress and results will appear in the job dashboard."
        ),
    }


def _calc_label(cfg: dict) -> str:
    """Human-friendly name for a resolved calculator config, e.g. 'MACE (…)'."""
    fam = {"mace": "MACE", "mattersim": "MatterSim"}.get(cfg.get("type"), cfg.get("type"))
    return f"{fam} ({cfg.get('model')})"


def _resolve_calculator(calc_type: Optional[str], model: Optional[str]) -> dict:
    """Resolve a calculator request to a concrete cfg, or an error envelope.

    Returns ``{"type", "model"}`` on success or ``{"status": "error", ...}`` when
    the requested potential is unsupported (so the caller skips enqueueing).
    """
    cfg = normalize_calculator(calc_type, model)
    if cfg.get("unsupported"):
        return {
            "status": "error",
            "message": (
                f"Calculator '{cfg['requested']}' is not supported. "
                f"Available potentials: {', '.join(cfg['supported'])}. "
                "Use list_models to see the variants."
            ),
        }
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — search_materials
# ─────────────────────────────────────────────────────────────────────────────

_SOURCE_LABELS = {
    "mp":   "Materials Project (bulk/3D)",
    "c2db": "C2DB (2D materials)",
    "oqmd": "OQMD (Open Quantum Materials Database)",
}

# Columns for the S1 "all polymorphs" CSV (card attr → header).
_POLYMORPH_CSV_COLUMNS = [
    ("id",                            "material_id"),
    ("formula",                       "formula"),
    ("crystal_system",               "crystal_system"),
    ("spacegroup_symbol",            "spacegroup"),
    ("band_gap_eV",                  "band_gap_eV"),
    ("energy_above_hull_eV_per_atom", "e_above_hull_eV"),
    ("formation_energy_eV_per_atom", "formation_e_eV_atom"),
    ("n_atoms",                       "n_atoms"),
    ("source",                        "source"),
]


def _write_polymorphs_csv(cards, query_str: str) -> Optional[str]:
    """Write every matching card's metadata to ``<formula>_polymorphs.csv`` (S1).

    Returns the filename on success, or None if it could not be written (e.g. no
    active session). Structures are NOT fetched — this is metadata only.
    """
    safe = re.sub(r"[^\w.-]", "_", query_str) or "search"
    fname = f"{safe}_polymorphs.csv"
    try:
        path = session_dir() / fname
        with path.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([h for _, h in _POLYMORPH_CSV_COLUMNS])
            for c in cards:
                row = []
                for attr, _ in _POLYMORPH_CSV_COLUMNS:
                    val = getattr(c, attr, None)
                    row.append(getattr(val, "value", val))   # enum → its value
                writer.writerow(row)
    except Exception as e:  # noqa: BLE001 — CSV is a bonus, never fail the search
        logger.warning("Could not write polymorphs CSV: %s", e)
        return None
    return fname


def search_materials(
    formula:         Optional[str]   = None,
    element:         Optional[str]   = None,
    elements:        Optional[str]   = None,
    min_gap:         Optional[float] = None,
    max_gap:         Optional[float] = None,
    max_formation_e: Optional[float] = None,
    dimensionality:  Optional[str]   = None,
    limit:           int             = 10,
) -> dict:
    """Search for materials across MP → C2DB → OQMD (first source with hits wins)."""
    if not any([formula, element, elements]):
        return {
            "status":         "error",
            "message":        "Provide at least one of: formula, element, or elements.",
            "materials":      [],
            "sources_tried":  [],
            "total_matching": 0,
            "returned":       0,
        }

    elem_list = (
        [e.strip() for e in elements.split(",") if e.strip()] if elements else []
    )
    display_limit = min(max(int(limit), 1), 20)
    query = MaterialQuery(
        formula=formula, element=element, elements=elem_list,
        min_gap=min_gap, max_gap=max_gap, max_formation_e=max_formation_e,
        dimensionality=dimensionality, limit=display_limit,
    )

    result    = search_service.search(query)
    all_cards = result.cards                       # full stability-sorted set (capped)
    tried     = [s.value for s in result.sources_tried]
    source    = result.source_used.value if result.source_used else None
    query_str = formula or element or elements or ""

    if not all_cards:
        return {
            "status":         "not_found",
            "source_used":    None,
            "sources_tried":  tried,
            "materials":      [],
            "total_matching": 0,
            "returned":       0,
            "message": (
                f"'{query_str}' was not found in any database "
                f"(searched: {', '.join(tried)}). "
                "Try a different formula or check the spelling."
            ),
        }

    display_cards = all_cards[:display_limit]
    materials = [c.model_dump(mode="json") for c in display_cards]
    total, returned = len(all_cards), len(display_cards)

    # S1: when there are more matches than we display, dump the full metadata set
    # to a CSV so the user can browse every polymorph and pick one to fetch.
    polymorphs_csv = _write_polymorphs_csv(all_cards, query_str) if total > returned else None

    tried_other = [s for s in tried if s != source]
    note = f" (not found in {', '.join(tried_other)})" if tried_other else ""
    if polymorphs_csv:
        msg = (f"Found {total} matches for '{query_str}' in "
               f"{_SOURCE_LABELS.get(source, source)}{note} — showing the {returned} "
               f"most stable. Full list saved to {polymorphs_csv} ({total} rows).")
    else:
        msg = (f"Found {total} result{'s' if total != 1 else ''} for '{query_str}' "
               f"in {_SOURCE_LABELS.get(source, source)}{note}.")

    return {
        "status":         "ok",
        "source_used":    source,
        "sources_tried":  tried,
        "materials":      materials,
        "total_matching": total,
        "returned":       returned,
        "polymorphs_csv": polymorphs_csv,
        "message":        msg,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Shared structure resolution (used by generate_vasp_inputs + generate_poscar)
# ─────────────────────────────────────────────────────────────────────────────

class _StructureError(Exception):
    """Raised when an input structure can't be resolved (user-facing message)."""


def _resolve_structure(
    material_id: Optional[str],
    source:      Optional[str],
    poscar_path: Optional[str],
):
    """Resolve a pymatgen ``Structure`` from a session file or a database id.

    Raises ``_StructureError`` with a friendly message on any failure.
    """
    try:
        from pymatgen.core import Structure
    except ImportError:
        raise _StructureError("pymatgen is required. Run: pip install pymatgen")

    if poscar_path and not material_id:
        try:
            path = find_structure_in_session(poscar_path)
            return Structure.from_file(str(path))
        except Exception as e:  # noqa: BLE001
            raise _StructureError(f"Could not read structure: {e}")

    if material_id:
        if material_id in (None, "", "auto"):
            raise _StructureError("No material selected. Search for a material first.")
        structure = search_service.get_structure(material_id, source)
        if structure is None:
            raise _StructureError(f"Could not retrieve a structure for '{material_id}'.")
        return structure

    raise _StructureError("Provide either material_id (+ source) or poscar_path.")


def _enforce_atom_cap(poscar_path: Path) -> Optional[dict]:
    """Reject structures larger than the server's atom limit before enqueueing.

    Returns an error envelope if too large, else None. If the file can't be
    parsed here, returns None and lets the worker surface the real error.
    """
    try:
        from pymatgen.core import Structure
        n_atoms = len(Structure.from_file(str(poscar_path)))
    except Exception:  # noqa: BLE001
        return None
    if n_atoms > settings.max_atoms:
        return {
            "status": "error",
            "message": (
                f"This structure has {n_atoms} atoms, above the "
                f"{settings.max_atoms}-atom limit on this server. "
                "Use a smaller cell or unit cell."
            ),
        }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — generate_vasp_inputs  (consolidates POSCAR + KPOINTS + INCAR generation)
# ─────────────────────────────────────────────────────────────────────────────

# Allowed modifier values (the agent-facing choices for generate_vasp_inputs).
_FUNCTIONALS = {"pbe", "hse06", "scan"}
_VDW_OPTIONS = {"none", "d3", "d3bj", "optb88", "df2"}
_SOLVENTS = {"none", "vaspsol", "vaspsol++"}


def generate_vasp_inputs(
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
    poscar_path: Optional[str] = None,
    task:        str           = "relaxation",
    cell_relax:  str           = "none",
    functional:  str           = "pbe",
    vdw:         str           = "none",
    soc:         bool          = False,
    hubbard_u:   bool          = False,
    dipole:      bool          = False,
    solvent:     str           = "none",
    charge:      float         = 0.0,
    **overrides,
) -> dict:
    """Generate a complete VASP input set (POSCAR + INCAR + KPOINTS).

    Provide either (`material_id` [+ `source`]) to fetch a structure from a
    database, or `poscar_path` to use an existing session structure. The
    modifiers (functional/vdw/soc/hubbard_u/dipole/charge) combine with any task.
    """
    try:
        task_enum = VaspTask(task.lower().strip())
    except ValueError:
        return {"status": "error",
                "message": (f"Invalid task '{task}'. Use: "
                            f"{' | '.join(t.value for t in VaspTask)}.")}
    try:
        cell_enum = CellRelax(cell_relax.lower().strip())
    except ValueError:
        return {"status": "error",
                "message": f"Invalid cell_relax '{cell_relax}'. Use: none | shape | full."}

    functional = (functional or "pbe").lower().strip()
    if functional not in _FUNCTIONALS:
        return {"status": "error",
                "message": f"Invalid functional '{functional}'. Use: {' | '.join(sorted(_FUNCTIONALS))}."}
    vdw = (vdw or "none").lower().strip()
    if vdw not in _VDW_OPTIONS:
        return {"status": "error",
                "message": f"Invalid vdw '{vdw}'. Use: {' | '.join(sorted(_VDW_OPTIONS))}."}
    solvent = (solvent or "none").lower().strip()
    if solvent not in _SOLVENTS:
        return {"status": "error",
                "message": f"Invalid solvent '{solvent}'. Use: {' | '.join(sorted(_SOLVENTS))}."}

    # ── resolve the input structure ───────────────────────────────────────────
    try:
        structure = _resolve_structure(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    if len(structure) > settings.max_atoms:
        return {"status": "error",
                "message": (f"This structure has {len(structure)} atoms, above the "
                            f"{settings.max_atoms}-atom limit on this server.")}

    modifiers = {
        "functional": functional, "vdw": vdw, "soc": bool(soc),
        "hubbard_u": bool(hubbard_u), "dipole": bool(dipole),
        "solvent": solvent, "charge": float(charge or 0.0),
    }

    # ── build the input set ────────────────────────────────────────────────────
    out_dir = session_dir() / "vasp_inputs" / task_enum.value
    try:
        input_set = vasp_service.build_input_set(
            structure, task=task_enum, cell_relax=cell_enum,
            output_dir=out_dir, overrides=overrides or None, modifiers=modifiers,
        )
    except Exception as e:
        return {"status": "error", "message": f"VASP input generation failed: {e}"}

    files_rel = {k: rel_to_storage(Path(v)) for k, v in input_set.files.items()}
    written = [Path(p).name for p in input_set.files.values()]
    mod_note = (f" [{', '.join(f'{k}={v}' for k, v in input_set.modifiers.items())}]"
                if input_set.modifiers else "")

    return {
        "status":        "success",
        "task":          task_enum.value,
        "formula":       input_set.formula,
        "n_sites":       input_set.n_sites,
        "encut":         input_set.encut,
        "kmesh":         input_set.kmesh,
        "elements":      input_set.elements,
        "potentials":    input_set.potentials,
        "modifiers":     input_set.modifiers,
        "nelect":        input_set.nelect,
        "warnings":      input_set.warnings,
        "files":         files_rel,
        "files_written": written,
        "message": (
            f"VASP {task_enum.value} inputs generated for {input_set.formula} "
            f"({input_set.n_sites} atoms){mod_note}: {', '.join(written)}."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — generate_poscar  (POSCAR only — no INCAR/KPOINTS/POTCAR)
# ─────────────────────────────────────────────────────────────────────────────

def generate_poscar(
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
    poscar_path: Optional[str] = None,
) -> dict:
    """Generate ONLY a POSCAR for a material or session structure.

    Writes ``POSCAR`` + ``POSCAR_<formula>`` into the session root so downstream
    tools (optimize / MD / VASP) pick it up. Does not create INCAR, KPOINTS, or
    POTCAR — use generate_vasp_inputs for the full VASP input set.
    """
    try:
        structure = _resolve_structure(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    formula = structure.composition.reduced_formula
    try:
        result = write_poscar(structure, session_dir(), name=formula)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"POSCAR generation failed: {e}"}

    return {
        "status":        "success",
        "formula":       result["formula"],
        "n_sites":       result["n_sites"],
        "lattice_a":     result["lattice_a"],
        "lattice_b":     result["lattice_b"],
        "lattice_c":     result["lattice_c"],
        "files_written": result["files_written"],
        "message": (
            f"POSCAR generated for {result['formula']} "
            f"({result['n_sites']} atoms). No other VASP inputs were created."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — generate_kpoints  (KPOINTS by accuracy level)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_mesh(text: str) -> list[int]:
    """Read an explicit k-mesh string. Accepts '2 2 2', '2,2,2', '2x2x2', or a
    single '2' (→ 2 2 2). Raises ValueError on anything else."""
    import re
    parts = [p for p in re.split(r"[\s,x×]+", text.strip()) if p]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ValueError(
            f'Could not read k-point mesh "{text}". Use three integers, e.g. "2 2 2".')
    if len(nums) == 1:
        nums = nums * 3
    if len(nums) != 3:
        raise ValueError(
            f'A k-point mesh needs one or three integers, got "{text}" — e.g. "2 2 2".')
    return nums


def generate_kpoints(
    accuracy_level: str = "Medium",
    gamma_centered: bool = True,
    custom_kppa:    Optional[int] = None,
    explicit_mesh:  Optional[str] = None,
    material_id:    Optional[str] = None,
    source:         Optional[str] = None,
    poscar_path:    Optional[str] = None,
) -> dict:
    """Write a VASP KPOINTS file at a chosen accuracy level (fast).

    `accuracy_level` sets the k-points-per-atom density: "Low" (1000), "Medium"
    (3000), "High" (5000), or "Custom" (uses `custom_kppa`). `explicit_mesh`
    (e.g. "2 2 2" or "1 1 1") overrides the density and writes that EXACT mesh —
    handy when the user asks for a specific grid; a mesh cannot go below 1 1 1.
    `gamma_centered=True` writes a Γ-centered mesh (recommended); False writes
    Monkhorst-Pack. Saves ``KPOINTS`` into the session root next to the active
    POSCAR. Operates on the active session structure by default; pass
    `poscar_path` for a specific session file or `material_id` (+ `source`) to
    fetch one from a database.
    """
    # Explicit mesh short-circuit — independent of the structure/density.
    if explicit_mesh and explicit_mesh.strip():
        try:
            text, used = generate_kpoints_explicit(
                _parse_mesh(explicit_mesh), gamma_centered=gamma_centered)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        out = session_dir() / "KPOINTS"
        out.write_text(text if text.endswith("\n") else text + "\n")
        style = "Γ-centered" if gamma_centered else "Monkhorst-Pack"
        grid = "×".join(map(str, used))
        return {
            "status":         "success",
            "accuracy_level": "Explicit",
            "mesh":           used,
            "gamma_centered": gamma_centered,
            "files_written":  ["KPOINTS"],
            "message":        f"KPOINTS written with an explicit {grid} mesh ({style}).",
        }

    try:
        structure = _resolve_structure(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    try:
        text, kppa = generate_kpoints_by_accuracy(
            structure, accuracy_level=accuracy_level,
            custom_kppa=custom_kppa, gamma_centered=gamma_centered)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"KPOINTS generation failed: {e}"}

    out = session_dir() / "KPOINTS"
    out.write_text(text if text.endswith("\n") else text + "\n")

    style = "Γ-centered" if gamma_centered else "Monkhorst-Pack"
    return {
        "status":        "success",
        "accuracy_level": accuracy_level,
        "kppa":          kppa,
        "gamma_centered": gamma_centered,
        "files_written": ["KPOINTS"],
        "message": (
            f"KPOINTS written at {accuracy_level} accuracy "
            f"(kppa={kppa}, {style})."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOLS — make_supercell / add_vacuum / make_slab / convert_structure (Step 5.5)
# ─────────────────────────────────────────────────────────────────────────────


def _build_tag(operation: str, *, scaling=None, axis=None, miller=None):
    """Operation tag for the labeled POSCAR copy (BS1), e.g. 'slab111', '2x2x1'."""
    if operation == "make_supercell":
        vals = str(scaling or "").replace(",", " ").split()
        if len(vals) == 1 and vals[0]:
            return f"{vals[0]}x{vals[0]}x{vals[0]}"
        if len(vals) == 3:
            return "x".join(vals)
        return "supercell"
    if operation == "add_vacuum":
        return f"vacuum-{str(axis).lower().strip()}"
    if operation == "make_slab":
        return "slab" + "".join(str(miller or "").replace(",", " ").split())
    return None


def _predicted_supercell_atoms(n_atoms: int, scaling) -> Optional[int]:
    """Atoms a supercell *would* have, for a pre-build cap check. None if unparsable.

    Delegates to ``builder.supercell_multiplier`` so it covers every scaling
    variety (uniform / per-axis / 3×3 matrix) and never drifts from make_supercell.
    """
    try:
        return n_atoms * builder.supercell_multiplier(scaling)
    except (ValueError, TypeError):
        return None


def _resolve_build_input(material_id, source, poscar_path):
    """Resolve the structure to transform: a database id, or the active session POSCAR."""
    if material_id:
        return _resolve_structure(material_id, source, None)
    try:
        path = find_structure_in_session(poscar_path)
    except FileNotFoundError as e:
        raise _StructureError(str(e))
    return _parse_structure(path)


def _convert_structure(structure, to_format: str) -> dict:
    """Write `structure` in the requested format into the session; return the envelope."""
    fmt = (to_format or "").lower().strip()
    if fmt not in builder.CONVERT_EXT:
        return {"status": "error",
                "message": (f"Invalid format '{to_format}'. Use: "
                            f"{' | '.join(builder.CONVERT_EXT)}.")}
    try:
        content = builder.to_format(structure, fmt)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"convert failed: {e}"}

    formula = structure.composition.reduced_formula
    fname = f"{formula}.{builder.CONVERT_EXT[fmt]}"
    try:
        (session_dir() / fname).write_text(content)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Could not write {fname}: {e}"}

    return {
        "status":        "success",
        "operation":     "convert",
        "formula":       formula,
        "format":        fmt,
        "files_written": [fname],
        "message": f"convert: wrote {formula} as {fmt.upper()} ({fname}).",
    }


def _finish_build(result, operation: str, n_before: int, *, tag, detail: str) -> dict:
    """Cap-check, write the result as the active POSCAR, return a uniform envelope.

    Shared by make_supercell / add_vacuum / make_slab. `detail` is the
    operation-specific phrase for the success message; `tag` labels the saved
    ``POSCAR_<formula>`` copy.
    """
    if len(result) > settings.max_atoms:
        return {"status": "error",
                "message": (f"The result has {len(result)} atoms, above the "
                            f"{settings.max_atoms}-atom limit on this server. "
                            "Use smaller parameters.")}

    formula = result.composition.reduced_formula
    try:
        wp = write_poscar(result, session_dir(), name=formula, tag=tag)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Could not write the structure: {e}"}

    return {
        "status":         "success",
        "operation":      operation,
        "formula":        formula,
        "n_sites_before": n_before,
        "n_sites":        len(result),
        "lattice_abc":    [round(x, 4) for x in result.lattice.abc],
        "files_written":  wp["files_written"],
        "message": (
            f"{operation}: {formula} {detail}. "
            f"Wrote {wp['files_written'][-1]} (active as POSCAR) for the next step."
        ),
    }


def make_supercell(
    scaling:     str,
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
    poscar_path: Optional[str] = None,
) -> dict:
    """Replicate a crystal cell into a supercell and save it as the active POSCAR.

    `scaling` sizes the cell, e.g. "2 2 1" (per-axis) or "2" (uniform 2×2×2).
    Operates on the active session structure by default; pass `poscar_path` for a
    specific session file or `material_id` (+ `source`) to fetch one from a database.
    Writes ``POSCAR`` + ``POSCAR_<formula>`` so the result chains into the next tool.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    n_before = len(structure)
    # Reject an oversized supercell BEFORE building it (cheap + deterministic).
    predicted = _predicted_supercell_atoms(n_before, scaling)
    if predicted and predicted > settings.max_atoms:
        return {"status": "error",
                "message": (f"A '{scaling}' supercell of this {n_before}-atom cell "
                            f"would be {predicted} atoms, above the "
                            f"{settings.max_atoms}-atom limit. Use a smaller scaling.")}

    try:
        result = builder.make_supercell(structure, scaling)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"make_supercell failed: {e}"}

    tag = _build_tag("make_supercell", scaling=scaling)
    detail = f"now has {len(result)} atoms (was {n_before})"
    return _finish_build(result, "make_supercell", n_before, tag=tag, detail=detail)


def add_vacuum(
    axis:        str   = "c",
    thickness:   float = 15.0,
    side:        str   = "both",
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
    poscar_path: Optional[str] = None,
) -> dict:
    """Set the vacuum gap along one axis to exactly `thickness` Å (active POSCAR).

    Resizes the cell so the gap to the next periodic image is exactly `thickness`
    Å along `axis` ("a"/"b"/"c") — independent of any existing padding. `side`
    places the slab: "both" (centred, default), "top" (all vacuum above), or
    "bottom" (all vacuum below). For 2D layers, molecules, or padding a slab.
    (make_slab already includes vacuum, so do NOT call this on a slab it produced.)
    Operates on the active session structure by default; pass `poscar_path` for a
    specific session file or `material_id` (+ `source`) to fetch one from a database.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    n_before = len(structure)
    try:
        result = builder.add_vacuum(structure, axis=axis, thickness=thickness,
                                    side=side)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"add_vacuum failed: {e}"}

    abc = [round(x, 4) for x in result.lattice.abc]
    tag = _build_tag("add_vacuum", axis=axis)
    detail = f"{thickness} Å vacuum on {side} along {axis} → lattice abc = {abc} Å"
    return _finish_build(result, "add_vacuum", n_before, tag=tag, detail=detail)


def make_slab(
    miller:          str   = "1 1 1",
    layers:          Optional[int] = None,
    min_slab_size:   float = 10.0,
    min_vacuum_size: float = 15.0,
    center:          bool  = True,
    lll_reduce:      bool  = True,
    shift:           float = 0.0,
    material_id:     Optional[str] = None,
    source:          Optional[str] = None,
    poscar_path:     Optional[str] = None,
) -> dict:
    """Cut a surface slab along a Miller index and save it as the active POSCAR.

    Cuts along `miller` (e.g. "1 1 1"). Set `layers` for an EXACT count of complete
    structural repeat units — one full crystal thickness per layer, so stoichiometry
    stays intact (what users mean by "N layers"); otherwise the slab is sized to `min_slab_size`
    Å thick. Vacuum (`min_vacuum_size` Å) is INCLUDED — do NOT also call add_vacuum.
    `shift` selects which surface termination; `lll_reduce` reduces the slab cell.
    Operates on the active session structure by default; pass `poscar_path` for a
    specific session file or `material_id` (+ `source`) to fetch one from a database.
    For an in-plane supercell, call make_supercell afterwards (e.g. "2 2 1"); to
    change the vacuum gap precisely, use add_vacuum — each is its own tool.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    n_before = len(structure)
    try:
        result = builder.make_slab(structure, miller=miller, layers=layers,
                                   min_slab_size=min_slab_size,
                                   min_vacuum_size=min_vacuum_size,
                                   center_slab=center, lll_reduce=lll_reduce,
                                   shift=shift)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"make_slab failed: {e}"}

    abc = [round(x, 4) for x in result.lattice.abc]
    tag = _build_tag("make_slab", miller=miller)
    size = f"{layers}-layer" if layers is not None else f"{min_slab_size} Å"
    detail = f"({miller}) {size} slab with {len(result)} atoms, abc = {abc} Å"
    return _finish_build(result, "make_slab", n_before, tag=tag, detail=detail)


def _ensure_slab(structure, material_type, *, miller, layers, min_vacuum_size):
    """Return ``(slab, built)`` — build a slab from a bulk crystal when needed.

    ``material_type``: "slab" adsorbs the input as-is; "bulk" always cuts a slab
    first; "auto" (default) cuts one only when the input has no vacuum gap (i.e. it
    is a space-filling bulk crystal). Slab-cut parameters (``miller`` / ``layers`` /
    ``min_vacuum_size``) are only used when a slab actually has to be built.
    """
    mt = (material_type or "auto").lower().strip()
    if mt not in ("auto", "bulk", "slab"):
        raise _StructureError('material_type must be "auto", "bulk" or "slab".')
    need = mt == "bulk" or (mt == "auto" and not builder.has_vacuum_gap(structure))
    if not need:
        return structure, False
    try:
        slab = builder.make_slab(structure, miller=miller, layers=layers,
                                 min_vacuum_size=min_vacuum_size)
    except Exception as e:  # noqa: BLE001
        raise _StructureError(f"could not build a slab from the bulk input: {e}")
    return slab, True


def add_adsorbate(
    molecule:         str,
    site_type:        str   = "ontop",
    distance:         float = 2.0,
    atom_index:       Optional[int] = None,
    relax:            bool  = False,
    calculator_type:  Optional[str] = None,
    calculator_model: Optional[str] = None,
    material_type:    str   = "auto",
    miller:           str   = "1 1 1",
    layers:           int   = 4,
    min_vacuum_size:  float = 15.0,
    material_id:      Optional[str] = None,
    source:           Optional[str] = None,
    poscar_path:      Optional[str] = None,
) -> dict:
    """Adsorb a molecule (e.g. CO2) onto a surface slab.

    `material_type` controls the input: "slab" adsorbs the structure as-is, "bulk"
    cuts a slab first (along `miller`, `layers` thick, `min_vacuum_size` Å vacuum),
    and "auto" (default) detects which — building a slab only when the input is a
    space-filling bulk crystal, so the user can hand over either a bulk or a slab.

    Default (relax=False): place the molecule geometrically on an auto-picked site
    (first symmetry-reduced `site_type`, "ontop" by default) at `distance` Å above the
    surface, save it as the active POSCAR, and return immediately. Pass `atom_index`
    (0-based) to place it directly above a specific slab atom instead of a site_type.

    relax=True: run an accurate AdsorbML-style background job — enumerate placements,
    relax each with an ML potential (MACE/MatterSim), discard desorbed/dissociated
    configs, and return the lowest adsorption-energy structure. Returns a job_id.

    Operates on the active session structure; pass `poscar_path` / `material_id`
    (+ `source`) for another source.
    """
    from app.services.structure import adsorption

    if relax:
        if atom_index is not None:
            return {"status": "error", "message": (
                "atom_index placement is only available in fast geometric mode "
                "(relax=False); accurate relax mode enumerates and ranks sites itself.")}
        try:
            slab_path = find_structure_in_session(poscar_path)
        except FileNotFoundError as e:
            return {"status": "error", "message": str(e)}
        # Cut a slab from a bulk input first (if needed), then relax on that slab.
        try:
            slab, built = _ensure_slab(_parse_structure(slab_path), material_type,
                                       miller=miller, layers=layers,
                                       min_vacuum_size=min_vacuum_size)
        except _StructureError as e:
            return {"status": "error", "message": str(e)}
        if built:
            if len(slab) > settings.max_atoms:
                return {"status": "error", "message": (
                    f"The built slab has {len(slab)} atoms, above the "
                    f"{settings.max_atoms}-atom limit on this server. "
                    "Use fewer layers or a smaller Miller index.")}
            wp = write_poscar(slab, session_dir(),
                              name=slab.composition.reduced_formula, tag="slab")
            slab_path = Path(wp["poscar_path"])
        calc_cfg = _resolve_calculator(calculator_type, calculator_model)
        if calc_cfg.get("status") == "error":
            return calc_cfg
        result = _enqueue_job(
            JobType.ADSORPTION,
            poscar_path=slab_path,
            output_dir=session_path() / "adsorption",
            params={"molecule": molecule, "site_type": site_type,
                    "distance": float(distance)},
            calculator=calc_cfg,
            emit_vasp_inputs=False,
        )
        if result.get("status") == "queued":
            result["calculator"] = calc_cfg
            result["message"] = (
                f"{result['message']} Relaxing {molecule} adsorption with "
                f"{_calc_label(calc_cfg)}.")
        return result

    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
        structure, built_slab = _ensure_slab(structure, material_type, miller=miller,
                                             layers=layers, min_vacuum_size=min_vacuum_size)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    n_before = len(structure)
    try:
        result = adsorption.place_adsorbate(structure, molecule=molecule,
                                            site_type=site_type, distance=distance,
                                            atom_index=atom_index)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"add_adsorbate failed: {e}"}

    tag = f"ads-{str(molecule).strip().lower()}"
    where = f"atom #{atom_index}" if atom_index is not None else f"{site_type} site"
    prefix = f"built {miller} slab, then " if built_slab else ""
    detail = (f"{prefix}{molecule} on {where} (+{len(result) - n_before} atoms); "
              f"now {len(result)} atoms")
    return _finish_build(result, "add_adsorbate", n_before, tag=tag, detail=detail)


def convert_structure(
    to_format:   str = "cif",
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
    poscar_path: Optional[str] = None,
) -> dict:
    """Write a structure in another file format. Does NOT change the active POSCAR.

    `to_format` is one of: poscar | cif | xyz | cssr | json. Operates on the active
    session structure by default; pass `poscar_path` for a specific session file or
    `material_id` (+ `source`) to fetch one from a database.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}
    return _convert_structure(structure, to_format)


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — analyze_symmetry  (read-only; Step 5.5)
# ─────────────────────────────────────────────────────────────────────────────

def analyze_symmetry(
    poscar_path: Optional[str] = None,
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
    symprec:     float         = 0.01,
    write:       Optional[str] = None,
) -> dict:
    """Report the symmetry of a structure (space group, point group, crystal system).

    Read-only by default. Set `write` to "primitive" or "conventional" to also save
    that standard cell as the active POSCAR. Operates on the active session
    structure unless `poscar_path` or `material_id` (+ `source`) is given.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    try:
        data = builder.analyze_symmetry(structure, symprec=symprec)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Symmetry analysis failed: {e}"}

    files_written: list[str] = []
    write_kind = (write or "").lower().strip()
    if write_kind in ("primitive", "conventional"):
        try:
            std = builder.standard_structure(structure, write_kind, symprec=symprec)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"Could not build the {write_kind} cell: {e}"}
        if len(std) > settings.max_atoms:
            return {"status": "error",
                    "message": (f"The {write_kind} cell has {len(std)} atoms, above the "
                                f"{settings.max_atoms}-atom limit.")}
        formula = std.composition.reduced_formula
        tag = {"primitive": "prim", "conventional": "conv"}.get(write_kind)
        try:
            wp = write_poscar(std, session_dir(), name=formula, tag=tag)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"Could not write the structure: {e}"}
        files_written = wp["files_written"]
    elif write_kind:
        return {"status": "error",
                "message": f"Invalid write '{write}'. Use: primitive | conventional (or omit)."}

    sg = f"{data['space_group_symbol']} (#{data['space_group_number']})"
    msg = (f"Symmetry: space group {sg}, point group {data['point_group']}, "
           f"{data['crystal_system']} system, {data['n_symmetry_ops']} symmetry operations.")
    if files_written:
        msg += f" Wrote the {write_kind} cell as the active POSCAR."

    return {"status": "success", **data, "files_written": files_written, "message": msg}


# ─────────────────────────────────────────────────────────────────────────────
# TOOLS — create_vacancy / create_substitution / create_interstitial (Step 5.5)
# ─────────────────────────────────────────────────────────────────────────────

def _finish_defect(sc, defect_name: str, kind: str, n_bulk: int,
                   tag: Optional[str] = None) -> dict:
    """Atom-cap, write the defective supercell as the active POSCAR, return the envelope."""
    if len(sc) > settings.max_atoms:
        return {"status": "error",
                "message": (f"The {kind} structure has {len(sc)} atoms, above the "
                            f"{settings.max_atoms}-atom limit. Use a smaller cell.")}
    formula = sc.composition.reduced_formula
    try:
        wp = write_poscar(sc, session_dir(), name=formula, tag=tag)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Could not write the structure: {e}"}
    return {
        "status":        "success",
        "defect":        kind,
        "defect_name":   defect_name,
        "formula":       formula,
        "n_sites":       len(sc),
        "files_written": wp["files_written"],
        "message": (
            f"Created {kind} ({defect_name}); structure now has {len(sc)} atoms. "
            f"Wrote {wp['files_written'][-1]} (active as POSCAR) for the next step. "
            "To make it a CHARGED defect, run generate_vasp_inputs with a `charge` "
            "value (it sets NELECT)."
        ),
    }


def create_vacancy(
    element:     Optional[str] = None,
    count:       Optional[str] = None,
    poscar_path: Optional[str] = None,
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
) -> dict:
    """Remove one or more atoms to make vacancies, saved as the active POSCAR.

    `element` selects which species to remove (defaults to the first site found).
    `count` is how many to remove — a number (e.g. "3") or "all"; defaults to 1.
    Operates on the current cell; call make_supercell first for a dilute defect.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}
    try:
        sc, name = builder.create_vacancy(structure, element=element, count=count)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Vacancy creation failed: {e}"}
    tag = f"vac-{element}" if element else "vac"
    return _finish_defect(sc, name, "vacancy", len(structure), tag=tag)


def create_substitution(
    from_element: str,
    to_element:   str,
    count:        Optional[str] = None,
    poscar_path:  Optional[str] = None,
    material_id:  Optional[str] = None,
    source:       Optional[str] = None,
) -> dict:
    """Replace one or more `from_element` atoms with `to_element`; save active POSCAR.

    `count` is how many to replace — a number (e.g. "3") or "all"; defaults to 1.
    Operates on the current cell.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}
    try:
        sc, name = builder.create_substitution(
            structure, from_element=from_element, to_element=to_element, count=count)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Substitution failed: {e}"}
    return _finish_defect(sc, name, "substitution", len(structure),
                          tag=f"sub-{from_element}-{to_element}")


def create_interstitial(
    insert_element: str,
    count:          Optional[str] = None,
    poscar_path:    Optional[str] = None,
    material_id:    Optional[str] = None,
    source:         Optional[str] = None,
) -> dict:
    """Insert one or more atoms at Voronoi interstitial sites; save active POSCAR.

    `count` is how many to insert — a number (e.g. "3") or "all"; defaults to 1.
    Operates on the current cell; call make_supercell first for a dilute defect.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}
    try:
        sc, name = builder.create_interstitial(
            structure, insert_element=insert_element, count=count)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Interstitial creation failed: {e}"}
    return _finish_defect(sc, name, "interstitial", len(structure),
                          tag=f"int-{insert_element}")


# ─────────────────────────────────────────────────────────────────────────────
# File-classification helper (shared by read_file + list_files)
# ─────────────────────────────────────────────────────────────────────────────

_STRUCTURE_EXTS = activation.STRUCTURE_EXTS   # shared widened set (Phase E)
_MAX_PREVIEW_CHARS = 4000


def _classify_file(path: Path) -> str:
    """Return a short human-readable type label for a session file."""
    name = path.name
    upper = name.upper()
    suffix = path.suffix.lower()

    if upper.startswith("POSCAR") or suffix == ".vasp":
        return "Crystal structure (POSCAR)"
    if upper.startswith("CONTCAR"):
        return "Relaxed structure (CONTCAR)"
    if suffix == ".cif":
        return "CIF structure"
    if suffix == ".xyz":
        return "XYZ structure"
    if upper == "INCAR":
        return "VASP INCAR (settings)"
    if upper == "KPOINTS":
        return "VASP KPOINTS (k-mesh)"
    if upper.startswith("POTCAR"):
        return "VASP POTCAR (pseudopotential)"
    if upper in ("OUTCAR", "OSZICAR", "XDATCAR"):
        return f"VASP output ({name})"
    if "trajectory" in name.lower() or suffix == ".traj":
        return "Trajectory (MD/optimization)"
    if suffix == ".csv":
        return "Data table (CSV)"
    if suffix == ".json":
        return "JSON data"
    if suffix == ".log":
        return "Log file"
    if suffix == ".png":
        return "Plot image"
    if activation.is_structure_file(name):
        return "Crystal structure"
    return "File"


def _is_structure_file(path: Path) -> bool:
    return activation.is_structure_file(path.name)


def _parse_structure(path: Path):
    """Parse a structure file (pymatgen → ASE fallback) via the shared service."""
    try:
        return activation.parse_structure(path)
    except activation.StructureParseError as e:
        raise _StructureError(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — read_file
# ─────────────────────────────────────────────────────────────────────────────

def _newest_upload() -> Optional[Path]:
    """Return the most-recently-modified file under the session's uploads/ folder."""
    up = session_path() / "uploads"
    if not up.exists():
        return None
    files = sorted(
        [p for p in up.rglob("*") if p.is_file()],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return files[0] if files else None


def read_file(filename: Optional[str] = None) -> dict:
    """Read and parse a file in the current session.

    Structure files (POSCAR/CONTCAR/CIF/XYZ/.vasp) are parsed and *activated*: a
    canonical POSCAR is written into the session root so optimize / MD / VASP
    tools operate on them. Text/config files (INCAR/KPOINTS/CSV/JSON/…) are
    returned as a trimmed preview. Omit `filename` to read the latest upload.
    """
    if filename:
        try:
            path = safe_file_in_session(filename)
        except (FileNotFoundError, PermissionError) as e:
            return {"status": "error", "message": str(e)}
    else:
        path = _newest_upload()
        if path is None:
            try:
                path = safe_file_in_session("auto")
            except FileNotFoundError as e:
                return {"status": "error", "message": str(e)}

    if _is_structure_file(path):
        return _read_structure_file(path)
    return _read_text_file(path)


def _read_structure_file(path: Path) -> dict:
    try:
        structure = _parse_structure(path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    formula = structure.composition.reduced_formula

    # Disordered structures (partial occupancies) can't be a POSCAR; keep them as a
    # .cif so generate_sqs can consume them. (Optimize/MD/VASP need an ordered cell.)
    if not structure.is_ordered:
        try:
            from pymatgen.io.cif import CifWriter
            out = session_dir() / f"{formula}_disordered.cif"
            CifWriter(structure).write_file(str(out))
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"Could not activate structure: {e}"}
        return {
            "status":        "success",
            "file_type":     "structure",
            "source_file":   path.name,
            "formula":       formula,
            "n_sites":       len(structure),
            "lattice_a":     round(structure.lattice.a, 4),
            "lattice_b":     round(structure.lattice.b, 4),
            "lattice_c":     round(structure.lattice.c, 4),
            "elements":      [str(e) for e in structure.composition.elements],
            "disordered":    True,
            "files_written": [out.name],
            "message": (
                f"Read {path.name}: {formula} ({len(structure)} atoms), a DISORDERED "
                f"structure (partial occupancies). Saved as {out.name} — ready for "
                "generate_sqs. (Optimization/MD/VASP need an ordered structure.)"
            ),
        }

    try:
        wp = write_poscar(structure, session_dir(), name=formula)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Could not activate structure: {e}"}

    return {
        "status":        "success",
        "file_type":     "structure",
        "source_file":   path.name,
        "formula":       formula,
        "n_sites":       len(structure),
        "lattice_a":     round(structure.lattice.a, 4),
        "lattice_b":     round(structure.lattice.b, 4),
        "lattice_c":     round(structure.lattice.c, 4),
        "elements":      [str(e) for e in structure.composition.elements],
        "disordered":    False,
        "files_written": wp["files_written"],
        "message": (
            f"Read {path.name}: {formula} ({len(structure)} atoms). Wrote POSCAR — "
            "this structure is now active for optimization, MD, or VASP inputs."
        ),
    }


def _read_text_file(path: Path) -> dict:
    try:
        text = path.read_text(errors="replace")
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Could not read '{path.name}': {e}"}

    truncated = len(text) > _MAX_PREVIEW_CHARS
    preview = text[:_MAX_PREVIEW_CHARS] + ("\n…(truncated)" if truncated else "")
    return {
        "status":          "success",
        "file_type":       _classify_file(path),
        "source_file":     path.name,
        "n_lines":         text.count("\n") + 1,
        "size_kb":         round(path.stat().st_size / 1024, 2),
        "truncated":       truncated,
        "content_preview": preview,
        "message":         f"Read {path.name} ({_classify_file(path)}).",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — list_files
# ─────────────────────────────────────────────────────────────────────────────

def list_files() -> dict:
    """List every file in the current session with type, time and description."""
    session_id = get_session_id()
    if not session_id:
        return {"status": "error", "message": "No active session yet.", "files": []}

    files = []
    for entry in list_session_files(session_id):
        rel = entry["rel_path"]
        abs_path = STORAGE_ROOT / rel
        uploaded = "uploads" in Path(rel).parts
        label = _classify_file(abs_path)
        try:
            when = datetime.fromtimestamp(
                abs_path.stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            when = None
        files.append({
            "name":        entry["name"],
            "type":        label,
            "uploaded":    uploaded,
            "time":        when,
            "size_kb":     entry["size_kb"],
            "rel_path":    rel,
            "description": label + (" — uploaded by user" if uploaded else ""),
        })

    if not files:
        return {"status": "ok", "files": [], "message": "No files in this session yet."}
    return {
        "status":  "ok",
        "files":   files,
        "message": f"{len(files)} file(s) in this session.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — list_models
# ─────────────────────────────────────────────────────────────────────────────

def list_models() -> dict:
    """List the available ML-potential models (MACE / MatterSim) with variants."""
    available = list_available_models()
    defaults = {"mace": DEFAULT_MACE_MODEL, "mattersim": DEFAULT_MATTERSIM_MODEL}

    models = []
    for ctype, entries in available.items():
        for e in entries:
            models.append({
                "calculator": ctype,
                "name":       e["name"],
                "is_default": e["name"] == defaults.get(ctype),
                "available":  e["exists"],
                "aliases":    MODEL_ALIAS_HINTS.get(e["name"], []),
            })

    n_mace = len(available.get("mace", []))
    n_ms = len(available.get("mattersim", []))
    return {
        "status":              "ok",
        "default_calculator":  "mace",
        "models":              models,
        "message": (
            f"2 potentials available: MACE ({n_mace} variants) and "
            f"MatterSim ({n_ms} variants)."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — optimize_structure
# ─────────────────────────────────────────────────────────────────────────────

def optimize_structure(
    poscar_name:      Optional[str] = None,
    fmax:             float         = 0.02,
    cell_relax:       str           = "none",
    optimizer:        str           = "FIRE",
    max_steps:        int           = 1000,
    calculator_type:  str           = "mace",
    calculator_model: Optional[str] = None,
    emit_vasp_inputs: bool          = False,
) -> dict:
    """Queue an ASE geometry optimization job for a structure in the session.

    Optimization does ONLY the relaxation of the active structure (V3): it does
    not generate VASP inputs unless `emit_vasp_inputs=True` is explicitly passed.
    Long-running, so this enqueues a job and returns immediately with a
    ``job_id``; progress and results are tracked via ``/api/jobs`` (redesign §11).
    """
    cell_relax = cell_relax.lower().strip()
    if cell_relax not in ("none", "shape", "full"):
        return {"status": "error", "message": f"Invalid cell_relax '{cell_relax}'. Use: none | shape | full"}

    optimizer = optimizer.upper().strip()
    if optimizer not in ("FIRE", "BFGS", "LBFGS"):
        return {"status": "error", "message": f"Invalid optimizer '{optimizer}'. Use: FIRE | BFGS | LBFGS"}

    if cell_relax != "none" and optimizer == "BFGS":
        optimizer = "FIRE"  # BFGS does not support cell DOF

    fmax      = max(float(fmax), 0.001)
    max_steps = min(max(int(max_steps), 1), settings.max_opt_steps)

    try:
        poscar_path = find_structure_in_session(poscar_name, prefer_contcar=False)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    too_big = _enforce_atom_cap(poscar_path)
    if too_big:
        return too_big

    calc_cfg = _resolve_calculator(calculator_type, calculator_model)
    if calc_cfg.get("status") == "error":
        return calc_cfg

    result = _enqueue_job(
        JobType.OPTIMIZE,
        poscar_path=poscar_path,
        output_dir=session_path() / "optimization",
        params={"fmax": fmax, "cell_relax": cell_relax,
                "optimizer": optimizer, "max_steps": max_steps},
        calculator=calc_cfg,
        emit_vasp_inputs=emit_vasp_inputs,
    )
    if result.get("status") == "queued":
        result["calculator"] = calc_cfg
        result["message"] = f"{result['message']} Using {_calc_label(calc_cfg)}."
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — run_md_simulation
# ─────────────────────────────────────────────────────────────────────────────

def run_md_simulation(
    poscar_name:      Optional[str] = None,
    ensemble:         str           = "nvt",
    temperature:      float         = 300.0,
    nsw:              int           = 2000,
    timestep:         float         = 1.0,
    thermostat:       str           = "langevin",
    pressure:         float         = 0.0,
    calculator_type:  str           = "mace",
    calculator_model: Optional[str] = None,
    log_interval:     int           = 10,
    emit_vasp_inputs: bool          = True,
) -> dict:
    """Queue an ASE Molecular Dynamics (NVT/NPT/NVE) job for a session structure.

    Long-running, so this enqueues a job and returns a ``job_id`` immediately;
    progress/results are tracked via ``/api/jobs`` (redesign §11).
    """
    ensemble = ensemble.lower().strip()
    if ensemble not in ("nvt", "npt", "nve"):
        return {"status": "error", "message": f"Invalid ensemble '{ensemble}'. Use: nvt | npt | nve"}

    thermostat = thermostat.lower().strip() or ("langevin" if ensemble == "nvt" else "berendsen")

    temperature   = max(float(temperature), 1.0)
    nsw           = min(max(int(nsw), 1), settings.max_md_steps)
    timestep      = max(float(timestep), 0.1)
    log_interval  = max(int(log_interval), 1)

    try:
        poscar_path = find_structure_in_session(poscar_name, prefer_contcar=True)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    too_big = _enforce_atom_cap(poscar_path)
    if too_big:
        return too_big

    calc_cfg = _resolve_calculator(calculator_type, calculator_model)
    if calc_cfg.get("status") == "error":
        return calc_cfg

    result = _enqueue_job(
        JobType.MD,
        poscar_path=poscar_path,
        output_dir=session_path() / "md_simulation",
        params={"ensemble": ensemble, "temperature": temperature, "nsw": nsw,
                "timestep": timestep, "thermostat": thermostat,
                "pressure": pressure, "log_interval": log_interval},
        calculator=calc_cfg,
        emit_vasp_inputs=emit_vasp_inputs,
    )
    if result.get("status") == "queued":
        result["calculator"] = calc_cfg
        result["message"] = f"{result['message']} Using {_calc_label(calc_cfg)}."
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — compute_elastic_tensor  (Step 5.7)
# ─────────────────────────────────────────────────────────────────────────────

def compute_elastic_tensor(
    poscar_name:      Optional[str] = None,
    material_id:      Optional[str] = None,
    source:           Optional[str] = None,
    fmax:             float         = 0.01,
    max_steps:        int           = 300,
    relax_mode:       str           = "full",
    calculator_type:  str           = "mace",
    calculator_model: Optional[str] = None,
    emit_vasp_inputs: bool          = True,
) -> dict:
    """Queue an elastic-tensor / mechanical-properties job (K, G, E, ν, Pugh, AU).

    Relaxes the cell, then strains it to read the 6×6 elastic tensor via the ML
    potential. Detects 2D materials and reports in-plane 2D moduli (N/m). Long-
    running, so this enqueues a job and returns a ``job_id`` immediately.
    """
    fmax      = max(float(fmax), 0.001)
    max_steps = min(max(int(max_steps), 1), settings.max_opt_steps)
    relax_mode = (relax_mode or "full").lower().strip()
    if relax_mode not in ("positions", "shape", "full"):
        relax_mode = "full"

    # Optionally materialize a database structure as the active POSCAR first.
    if material_id:
        try:
            structure = _resolve_structure(material_id, source, None)
            write_poscar(structure, session_dir(), name=structure.composition.reduced_formula)
        except _StructureError as e:
            return {"status": "error", "message": str(e)}

    try:
        poscar_path = find_structure_in_session(poscar_name, prefer_contcar=False)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    too_big = _enforce_atom_cap(poscar_path)
    if too_big:
        return too_big

    calc_cfg = _resolve_calculator(calculator_type, calculator_model)
    if calc_cfg.get("status") == "error":
        return calc_cfg

    result = _enqueue_job(
        JobType.ELASTIC,
        poscar_path=poscar_path,
        output_dir=session_path() / "elastic",
        params={"fmax": fmax, "max_steps": max_steps, "relax_mode": relax_mode},
        calculator=calc_cfg,
        emit_vasp_inputs=emit_vasp_inputs,
    )
    if result.get("status") == "queued":
        result["calculator"] = calc_cfg
        result["message"] = f"{result['message']} Using {_calc_label(calc_cfg)}."
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — compute_phonons  (Step 5.7)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_supercell(text: str) -> tuple:
    """Parse "3 3 3" / "2" → a 3-tuple of positive ints (defaults to 3×3×3)."""
    parts = [p for p in str(text).replace(",", " ").split() if p]
    if len(parts) == 1:
        n = max(int(parts[0]), 1)
        return (n, n, n)
    if len(parts) == 3:
        return tuple(max(int(p), 1) for p in parts)
    raise ValueError(f"Invalid supercell '{text}'. Use '3 3 3' or a single number.")


def compute_phonons(
    poscar_name:      Optional[str] = None,
    material_id:      Optional[str] = None,
    source:           Optional[str] = None,
    supercell:        str           = "3 3 3",
    disp_distance:    float         = 0.01,
    mesh:             int           = 20,
    calculator_type:  str           = "mace",
    calculator_model: Optional[str] = None,
) -> dict:
    """Queue a phonon band-structure + DOS job (finite displacements, ML forces).

    Builds a supercell, displaces atoms, computes forces with the ML potential,
    and produces a phonon band/DOS plot plus phonopy.yaml. Long-running, so this
    enqueues a job and returns a ``job_id`` immediately.
    """
    try:
        sc = _parse_supercell(supercell)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    disp_distance = max(float(disp_distance), 0.001)
    mesh = min(max(int(mesh), 5), 60)

    # Optionally materialize a database structure as the active POSCAR first.
    if material_id:
        try:
            structure = _resolve_structure(material_id, source, None)
            write_poscar(structure, session_dir(), name=structure.composition.reduced_formula)
        except _StructureError as e:
            return {"status": "error", "message": str(e)}

    try:
        poscar_path = find_structure_in_session(poscar_name, prefer_contcar=False)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    # Atom cap applies to the SUPERCELL (n_primitive × Nx×Ny×Nz), not the input.
    try:
        from pymatgen.core import Structure
        n_prim = len(Structure.from_file(str(poscar_path)))
        n_super = n_prim * sc[0] * sc[1] * sc[2]
        if n_super > settings.max_atoms:
            return {
                "status": "error",
                "message": (
                    f"A {sc[0]}×{sc[1]}×{sc[2]} supercell of this {n_prim}-atom cell is "
                    f"{n_super} atoms, above the {settings.max_atoms}-atom limit. "
                    "Use a smaller supercell or a smaller unit cell."
                ),
            }
    except Exception:  # noqa: BLE001 — let the worker surface a real parse error
        pass

    calc_cfg = _resolve_calculator(calculator_type, calculator_model)
    if calc_cfg.get("status") == "error":
        return calc_cfg

    result = _enqueue_job(
        JobType.PHONON,
        poscar_path=poscar_path,
        output_dir=session_path() / "phonon",
        params={"supercell": list(sc), "disp_distance": disp_distance, "mesh": mesh},
        calculator=calc_cfg,
        emit_vasp_inputs=False,
    )
    if result.get("status") == "queued":
        result["calculator"] = calc_cfg
        result["message"] = f"{result['message']} Using {_calc_label(calc_cfg)}."
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — generate_sqs  (Step 5.7; ATAT mcsqs)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_target_comp(text: Optional[str]) -> Optional[dict]:
    """Parse "Li:1,Ni:0.8,Mn:0.1" → {"Li":1.0,...}; None/blank → None."""
    if not text:
        return None
    out: dict = {}
    for part in str(text).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            el, val = part.split(":", 1)
        elif "=" in part:
            el, val = part.split("=", 1)
        else:
            raise ValueError(
                f"Invalid target_comp entry '{part}'. Use 'El:value' pairs.")
        out[el.strip()] = float(val)
    return out or None


def _parse_substitutions(text: Optional[str]) -> Optional[list]:
    """Parse a partial-substitution spec into [{"from","to","fraction"}, ...].

    Accepts entries like "Si->S:0.25", "Si->S=25%", or "Si:S:0.25", separated by
    commas/semicolons. Means "replace 25% of Si sites' occupancy with S". None/blank
    → None. Raises ValueError on a malformed entry.
    """
    if not text:
        return None
    out: list = []
    for part in str(text).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^\s*([A-Za-z]+)\s*(?:->|:)\s*([A-Za-z]+)\s*[:=]\s*([0-9.]+%?)\s*$",
                     part)
        if not m:
            raise ValueError(
                f"Invalid substitution '{part}'. Use 'From->To:fraction', "
                "e.g. 'Si->S:0.25' (replace 25% of Si with S).")
        frm, to, frac_txt = m.group(1), m.group(2), m.group(3)
        frac = float(frac_txt[:-1]) / 100.0 if frac_txt.endswith("%") else float(frac_txt)
        if frac > 1.0:                    # tolerate "25" meaning 25%
            frac /= 100.0
        out.append({"from": frm, "to": to, "fraction": frac})
    return out or None


def _parse_sublattice_comp(text: Optional[str]) -> Optional[dict]:
    """Parse a per-sublattice composition into ``{sublattice: {El: frac}}``.

    Accepts entries like ``"Ti=Ti0.6,Zr0.4; Sr=Sr0.6,Ba0.4"`` (semicolon between
    sublattices, ``=`` or ``:`` between the sublattice key and its occupancy,
    comma/space between element tokens). Each element token is ``El<number>``,
    e.g. ``Zr0.4``. None/blank → None. Raises ValueError on a malformed entry.
    """
    if not text:
        return None
    out: dict = {}
    for entry in str(text).split(";"):
        entry = entry.strip()
        if not entry:
            continue
        m = re.match(r"^\s*([A-Za-z][A-Za-z0-9()]*?)\s*[=:]\s*(.+)$", entry)
        if not m:
            raise ValueError(
                f"Invalid sublattice composition '{entry}'. Use "
                "'Sublattice=El1frac1,El2frac2', e.g. 'Ti=Ti0.6,Zr0.4'.")
        key, rest = m.group(1), m.group(2)
        occ: dict = {}
        for tok in re.split(r"[,\s]+", rest.strip()):
            if not tok:
                continue
            tm = re.match(r"^([A-Za-z]+)\s*([0-9]*\.?[0-9]+)$", tok)
            if not tm:
                raise ValueError(
                    f"Invalid occupancy token '{tok}' for sublattice '{key}'. "
                    "Use 'El<fraction>', e.g. 'Zr0.4'.")
            occ[tm.group(1)] = float(tm.group(2))
        if not occ:
            raise ValueError(f"No occupancies given for sublattice '{key}'.")
        out[key] = occ
    return out or None


def list_sublattices(
    cif_name: Optional[str] = None,
    symprec:  float         = 0.1,
) -> dict:
    """List the symmetry-distinct sublattices (Wyckoff sites) of a structure.

    Use this BEFORE generate_sqs to see which sites you can turn into a random
    alloy. For SrTiO₃ it reports an Sr site, a Ti site and an O site; the user
    then picks one and gives a composition (e.g. "Ti=Ti0.6,Zr0.4"). Reads the
    active structure if ``cif_name`` is omitted. Fast — returns immediately.
    """
    try:
        cif_path = find_structure_in_session(cif_name, prefer_contcar=True)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}
    from app.services.simulation.sqs import list_sublattices as _list
    return _list(str(cif_path), symprec=float(symprec))


def generate_sqs(
    cif_name:         Optional[str] = None,
    sublattice_comp:  Optional[str] = None,
    target_comp:      Optional[str] = None,
    substitute:       Optional[str] = None,
    supercell:        str           = "2 2 2",
    cutoff:           Optional[float] = None,
    n_parallel:       int           = 4,
    target_objective: float         = -0.99,
    time_budget_s:    int           = 600,
    relax:            bool          = True,
    calculator_type:  str           = "mace",
    calculator_model: Optional[str] = None,
) -> dict:
    """Queue a Special Quasi-random Structure (SQS) job via ATAT mcsqs.

    Works from a **normal ordered structure** (the active POSCAR/material) — no
    disordered CIF required. Define the random alloy with ``sublattice_comp``:
    a per-sublattice target composition like ``"Ti=Ti0.6,Zr0.4"`` (put 60% Ti /
    40% Zr on the Ti sublattice) or ``"Ti=Ti0.6,Zr0.4; Sr=Sr0.6,Ba0.4"`` for two
    sublattices at once. Call ``list_sublattices`` first to see the site names.

    Legacy alternatives still work: ``substitute`` ("Si->S:0.25") or an
    already-disordered CIF. After the search, the SQS supercell is relaxed with an
    ML potential (``relax``/``calculator_type``, MACE by default).

    Long-running, so this enqueues a job and returns a ``job_id`` immediately.
    """
    try:
        sc = _parse_supercell(supercell)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    try:
        comp = _parse_target_comp(target_comp)
        sub_comp = _parse_sublattice_comp(sublattice_comp)
        subs = _parse_substitutions(substitute)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    n_parallel = min(max(int(n_parallel), 1), 16)
    time_budget_s = max(int(time_budget_s), 30)

    calc_cfg = _resolve_calculator(calculator_type, calculator_model) if relax else {}
    if calc_cfg.get("status") == "error":
        return calc_cfg

    try:
        if cif_name:
            cif_path = find_structure_in_session(cif_name, prefer_contcar=True)
        elif not (sub_comp or subs):
            # No composition given: an activated disordered CIF (partial occupancies)
            # is the only thing that can seed an SQS, so prefer it over the POSCAR.
            base = session_path()
            cifs = sorted([p for p in base.rglob("*.cif") if p.is_file()],
                          key=lambda p: p.stat().st_mtime, reverse=True)
            disordered = [p for p in cifs if p.name.endswith("_disordered.cif")]
            cif_path = (disordered or cifs or [None])[0] or find_structure_in_session(
                None, prefer_contcar=True)
        else:
            # Composition given → start from the active ordered structure.
            cif_path = find_structure_in_session(None, prefer_contcar=True)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    result = _enqueue_job(
        JobType.SQS,
        poscar_path=cif_path,
        output_dir=session_path() / "sqs",
        params={
            "target_comp": comp,
            "sublattice_comp": sub_comp,
            "substitutions": subs,
            "supercell": list(sc),
            "cutoff": cutoff,
            "n_parallel": n_parallel,
            "target_objective": float(target_objective),
            "time_budget_s": time_budget_s,
            "relax": bool(relax),
        },
        calculator=calc_cfg if relax else {},
        emit_vasp_inputs=False,
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — compute_neb  (NEB migration barrier; ML potential)
# ─────────────────────────────────────────────────────────────────────────────

def list_migration_paths(
    element:          str,
    cutoff:           float         = 5.0,
    poscar_name:      Optional[str] = None,
    material_id:      Optional[str] = None,
    source:           Optional[str] = None,
    symprec:          float         = 0.1,
) -> dict:
    """List candidate NEB migration hops for a migrating element (no job).

    Finds the symmetry-distinct sites of ``element`` (labelled 1..N) and returns
    every source→destination pair within ``cutoff`` Å, sorted shortest-first — so
    the user can pick a hop (e.g. "1-5") before launching a long NEB.

    Analyses the structure exactly as supplied (no auto-supercell). If the cell is
    small, run ``make_supercell`` first to give the migrating ion enough hop space.
    """
    from app.services.simulation import neb_path

    if material_id:
        try:
            structure = _resolve_structure(material_id, source, None)
            write_poscar(structure, session_dir(),
                         name=structure.composition.reduced_formula)
        except _StructureError as e:
            return {"status": "error", "message": str(e)}

    try:
        path = find_structure_in_session(poscar_name, prefer_contcar=False)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    try:
        sites = neb_path.find_migration_sites(path, element, symprec=symprec)
        pairs = neb_path.list_migration_pairs(path, element, cutoff=cutoff,
                                              symprec=symprec)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Migration-site analysis failed: {e}"}

    if not sites:
        return {"status": "error",
                "message": f"No {element} atoms found in the structure."}

    return {
        "status": "success",
        "element": element,
        "n_sites": len(sites),
        "sites": [{"label": s.label, "frac_coords": list(s.frac_coords),
                   "orbit": s.orbit} for s in sites],
        "pairs": neb_path.pairs_to_rows(pairs),
        "message": (
            f"{element}: {len(sites)} site(s); "
            f"{len(pairs)} candidate hop(s) within {cutoff} Å. "
            f"Pick a pair (e.g. source_site/dest_site) for compute_neb."),
    }


def _build_neb_endpoints(initial_path, element, source_site, dest_site, symprec):
    """Build + write initial/final endpoint POSCARs for a migrating-atom hop.

    Returns ``(initial_path, final_path, info)`` or raises ValueError. The chosen
    hop defaults to the shortest candidate pair when source/dest are not given.

    The endpoints are built from the cell exactly as supplied (no auto-supercell) —
    prepare a large enough cell with ``make_supercell`` first if the ion needs more
    hop space. The MLP relaxation of the endpoints happens later inside the NEB job
    (neb.py).
    """
    from app.services.simulation import neb_path

    pairs = neb_path.list_migration_pairs(initial_path, element, cutoff=0.0,
                                          symprec=symprec)
    if source_site is None or dest_site is None:
        if not pairs:
            raise ValueError(f"No {element} site pairs found to build a hop.")
        chosen = pairs[0]                       # shortest hop
        source_site = source_site or chosen.source_label
        dest_site = dest_site or chosen.dest_label

    initial, final = neb_path.build_migration_endpoints(
        initial_path, element, int(source_site), int(dest_site), symprec=symprec)

    tag = f"{element}_{source_site}-{dest_site}"
    init_res = write_poscar(initial, session_dir(), name="NEB_initial", tag=tag)
    final_res = write_poscar(final, session_dir(), name="NEB_final", tag=tag)
    info = {"migrating_element": element, "source_site": int(source_site),
            "dest_site": int(dest_site)}
    return Path(init_res["named_path"]), Path(final_res["named_path"]), info


def compute_neb(
    poscar_name:       Optional[str] = None,
    final_poscar_name: Optional[str] = None,
    migrating_element: Optional[str] = None,
    source_site:       Optional[int] = None,
    dest_site:         Optional[int] = None,
    n_images:          int           = 8,
    fmax:              float         = 0.05,
    endpoint_fmax:     float         = 0.03,
    max_steps:         int           = 300,
    spring_k:          float         = 1.0,
    climb:             bool          = True,
    relax_endpoints:   bool          = True,
    optimizer:         str           = "FIRE",
    run_frequencies:   bool          = True,
    emit_vasp_inputs:  bool          = True,
    symprec:           float         = 0.1,
    calculator_type:   str           = "mace",
    calculator_model:  Optional[str] = None,
) -> dict:
    """Queue an NEB job: find the migration barrier for an atomic hop.

    Two ways to specify the hop:
      • **Two endpoints** — pass ``final_poscar_name`` (an end-state structure
        already in the session), or
      • **A migrating atom** — pass ``migrating_element`` (e.g. "Mg") and optionally
        ``source_site``/``dest_site`` labels from ``list_migration_paths``; the tool
        auto-builds the vacancy-mediated initial/final endpoints (remove the
        destination atom; move the source atom into it).

    Interpolates a band of images and relaxes it with the ML potential to the
    minimum-energy path — returning forward/reverse barriers + a path plot +
    a convergence report. Long-running, so this enqueues a job and returns a
    ``job_id``.
    """
    if not final_poscar_name and not migrating_element:
        return {"status": "error",
                "message": "compute_neb needs either final_poscar_name (an end-state "
                           "structure) OR migrating_element (e.g. 'Mg') to auto-build "
                           "the hop."}

    n_images = min(max(int(n_images), 3), 15)
    fmax = max(float(fmax), 0.001)
    endpoint_fmax = max(float(endpoint_fmax), 0.001)
    max_steps = min(max(int(max_steps), 1), settings.max_opt_steps)
    spring_k = max(float(spring_k), 0.01)

    try:
        initial_path = find_structure_in_session(poscar_name, prefer_contcar=False)
    except FileNotFoundError as e:
        return {"status": "error", "message": f"Initial structure: {e}"}

    endpoint_info: Optional[dict] = None
    if final_poscar_name:
        try:
            final_path = find_structure_in_session(final_poscar_name,
                                                   prefer_contcar=False)
        except FileNotFoundError as e:
            return {"status": "error", "message": f"Final structure: {e}"}
    else:
        # Auto-build endpoints from the migrating element.
        try:
            initial_path, final_path, endpoint_info = _build_neb_endpoints(
                initial_path, migrating_element.strip(),
                source_site, dest_site, symprec)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:  # noqa: BLE001
            return {"status": "error",
                    "message": f"Failed to build NEB endpoints: {e}"}

    if initial_path.resolve() == final_path.resolve():
        return {"status": "error",
                "message": "Initial and final structures are the same file — NEB "
                           "needs two distinct end states."}

    # Atom cap applies to one image (all images share the same composition).
    try:
        from pymatgen.core import Structure
        n_atoms = len(Structure.from_file(str(initial_path)))
        if n_atoms > settings.max_atoms:
            return {
                "status": "error",
                "message": (
                    f"This structure has {n_atoms} atoms, above the "
                    f"{settings.max_atoms}-atom limit on this server. "
                    "Use a smaller supercell for the migration cell."
                ),
            }
    except Exception:  # noqa: BLE001 — let the worker surface a real parse error
        pass

    calc_cfg = _resolve_calculator(calculator_type, calculator_model)
    if calc_cfg.get("status") == "error":
        return calc_cfg

    result = _enqueue_job(
        JobType.NEB,
        poscar_path=initial_path,
        output_dir=session_path() / "neb",
        params={
            "final_poscar_path": str(final_path),
            "n_images": n_images,
            "fmax": fmax,
            "endpoint_fmax": endpoint_fmax,
            "max_steps": max_steps,
            "spring_k": spring_k,
            "climb": bool(climb),
            "relax_endpoints": bool(relax_endpoints),
            "optimizer": str(optimizer),
            "run_frequencies": bool(run_frequencies),
            "migrating_element": (migrating_element.strip()
                                  if migrating_element else None),
        },
        calculator=calc_cfg,
        emit_vasp_inputs=bool(emit_vasp_inputs),
    )
    if result.get("status") == "queued":
        result["calculator"] = calc_cfg
        msg = f"{result['message']} Using {_calc_label(calc_cfg)}."
        if endpoint_info:
            result["endpoints"] = endpoint_info
            msg += (f" Auto-built {endpoint_info['migrating_element']} hop "
                    f"{endpoint_info['source_site']}→{endpoint_info['dest_site']}.")
        result["message"] = msg
    return result
