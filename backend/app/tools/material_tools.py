"""
backend/app/tools/material_tools.py
=====================================
All agent-callable tool implementations in one file.

Tools registered in agent/tool_registry.py:
  search_material          — search MP / C2DB / OQMD
  generate_poscar          — write POSCAR for any source
  generate_vasp_poscar     — alias for generate_poscar
  list_files               — list session files
  read_file                — read a text file from the session
  rename_file              — rename a session file
  customize_vasp_kpoints_with_accuracy — generate KPOINTS
  generate_vasp_inputs_from_poscar     — generate INCAR + KPOINTS
  optimize_structure       — ASE geometry optimization (MACE / MatterSim)
  list_available_calculators           — list local MLP models
  run_md_simulation        — ASE NVT / NPT molecular dynamics
"""

import os
from typing import Optional
from pathlib import Path

from app.core.logging import get_logger
from app.services.file_service import STORAGE_ROOT
from app.services.search_service import search_all_sources, get_mp_structure, get_structure_from_c2db, get_oqmd_structure
from app.tools.utils import session_dir, write_poscar

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SHARED PATH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

TEXT_EXTENSIONS = {"", ".txt", ".log", ".csv", ".json", ".xml", ".cif", ".xyz", ".html"}
VASP_TEXT_NAMES = {"POSCAR", "CONTCAR", "INCAR", "KPOINTS", "POTCAR", "OSZICAR", "OUTCAR", "XDATCAR"}


def _session_path() -> Path:
    return session_dir().resolve()


def _rel_to_storage(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(STORAGE_ROOT.resolve()))
    except ValueError:
        return str(path.name)


def _safe_file_in_session(name: str) -> Path:
    base      = _session_path()
    requested = "auto" if name in ("", None) else str(name)

    if requested == "auto":
        candidates = sorted(
            [p for p in base.rglob("*") if p.is_file()],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not candidates:
            raise FileNotFoundError("No files exist in this session yet.")
        return candidates[0]

    rel = Path(requested)

    # Absolute paths are allowed if they resolve inside the session directory
    if rel.is_absolute():
        try:
            rel.resolve().relative_to(base)
        except ValueError:
            raise PermissionError("File path must stay inside the current session.")
        if rel.exists() and rel.is_file():
            return rel.resolve()
        raise FileNotFoundError(f"File '{rel.name}' was not found in this session.")

    if ".." in rel.parts:
        raise PermissionError("File path must stay inside the current session.")

    direct = (base / rel).resolve()
    if direct.exists() and direct.is_file():
        direct.relative_to(base)
        return direct

    matches = [p for p in base.rglob(rel.name) if p.is_file()]
    if matches:
        return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]

    raise FileNotFoundError(f"File '{requested}' was not found in this session.")


def _find_poscar_in_session(name: Optional[str], prefer_contcar: bool = False) -> Path:
    """
    Locate a POSCAR / CONTCAR in the current session directory.

    prefer_contcar=True: prefer post-relaxation CONTCAR over POSCAR (use for MD).
    prefer_contcar=False: prefer POSCAR over CONTCAR (use for optimization).
    """
    base = _session_path()

    if name:
        direct = (base / name).resolve()
        if direct.exists() and direct.is_file():
            return direct
        matches = [p for p in base.rglob(name) if p.is_file()]
        if matches:
            return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        raise FileNotFoundError(
            f"File '{name}' not found in this session. "
            "Run generate_poscar (or optimize_structure) first."
        )

    candidates = ("CONTCAR", "POSCAR") if prefer_contcar else ("POSCAR", "CONTCAR")
    for candidate in candidates:
        p = base / candidate
        if p.exists():
            return p

    poscar_files = sorted(
        [p for p in base.rglob("POSCAR*") if p.is_file()],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if poscar_files:
        return poscar_files[0]

    vasp_files = sorted(
        [p for p in base.rglob("*.vasp") if p.is_file()],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if vasp_files:
        return vasp_files[0]

    all_files = sorted(
        [p for p in base.rglob("*") if p.is_file()],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if all_files:
        return all_files[0]

    raise FileNotFoundError(
        "No structure file found in this session. Run generate_poscar first."
    )


# ─────────────────────────────────────────────────────────────────────────────
# FILE TOOLS
# ─────────────────────────────────────────────────────────────────────────────

def list_files() -> dict:
    """List files in the current session directory."""
    base  = _session_path()
    files = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        files.append({
            "name":     path.name,
            "size_kb":  round(path.stat().st_size / 1024, 2),
            "rel_path": _rel_to_storage(path),
        })
    return {
        "status":  "success",
        "message": f"Found {len(files)} file{'s' if len(files) != 1 else ''} in this session.",
        "files":   files,
    }


def read_file(name: str = "auto", max_chars: int = 12000) -> dict:
    """Read a text-like file from the current session."""
    try:
        path = _safe_file_in_session(name)
        if path.suffix.lower() not in TEXT_EXTENSIONS and path.name.upper() not in VASP_TEXT_NAMES:
            return {
                "status":   "error",
                "message":  f"File '{path.name}' is not readable as text.",
                "name":     path.name,
                "rel_path": _rel_to_storage(path),
            }
        content   = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars] + "\n\n[truncated]"
        return {
            "status":    "success",
            "message":   f"Read {path.name}.",
            "name":      path.name,
            "rel_path":  _rel_to_storage(path),
            "content":   content,
            "truncated": truncated,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "content": ""}


def rename_file(name: str, new_name: str) -> dict:
    """Rename a file inside the current session directory."""
    try:
        src      = _safe_file_in_session(name)
        base     = _session_path()
        dst_name = Path(new_name).name
        if not dst_name:
            return {"status": "error", "message": "New file name is empty."}
        dst = (src.parent / dst_name).resolve()
        dst.relative_to(base)
        if dst.exists():
            return {"status": "error", "message": f"'{dst_name}' already exists."}
        src.rename(dst)
        return {
            "status":  "success",
            "message": f"Renamed {src.name} to {dst.name}.",
            "files":   [{"name": dst.name, "size_kb": round(dst.stat().st_size / 1024, 2), "rel_path": _rel_to_storage(dst)}],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — search_material
# ─────────────────────────────────────────────────────────────────────────────

def search_material(
    formula:         Optional[str]   = None,
    element:         Optional[str]   = None,
    elements:        Optional[str]   = None,
    max_gap:         Optional[float] = None,
    min_gap:         Optional[float] = None,
    max_formation_e: Optional[float] = None,
    limit:           int             = 10,
) -> dict:
    """
    Search for materials across all available databases.

    Search order (fastest/most curated first):
      1. Materials Project  — bulk/3D curated structures, live API
      2. C2DB               — local ASE db, 2D materials (~17k)
      3. OQMD               — public REST API, ~1M structures, fallback

    Stops at the first source that returns ≥ 1 result.

    Parameters
    ----------
    formula         : Chemical formula, e.g. "LiFeIn2", "MoS2", "NaCl"
    element         : Single element that must be present, e.g. "Mo"
    elements        : All elements required comma-separated, e.g. "Mo,S"
    max_gap         : Max PBE band gap [eV]
    min_gap         : Min PBE band gap [eV]
    max_formation_e : Max formation energy [eV/atom]
    limit           : Max results per source (default 10)

    Returns
    -------
    {
      "status":         "ok" | "not_found" | "error",
      "source_used":    "mp" | "c2db" | "oqmd" | None,
      "sources_tried":  [str, ...],
      "materials":      [...material card dicts...],
      "total_matching": int,
      "returned":       int,
      "message":        str
    }
    """
    if not any([formula, element, elements]):
        return {
            "status":         "error",
            "message":        "Provide at least one of: formula, element, or elements.",
            "materials":      [],
            "sources_tried":  [],
            "total_matching": 0,
            "returned":       0,
        }

    result    = search_all_sources(
        formula=formula, element=element, elements=elements,
        max_gap=max_gap, min_gap=min_gap, max_formation_e=max_formation_e,
        limit=min(int(limit), 20),
    )

    materials = result.get("results", [])
    source    = result.get("source_used")
    tried     = result.get("sources_tried", [])
    query_str = formula or element or elements or ""

    if not materials:
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

    total   = result.get("total_matching", len(materials))
    more    = f" ({total} total in {source})" if total > len(materials) else ""
    tried_b = [s for s in tried if s != source]
    note    = f" (not found in {', '.join(tried_b)})" if tried_b else ""

    source_labels = {
        "mp":   "Materials Project (bulk/3D)",
        "c2db": "C2DB (2D materials)",
        "oqmd": "OQMD (Open Quantum Materials Database)",
    }

    return {
        "status":         "ok",
        "source_used":    source,
        "sources_tried":  tried,
        "materials":      materials,
        "total_matching": total,
        "returned":       len(materials),
        "message": (
            f"Found {len(materials)} result{'s' if len(materials) != 1 else ''} "
            f"for '{query_str}' in {source_labels.get(source, source)}"
            f"{more}{note}."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — generate_poscar
# ─────────────────────────────────────────────────────────────────────────────

def generate_poscar(
    material_id: str,
    source:      Optional[str] = None,
    name:        Optional[str] = None,
) -> dict:
    """
    Generate a VASP POSCAR for a material from any supported database.

    Uses the `id` and `source` fields returned by search_material.
    The POSCAR is saved to the current session directory.

    Parameters
    ----------
    material_id : The `id` from search_material, e.g. "mp-19306", "c2db:42", "oqmd:12345"
    source      : "mp" | "c2db" | "oqmd"
    name        : Label for the named POSCAR file (default: formula)

    Returns
    -------
    {
      "status":        "success" | "error",
      "message":       str,
      "formula":       str,
      "n_sites":       int,
      "poscar_path":   str,
      "named_path":    str,
      "files_written": [str, ...],
      "source":        str,
      "material_id":   str
    }
    """
    try:
        from pymatgen.core import Structure  # noqa: F401 — validates pymatgen is available
    except ImportError:
        return {"status": "error", "message": "pymatgen is required. Run: pip install pymatgen"}

    dest      = session_dir()
    structure = None
    src       = (source or _infer_source(material_id)).lower().strip()

    if src == "mp":
        mp_id     = material_id[3:] if material_id.startswith("mp:") else material_id
        structure = get_mp_structure(mp_id)
        if structure is None:
            return {"status": "error", "message": f"Could not retrieve MP structure for {mp_id}."}

    elif src == "c2db":
        try:
            structure = get_structure_from_c2db(material_id)
        except Exception as e:
            return {"status": "error", "message": f"Failed to load structure from C2DB: {e}"}
        if structure is None:
            return {"status": "error", "message": f"Could not retrieve C2DB structure for '{material_id}'."}

    elif src == "oqmd":
        oqmd_id   = material_id[5:] if material_id.startswith("oqmd:") else material_id
        structure = get_oqmd_structure(oqmd_id)
        if structure is None:
            return {
                "status":  "error",
                "message": (
                    f"Could not retrieve OQMD structure for entry {oqmd_id}. "
                    "The OQMD API may be temporarily unavailable."
                ),
            }

    else:
        return {"status": "error", "message": f"Unknown source '{src}'. Use: mp | c2db | oqmd"}

    label = name or structure.composition.reduced_formula
    try:
        result = write_poscar(structure, dest, name=label)
        result.update({
            "source":      src,
            "material_id": material_id,
            "message": (
                f"POSCAR generated for {result['formula']} "
                f"({result['n_sites']} atoms) from {src.upper()}."
            ),
        })
        logger.info(result["message"])
        return result
    except Exception as e:
        return {"status": "error", "message": f"POSCAR write error: {e}"}


def _infer_source(material_id: str) -> str:
    mid = str(material_id)
    if mid.startswith("mp"):
        return "mp"
    if mid.startswith("oqmd:"):
        return "oqmd"
    return "c2db"


def generate_vasp_poscar(material_id: str, source: Optional[str] = None, name: Optional[str] = None) -> dict:
    """Alias for generate_poscar."""
    return generate_poscar(material_id=material_id, source=source, name=name)


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — VASP input generation
# ─────────────────────────────────────────────────────────────────────────────

def customize_vasp_kpoints_with_accuracy(
    poscar_path: str  = "auto",
    density:     int  = 40,
    is_md:       bool = False,
) -> dict:
    """Generate KPOINTS from a POSCAR in the current session.

    Parameters
    ----------
    poscar_path : session-local filename or 'auto'
    density     : k-point density
    is_md       : use Gamma-only (for MD runs)
    """
    try:
        from app.services.incar_kpoints_service import generate_kpoints
        from pymatgen.core import Structure

        path      = _safe_file_in_session(poscar_path)
        structure = Structure.from_file(str(path))
        ktxt      = generate_kpoints(structure, density=density, is_md=is_md)
        dest      = session_dir() / "vasp_inputs"
        dest.mkdir(parents=True, exist_ok=True)
        kp        = dest / "KPOINTS"
        kp.write_text(ktxt)
        return {
            "status":        "success",
            "message":       f"KPOINTS generated (density={density}).",
            "files_written": ["KPOINTS"],
            "poscar_path":   str(path),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def generate_vasp_inputs_from_poscar(
    poscar_path: str = "auto",
    task:        str = "optimization",
    cell_relax:  str = "none",
    **overrides,
) -> dict:
    """Generate INCAR and KPOINTS from a POSCAR and save them in session."""
    try:
        from app.services.incar_kpoints_service import generate_incar, generate_kpoints
        from pymatgen.core import Structure

        path      = _safe_file_in_session(poscar_path)
        structure = Structure.from_file(str(path))

        incar_txt = generate_incar(structure, task=task, cell_relax=cell_relax, **overrides)
        kpt_txt   = generate_kpoints(structure)

        dest = session_dir() / "vasp_inputs"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "INCAR").write_text(incar_txt)
        (dest / "KPOINTS").write_text(kpt_txt)

        return {
            "status":        "success",
            "message":       f"INCAR and KPOINTS written for task={task}.",
            "files_written": ["INCAR", "KPOINTS"],
            "poscar_path":   str(path),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — optimize_structure
# ─────────────────────────────────────────────────────────────────────────────

def optimize_structure(
    poscar_name:          Optional[str] = None,
    fmax:                 float         = 0.02,
    cell_relax:           str           = "none",
    optimizer:            str           = "FIRE",
    max_steps:            int           = 1000,
    calculator_type:      str           = "mace",
    calculator_model:     Optional[str] = None,
    generate_vasp_inputs: bool          = True,
) -> dict:
    """
    Run ASE geometry optimization on a POSCAR in the current session.

    Parameters
    ----------
    poscar_name          : Input file name. Auto-detects POSCAR if omitted.
    fmax                 : Force convergence threshold [eV/Å]. Tight: 0.01 | Normal: 0.02 | Loose: 0.05
    cell_relax           : "none" — atoms only | "shape" — shape+atoms | "full" — shape+volume+atoms
    optimizer            : "FIRE" (default) | "BFGS" | "LBFGS"
    max_steps            : Maximum optimizer steps. Default 1000.
    calculator_type      : "mace" (default) | "mattersim"
    calculator_model     : Override default model, e.g. "mace-mp-0b3-medium".
    generate_vasp_inputs : Also write INCAR + KPOINTS for VASP handoff.

    Returns
    -------
    { "status", "message", "converged", "steps", "final_energy",
      "final_fmax", "formula", "n_sites", "elapsed_s", "files": {...} }
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
        poscar_path = _find_poscar_in_session(poscar_name, prefer_contcar=False)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    output_dir = _session_path() / "optimization"
    output_dir.mkdir(parents=True, exist_ok=True)
    calc_cfg: dict = {"type": calculator_type.lower()}
    if calculator_model:
        calc_cfg["model"] = calculator_model

    from app.services.optimization_service import run_optimization
    result = run_optimization(
        poscar_path=str(poscar_path), output_dir=str(output_dir),
        fmax=fmax, cell_relax=cell_relax, optimizer=optimizer,
        max_steps=max_steps, calculator=calc_cfg, generate_vasp_inputs=generate_vasp_inputs,
    )

    if result.get("status") == "error":
        return result

    files = result.get("files", {})
    result["files"] = {
        k: (_rel_to_storage(Path(v)) if v and Path(v).exists() else None)
        for k, v in files.items()
    }

    conv_label    = "Converged" if result.get("converged") else "Not converged"
    result["message"] = (
        f"{conv_label} — {result.get('formula', '')} ({result.get('n_sites', '?')} atoms), "
        f"E = {result.get('final_energy', '?')} eV, fmax = {result.get('final_fmax', '?')} eV/Å "
        f"after {result.get('steps', '?')} steps ({result.get('elapsed_s', '?')}s)."
    )
    return result


def list_available_calculators() -> dict:
    """List all locally available MACE and MatterSim models.

    Returns
    -------
    { "status", "message", "models": {"mace": [...], "mattersim": [...]} }
    """
    try:
        from app.services.calculator_factory import list_available_models
        models   = list_available_models()
        mace_ok  = [m for m in models["mace"]      if m["exists"]]
        msim_ok  = [m for m in models["mattersim"] if m["exists"]]
        total_ok = len(mace_ok) + len(msim_ok)
        return {
            "status":  "ok",
            "message": f"{total_ok} model(s) available locally: {len(mace_ok)} MACE, {len(msim_ok)} MatterSim.",
            "models":  models,
        }
    except Exception as e:
        return {"status": "error", "message": f"Could not list models: {e}", "models": {}}


# ─────────────────────────────────────────────────────────────────────────────
# TOOL — run_md_simulation
# ─────────────────────────────────────────────────────────────────────────────

def run_md_simulation(
    poscar_name:          Optional[str] = None,
    ensemble:             str           = "nvt",
    temperature:          float         = 300.0,
    nsw:                  int           = 10000,
    timestep:             float         = 1.0,
    thermostat:           str           = "langevin",
    pressure:             float         = 0.0,
    calculator_type:      str           = "mace",
    calculator_model:     Optional[str] = None,
    log_interval:         int           = 10,
    generate_vasp_inputs: bool          = True,
) -> dict:
    """
    Run ASE Molecular Dynamics (NVT or NPT) on a structure in the session.

    Parameters
    ----------
    poscar_name          : Input file. Auto-detects CONTCAR/POSCAR if omitted.
                           Tip: run optimize_structure first to get a relaxed CONTCAR.
    ensemble             : "nvt" (default) | "npt"
    temperature          : Target temperature [K]. Default 300.
    nsw                  : Total MD steps. Default 10000.
    timestep             : MD timestep [fs]. Default 1.0.
    thermostat           : NVT: "langevin" (default) | "nose-hoover"
                           NPT: "berendsen" | "bussi"
    pressure             : Target pressure [GPa], NPT only.
    calculator_type      : "mace" (default) | "mattersim"
    calculator_model     : Override default model, e.g. "mace-omat-0-medium".
    log_interval         : Log every N steps.
    generate_vasp_inputs : Also write INCAR + KPOINTS for equivalent VASP-MD.

    Returns
    -------
    { "status", "message", "steps_completed", "total_time_fs", "total_time_ps",
      "formula", "n_sites", "final_energy", "mean_temperature", "ensemble",
      "thermostat", "elapsed_s", "files": {...} }
    """
    ensemble = ensemble.lower().strip()
    if ensemble not in ("nvt", "npt"):
        return {"status": "error", "message": f"Invalid ensemble '{ensemble}'. Use: nvt | npt"}

    thermostat = thermostat.lower().strip()

    temperature  = max(float(temperature), 1.0)
    nsw          = max(int(nsw), 1)
    timestep     = max(float(timestep), 0.1)
    log_interval = max(int(log_interval), 1)
    total_time_fs = nsw * timestep
    total_time_ps = total_time_fs / 1000.0

    try:
        poscar_path = _find_poscar_in_session(poscar_name, prefer_contcar=True)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}

    output_dir = _session_path() / "md_simulation"
    output_dir.mkdir(parents=True, exist_ok=True)
    calc_cfg: dict = {"type": calculator_type.lower()}
    if calculator_model:
        calc_cfg["model"] = calculator_model

    from app.services.md_service import run_md
    result = run_md(
        poscar_path=str(poscar_path), output_dir=str(output_dir),
        ensemble=ensemble, temperature=temperature, nsw=nsw, timestep=timestep,
        thermostat=thermostat or ("langevin" if ensemble == "nvt" else "berendsen"),
        pressure=pressure, log_interval=log_interval,
        calculator=calc_cfg, generate_vasp_inputs=generate_vasp_inputs,
    )

    if result.get("status") == "error":
        return result

    files = result.get("files", {})
    rel_files: dict = {
        k: (_rel_to_storage(Path(v)) if v and Path(v).exists() else None)
        for k, v in files.items()
    }

    try:
        from app.services.md_plots import generate_md_plots
        plots = generate_md_plots(
            energy_csv=str(output_dir / "md_energy.csv"),
            temp_csv=str(output_dir / "md_temp.csv"),
            output_dir=str(output_dir),
        )
        rel_files["plot_energy"] = _rel_to_storage(Path(plots["energy_png"])) if plots.get("energy_png") else None
        rel_files["plot_temp"]   = _rel_to_storage(Path(plots["temp_png"]))   if plots.get("temp_png")   else None
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
