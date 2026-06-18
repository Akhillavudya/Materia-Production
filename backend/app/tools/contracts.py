"""Pydantic in/out contracts for the four agent tools (redesign §14).

The `tool_registry` derives its arg list and human-readable arg descriptions from
these models (via `args_and_desc`), so there is a single source of truth for tool
schemas — no hand-written description drift.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.core.config import settings

# ── 14.1 search_materials ─────────────────────────────────────────────────────

class SearchMaterialsInput(BaseModel):
    formula: Optional[str] = Field(
        None, description='chemical formula, e.g. "MoS2" or "NaCl"')
    element: Optional[str] = Field(
        None, description='single element that must be present, e.g. "Mo"')
    elements: Optional[str] = Field(
        None, description='comma-separated elements that must all be present, e.g. "Mo,S"')
    min_gap: Optional[float] = Field(None, description="minimum PBE band gap [eV]")
    max_gap: Optional[float] = Field(None, description="maximum PBE band gap [eV]")
    max_formation_e: Optional[float] = Field(
        None, description="maximum formation energy [eV/atom]")
    dimensionality: Optional[str] = Field(
        None, description='"2D" or "3D" filter (optional)')
    limit: int = Field(10, description="max results to return (1-20)")


# ── 14.2 generate_vasp_inputs ─────────────────────────────────────────────────

class GenerateVaspInputsInput(BaseModel):
    material_id: Optional[str] = Field(
        None, description='id from search_materials, e.g. "mp-19306" (with source)')
    source: Optional[str] = Field(
        None, description='"mp" | "c2db" | "oqmd" (paired with material_id)')
    poscar_path: Optional[str] = Field(
        None, description="existing session structure file to use instead of an id")
    task: str = Field(
        "relaxation",
        description=('calculation type: "static" | "relaxation" | "band" | "dos" | '
                    '"aimd" | "elastic" | "phonon_dfpt" | "dielectric" | "bader" | '
                    '"elf" | "workfunction"'))
    cell_relax: str = Field(
        "none", description='"none" | "shape" | "full"')
    # ── modifiers (Step 5.5) — combine freely with any task ──
    functional: str = Field(
        "pbe", description='exchange-correlation functional: "pbe" | "hse06" | "scan"')
    vdw: str = Field(
        "none",
        description='van-der-Waals correction: "none" | "d3" | "d3bj" | "optb88" | "df2"')
    soc: bool = Field(
        False, description="enable spin-orbit coupling (noncollinear)")
    hubbard_u: bool = Field(
        False, description="enable DFT+U (curated U values for transition-metal d-electrons)")
    dipole: bool = Field(
        False, description="add a dipole correction along c (slabs / charged cells)")
    solvent: str = Field(
        "none",
        description=('implicit solvation: "none" | "vaspsol" | "vaspsol++" '
                     '(requires the VASPsol-patched VASP binary)'))
    charge: float = Field(
        0.0, description="net cell charge in e (positive = electrons removed); sets NELECT")


# ── 14.3 optimize_structure ───────────────────────────────────────────────────

# Shared, model-facing help for the ML-potential selection args (used by both
# optimize_structure and run_md_simulation). Mirrors calculator_factory.
_CALC_TYPE_DESC = (
    'ML potential family: "mace" or "mattersim" (default "mace"). '
    'Accepts natural names like "MACE-MP" or "MatterSim Large".'
)
_CALC_MODEL_DESC = (
    "specific model/variant; omit for the family default. "
    "MACE: mace-mp-0b3-medium (default), mace-mpa-0-medium, mace-omat-0-medium, "
    "MACE-matpes-pbe-omat-ft. MatterSim: mattersim-v1.0.0-1M (default, 'small'), "
    "mattersim-v1.0.0-5M ('large'). Use list_models to discover what is available."
)


class OptimizeStructureInput(BaseModel):
    poscar_name: Optional[str] = Field(
        None, description="input file (auto-detects POSCAR if omitted)")
    fmax: float = Field(0.02, description="force convergence threshold [eV/Å]")
    cell_relax: str = Field("none", description='"none" | "shape" | "full"')
    optimizer: str = Field("FIRE", description='"FIRE" | "BFGS" | "LBFGS"')
    max_steps: int = Field(1000, ge=1, le=settings.max_opt_steps,
                           description="maximum optimizer steps")
    calculator_type: str = Field("mace", description=_CALC_TYPE_DESC)
    calculator_model: Optional[str] = Field(None, description=_CALC_MODEL_DESC)
    emit_vasp_inputs: bool = Field(
        True, description="also write INCAR + KPOINTS for VASP handoff")


# ── 14.4 run_md_simulation ────────────────────────────────────────────────────

class RunMdSimulationInput(BaseModel):
    poscar_name: Optional[str] = Field(
        None, description="input file (auto-detects CONTCAR/POSCAR if omitted)")
    ensemble: str = Field("nvt", description='"nvt" | "npt"')
    temperature: float = Field(300.0, description="target temperature [K]")
    nsw: int = Field(2000, ge=1, le=settings.max_md_steps,
                     description="total MD steps (CPU-bound: each step is one "
                                 "force eval, ~hundreds of ms; only go above a "
                                 "few thousand when the user explicitly asks)")
    timestep: float = Field(1.0, description="MD timestep [fs]")
    thermostat: str = Field(
        "langevin", description="langevin|nose-hoover (NVT) or berendsen|bussi (NPT)")
    pressure: float = Field(0.0, description="target pressure [GPa], NPT only")
    calculator_type: str = Field("mace", description=_CALC_TYPE_DESC)
    calculator_model: Optional[str] = Field(None, description=_CALC_MODEL_DESC)
    log_interval: int = Field(10, description="log every N steps")
    emit_vasp_inputs: bool = Field(
        True, description="also write INCAR + KPOINTS for VASP-MD handoff")


# ── 14.5 generate_poscar ──────────────────────────────────────────────────────

class GeneratePoscarInput(BaseModel):
    material_id: Optional[str] = Field(
        None, description='id from search_materials, e.g. "mp-19306" (with source)')
    source: Optional[str] = Field(
        None, description='"mp" | "c2db" | "oqmd" (paired with material_id)')
    poscar_path: Optional[str] = Field(
        None, description="existing session structure file to convert to a POSCAR")


# ── 14.9 build_structure (Step 5.5) ───────────────────────────────────────────

class BuildStructureInput(BaseModel):
    operation: str = Field(
        ...,
        description='"make_supercell" | "add_vacuum" | "make_slab" | "convert"')
    material_id: Optional[str] = Field(
        None, description="optional: fetch + transform a database structure instead of a session file")
    source: Optional[str] = Field(
        None, description='"mp" | "c2db" | "oqmd" (paired with material_id)')
    poscar_path: Optional[str] = Field(
        None, description="session structure to transform (defaults to the active POSCAR)")
    scaling: Optional[str] = Field(
        None, description='[make_supercell] supercell size, e.g. "2 2 1" or "2"')
    axis: str = Field(
        "c", description='[add_vacuum] axis to add vacuum along: "a" | "b" | "c"')
    thickness: float = Field(
        15.0, description="[add_vacuum] vacuum thickness in Å")
    center: bool = Field(
        True, description="[add_vacuum / make_slab] recenter atoms within the cell")
    miller: str = Field(
        "1 1 1", description='[make_slab] Miller index of the surface, e.g. "1 1 1"')
    min_slab_size: float = Field(
        10.0, description="[make_slab] minimum slab thickness in Å")
    min_vacuum_size: float = Field(
        15.0, description="[make_slab] vacuum gap in Å (slab already includes vacuum)")
    lll_reduce: bool = Field(
        True, description="[make_slab] LLL-reduce the slab cell")
    shift: float = Field(
        0.0, description="[make_slab] termination shift (selects which surface cut)")
    to_format: str = Field(
        "cif", description='[convert] output format: "poscar" | "cif" | "xyz" | "cssr" | "json"')


# ── 14.10 analyze_symmetry (Step 5.5) ─────────────────────────────────────────

class AnalyzeSymmetryInput(BaseModel):
    poscar_path: Optional[str] = Field(
        None, description="session structure to analyze (defaults to the active POSCAR)")
    material_id: Optional[str] = Field(
        None, description="optional: analyze a database structure instead of a session file")
    source: Optional[str] = Field(
        None, description='"mp" | "c2db" | "oqmd" (paired with material_id)')
    symprec: float = Field(
        0.01, description="symmetry tolerance in Å (larger = looser)")
    write: Optional[str] = Field(
        None, description='optionally save a standard cell as POSCAR: "primitive" | "conventional"')


# ── 14.11 defect tools (Step 5.5) ─────────────────────────────────────────────

class CreateVacancyInput(BaseModel):
    element: Optional[str] = Field(
        None, description="element to remove (defaults to the first site found)")
    supercell: Optional[str] = Field(
        None, description='supercell size, e.g. "2 2 2" (omit to auto-size for isolation)')
    poscar_path: Optional[str] = Field(
        None, description="session structure to use (defaults to the active POSCAR)")
    material_id: Optional[str] = Field(
        None, description="optional: use a database structure instead of a session file")
    source: Optional[str] = Field(
        None, description='"mp" | "c2db" | "oqmd" (paired with material_id)')


class CreateSubstitutionInput(BaseModel):
    from_element: str = Field(..., description="element being replaced, e.g. \"Si\"")
    to_element: str = Field(..., description="replacement element, e.g. \"Al\"")
    supercell: Optional[str] = Field(
        None, description='supercell size, e.g. "2 2 2" (omit to auto-size)')
    poscar_path: Optional[str] = Field(
        None, description="session structure to use (defaults to the active POSCAR)")
    material_id: Optional[str] = Field(
        None, description="optional: use a database structure instead of a session file")
    source: Optional[str] = Field(
        None, description='"mp" | "c2db" | "oqmd" (paired with material_id)')


class CreateInterstitialInput(BaseModel):
    insert_element: str = Field(..., description="element to insert, e.g. \"H\" or \"Li\"")
    supercell: Optional[str] = Field(
        None, description='supercell size, e.g. "2 2 2" (omit to auto-size)')
    poscar_path: Optional[str] = Field(
        None, description="session structure to use (defaults to the active POSCAR)")
    material_id: Optional[str] = Field(
        None, description="optional: use a database structure instead of a session file")
    source: Optional[str] = Field(
        None, description='"mp" | "c2db" | "oqmd" (paired with material_id)')


# ── 14.6 read_file ────────────────────────────────────────────────────────────

class ReadFileInput(BaseModel):
    filename: Optional[str] = Field(
        None,
        description="file to read; omit to auto-pick the most recent uploaded file")


# ── 14.7 list_files ───────────────────────────────────────────────────────────

class ListFilesInput(BaseModel):
    """No arguments — lists every file in the current session."""


# ── 14.8 list_models ──────────────────────────────────────────────────────────

class ListModelsInput(BaseModel):
    """No arguments — lists the available ML-potential models."""


def args_and_desc(model: type[BaseModel]) -> tuple[list[str], str]:
    """Return (arg names, human-readable arg description) from a model's fields."""
    names = list(model.model_fields.keys())
    desc = "; ".join(
        f"{name}: {field.description}"
        for name, field in model.model_fields.items()
        if field.description
    )
    return names, desc
