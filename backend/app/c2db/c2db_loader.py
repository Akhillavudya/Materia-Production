
# app/c2db/c2db_loader.py
# Handles all C2DB database access — ASE .db file or CIF folder format.
# Called by c2db_search.py and c2db_tools.py — never directly by the agent.
 
import os
import logging
from pathlib import Path
 
logger = logging.getLogger(__name__)
 
 
def get_c2db_config() -> dict:
    """
    Read C2DB configuration from environment variables.
    Set in .env:
        C2DB_PATH=/home/roy/Desktop/c2db.db
        C2DB_FORMAT=ase_db   (or cif_folder)
    """
    return {
        "path":   os.environ.get("C2DB_PATH",   ""),
        "format": os.environ.get("C2DB_FORMAT", "ase_db"),
    }
 
 
def validate_c2db_config() -> tuple[bool, str]:
    """
    Check that C2DB is configured and the path actually exists.
    Returns (is_valid, error_message).
    Called before any DB access so we get a clean error instead of a crash.
    """
    config = get_c2db_config()
 
    if not config["path"]:
        return False, (
            "C2DB_PATH is not set. "
            "Add C2DB_PATH=/path/to/c2db.db to your .env file. "
            "Download C2DB from https://cmrdb.fysik.dtu.dk/c2db"
        )
 
    path = Path(config["path"])
    if not path.exists():
        return False, (
            f"C2DB_PATH '{config['path']}' does not exist. "
            "Download from https://cmrdb.fysik.dtu.dk/c2db"
        )
 
    fmt = config["format"]
    if fmt == "ase_db":
        if not path.is_file():
            return False, f"C2DB_FORMAT is 'ase_db' but '{config['path']}' is not a file."
    elif fmt == "cif_folder":
        if not path.is_dir():
            return False, f"C2DB_FORMAT is 'cif_folder' but '{config['path']}' is not a directory."
    else:
        return False, f"Unknown C2DB_FORMAT '{fmt}'. Use 'ase_db' or 'cif_folder'."
 
    return True, ""
 
 
def connect_ase_db():
    """
    Open and return an ASE database connection.
    Raises RuntimeError with a helpful message if not configured.
    """
    valid, err = validate_c2db_config()
    if not valid:
        raise RuntimeError(err)
 
    try:
        from ase.db import connect
        return connect(get_c2db_config()["path"])
    except ImportError:
        raise RuntimeError("ASE is not installed. Run: pip install ase")
    except Exception as e:
        raise RuntimeError(f"Failed to open C2DB database: {e}")
 
 
def list_cif_files() -> list[Path]:
    """Return all CIF files under the configured CIF folder."""
    valid, err = validate_c2db_config()
    if not valid:
        raise RuntimeError(err)
    folder = Path(get_c2db_config()["path"])
    return list(folder.rglob("*.cif"))
 
 
def row_to_entry(row) -> dict:
    """
    Convert an ASE DB row to a standardised Materia C2DB entry dict.
    All keys are consistent regardless of which DB format was used.
    None is used for missing properties — never raise on missing keys.
    """
    return {
        "id":                       str(row.get("uid", row.id)),
        "db_id":                    row.id,
        "formula":                  row.formula,
        "source":                   "C2DB",
        # electronic
        "bandgap_pbe":              _safe(row, "gap"),
        "bandgap_hse":              _safe(row, "gap_hse"),
        "bandgap_gw":               _safe(row, "gap_gw"),
        # thermodynamic
        "heat_of_formation":        _safe(row, "hform"),
        "energy_above_hull":        _safe(row, "ehull"),
        "dynamically_stable":       _safe(row, "dynamic_stability_level"),
        "thermodynamically_stable": _safe(row, "thermodynamic_stability_level"),
        # magnetic
        "magnetic_state":           _safe(row, "magstate"),
        "magnetic_moment":          _safe(row, "magmom"),
        # crystal
        "space_group":              _safe(row, "spacegroup"),
        "crystal_type":             _safe(row, "crystal_type"),
        "prototype":                _safe(row, "prototype"),
        # mechanical
        "stiffness_c11":            _safe(row, "c_11"),
        "stiffness_c12":            _safe(row, "c_12"),
    }
 
 
def _safe(row, key, default=None):
    """Safely get any attribute from an ASE DB row — never throws."""
    try:
        val = getattr(row, key, default)
        if val is None:
            val = row.get(key, default)
        return val
    except Exception:
        return default
