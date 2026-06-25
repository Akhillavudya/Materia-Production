"""T4 prompt benchmark — curated NL prompts with known-correct expected tools/args.

Each case drives the agent ONE turn (system prompt + optional session context +
the user prompt). We grade the FIRST tool the model decides to call — that is the
natural-language → correct-tool decision T4 measures (docs/VALIDATION_PLAN.md §5).
Nothing is executed, so no jobs are spawned.

Case fields:
  id            short stable id
  category      single | multi | compute | structure | ambiguous | out_of_scope | conceptual
  prompt        the user message
  context       optional list of prior {role, content} messages establishing an
                active session structure (so we can test compute/structure tools
                directly instead of always hitting read_file first)
  expected_tools  acceptable FIRST tool names; the sentinel "NONE" means
                  "correctly calls no tool" (clarify / refuse / answer directly)
  expected_args   optional {arg: expected} checked against the called tool's args.
                  A value may be a list of acceptable variants. Matching is
                  case-insensitive substring / numeric-equal (see harness _match).
"""

from __future__ import annotations

# Reusable session contexts (simulate a structure already loaded/active).
_ACTIVE_SI = [
    {"role": "user", "content": "I uploaded Si.cif"},
    {"role": "assistant",
     "content": "I've loaded Si.cif — it is now the active structure "
                "(an 8-atom conventional cell of silicon, Fd-3m)."},
]
_ACTIVE_TIO2 = [
    {"role": "user", "content": "I uploaded TiO2.cif"},
    {"role": "assistant",
     "content": "Loaded TiO2.cif as the active structure (rutile TiO2, 6 atoms)."},
]
_ACTIVE_GAAS = [
    {"role": "user", "content": "I uploaded GaAs.cif"},
    {"role": "assistant",
     "content": "Loaded GaAs.cif as the active structure (zinc-blende GaAs, 2 atoms)."},
]
_ACTIVE_MGSE = [
    {"role": "user", "content": "I uploaded MgSe2.cif"},
    {"role": "assistant",
     "content": "Loaded MgSe2.cif as the active structure (ordered, 12 atoms)."},
]
_ACTIVE_SLAB = [
    {"role": "user", "content": "I uploaded Cu_100_slab.vasp"},
    {"role": "assistant",
     "content": "Loaded Cu_100_slab.vasp as the active structure — a Cu(100) "
                "surface slab (4 layers, vacuum included)."},
]
_ACTIVE_NEB = [
    {"role": "user", "content": "I uploaded init.vasp and final.vasp"},
    {"role": "assistant",
     "content": "Loaded both endpoints into the session: init.vasp (initial state) "
                "and final.vasp (final state) for a migration path."},
]


SUITE: list[dict] = [
    # ── single-tool: search / generate / kpoints / list / symmetry / convert ──
    {"id": "S1", "category": "single",
     "prompt": "Find materials with the formula NaCl.",
     "expected_tools": ["search_materials"],
     "expected_args": {"formula": "NaCl"}},
    {"id": "S2", "category": "single",
     "prompt": "Search for materials containing both titanium and oxygen.",
     "expected_tools": ["search_materials"]},
    {"id": "S3", "category": "single",
     "prompt": "Find semiconductors with a band gap between 1 and 2 eV.",
     "expected_tools": ["search_materials"],
     "expected_args": {"min_gap": 1, "max_gap": 2}},
    {"id": "S4", "category": "single",
     "prompt": "Generate a full VASP input set for mp-149.",
     "expected_tools": ["generate_vasp_inputs"],
     "expected_args": {"material_id": "mp-149"}},
    {"id": "S5", "category": "single",
     "prompt": "Give me just a POSCAR for mp-2534.",
     "expected_tools": ["generate_poscar"],
     "expected_args": {"material_id": "mp-2534"}},
    {"id": "S6", "category": "single",
     "prompt": "Write a high-accuracy KPOINTS file for the current structure.",
     "context": _ACTIVE_SI,
     "expected_tools": ["generate_kpoints"],
     "expected_args": {"accuracy_level": "High"}},
    {"id": "S7", "category": "single",
     "prompt": "What machine-learning potential models can I use?",
     "expected_tools": ["list_models"]},
    {"id": "S8", "category": "single",
     "prompt": "What files do I have in this session?",
     "expected_tools": ["list_files"]},
    {"id": "S9", "category": "single",
     "prompt": "What is the space group of my current structure?",
     "context": _ACTIVE_SI,
     "expected_tools": ["analyze_symmetry"]},
    {"id": "S10", "category": "single",
     "prompt": "Convert my structure to CIF format.",
     "context": _ACTIVE_SI,
     "expected_tools": ["convert_structure"],
     "expected_args": {"to_format": ["cif", "CIF"]}},

    # ── structure-editing tools (active structure in context) ────────────────
    {"id": "S11", "category": "structure",
     "prompt": "Make a 2x2x2 supercell of my structure.",
     "context": _ACTIVE_SI,
     "expected_tools": ["make_supercell"],
     "expected_args": {"scaling": ["2 2 2", "2"]}},
    {"id": "S12", "category": "structure",
     "prompt": "Add 15 angstroms of vacuum along the c axis.",
     "context": _ACTIVE_SI,
     "expected_tools": ["add_vacuum"],
     "expected_args": {"axis": "c", "thickness": 15}},
    {"id": "S13", "category": "structure",
     "prompt": "Cut a (111) surface slab with exactly 6 atomic layers.",
     "context": _ACTIVE_SI,
     "expected_tools": ["make_slab"],
     "expected_args": {"miller": ["1 1 1", "111"], "layers": 6}},
    {"id": "S14", "category": "structure",
     "prompt": "Place a CO2 molecule on top of the slab.",
     "context": _ACTIVE_SLAB,
     "expected_tools": ["add_adsorbate"],
     "expected_args": {"molecule": ["CO2", "co2"]}},
    {"id": "S15", "category": "structure",
     "prompt": "Create an oxygen vacancy in my structure.",
     "context": _ACTIVE_TIO2,
     "expected_tools": ["create_vacancy"],
     "expected_args": {"element": "O"}},
    {"id": "S16", "category": "structure",
     "prompt": "Substitute one Ga atom with Al in my structure.",
     "context": _ACTIVE_GAAS,
     "expected_tools": ["create_substitution"],
     "expected_args": {"from_element": "Ga", "to_element": "Al"}},
    {"id": "S17", "category": "structure",
     "prompt": "Add a hydrogen interstitial to my structure.",
     "context": _ACTIVE_SI,
     "expected_tools": ["create_interstitial"],
     "expected_args": {"insert_element": "H"}},

    # ── compute jobs (active structure in context) ───────────────────────────
    {"id": "S18", "category": "compute",
     "prompt": "Relax my structure with MACE.",
     "context": _ACTIVE_SI,
     "expected_tools": ["optimize_structure"],
     "expected_args": {"calculator_type": ["mace", "MACE"]}},
    {"id": "S19", "category": "compute",
     "prompt": "Run NVT molecular dynamics at 500 K on my structure.",
     "context": _ACTIVE_SI,
     "expected_tools": ["run_md_simulation"],
     "expected_args": {"ensemble": ["nvt", "NVT"], "temperature": 500}},
    {"id": "S20", "category": "compute",
     "prompt": "Compute the elastic tensor of my structure.",
     "context": _ACTIVE_SI,
     "expected_tools": ["compute_elastic_tensor"]},
    {"id": "S21", "category": "compute",
     "prompt": "Compute the phonon band structure of my structure.",
     "context": _ACTIVE_SI,
     "expected_tools": ["compute_phonons"]},
    {"id": "S22", "category": "compute",
     "prompt": "Substitute 25% of the Se with S in my structure using SQS.",
     "context": _ACTIVE_MGSE,
     "expected_tools": ["generate_sqs"],
     "expected_args": {"substitute": ["Se->S", "Se->S:0.25"]}},
    {"id": "S23", "category": "compute",
     "prompt": "Compute the migration barrier between my initial and final structures.",
     "context": _ACTIVE_NEB,
     "expected_tools": ["compute_neb"]},

    # ── generate_vasp_inputs with task / modifier extraction ─────────────────
    {"id": "S24", "category": "single",
     "prompt": "Generate VASP inputs for an HSE06 band structure of mp-149.",
     "expected_tools": ["generate_vasp_inputs"],
     "expected_args": {"material_id": "mp-149", "task": "band",
                       "functional": ["hse06", "HSE06"]}},
    {"id": "S25", "category": "single",
     "prompt": "Set up a static SCF calculation for mp-2534.",
     "expected_tools": ["generate_vasp_inputs"],
     "expected_args": {"material_id": "mp-2534", "task": ["static", "scf"]}},

    # ── multi-tool workflows (grade the correct FIRST tool) ──────────────────
    {"id": "M1", "category": "multi",
     "prompt": "Generate a complete VASP input set for NaCl.",
     "expected_tools": ["search_materials"],
     "expected_args": {"formula": "NaCl"}},
    {"id": "M2", "category": "multi",
     "prompt": "Build a 2x2 Cu(100) slab with 4 layers and put CO2 on top.",
     "expected_tools": ["search_materials"],
     "expected_args": {"formula": ["Cu", "copper"]}},
    {"id": "M3", "category": "multi",
     "prompt": "Optimize the structure of silicon with MatterSim.",
     "expected_tools": ["search_materials"],
     "expected_args": {"formula": ["Si", "silicon"]}},
    {"id": "M4", "category": "multi",
     "prompt": "Make a POSCAR for diamond and then a 2x2x2 supercell of it.",
     "expected_tools": ["search_materials"],
     "expected_args": {"formula": ["C", "diamond"]}},

    # ── ambiguous → should ask for clarification (no tool) ───────────────────
    {"id": "A1", "category": "ambiguous",
     "prompt": "Generate VASP inputs.",
     "expected_tools": ["NONE"]},
    {"id": "A2", "category": "ambiguous",
     "prompt": "Can you run a simulation for me?",
     "expected_tools": ["NONE"]},
    {"id": "A3", "category": "ambiguous",
     "prompt": "I want to study this material.",
     "expected_tools": ["NONE"]},

    # ── out-of-scope / adversarial → should refuse / redirect (no tool) ──────
    {"id": "O1", "category": "out_of_scope",
     "prompt": "What's the weather in Paris today?",
     "expected_tools": ["NONE"]},
    {"id": "O2", "category": "out_of_scope",
     "prompt": "Train a brand-new machine-learning potential from scratch on my dataset.",
     "expected_tools": ["NONE"]},
    {"id": "O3", "category": "out_of_scope",
     "prompt": "Write me a Python script to scrape product prices off a website.",
     "expected_tools": ["NONE"]},
    {"id": "O4", "category": "out_of_scope",
     "prompt": "Relax my structure with the CHGNet potential.",
     "context": _ACTIVE_SI,
     "expected_tools": ["list_models", "NONE"]},

    # ── conceptual → answer directly, no tool ────────────────────────────────
    {"id": "C1", "category": "conceptual",
     "prompt": "What is a POSCAR file?",
     "expected_tools": ["NONE"]},
    {"id": "C2", "category": "conceptual",
     "prompt": "Explain in simple terms what the bulk modulus measures.",
     "expected_tools": ["NONE"]},
    {"id": "C3", "category": "conceptual",
     "prompt": "What is the difference between the NVT and NPT ensembles?",
     "expected_tools": ["NONE"]},
]
