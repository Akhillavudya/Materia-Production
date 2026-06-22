# Step 5.5 · Step 5 — `add_vacuum` operation

**Status:** ✅ Done
**Superseded 2026-06-22 (Step 12):** `add_vacuum` is now a standalone tool, produces the *exact*
requested vacuum gap (not cell-length + thickness), and replaces `center` with `side`
(both/top/bottom). See `step12_explanation.md`. This doc describes the original behaviour.

## Goal
Add the second `build_structure` operation: **`add_vacuum`** — open up empty space along a chosen
axis so a surface or layer doesn't interact with its own periodic image.

## Why vacuum is needed (plain language)
VASP repeats the cell infinitely in all directions. For a **2D material** (graphene, MoS₂) or a
**slab/molecule**, that would stack copies right on top of each other. Adding ~15 Å of vacuum along
`c` isolates the layer so it behaves like a true free-standing surface. (Slabs made with
`make_slab` in Step 6 get vacuum built in — `add_vacuum` is for the other cases, or extra padding.)

## How it works
- Lengthens the chosen lattice vector (`axis` = a/b/c) by `thickness` Å, keeping its direction.
- Holds atoms at their **Cartesian** positions, so the new space is genuinely empty.
- `center=True` (default) recentres the atoms within the enlarged cell — symmetric vacuum on both
  sides, which is what slab/work-function calculations want.

Atom count never changes, so the atom cap is irrelevant here.

## What changed
- **`services/structure/builder.py`** — `add_vacuum(structure, axis, thickness, center)` + an
  `_axis_index` helper (accepts a/b/c or x/y/z); rejects thickness ≤ 0 and unknown axes.
- **`tools/material_tools.py`** — added `add_vacuum` to `_BUILD_OPERATIONS`, the dispatch branch, and
  the tool params (`axis`/`thickness`/`center`); the response now reports `lattice_abc` and an
  operation-aware message.
- **`tools/contracts.py`** — `axis`/`thickness`/`center` fields.
- **`agent/tool_schemas.py`** — description now lists `add_vacuum`.

## Verified
- `add_vacuum(c, 15)` on cubic Si → abc `[5.43, 5.43, 20.43]`, 2 atoms; `a`-axis works; atoms centred
  (midpoint ≈ 0.5). ✅
- thickness=0 and axis="q" rejected. ✅
- End-to-end: writes the active POSCAR; **chains** — a follow-up `make_supercell` read the vacuumed
  cell (2 → 8 atoms). ✅
- `axis`/`thickness`/`center` present in the agent schema. ✅
