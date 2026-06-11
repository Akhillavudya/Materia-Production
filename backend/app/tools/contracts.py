"""Pydantic in/out contracts for the four agent tools (redesign §14).

The `tool_registry` derives its arg list and human-readable arg descriptions from
these models (via `args_and_desc`), so there is a single source of truth for tool
schemas — no hand-written description drift.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

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
        "relaxation", description='"static" | "relaxation" | "band" | "dos"')
    cell_relax: str = Field(
        "none", description='"none" | "shape" | "full"')


# ── 14.3 optimize_structure ───────────────────────────────────────────────────

class OptimizeStructureInput(BaseModel):
    poscar_name: Optional[str] = Field(
        None, description="input file (auto-detects POSCAR if omitted)")
    fmax: float = Field(0.02, description="force convergence threshold [eV/Å]")
    cell_relax: str = Field("none", description='"none" | "shape" | "full"')
    optimizer: str = Field("FIRE", description='"FIRE" | "BFGS" | "LBFGS"')
    max_steps: int = Field(1000, description="maximum optimizer steps")
    calculator_type: str = Field("mace", description='"mace" | "mattersim"')
    calculator_model: Optional[str] = Field(
        None, description="override default model name")
    emit_vasp_inputs: bool = Field(
        True, description="also write INCAR + KPOINTS for VASP handoff")


# ── 14.4 run_md_simulation ────────────────────────────────────────────────────

class RunMdSimulationInput(BaseModel):
    poscar_name: Optional[str] = Field(
        None, description="input file (auto-detects CONTCAR/POSCAR if omitted)")
    ensemble: str = Field("nvt", description='"nvt" | "npt"')
    temperature: float = Field(300.0, description="target temperature [K]")
    nsw: int = Field(10000, description="total MD steps")
    timestep: float = Field(1.0, description="MD timestep [fs]")
    thermostat: str = Field(
        "langevin", description="langevin|nose-hoover (NVT) or berendsen|bussi (NPT)")
    pressure: float = Field(0.0, description="target pressure [GPa], NPT only")
    calculator_type: str = Field("mace", description='"mace" | "mattersim"')
    calculator_model: Optional[str] = Field(
        None, description="override default model name")
    log_interval: int = Field(10, description="log every N steps")
    emit_vasp_inputs: bool = Field(
        True, description="also write INCAR + KPOINTS for VASP-MD handoff")


def args_and_desc(model: type[BaseModel]) -> tuple[list[str], str]:
    """Return (arg names, human-readable arg description) from a model's fields."""
    names = list(model.model_fields.keys())
    desc = "; ".join(
        f"{name}: {field.description}"
        for name, field in model.model_fields.items()
        if field.description
    )
    return names, desc
