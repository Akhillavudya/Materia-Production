/**
 * Declarative specs for the RightPanel "method card" launcher.
 *
 * Each entry drives one category-coded card in ToolLaunchPanel: a colored edge
 * rail + icon keyed to a physics category, a collapsed one-line description, and
 * (when expanded) a parameter grid. Field `name`s match the backend Form
 * parameter names exactly, and defaults/options are pulled straight from
 * backend/app/tools/contracts.py — not invented.
 *
 * `calculator: true` adds the shared MACE/MatterSim "Potential" row (rendered
 * separately, teal-tinted). `twoFiles` marks NEB (initial + final endpoints).
 * `fields` holds only the non-calculator numeric/select/text params.
 * `heavy: true` marks the long-running ML-potential simulations: on the lite web
 * edition (heavy_tools_enabled=false) the card stays VISIBLE but its Run button
 * points the user to the desktop app instead of starting a job (Deployment Part A).
 */

export const TOOL_FORMS = [
  // ── instant structure tools (Step 3): run synchronously and post the result
  //    straight into the chat timeline as a tool card (no background job). ──
  {
    key: 'make_supercell',
    label: 'Supercell',
    category: 'Structure',
    color: '#0E7C66',
    icon: 'supercell',
    description: 'Replicate the active cell into a larger supercell.',
    endpoint: 'make_supercell',
    instant: true,
    fields: [
      { name: 'scaling', label: 'Scaling', type: 'text', default: '2 2 1', placeholder: '2 2 1  or  2' },
    ],
  },
  {
    key: 'add_vacuum',
    label: 'Add Vacuum',
    category: 'Structure',
    color: '#2E8B8B',
    icon: 'vacuum',
    description: 'Set the vacuum gap along one axis to an exact thickness.',
    endpoint: 'add_vacuum',
    instant: true,
    fields: [
      { name: 'axis', label: 'Axis', type: 'select', default: 'c',
        options: [['a', 'a'], ['b', 'b'], ['c', 'c']] },
      { name: 'thickness', label: 'Thickness (Å)', type: 'number', default: 15.0, step: 0.5, min: 0 },
      { name: 'side', label: 'Side', type: 'select', default: 'both',
        options: [['both', 'both'], ['top', 'top'], ['bottom', 'bottom']] },
    ],
  },
  {
    key: 'make_slab',
    label: 'Make Slab',
    category: 'Structure',
    color: '#1F8A70',
    icon: 'slab',
    description: 'Cut a surface slab along a Miller index (vacuum included).',
    endpoint: 'make_slab',
    instant: true,
    fields: [
      { name: 'miller', label: 'Miller (hkl)', type: 'text', default: '1 1 1' },
      { name: 'layers', label: 'Layers (blank = by size)', type: 'number', default: '', min: 1 },
      { name: 'min_slab_size', label: 'Min slab (Å)', type: 'number', default: 10.0, step: 1, min: 1 },
      { name: 'min_vacuum_size', label: 'Min vacuum (Å)', type: 'number', default: 15.0, step: 1, min: 0 },
      { name: 'shift', label: 'Shift', type: 'number', default: 0.0, step: 0.1 },
    ],
  },
  {
    key: 'add_adsorbate',
    label: 'Add Adsorbate',
    category: 'Surface',
    color: '#C06B2E',
    icon: 'adsorbate',
    description: 'Place a molecule on the active slab (optional accurate relax).',
    endpoint: 'add_adsorbate',
    instant: true,
    calculator: true,
    fields: [
      { name: 'molecule', label: 'Molecule', type: 'text', default: '', placeholder: 'CO2', required: true },
      { name: 'site_type', label: 'Site', type: 'select', default: 'ontop',
        options: [['ontop', 'ontop'], ['bridge', 'bridge'], ['hollow', 'hollow']] },
      { name: 'distance', label: 'Distance (Å)', type: 'number', default: 2.0, step: 0.1, min: 0.5 },
      { name: 'relax', label: 'Relax (accurate — runs a job)', type: 'checkbox', default: false },
    ],
  },
  {
    key: 'convert_structure',
    label: 'Convert Format',
    category: 'Format',
    color: '#5C6BC0',
    icon: 'convert',
    description: 'Write the active structure in another file format.',
    endpoint: 'convert_structure',
    instant: true,
    fields: [
      { name: 'to_format', label: 'Format', type: 'select', default: 'cif',
        options: [['cif', 'CIF'], ['poscar', 'POSCAR'], ['xyz', 'XYZ'], ['cssr', 'CSSR'], ['json', 'JSON']] },
    ],
  },
  // ── instant VASP-input tools: write VASP files for the active structure ──
  {
    key: 'generate_vasp_inputs',
    label: 'VASP Inputs',
    category: 'VASP',
    color: '#6D5BD0',
    icon: 'vasp',
    description: 'Full VASP input set (POSCAR + INCAR + KPOINTS) with modifiers.',
    endpoint: 'generate_vasp_inputs',
    instant: true,
    fields: [
      { name: 'task', label: 'Task', type: 'select', default: 'relaxation',
        options: [
          ['static', 'static'], ['relaxation', 'relaxation'], ['band', 'band'],
          ['dos', 'dos'], ['aimd', 'aimd'], ['elastic', 'elastic'],
          ['phonon_dfpt', 'phonon_dfpt'], ['dielectric', 'dielectric'],
          ['bader', 'bader'], ['elf', 'elf'], ['workfunction', 'workfunction'],
        ] },
      { name: 'cell_relax', label: 'Cell relax', type: 'select', default: 'none',
        options: [['none', 'none'], ['shape', 'shape'], ['full', 'full']] },
      { name: 'functional', label: 'Functional', type: 'select', default: 'pbe',
        options: [['pbe', 'PBE'], ['hse06', 'HSE06'], ['scan', 'SCAN']] },
      { name: 'vdw', label: 'vdW', type: 'select', default: 'none',
        options: [['none', 'none'], ['d3', 'D3'], ['d3bj', 'D3BJ'],
                  ['optb88', 'optB88'], ['df2', 'DF2']] },
      { name: 'charge', label: 'Charge (e)', type: 'number', default: 0.0, step: 0.1 },
      { name: 'soc', label: 'Spin-orbit (SOC)', type: 'checkbox', default: false },
      { name: 'hubbard_u', label: 'DFT+U', type: 'checkbox', default: false },
      { name: 'dipole', label: 'Dipole correction', type: 'checkbox', default: false },
    ],
  },
  {
    key: 'generate_poscar',
    label: 'Generate POSCAR',
    category: 'VASP',
    color: '#7C6FD6',
    icon: 'poscar',
    description: 'Write just a POSCAR for the active structure (no INCAR/KPOINTS).',
    endpoint: 'generate_poscar',
    instant: true,
    fields: [],
  },
  {
    key: 'generate_kpoints',
    label: 'Generate KPOINTS',
    category: 'VASP',
    color: '#8A7EE0',
    icon: 'kpoints',
    description: 'Write a KPOINTS mesh at a chosen accuracy (k-points per atom).',
    endpoint: 'generate_kpoints',
    instant: true,
    fields: [
      { name: 'accuracy_level', label: 'Accuracy', type: 'select', default: 'Medium',
        options: [['Low', 'Low (kppa 1000)'], ['Medium', 'Medium (3000)'],
                  ['High', 'High (5000)'], ['Custom', 'Custom (kppa)']] },
      { name: 'custom_kppa', label: 'Custom kppa', type: 'number', default: '', min: 1 },
      { name: 'gamma_centered', label: 'Γ-centered (else Monkhorst-Pack)', type: 'checkbox', default: true },
    ],
  },
  // ── instant defect tools: build a defective supercell as the active POSCAR ──
  {
    key: 'create_vacancy',
    label: 'Vacancy',
    category: 'Defect',
    color: '#C9536B',
    icon: 'vacancy',
    description: 'Remove one atom in a supercell to make a vacancy defect.',
    endpoint: 'create_vacancy',
    instant: true,
    fields: [
      { name: 'element', label: 'Element (blank = first)', type: 'text', default: '', placeholder: 'O' },
      { name: 'supercell', label: 'Supercell (blank = auto)', type: 'text', default: '', placeholder: '2 2 2' },
    ],
  },
  {
    key: 'create_substitution',
    label: 'Substitution',
    category: 'Defect',
    color: '#CB6553',
    icon: 'substitution',
    description: 'Replace one element with another in a supercell.',
    endpoint: 'create_substitution',
    instant: true,
    fields: [
      { name: 'from_element', label: 'From', type: 'text', default: '', placeholder: 'Si', required: true },
      { name: 'to_element', label: 'To', type: 'text', default: '', placeholder: 'Al', required: true },
      { name: 'supercell', label: 'Supercell (blank = auto)', type: 'text', default: '', placeholder: '2 2 2' },
    ],
  },
  {
    key: 'create_interstitial',
    label: 'Interstitial',
    category: 'Defect',
    color: '#C77A45',
    icon: 'interstitial',
    description: 'Insert an atom at a Voronoi interstitial site in a supercell.',
    endpoint: 'create_interstitial',
    instant: true,
    fields: [
      { name: 'insert_element', label: 'Insert element', type: 'text', default: '', placeholder: 'H', required: true },
      { name: 'supercell', label: 'Supercell (blank = auto)', type: 'text', default: '', placeholder: '2 2 2' },
    ],
  },
  {
    key: 'optimize',
    label: 'Optimize',
    category: 'Structure',
    color: '#00B4A6',
    icon: 'optimize',
    description: 'Relax atoms (and optionally the cell) to a local energy minimum.',
    endpoint: 'optimize',
    calculator: true,
    heavy: true,
    fields: [
      { name: 'fmax', label: 'fmax (eV/Å)', type: 'number', default: 0.02, step: 0.01, min: 0.001 },
      { name: 'cell_relax', label: 'Cell relax', type: 'select', default: 'none',
        options: [['none', 'none'], ['shape', 'shape'], ['full', 'full']] },
      { name: 'optimizer', label: 'Optimizer', type: 'select', default: 'FIRE',
        options: [['FIRE', 'FIRE'], ['BFGS', 'BFGS'], ['LBFGS', 'LBFGS']] },
      { name: 'max_steps', label: 'Max steps', type: 'number', default: 1000, min: 1 },
    ],
  },
  {
    key: 'md',
    label: 'Molecular Dynamics',
    category: 'Dynamics',
    color: '#378ADD',
    icon: 'md',
    description: 'Evolve the structure at temperature with NVT/NPT/NVE dynamics.',
    endpoint: 'md',
    calculator: true,
    heavy: true,
    fields: [
      { name: 'ensemble', label: 'Ensemble', type: 'select', default: 'nvt',
        options: [
          ['nvt', 'NVT (const T)'],
          ['npt', 'NPT (const T,P)'],
          ['nve', 'NVE (microcanonical)'],
        ] },
      // Thermostat choices depend on the ensemble; NVE has none (pure energy
      // conservation) so the field is hidden for it. Matches backend md.py.
      { name: 'thermostat', label: 'Thermostat', type: 'select', default: 'langevin',
        showIf: (v) => v.ensemble !== 'nve',
        options: (v) => v.ensemble === 'npt'
          ? [['berendsen', 'Berendsen'], ['bussi', 'Bussi (CSVR)']]
          : [['langevin', 'Langevin'], ['nose-hoover', 'Nosé–Hoover']] },
      { name: 'temperature', label: 'Temp (K)', type: 'number', default: 300, min: 1 },
      { name: 'nsw', label: 'Steps', type: 'number', default: 2000, min: 1 },
      { name: 'timestep', label: 'Δt (fs)', type: 'number', default: 1.0, step: 0.1, min: 0.1 },
      // Pressure is only meaningful for NPT.
      { name: 'pressure', label: 'Pressure (GPa)', type: 'number', default: 0.0, step: 0.1,
        showIf: (v) => v.ensemble === 'npt' },
    ],
  },
  {
    key: 'phonons',
    label: 'Phonons',
    category: 'Vibrational',
    color: '#D85A30',
    icon: 'phonons',
    description: 'Lattice vibration band structure + DOS via finite displacements.',
    endpoint: 'phonons',
    calculator: true,
    heavy: true,
    fields: [
      { name: 'supercell', label: 'Supercell', type: 'text', default: '3 3 3' },
      { name: 'disp_distance', label: 'Disp (Å)', type: 'number', default: 0.01, step: 0.01, min: 0.001 },
      { name: 'mesh', label: 'Mesh (N)', type: 'number', default: 20, min: 5, max: 60 },
    ],
  },
  {
    key: 'elastic',
    label: 'Elastic Tensor',
    category: 'Mechanical',
    color: '#7F77DD',
    icon: 'elastic',
    description: 'Elastic constants and moduli (K, G, E, ν) from strained cells.',
    endpoint: 'elastic',
    calculator: true,
    heavy: true,
    fields: [
      { name: 'fmax', label: 'fmax (eV/Å)', type: 'number', default: 0.01, step: 0.01, min: 0.001 },
      { name: 'max_steps', label: 'Max steps', type: 'number', default: 300, min: 1 },
    ],
  },
  {
    key: 'sqs',
    label: 'SQS',
    category: 'Statistical',
    color: '#D4537E',
    icon: 'sqs',
    description: 'Best quasi-random ordering of a disordered (alloy) cell.',
    endpoint: 'sqs',
    calculator: false,
    heavy: true,
    fields: [
      { name: 'supercell', label: 'Supercell', type: 'text', default: '2 2 2' },
      { name: 'target_comp', label: 'Target comp', type: 'text', default: '',
        placeholder: 'Li:1,Ni:0.8,Mn:0.1,Co:0.1,O:2' },
      { name: 'n_parallel', label: 'Parallel', type: 'number', default: 4, min: 1, max: 16 },
      { name: 'time_budget_s', label: 'Budget (s)', type: 'number', default: 600, min: 30 },
    ],
  },
  {
    key: 'neb',
    label: 'NEB',
    category: 'Pathway',
    color: '#BA7517',
    icon: 'neb',
    description: 'Migration energy barrier between a start and an end state.',
    endpoint: 'neb',
    calculator: true,
    twoFiles: true,
    heavy: true,
    fields: [
      { name: 'n_images', label: 'Images', type: 'number', default: 7, min: 3, max: 15 },
      { name: 'climb', label: 'Climbing image', type: 'checkbox', default: true },
    ],
  },
]
