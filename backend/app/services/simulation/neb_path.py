"""
backend/app/services/simulation/neb_path.py
============================================
Build NEB migration endpoints from a **migrating atom**, instead of forcing the
user to hand-craft two endpoint files.

This generalizes the vacancy-mediated recipe from the PhD tester's notebook
(`/home/roy/Desktop/NEB.ipynb`):

  1. **Find migration sites** — symmetry-distinct sites of the migrating element,
     labelled 1..N (so the user can talk about "Mg1", "Mg5", ...).
  2. **List candidate hops** — every source→destination pair, sorted by distance,
     filtered by a cutoff (short hops are the physically relevant ones).
  3. **Build endpoints for a chosen hop (i → j)** — vacancy-mediated:
       - **initial** = remove the *destination* atom j  (vacancy at j, mobile atom
         still at i);
       - **final**  = take the initial structure and move the *source* atom i into
         j's position (vacancy now at i).
     The two states share the same atom count and box, exactly what NEB needs.

Nothing here runs a calculator — endpoint *relaxation* happens inside the NEB job
(neb.py). This module is pure pymatgen geometry, so it is cheap to call from a
lightweight `list_migration_paths` tool to preview hops before a long run.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Optional


@dataclass
class MigrationSite:
    label: int                 # 1-based, in structure atom order (like "Mg1".."MgN")
    index: int                 # index into structure[...] of this atom
    frac_coords: tuple         # fractional coordinates
    orbit: int                 # symmetry orbit id — atoms sharing it are equivalent


@dataclass
class MigrationPair:
    source_label: int
    dest_label: int
    distance_A: float


def _structure_from(path_or_structure):
    """Accept a path or a pymatgen Structure; return a Structure."""
    from pymatgen.core import Structure
    if isinstance(path_or_structure, Structure):
        return path_or_structure
    return Structure.from_file(str(path_or_structure))


def find_migration_sites(
    path_or_structure,
    element: str,
    symprec: float = 0.1,
) -> list[MigrationSite]:
    """Label EVERY ``element`` atom 1..N (structure order), tagged by symmetry orbit.

    Mirrors the notebook, which lists all migrating atoms (Mg1..Mg8) and hops
    between them — so a vacancy hop between two *symmetry-equivalent* sites is still
    a valid candidate. SpacegroupAnalyzer is used only to annotate which atoms are
    equivalent (the ``orbit`` field), not to drop any.
    """
    structure = _structure_from(path_or_structure)
    element = element.strip()

    # Map each atom index → an orbit id (atoms in the same orbit are equivalent).
    orbit_of: dict[int, int] = {}
    try:
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
        sga = SpacegroupAnalyzer(structure, symprec=symprec)
        symm = sga.get_symmetrized_structure()
        for orbit_id, indices in enumerate(symm.equivalent_indices):
            for idx in indices:
                orbit_of[int(idx)] = orbit_id
    except Exception:  # noqa: BLE001 — orbit annotation is a nicety, not required
        pass

    sites: list[MigrationSite] = []
    label = 0
    for i, site in enumerate(structure):
        if site.specie.symbol != element:
            continue
        label += 1
        sites.append(MigrationSite(
            label=label, index=i,
            frac_coords=tuple(round(float(x), 6) for x in site.frac_coords),
            orbit=orbit_of.get(i, -1)))
    return sites


def _element_indices(structure, element: str) -> list[int]:
    return [i for i, s in enumerate(structure) if s.specie.symbol == element]


def list_migration_pairs(
    path_or_structure,
    element: str,
    cutoff: float = 5.0,
    symprec: float = 0.1,
) -> list[MigrationPair]:
    """All source→dest hops of ``element`` within ``cutoff`` Å, sorted by distance.

    Pairs reference the 1..N labels from :func:`find_migration_sites` so they read
    like the notebook's "Mg1 → Mg5". Distances use the minimum-image convention via
    ``structure.get_distance``.
    """
    structure = _structure_from(path_or_structure)
    sites = find_migration_sites(structure, element, symprec=symprec)
    pairs: list[MigrationPair] = []
    for a, b in combinations(sites, 2):
        try:
            dist = float(structure.get_distance(a.index, b.index))
        except Exception:  # noqa: BLE001
            continue
        if cutoff and dist > cutoff:
            continue
        pairs.append(MigrationPair(a.label, b.label, round(dist, 4)))
    pairs.sort(key=lambda p: p.distance_A)
    return pairs


def build_migration_endpoints(
    path_or_structure,
    element: str,
    source_label: int,
    dest_label: int,
    symprec: float = 0.1,
):
    """Return ``(initial, final)`` pymatgen Structures for the hop source→dest.

    Vacancy-mediated (notebook recipe):
      - **initial**: copy of the input with the *destination* atom removed — the
        mobile atom sits at the source, the destination site is the vacancy.
      - **final**:   the initial structure with the *source* atom moved into the
        destination's (original) fractional position — the vacancy is now at the
        source. Same atoms, same box ⇒ a valid NEB pair.

    Raises ValueError on bad labels (so the tool can return a friendly message).
    """
    structure = _structure_from(path_or_structure)
    sites = find_migration_sites(structure, element, symprec=symprec)
    by_label = {s.label: s for s in sites}
    if source_label not in by_label or dest_label not in by_label:
        valid = ", ".join(str(s.label) for s in sites)
        raise ValueError(
            f"Invalid {element} site label(s): source={source_label}, "
            f"dest={dest_label}. Valid labels: {valid or '(none found)'}.")
    if source_label == dest_label:
        raise ValueError("Source and destination sites must differ.")

    src = by_label[source_label]
    dst = by_label[dest_label]
    dest_coords = structure[dst.index].frac_coords  # remember before any removal

    # initial: remove the destination atom (vacancy at destination).
    initial = structure.copy()
    initial.remove_sites([dst.index])

    # The source atom's index can shift when an earlier-indexed atom is removed.
    src_index_after = src.index - 1 if dst.index < src.index else src.index

    # final: move the source atom into the destination site.
    final = initial.copy()
    final.replace(src_index_after, element, coords=dest_coords,
                  coords_are_cartesian=False)
    return initial, final


def pairs_to_rows(pairs: list[MigrationPair]) -> list[dict]:
    """Serialize pairs for a tool/JSON response."""
    return [
        {"source": f"{p.source_label}", "dest": f"{p.dest_label}",
         "pair": f"{p.source_label}-{p.dest_label}", "distance_A": p.distance_A}
        for p in pairs
    ]
