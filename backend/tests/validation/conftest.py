"""Pytest config for the validation suite.

Adds the backend root to ``sys.path`` so ``import app...`` resolves when pytest is
invoked from anywhere, and exposes a few shared pymatgen reference structures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# backend/ root = parents[2] of this file (tests/validation/conftest.py).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


@pytest.fixture
def cu_fcc():
    """Conventional FCC copper (4 atoms, a = 3.615 Å)."""
    from pymatgen.core import Lattice, Structure
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(3.615), ["Cu"], [[0, 0, 0]])


@pytest.fixture
def si_diamond():
    """Conventional diamond silicon (8 atoms, a = 5.43 Å)."""
    from pymatgen.core import Lattice, Structure
    return Structure.from_spacegroup(
        "Fd-3m", Lattice.cubic(5.43), ["Si"], [[0.125, 0.125, 0.125]])


@pytest.fixture
def nacl():
    """Conventional rocksalt NaCl (8 atoms, a = 5.64 Å)."""
    from pymatgen.core import Lattice, Structure
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"],
        [[0, 0, 0], [0.5, 0.5, 0.5]])
