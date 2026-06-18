# Step 5.5 · Step 6 — `make_slab` operation

**Status:** ✅ Done

## Goal
Add the `make_slab` operation: **cut a surface** from a bulk crystal along a Miller plane — the
starting point for any surface, catalysis, adsorption, or work-function study.

## What a slab is (plain language)
A bulk crystal repeats forever. To study a **surface** you slice the crystal along a chosen plane —
specified by a **Miller index** like (1 1 1) or (1 0 0) — keeping a few atomic layers thick (`min_slab_size`)
and adding a **vacuum gap** (`min_vacuum_size`) above it so the surface doesn't see its periodic copy.
The `shift` parameter picks *which* atomic termination the cut exposes.

## Key behaviours
- Uses pymatgen's **`SlabGenerator`** — battle-tested crystallography, not hand-rolled.
- **Vacuum is built in** (`min_vacuum_size`), so users must NOT also call `add_vacuum`. Both the tool
  description and this doc say so, to stop the agent double-adding vacuum.
- Miller indices are defined against the **conventional cell**, so the bulk is converted to its
  conventional standard form first (graceful fallback if symmetry analysis fails).
- The slab output is subject to the **atom cap** (slabs can be large).

## What changed
- **`services/structure/builder.py`** — `make_slab(structure, miller, min_slab_size,
  min_vacuum_size, center_slab, lll_reduce, shift)` + a `_parse_miller` helper (rejects non-3-component
  and (0 0 0) indices, and non-positive sizes).
- **`tools/material_tools.py`** — `make_slab` in `_BUILD_OPERATIONS`, the dispatch branch, the slab
  params, and a slab-specific result message. (`center` is shared with add_vacuum as `center_slab`.)
- **`tools/contracts.py`** — `miller`/`min_slab_size`/`min_vacuum_size`/`lll_reduce`/`shift` fields.
- **`agent/tool_schemas.py`** — description now lists make_slab and the "don't also add_vacuum" note.

## Verified
- (1 1 1) slab from Si → 18-atom `Slab`, c = 29.2 Å (slab + vacuum); (1 0 0) → 12 atoms, c = 26.6 Å. ✅
- Bad Miller ("1 1", "0 0 0") and `min_vacuum_size=0` rejected. ✅
- End-to-end: writes the active POSCAR with a descriptive message; all slab params in the schema. ✅
