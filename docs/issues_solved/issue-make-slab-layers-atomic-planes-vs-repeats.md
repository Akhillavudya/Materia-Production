# make_slab `layers` counted atomic planes instead of complete structural repeats

## Symptom
A PhD student pointed out that `make_slab(..., layers=N)` was producing the wrong
slab thickness. Asking for "N layers" gave N single **atomic planes**, whereas in
surface science "N layers" means N complete **structural repeat units** — one full
crystal thickness each. For a layered/compound material this is badly wrong: a
"3-layer MoS₂ slab" should be 3 whole S–Mo–S trilayers (9 atomic planes), but the
tool returned 3 lone atomic planes — a single, possibly bond-broken and
non-stoichiometric sandwich.

## Root cause
The `layers` branch over-generated a slab in pymatgen `in_unit_planes` mode and then
called `_enforce_layer_count`, which **trimmed the slab down to exactly N distinct
atomic planes** (grouping sites by height along the normal and dropping the excess).
That silently redefined a "layer" as a single atomic sheet. It happens to look right
for close-packed metals (Cu(111): one repeat *is* one atomic plane), which is why it
went unnoticed — but it breaks stoichiometry and bonded units for every compound.

## How we fixed it
Re-defined a layer as one complete oriented-unit-cell (OUC) repeat and build the slab
by **stacking that repeat N times**, so stoichiometry and bonded units always stay
intact:

1. Ask `SlabGenerator` (unit-plane mode) for the `oriented_unit_cell` — one full
   periodic repeat perpendicular to the Miller plane.
2. Apply the `shift` termination by translating the OUC along c.
3. `make_supercell([[1,0,0],[0,1,0],[0,0,N]])` — stack N complete repeats. Because the
   ABC glide is frozen into the OUC's tilted c-vector, the stacking sequence
   (e.g. ABCABC for FCC(111)) is reproduced automatically.
4. New helper `_slab_orientation` rotates a, b into the xy-plane and makes c vertical
   along the surface normal, so `add_vacuum` measures the gap perpendicular to the
   surface (a tilted c would have under-delivered the vacuum by `cos(tilt)`).
5. `add_vacuum` adds the real Å gap.

Deleted the now-dead `_enforce_layer_count`, `_plane_groups`, `_normal_unit`,
`_PLANE_TOL`. The Å-thickness path (no `layers`) is unchanged.

## Files changed
- `backend/app/services/structure/builder.py` — rewrote the `layers` branch to stack
  OUC repeats; added `_slab_orientation`; removed the atomic-plane-trimming helpers;
  updated `make_slab` docstring.
- `backend/app/tools/contracts.py`, `backend/app/agent/tool_schemas.py`,
  `backend/app/tools/material_tools.py` — `layers` now described as "complete
  structural repeat units," not "atomic planes," so the LLM picks it correctly.
- `backend/tests/validation/test_structure_tools.py` — replaced the
  atomic-plane-count assertions (and the removed `_plane_groups` usage) with the
  linear-scaling + stoichiometry invariant, plus a Cu(111) ABC-stacking plane check.

## How to verify
- `cd backend && python -m pytest tests/validation/test_structure_tools.py -q` (24 pass).
- Cu(111): `layers=N` → N atomic planes at the correct 2.087 Å spacing with proper
  ABC glide; each layer adds 4 atoms in the 2×2 surface cell.
- Rutile TiO₂(110): `layers=1/2/3` → Ti:O stays exactly 1:2 (6/12/18 atoms); before
  the fix a plane-trimmed slab would have been non-stoichiometric.
- All slabs come out with a, b in the xy-plane, c vertical, and the requested vacuum
  gap measured perpendicular to the surface.

## Lesson
"Layer" is ambiguous in materials science: for close-packed metals it reads as an
atomic plane, but the physically meaningful, material-agnostic definition is a
complete periodic repeat unit. When a parameter maps to a domain term with more than
one reading, pin the definition down (with the domain expert) before implementing —
and prefer the definition that preserves invariants (stoichiometry, intact bonded
units) across all material classes, not just the easy case.
