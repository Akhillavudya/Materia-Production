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
    AddAdsorbateInput,
    AddVacuumInput,
    AnalyzeSymmetryInput,
    ComputeElasticInput,
    ComputeNebInput,
    ComputePhononInput,
    ConvertStructureInput,
    CreateInterstitialInput,
    CreateSubstitutionInput,
    CreateVacancyInput,
    GenerateKpointsInput,
    GeneratePoscarInput,
    GenerateSqsInput,
    GenerateVaspInputsInput,
    ListFilesInput,
    ListMigrationPathsInput,
    ListModelsInput,
    MakeSlabInput,
    MakeSupercellInput,
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
    "generate_kpoints": (
        "Write ONLY a VASP KPOINTS file at a chosen accuracy level. `accuracy_level` "
        "sets the k-points-per-atom density: 'Low' (1000), 'Medium' (3000, default), "
        "'High' (5000), or 'Custom' (then set `custom_kppa`). `gamma_centered=true` "
        "(default) writes a Γ-centered mesh, false writes Monkhorst-Pack. Operates on "
        "the active POSCAR by default, or pass poscar_path / material_id. Use "
        "generate_vasp_inputs instead for the full POSCAR+INCAR+KPOINTS+POTCAR set."
    ),
    "make_supercell": (
        "Replicate a crystal cell into a supercell and save it as the active POSCAR "
        "(so it chains into optimize/MD/VASP). `scaling` accepts a uniform factor "
        "('2' → 2x2x2), per-axis factors ('2 2 1'), or 9 numbers for a full 3x3 "
        "transformation matrix ('2 0 0 0 2 0 0 0 1', for rotated/non-diagonal cells "
        "like a sqrt3 x sqrt3). Operates on the active session structure by default, "
        "or pass poscar_path / material_id."
    ),
    "add_vacuum": (
        "Set the vacuum gap along `axis` (a/b/c) to EXACTLY `thickness` Å and save "
        "the result as the active POSCAR — for 2D layers, molecules, or padding a "
        "structure. `side` controls placement: 'both' (centred, default), 'top' (all "
        "vacuum above the slab), or 'bottom'. The gap matches `thickness` regardless "
        "of existing padding. Do NOT use on a make_slab result (slabs already include "
        "vacuum). Operates on the active session structure by default, or pass "
        "poscar_path / material_id."
    ),
    "make_slab": (
        "Cut a surface slab along `miller` (e.g. '1 1 1'), saved as the active POSCAR. "
        "Set `layers` for an EXACT atomic-layer count (what the user means by 'N "
        "layers'); otherwise the slab is `min_slab_size` Å thick. Vacuum "
        "(`min_vacuum_size` Å) is INCLUDED, so do not also call add_vacuum. `shift` "
        "selects the surface termination. For an in-plane supercell, call make_supercell "
        "afterwards (e.g. '2 2 1'); to change the vacuum precisely use add_vacuum. So 'a "
        "2x2 Cu(100) slab, 4 layers' = make_slab(miller='1 0 0', layers=4) → "
        "make_supercell('2 2 1'). Operates on the active session structure by default, "
        "or pass poscar_path / material_id."
    ),
    "add_adsorbate": (
        "Adsorb a molecule (e.g. CO2, CO, H2O, O, H) onto the active surface slab. By "
        "default it places the molecule geometrically on an auto-picked site (first "
        "symmetry-reduced `site_type`, 'ontop' by default) at `distance` Å above the "
        "surface and saves it as the active POSCAR (fast). Set `relax=true` for an "
        "accurate AdsorbML-style background job that enumerates placements, relaxes them "
        "with an ML potential, and returns the lowest adsorption-energy structure (returns "
        "a job_id). The active structure should be a slab first (make_slab)."
    ),
    "convert_structure": (
        "Write a structure in another file format (`to_format`: poscar/cif/xyz/cssr/"
        "json). Does NOT change the active POSCAR. Operates on the active session "
        "structure by default, or pass poscar_path / material_id."
    ),
    "analyze_symmetry": (
        "Report a structure's symmetry: space group (symbol + number), point group, "
        "crystal system, and primitive/conventional site counts. Read-only by "
        "default; set write='primitive' or 'conventional' to also save that standard "
        "cell as the active POSCAR. Use when the user asks about space group, "
        "symmetry, or wants the primitive/conventional cell."
    ),
    "create_vacancy": (
        "Create a point vacancy (remove one atom) in a supercell and save it as the "
        "active POSCAR. `element` picks which species to remove; `supercell` (e.g. "
        "'2 2 2') sizes the cell, or omit it to auto-size for defect isolation. Make "
        "it charged afterwards via generate_vasp_inputs(charge=...)."
    ),
    "create_substitution": (
        "Create a substitutional defect — replace one `from_element` atom with "
        "`to_element` — in a supercell, saved as the active POSCAR. `supercell` "
        "optional (auto-sizes if omitted)."
    ),
    "create_interstitial": (
        "Insert `insert_element` at a Voronoi interstitial site in a supercell, saved "
        "as the active POSCAR. `supercell` optional (auto-sizes if omitted)."
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
    "compute_elastic_tensor": (
        "Compute the elastic tensor and derived moduli (bulk/shear/Young's, "
        "Poisson ratio) of a session structure with a machine-learned potential. "
        "Long-running: returns a job_id and runs in the background."
    ),
    "compute_phonons": (
        "Compute the phonon band structure / density of states of a session "
        "structure (finite-displacement via phonopy) with a machine-learned "
        "potential. Long-running: returns a job_id and runs in the background."
    ),
    "generate_sqs": (
        "Generate a Special Quasi-random Structure (SQS) for a disordered alloy "
        "using ATAT mcsqs. To turn an ORDERED structure into a disordered one, "
        "pass `substitute` (e.g. \"Se->S:0.25\" = replace 25% of Se with S) — this "
        "is the tool for requests like 'substitute 25% of Se with S using SQS'. "
        "Operates on the active/most-recent session structure. Long-running: "
        "returns a job_id and runs in the background."
    ),
    "list_migration_paths": (
        "List candidate ion migration hops (source/dest site pairs) for a given "
        "element in a session structure, so the user can pick one for compute_neb. "
        "Use this before compute_neb when the hop is not yet specified."
    ),
    "compute_neb": (
        "Run a Nudged Elastic Band (NEB) calculation of a migration barrier "
        "between two endpoints with a machine-learned potential. Provide either a "
        "final_poscar_name or source_site/dest_site labels (from "
        "list_migration_paths). Long-running: returns a job_id and runs in the "
        "background."
    ),
}

# (tool name, contract model)
_TOOL_MODELS: list[tuple[str, type[BaseModel]]] = [
    ("search_materials", SearchMaterialsInput),
    ("generate_vasp_inputs", GenerateVaspInputsInput),
    ("generate_poscar", GeneratePoscarInput),
    ("generate_kpoints", GenerateKpointsInput),
    ("make_supercell", MakeSupercellInput),
    ("add_vacuum", AddVacuumInput),
    ("make_slab", MakeSlabInput),
    ("add_adsorbate", AddAdsorbateInput),
    ("convert_structure", ConvertStructureInput),
    ("analyze_symmetry", AnalyzeSymmetryInput),
    ("create_vacancy", CreateVacancyInput),
    ("create_substitution", CreateSubstitutionInput),
    ("create_interstitial", CreateInterstitialInput),
    ("read_file", ReadFileInput),
    ("list_files", ListFilesInput),
    ("list_models", ListModelsInput),
    ("optimize_structure", OptimizeStructureInput),
    ("run_md_simulation", RunMdSimulationInput),
    ("compute_elastic_tensor", ComputeElasticInput),
    ("compute_phonons", ComputePhononInput),
    ("generate_sqs", GenerateSqsInput),
    ("list_migration_paths", ListMigrationPathsInput),
    ("compute_neb", ComputeNebInput),
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
