"""INCAR task presets (redesign §9).

`_INCAR_TASKS` keys are the *internal* template names. The user-facing
`VaspTask` enum maps onto these in `service.py`:

    VaspTask.RELAXATION → "optimization"
    VaspTask.STATIC     → "static"

The ``md_nvt`` / ``md_npt`` presets are consumed directly by the MD service for
the equivalent VASP-MD handoff inputs.

Parallelisation (``NCORE``) is intentionally NOT hardcoded here — it is injected
by ``incar.generate_incar`` from ``settings.vasp_ncore`` and omitted when unset so
VASP auto-parallelises rather than crashing on machines with a different layout.
"""

# Tags shared by all tasks
_INCAR_COMMON = {
    "SYSTEM":   "Materia calculation",
    "ISTART":   0,
    "ICHARG":   2,
    "ENCUT":    520,
    "PREC":     "Accurate",
    "EDIFF":    "1E-6",
    "NELM":     200,
    "NELMIN":   6,
    "LREAL":    "Auto",
    "ALGO":     "Fast",
    "ISMEAR":   0,
    "SIGMA":    0.05,
    "LORBIT":   11,
    "LWAVE":    ".FALSE.",
    "LCHARG":   ".FALSE.",
}

# Task-specific overrides / additions
_INCAR_TASKS: dict[str, dict] = {
    "optimization": {
        "IBRION":   2,
        "ISIF":     2,          # overridden by cell_relax logic
        "NSW":      200,
        "EDIFFG":   "-0.02",    # force convergence [eV/Å]
        "POTIM":    0.5,
    },
    "static": {
        "IBRION":  -1,
        "ISIF":     2,
        "NSW":      0,
    },
    "band": {
        # Non-self-consistent band structure along a high-symmetry path.
        # Reads the converged charge density (CHGCAR) from a prior static run.
        "IBRION":  -1,
        "NSW":      0,
        "ICHARG":   11,         # non-SCF: fixed charge density from static run
        "ISMEAR":   0,
        "SIGMA":    0.05,
        "LORBIT":   11,
        "LCHARG":   ".FALSE.",
    },
    "dos": {
        # Dense, self-consistent run for an accurate density of states.
        "IBRION":  -1,
        "NSW":      0,
        "ISMEAR":  -5,          # tetrahedron method with Blöchl corrections
        "NEDOS":    2001,
        "LORBIT":   11,
        "LCHARG":   ".TRUE.",
    },
    "md_nvt": {
        "IBRION":   0,
        "MDALGO":   2,          # NVT Nosé-Hoover
        "NSW":      10000,
        "POTIM":    1.0,        # timestep [fs]
        "TEBEG":    300,
        "TEEND":    300,
        "SMASS":    1.0,
        "ISIF":     2,
        "LSCALU":   ".FALSE.",
        "LPLANE":   ".FALSE.",
    },
    "md_npt": {
        "IBRION":   0,
        "MDALGO":   3,          # NPT Langevin
        "NSW":      10000,
        "POTIM":    1.0,
        "TEBEG":    300,
        "TEEND":    300,
        "LANGEVIN_GAMMA":   "1.0",   # friction [ps^-1] for atoms
        "LANGEVIN_GAMMA_L": "10.0",  # friction for lattice
        "PMASS":    50,              # lattice mass parameter
        "ISIF":     3,
        "LSCALU":   ".FALSE.",
        "LPLANE":   ".FALSE.",
    },
}

# ISIF values for cell relaxation modes
_ISIF_MAP = {
    "none":  2,   # positions only
    "shape": 5,   # shape + positions, fixed volume
    "full":  3,   # shape + volume + positions
}
