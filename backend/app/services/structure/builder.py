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


def _resolve_count(count, available: int, label: str) -> int:
    """Turn a `count` spec (int, numeric string, ``None``, or "all") into a number.

    ``None`` → 1 (single defect, the common case). "all" → every matching site.
    Anything else must be a positive integer, and never more than `available`.
    """
    if count is None:
        n = 1
    elif isinstance(count, str) and count.strip().lower() == "all":
        n = available
    else:
        try:
            n = int(count)
        except (TypeError, ValueError):
            raise ValueError(f"count must be a positive integer or 'all', got {count!r}.")
    if n < 1:
        raise ValueError("count must be at least 1 (or 'all').")
    if n > available:
        raise ValueError(
            f"asked to act on {n} '{label}' atom(s) but only {available} present.")
    return n


def create_vacancy(structure, element=None, count=1):
    """Remove `count` atoms of `element` (or "all" of them) to make vacancies.

    Operates on the current cell — call make_supercell first for a dilute defect.
    `element` selects the species (defaults to any site); `count` is a number or
    "all". Removes the lowest-indexed matching sites. Returns (structure, name).
    """
    s = structure.copy()
    if element:
        idx = list(s.indices_from_symbol(element))
        if not idx:
            raise ValueError(f"no '{element}' atom found in the structure.")
    else:
        idx = list(range(len(s)))
    n = _resolve_count(count, len(idx), element or "atom")
    s.remove_sites(idx[:n])
    if len(s) == 0:
        raise ValueError("that would remove every atom — nothing would be left.")
    label = element or "atom"
    name = f"{n}x {label} vacancy" if n > 1 else f"{label} vacancy"
    return s, name


def create_substitution(structure, from_element, to_element, count=1):
    """Replace `count` `from_element` atoms with `to_element` (or "all" of them).

    Operates on the current cell. `count` is a number or "all"; the lowest-indexed
    matching sites are substituted. Returns (structure, name).
    """
    if not from_element or not to_element:
        raise ValueError("from_element and to_element are required.")
    s = structure.copy()
    idx = list(s.indices_from_symbol(from_element))
    if not idx:
        raise ValueError(f"no '{from_element}' atom found to substitute.")
    n = _resolve_count(count, len(idx), from_element)
    for i in idx[:n]:
        s.replace(i, to_element)
    name = (f"{n}x {from_element}->{to_element}" if n > 1
            else f"{from_element}->{to_element}")
    return s, name


def create_interstitial(structure, insert_element, count=1):
    """Insert `count` `insert_element` atom(s) at Voronoi interstitial sites.

    Operates on the current cell — call make_supercell first for a dilute defect.
    Distinct symmetry-inequivalent Voronoi sites are used (lowest-indexed first);
    `count` is a number or "all". Returns (structure, name).
    """
    from pymatgen.analysis.defects.generators import VoronoiInterstitialGenerator

    if not insert_element:
        raise ValueError("insert_element is required.")
    defects = list(VoronoiInterstitialGenerator().generate(
        structure, insert_species=[insert_element]))
    if not defects:
        raise ValueError(f"no interstitial site found for '{insert_element}'.")
    n = _resolve_count(count, len(defects), f"{insert_element} interstitial site")
    s = structure.copy()
    for defect in defects[:n]:
        s.append(insert_element, defect.site.frac_coords, coords_are_cartesian=False)
    name = (f"{n}x {insert_element} interstitial" if n > 1
            else f"{insert_element} interstitial")
    return s, name


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


# ── Structural-layer stacking (used when make_slab is given `layers`) ─────────
# In surface science an "N-layer slab" means N complete structural repeat units
# (oriented unit cells) stacked along the surface normal — one full "thickness"
# of the crystal — NOT N individual atomic planes. Trimming to atomic planes can
# split bonded units and break stoichiometry (a MoS2 layer is a whole S–Mo–S
# trilayer, so 3 layers = 3 trilayers = 9 planes, never 3 planes).


def _slab_orientation(struct):
    """Reorient a stacked slab so a, b lie in the xy-plane and c points straight
    up along the surface normal.

    The oriented unit cell has the two surface vectors as a, b and the (possibly
    tilted) stacking vector as c. We rotate a, b into the xy-plane, then make c
    vertical, so downstream tools (POSCAR export, the viewer, adsorbate placement)
    get the surface normal along c and add_vacuum measures the gap perpendicular
    to the surface rather than along a tilted c.
    """
    from pymatgen.core import Lattice, Structure

    matrix = struct.lattice.matrix
    e1 = matrix[0] / float(np.linalg.norm(matrix[0]))
    e2 = matrix[1] - (matrix[1] @ e1) * e1
    e2 /= float(np.linalg.norm(e2))
    e3 = np.cross(e1, e2)              # surface normal (right-handed with a, b)
    rot = np.array([e1, e2, e3])      # rows: new basis expressed in old coords

    new_matrix = matrix @ rot.T
    new_coords = struct.cart_coords @ rot.T
    new_matrix[2] = [0.0, 0.0, abs(new_matrix[2][2])]  # c straight up along normal

    slab = Structure(Lattice(new_matrix), struct.species, new_coords,
                     coords_are_cartesian=True)
    frac = slab.frac_coords
    frac[:, :2] %= 1.0                # wrap in-plane only; keep the slab intact along c
    return Structure(slab.lattice, slab.species, frac)


def make_slab(structure, miller="1 1 1", min_slab_size=10.0, min_vacuum_size=15.0,
              center_slab=True, lll_reduce=True, shift=0.0, layers=None):
    """Cut a surface slab from a bulk structure along a Miller plane.

    Uses pymatgen's ``SlabGenerator``, which **already adds the vacuum gap**
    (`min_vacuum_size`) — do not also call add_vacuum. Miller indices are defined
    against the conventional cell, so the bulk is converted to its conventional
    standard form first (falling back to the input if symmetry analysis fails).

    If ``layers`` is given, the slab is EXACTLY that many complete structural
    repeat units (oriented unit cells) stacked along the surface normal — one full
    "thickness" of the crystal per layer, so stoichiometry and bonded units stay
    intact (a MoS2 "3-layer" slab is 3 whole S–Mo–S trilayers). This is what users
    mean by "N-layer slab"; ``min_slab_size`` (a thickness in Å) is ignored in that
    case. Without ``layers`` the original Å-thickness behaviour is unchanged.
    """
    from pymatgen.core.surface import SlabGenerator
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    hkl = _parse_miller(miller)
    if float(min_vacuum_size) <= 0:
        raise ValueError("min_vacuum_size must be > 0 Å.")

    try:
        conv = SpacegroupAnalyzer(structure).get_conventional_standard_structure()
    except Exception:  # noqa: BLE001 — degrade to the raw cell
        conv = structure

    if layers is not None:
        n_layers = int(layers)
        if n_layers < 1:
            raise ValueError("layers must be a positive integer.")
        # Build ONE complete repeat (the oriented unit cell), apply the termination
        # shift, then stack it n_layers times along the normal — so N layers is N
        # whole structural units, not N atomic planes. lll_reduce is forced off: it
        # can tilt the c-vector off the surface normal and scramble the stacking
        # (lll_reduce is ignored when layers is set). The tiny vacuum here is a
        # placeholder; the real Å gap is added after reorientation.
        sg = SlabGenerator(
            conv, hkl, min_slab_size=1, min_vacuum_size=1,
            in_unit_planes=True, lll_reduce=False,
            center_slab=False, primitive=False, reorient_lattice=True,
        )
        repeat = sg.oriented_unit_cell.copy()
        if float(shift):
            frac = repeat.frac_coords
            frac[:, 2] = np.mod(frac[:, 2] + float(shift), 1.0)  # select termination
            repeat = repeat.__class__(repeat.lattice, repeat.species, frac)
        repeat.make_supercell([[1, 0, 0], [0, 1, 0], [0, 0, n_layers]])
        slab = _slab_orientation(repeat)
        side = "both" if center_slab else "top"
        return add_vacuum(slab, axis="c", thickness=float(min_vacuum_size), side=side)

    if float(min_slab_size) <= 0:
        raise ValueError("min_slab_size must be > 0 Å.")
    sg = SlabGenerator(
        conv, hkl, float(min_slab_size), float(min_vacuum_size),
        lll_reduce=bool(lll_reduce), center_slab=bool(center_slab),
        primitive=True, reorient_lattice=True,
    )
    return sg.get_slab(shift=float(shift))


def has_vacuum_gap(structure, min_gap: float = 5.0) -> bool:
    """True if the cell has a large empty gap along any axis — i.e. the structure is
    already a slab, 2D layer or molecule rather than a space-filling bulk crystal.

    Used to auto-detect whether add_adsorbate must build a slab first (bulk input)
    or can adsorb directly (the structure is already a surface).
    """
    if len(structure) < 2:
        return True
    for i in range(3):
        vec = structure.lattice.matrix[i]
        length = float(np.linalg.norm(vec))
        proj = np.sort(structure.cart_coords @ (vec / length))
        biggest = float(np.max(np.diff(proj)))                 # largest interior gap
        wrap = length - float(proj[-1] - proj[0])              # gap across the boundary
        if max(biggest, wrap) >= min_gap:
            return True
    return False
