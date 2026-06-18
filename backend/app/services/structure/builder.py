"""Structure-building transforms (Step 5.5).

Pure functions: take a pymatgen ``Structure`` and return a new ``Structure`` (or
data). No session/file/HTTP concerns — those live in the adapter tools. Operations
are added incrementally: Step 4 = make_supercell.
"""

from __future__ import annotations


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
