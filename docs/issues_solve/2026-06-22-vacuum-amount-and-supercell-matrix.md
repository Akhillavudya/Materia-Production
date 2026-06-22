# 2026-06-22 — Vacuum gap wrong, no "top only", and supercell matrix rejected

**Area:** structure builders (`app/services/structure/builder.py`, `app/tools/material_tools.py`)
**Trigger:** user/student complaints while preparing slabs and rotated supercells.
**Related:** full write-up in `docs/step_explanations/steps_explanation_5.5/step12_explanation.md`
(same change also split `build_structure` into four standalone tools).

---

## Symptom
1. Requesting vacuum **only on the upper side** of a slab didn't work.
2. The vacuum that *was* added **didn't equal the requested thickness** — a slab with existing
   padding asked for 10 Å and got ~13.5 Å.
3. A **3×3 transformation-matrix supercell** (e.g. for a √3×√3 cell) was rejected with
   "supercell scaling factors must be >= 1".

## Root cause
- `add_vacuum` lengthened the lattice vector by `thickness`, so the inter-image gap became
  *existing empty space* + `thickness`, not `thickness`. Side control was a `center` bool only:
  `True` split the gap, `False` left atoms wherever they sat (pre-existing offset stayed below).
- `_parse_scaling` accepted only 1 or 3 integers and applied a blanket `>= 1` check, so a
  9-number matrix never parsed. The atom-cap predictor used a *separate* parser that also couldn't
  size a matrix.

## Fix
- **Vacuum:** measure the atom span along the axis and resize the cell to `span + thickness`, so the
  inter-image gap is exactly `thickness`. Replace `center` with `side` ∈ {`both`, `top`, `bottom`}
  (centred / all vacuum above / all vacuum below). Documented as a slab/2D/molecule tool, not bulk.
- **Supercell:** `_parse_scaling` now accepts uniform / per-axis / **9-number 3×3 matrix**
  (rejecting singular or negative-determinant matrices). A new `builder.supercell_multiplier()`
  (factor³ / nx·ny·nz / |det|) is the single source of truth for the pre-build atom-cap check.

## Verify
- Vacuum inter-image gap = requested thickness for `both`/`top`/`bottom`; bad `side` rejected.
- Supercell builds for `"2"`, `"2 2 1"`, `"3 1 1"`, `"2 0 0 0 2 0 0 0 1"`, `"1 1 0 -1 1 0 0 0 1"`
  with correct atom counts; cap predictor matches actual counts; singular matrix rejected.
- End-to-end through a session: all four structure tools write/convert correctly; `app.main` imports.

## Lesson
"Add vacuum" is ambiguous — *grow the cell* vs *set the gap*. Users mean the **gap to the next
image**, so compute it from the atom span, never from the current cell length. And when a single
parser feeds a safety check (the atom cap), share it — two parsers drift and one silently skips the
case the other rejects.
