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


def _sc_matrix(supercell):
    """Parse a supercell spec into a diagonal matrix, or None for auto-sizing."""
    if not supercell:
        return None
    vals = [int(x) for x in str(supercell).replace(",", " ").split()]
    if len(vals) == 1:
        vals = vals * 3
    if len(vals) != 3 or any(v < 1 for v in vals):
        raise ValueError("supercell must be one or three positive integers, e.g. '2 2 2'.")
    return np.diag(vals)


def create_vacancy(structure, element=None, supercell=None):
    """Return a defective supercell with one `element` atom removed (a vacancy).

    Picks the first symmetry-distinct site of `element` (or any site if omitted).
    Returns (defect_structure, defect_name).
    """
    from pymatgen.analysis.defects.generators import VacancyGenerator

    rm = [element] if element else None
    defects = list(VacancyGenerator().generate(structure, rm_species=rm))
    if not defects:
        raise ValueError(f"no vacancy site found{f' for {element}' if element else ''}.")
    defect = defects[0]
    sc = defect.get_supercell_structure(sc_mat=_sc_matrix(supercell))
    return sc, getattr(defect, "name", "vacancy")


def create_substitution(structure, from_element, to_element, supercell=None):
    """Return a defective supercell with one `from_element` atom replaced by `to_element`."""
    from pymatgen.analysis.defects.generators import SubstitutionGenerator

    if not from_element or not to_element:
        raise ValueError("from_element and to_element are required.")
    defects = list(SubstitutionGenerator().generate(
        structure, substitution={from_element: [to_element]}))
    if not defects:
        raise ValueError(f"no '{from_element}' site found to substitute with '{to_element}'.")
    defect = defects[0]
    sc = defect.get_supercell_structure(sc_mat=_sc_matrix(supercell))
    return sc, getattr(defect, "name", "substitution")


def create_interstitial(structure, insert_element, supercell=None):
    """Return a defective supercell with `insert_element` added at a Voronoi interstitial site."""
    from pymatgen.analysis.defects.generators import VoronoiInterstitialGenerator

    if not insert_element:
        raise ValueError("insert_element is required.")
    defects = list(VoronoiInterstitialGenerator().generate(
        structure, insert_species=[insert_element]))
    if not defects:
        raise ValueError(f"no interstitial site found for '{insert_element}'.")
    defect = defects[0]
    sc = defect.get_supercell_structure(sc_mat=_sc_matrix(supercell))
    return sc, getattr(defect, "name", "interstitial")


def analyze_symmetry(structure, symprec=0.01) -> dict:
    """Return the space-group / point-group symmetry summary for `structure`."""
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    sga = SpacegroupAnalyzer(structure, symprec=float(symprec))
    n_prim = len(sga.find_primitive())
    return {
        "space_group_symbol":   sga.get_space_group_symbol(),
        "space_group_number":   sga.get_space_group_number(),
        "point_group":          sga.get_point_group_symbol(),
        "crystal_system":       sga.get_crystal_system(),
        "lattice_system":       sga.get_lattice_type(),
        "n_symmetry_ops":       len(sga.get_symmetry_operations()),
        "n_sites":              len(structure),
        "n_sites_primitive":    n_prim,
        "n_sites_conventional": len(sga.get_conventional_standard_structure()),
        "is_primitive":         n_prim == len(structure),
    }


def standard_structure(structure, kind="conventional", symprec=0.01):
    """Return the conventional or primitive standard cell of `structure`."""
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    sga = SpacegroupAnalyzer(structure, symprec=float(symprec))
    if kind == "primitive":
        return sga.get_primitive_standard_structure()
    return sga.get_conventional_standard_structure()


# Supported output formats for `convert` → file extension.
CONVERT_EXT = {"poscar": "vasp", "cif": "cif", "xyz": "xyz", "cssr": "cssr", "json": "json"}


def to_format(structure, fmt) -> str:
    """Serialize `structure` to the requested format string.

    Supported: poscar | cif | xyz | cssr | json. XYZ goes through ASE (pymatgen's
    native XYZ is molecule-oriented and drops the lattice).
    """
    key = (fmt or "").lower().strip()
    if key not in CONVERT_EXT:
        raise ValueError(f"unknown format '{fmt}'. Use: {', '.join(CONVERT_EXT)}.")
    if key == "xyz":
        # extXYZ uses line 2 for lattice/metadata, so we leave its comment alone.
        import io
        from ase.io import write as ase_write
        from pymatgen.io.ase import AseAtomsAdaptor
        buf = io.StringIO()
        ase_write(buf, AseAtomsAdaptor.get_atoms(structure), format="extxyz")
        return buf.getvalue()

    from datetime import date
    stamp = f"Generated by Materia {date.today().isoformat()}"
    if key == "poscar":
        from pymatgen.io.vasp import Poscar
        comment = f"{structure.composition.reduced_formula} — {stamp}"
        return str(Poscar(structure, comment=comment))
    if key == "cif":
        return f"# {stamp}\n" + structure.to(fmt="cif")
    return structure.to(fmt=key)


def _parse_miller(miller):
    """Parse a Miller index ('1 1 1' / '1,1,1' / [1,1,1]) into a 3-tuple."""
    if isinstance(miller, (list, tuple)):
        vals = [int(v) for v in miller]
    else:
        vals = [int(x) for x in str(miller).replace(",", " ").split()]
    if len(vals) != 3:
        raise ValueError("miller index must have 3 components, e.g. '1 1 1'.")
    if all(v == 0 for v in vals):
        raise ValueError("miller index cannot be (0 0 0).")
    return tuple(vals)


def _parse_scaling(scaling):
    """Parse a supercell spec into a scaling argument for ``make_supercell``.

    Accepts every common variety:
      - uniform:    ``"2"`` / ``2``                      → int (a 2×2×2 cell)
      - per-axis:   ``"2 2 1"`` / ``"2,2,1"`` / ``[2,2,1]`` → ``[nx, ny, nz]``
      - 3×3 matrix: ``"2 0 0 0 2 0 0 0 1"`` / nested 3×3  → ``[[…],[…],[…]]``
        (for non-diagonal / rotated supercells, e.g. a √3×√3 cell)

    Raises ``ValueError`` on anything else, on diagonal factors < 1, or on a
    singular / non-positive-determinant matrix.
    """
    if scaling is None:
        raise ValueError("scaling is required, e.g. '2 2 1' or '2'.")

    # Flatten to a flat list of ints (supports nested lists and string forms).
    if isinstance(scaling, (list, tuple)):
        vals: list[int] = []
        for v in scaling:
            if isinstance(v, (list, tuple)):
                vals.extend(int(x) for x in v)
            else:
                vals.append(int(v))
    else:
        vals = [int(x) for x in str(scaling).replace(",", " ").split()]

    if not vals:
        raise ValueError("scaling is empty; use e.g. '2 2 1' or '2'.")
    if len(vals) == 1:
        if vals[0] < 1:
            raise ValueError("supercell scaling factor must be >= 1.")
        return vals[0]
    if len(vals) == 3:
        if any(v < 1 for v in vals):
            raise ValueError("per-axis supercell factors must be >= 1.")
        return vals
    if len(vals) == 9:
        matrix = [vals[0:3], vals[3:6], vals[6:9]]
        det = round(float(np.linalg.det(np.array(matrix))))
        if det <= 0:
            raise ValueError(
                "a 3×3 supercell matrix must have a positive determinant "
                "(reorder the rows if it is negative).")
        return matrix
    raise ValueError(
        "scaling must be 1 integer ('2'), 3 integers ('2 2 1'), or 9 numbers "
        "for a 3×3 matrix ('2 0 0 0 2 0 0 0 1').")


def supercell_multiplier(scaling) -> int:
    """How many times the atom count grows for a given scaling spec.

    Uniform → factor³, per-axis → nx·ny·nz, 3×3 matrix → |determinant|. Shared by
    the pre-build atom-cap check so it matches what ``make_supercell`` will produce.
    """
    factor = _parse_scaling(scaling)
    if isinstance(factor, int):
        return factor ** 3
    arr = np.array(factor)
    if arr.ndim == 1:
        return int(arr[0] * arr[1] * arr[2])
    return int(round(abs(np.linalg.det(arr))))


def make_supercell(structure, scaling):
    """Return a supercell of `structure` for any `scaling` variety.

    `scaling` may be uniform ('2'), per-axis ('2 2 1') or a full 3×3 matrix
    ('2 0 0 0 2 0 0 0 1') — see ``_parse_scaling``.
    """
    factor = _parse_scaling(scaling)
    s = structure.copy()
    s.make_supercell(factor)
    return s


_VACUUM_SIDES = ("both", "top", "bottom")


def add_vacuum(structure, axis="c", thickness=15.0, side="both"):
    """Set the vacuum gap along `axis` to exactly `thickness` Å.

    Measures how far the atoms actually extend along the axis and resizes the cell
    so the gap to the next periodic image is exactly `thickness` Å — independent of
    any padding the input already had. This makes the vacuum match what the caller
    asked for rather than *adding* to whatever empty space happened to be there.

    `side` places the slab within the resized cell:
      - "both"   (default): centred, `thickness`/2 of vacuum on each side
      - "top"    : slab flush to the bottom, all `thickness` Å of vacuum above
      - "bottom" : slab flush to the top, all `thickness` Å of vacuum below

    Intended for slabs, 2D layers and molecules — not bulk crystals, which fill
    their cell and should not have a vacuum gap inserted.
    """
    from pymatgen.core import Lattice, Structure

    thickness = float(thickness)
    if thickness <= 0:
        raise ValueError("vacuum thickness must be > 0 Å.")
    s = str(side or "both").lower().strip()
    if s not in _VACUUM_SIDES:
        raise ValueError('side must be one of "both", "top" or "bottom".')
    i = _axis_index(axis)

    matrix = structure.lattice.matrix.copy()
    axis_vec = matrix[i]
    unit = axis_vec / float(np.linalg.norm(axis_vec))

    # Project atoms onto the axis direction; the material spans [proj_min, proj_max].
    proj = structure.cart_coords @ unit
    proj_min = float(proj.min())
    span = float(proj.max() - proj.min())

    # Resize the axis so the inter-image gap equals `thickness` exactly.
    matrix[i] = unit * (span + thickness)
    new_lat = Lattice(matrix)

    # Where the bottom-most atom should sit along the axis after the resize.
    target_min = {"both": thickness / 2.0, "top": 0.0, "bottom": thickness}[s]
    new_coords = structure.cart_coords + unit * (target_min - proj_min)

    return Structure(new_lat, structure.species, new_coords,
                     coords_are_cartesian=True)


def make_slab(structure, miller="1 1 1", min_slab_size=10.0, min_vacuum_size=15.0,
              center_slab=True, lll_reduce=True, shift=0.0):
    """Cut a surface slab from a bulk structure along a Miller plane.

    Uses pymatgen's ``SlabGenerator``, which **already adds the vacuum gap**
    (`min_vacuum_size`) — do not also call add_vacuum. Miller indices are defined
    against the conventional cell, so the bulk is converted to its conventional
    standard form first (falling back to the input if symmetry analysis fails).
    """
    from pymatgen.core.surface import SlabGenerator
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    hkl = _parse_miller(miller)
    if float(min_slab_size) <= 0 or float(min_vacuum_size) <= 0:
        raise ValueError("min_slab_size and min_vacuum_size must be > 0 Å.")

    try:
        conv = SpacegroupAnalyzer(structure).get_conventional_standard_structure()
    except Exception:  # noqa: BLE001 — degrade to the raw cell
        conv = structure

    sg = SlabGenerator(
        conv, hkl, float(min_slab_size), float(min_vacuum_size),
        lll_reduce=bool(lll_reduce), center_slab=bool(center_slab),
        primitive=True, reorient_lattice=True,
    )
    return sg.get_slab(shift=float(shift))
