"""Surface-slab construction pipeline (exact layer count + lateral supercell + vacuum).

The public entry point is :func:`build_slab`. It is a pure transform — it returns
a ``(Structure, metadata)`` pair and never touches the filesystem. File output is a
separate concern handled by :func:`export_slab`.

Why this module exists
----------------------
pymatgen's ``SlabGenerator`` sizes a slab by *thickness* (Å) or by *oriented-cell
repeats* (``in_unit_planes``), neither of which is the number of distinct atomic
planes a user means by "4 layers". That is exactly how a request for a 4-layer
Cu(100) slab silently produced 6. We instead over-generate the slab in unit-plane
mode and then **count the distinct atomic planes along the surface normal and trim
the excess from the top** until the count is exactly ``n_layers``. This is the
robust fix for the layer-count bug.

Pipeline (strict order)
------------------------
1. input pymatgen ``Structure``
2. standardise to the conventional cell (Miller indices are defined against it)
3. generate the slab with ``SlabGenerator`` in unit-plane mode (a tiny temporary
   vacuum; the real vacuum is added later)
4. enforce an exact atomic-layer count by plane-counting + trimming
5. apply the lateral supercell, asserting the c-vector is untouched
6. add vacuum (``symmetric`` or ``top_only``) reusing the exact-gap ``add_vacuum``
7. (centring is handled by ``add_vacuum``'s placement)
8. validate: contiguous slab (no clipping) + measured vacuum >= requested +
   atom count == base * sx * sy
9. assemble a provenance ``metadata`` dict
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.services.structure.builder import _parse_miller, add_vacuum, to_format
from app.services.vasp.poscar import write_poscar

# Two atoms are on the same atomic plane if their positions along the surface
# normal differ by less than this (Å). Atoms in one plane of a slab cut by
# SlabGenerator share an identical normal coordinate, so a tight tolerance is safe;
# it is generous enough to absorb floating-point noise but tight enough that
# genuinely distinct planes (interlayer spacings are typically > 1 Å) stay separate.
_PLANE_TOL = 0.10

_VACUUM_MODES = {"symmetric": "both", "top_only": "top"}


def _pymatgen_version() -> str:
    """Best-effort pymatgen version string for provenance (never raises)."""
    try:
        from importlib.metadata import version
        return version("pymatgen")
    except Exception:  # noqa: BLE001
        return "unknown"


def _parse_supercell_2d(supercell) -> tuple[int, int]:
    """Parse an in-plane supercell spec into ``(sx, sy)`` positive integers.

    Accepts ``(4, 4)``, ``"4 4"``, ``"4,4"``, ``"4"`` (→ 4×4) or ``"4 4 1"`` (the
    out-of-plane factor must be 1 — the slab thickness is set by ``n_layers``).
    """
    if isinstance(supercell, (list, tuple)):
        vals = [int(x) for x in supercell]
    else:
        vals = [int(x) for x in str(supercell).replace(",", " ").split()]
    if len(vals) == 1:
        vals = [vals[0], vals[0]]
    if len(vals) == 3:
        if vals[2] != 1:
            raise ValueError(
                "the out-of-plane supercell factor must be 1 — set the slab "
                "thickness with n_layers, not the supercell c-factor.")
        vals = vals[:2]
    if len(vals) != 2 or any(v < 1 for v in vals):
        raise ValueError("supercell must be 1 or 2 positive integers, e.g. '4 4'.")
    return vals[0], vals[1]


def _normal_unit(structure) -> np.ndarray:
    """Unit vector along the c (out-of-plane) lattice direction."""
    c = structure.lattice.matrix[2]
    return c / float(np.linalg.norm(c))


def _plane_groups(structure, tol: float = _PLANE_TOL) -> list[list[int]]:
    """Group site indices into atomic planes along the surface normal (bottom→top).

    Returns a list of planes; each plane is a list of site indices. Two sites are on
    the same plane when their projection onto the normal differs by < ``tol``.

    Wrap-aware: an atom sitting at the very top of the cell can be wrapped just past
    the periodic boundary and would otherwise be miscounted as a separate plane. We
    cut the periodic axis at its largest empty region (the vacuum) so the slab forms a
    single contiguous, monotonically increasing block before grouping.
    """
    unit = _normal_unit(structure)
    c_len = float(np.linalg.norm(structure.lattice.matrix[2]))
    proj = np.mod(structure.cart_coords @ unit, c_len)
    order = list(np.argsort(proj))
    if len(order) == 1:
        return [[int(order[0])]]

    sorted_proj = proj[order]
    gaps = list(np.diff(sorted_proj)) + [c_len - (sorted_proj[-1] - sorted_proj[0])]
    cut = int(np.argmax(gaps))  # largest empty region = vacuum; block starts after it
    start = (cut + 1) % len(order)
    rolled = order[start:] + order[:start]

    # Re-reference to the block's first atom so the sequence increases monotonically.
    base = proj[rolled[0]]
    pos = np.mod(proj[rolled] - base, c_len)
    groups: list[list[int]] = [[int(rolled[0])]]
    last = pos[0]
    for k in range(1, len(rolled)):
        if pos[k] - last <= tol:
            groups[-1].append(int(rolled[k]))
        else:
            groups.append([int(rolled[k])])
        last = pos[k]
    return groups


def _enforce_layer_count(slab, n_layers: int, tol: float = _PLANE_TOL):
    """Trim the slab to exactly ``n_layers`` distinct atomic planes (from the top).

    Raises if the generated slab has fewer planes than requested (caller should ask
    for a thicker slab — should not happen given unit-plane over-generation).
    """
    groups = _plane_groups(slab, tol)
    n_planes = len(groups)
    if n_planes < n_layers:
        raise ValueError(
            f"the generated slab has only {n_planes} atomic plane(s) but "
            f"{n_layers} were requested; try a smaller n_layers or a different "
            "Miller index.")
    if n_planes == n_layers:
        return slab
    # Remove the top-most (n_planes - n_layers) planes.
    drop: list[int] = []
    for grp in groups[n_layers:]:
        drop.extend(grp)
    slab = slab.copy()
    slab.remove_sites(sorted(drop))
    return slab


def _validate_slab(structure, requested_vacuum: float, tol: float = 0.1) -> float:
    """Validate placement and return the measured vacuum gap (Å).

    Implements the spec's intent — catch clipping bugs and confirm the real vacuum —
    in a mode-agnostic way by analysing the empty regions along the surface normal:

    * the largest empty region is the vacuum gap; it must be >= ``requested_vacuum``
      (measured directly, not trusted from the parameter);
    * the slab must be a single contiguous block — if a *second* comparably large
      gap exists, the slab has been split/wrapped across the periodic boundary
      (an atom clipped to the far face), which we reject.
    """
    unit = _normal_unit(structure)
    c_len = float(np.linalg.norm(structure.lattice.matrix[2]))
    proj = np.sort(structure.cart_coords @ unit)
    if len(proj) < 2:
        return c_len  # single atom — nothing to validate

    diffs = np.diff(proj).tolist()
    wrap_gap = c_len - (proj[-1] - proj[0])  # empty region across the cell boundary
    gaps = sorted(diffs + [wrap_gap])
    vacuum_gap = gaps[-1]
    second_gap = gaps[-2]

    if vacuum_gap + 1e-6 < requested_vacuum:
        raise ValueError(
            f"measured vacuum gap is {vacuum_gap:.2f} Å, below the requested "
            f"{requested_vacuum:.2f} Å.")
    if second_gap > 0.5 * vacuum_gap:
        raise ValueError(
            "the slab is not contiguous along the surface normal — an atom appears "
            "clipped/wrapped across the cell boundary.")
    return float(vacuum_gap)


def build_slab(
    structure,
    miller_index,
    n_layers: int,
    supercell=(4, 4),
    vacuum_angstrom: float = 20.0,
    vacuum_mode: str = "symmetric",
    source_label: str | None = None,
    plane_tol: float = _PLANE_TOL,
):
    """Build a surface slab with an EXACT atomic-layer count.

    Args:
        structure:        bulk pymatgen ``Structure`` to cut.
        miller_index:     Miller index, e.g. ``"1 0 0"``, ``"1,1,1"`` or ``(1, 1, 1)``.
        n_layers:         exact number of distinct atomic planes along the normal.
        supercell:        in-plane replication, e.g. ``(4, 4)`` or ``"2 2"`` (c stays 1).
        vacuum_angstrom:  total vacuum gap to add along c (Å).
        vacuum_mode:      ``"symmetric"`` (split above/below, slab centred) or
                          ``"top_only"`` (all vacuum above, slab flush at the bottom).
        source_label:     optional provenance string (e.g. an mp-id) for metadata.
        plane_tol:        normal-axis tolerance for grouping atoms into a plane (Å).

    Returns:
        ``(slab_structure, metadata)``. No files are written — call
        :func:`export_slab` for that.
    """
    from pymatgen.core.surface import SlabGenerator
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    hkl = _parse_miller(miller_index)
    n_layers = int(n_layers)
    if n_layers < 1:
        raise ValueError("n_layers must be >= 1.")
    sx, sy = _parse_supercell_2d(supercell)
    mode = str(vacuum_mode or "symmetric").lower().strip()
    if mode not in _VACUUM_MODES:
        raise ValueError('vacuum_mode must be "symmetric" or "top_only".')
    vac = float(vacuum_angstrom)
    if vac <= 0:
        raise ValueError("vacuum_angstrom must be > 0.")

    # 2. Conventional cell (Miller indices are defined against it).
    try:
        conv = SpacegroupAnalyzer(structure).get_conventional_standard_structure()
    except Exception:  # noqa: BLE001 — degrade to the raw cell
        conv = structure

    # 3. Over-generate the slab in unit-plane mode. min_slab_size counts oriented-cell
    #    repeats here (>= n_layers atomic planes); the real vacuum is added in step 6,
    #    so only a tiny placeholder gap is requested now. primitive=False keeps the
    #    conventional surface mesh the lateral supercell expects.
    sg = SlabGenerator(
        conv, hkl, min_slab_size=n_layers, min_vacuum_size=1.0,
        in_unit_planes=True, lll_reduce=False, center_slab=False,
        primitive=False, reorient_lattice=True,
    )
    slab = sg.get_slab()

    # 4. Exact atomic-layer count via plane-counting + trim.
    slab = _enforce_layer_count(slab, n_layers, plane_tol)
    base_atoms = len(slab)
    atoms_per_layer = base_atoms / n_layers

    # 5. Lateral supercell — c-vector must be untouched.
    c_before = slab.lattice.matrix[2].copy()
    sc_matrix = [[sx, 0, 0], [0, sy, 0], [0, 0, 1]]
    slab = slab.copy()
    slab.make_supercell(sc_matrix)
    if not np.allclose(slab.lattice.matrix[2], c_before, atol=1e-6):
        raise AssertionError(
            "lateral supercell altered the c-vector "
            f"({c_before} → {slab.lattice.matrix[2]}); refusing to proceed.")

    # 6/7. Add vacuum (exact gap; symmetric centres the slab, top_only puts it at the bottom).
    slab = add_vacuum(slab, axis="c", thickness=vac, side=_VACUUM_MODES[mode])

    # 8. Validate placement and measure the real vacuum gap.
    measured_vacuum = _validate_slab(slab, vac)
    expected_atoms = base_atoms * sx * sy
    if len(slab) != expected_atoms:
        raise ValueError(
            f"atom-count check failed: got {len(slab)}, expected "
            f"{expected_atoms} ({base_atoms} base × {sx}×{sy} supercell).")

    # 9. Provenance metadata.
    metadata = {
        "source": source_label,
        "miller_index": list(hkl),
        "n_layers": n_layers,
        "atoms_per_layer": round(atoms_per_layer, 3),
        "supercell_matrix": sc_matrix,
        "vacuum_mode": mode,
        "vacuum_angstrom": vac,
        "measured_vacuum_angstrom": round(measured_vacuum, 3),
        "n_atoms": len(slab),
        "formula": slab.composition.reduced_formula,
        "lattice_abc": [round(x, 4) for x in slab.lattice.abc],
        "pymatgen_version": _pymatgen_version(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return slab, metadata


def export_slab(structure, metadata: dict, dest_dir, name: str | None = None) -> dict:
    """Write the slab as POSCAR + CIF + a sidecar provenance JSON.

    Returns ``{"files_written": [...], "poscar_path": ...}``. This is the only
    function in the module with filesystem side effects.
    """
    dest = Path(dest_dir)
    formula = structure.composition.reduced_formula
    base = name or formula
    hkl = "".join(str(i) for i in metadata.get("miller_index", []))
    tag = f"slab{hkl}_{metadata.get('n_layers', '')}L"

    wp = write_poscar(structure, dest, name=base, tag=tag)
    files = list(wp["files_written"])

    cif_name = f"{base}_{tag}.cif"
    (dest / cif_name).write_text(to_format(structure, "cif"))
    files.append(cif_name)

    json_name = f"{base}_{tag}_slab.json"
    (dest / json_name).write_text(json.dumps(metadata, indent=2))
    files.append(json_name)

    return {"files_written": files, "poscar_path": wp["poscar_path"]}
