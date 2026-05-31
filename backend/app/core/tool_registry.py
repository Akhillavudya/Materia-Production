# # app/core/tool_registry.py

# TOOL_REGISTRY = [
#     {
#         "fn_name": "list_files",
#         "label": "Listing session files",
#         "args": [],
#         "arg_desc": "No arguments required.",
#     },
#     {
#         "fn_name": "read_file",
#         "label": "Reading file",
#         "args": ["name"],
#         "arg_desc": "name: file name/path inside current session directory.",
#     },
#     {
#         "fn_name": "rename_file",
#         "label": "Renaming file",
#         "args": ["name", "new_name"],
#         "arg_desc": "name: existing file name, new_name: new file name.",
#     },
#     {
#         "fn_name": "generate_vasp_poscar",
#         "label": "Fetching structure from Materials Project",
#         "args": ["formula"],
#         "arg_desc": 'formula: chemical formula string e.g. "NaCl"',
#     },
#     {
#         "fn_name": "generate_vasp_inputs_from_poscar",
#         "label": "Preparing VASP input files",
#         "args": ["poscar_path", "vasp_input_sets"],
#         "arg_desc": (
#             'poscar_path: path to existing POSCAR, '
#             'vasp_input_sets: one of "MPRelaxSet", "MPStaticSet", '
#             '"MPMetalRelaxSet", "MPNonSCFSet", "MPMDSet"'
#         ),
#     },
#     {
#         "fn_name": "generate_vasp_inputs_hpc_slurm_script",
#         "label": "Generating SLURM script",
#         "args": ["job_name"],
#         "arg_desc": "job_name: name for the HPC job.",
#     },
#     {
#         "fn_name": "customize_vasp_kpoints_with_accuracy",
#         "label": "Generating KPOINTS",
#         "args": ["poscar_path", "accuracy_level"],
#         "arg_desc": (
#             'poscar_path: path to POSCAR, '
#             'accuracy_level: one of "Low", "Medium", "High"'
#         ),
#     },
#     {
#         "fn_name": "convert_structure_format",
#         "label": "Converting structure format",
#         "args": ["input_file", "output_format"],
#         "arg_desc": "input_file: structure file path, output_format: target format.",
#     },
#     {
#         "fn_name": "convert_poscar_coordinates",
#         "label": "Converting POSCAR coordinates",
#         "args": ["poscar_path", "coordinate_type"],
#         "arg_desc": 'poscar_path: path to POSCAR, coordinate_type: "Direct" or "Cartesian".',
#     },
#     {
#         "fn_name": "generate_vasp_poscar_with_vacancy_defects",
#         "label": "Generating vacancy defects",
#         "args": ["poscar_path", "original_element", "defect_amount"],
#         "arg_desc": (
#             'poscar_path: path to POSCAR, '
#             'original_element: element symbol e.g. "Na", '
#             "defect_amount: integer >= 1"
#         ),
#     },
#     {
#         "fn_name": "generate_vasp_poscar_with_substitution_defects",
#         "label": "Generating substitution defects",
#         "args": ["poscar_path", "original_element", "defect_element", "defect_amount"],
#         "arg_desc": (
#             'poscar_path: path to POSCAR, '
#             'original_element: element to replace e.g. "Na", '
#             'defect_element: replacement element e.g. "K", '
#             "defect_amount: integer >= 1"
#         ),
#     },
#     {
#         "fn_name": "generate_vasp_poscar_with_interstitial_defects",
#         "label": "Generating interstitial defects",
#         "args": ["poscar_path", "defect_element", "defect_amount"],
#         "arg_desc": (
#             "poscar_path: path to POSCAR, "
#             "defect_element: inserted element symbol, "
#             "defect_amount: integer >= 1"
#         ),
#     },
#     {
#         "fn_name": "generate_supercell_from_poscar",
#         "label": "Generating supercell",
#         "args": ["poscar_path", "scaling_matrix"],
#         "arg_desc": (
#             'poscar_path: path to existing POSCAR, '
#             'scaling_matrix: string like "2 0 0; 0 2 0; 0 0 2"'
#         ),
#     },
#     {
#         "fn_name": "generate_sqs_from_poscar",
#         "label": "Generating SQS structure",
#         "args": ["poscar_path"],
#         "arg_desc": "poscar_path: path to existing POSCAR.",
#     },
#     {
#         "fn_name": "generate_surface_slab_from_poscar",
#         "label": "Generating surface slab",
#         "args": ["poscar_path", "miller_indices"],
#         "arg_desc": (
#             "poscar_path: path to POSCAR, "
#             "miller_indices: list of 3 integers e.g. [1, 0, 0]"
#         ),
#     },
#     {
#         "fn_name": "generate_interface_from_poscars",
#         "label": "Generating interface structure",
#         "args": ["film_poscar_path", "substrate_poscar_path"],
#         "arg_desc": "film_poscar_path and substrate_poscar_path: paths to POSCAR files.",
#     },
#     {
#         "fn_name": "visualize_structure_from_poscar",
#         "label": "Visualizing structure",
#         "args": ["poscar_path"],
#         "arg_desc": "poscar_path: path to POSCAR file.",
#     },
#     {
#         "fn_name": "generate_vasp_workflow_of_convergence_tests",
#         "label": "Generating VASP convergence workflow",
#         "args": ["poscar_path"],
#         "arg_desc": "poscar_path: path to POSCAR file.",
#     },
#     {
#         "fn_name": "generate_vasp_workflow_of_eos",
#         "label": "Generating EOS workflow",
#         "args": ["poscar_path"],
#         "arg_desc": "poscar_path: path to POSCAR file.",
#     },
#     {
#         "fn_name": "generate_vasp_workflow_of_elastic_constants",
#         "label": "Generating elastic constants workflow",
#         "args": ["poscar_path"],
#         "arg_desc": "poscar_path: path to POSCAR file.",
#     },
#     {
#         "fn_name": "generate_vasp_workflow_of_aimd",
#         "label": "Generating AIMD workflow",
#         "args": ["poscar_path"],
#         "arg_desc": "poscar_path: path to POSCAR file.",
#     },
#     {
#         "fn_name": "generate_vasp_workflow_of_neb",
#         "label": "Generating NEB workflow",
#         "args": ["initial_poscar_path", "final_poscar_path"],
#         "arg_desc": "initial_poscar_path and final_poscar_path: paths to POSCAR files.",
#     },
#     {
#         "fn_name": "analyze_vasp_workflow_of_convergence_tests",
#         "label": "Analyzing convergence workflow",
#         "args": [],
#         "arg_desc": "Analyzes convergence workflow outputs in current session directory.",
#     },
#     {
#         "fn_name": "analyze_vasp_workflow_of_eos",
#         "label": "Analyzing EOS workflow",
#         "args": [],
#         "arg_desc": "Analyzes EOS workflow outputs in current session directory.",
#     },
#     {
#         "fn_name": "analyze_vasp_workflow_of_elastic_constants",
#         "label": "Analyzing elastic constants workflow",
#         "args": [],
#         "arg_desc": "Analyzes elastic constants workflow outputs in current session directory.",
#     },
#     {
#         "fn_name": "analyze_vasp_workflow_of_aimd",
#         "label": "Analyzing AIMD workflow",
#         "args": [],
#         "arg_desc": "Analyzes AIMD workflow outputs in current session directory.",
#     },
#     {
#         "fn_name": "analyze_vasp_workflow_of_neb",
#         "label": "Analyzing NEB workflow",
#         "args": [],
#         "arg_desc": "Analyzes NEB workflow outputs in current session directory.",
#     },
#     {
#         "fn_name": "run_simulation_using_mlps",
#         "label": "Running MLP simulation",
#         "args": ["poscar_path", "mlp_type", "task_type"],
#         "arg_desc": (
#             "poscar_path: path to POSCAR, "
#             'mlp_type: e.g. "CHGNet", "M3GNet", "MatterSim", '
#             'task_type: e.g. "single", "relax"'
#         ),
#     },
#     # add these at the TOP of TOOL_REGISTRY list

#     {
#         "fn_name":  "list_files",
#         "label":    "Listing session files",
#         "args":     [],
#         "arg_desc": 'args: {}  — no arguments, lists all files in session',
#     },
#     {
#         "fn_name":  "read_file",
#         "label":    "Reading file",
#         "args":     ["name"],
#         "arg_desc": 'args: {"name": "filename.csv"}  — filename only, not full path',
#     },
# ]

# TOOL_MAP = {tool["fn_name"]: tool for tool in TOOL_REGISTRY}

# from app.tools import tools as tools

# CALLABLE_TOOL_MAP = {
#     name: getattr(tools, name)
#     for name in [tool["fn_name"] for tool in TOOL_REGISTRY]
#     if hasattr(tools, name)
# }


# app/core/tool_registry.py
# Complete registry — existing Materia tools + C2DB tools merged together.
# TOOL_MAP is what the agent uses to look up metadata and callable functions.

TOOL_REGISTRY = [

    # ── file utilities ─────────────────────────────────────────────────────────
    {
        "fn_name":  "list_files",
        "label":    "Listing session files",
        "args":     [],
        "arg_desc": 'args: {} — no arguments, lists all files in session',
    },
    {
        "fn_name":  "read_file",
        "label":    "Reading file",
        "args":     ["name"],
        "arg_desc": 'args: {"name": "filename.csv"} — filename only, not full path',
    },
    {
        "fn_name":  "rename_file",
        "label":    "Renaming file",
        "args":     ["name", "new_name"],
        "arg_desc": "name: existing file name, new_name: new file name.",
    },

    # ── POSCAR generation (Materials Project) ─────────────────────────────────
    {
        "fn_name":  "generate_vasp_poscar",
        "label":    "Fetching structure from Materials Project",
        "args":     ["formula"],
        "arg_desc": 'formula: chemical formula string e.g. "NaCl"',
    },

    # ── VASP input files ──────────────────────────────────────────────────────
    {
        "fn_name":  "generate_vasp_inputs_from_poscar",
        "label":    "Preparing VASP input files",
        "args":     ["poscar_path", "vasp_input_sets"],
        "arg_desc": (
            'poscar_path: path to existing POSCAR, '
            'vasp_input_sets: one of "MPRelaxSet", "MPStaticSet", '
            '"MPMetalRelaxSet", "MPNonSCFSet", "MPMDSet"'
        ),
    },
    {
        "fn_name":  "generate_vasp_inputs_hpc_slurm_script",
        "label":    "Generating SLURM script",
        "args":     ["job_name"],
        "arg_desc": "job_name: name for the HPC job.",
    },
    {
        "fn_name":  "customize_vasp_kpoints_with_accuracy",
        "label":    "Generating KPOINTS",
        "args":     ["poscar_path", "accuracy_level"],
        "arg_desc": 'poscar_path: path to POSCAR, accuracy_level: "Low", "Medium", or "High"',
    },

    # ── structure manipulation ────────────────────────────────────────────────
    {
        "fn_name":  "convert_structure_format",
        "label":    "Converting structure format",
        "args":     ["input_file", "output_format"],
        "arg_desc": "input_file: structure file path, output_format: target format.",
    },
    {
        "fn_name":  "convert_poscar_coordinates",
        "label":    "Converting POSCAR coordinates",
        "args":     ["poscar_path", "coordinate_type"],
        "arg_desc": 'poscar_path: path to POSCAR, coordinate_type: "Direct" or "Cartesian".',
    },
    {
        "fn_name":  "generate_vasp_poscar_with_vacancy_defects",
        "label":    "Generating vacancy defects",
        "args":     ["poscar_path", "original_element", "defect_amount"],
        "arg_desc": 'poscar_path: path to POSCAR, original_element: e.g. "Na", defect_amount: integer >= 1',
    },
    {
        "fn_name":  "generate_vasp_poscar_with_substitution_defects",
        "label":    "Generating substitution defects",
        "args":     ["poscar_path", "original_element", "defect_element", "defect_amount"],
        "arg_desc": 'poscar_path: path to POSCAR, original_element: "Na", defect_element: "K", defect_amount: integer >= 1',
    },
    {
        "fn_name":  "generate_vasp_poscar_with_interstitial_defects",
        "label":    "Generating interstitial defects",
        "args":     ["poscar_path", "defect_element", "defect_amount"],
        "arg_desc": "poscar_path: path to POSCAR, defect_element: inserted element, defect_amount: integer >= 1",
    },
    {
        "fn_name":  "generate_supercell_from_poscar",
        "label":    "Generating supercell",
        "args":     ["poscar_path", "scaling_matrix"],
        "arg_desc": 'poscar_path: path to POSCAR, scaling_matrix: string like "2 0 0; 0 2 0; 0 0 2"',
    },
    {
        "fn_name":  "generate_sqs_from_poscar",
        "label":    "Generating SQS structure",
        "args":     ["poscar_path"],
        "arg_desc": "poscar_path: path to existing POSCAR.",
    },
    {
        "fn_name":  "generate_surface_slab_from_poscar",
        "label":    "Generating surface slab",
        "args":     ["poscar_path", "miller_indices"],
        "arg_desc": "poscar_path: path to POSCAR, miller_indices: list of 3 integers e.g. [1, 0, 0]",
    },
    {
        "fn_name":  "generate_interface_from_poscars",
        "label":    "Generating interface structure",
        "args":     ["film_poscar_path", "substrate_poscar_path"],
        "arg_desc": "film_poscar_path and substrate_poscar_path: paths to POSCAR files.",
    },
    {
        "fn_name":  "visualize_structure_from_poscar",
        "label":    "Visualizing structure",
        "args":     ["poscar_path"],
        "arg_desc": "poscar_path: path to POSCAR file.",
    },

    # ── VASP workflows ────────────────────────────────────────────────────────
    {
        "fn_name":  "generate_vasp_workflow_of_convergence_tests",
        "label":    "Generating VASP convergence workflow",
        "args":     ["poscar_path"],
        "arg_desc": "poscar_path: path to POSCAR file.",
    },
    {
        "fn_name":  "generate_vasp_workflow_of_eos",
        "label":    "Generating EOS workflow",
        "args":     ["poscar_path"],
        "arg_desc": "poscar_path: path to POSCAR file.",
    },
    {
        "fn_name":  "generate_vasp_workflow_of_elastic_constants",
        "label":    "Generating elastic constants workflow",
        "args":     ["poscar_path"],
        "arg_desc": "poscar_path: path to POSCAR file.",
    },
    {
        "fn_name":  "generate_vasp_workflow_of_aimd",
        "label":    "Generating AIMD workflow",
        "args":     ["poscar_path"],
        "arg_desc": "poscar_path: path to POSCAR file.",
    },
    {
        "fn_name":  "generate_vasp_workflow_of_neb",
        "label":    "Generating NEB workflow",
        "args":     ["initial_poscar_path", "final_poscar_path"],
        "arg_desc": "initial_poscar_path and final_poscar_path: paths to POSCAR files.",
    },

    # ── VASP analysis ─────────────────────────────────────────────────────────
    {
        "fn_name":  "analyze_vasp_workflow_of_convergence_tests",
        "label":    "Analyzing convergence workflow",
        "args":     [],
        "arg_desc": "Analyzes convergence workflow outputs in current session directory.",
    },
    {
        "fn_name":  "analyze_vasp_workflow_of_eos",
        "label":    "Analyzing EOS workflow",
        "args":     [],
        "arg_desc": "Analyzes EOS workflow outputs in current session directory.",
    },
    {
        "fn_name":  "analyze_vasp_workflow_of_elastic_constants",
        "label":    "Analyzing elastic constants workflow",
        "args":     [],
        "arg_desc": "Analyzes elastic constants workflow outputs in current session directory.",
    },
    {
        "fn_name":  "analyze_vasp_workflow_of_aimd",
        "label":    "Analyzing AIMD workflow",
        "args":     [],
        "arg_desc": "Analyzes AIMD workflow outputs in current session directory.",
    },
    {
        "fn_name":  "analyze_vasp_workflow_of_neb",
        "label":    "Analyzing NEB workflow",
        "args":     [],
        "arg_desc": "Analyzes NEB workflow outputs in current session directory.",
    },

    # ── MLP simulations ───────────────────────────────────────────────────────
    {
        "fn_name":  "run_simulation_using_mlps",
        "label":    "Running MLP simulation",
        "args":     ["poscar_path", "mlp_type", "task_type"],
        "arg_desc": 'poscar_path: POSCAR, mlp_type: "CHGNet"/"M3GNet"/"MatterSim", task_type: "single"/"relax"',
    },

    # ── C2DB tools ────────────────────────────────────────────────────────────
    # These are for 2D materials from the Computational 2D Materials Database.
    # Use instead of generate_vasp_poscar when user mentions 2D materials,
    # monolayers, TMDs, MXenes, or explicitly says "from C2DB".
    {
        "fn_name":  "search_c2db_material",
        "label":    "Searching C2DB for 2D materials",
        "args":     ["formula"],
        "arg_desc": (
            'formula: chemical formula e.g. "MoS2", '
            'elements: list e.g. ["Mo","S"], '
            'bandgap_min/max: eV range, '
            'magnetic_state: "NM"/"FM"/"AFM", '
            'dynamically_stable: true/false, '
            'max_results: integer default 20'
        ),
    },
    {
        "fn_name":  "generate_poscar_from_c2db",
        "label":    "Generating POSCAR from C2DB",
        "args":     ["formula"],
        "arg_desc": (
            'formula: chemical formula e.g. "MoS2", '
            'c2db_id: UID from search results, '
            'db_id: integer row id from search results, '
            'cif_path: direct CIF file path'
        ),
    },
    {
        "fn_name":  "relax_c2db_structure_with_mace",
        "label":    "Relaxing structure with MACE",
        "args":     ["poscar_path"],
        "arg_desc": (
            'poscar_path: POSCAR path (defaults to session POSCAR), '
            'model_path: MACE model file or "mace-mp-0", '
            'fmax: force threshold eV/Å default 0.02, '
            'steps: max steps default 500, '
            'device: "cuda"/"cpu"/null'
        ),
    },
    {
        "fn_name":  "run_c2db_bayesian_optimization",
        "label":    "Running Bayesian Optimization over C2DB",
        "args":     ["objective"],
        "arg_desc": (
            'objective: "maximize_bandgap"/"minimize_energy"/"minimize_formation"/"maximize_stability", '
            'formula/elements: optional search filters, '
            'initial_samples: default 5, '
            'max_iterations: default 10, '
            'acquisition_function: "EI"/"UCB", '
            'mace_model_path: MACE model or "mace-mp-0"'
        ),
    },
]

# ── TOOL_MAP: fn_name → metadata dict ─────────────────────────────────────────
# Used by the agent planner and tool_executor.
# Later entries with the same fn_name overwrite earlier ones — no duplicates.
TOOL_MAP = {tool["fn_name"]: tool for tool in TOOL_REGISTRY}


# ── CALLABLE_TOOL_MAP: fn_name → actual callable function ────────────────────
# Tries to import each tool function. Missing functions are silently skipped
# (e.g. C2DB tools when C2DB is not installed).
def _build_callable_map() -> dict:
    callables = {}

    # existing Materia tools from app.tools
    try:
        from app.tools import tools as materia_tools
        for tool in TOOL_REGISTRY:
            name = tool["fn_name"]
            fn   = getattr(materia_tools, name, None)
            if fn:
                callables[name] = fn
    except ImportError:
        pass

    # C2DB tools
    try:
        from app.c2db.c2db_tools import (
            search_c2db_material,
            generate_poscar_from_c2db,
            relax_c2db_structure_with_mace,
        )
        callables["search_c2db_material"]          = search_c2db_material
        callables["generate_poscar_from_c2db"]     = generate_poscar_from_c2db
        callables["relax_c2db_structure_with_mace"] = relax_c2db_structure_with_mace
    except ImportError:
        pass

    # BO tool
    try:
        from app.c2db.bayes_opt import run_c2db_bayesian_optimization
        callables["run_c2db_bayesian_optimization"] = run_c2db_bayesian_optimization
    except ImportError:
        pass

    return callables


CALLABLE_TOOL_MAP = _build_callable_map()
