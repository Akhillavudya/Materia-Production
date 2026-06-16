"""Tool metadata and callable mapping for the Materia agent.

The four tools and their arg schemas are derived from the Pydantic contracts in
`app.tools.contracts` — the single source of truth — so the planner prompt and
the executor never drift from the actual tool signatures.
"""

from app.tools import material_tools
from app.tools.contracts import (
    GeneratePoscarInput,
    GenerateVaspInputsInput,
    ListFilesInput,
    ListModelsInput,
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
    ("read_file",            "Reading file",                 ReadFileInput),
    ("list_files",           "Listing session files",        ListFilesInput),
    ("list_models",          "Listing models",               ListModelsInput),
    ("optimize_structure",   "Optimizing structure",         OptimizeStructureInput),
    ("run_md_simulation",    "Running MD simulation",         RunMdSimulationInput),
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
