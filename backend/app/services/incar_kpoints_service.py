"""
backend/app/services/incar_kpoints_service.py
=============================================
Generates VASP INCAR and KPOINTS files from a pymatgen Structure.

Two public functions:
    generate_incar(structure, task, cell_relax, **overrides)  → str
    generate_kpoints(structure, density, **overrides)         → str

Supported tasks
---------------
  optimization  — geometry relaxation (IBRION=2, NSW=200)
  md_nvt        — NVT molecular dynamics (IBRION=0, MDALGO=2)
  md_npt        — NPT molecular dynamics (IBRION=0, MDALGO=3)
  static        — single-point energy (NSW=0)

Usage
-----
    from app.services.incar_kpoints_service import generate_incar, generate_kpoints

    incar_str   = generate_incar(structure, task="optimization", cell_relax="full")
    kpoints_str = generate_kpoints(structure)

    Path("INCAR").write_text(incar_str)
    Path("KPOINTS").write_text(kpoints_str)
"""

from typing import Optional


# ── INCAR ─────────────────────────────────────────────────────────────────────

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
    "NCORE":    4,
}

# Task-specific overrides / additions
_INCAR_TASKS: dict[str, dict] = {
    "optimization": {
        "IBRION":    2,
        "ISIF":      2,         # will be overridden by cell_relax logic
        "NSW":       200,
        "EDIFFG":   "-0.02",    # force convergence [eV/Å]
        "POTIM":     0.5,
    },
    "static": {
        "IBRION":   -1,
        "ISIF":      2,
        "NSW":       0,
    },
    "md_nvt": {
        "IBRION":    0,
        "MDALGO":    2,          # NVT Nosé-Hoover
        "NSW":       10000,
        "POTIM":     1.0,        # timestep [fs]
        "TEBEG":     300,
        "TEEND":     300,
        "SMASS":     1.0,
        "ISIF":      2,
        "LSCALU":    ".FALSE.",
        "LPLANE":    ".FALSE.",
        "NPAR":      4,
    },
    "md_npt": {
        "IBRION":    0,
        "MDALGO":    3,          # NPT Langevin
        "NSW":       10000,
        "POTIM":     1.0,
        "TEBEG":     300,
        "TEEND":     300,
        "LANGEVIN_GAMMA":   "1.0",   # friction [ps^-1] for atoms
        "LANGEVIN_GAMMA_L": "10.0",  # friction for lattice
        "PMASS":     50,             # lattice mass parameter
        "ISIF":      3,
        "LSCALU":    ".FALSE.",
        "LPLANE":    ".FALSE.",
        "NPAR":      4,
    },
}

# ISIF values for cell relaxation modes
_ISIF_MAP = {
    "none":  2,   # positions only
    "shape": 5,   # shape + positions, fixed volume
    "full":  3,   # shape + volume + positions
}


def generate_incar(
    structure,
    task:        str           = "optimization",
    cell_relax:  str           = "none",
    temperature: Optional[int] = None,
    nsw:         Optional[int] = None,
    timestep:    Optional[float] = None,
    ediffg:      Optional[float] = None,
    **overrides,
) -> str:
    """
    Generate VASP INCAR content as a string.

    Parameters
    ----------
    structure   : pymatgen Structure (used for element-aware MAGMOM, LDAU etc.)
    task        : "optimization" | "static" | "md_nvt" | "md_npt"
    cell_relax  : "none" | "shape" | "full"  (optimization only)
    temperature : Override TEBEG/TEEND [K]
    nsw         : Override NSW (number of steps)
    timestep    : Override POTIM [fs]
    ediffg      : Override EDIFFG (force threshold, stored as negative float)
    **overrides : Any additional INCAR tags to set/override

    Returns
    -------
    str — full INCAR file content
    """
    task_key = task.lower().strip()
    if task_key not in _INCAR_TASKS:
        raise ValueError(
            f"Unknown task '{task}'. "
            f"Supported: {list(_INCAR_TASKS.keys())}"
        )

    tags = {**_INCAR_COMMON, **_INCAR_TASKS[task_key]}

    # Cell relax → ISIF
    if task_key == "optimization":
        tags["ISIF"] = _ISIF_MAP.get(cell_relax.lower(), 2)

    # Dynamic overrides
    if temperature is not None:
        tags["TEBEG"] = temperature
        tags["TEEND"] = temperature

    if nsw is not None:
        tags["NSW"] = int(nsw)

    if timestep is not None:
        tags["POTIM"] = float(timestep)

    if ediffg is not None:
        # Always store as negative (force convergence)
        tags["EDIFFG"] = f"{-abs(float(ediffg))}"

    tags.update(overrides)

    # Add NUPDOWN if magnetic elements detected
    magnetic_elements = {"Fe", "Co", "Ni", "Mn", "Cr", "V", "Cu", "Mo", "W"}
    elements = set(str(el) for el in structure.composition.elements)
    if elements & magnetic_elements:
        tags["ISPIN"] = 2
        # Simple MAGMOM: 5 for mag elements, 0.6 otherwise
        magmom_vals = []
        for site in structure:
            el = str(site.specie)
            magmom_vals.append(5.0 if el in magnetic_elements else 0.6)
        tags["MAGMOM"] = " ".join(str(m) for m in magmom_vals)

    return _format_incar(tags, task_key, cell_relax)


def _format_incar(tags: dict, task: str, cell_relax: str) -> str:
    """Format tags dict into INCAR string with section headers."""
    lines = [
        f"# INCAR generated by Materia",
        f"# Task: {task}  |  Cell relax: {cell_relax}",
        "",
        "# General",
    ]

    general_keys = {"SYSTEM", "ISTART", "ICHARG", "PREC", "ENCUT", "EDIFF",
                    "NELM", "NELMIN", "LREAL", "ALGO", "NCORE"}
    ionic_keys   = {"IBRION", "ISIF", "NSW", "EDIFFG", "POTIM"}
    smear_keys   = {"ISMEAR", "SIGMA"}
    output_keys  = {"LORBIT", "LWAVE", "LCHARG"}
    md_keys      = {"MDALGO", "TEBEG", "TEEND", "SMASS", "LANGEVIN_GAMMA",
                    "LANGEVIN_GAMMA_L", "PMASS", "LSCALU", "LPLANE", "NPAR"}
    mag_keys     = {"ISPIN", "MAGMOM", "NUPDOWN"}

    sections = [
        ("# General",       general_keys),
        ("# Ionic / Cell",  ionic_keys),
        ("# Smearing",      smear_keys),
        ("# Output",        output_keys),
        ("# MD",            md_keys),
        ("# Magnetism",     mag_keys),
    ]

    written = set()
    for header, key_set in sections:
        section_tags = {k: v for k, v in tags.items() if k in key_set}
        if section_tags:
            lines.append(header)
            for k, v in section_tags.items():
                lines.append(f"  {k:<20} = {v}")
                written.add(k)
            lines.append("")

    # Any remaining keys not in predefined sections
    extra = {k: v for k, v in tags.items() if k not in written}
    if extra:
        lines.append("# Additional")
        for k, v in extra.items():
            lines.append(f"  {k:<20} = {v}")
        lines.append("")

    return "\n".join(lines)


# ── KPOINTS ───────────────────────────────────────────────────────────────────

def generate_kpoints(
    structure,
    density:   int  = 40,
    is_md:     bool = False,
    **overrides,
) -> str:
    """
    Generate VASP KPOINTS file using automatic Gamma-centered mesh.

    Parameters
    ----------
    structure : pymatgen Structure
    density   : k-point density [k-points per Å^-1] — higher = denser mesh
    is_md     : If True, uses Gamma-only (1 1 1) — sufficient for MD
    **overrides: Not used; reserved for future mesh overrides

    Returns
    -------
    str — KPOINTS file content
    """
    if is_md:
        return _format_kpoints([1, 1, 1], method="Gamma-only for MD")

    try:
        from pymatgen.io.vasp.inputs import Kpoints
        kpts = Kpoints.automatic_density(structure, kppa=density * 1000)
        mesh = list(kpts.kpts[0])
    except Exception:
        # Fallback: simple reciprocal-length based mesh
        import numpy as np
        lengths    = structure.lattice.abc
        mesh_float = [max(1, round(density / l)) for l in lengths]
        mesh       = [int(m) for m in mesh_float]

    return _format_kpoints(mesh)


def _format_kpoints(mesh: list[int], method: str = "Automatic") -> str:
    """Format a Gamma-centered mesh into KPOINTS string."""
    lines = [
        f"Automatic mesh — Materia ({method})",
        "0",
        "Gamma",
        f"  {mesh[0]}  {mesh[1]}  {mesh[2]}",
        "  0  0  0",
    ]
    return "\n".join(lines)