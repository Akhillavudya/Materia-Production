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

import hashlib
import json
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
from app.services.structure import builder
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
    get_session_dir,
    list_session_files,
    rel_to_storage,
    safe_file_in_session,
    session_dir,
    session_path,
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
    query = MaterialQuery(
        formula=formula, element=element, elements=elem_list,
        min_gap=min_gap, max_gap=max_gap, max_formation_e=max_formation_e,
        dimensionality=dimensionality, limit=min(int(limit), 20),
    )

    result    = search_service.search(query)
    cards     = [c.model_dump(mode="json") for c in result.cards]
    tried     = [s.value for s in result.sources_tried]
    source    = result.source_used.value if result.source_used else None
    query_str = formula or element or elements or ""

    if not cards:
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

    tried_other = [s for s in tried if s != source]
    note = f" (not found in {', '.join(tried_other)})" if tried_other else ""

    return {
        "status":         "ok",
        "source_used":    source,
        "sources_tried":  tried,
        "materials":      cards,
        "total_matching": len(cards),
        "returned":       len(cards),
        "message": (
            f"Found {len(cards)} result{'s' if len(cards) != 1 else ''} "
            f"for '{query_str}' in {_SOURCE_LABELS.get(source, source)}{note}."
        ),
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
# TOOL — build_structure  (combined structure transforms; Step 5.5)
# ─────────────────────────────────────────────────────────────────────────────

_BUILD_OPERATIONS = {"make_supercell", "add_vacuum", "make_slab", "convert"}


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


def build_structure(
    operation:   str,
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
    poscar_path: Optional[str] = None,
    scaling:     Optional[str] = None,
    axis:        str           = "c",
    thickness:   float         = 15.0,
    center:      bool          = True,
    miller:      str           = "1 1 1",
    min_slab_size:  float      = 10.0,
    min_vacuum_size: float     = 15.0,
    lll_reduce:  bool          = True,
    shift:       float         = 0.0,
    to_format:   str           = "cif",
) -> dict:
    """Transform a crystal structure and save the result as the active POSCAR.

    Operations (selected by `operation`):
      - make_supercell: replicate the cell, e.g. scaling="2 2 1" or "2".
      - add_vacuum: add `thickness` Å of vacuum along `axis` (a/b/c), optionally
        centering the atoms — for 2D layers, molecules, or padding a slab.
      - make_slab: cut a surface along `miller` (e.g. "1 1 1") with `min_slab_size`
        and `min_vacuum_size` Å. Vacuum is included — do NOT also call add_vacuum.
      - convert: write the structure in another format (`to_format`: poscar | cif |
        xyz | cssr | json). Does NOT change the active POSCAR.

    Operates on the active session structure by default; pass `poscar_path` for a
    specific session file or `material_id` (+ `source`) to fetch one from a database.
    Writes ``POSCAR`` + ``POSCAR_<formula>`` so the result chains into the next tool.
    """
    op = (operation or "").lower().strip()
    if op not in _BUILD_OPERATIONS:
        return {"status": "error",
                "message": (f"Invalid operation '{operation}'. Use: "
                            f"{' | '.join(sorted(_BUILD_OPERATIONS))}.")}

    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}

    # convert is special — it writes a format file, not the active POSCAR.
    if op == "convert":
        return _convert_structure(structure, to_format)

    n_before = len(structure)

    try:
        if op == "make_supercell":
            result = builder.make_supercell(structure, scaling)
        elif op == "add_vacuum":
            result = builder.add_vacuum(structure, axis=axis, thickness=thickness,
                                        center=center)
        elif op == "make_slab":
            result = builder.make_slab(structure, miller=miller,
                                       min_slab_size=min_slab_size,
                                       min_vacuum_size=min_vacuum_size,
                                       center_slab=center, lll_reduce=lll_reduce,
                                       shift=shift)
        else:  # pragma: no cover - guarded by _BUILD_OPERATIONS
            return {"status": "error", "message": f"Operation '{op}' is not implemented."}
    except Exception as e:  # noqa: BLE001 — surface a friendly message
        return {"status": "error", "message": f"{op} failed: {e}"}

    if len(result) > settings.max_atoms:
        return {"status": "error",
                "message": (f"The result has {len(result)} atoms, above the "
                            f"{settings.max_atoms}-atom limit on this server. "
                            "Use a smaller scaling factor.")}

    formula = result.composition.reduced_formula
    try:
        write_poscar(result, session_dir(), name=formula)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Could not write the structure: {e}"}

    abc = [round(x, 4) for x in result.lattice.abc]
    if op == "make_supercell":
        detail = f"now has {len(result)} atoms (was {n_before})"
    elif op == "add_vacuum":
        detail = f"vacuum added along {axis} → lattice abc = {abc} Å"
    elif op == "make_slab":
        detail = f"({miller}) slab with {len(result)} atoms, abc = {abc} Å"
    else:  # pragma: no cover
        detail = f"now has {len(result)} atoms"

    return {
        "status":         "success",
        "operation":      op,
        "formula":        formula,
        "n_sites_before": n_before,
        "n_sites":        len(result),
        "lattice_abc":    abc,
        "files_written":  ["POSCAR", f"POSCAR_{formula}"],
        "message": (
            f"{op}: {formula} {detail}. "
            "Wrote POSCAR — this structure is now active for the next step."
        ),
    }


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
        try:
            write_poscar(std, session_dir(), name=formula)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"Could not write the structure: {e}"}
        files_written = ["POSCAR", f"POSCAR_{formula}"]
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

def _finish_defect(sc, defect_name: str, kind: str, n_bulk: int) -> dict:
    """Atom-cap, write the defective supercell as the active POSCAR, return the envelope."""
    if len(sc) > settings.max_atoms:
        return {"status": "error",
                "message": (f"The {kind} supercell has {len(sc)} atoms, above the "
                            f"{settings.max_atoms}-atom limit. Use a smaller supercell.")}
    formula = sc.composition.reduced_formula
    try:
        write_poscar(sc, session_dir(), name=formula)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Could not write the structure: {e}"}
    return {
        "status":        "success",
        "defect":        kind,
        "defect_name":   defect_name,
        "formula":       formula,
        "n_sites":       len(sc),
        "files_written": ["POSCAR", f"POSCAR_{formula}"],
        "message": (
            f"Created {kind} ({defect_name}); supercell now has {len(sc)} atoms. "
            "Wrote POSCAR — active for the next step. To make it a CHARGED defect, run "
            "generate_vasp_inputs with a `charge` value (it sets NELECT)."
        ),
    }


def create_vacancy(
    element:     Optional[str] = None,
    supercell:   Optional[str] = None,
    poscar_path: Optional[str] = None,
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
) -> dict:
    """Create a vacancy (remove one atom) in a supercell and save it as the active POSCAR.

    `element` selects which species to remove (defaults to the first site found).
    `supercell` like "2 2 2" sizes the cell; omit it to auto-size for defect isolation.
    """
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}
    try:
        sc, name = builder.create_vacancy(structure, element=element, supercell=supercell)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Vacancy creation failed: {e}"}
    return _finish_defect(sc, name, "vacancy", len(structure))


def create_substitution(
    from_element: str,
    to_element:   str,
    supercell:    Optional[str] = None,
    poscar_path:  Optional[str] = None,
    material_id:  Optional[str] = None,
    source:       Optional[str] = None,
) -> dict:
    """Substitute one `from_element` atom with `to_element` in a supercell; save active POSCAR."""
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}
    try:
        sc, name = builder.create_substitution(
            structure, from_element=from_element, to_element=to_element, supercell=supercell)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Substitution failed: {e}"}
    return _finish_defect(sc, name, "substitution", len(structure))


def create_interstitial(
    insert_element: str,
    supercell:      Optional[str] = None,
    poscar_path:    Optional[str] = None,
    material_id:    Optional[str] = None,
    source:         Optional[str] = None,
) -> dict:
    """Insert `insert_element` at a Voronoi interstitial site in a supercell; save active POSCAR."""
    try:
        structure = _resolve_build_input(material_id, source, poscar_path)
    except _StructureError as e:
        return {"status": "error", "message": str(e)}
    try:
        sc, name = builder.create_interstitial(
            structure, insert_element=insert_element, supercell=supercell)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Interstitial creation failed: {e}"}
    return _finish_defect(sc, name, "interstitial", len(structure))


# ─────────────────────────────────────────────────────────────────────────────
# File-classification helper (shared by read_file + list_files)
# ─────────────────────────────────────────────────────────────────────────────

_STRUCTURE_EXTS = {".cif", ".xyz", ".vasp"}
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
    return "File"


def _is_structure_file(path: Path) -> bool:
    upper = path.name.upper()
    return (
        upper.startswith(("POSCAR", "CONTCAR"))
        or path.suffix.lower() in _STRUCTURE_EXTS
    )


def _parse_structure(path: Path):
    """Parse a structure file with pymatgen, falling back to ASE for XYZ/etc."""
    try:
        from pymatgen.core import Structure
    except ImportError:
        raise _StructureError("pymatgen is required. Run: pip install pymatgen")

    try:
        return Structure.from_file(str(path))
    except Exception:  # noqa: BLE001 — try ASE before giving up
        pass

    try:
        from ase.io import read as ase_read
        from pymatgen.io.ase import AseAtomsAdaptor
        atoms = ase_read(str(path))
        return AseAtomsAdaptor.get_structure(atoms)
    except Exception as e:  # noqa: BLE001
        raise _StructureError(
            f"Could not parse a crystal structure from '{path.name}': {e}. "
            "A periodic cell is required (XYZ files without a lattice are not supported)."
        )


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
    try:
        write_poscar(structure, session_dir(), name=formula)
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
        "files_written": ["POSCAR", f"POSCAR_{formula}"],
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
    emit_vasp_inputs: bool          = True,
) -> dict:
    """Queue an ASE geometry optimization job for a structure in the session.

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
    """Queue an ASE Molecular Dynamics (NVT/NPT) job for a session structure.

    Long-running, so this enqueues a job and returns a ``job_id`` immediately;
    progress/results are tracked via ``/api/jobs`` (redesign §11).
    """
    ensemble = ensemble.lower().strip()
    if ensemble not in ("nvt", "npt"):
        return {"status": "error", "message": f"Invalid ensemble '{ensemble}'. Use: nvt | npt"}

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
