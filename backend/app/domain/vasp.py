"""VASP domain enums and the input-set summary model (redesign §9).

Framework-agnostic vocabulary shared by the VASP service, the
`generate_vasp_inputs` tool, and the `/api/vasp/tasks` catalog endpoint.

All four tasks (``STATIC``, ``RELAXATION``, ``BAND``, ``DOS``) are wired in the
VASP service. ``BAND`` emits a non-self-consistent line-mode KPOINTS path and
``DOS`` a dense tetrahedron mesh (§9 "VASP completeness").
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class VaspTask(str, Enum):
    STATIC = "static"
    RELAXATION = "relaxation"
    BAND = "band"          # non-SCF band structure (line-mode KPOINTS)
    DOS = "dos"            # dense tetrahedron DOS


class CellRelax(str, Enum):
    NONE = "none"          # atoms only (ISIF 2)
    SHAPE = "shape"        # shape + positions, fixed volume (ISIF 5)
    FULL = "full"          # shape + volume + positions (ISIF 3)


class VaspInputSet(BaseModel):
    """Machine-readable summary of a generated VASP input package."""

    task: VaspTask
    cell_relax: CellRelax = CellRelax.NONE
    encut: int | None = None
    kmesh: list[int] | None = None          # [kx, ky, kz]
    elements: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)  # logical name -> rel path
    formula: str | None = None
    n_sites: int | None = None
    potentials: dict[str, str] = Field(default_factory=dict)  # element -> POTCAR label
    warnings: list[str] = Field(default_factory=list)
