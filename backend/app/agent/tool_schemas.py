"""Provider-neutral tool schemas, derived from the Pydantic contracts.

Single source of truth: the four `tools/contracts.py` models define the argument
schemas, and this module turns them into `ToolSpec`s the LLM providers declare to
the model for native function calling (redesign §14/§15). No hand-written arg
descriptions, so the model never sees a schema that drifts from the real tool.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agent.providers.base import ToolSpec
from app.tools.contracts import (
    AnalyzeSymmetryInput,
    BuildStructureInput,
    GeneratePoscarInput,
    GenerateVaspInputsInput,
    ListFilesInput,
    ListModelsInput,
    OptimizeStructureInput,
    ReadFileInput,
    RunMdSimulationInput,
    SearchMaterialsInput,
)

# One-line, model-facing description of what each tool does and when to use it.
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "search_materials": (
        "Search the Materials Project, C2DB and OQMD databases for materials by "
        "formula, element(s) or property filters. Returns matching structures "
        "with ids you can pass to generate_vasp_inputs. Use this first whenever "
        "the user names a material by formula rather than by database id."
    ),
    "generate_vasp_inputs": (
        "Generate a complete VASP input set (POSCAR + INCAR + KPOINTS) for a "
        "material. Provide a material_id (and source) from a prior search, or a "
        "poscar_path for an existing session structure. Choose a `task` "
        "(static/relaxation/band/dos/aimd/elastic/phonon_dfpt/dielectric/bader/elf/"
        "workfunction) and optionally stack modifiers that apply to ANY task: "
        "`functional` (pbe/hse06/scan), `vdw`, `soc`, `hubbard_u`, `dipole`, "
        "`solvent` (vaspsol/vaspsol++, needs a patched VASP binary), and `charge` "
        "(sets NELECT). E.g. an HSE06 band structure = task=band, functional=hse06. "
        "Fast/synchronous."
    ),
    "generate_poscar": (
        "Generate ONLY a POSCAR structure file (no INCAR/KPOINTS/POTCAR). Use this "
        "when the user asks just for a POSCAR. Provide a material_id (and source) "
        "from a prior search, or a poscar_path to convert an existing session "
        "structure. Use generate_vasp_inputs instead for the full input set."
    ),
    "build_structure": (
        "Build or modify a crystal structure and save the result as the active "
        "POSCAR (so it chains into optimize/MD/VASP). Pick an `operation`: "
        "make_supercell (replicate the cell, e.g. scaling='2 2 1' or '2'); add_vacuum "
        "(add `thickness` Å of vacuum along `axis` a/b/c — for 2D layers, molecules, "
        "or padding a slab); make_slab (cut a surface along `miller` e.g. '1 1 1' with "
        "`min_slab_size`/`min_vacuum_size` Å — vacuum is INCLUDED, so do not also call "
        "add_vacuum); convert (write the structure in another format via `to_format`: "
        "poscar/cif/xyz/cssr/json). Operates on the active session structure by "
        "default, or pass poscar_path / material_id."
    ),
    "analyze_symmetry": (
        "Report a structure's symmetry: space group (symbol + number), point group, "
        "crystal system, and primitive/conventional site counts. Read-only by "
        "default; set write='primitive' or 'conventional' to also save that standard "
        "cell as the active POSCAR. Use when the user asks about space group, "
        "symmetry, or wants the primitive/conventional cell."
    ),
    "read_file": (
        "Read and parse a file the user uploaded into this session. Structure "
        "files (POSCAR/CONTCAR/CIF/XYZ) are parsed and made the active structure "
        "so you can then optimize, run MD, or generate VASP inputs from them; "
        "text/config files (INCAR/KPOINTS/CSV/JSON) are returned as a preview. "
        "Call this first when the user refers to 'this'/'the uploaded' file. Omit "
        "filename to read the most recent upload."
    ),
    "list_files": (
        "List all files in the current session (name, type, upload time, short "
        "description). Use when the user asks what files or structures are "
        "available."
    ),
    "list_models": (
        "List the available machine-learned potential models (MACE and MatterSim) "
        "and their variants, including which is the default. Use when the user "
        "asks what models they can use, or to validate a requested model."
    ),
    "optimize_structure": (
        "Run an ASE geometry optimization (relaxation) on a structure already in "
        "the session, using a machine-learned potential (MACE/MatterSim). This is "
        "long-running: it returns a job_id immediately and runs in the background."
    ),
    "run_md_simulation": (
        "Run an ASE molecular-dynamics simulation (NVT/NPT) on a session "
        "structure using a machine-learned potential. Long-running: returns a "
        "job_id immediately and runs in the background."
    ),
}

# (tool name, contract model)
_TOOL_MODELS: list[tuple[str, type[BaseModel]]] = [
    ("search_materials", SearchMaterialsInput),
    ("generate_vasp_inputs", GenerateVaspInputsInput),
    ("generate_poscar", GeneratePoscarInput),
    ("build_structure", BuildStructureInput),
    ("analyze_symmetry", AnalyzeSymmetryInput),
    ("read_file", ReadFileInput),
    ("list_files", ListFilesInput),
    ("list_models", ListModelsInput),
    ("optimize_structure", OptimizeStructureInput),
    ("run_md_simulation", RunMdSimulationInput),
]


def _clean_schema(node: Any) -> Any:
    """Normalise Pydantic JSON schema for broad provider compatibility.

    - drops `title`/`default` (cosmetic, and some providers reject them)
    - flattens Optional `anyOf: [T, null]` to `T` + `nullable: true`
    - recurses through `properties` and `items`
    """
    if not isinstance(node, dict):
        return node

    node = {k: v for k, v in node.items() if k not in ("title", "default")}

    if "anyOf" in node:
        variants = node.pop("anyOf")
        non_null = [v for v in variants if v.get("type") != "null"]
        has_null = any(v.get("type") == "null" for v in variants)
        if len(non_null) == 1:
            merged = _clean_schema(non_null[0])
            for k, v in node.items():
                merged.setdefault(k, v)
            if has_null:
                merged["nullable"] = True
            node = merged
        else:
            node["anyOf"] = [_clean_schema(v) for v in non_null]
            if has_null:
                node["nullable"] = True

    if isinstance(node.get("properties"), dict):
        node["properties"] = {
            k: _clean_schema(v) for k, v in node["properties"].items()
        }
    if isinstance(node.get("items"), dict):
        node["items"] = _clean_schema(node["items"])

    return node


def build_tool_specs() -> list[ToolSpec]:
    """Return the four agent tools as provider-neutral `ToolSpec`s."""
    specs: list[ToolSpec] = []
    for name, model in _TOOL_MODELS:
        schema = _clean_schema(model.model_json_schema())
        schema.setdefault("type", "object")
        specs.append(ToolSpec(
            name=name,
            description=_TOOL_DESCRIPTIONS[name],
            parameters=schema,
        ))
    return specs


TOOL_SPECS: list[ToolSpec] = build_tool_specs()
TOOL_NAMES: set[str] = {s.name for s in TOOL_SPECS}
