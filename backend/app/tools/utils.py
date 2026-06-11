"""
backend/app/tools/utils.py
============================
Shared utilities for Materia tool functions.
"""

import os
from contextvars import ContextVar
from pathlib import Path

# Per-coroutine session dir — safe under concurrent async requests.
# agent.py sets this via a ContextVar.set() token before each tool call.
_session_dir_var: ContextVar[str] = ContextVar("session_dir", default="")


def session_dir() -> Path:
    """Resolve the current request's session storage directory."""
    d = _session_dir_var.get()
    if d:
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path.cwd()


def write_poscar(structure, dest_dir: Path, name: str = "POSCAR") -> dict:
    """
    Write a pymatgen Structure to POSCAR and POSCAR_{name} in dest_dir.

    Returns a dict with status, formula, n_sites, lattice params,
    and file paths — matches the tool result schema.
    """
    from pymatgen.io.vasp import Poscar

    formula     = structure.composition.reduced_formula
    poscar_path = dest_dir / "POSCAR"
    named_path  = dest_dir / f"POSCAR_{name}"

    Poscar(structure).write_file(str(poscar_path))
    Poscar(structure).write_file(str(named_path))

    return {
        "status":       "success",
        "formula":      formula,
        "n_sites":      len(structure),
        "lattice_a":    round(structure.lattice.a, 4),
        "lattice_b":    round(structure.lattice.b, 4),
        "lattice_c":    round(structure.lattice.c, 4),
        "poscar_path":  str(poscar_path),
        "named_path":   str(named_path),
        "files_written": ["POSCAR", f"POSCAR_{name}"],
    }