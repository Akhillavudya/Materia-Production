# Step 5.5 · Step 12 — Split `build_structure` into four tools + vacuum/supercell correctness

**Date:** 2026-06-22
**Status:** ✅ Done (local; not yet rebuilt into the Docker image)

> This step supersedes the design in `step4`/`step5`/`step7`, which described a single
> combined `build_structure` tool with an `operation` argument. Those docs are kept as the
> historical record; this one describes the current code.

---

## What changed (one line)
The one combined `build_structure(operation=…)` tool became **four dedicated tools** —
`make_supercell`, `add_vacuum`, `make_slab`, `convert_structure` — and two long-standing
correctness bugs in vacuum and supercell creation were fixed.

---

## 1. Why split one tool into four

The old tool was a *god tool*: a single entry point that secretly did four unrelated jobs,
picked by a string `operation`. That forced three kinds of waste:

1. **Schema noise** — when the model wanted a supercell it still saw `miller`, `min_slab_size`,
   `to_format`, etc., each tagged `[make_slab]`/`[convert]` so it would know which to ignore. The
   tool even returned "you passed a param that doesn't apply" warnings at runtime.
2. **Runtime branching** — an `if op == …` dispatch inside the adapter.
3. **Weaker tool selection** — `build_structure(operation="make_slab")` is a softer signal to the
   LLM than a tool literally named `make_slab`.

**Now:** each tool exposes only its own parameters, so misuse is impossible *by construction* (the
schema won't let the model pass a slab parameter to a supercell call). The shared concern —
resolve a structure → atom-cap check → write the active POSCAR — is factored into two helpers
(`_resolve_build_input`, `_finish_build`), so there is no copy-paste across the four tools.

**Beginner analogy:** we replaced one Swiss-army knife (where you had to tell it "be a screwdriver
now") with four labelled tools in a drawer. You grab the screwdriver because it *is* a screwdriver.

`convert_structure` stays special: like the old `convert` operation it writes a file in another
format and does **not** overwrite the active POSCAR.

---

## 2. Bug fix — vacuum was the wrong amount and couldn't go "on top only"

**Symptom (user complaint):** asking for *N* Å of vacuum on the **upper** side of a slab didn't
work, and the vacuum that *was* added didn't match the requested amount.

**Root cause:** the old `add_vacuum` simply **lengthened the lattice vector by `thickness`**. So:
- The *cell* grew by `thickness`, but the **gap to the next periodic image** = (whatever empty
  space the cell already had) + `thickness`. On a slab with 3.5 Å of existing padding, asking for
  10 Å produced a **13.5 Å** gap.
- "Top only" was impossible. `center=True` split the vacuum on both sides; `center=False` just kept
  the atoms wherever they were, so any pre-existing offset stayed below them.

**Fix:** `add_vacuum` now measures how far the atoms actually extend along the axis (`span`) and
resizes the cell to `span + thickness`, so the inter-image gap is **exactly `thickness`**,
independent of existing padding. The old `center: bool` is replaced by `side`:

| `side`   | result |
|----------|--------|
| `both` (default) | slab centred — `thickness`/2 of vacuum on each side |
| `top`    | slab flush to the bottom — **all** `thickness` Å of vacuum above |
| `bottom` | slab flush to the top — all `thickness` Å of vacuum below |

Verified: for a slab spanning 1.5 Å, `thickness=10` gives cell = 11.5 Å and an inter-image gap of
exactly 10.000 Å for every `side` (top → 10 above / 0 below, bottom → 0 above / 10 below, both →
5 / 5).

> **Caveat (documented in the code):** `add_vacuum` is for slabs / 2D layers / molecules. It is not
> meant for bulk crystals, which fill their cell and should not have a vacuum gap inserted.

---

## 3. Bug fix — supercell "varieties" were incomplete

**Symptom:** uniform (`"2"`) and per-axis (`"2 2 1"`) supercells worked, but a **3×3
transformation matrix** — needed for non-diagonal / rotated cells such as a √3×√3 surface cell —
was rejected with "supercell scaling factors must be >= 1".

**Fix:** `_parse_scaling` now accepts all three varieties:

| input | meaning |
|-------|---------|
| `"2"` | uniform 2×2×2 |
| `"2 2 1"` | per-axis |
| `"2 0 0 0 2 0 0 0 1"` (9 numbers) | full 3×3 matrix (rotated/non-diagonal) |

A singular or negative-determinant matrix is rejected with a clear message. The pre-build atom-cap
check was unified through a new `builder.supercell_multiplier()` (factor³ / nx·ny·nz / |det|) so the
predicted atom count always matches what `make_supercell` actually produces — including the matrix
case, which the old predictor couldn't size at all.

---

## Files touched
- `app/services/structure/builder.py` — rewrote `_parse_scaling` (+ matrix), added
  `supercell_multiplier`, rewrote `add_vacuum` (exact gap + `side`).
- `app/tools/material_tools.py` — replaced `build_structure` with `make_supercell` / `add_vacuum` /
  `make_slab` / `convert_structure` + shared `_finish_build`; cap predictor now delegates to
  `supercell_multiplier`.
- `app/tools/contracts.py` — `BuildStructureInput` → `MakeSupercellInput` / `AddVacuumInput` /
  `MakeSlabInput` / `ConvertStructureInput` (shared `_StructureSourceInput` base).
- `app/agent/tool_schemas.py`, `app/agent/tool_registry.py`, `app/agent/graph.py` — register the four
  tools; updated descriptions and the system-prompt tool list.
- `frontend/src/features/chat/ToolStatus.jsx` — friendly labels for the four tools.

## Verification
- Imports clean; `app.main` imports OK; 16 model-facing tools registered, no `build_structure` refs left.
- Supercell: `"2"`, `"2 2 1"`, `"3 1 1"`, `"2 0 0 0 2 0 0 0 1"`, `"1 1 0 -1 1 0 0 0 1"` all build with
  the right atom counts; singular matrix rejected; cap predictor matches reality.
- Vacuum: inter-image gap = requested thickness for `both`/`top`/`bottom`; bad `side` rejected.
- End-to-end through a real session: all four tools write the active POSCAR / convert correctly.

## Still pending
- Rebuild the Docker image and smoke-test in-image (same as the Step 11 gate).
