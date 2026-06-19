"""The unified `MaterialCard` model (architecture redesign §7).

Every search provider produces this one model via `services/search/mappers.py`,
so the rest of the system sees a single, validated shape regardless of source.

Identity is canonical and source-routable: `id` carries a source prefix
(``mp-19306`` | ``c2db-<uid>`` | ``oqmd-12345``) so
``SearchService.get_structure(id)`` can route by prefix with no source guessing.

Rules:
- Missing data is ``None`` — never ``0`` or the string ``"None"``.
- Energies are normalised to eV / eV-per-atom in the mappers, not here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Source(str, Enum):
    MP = "mp"
    C2DB = "c2db"
    OQMD = "oqmd"


class Dimensionality(str, Enum):
    BULK = "3D"
    LAYERED = "2D"
    UNKNOWN = "unknown"


class MaterialCard(BaseModel):
    """A single material returned by a search provider."""

    # ── Identity ──────────────────────────────────────────────────────────────
    id: str                       # canonical: "mp-19306" | "c2db-<uid>" | "oqmd-12345"
    source: Source
    source_id: str                # native id used to re-fetch the structure

    # ── Composition ───────────────────────────────────────────────────────────
    formula: str                  # reduced/pretty, e.g. "MoS2"
    elements: list[str] = Field(default_factory=list)
    n_atoms: int | None = None
    dimensionality: Dimensionality = Dimensionality.UNKNOWN

    # ── Electronic / energetics (eV or eV/atom; None if unavailable) ──────────
    band_gap_eV: float | None = None
    formation_energy_eV_per_atom: float | None = None
    energy_above_hull_eV_per_atom: float | None = None
    energy_per_atom_eV: float | None = None
    is_stable: bool | None = None

    # ── Structure / symmetry ──────────────────────────────────────────────────
    spacegroup_symbol: str | None = None
    spacegroup_number: int | None = None
    crystal_system: str | None = None     # cubic | tetragonal | … (the "geometry")
    magnetic: bool | None = None
    density_g_cm3: float | None = None
    has_structure: bool = True

    # ── Provenance ────────────────────────────────────────────────────────────
    source_url: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
