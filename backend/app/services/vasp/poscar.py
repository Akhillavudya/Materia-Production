"""POSCAR writing from a pymatgen Structure."""

from pathlib import Path


def write_poscar(structure, dest_dir: Path, name: str = "POSCAR") -> dict:
    """Write a Structure to ``POSCAR`` and ``POSCAR_{name}`` in `dest_dir`.

    Returns a summary dict (status, formula, n_sites, lattice params, paths).
    """
    from pymatgen.io.vasp import Poscar

    formula = structure.composition.reduced_formula
    poscar_path = dest_dir / "POSCAR"
    named_path = dest_dir / f"POSCAR_{name}"

    Poscar(structure).write_file(str(poscar_path))
    Poscar(structure).write_file(str(named_path))

    return {
        "status":        "success",
        "formula":       formula,
        "n_sites":       len(structure),
        "lattice_a":     round(structure.lattice.a, 4),
        "lattice_b":     round(structure.lattice.b, 4),
        "lattice_c":     round(structure.lattice.c, 4),
        "poscar_path":   str(poscar_path),
        "named_path":    str(named_path),
        "files_written": ["POSCAR", f"POSCAR_{name}"],
    }
