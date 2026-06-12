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
from pathlib import Path
from typing import Optional

from app.core.context import get_session_id, get_user_id
from app.core.logging import get_logger
from app.domain.jobs import JobType
from app.domain.vasp import CellRelax, VaspTask
from app.jobs import store
from app.jobs.queue import enqueue
from app.services.search import MaterialQuery, search_service
from app.services.storage.file_service import (
    find_structure_in_session,
    rel_to_storage,
    session_dir,
    session_path,
)
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
# TOOL — generate_vasp_inputs  (consolidates POSCAR + KPOINTS + INCAR generation)
# ─────────────────────────────────────────────────────────────────────────────

def generate_vasp_inputs(
    material_id: Optional[str] = None,
    source:      Optional[str] = None,
    poscar_path: Optional[str] = None,
    task:        str           = "relaxation",
    cell_relax:  str           = "none",
    **overrides,
) -> dict:
    """Generate a complete VASP input set (POSCAR + INCAR + KPOINTS).

    Provide either (`material_id` [+ `source`]) to fetch a structure from a
    database, or `poscar_path` to use an existing session structure.
    """
    try:
        task_enum = VaspTask(task.lower().strip())
    except ValueError:
        return {"status": "error",
                "message": f"Invalid task '{task}'. Use: static | relaxation | band | dos."}
    try:
        cell_enum = CellRelax(cell_relax.lower().strip())
    except ValueError:
        return {"status": "error",
                "message": f"Invalid cell_relax '{cell_relax}'. Use: none | shape | full."}

    # ── resolve the input structure ───────────────────────────────────────────
    try:
        from pymatgen.core import Structure
    except ImportError:
        return {"status": "error", "message": "pymatgen is required. Run: pip install pymatgen"}

    structure = None
    if poscar_path and not material_id:
        try:
            path = find_structure_in_session(poscar_path)
            structure = Structure.from_file(str(path))
        except Exception as e:
            return {"status": "error", "message": f"Could not read structure: {e}"}
    elif material_id:
        if material_id in (None, "", "auto"):
            return {"status": "error",
                    "message": "No material selected. Search for a material first."}
        structure = search_service.get_structure(material_id, source)
        if structure is None:
            return {"status": "error",
                    "message": f"Could not retrieve a structure for '{material_id}'."}
    else:
        return {"status": "error",
                "message": "Provide either material_id (+ source) or poscar_path."}

    # ── build the input set ────────────────────────────────────────────────────
    out_dir = session_dir() / "vasp_inputs" / task_enum.value
    try:
        input_set = vasp_service.build_input_set(
            structure, task=task_enum, cell_relax=cell_enum,
            output_dir=out_dir, overrides=overrides or None,
        )
    except Exception as e:
        return {"status": "error", "message": f"VASP input generation failed: {e}"}

    files_rel = {k: rel_to_storage(Path(v)) for k, v in input_set.files.items()}
    written = [Path(p).name for p in input_set.files.values()]

    return {
        "status":        "success",
        "task":          task_enum.value,
        "formula":       input_set.formula,
        "n_sites":       input_set.n_sites,
        "encut":         input_set.encut,
        "kmesh":         input_set.kmesh,
        "elements":      input_set.elements,
        "potentials":    input_set.potentials,
        "warnings":      input_set.warnings,
        "files":         files_rel,
        "files_written": written,
        "message": (
            f"VASP {task_enum.value} inputs generated for {input_set.formula} "
            f"({input_set.n_sites} atoms): {', '.join(written)}."
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
    max_steps = max(int(max_steps), 1)

    try:
        poscar_path = find_structure_in_session(poscar_name, prefer_contcar=False)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    calc_cfg: dict = {"type": calculator_type.lower()}
    if calculator_model:
        calc_cfg["model"] = calculator_model

    return _enqueue_job(
        JobType.OPTIMIZE,
        poscar_path=poscar_path,
        output_dir=session_path() / "optimization",
        params={"fmax": fmax, "cell_relax": cell_relax,
                "optimizer": optimizer, "max_steps": max_steps},
        calculator=calc_cfg,
        emit_vasp_inputs=emit_vasp_inputs,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — run_md_simulation
# ─────────────────────────────────────────────────────────────────────────────

def run_md_simulation(
    poscar_name:      Optional[str] = None,
    ensemble:         str           = "nvt",
    temperature:      float         = 300.0,
    nsw:              int           = 10000,
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
    nsw           = max(int(nsw), 1)
    timestep      = max(float(timestep), 0.1)
    log_interval  = max(int(log_interval), 1)

    try:
        poscar_path = find_structure_in_session(poscar_name, prefer_contcar=True)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    calc_cfg: dict = {"type": calculator_type.lower()}
    if calculator_model:
        calc_cfg["model"] = calculator_model

    return _enqueue_job(
        JobType.MD,
        poscar_path=poscar_path,
        output_dir=session_path() / "md_simulation",
        params={"ensemble": ensemble, "temperature": temperature, "nsw": nsw,
                "timestep": timestep, "thermostat": thermostat,
                "pressure": pressure, "log_interval": log_interval},
        calculator=calc_cfg,
        emit_vasp_inputs=emit_vasp_inputs,
    )
