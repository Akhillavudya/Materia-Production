"""Tool metadata and callable mapping for the Materia agent."""

from app.tools import material_tools


TOOL_REGISTRY = [
    {
        "fn_name":  "list_files",
        "label":    "Listing session files",
        "args":     [],
        "arg_desc": "No arguments. Lists uploaded and generated files in the current session.",
    },
    {
        "fn_name":  "read_file",
        "label":    "Reading file",
        "args":     ["name"],
        "arg_desc": 'name: file name/path in the session, or "auto" for the latest file.',
    },
    {
        "fn_name":  "rename_file",
        "label":    "Renaming file",
        "args":     ["name", "new_name"],
        "arg_desc": "name: existing session file, new_name: replacement file name.",
    },
    {
        "fn_name":  "search_material",
        "label":    "Searching material databases",
        "args":     ["formula", "element", "elements", "max_gap", "min_gap", "max_formation_e", "limit"],
        "arg_desc": (
            'formula: optional formula e.g. "NaCl" or "MoS2"; '
            'element: optional single element e.g. "Mo"; '
            'elements: optional comma-separated elements e.g. "Mo,S"; '
            "max_gap/min_gap: optional band-gap bounds in eV; "
            "max_formation_e: optional max formation energy in eV/atom; "
            "limit: optional result limit."
        ),
    },
    {
        "fn_name":  "generate_poscar",
        "label":    "Generating POSCAR",
        "args":     ["material_id", "source", "name"],
        "arg_desc": (
            "material_id: id returned by search_material; "
            'source: "mp", "c2db", "oqmd", or auto-detected from id; '
            "name: optional POSCAR label."
        ),
    },
    {
        "fn_name":  "generate_vasp_poscar",
        "label":    "POSCAR from Materials Project",
        "args":     ["material_id", "source", "name"],
        "arg_desc": "Alias for generate_poscar (material_id, source, name).",
    },
    {
        "fn_name":  "customize_vasp_kpoints_with_accuracy",
        "label":    "Generating KPOINTS",
        "args":     ["poscar_path", "density", "is_md"],
        "arg_desc": "poscar_path: session file or 'auto', density: k-point density, is_md: use Gamma-only.",
    },
    {
        "fn_name":  "generate_vasp_inputs_from_poscar",
        "label":    "VASP inputs (full set)",
        "args":     ["poscar_path", "task", "cell_relax"],
        "arg_desc": "Generate INCAR and KPOINTS from a POSCAR and save them in session.",
    },
    {
        "fn_name":  "optimize_structure",
        "label":    "Optimizing structure",
        "args":     ["poscar_name", "fmax", "cell_relax", "optimizer", "max_steps", "calculator_type", "calculator_model", "generate_vasp_inputs"],
        "arg_desc": (
            "poscar_name: input file (auto-detected if omitted); "
            "fmax: force threshold [eV/Å] default 0.02; "
            "cell_relax: none|shape|full; "
            "optimizer: FIRE|BFGS|LBFGS; "
            "max_steps: max optimizer steps; "
            "calculator_type: mace|mattersim; "
            "calculator_model: override default model."
        ),
    },
    {
        "fn_name":  "list_available_calculators",
        "label":    "Listing available MLP models",
        "args":     [],
        "arg_desc": "No arguments. Lists locally available MACE and MatterSim models.",
    },
    {
        "fn_name":  "run_md_simulation",
        "label":    "Running MD simulation",
        "args":     ["poscar_name", "ensemble", "temperature", "nsw", "timestep", "thermostat", "pressure", "calculator_type", "calculator_model", "log_interval", "generate_vasp_inputs"],
        "arg_desc": (
            "poscar_name: input file (auto-detects CONTCAR/POSCAR); "
            "ensemble: nvt|npt; "
            "temperature: target [K]; "
            "nsw: total MD steps; "
            "timestep: [fs]; "
            "thermostat: langevin|nose-hoover (NVT) or berendsen|bussi (NPT); "
            "pressure: [GPa] NPT only; "
            "calculator_type: mace|mattersim."
        ),
    },
]


TOOL_MAP = {tool["fn_name"]: tool for tool in TOOL_REGISTRY}

CALLABLE_TOOL_MAP = {
    tool["fn_name"]: getattr(material_tools, tool["fn_name"])
    for tool in TOOL_REGISTRY
    if hasattr(material_tools, tool["fn_name"])
}
