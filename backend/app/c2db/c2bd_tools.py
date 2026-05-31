# app/c2db/c2db_tools.py
# The 3 C2DB tool functions callable by the Materia agent.
# Each returns a dict with 'status', 'message', and result fields —
# matching the pattern of all existing Materia tools.
 
import os
import logging
from pathlib import Path
from typing import Optional
 
logger = logging.getLogger(__name__)
 
 
# ── session directory helper ──────────────────────────────────────────────────
 
def _get_runs_dir() -> str:
    """
    Get the current session runs directory from environment.
    Falls back to a local test dir if not set (never happens in production).
    """
    runs_dir = os.environ.get("MATERIA_SESSION_RUNS_DIR")
    if not runs_dir:
        runs_dir = os.path.join(os.getcwd(), "materia_test_run")
        os.environ["MATERIA_SESSION_RUNS_DIR"] = runs_dir
    os.makedirs(runs_dir, exist_ok=True)
    return runs_dir
 
 
def _rel(abs_path: str, base_dir: str) -> str:
    """Return path relative to base_dir — safe to expose to frontend."""
    try:
        return str(Path(abs_path).relative_to(base_dir))
    except ValueError:
        return os.path.basename(abs_path)
 
 
# ── Tool 1: search_c2db_material ─────────────────────────────────────────────
 
def search_c2db_material(
    formula:            Optional[str]   = None,
    elements:           Optional[list]  = None,
    bandgap_min:        Optional[float] = None,
    bandgap_max:        Optional[float] = None,
    magnetic_state:     Optional[str]   = None,
    dynamically_stable: Optional[bool]  = None,
    max_results:        int             = 20,
) -> dict:
    """
    Search the local C2DB database for 2D materials.
 
    Use when user asks about 2D materials, monolayers, TMDs, MXenes.
    Returns entries with bandgap, formation energy, magnetic state.
    Does NOT generate a POSCAR — follow with generate_poscar_from_c2db.
 
    Args:
        formula:            e.g. "MoS2"
        elements:           e.g. ["Mo", "S"]
        bandgap_min/max:    PBE bandgap range in eV
        magnetic_state:     "NM", "FM", or "AFM"
        dynamically_stable: True to require stable only
        max_results:        default 20
    """
    # require at least one filter
    if not any([formula, elements, bandgap_min, bandgap_max,
                magnetic_state, dynamically_stable is not None]):
        return {
            "status":  "error",
            "message": (
                "Provide at least one filter: formula, elements, "
                "bandgap_min/max, magnetic_state, or dynamically_stable."
            ),
        }
 
    try:
        from .c2db_loader import get_c2db_config, validate_c2db_config
        from .c2db_search import search_c2db_ase_db, search_c2db_cif_folder
 
        valid, err = validate_c2db_config()
        if not valid:
            return {"status": "error", "message": err}
 
        fmt = get_c2db_config()["format"]
 
        if fmt == "ase_db":
            results = search_c2db_ase_db(
                formula=formula,
                elements=elements,
                bandgap_min=bandgap_min,
                bandgap_max=bandgap_max,
                magnetic_state=magnetic_state,
                dynamically_stable=dynamically_stable,
                max_results=max_results,
            )
        else:
            results = search_c2db_cif_folder(
                formula=formula,
                elements=elements,
                max_results=max_results,
            )
 
        if not results:
            return {
                "status":  "not_found",
                "message": "No matching C2DB material found.",
                "results": [],
            }
 
        return {
            "status":  "success",
            "message": f"Found {len(results)} C2DB material(s).",
            "count":   len(results),
            "results": results,
        }
 
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception("search_c2db_material failed")
        return {"status": "error", "message": f"C2DB search failed: {e}"}
 
 
# ── Tool 2: generate_poscar_from_c2db ─────────────────────────────────────────
 
def generate_poscar_from_c2db(
    formula:     Optional[str] = None,
    c2db_id:     Optional[str] = None,
    db_id:       Optional[int] = None,
    cif_path:    Optional[str] = None,
    output_name: str           = "POSCAR",
) -> dict:
    """
    Convert a C2DB entry into a VASP POSCAR file in the session folder.
 
    Use after search_c2db_material or when user asks to generate a
    POSCAR from C2DB. Writes POSCAR to session_dir/C2DB/{formula}/POSCAR
    AND to session_dir/POSCAR (root) so downstream tools find it.
 
    Args:
        formula:     Chemical formula, e.g. "MoS2"
        c2db_id:     UID from search results
        db_id:       Integer ASE DB row id from search results
        cif_path:    Direct CIF file path (cif_folder format)
        output_name: Output filename, default "POSCAR"
    """
    if not any([formula, c2db_id, db_id, cif_path]):
        return {
            "status":  "error",
            "message": "Provide formula, c2db_id, db_id, or cif_path.",
        }
 
    try:
        from .c2db_loader import get_c2db_config, validate_c2db_config
        from .c2db_search import (
            search_c2db_ase_db,
            search_c2db_cif_folder,
            get_atoms_from_ase_db,
            get_atoms_from_cif,
        )
 
        valid, err = validate_c2db_config()
        if not valid:
            return {"status": "error", "message": err}
 
        fmt      = get_c2db_config()["format"]
        runs_dir = _get_runs_dir()
        atoms    = None
        used_formula = formula or "unknown"
        entry_id     = c2db_id or str(db_id) or "unknown"
 
        # resolve atoms from whatever identifier was given
        if cif_path:
            atoms        = get_atoms_from_cif(cif_path)
            used_formula = Path(cif_path).stem
 
        elif db_id is not None:
            if fmt != "ase_db":
                return {"status": "error", "message": "db_id only works with C2DB_FORMAT=ase_db."}
            atoms = get_atoms_from_ase_db(db_id)
 
        elif c2db_id or formula:
            if fmt == "ase_db":
                results = search_c2db_ase_db(formula=formula, max_results=1)
                if not results:
                    return {"status": "not_found", "message": f"No C2DB entry for '{formula}'."}
                first        = results[0]
                atoms        = get_atoms_from_ase_db(first["db_id"])
                used_formula = first["formula"] or used_formula
                entry_id     = first["id"]
            else:
                results = search_c2db_cif_folder(formula=formula, max_results=1)
                if not results:
                    return {"status": "not_found", "message": f"No CIF found for '{formula}'."}
                first        = results[0]
                atoms        = get_atoms_from_cif(first["cif_path"])
                used_formula = first["formula"] or used_formula
 
        if atoms is None:
            return {"status": "error", "message": "Could not resolve C2DB structure."}
 
        # convert ASE Atoms → pymatgen Structure → POSCAR
        try:
            from pymatgen.io.ase import AseAtomsAdaptor
            from pymatgen.io.vasp import Poscar
        except ImportError:
            return {"status": "error", "message": "pymatgen not installed. Run: pip install pymatgen"}
 
        structure = AseAtomsAdaptor().get_structure(atoms)
        poscar    = Poscar(structure)
 
        # save to C2DB subfolder
        out_dir    = Path(runs_dir) / "C2DB" / used_formula
        out_dir.mkdir(parents=True, exist_ok=True)
        poscar_abs = str(out_dir / output_name)
        poscar.write_file(poscar_abs, direct=True)
 
        # also write to session root so find_best_poscar() picks it up
        root_poscar = str(Path(runs_dir) / "POSCAR")
        poscar.write_file(root_poscar, direct=True)
 
        rel = _rel(poscar_abs, runs_dir)
 
        return {
            "status":    "success",
            "message":   f"POSCAR generated from C2DB for '{used_formula}' (id: {entry_id}).",
            "poscar_path": poscar_abs,
            "rel_path":  rel,
            "formula":   used_formula,
            "c2db_id":   entry_id,
            "source":    "C2DB",
        }
 
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception("generate_poscar_from_c2db failed")
        return {"status": "error", "message": f"POSCAR generation failed: {e}"}
 
 
# ── Tool 3: relax_c2db_structure_with_mace ────────────────────────────────────
 
def relax_c2db_structure_with_mace(
    poscar_path: Optional[str]   = None,
    model_path:  Optional[str]   = None,
    fmax:        float           = 0.02,
    steps:       int             = 500,
    device:      Optional[str]   = None,
) -> dict:
    """
    Relax a POSCAR structure using the MACE machine-learning potential.
 
    MACE does NOT need INCAR/KPOINTS/POTCAR — only the structure.
    Use 'mace-mp-0' as model_path to use the universal foundation model.
    Run after generate_poscar_from_c2db.
 
    Args:
        poscar_path: Path to POSCAR (defaults to session POSCAR)
        model_path:  MACE .model file or 'mace-mp-0' for foundation model
        fmax:        Force convergence threshold eV/Å (default 0.02)
        steps:       Max relaxation steps (default 500)
        device:      'cuda', 'cpu', or None for auto-detect
    """
    runs_dir = _get_runs_dir()
 
    # resolve POSCAR path
    if not poscar_path:
        poscar_path = os.path.join(runs_dir, "POSCAR")
    if not os.path.exists(poscar_path):
        return {
            "status":  "error",
            "message": f"POSCAR not found at '{poscar_path}'. Run generate_poscar_from_c2db first.",
        }
 
    # resolve model path
    if not model_path:
        model_path = os.environ.get("MACE_MODEL_PATH", "")
    if not model_path:
        return {
            "status":  "error",
            "message": (
                "MACE model not configured. "
                "Set MACE_MODEL_PATH=mace-mp-0 in .env, "
                "or pass model_path='mace-mp-0'."
            ),
        }
 
    # auto-detect device
    if not device or device == "auto":
        device = os.environ.get("MLP_DEVICE", "auto")
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
 
    try:
        from ase.io import read, write
 
        atoms = read(poscar_path, format="vasp")
 
        # load MACE calculator
        try:
            from mace.calculators import MACECalculator, mace_mp
        except ImportError:
            return {
                "status":  "error",
                "message": "MACE not installed. Run: pip install mace-torch",
            }
 
        if model_path == "mace-mp-0":
            # universal foundation model — downloads ~50MB on first use
            calc        = mace_mp(model="medium", device=device, default_dtype="float64")
            model_label = "MACE-MP-0 (foundation)"
        else:
            if not os.path.exists(model_path):
                return {"status": "error", "message": f"MACE model not found: '{model_path}'"}
            calc        = MACECalculator(model_paths=model_path, device=device, default_dtype="float64")
            model_label = os.path.basename(model_path)
 
        atoms.calc = calc
 
        # run relaxation
        from ase.optimize import LBFGS
 
        poscar_dir = os.path.dirname(poscar_path)
        traj_path  = os.path.join(poscar_dir, "mace_relaxation.traj")
        log_path   = os.path.join(poscar_dir, "mace_relaxation.log")
 
        opt       = LBFGS(atoms, logfile=log_path, trajectory=traj_path)
        converged = opt.run(fmax=fmax, steps=steps)
 
        # save relaxed structure as CONTCAR
        contcar_path = os.path.join(poscar_dir, "CONTCAR")
        write(contcar_path, atoms, format="vasp", direct=True)
 
        import numpy as np
        final_energy = float(atoms.get_potential_energy())
        max_force    = float(np.max(np.linalg.norm(atoms.get_forces(), axis=1)))
 
        status_msg = "converged" if converged else "not converged (max steps reached)"
 
        return {
            "status":              "success",
            "message":             (
                f"MACE relaxation {status_msg}. "
                f"Final energy: {final_energy:.4f} eV, "
                f"Max force: {max_force:.4f} eV/Å. "
                f"Device: {device}, Model: {model_label}."
            ),
            "converged":           converged,
            "final_energy_ev":     final_energy,
            "max_force_ev_per_ang": max_force,
            "device_used":         device,
            "model":               model_label,
            "contcar_path":        contcar_path,
            "rel_contcar":         _rel(contcar_path, runs_dir),
            "rel_trajectory":      _rel(traj_path, runs_dir),
            "rel_log":             _rel(log_path, runs_dir),
        }
 
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.exception("relax_c2db_structure_with_mace failed")
        return {"status": "error", "message": f"MACE relaxation failed: {e}"}
