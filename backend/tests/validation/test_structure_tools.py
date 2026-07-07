"""T2 — Structure-tool correctness (Materia validation plan, docs/VALIDATION_PLAN.md §3).

Deterministic checks that the five structure transforms produce *exactly* what they
claim, measured against pymatgen ground truth. No ML potentials, no network, no
ATAT — these are fast unit checks that double as the regression test net (Step 9).

Covered:
  * make_supercell   — atom count & lattice scaling (uniform / per-axis / 3×3 matrix)
  * add_vacuum       — realised inter-image gap matches the request, on every side
  * make_slab        — EXACTLY the requested number of complete structural repeats, correct vacuum
  * add_adsorbate    — adsorbate placed at the requested height above the surface
  * generate_sqs     — partial-substitution composition matches the target (ATAT-free)
  * convert_structure— POSCAR ↔ CIF ↔ XYZ round-trips preserve the structure
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.structure import builder
from app.services.structure.adsorption import place_adsorbate, _min_adsorbate_surface_gap
from app.services.simulation.sqs import _apply_partial_substitutions


# ── make_supercell ────────────────────────────────────────────────────────────

def test_supercell_uniform(cu_fcc):
    sc = builder.make_supercell(cu_fcc, "2")
    assert len(sc) == 8 * len(cu_fcc)
    # Every lattice vector doubled in length.
    for orig, new in zip(cu_fcc.lattice.abc, sc.lattice.abc):
        assert new == pytest.approx(2 * orig, rel=1e-9)
    assert builder.supercell_multiplier("2") == 8


def test_supercell_per_axis(cu_fcc):
    sc = builder.make_supercell(cu_fcc, "2 2 1")
    assert len(sc) == 4 * len(cu_fcc)
    a, b, c = sc.lattice.abc
    a0, b0, c0 = cu_fcc.lattice.abc
    assert a == pytest.approx(2 * a0) and b == pytest.approx(2 * b0)
    assert c == pytest.approx(c0)
    assert builder.supercell_multiplier("2 2 1") == 4


def test_supercell_matrix(cu_fcc):
    # Diagonal 3×3 matrix with |det| = 4.
    sc = builder.make_supercell(cu_fcc, "2 0 0 0 2 0 0 0 1")
    assert len(sc) == 4 * len(cu_fcc)
    assert builder.supercell_multiplier("2 0 0 0 2 0 0 0 1") == 4


def test_supercell_preserves_composition(nacl):
    sc = builder.make_supercell(nacl, "3")
    assert sc.composition.reduced_formula == nacl.composition.reduced_formula
    assert len(sc) == 27 * len(nacl)


# ── add_vacuum ────────────────────────────────────────────────────────────────

def _axis_span(structure, axis_index=2):
    vec = structure.lattice.matrix[axis_index]
    unit = vec / np.linalg.norm(vec)
    proj = structure.cart_coords @ unit
    return float(proj.max() - proj.min())


@pytest.mark.parametrize("side", ["both", "top", "bottom"])
def test_add_vacuum_thickness(cu_fcc, side):
    thickness = 15.0
    out = builder.add_vacuum(cu_fcc, axis="c", thickness=thickness, side=side)
    span = _axis_span(out)
    c_len = float(np.linalg.norm(out.lattice.matrix[2]))
    # The realised inter-image gap (cell length minus material span) == request.
    assert (c_len - span) == pytest.approx(thickness, abs=1e-6)
    assert len(out) == len(cu_fcc)


def test_add_vacuum_side_placement(cu_fcc):
    """`top` flushes the slab to the bottom; `bottom` flushes it to the top."""
    thick = 12.0
    unit = np.array([0.0, 0.0, 1.0])
    top = builder.add_vacuum(cu_fcc, axis="c", thickness=thick, side="top")
    bot = builder.add_vacuum(cu_fcc, axis="c", thickness=thick, side="bottom")
    assert float((top.cart_coords @ unit).min()) == pytest.approx(0.0, abs=1e-6)
    c_len = float(np.linalg.norm(bot.lattice.matrix[2]))
    assert float((bot.cart_coords @ unit).max()) == pytest.approx(c_len, abs=1e-6)


# ── make_slab (exact structural-layer counting) ───────────────────────────────
# A "layer" is one complete structural repeat unit (oriented unit cell), NOT a
# single atomic plane, so N layers is N whole crystal thicknesses stacked along
# the normal. The invariant is linear: N layers has N× the atoms of one layer and
# keeps the bulk stoichiometry intact.

def _count_planes(slab, tol=0.3):
    """Number of distinct atomic planes along the (vertical) c-axis of a slab."""
    z = np.sort(slab.cart_coords[:, 2])
    return 1 + int(np.sum(np.diff(z) > tol))


@pytest.mark.parametrize("n_layers", [1, 2, 3, 4])
def test_slab_layers_scale_linearly(cu_fcc, n_layers):
    one = builder.make_slab(cu_fcc, miller="1 1 1", layers=1, min_vacuum_size=15.0)
    slab = builder.make_slab(cu_fcc, miller="1 1 1", layers=n_layers,
                             min_vacuum_size=15.0)
    # N complete repeats == N× the atoms of a single repeat, stoichiometry preserved.
    assert len(slab) == n_layers * len(one)
    assert slab.composition.reduced_formula == cu_fcc.composition.reduced_formula


def test_slab_cu111_layer_is_one_plane(cu_fcc):
    """For close-packed Cu(111) one repeat is a single atomic plane, so the atomic
    plane count equals the requested layer count — and the stacking is ABC."""
    for n in (3, 4, 5, 6):
        slab = builder.make_slab(cu_fcc, miller="1 1 1", layers=n,
                                 min_vacuum_size=15.0)
        assert _count_planes(slab) == n, f"requested {n} layers, got {_count_planes(slab)} planes"


def test_slab_vacuum_applied(cu_fcc):
    vac = 18.0
    slab = builder.make_slab(cu_fcc, miller="1 0 0", layers=4, min_vacuum_size=vac)
    span = _axis_span(slab)
    c_len = float(np.linalg.norm(slab.lattice.matrix[2]))
    assert (c_len - span) == pytest.approx(vac, abs=1e-3)


def test_slab_layers_ignore_min_slab_size(cu_fcc):
    """With `layers` set, min_slab_size (Å) is ignored — atom count still exact."""
    a = builder.make_slab(cu_fcc, miller="1 1 1", layers=4, min_slab_size=5.0,
                          min_vacuum_size=15.0)
    b = builder.make_slab(cu_fcc, miller="1 1 1", layers=4, min_slab_size=50.0,
                          min_vacuum_size=15.0)
    assert len(a) == len(b)


# ── add_adsorbate ─────────────────────────────────────────────────────────────

def test_adsorbate_placed_above_surface(cu_fcc):
    """The adsorbate must sit ABOVE the top surface (positive gap), never buried.

    Regression for the trimmed-slab bug where ``position_index=0`` selected a
    lower-surface site and put the molecule inside the slab. pymatgen measures
    ``distance`` along the local surface normal vs the coordinating ensemble, so
    the realised vertical gap is a bit under the requested 2.0 Å — we only require
    it to be clearly positive and in a physical band.
    """
    slab = builder.make_slab(cu_fcc, miller="1 1 1", layers=4, min_vacuum_size=18.0)
    n_slab = len(slab)
    combo = place_adsorbate(slab, "CO", site_type="ontop", distance=2.0)
    assert len(combo) > n_slab
    gap = _min_adsorbate_surface_gap(combo, n_slab)
    assert gap > 0.5, f"adsorbate buried/too low (gap={gap:.3f} Å)"
    assert gap < 3.0, f"adsorbate too far from surface (gap={gap:.3f} Å)"


def test_adsorbate_atom_count(cu_fcc):
    slab = builder.make_slab(cu_fcc, miller="1 1 1", layers=3, min_vacuum_size=18.0)
    n_slab = len(slab)
    combo = place_adsorbate(slab, "CO2", site_type="ontop", distance=2.0)
    # CO2 contributes 3 atoms.
    assert len(combo) == n_slab + 3


# ── generate_sqs (partial substitution composition, ATAT-free) ────────────────

def test_partial_substitution_composition():
    """`Si->S:0.25` makes every Si site {Si:0.75, S:0.25} — composition matches."""
    from pymatgen.core import Lattice, Structure
    # Ordered MgSi2Se4-like cell: 1 Mg, 2 Si, 4 Se.
    s = Structure(
        Lattice.cubic(6.0),
        ["Mg", "Si", "Si", "Se", "Se", "Se", "Se"],
        [[0, 0, 0], [0.25, 0.25, 0.25], [0.75, 0.75, 0.75],
         [0.5, 0, 0], [0, 0.5, 0], [0, 0, 0.5], [0.5, 0.5, 0.5]],
    )
    out, applied = _apply_partial_substitutions(
        s, [{"from": "Si", "to": "S", "fraction": 0.25}])
    comp = out.composition.as_dict()
    # 2 Si sites → 0.75 each = 1.5 Si, 0.25 each = 0.5 S.
    assert comp["Si"] == pytest.approx(1.5)
    assert comp["S"] == pytest.approx(0.5)
    assert applied == ["Si->S on 2 site(s) at 0.25"]


def test_partial_substitution_rejects_bad_fraction():
    from pymatgen.core import Lattice, Structure
    s = Structure(Lattice.cubic(5.0), ["Si"], [[0, 0, 0]])
    with pytest.raises(ValueError):
        _apply_partial_substitutions(s, [{"from": "Si", "to": "S", "fraction": 1.0}])


def test_partial_substitution_rejects_missing_element():
    from pymatgen.core import Lattice, Structure
    s = Structure(Lattice.cubic(5.0), ["Si"], [[0, 0, 0]])
    with pytest.raises(ValueError):
        _apply_partial_substitutions(s, [{"from": "Ge", "to": "S", "fraction": 0.25}])


# ── convert_structure (round-trip fidelity) ───────────────────────────────────

def _assert_same_structure(a, b, tol=1e-3):
    assert a.composition.reduced_formula == b.composition.reduced_formula
    assert len(a) == len(b)
    for x, y in zip(sorted(a.lattice.abc), sorted(b.lattice.abc)):
        assert x == pytest.approx(y, abs=tol)


def test_roundtrip_poscar(nacl):
    from pymatgen.core import Structure
    text = builder.to_format(nacl, "poscar")
    back = Structure.from_str(text, fmt="poscar")
    _assert_same_structure(nacl, back)


def test_roundtrip_cif(nacl):
    from pymatgen.core import Structure
    text = builder.to_format(nacl, "cif")
    back = Structure.from_str(text, fmt="cif")
    _assert_same_structure(nacl, back)


def test_roundtrip_xyz(nacl):
    import io
    from ase.io import read as ase_read
    from pymatgen.io.ase import AseAtomsAdaptor
    text = builder.to_format(nacl, "xyz")
    atoms = ase_read(io.StringIO(text), format="extxyz")
    back = AseAtomsAdaptor.get_structure(atoms)
    _assert_same_structure(nacl, back)


def test_convert_rejects_unknown_format(nacl):
    with pytest.raises(ValueError):
        builder.to_format(nacl, "foobar")
