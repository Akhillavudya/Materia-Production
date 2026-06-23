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


# k-points per atom (kppa) for each named accuracy level. Higher = denser mesh =
# more accurate (and more expensive). These are the common rule-of-thumb densities
# used for metals/semiconductors; "Custom" defers to a user-supplied kppa.
ACCURACY_KPPA = {"Low": 1000, "Medium": 3000, "High": 5000}


def generate_kpoints_by_accuracy(
    structure,
    accuracy_level: str,
    custom_kppa: int | None = None,
    gamma_centered: bool = True,
) -> tuple[str, int]:
    """Build a KPOINTS mesh from a named accuracy level (k-points-per-atom density).

    `accuracy_level` is one of "Low" (1000), "Medium" (3000), "High" (5000) or
    "Custom" (uses `custom_kppa`). `gamma_centered=True` gives a Γ-centered mesh
    (recommended, especially for hexagonal cells); False gives Monkhorst-Pack.

    Returns ``(kpoints_text, kppa_used)``. Raises ValueError on a bad accuracy level
    or a missing/invalid custom_kppa.
    """
    if accuracy_level == "Custom":
        if custom_kppa is None:
            raise ValueError(
                'accuracy_level="Custom" requires custom_kppa (k-points per atom).')
        if int(custom_kppa) < 1:
            raise ValueError("custom_kppa must be a positive integer.")
        kppa = int(custom_kppa)
    elif accuracy_level in ACCURACY_KPPA:
        kppa = ACCURACY_KPPA[accuracy_level]
    else:
        raise ValueError(
            f'Invalid accuracy_level "{accuracy_level}". '
            'Use "Low", "Medium", "High" or "Custom".')

    from pymatgen.io.vasp.inputs import Kpoints

    kpts = Kpoints.automatic_density(structure, kppa=kppa).kpts[0]
    kpoints = (Kpoints.gamma_automatic(kpts=kpts) if gamma_centered
               else Kpoints.monkhorst_automatic(kpts=kpts))
    style = "Gamma-centered" if gamma_centered else "Monkhorst-Pack"
    kpoints.comment = (
        f"Materia KPOINTS — {accuracy_level} accuracy "
        f"(kppa={kppa}, {style})")
    return str(kpoints), kppa


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
