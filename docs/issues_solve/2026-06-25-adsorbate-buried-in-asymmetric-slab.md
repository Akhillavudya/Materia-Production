# Adsorbate buried inside an asymmetric slab (add_adsorbate)

**Date:** 2026-06-25
**Found by:** T2 structure-tool validation (`backend/tests/validation/test_structure_tools.py`)
**Area:** `backend/app/services/structure/adsorption.py` → `place_adsorbate`

## Symptom
`add_adsorbate` in geometric mode (`relax=False`, the default tool path) placed a CO
molecule's carbon atom at z ≈ 13.77 Å on a 4-layer Cu(111) slab whose top atom was at
z ≈ 14.42 Å. The adsorbate ended up **inside the slab** instead of above the surface.

## Root cause
1. `make_slab(..., layers=N)` over-generates planes then **trims excess planes from the
   top** (`_enforce_layer_count`) and returns a plain pymatgen `Structure` (via
   `add_vacuum`), not a `Slab`. The result is **asymmetric**: the top and bottom
   surfaces are no longer symmetry-equivalent.
2. On an asymmetric slab, `AdsorbateSiteFinder.find_adsorption_sites(symm_reduce=0.01)`
   returns inequivalent candidate sites on **both** the top and the bottom surface.
3. `place_adsorbate` selected `coords[position_index]` with `position_index=0`. The
   returned list is not height-ordered, so index 0 could be a lower/bottom-surface site
   → adsorbate buried.

(Confirmed a native pymatgen `Slab` collapses to a single top site under `symm_reduce`,
so the bug is specific to the trimmed plain-`Structure` slabs `make_slab` produces.)

## Fix
Sort the candidate site coordinates by their projection onto the c (out-of-plane)
normal, descending, before indexing. `position_index=0` is now always the **topmost**
site; higher indices walk downward. One-time geometric cost, no behaviour change for
already-correct symmetric slabs.

```python
c = slab.lattice.matrix[2]
normal = c / float(np.linalg.norm(c))
coords = sorted(coords, key=lambda p: float(np.asarray(p) @ normal), reverse=True)
idx = max(0, min(int(position_index), len(coords) - 1))
```

## Verify
`backend/tests/validation/test_structure_tools.py::test_adsorbate_placed_above_surface`
asserts the minimum adsorbate–surface gap is positive (0.5–3.0 Å band). Manual check:
CO atoms now at z = 15.58 / 16.24 Å above the 14.42 Å top (gap 1.155 Å), vs the buried
13.77 Å before. Full T2 suite: 23/23 pass.

## Lesson
A "distance above the surface" placement must pick the site by **height along the
surface normal**, never by list order — `find_adsorption_sites` does not guarantee
top-first ordering, and trimmed/asymmetric slabs expose both faces. Also note pymatgen's
`distance` is measured along the local normal against the coordinating ensemble, so the
realised vertical gap is smaller than the requested value even when correct.
