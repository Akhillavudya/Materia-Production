"""INCAR generation from a pymatgen Structure.

Public:
    generate_incar(structure, task, cell_relax, **overrides) -> str

`task` is an internal template key (see `templates._INCAR_TASKS`):
``optimization`` | ``static`` | ``md_nvt`` | ``md_npt``.
"""

from typing import Optional

from app.core.config import settings
from app.services.vasp.templates import (
    _DIPOLE_TAGS,
    _FUNCTIONAL_TAGS,
    _HUBBARD_U,
    _INCAR_COMMON,
    _INCAR_TASKS,
    _ISIF_MAP,
    _SOC_TAGS,
    _SOLVENT_TAGS,
    _VDW_TAGS,
)


def generate_incar(
    structure,
    task:        str             = "optimization",
    cell_relax:  str             = "none",
    temperature: Optional[int]   = None,
    nsw:         Optional[int]   = None,
    timestep:    Optional[float] = None,
    ediffg:      Optional[float] = None,
    # ── modifiers (Step 5.5) — orthogonal knobs layered on top of the task.
    #    Defaults are inert: with these unset the INCAR is byte-identical to before.
    functional:  str  = "pbe",
    vdw:         str  = "none",
    soc:         bool = False,
    hubbard_u=None,                  # truthy → DFT+U; dict overrides curated values
    solvent:     str  = "none",
    dipole:      bool = False,
    **overrides,
) -> str:
    """Generate VASP INCAR content as a string."""
    task_key = task.lower().strip()
    if task_key not in _INCAR_TASKS:
        raise ValueError(
            f"Unknown task '{task}'. Supported: {list(_INCAR_TASKS.keys())}"
        )

    tags = {**_INCAR_COMMON, **_INCAR_TASKS[task_key]}

    # Cell relax → ISIF (optimization only)
    if task_key == "optimization":
        tags["ISIF"] = _ISIF_MAP.get(cell_relax.lower(), 2)

    # Modifiers (COMMON → task → MODIFIERS → MD params → overrides). Inert at defaults.
    tags.update(_modifier_tags(structure, functional, vdw, soc, hubbard_u, solvent, dipole))

    if temperature is not None:
        tags["TEBEG"] = temperature
        tags["TEEND"] = temperature
    if nsw is not None:
        tags["NSW"] = int(nsw)
    if timestep is not None:
        tags["POTIM"] = float(timestep)
    if ediffg is not None:
        tags["EDIFFG"] = f"{-abs(float(ediffg))}"   # always negative (force conv.)

    # Parallelisation: only emit NCORE when explicitly configured, so VASP
    # auto-parallelises elsewhere instead of inheriting a hardcoded value (§9).
    if settings.vasp_ncore:
        tags.setdefault("NCORE", int(settings.vasp_ncore))

    tags.update(overrides)

    # Add spin/MAGMOM if magnetic elements detected
    magnetic_elements = {"Fe", "Co", "Ni", "Mn", "Cr", "V", "Cu", "Mo", "W"}
    elements = set(str(el) for el in structure.composition.elements)
    if elements & magnetic_elements:
        tags["ISPIN"] = 2
        magmom_vals = [
            5.0 if str(site.specie) in magnetic_elements else 0.6
            for site in structure
        ]
        tags["MAGMOM"] = " ".join(str(m) for m in magmom_vals)

    return _format_incar(tags, task_key, cell_relax)


def _ordered_elements(structure) -> list[str]:
    """Unique element symbols in POSCAR/POTCAR order (first appearance)."""
    seen: list[str] = []
    for site in structure:
        sym = site.specie.symbol if hasattr(site.specie, "symbol") else str(site.specie)
        if sym not in seen:
            seen.append(sym)
    return seen


def _hubbard_tags(structure, hubbard_u) -> dict:
    """Build LDAU tags (Dudarev, LDAUTYPE=2) in POTCAR element order.

    `hubbard_u` may be ``True`` (use the curated `_HUBBARD_U` table) or a dict of
    ``{element: U_eV}`` overriding/extending it. Elements with no U get LDAUL=-1.
    """
    if not hubbard_u:
        return {}
    u_table = dict(_HUBBARD_U)
    if isinstance(hubbard_u, dict):
        u_table.update({k: float(v) for k, v in hubbard_u.items()})

    elements = _ordered_elements(structure)
    ldaul, ldauu, ldauj = [], [], []
    for el in elements:
        if el in u_table:
            ldaul.append("2")              # d-electrons
            ldauu.append(f"{u_table[el]:g}")
            ldauj.append("0")
        else:
            ldaul.append("-1")             # no +U
            ldauu.append("0")
            ldauj.append("0")
    return {
        "LDAU":     ".TRUE.",
        "LDAUTYPE": 2,
        "LDAUL":    " ".join(ldaul),
        "LDAUU":    " ".join(ldauu),
        "LDAUJ":    " ".join(ldauj),
        "LMAXMIX":  4,                     # required for d-electron +U
    }


def _modifier_tags(structure, functional, vdw, soc, hubbard_u, solvent, dipole) -> dict:
    """Merge the requested modifier tag-groups. Returns ``{}`` when all are default."""
    tags: dict = {}
    tags.update(_FUNCTIONAL_TAGS.get((functional or "pbe").lower(), {}))
    tags.update(_VDW_TAGS.get((vdw or "none").lower(), {}))
    tags.update(_SOLVENT_TAGS.get((solvent or "none").lower(), {}))
    if soc:
        tags.update(_SOC_TAGS)
    if dipole:
        tags.update(_DIPOLE_TAGS)
    tags.update(_hubbard_tags(structure, hubbard_u))
    return tags


def _format_incar(tags: dict, task: str, cell_relax: str) -> str:
    """Format a tags dict into INCAR text with section headers."""
    lines = [
        "# INCAR generated by Materia",
        f"# Task: {task}  |  Cell relax: {cell_relax}",
        "",
    ]

    general_keys = {"SYSTEM", "ISTART", "ICHARG", "PREC", "ENCUT", "EDIFF",
                    "NELM", "NELMIN", "LREAL", "ALGO", "NCORE"}
    ionic_keys   = {"IBRION", "ISIF", "NSW", "EDIFFG", "POTIM"}
    smear_keys   = {"ISMEAR", "SIGMA"}
    output_keys  = {"LORBIT", "LWAVE", "LCHARG", "NEDOS"}
    md_keys      = {"MDALGO", "TEBEG", "TEEND", "SMASS", "LANGEVIN_GAMMA",
                    "LANGEVIN_GAMMA_L", "PMASS", "LSCALU", "LPLANE", "NPAR"}
    mag_keys     = {"ISPIN", "MAGMOM", "NUPDOWN"}

    sections = [
        ("# General",      general_keys),
        ("# Ionic / Cell", ionic_keys),
        ("# Smearing",     smear_keys),
        ("# Output",       output_keys),
        ("# MD",           md_keys),
        ("# Magnetism",    mag_keys),
    ]

    written: set = set()
    for header, key_set in sections:
        section_tags = {k: v for k, v in tags.items() if k in key_set}
        if section_tags:
            lines.append(header)
            for k, v in section_tags.items():
                lines.append(f"  {k:<20} = {v}")
                written.add(k)
            lines.append("")

    extra = {k: v for k, v in tags.items() if k not in written}
    if extra:
        lines.append("# Additional")
        for k, v in extra.items():
            lines.append(f"  {k:<20} = {v}")
        lines.append("")

    return "\n".join(lines)
