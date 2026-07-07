"""Tool metadata and callable mapping for the Materia agent.

The four tools and their arg schemas are derived from the Pydantic contracts in
`app.tools.contracts` — the single source of truth — so the planner prompt and
the executor never drift from the actual tool signatures.
"""

from app.tools import material_tools
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
    ListModelsInput,
    ListSublatticesInput,
    MakeSlabInput,
    MakeSupercellInput,
    OptimizeStructureInput,
    ReadFileInput,
    RunMdSimulationInput,
    SearchMaterialsInput,
    args_and_desc,
)

# (fn_name, label, input contract)
_TOOL_SPECS = [
    ("search_materials",     "Searching material databases", SearchMaterialsInput),
    ("generate_vasp_inputs", "Generating VASP inputs",       GenerateVaspInputsInput),
    ("generate_poscar",      "Generating POSCAR",            GeneratePoscarInput),
    ("generate_kpoints",     "Generating KPOINTS",           GenerateKpointsInput),
    ("make_supercell",       "Building supercell",           MakeSupercellInput),
    ("add_vacuum",           "Adding vacuum",                AddVacuumInput),
    ("make_slab",            "Building surface slab",        MakeSlabInput),
    ("add_adsorbate",        "Adsorbing molecule on surface", AddAdsorbateInput),
    ("convert_structure",    "Converting structure format",  ConvertStructureInput),
    ("analyze_symmetry",     "Analyzing symmetry",           AnalyzeSymmetryInput),
    ("create_vacancy",       "Creating vacancy defect",      CreateVacancyInput),
    ("create_substitution",  "Creating substitution defect", CreateSubstitutionInput),
    ("create_interstitial",  "Creating interstitial defect", CreateInterstitialInput),
    ("read_file",            "Reading file",                 ReadFileInput),
    ("list_files",           "Listing session files",        ListFilesInput),
    ("list_models",          "Listing models",               ListModelsInput),
    ("optimize_structure",   "Optimizing structure",         OptimizeStructureInput),
    ("run_md_simulation",    "Running MD simulation",         RunMdSimulationInput),
    ("compute_elastic_tensor", "Computing elastic properties", ComputeElasticInput),
    ("compute_phonons",       "Computing phonons",            ComputePhononInput),
    ("list_sublattices",      "Listing sublattices",          ListSublatticesInput),
    ("generate_sqs",          "Generating SQS (ATAT mcsqs)",  GenerateSqsInput),
    ("compute_neb",           "Computing NEB pathway",        ComputeNebInput),
]


TOOL_REGISTRY = []
for _fn_name, _label, _model in _TOOL_SPECS:
    _args, _arg_desc = args_and_desc(_model)
    TOOL_REGISTRY.append({
        "fn_name":  _fn_name,
        "label":    _label,
        "args":     _args,
        "arg_desc": _arg_desc,
    })


TOOL_MAP = {tool["fn_name"]: tool for tool in TOOL_REGISTRY}

CALLABLE_TOOL_MAP = {
    tool["fn_name"]: getattr(material_tools, tool["fn_name"])
    for tool in TOOL_REGISTRY
    if hasattr(material_tools, tool["fn_name"])
}
