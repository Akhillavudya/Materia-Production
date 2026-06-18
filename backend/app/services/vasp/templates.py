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
    "elastic": {
        # Elastic constants via finite differences of the stress tensor.
        "IBRION":  6,
        "ISIF":    3,
        "NFREE":   2,
        "NSW":     1,
        "EDIFF":   "1E-7",     # tight electronic convergence for accurate stress
        "ISMEAR":  0,
        "SIGMA":   0.05,
    },
    "phonon_dfpt": {
        # Γ-point phonons + Born charges via density-functional perturbation theory.
        "IBRION":   8,
        "LEPSILON": ".TRUE.",  # also yields the ion-clamped dielectric tensor
        "NSW":      1,
        "EDIFF":    "1E-8",    # phonons need very tight convergence
        "ISMEAR":   0,
        "SIGMA":    0.05,
    },
    "dielectric": {
        # Frequency-dependent dielectric function (independent-particle, LOPTIC).
        "IBRION":  -1,
        "NSW":      0,
        "LOPTIC":   ".TRUE.",
        "CSHIFT":   0.100,     # complex shift for the Kramers-Kronig transform
        "NEDOS":    2000,
        "LREAL":    ".FALSE.", # LOPTIC requires reciprocal-space projection
        "ISMEAR":   0,
        "SIGMA":    0.05,
    },
    "bader": {
        # Static run that writes the all-electron density for Bader analysis.
        "IBRION":  -1,
        "NSW":      0,
        "LAECHG":   ".TRUE.",  # AECCAR0/AECCAR2 for the bader code
        "LCHARG":   ".TRUE.",
        "ISMEAR":  -5,
    },
    "elf": {
        # Electron localization function.
        "IBRION":  -1,
        "NSW":      0,
        "LELF":     ".TRUE.",
        "LCHARG":   ".TRUE.",
        "ISMEAR":   0,
        "SIGMA":    0.05,
    },
    "workfunction": {
        # Slab static run writing the planar-averaged potential (LVTOT/LVHAR)
        # with a dipole correction along c so the vacuum level is well defined.
        "IBRION":  -1,
        "NSW":      0,
        "LVTOT":    ".TRUE.",
        "LVHAR":    ".TRUE.",
        "LDIPOL":   ".TRUE.",
        "IDIPOL":   3,
        "ISMEAR":   0,
        "SIGMA":    0.05,
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


# ─────────────────────────────────────────────────────────────────────────────
# Modifier tag groups (Step 5.5)
#
# Modifiers are orthogonal knobs that `incar.generate_incar` layers on top of ANY
# task's tags. Each maps a user-facing choice to the INCAR tags it injects. The
# "off"/default choice (``pbe`` / ``none`` / disabled) maps to an EMPTY dict, so
# default generation stays byte-for-byte unchanged when no modifier is requested.
# ─────────────────────────────────────────────────────────────────────────────

# Exchange-correlation functional. PBE is the implicit default (no extra tags).
# HSE06 and SCAN are mutually exclusive (both set ALGO); the caller validates.
_FUNCTIONAL_TAGS: dict[str, dict] = {
    "pbe": {},
    "hse06": {
        "LHFCALC":  ".TRUE.",
        "HFSCREEN": 0.2,        # range-separation parameter ω [Å^-1]
        "AEXX":     0.25,       # 25% exact exchange
        "ALGO":     "Damped",   # robust for hybrids
        "TIME":     0.4,
        "PRECFOCK": "Fast",
    },
    "scan": {
        "METAGGA":  "SCAN",
        "LASPH":    ".TRUE.",   # aspherical gradient corrections (required)
        "ALGO":     "All",
    },
}

# Empirical / non-local van-der-Waals dispersion corrections.
_VDW_TAGS: dict[str, dict] = {
    "none":   {},
    "d3":     {"IVDW": 11},     # DFT-D3 (zero damping)
    "d3bj":   {"IVDW": 12},     # DFT-D3 (Becke-Johnson damping)
    "optb88": {"GGA": "BO", "PARAM1": 0.1833333333, "PARAM2": 0.2200000000,
               "LUSE_VDW": ".TRUE.", "AGGAC": 0.0},
    "df2":    {"GGA": "ML", "LUSE_VDW": ".TRUE.", "Zab_vdW": -1.8867, "AGGAC": 0.0},
}

# Implicit solvation (VASPsol). Requires the VASPsol-patched VASP binary — the
# generator warns about this; tags are inert in a stock VASP build.
_SOLVENT_TAGS: dict[str, dict] = {
    "none": {},
    "vaspsol": {
        "LSOL": ".TRUE.",
        "EB_K": 78.4,           # bulk relative permittivity (water)
    },
    "vaspsol++": {
        "LSOL":   ".TRUE.",
        "EB_K":   78.4,
        "LRHOB":  ".TRUE.",     # linearized Poisson-Boltzmann electrolyte
        "NC_K":   1.0,          # bulk electrolyte concentration [mol/L]
    },
}

# Spin-orbit coupling (noncollinear). MAGMOM must become 3-vectors per atom —
# the generator emits a warning when this is enabled.
_SOC_TAGS: dict = {
    "LSORBIT":       ".TRUE.",
    "LNONCOLLINEAR": ".TRUE.",
    "ISYM":          -1,        # symmetry off for noncollinear
}

# Dipole correction along c (slabs / work-function / charged cells).
_DIPOLE_TAGS: dict = {
    "LDIPOL": ".TRUE.",
    "IDIPOL": 3,
}

# Curated Hubbard-U values [eV] for common transition-metal d-electrons
# (LDAUTYPE=2, Dudarev). Elements absent here get U=0 (LDAUL=-1). These are
# typical literature defaults — the generator warns that they should be verified.
_HUBBARD_U: dict[str, float] = {
    "V": 3.25, "Cr": 3.7, "Mn": 3.9, "Fe": 5.3, "Co": 3.32,
    "Ni": 6.45, "Cu": 4.0, "Mo": 4.38, "W": 6.2,
}
