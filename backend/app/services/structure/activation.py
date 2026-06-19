"""Structure parsing + activation (Phase E, U1/U2).

A single place that knows how to (a) recognise a structure file by name, (b)
parse it into a pymatgen ``Structure`` across the many formats pymatgen/ASE read,
and (c) *activate* it — write the canonical ``POSCAR`` into the session so the
optimize / MD / VASP tools pick it up. Used by both the upload endpoint and the
``read_file`` tool so the behaviour is identical wherever a structure enters.
"""

from __future__ import annotations

from pathlib import Path

# Periodic-structure file extensions pymatgen/ASE can read (U2 — widened from the
# old {.cif, .xyz}). VASP files (POSCAR/CONTCAR) are matched by name, not suffix.
STRUCTURE_EXTS = {
    ".cif", ".xyz", ".vasp", ".poscar", ".contcar", ".cssr",
    ".pwscf", ".in", ".pdb", ".xsf", ".res", ".gen",
}


class StructureParseError(Exception):
    """Raised when a file can't be parsed into a periodic Structure (user-facing)."""


def is_structure_file(name: str) -> bool:
    """True if `name` looks like a crystal-structure file (by VASP name or suffix)."""
    base = Path(name).name
    if base.upper().startswith(("POSCAR", "CONTCAR")):
        return True
    return Path(name).suffix.lower() in STRUCTURE_EXTS


def parse_structure(path: Path):
    """Parse a structure file with pymatgen, falling back to ASE for odd formats.

    Raises ``StructureParseError`` with a friendly message on any failure.
    """
    try:
        from pymatgen.core import Structure
    except ImportError:
        raise StructureParseError("pymatgen is required. Run: pip install pymatgen")

    try:
        return Structure.from_file(str(path))
    except Exception:  # noqa: BLE001 — try ASE before giving up
        pass

    try:
        from ase.io import read as ase_read
        from pymatgen.io.ase import AseAtomsAdaptor
        return AseAtomsAdaptor.get_structure(ase_read(str(path)))
    except Exception as e:  # noqa: BLE001
        raise StructureParseError(
            f"Could not parse a crystal structure from '{Path(path).name}': {e}. "
            "A periodic cell is required (XYZ files without a lattice are not supported)."
        )


def activate_structure(path: Path, dest_dir: Path) -> dict:
    """Parse `path` and write it as the active structure in `dest_dir`.

    Ordered structures are written as a canonical ``POSCAR`` (so optimize / MD /
    VASP pick them up). Disordered structures (partial site occupancies) CANNOT be
    a POSCAR, so they are kept as a ``.cif`` instead — this is what ``generate_sqs``
    consumes. Returns ``{formula, n_sites, disordered}``; raises
    ``StructureParseError`` if the file can't be parsed.
    """
    from app.services.vasp.poscar import write_poscar

    structure = parse_structure(path)
    formula = structure.composition.reduced_formula

    if not structure.is_ordered:
        from pymatgen.io.cif import CifWriter
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / f"{formula}_disordered.cif"
        CifWriter(structure).write_file(str(out))
        return {"formula": formula, "n_sites": len(structure), "disordered": True}

    write_poscar(structure, dest_dir, name=formula)
    return {"formula": formula, "n_sites": len(structure), "disordered": False}
