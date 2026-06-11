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

from pathlib import Path
from typing import Optional

from app.core.logging import get_logger
from app.domain.vasp import CellRelax, VaspTask
from app.services.search import MaterialQuery, search_service
from app.services.storage.file_service import (
    find_structure_in_session,
    rel_to_storage,
    session_dir,
    session_path,
)
from app.services.vasp.service import vasp_service

logger = get_logger(__name__)


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
    """Run ASE geometry optimization on a structure in the current session."""
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

    output_dir = session_path() / "optimization"
    output_dir.mkdir(parents=True, exist_ok=True)
    calc_cfg: dict = {"type": calculator_type.lower()}
    if calculator_model:
        calc_cfg["model"] = calculator_model

    from app.services.simulation.optimization import run_optimization
    result = run_optimization(
        poscar_path=str(poscar_path), output_dir=str(output_dir),
        fmax=fmax, cell_relax=cell_relax, optimizer=optimizer,
        max_steps=max_steps, calculator=calc_cfg, generate_vasp_inputs=emit_vasp_inputs,
    )

    if result.get("status") == "error":
        return result

    files = result.get("files", {})
    result["files"] = {
        k: (rel_to_storage(Path(v)) if v and Path(v).exists() else None)
        for k, v in files.items()
    }

    conv_label = "Converged" if result.get("converged") else "Not converged"
    result["message"] = (
        f"{conv_label} — {result.get('formula', '')} ({result.get('n_sites', '?')} atoms), "
        f"E = {result.get('final_energy', '?')} eV, fmax = {result.get('final_fmax', '?')} eV/Å "
        f"after {result.get('steps', '?')} steps ({result.get('elapsed_s', '?')}s)."
    )
    return result


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
    """Run ASE Molecular Dynamics (NVT or NPT) on a session structure."""
    ensemble = ensemble.lower().strip()
    if ensemble not in ("nvt", "npt"):
        return {"status": "error", "message": f"Invalid ensemble '{ensemble}'. Use: nvt | npt"}

    thermostat = thermostat.lower().strip()

    temperature   = max(float(temperature), 1.0)
    nsw           = max(int(nsw), 1)
    timestep      = max(float(timestep), 0.1)
    log_interval  = max(int(log_interval), 1)
    total_time_ps = (nsw * timestep) / 1000.0

    try:
        poscar_path = find_structure_in_session(poscar_name, prefer_contcar=True)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    output_dir = session_path() / "md_simulation"
    output_dir.mkdir(parents=True, exist_ok=True)
    calc_cfg: dict = {"type": calculator_type.lower()}
    if calculator_model:
        calc_cfg["model"] = calculator_model

    from app.services.simulation.md import run_md
    result = run_md(
        poscar_path=str(poscar_path), output_dir=str(output_dir),
        ensemble=ensemble, temperature=temperature, nsw=nsw, timestep=timestep,
        thermostat=thermostat or ("langevin" if ensemble == "nvt" else "berendsen"),
        pressure=pressure, log_interval=log_interval,
        calculator=calc_cfg, generate_vasp_inputs=emit_vasp_inputs,
    )

    if result.get("status") == "error":
        return result

    files = result.get("files", {})
    rel_files: dict = {
        k: (rel_to_storage(Path(v)) if v and Path(v).exists() else None)
        for k, v in files.items()
    }

    try:
        from app.services.simulation.plots import generate_md_plots
        plots = generate_md_plots(
            energy_csv=str(output_dir / "md_energy.csv"),
            temp_csv=str(output_dir / "md_temp.csv"),
            output_dir=str(output_dir),
        )
        rel_files["plot_energy"] = rel_to_storage(Path(plots["energy_png"])) if plots.get("energy_png") else None
        rel_files["plot_temp"]   = rel_to_storage(Path(plots["temp_png"]))   if plots.get("temp_png")   else None
    except Exception as e:
        logger.warning("MD plot generation failed: %s", e)
        rel_files["plot_energy"] = None
        rel_files["plot_temp"]   = None

    result["files"]         = rel_files
    result["total_time_ps"] = round(total_time_ps, 3)

    mean_T  = result.get("mean_temperature")
    final_E = result.get("final_energy")
    steps   = result.get("steps_completed", nsw)
    elapsed = result.get("elapsed_s", "?")

    result["message"] = (
        f"MD ({ensemble.upper()}, {thermostat}) completed — "
        f"{result.get('formula', '')} ({result.get('n_sites', '?')} atoms), "
        f"{steps} steps × {timestep} fs = {total_time_ps:.3f} ps, "
        f"T_target = {temperature} K, T_mean = {mean_T} K, "
        f"E_final = {final_E} eV (wall time: {elapsed}s)."
    )
    return result
