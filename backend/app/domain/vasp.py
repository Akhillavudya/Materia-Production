"""VASP domain enums and the input-set summary model (redesign §9).

Framework-agnostic vocabulary shared by the VASP service, the
`generate_vasp_inputs` tool, and the `/api/vasp/tasks` catalog endpoint.

The core tasks (``STATIC``, ``RELAXATION``, ``BAND``, ``DOS``) plus the Step 5.5
single-directory tasks (``AIMD``, ``ELASTIC``, ``PHONON_DFPT``, ``DIELECTRIC``,
``BADER``, ``ELF``, ``WORKFUNCTION``) are all wired in the VASP service. ``BAND``
emits a non-self-consistent line-mode KPOINTS path, ``DOS`` a dense tetrahedron
mesh, and ``AIMD`` a Γ-only mesh (§9 "VASP completeness").
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class VaspTask(str, Enum):
    STATIC = "static"
    RELAXATION = "relaxation"
    BAND = "band"          # non-SCF band structure (line-mode KPOINTS)
    DOS = "dos"            # dense tetrahedron DOS
    # Step 5.5 — single-directory calculation types.
    AIMD = "aimd"                  # ab-initio MD (IBRION=0); Gamma-only mesh
    ELASTIC = "elastic"            # elastic constants (IBRION=6)
    PHONON_DFPT = "phonon_dfpt"    # DFPT Γ-phonons (IBRION=8)
    DIELECTRIC = "dielectric"      # frequency-dependent dielectric (LOPTIC)
    BADER = "bader"                # all-electron density for Bader (LAECHG)
    ELF = "elf"                    # electron localization function (LELF)
    WORKFUNCTION = "workfunction"  # slab potential + dipole (LVTOT/LVHAR/LDIPOL)


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
    modifiers: dict[str, str] = Field(default_factory=dict)   # applied non-default modifiers
    nelect: float | None = None                               # set only for charged cells
