"""Structure-building transforms (Step 5.5).

Pure functions: take a pymatgen ``Structure`` and return a new ``Structure`` (or
data). No session/file/HTTP concerns — those live in the adapter tools. Operations
are added incrementally: Step 4 = make_supercell.
"""

from __future__ import annotations

import numpy as np

_AXIS_INDEX = {"a": 0, "b": 1, "c": 2, "x": 0, "y": 1, "z": 2, "0": 0, "1": 1, "2": 2}


def _axis_index(axis) -> int:
    key = str(axis).lower().strip()
    if key not in _AXIS_INDEX:
        raise ValueError("axis must be one of a/b/c (or x/y/z).")
    return _AXIS_INDEX[key]


def _parse_scaling(scaling):
    """Parse a supercell spec into an int or a [nx, ny, nz] list.

    Accepts ``"2"`` / ``2`` (uniform) or ``"2 2 1"`` / ``"2,2,1"`` / a 3-list.
    Raises ``ValueError`` on anything else or on factors < 1.
    """
    if scaling is None:
        raise ValueError("scaling is required, e.g. '2 2 1' or '2'.")
    if isinstance(scaling, (list, tuple)):
        vals = [int(v) for v in scaling]
    else:
        vals = [int(x) for x in str(scaling).replace(",", " ").split()]

    if not vals:
        raise ValueError("scaling is empty; use e.g. '2 2 1' or '2'.")
    if any(v < 1 for v in vals):
        raise ValueError("supercell scaling factors must be >= 1.")
    if len(vals) == 1:
        return vals[0]
    if len(vals) == 3:
        return vals
    raise ValueError("scaling must be one integer or three (e.g. '2' or '2 2 1').")


def make_supercell(structure, scaling):
    """Return a supercell of `structure` replicated by `scaling` ('2 2 1' or '2')."""
    factor = _parse_scaling(scaling)
    s = structure.copy()
    s.make_supercell(factor)
    return s


def add_vacuum(structure, axis="c", thickness=15.0, center=True):
    """Extend the cell along `axis` by `thickness` Å of vacuum.

    Lengthens the chosen lattice vector (keeping its direction) while holding atoms
    at their Cartesian positions, so empty space opens up along that axis. When
    `center` is true the atoms are recentred within the enlarged cell — the usual
    choice for slabs and 2D layers.
    """
    from pymatgen.core import Lattice, Structure

    thickness = float(thickness)
    if thickness <= 0:
        raise ValueError("vacuum thickness must be > 0 Å.")
    i = _axis_index(axis)

    matrix = structure.lattice.matrix.copy()
    length = float(np.linalg.norm(matrix[i]))
    matrix[i] = matrix[i] / length * (length + thickness)
    new_lat = Lattice(matrix)

    new = Structure(new_lat, structure.species, structure.cart_coords,
                    coords_are_cartesian=True)
    if center:
        frac = new.frac_coords
        col = frac[:, i]
        frac[:, i] = col + (0.5 - (col.min() + col.max()) / 2.0)
        new = Structure(new_lat, new.species, frac)
    return new
