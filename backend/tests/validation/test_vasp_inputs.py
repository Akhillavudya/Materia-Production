"""T3 — VASP input fidelity (Materia validation plan, docs/VALIDATION_PLAN.md §4).

Checks that generated INCAR / KPOINTS / POTCAR(.spec) are correct and internally
consistent, and where a ground truth exists, agree with pymatgen.

  * KPOINTS — k-point density per named accuracy level is monotonic and tracks the
    requested kppa; Γ-centred vs Monkhorst-Pack style honoured.
  * POTCAR  — element ordering matches POSCAR order; curated labels & ENCUT floor
    are correct. (Real POTCAR assembly needs the licensed PAW mount — skipped here.)
  * INCAR   — task presets, cell-relax ISIF map, magnetism auto-detection, DFT+U
    element ordering, and orthogonal modifiers (functional / vdW) are all correct.

The Materia ↔ MP POTCAR-label deviation analysis (a deliberate design choice, not a
bug) is recorded in docs/validation_results/T3_vasp_inputs.md.
"""

from __future__ import annotations

import re

import pytest

from app.services.vasp.kpoints import generate_kpoints_by_accuracy, ACCURACY_KPPA
from app.services.vasp.potcar import build_potcar_spec
from app.services.vasp.incar import generate_incar


# ── helpers ───────────────────────────────────────────────────────────────────

def _kmesh(text: str) -> list[int]:
    """Pull the 3-integer mesh line out of a KPOINTS string."""
    for line in text.splitlines():
        nums = re.findall(r"\d+", line)
        if len(nums) == 3 and "0  0  0" not in line:
            vals = [int(n) for n in nums]
            if all(v >= 1 for v in vals):
                return vals
    raise AssertionError(f"no mesh line found in:\n{text}")


def _parse_incar(text: str) -> dict:
    tags = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            tags[k.strip()] = v.strip()
    return tags


# ── KPOINTS density ───────────────────────────────────────────────────────────

def test_kpoints_density_monotonic(si_diamond):
    """Higher accuracy never yields fewer k-points; realised kppa tracks request."""
    n = len(si_diamond)
    totals = {}
    for level in ("Low", "Medium", "High"):
        text, kppa = generate_kpoints_by_accuracy(si_diamond, level)
        assert kppa == ACCURACY_KPPA[level]
        mesh = _kmesh(text)
        total_kpts = mesh[0] * mesh[1] * mesh[2]
        realised_kppa = total_kpts * n
        totals[level] = total_kpts
        # pymatgen rounds the mesh to a grid, so allow a generous band around request.
        assert 0.3 * kppa <= realised_kppa <= 3.0 * kppa, (
            f"{level}: realised kppa {realised_kppa} far from requested {kppa}")
    assert totals["Low"] <= totals["Medium"] <= totals["High"]


def test_kpoints_gamma_vs_monkhorst(si_diamond):
    g, _ = generate_kpoints_by_accuracy(si_diamond, "Medium", gamma_centered=True)
    m, _ = generate_kpoints_by_accuracy(si_diamond, "Medium", gamma_centered=False)
    assert "Gamma" in g
    assert "Monkhorst" in m


def test_kpoints_custom_requires_kppa(si_diamond):
    with pytest.raises(ValueError):
        generate_kpoints_by_accuracy(si_diamond, "Custom")
    text, kppa = generate_kpoints_by_accuracy(si_diamond, "Custom", custom_kppa=2000)
    assert kppa == 2000 and _kmesh(text)


def test_kpoints_invalid_level(si_diamond):
    with pytest.raises(ValueError):
        generate_kpoints_by_accuracy(si_diamond, "Ultra")


# ── POTCAR spec ───────────────────────────────────────────────────────────────

def test_potcar_element_order_matches_poscar(nacl):
    res = build_potcar_spec(nacl)
    assert [e.element for e in res.entries] == ["Na", "Cl"]
    assert [e.label for e in res.entries] == ["Na_pv", "Cl"]


def test_potcar_order_follows_first_appearance():
    from pymatgen.core import Lattice, Structure
    # Deliberately interleave species; POTCAR order = first appearance (O, Fe).
    s = Structure(Lattice.cubic(4.3), ["O", "Fe", "O", "Fe"],
                  [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0, 0], [0, 0.5, 0.5]])
    res = build_potcar_spec(s)
    assert [e.element for e in res.entries] == ["O", "Fe"]


def test_potcar_encut_floor(nacl):
    res = build_potcar_spec(nacl)
    # Na enmax 260, Cl enmax 262 → ceil(262 * 1.3) = 341.
    assert res.recommended_encut == 341


def test_potcar_unknown_element_degrades():
    from pymatgen.core import Lattice, Structure
    s = Structure(Lattice.cubic(5.0), ["Pu"], [[0, 0, 0]])
    res = build_potcar_spec(s)
    e = res.entries[0]
    assert e.element == "Pu" and e.label == "Pu" and e.known is False
    assert res.warnings


# ── INCAR task presets & cell-relax ISIF map ──────────────────────────────────

def test_incar_optimization(si_diamond):
    tags = _parse_incar(generate_incar(si_diamond, task="optimization"))
    assert tags["IBRION"] == "2"
    assert int(tags["NSW"]) > 0
    assert tags["EDIFFG"].startswith("-")
    assert tags["ENCUT"] == "520"
    assert tags["EDIFF"] == "1E-6"


def test_incar_static(si_diamond):
    tags = _parse_incar(generate_incar(si_diamond, task="static"))
    assert tags["IBRION"] == "-1"
    assert tags["NSW"] == "0"


@pytest.mark.parametrize("mode,isif", [("none", "2"), ("shape", "5"), ("full", "3")])
def test_incar_cell_relax_isif(si_diamond, mode, isif):
    tags = _parse_incar(generate_incar(si_diamond, task="optimization", cell_relax=mode))
    assert tags["ISIF"] == isif


def test_incar_unknown_task_raises(si_diamond):
    with pytest.raises(ValueError):
        generate_incar(si_diamond, task="nonsense")


# ── Magnetism auto-detection ──────────────────────────────────────────────────

def test_incar_magnetic_detection():
    from pymatgen.core import Lattice, Structure
    fe = Structure.from_spacegroup("Im-3m", Lattice.cubic(2.87), ["Fe"], [[0, 0, 0]])
    tags = _parse_incar(generate_incar(fe, task="static"))
    assert tags["ISPIN"] == "2"
    # One MAGMOM entry per site.
    assert len(tags["MAGMOM"].split()) == len(fe)


def test_incar_nonmagnetic_no_spin(si_diamond):
    tags = _parse_incar(generate_incar(si_diamond, task="static"))
    assert "ISPIN" not in tags
    assert "MAGMOM" not in tags


# ── DFT+U element ordering ─────────────────────────────────────────────────────

def test_incar_hubbard_u_ordering():
    from pymatgen.core import Lattice, Structure
    # Rocksalt FeO: POTCAR/element order = Fe, O.
    feo = Structure(Lattice.cubic(4.3), ["Fe", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    tags = _parse_incar(generate_incar(feo, task="static", hubbard_u=True))
    assert tags["LDAU"] == ".TRUE."
    assert tags["LMAXMIX"] == "4"
    # Fe has a curated U (5.3), O has none (-1 / 0).
    assert tags["LDAUL"].split() == ["2", "-1"]
    assert tags["LDAUU"].split()[0] == "5.3"
    assert tags["LDAUU"].split()[1] == "0"


# ── Orthogonal modifiers (functional / vdW) ───────────────────────────────────

def test_incar_scan_functional(si_diamond):
    tags = _parse_incar(generate_incar(si_diamond, task="static", functional="scan"))
    assert tags["METAGGA"] == "SCAN"


def test_incar_hse06_functional(si_diamond):
    tags = _parse_incar(generate_incar(si_diamond, task="static", functional="hse06"))
    assert tags["LHFCALC"] == ".TRUE."


def test_incar_vdw_d3(si_diamond):
    tags = _parse_incar(generate_incar(si_diamond, task="optimization", vdw="d3"))
    assert tags["IVDW"] == "11"


def test_incar_defaults_have_no_modifier_tags(si_diamond):
    """With no modifiers requested the INCAR carries none of their tags."""
    tags = _parse_incar(generate_incar(si_diamond, task="optimization"))
    for absent in ("METAGGA", "LHFCALC", "IVDW", "LDAU", "LSOL", "LSORBIT"):
        assert absent not in tags
