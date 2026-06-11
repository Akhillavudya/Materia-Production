"""
backend/app/services/search_service.py
========================================
Unified material search across all databases.

Public functions:
  search_mp / get_mp_structure         — Materials Project (REST API, key required)
  search_c2db / get_structure_from_c2db — C2DB (local ASE db, 2D materials)
  search_oqmd / get_oqmd_structure     — OQMD (REST API, no key needed)
  search_all_sources                   — chains MP → C2DB → OQMD in order
"""

import os
import re
import json
import urllib.request
import urllib.parse
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MATERIALS PROJECT
# ─────────────────────────────────────────────────────────────────────────────

def search_mp(
    formula:  Optional[str]   = None,
    element:  Optional[str]   = None,
    elements: Optional[str]   = None,
    max_gap:  Optional[float] = None,
    min_gap:  Optional[float] = None,
    limit:    int             = 10,
) -> dict:
    """Search Materials Project for bulk/3D structures."""
    api_key = os.environ.get("MP_API_KEY", "")
    if not api_key:
        return {
            "source":         "mp",
            "status":         "error",
            "error":          "MP_API_KEY not set. Save it via the Materia settings.",
            "results":        [],
            "total_matching": 0,
        }

    try:
        from mp_api.client import MPRester

        with MPRester(api_key=api_key, mute_progress_bars=True) as mpr:
            kwargs: dict = {}
            if formula:
                kwargs["formula"] = formula
            if element and not elements:
                kwargs["elements"] = [element]
            if elements:
                kwargs["elements"] = [e.strip() for e in elements.split(",") if e.strip()]
            if max_gap is not None or min_gap is not None:
                kwargs["band_gap"] = (
                    min_gap if min_gap is not None else 0.0,
                    max_gap if max_gap is not None else 100.0,
                )

            fields = [
                "material_id", "formula_pretty", "band_gap",
                "formation_energy_per_atom", "energy_per_atom",
                "symmetry", "energy_above_hull", "elements",
            ]
            docs = mpr.materials.summary.search(**kwargs, fields=fields)

            if not docs:
                return {"source": "mp", "status": "not_found", "results": [], "total_matching": 0}

            docs_sorted = sorted(docs, key=lambda d: d.energy_above_hull or 999)
            results = []
            for doc in docs_sorted[:limit]:
                elem_list = [str(e) for e in (doc.elements or [])]
                results.append({
                    "id":               str(doc.material_id),
                    "mp_id":            str(doc.material_id),
                    "formula":          doc.formula_pretty or formula or "",
                    "elements":         ",".join(elem_list),
                    "source":           "mp",
                    "gap_pbe":          doc.band_gap,
                    "formation_energy": doc.formation_energy_per_atom,
                    "energy_per_atom":  doc.energy_per_atom,
                    "energy_above_hull":doc.energy_above_hull,
                    "spacegroup":       doc.symmetry.symbol if doc.symmetry else None,
                    "magnetic":         None,
                    "natoms":           None,
                    "has_structure":    True,
                    "c2db_url":         None,
                    "oqmd_id":          None,
                })

            return {
                "source":         "mp",
                "status":         "ok",
                "results":        results,
                "total_matching": len(docs),
                "returned":       len(results),
            }

    except Exception as e:
        return {"source": "mp", "status": "error", "error": str(e), "results": [], "total_matching": 0}


def get_mp_structure(mp_id: str, api_key: Optional[str] = None):
    """Fetch pymatgen Structure for a specific MP material_id."""
    key = api_key or os.environ.get("MP_API_KEY", "")
    if not key:
        return None
    try:
        from mp_api.client import MPRester
        with MPRester(api_key=key, mute_progress_bars=True) as mpr:
            return mpr.get_structure_by_material_id(mp_id, conventional_unit_cell=True)
    except Exception as e:
        logger.warning("MP get_structure error for %s: %s", mp_id, e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# C2DB
# ─────────────────────────────────────────────────────────────────────────────

C2DB_DB = os.environ.get("C2DB_DB", "/data/c2db/c2db.db")


def search_c2db(
    formula:  Optional[str]   = None,
    element:  Optional[str]   = None,
    elements: Optional[str]   = None,
    max_gap:  Optional[float] = None,
    min_gap:  Optional[float] = None,
    limit:    int             = 10,
) -> dict:
    """Search C2DB (local ASE database, 2D materials)."""
    try:
        from ase.db import connect
        db   = connect(C2DB_DB)
        rows = db.select(formula=formula) if formula else db.select()

        results = []
        for row in rows:
            kv         = row.key_value_pairs or {}
            formula_db = row.formula

            if element and element not in formula_db:
                continue
            if elements:
                required = [e.strip() for e in elements.split(",") if e.strip()]
                if not all(e in formula_db for e in required):
                    continue

            gap = kv.get("gap")
            if max_gap is not None and (gap is None or gap > max_gap):
                continue
            if min_gap is not None and (gap is None or gap < min_gap):
                continue

            atoms     = row.toatoms()
            elem_list = sorted(set(atoms.get_chemical_symbols()))

            results.append({
                "id":               f"c2db:{row.id}",
                "formula":          formula_db,
                "elements":         ",".join(elem_list),
                "source":           "c2db",
                "gap_pbe":          gap,
                "formation_energy": kv.get("hform"),
                "energy_per_atom":  None,
                "energy_above_hull":kv.get("ehull"),
                "spacegroup":       kv.get("international"),
                "magnetic":         str(kv.get("is_magnetic")),
                "natoms":           row.natoms,
                "has_structure":    True,
                "c2db_uid":         kv.get("uid"),
                "c2db_url":         None,
                "mp_id":            None,
                "oqmd_id":          None,
            })

            if len(results) >= limit:
                break

        if not results:
            return {"source": "c2db", "status": "not_found", "results": [], "total_matching": 0}

        return {
            "source":         "c2db",
            "status":         "ok",
            "results":        results,
            "total_matching": len(results),
            "returned":       len(results),
        }

    except Exception as e:
        return {"source": "c2db", "status": "error", "error": str(e), "results": [], "total_matching": 0}


def get_structure_from_c2db(material_id: str):
    """Fetch pymatgen Structure from C2DB. Accepts 'c2db:123' or '123'."""
    try:
        from ase.db import connect
        from pymatgen.io.ase import AseAtomsAdaptor

        db_id = int(str(material_id).replace("c2db:", ""))
        db    = connect(C2DB_DB)
        row   = db.get(id=db_id)
        if row is None:
            return None
        return AseAtomsAdaptor.get_structure(row.toatoms())
    except Exception as e:
        logger.warning("C2DB structure retrieval error: %s", e)
        return None


# Compatibility alias
get_c2db_structure = get_structure_from_c2db


# ─────────────────────────────────────────────────────────────────────────────
# OQMD
# ─────────────────────────────────────────────────────────────────────────────

OQMD_BASE    = "https://oqmd.org/oqmdapi/formationenergy"
OQMD_TIMEOUT = int(os.environ.get("OQMD_TIMEOUT", "120"))


def _oqmd_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Materia/1.0 (materials search)"})
    try:
        with urllib.request.urlopen(req, timeout=OQMD_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def search_oqmd(
    formula:         Optional[str]   = None,
    element:         Optional[str]   = None,
    elements:        Optional[str]   = None,
    max_formation_e: Optional[float] = None,
    limit:           int             = 10,
) -> dict:
    """Search OQMD via the public REST API (no API key required)."""
    limit  = min(int(limit), 50)
    params: dict[str, str] = {
        "limit":  str(limit),
        "offset": "0",
        "fields": "name,entry_id,composition,delta_e,stability,band_gap,spacegroup",
    }

    if formula:
        params["composition"] = formula
    elif element and not elements:
        params["composition"] = element
    elif elements:
        params["composition"] = "-".join(e.strip() for e in elements.split(",") if e.strip())

    if max_formation_e is not None:
        params["delta_e__lte"] = str(float(max_formation_e))

    url  = f"{OQMD_BASE}?{urllib.parse.urlencode(params)}"
    data = _oqmd_get(url)

    if "error" in data:
        return {"source": "oqmd", "status": "error", "error": data["error"], "results": [], "total_matching": 0}

    raw_results = data.get("data") or data.get("results") or []
    total       = data.get("meta", {}).get("total_count", len(raw_results))

    if not raw_results:
        return {"source": "oqmd", "status": "not_found", "results": [], "total_matching": 0}

    results = []
    for item in raw_results:
        entry_id  = item.get("entry_id") or item.get("id") or ""
        name      = item.get("name") or item.get("composition") or formula or ""
        delta_e   = item.get("delta_e")
        stability = item.get("stability")
        band_gap  = item.get("band_gap")
        sg        = item.get("spacegroup") or item.get("space_group")
        elem_syms = sorted(set(re.findall(r"[A-Z][a-z]?", name)))

        results.append({
            "id":               f"oqmd:{entry_id}",
            "oqmd_id":          str(entry_id),
            "formula":          name,
            "elements":         ",".join(elem_syms),
            "source":           "oqmd",
            "gap_pbe":          float(band_gap) if band_gap is not None else None,
            "formation_energy": float(delta_e)  if delta_e  is not None else None,
            "energy_per_atom":  None,
            "energy_above_hull":float(stability) if stability is not None else None,
            "spacegroup":       sg,
            "magnetic":         None,
            "natoms":           None,
            "has_structure":    True,
            "c2db_url":         None,
            "mp_id":            None,
            "oqmd_url":         f"https://oqmd.org/materials/entry/{entry_id}",
        })

    return {
        "source":         "oqmd",
        "status":         "ok",
        "results":        results,
        "total_matching": total,
        "returned":       len(results),
    }


def get_oqmd_structure(entry_id: str):
    """Fetch pymatgen Structure for an OQMD entry."""
    try:
        from pymatgen.core import Structure, Lattice
    except ImportError:
        logger.warning("pymatgen not installed")
        return None

    data = _oqmd_get(f"https://oqmd.org/oqmdapi/entry/{entry_id}")
    if "error" in data:
        logger.warning("OQMD error: %s", data["error"])
        return None

    try:
        lattice         = Lattice(data["unit_cell"])
        species: list   = []
        coords:  list   = []
        for site in data["sites"]:
            left, right = site.split("@")
            species.append(left.strip())
            coords.append([float(x) for x in right.strip().split()])
        return Structure(lattice, species, coords, coords_are_cartesian=False)
    except Exception as e:
        logger.warning("OQMD structure parse error: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# UNIFIED SEARCH
# ─────────────────────────────────────────────────────────────────────────────

_FOUND_THRESHOLD = 1


def search_all_sources(
    formula:         Optional[str]   = None,
    element:         Optional[str]   = None,
    elements:        Optional[str]   = None,
    max_gap:         Optional[float] = None,
    min_gap:         Optional[float] = None,
    max_formation_e: Optional[float] = None,
    limit:           int             = 10,
    sources:         Optional[list]  = None,
) -> dict:
    """
    Search MP → C2DB → OQMD in order, stopping at the first source with results.

    Returns:
    {
      "results":              [...unified material dicts...],
      "total_matching":       int,
      "source_used":          "mp" | "c2db" | "oqmd" | None,
      "sources_tried":        [str, ...],
      "status":               "ok" | "not_found",
      "all_source_responses": {source: response_dict, ...},
    }
    """
    order           = sources or ["mp", "c2db", "oqmd"]
    tried:          list[str] = []
    all_responses:  dict      = {}

    for source in order:
        logger.info("UnifiedSearch: trying %s", source)
        tried.append(source)

        resp = _query_source(
            source=source, formula=formula, element=element, elements=elements,
            max_gap=max_gap, min_gap=min_gap, max_formation_e=max_formation_e,
            limit=limit,
        )
        all_responses[source] = {
            "status":         resp.get("status"),
            "returned":       resp.get("returned", 0),
            "total_matching": resp.get("total_matching", 0),
            "error":          resp.get("error"),
        }

        results = resp.get("results", [])
        if len(results) >= _FOUND_THRESHOLD:
            logger.info("UnifiedSearch: found %d results in %s", len(results), source)
            return {
                "results":              results,
                "total_matching":       resp.get("total_matching", len(results)),
                "returned":             len(results),
                "source_used":          source,
                "sources_tried":        tried,
                "status":               "ok",
                "all_source_responses": all_responses,
            }

        if resp.get("status") in ("error", "unavailable"):
            logger.warning("UnifiedSearch: %s unavailable: %s", source, resp.get("error", ""))
        else:
            logger.info("UnifiedSearch: %s not found", source)

    return {
        "results":              [],
        "total_matching":       0,
        "returned":             0,
        "source_used":          None,
        "sources_tried":        tried,
        "status":               "not_found",
        "all_source_responses": all_responses,
    }


def _query_source(
    source:          str,
    formula:         Optional[str],
    element:         Optional[str],
    elements:        Optional[str],
    max_gap:         Optional[float],
    min_gap:         Optional[float],
    max_formation_e: Optional[float],
    limit:           int,
) -> dict:
    try:
        if source == "mp":
            return search_mp(formula=formula, element=element, elements=elements,
                             max_gap=max_gap, min_gap=min_gap, limit=limit)
        if source == "c2db":
            return search_c2db(formula=formula, element=element, elements=elements,
                               max_gap=max_gap, min_gap=min_gap, limit=limit)
        if source == "oqmd":
            return search_oqmd(formula=formula, element=element, elements=elements,
                               max_formation_e=max_formation_e, limit=limit)
        return {
            "source": source, "status": "error",
            "error": f"Unknown source: {source}", "results": [], "total_matching": 0,
        }
    except Exception as e:
        logger.exception("UnifiedSearch: query error for %s", source)
        return {"source": source, "status": "error", "error": str(e), "results": [], "total_matching": 0}
