"""KPOINTS generation from a pymatgen Structure.

Public:
    generate_kpoints(structure, density, is_md, **overrides) -> str
    generate_line_kpoints(structure, divisions) -> str   # band-structure path
"""


def generate_kpoints(
    structure,
    density: int  = 40,
    is_md:   bool = False,
    **overrides,
) -> str:
    """Generate a Gamma-centered KPOINTS mesh.

    `density` is k-points per Å^-1 (higher = denser). `is_md=True` uses a single
    Gamma point, which is sufficient for molecular dynamics.
    """
    if is_md:
        return _format_kpoints([1, 1, 1], method="Gamma-only for MD")

    try:
        from pymatgen.io.vasp.inputs import Kpoints
        kpts = Kpoints.automatic_density(structure, kppa=density * 50)
        mesh = list(kpts.kpts[0])
    except Exception:
        lengths = structure.lattice.abc
        mesh = [int(max(1, round(density / l))) for l in lengths]

    return _format_kpoints(mesh)


def generate_line_kpoints(structure, divisions: int = 40) -> str:
    """Generate a line-mode KPOINTS file along the high-symmetry path (for bands).

    Uses pymatgen's `HighSymmKpath`; falls back to a Γ-mesh string if pymatgen or
    the symmetry analysis is unavailable.
    """
    try:
        from pymatgen.io.vasp.inputs import Kpoints
        from pymatgen.symmetry.bandstructure import HighSymmKpath

        kpath = HighSymmKpath(structure)
        kpoints = Kpoints.automatic_linemode(divisions, kpath)
        return str(kpoints)
    except Exception:
        # Degrade gracefully — a regular mesh is still a usable (if non-ideal) input.
        return generate_kpoints(structure)


def _format_kpoints(mesh: list[int], method: str = "Automatic") -> str:
    lines = [
        f"Automatic mesh — Materia ({method})",
        "0",
        "Gamma",
        f"  {mesh[0]}  {mesh[1]}  {mesh[2]}",
        "  0  0  0",
    ]
    return "\n".join(lines)
