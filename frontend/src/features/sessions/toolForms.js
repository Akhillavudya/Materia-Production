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
 */

export const TOOL_FORMS = [
  {
    key: 'optimize',
    label: 'Optimize',
    category: 'Structure',
    color: '#00B4A6',
    icon: 'optimize',
    description: 'Relax atoms (and optionally the cell) to a local energy minimum.',
    endpoint: 'optimize',
    calculator: true,
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
    description: 'Evolve the structure at temperature with NVT/NPT dynamics.',
    endpoint: 'md',
    calculator: true,
    fields: [
      { name: 'ensemble', label: 'Ensemble', type: 'select', default: 'nvt',
        options: [['nvt', 'nvt'], ['npt', 'npt']] },
      { name: 'temperature', label: 'Temp (K)', type: 'number', default: 300, min: 1 },
      { name: 'nsw', label: 'Steps', type: 'number', default: 2000, min: 1 },
      { name: 'timestep', label: 'Δt (fs)', type: 'number', default: 1.0, step: 0.1, min: 0.1 },
      { name: 'pressure', label: 'Pressure (GPa)', type: 'number', default: 0.0, step: 0.1 },
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
    fields: [
      { name: 'n_images', label: 'Images', type: 'number', default: 7, min: 3, max: 15 },
      { name: 'climb', label: 'Climbing image', type: 'checkbox', default: true },
    ],
  },
]
