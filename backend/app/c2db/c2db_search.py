# app/c2db/c2db_search.py
# Search logic for both ASE .db and CIF folder formats.
# Called by c2db_tools.py and bayes_opt.py.
 
import re
import logging
from pathlib import Path
from typing import Optional
 
from .c2db_loader import connect_ase_db, list_cif_files, row_to_entry
 
logger = logging.getLogger(__name__)
 
 
def search_c2db_ase_db(
    formula:            Optional[str]   = None,
    elements:           Optional[list]  = None,
    bandgap_min:        Optional[float] = None,
    bandgap_max:        Optional[float] = None,
    magnetic_state:     Optional[str]   = None,
    dynamically_stable: Optional[bool]  = None,
    max_results:        int             = 20,
) -> list[dict]:
    """
    Search the C2DB ASE .db file.
    Builds an ASE query string for indexed fields, then post-filters.
    Returns a list of standardised entry dicts.
    """
    db = connect_ase_db()
 
    # build ASE query string for fields that are indexed in the DB
    query_parts = []
    if formula:
        query_parts.append(f"formula={formula}")
    if magnetic_state:
        query_parts.append(f"magstate={magnetic_state}")
    if dynamically_stable is True:
        query_parts.append("dynamic_stability_level=high")
    elif dynamically_stable is False:
        query_parts.append("dynamic_stability_level!=high")
 
    query_str = ",".join(query_parts) if query_parts else None
 
    try:
        # over-fetch then post-filter for bandgap range and elements
        rows = list(db.select(query_str, limit=max_results * 5))
    except Exception as e:
        raise RuntimeError(f"C2DB query failed: {e}")
 
    results = []
    for row in rows:
        entry = row_to_entry(row)
 
        # post-filter: all requested elements must appear in formula
        if elements:
            found = set(re.findall(r"[A-Z][a-z]?", entry.get("formula") or ""))
            if not set(elements).issubset(found):
                continue
 
        # post-filter: PBE bandgap range
        gap = entry.get("bandgap_pbe")
        if gap is not None:
            if bandgap_min is not None and gap < bandgap_min:
                continue
            if bandgap_max is not None and gap > bandgap_max:
                continue
 
        results.append(entry)
        if len(results) >= max_results:
            break
 
    return results
 
 
def search_c2db_cif_folder(
    formula:     Optional[str]  = None,
    elements:    Optional[list] = None,
    max_results: int            = 20,
) -> list[dict]:
    """
    Search a CIF folder by filename pattern.
    Returns minimal entry dicts — no property data available.
    """
    results = []
    for cif_path in list_cif_files():
        name = cif_path.stem
        if formula and formula.lower() not in name.lower():
            continue
        if elements and not all(el in name for el in elements):
            continue
 
        results.append({
            "id":               name,
            "db_id":            None,
            "formula":          _extract_formula(name),
            "cif_path":         str(cif_path),
            "source":           "C2DB",
            "bandgap_pbe":      None,
            "heat_of_formation": None,
            "magnetic_state":   None,
            "space_group":      None,
        })
        if len(results) >= max_results:
            break
 
    return results
 
 
def get_atoms_from_ase_db(db_id: int):
    """Retrieve an ASE Atoms object from the C2DB ASE database by row ID."""
    db  = connect_ase_db()
    row = db.get(id=db_id)
    return row.toatoms()
 
 
def get_atoms_from_cif(cif_path: str):
    """Load an ASE Atoms object from a CIF file."""
    try:
        from ase.io import read
        return read(cif_path)
    except ImportError:
        raise RuntimeError("ASE is not installed. Run: pip install ase")
    except Exception as e:
        raise RuntimeError(f"Failed to read CIF: {e}")
 
 
def _extract_formula(name: str) -> str:
    """Extract a formula string from a CIF filename, e.g. 'MoS2-ABC-123' → 'MoS2'."""
    m = re.match(r"^([A-Za-z0-9]+)", name)
    return m.group(1) if m else name
