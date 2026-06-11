"""
backend/app/tools/schemas.py
==============================
Pydantic schemas for Materia material tool inputs and outputs.
Used for validation in material_tools.py and API endpoints.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


# ── Request schemas ───────────────────────────────────────────────────────────

class MaterialSearchRequest(BaseModel):
    formula:         Optional[str]   = None
    element:         Optional[str]   = None
    elements:        Optional[str]   = None
    max_gap:         Optional[float] = None
    min_gap:         Optional[float] = None
    max_formation_e: Optional[float] = None
    limit:           int             = Field(default=10, ge=1, le=50)


class PoscarRequest(BaseModel):
    material_id: str
    source:      str   # "mp" | "c2db" | "oqmd"
    name:        Optional[str] = None


# ── Material card schema (returned in search results) ─────────────────────────

class MaterialCard(BaseModel):
    id:               str
    formula:          str
    elements:         str
    source:           str

    gap_pbe:          Optional[float] = None
    formation_energy: Optional[float] = None
    energy_per_atom:  Optional[float] = None
    energy_above_hull:Optional[float] = None
    magnetic:         Optional[str]   = None
    natoms:           Optional[int]   = None
    spacegroup:       Optional[str]   = None

    has_structure:    bool            = True
    c2db_url:         Optional[str]   = None
    mp_id:            Optional[str]   = None
    oqmd_id:          Optional[str]   = None


# ── Response schemas ──────────────────────────────────────────────────────────

class MaterialSearchResponse(BaseModel):
    status:          str
    source_used:     Optional[str]  = None
    sources_tried:   List[str]      = []
    materials:       List[dict]     = []
    total_matching:  int            = 0
    returned:        int            = 0
    message:         str            = ""


class PoscarResponse(BaseModel):
    status:       str
    message:      str
    formula:      Optional[str]   = None
    n_sites:      Optional[int]   = None
    lattice_a:    Optional[float] = None
    lattice_b:    Optional[float] = None
    lattice_c:    Optional[float] = None
    poscar_path:  Optional[str]   = None
    named_path:   Optional[str]   = None
    files_written:List[str]       = []
    source:       Optional[str]   = None
    material_id:  Optional[str]   = None