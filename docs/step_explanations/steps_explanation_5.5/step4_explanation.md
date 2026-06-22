# Step 5.5 · Step 4 — `build_structure` tool + `make_supercell`

**Status:** ✅ Done
**Superseded 2026-06-22 (Step 12):** `build_structure` was split into four standalone tools;
`make_supercell` is now its own tool and also accepts a 3×3 transformation matrix. See
`step12_explanation.md`. This doc describes the original combined-tool design.

## Goal
Introduce the first structure-building tool, `build_structure`, with its first operation
**`make_supercell`** (replicate the unit cell). This also establishes the new `services/structure/`
service module and the combined-tool pattern that Steps 5–7 extend.

## Why a "supercell" matters (plain language)
A unit cell is the smallest repeating block of a crystal. Many calculations need a **bigger** box:
- **defects** — to stop a vacancy "seeing" its own periodic copies,
- **molecular dynamics** — to sample enough atoms,
- **phonons** — to capture longer-wavelength vibrations.

`make_supercell` tiles the cell, e.g. `"2 2 1"` doubles a-and-b (good for a thicker slab base) or `"2"`
makes a 2×2×2 block. It is, by design, the prerequisite for the defect tools in Step 9.

## The combined-tool pattern
`build_structure` takes an `operation` argument and dispatches to a builder function. Today only
`make_supercell` is wired; Steps 5–7 add `add_vacuum`, `make_slab`, `convert` behind the *same* tool.
All operations share one shape: **resolve a structure → transform → write the active POSCAR** so the
result chains straight into the next tool (optimize / MD / VASP / a further transform).

## What changed
- **`services/structure/__init__.py` + `builder.py`** *(new)* — pure `make_supercell(structure,
  scaling)` with a `_parse_scaling` helper (accepts `"2"`, `"2 2 1"`, `"2,2,1"`; rejects <1 / wrong arity).
- **`tools/material_tools.py`** — the `build_structure` adapter: validates `operation`, resolves the
  input (active session POSCAR by default, or `material_id`/`poscar_path`), **enforces the atom cap on
  the output**, writes `POSCAR` + `POSCAR_<formula>`.
- **`tools/contracts.py`** — `BuildStructureInput` (operation required + scaling/poscar/material args).
- **`agent/tool_registry.py` + `tool_schemas.py`** — registered the tool (3-spot pattern) with a
  description telling the agent when to use it.

## Verified
- Builder math: `"2 2 1"`→8, `"2"`→16, `"3,1,1"`→6 atoms (from a 2-atom Si cell); bad specs rejected. ✅
- Registration: present in `TOOL_NAMES` + `CALLABLE_TOOL_MAP`; schema props `[operation, scaling,
  poscar_path, material_id, source]`, `required=[operation]`. ✅
- End-to-end with a session: supercell wrote the active POSCAR; an oversized result hit the
  `max_atoms` cap with a friendly message. ✅
- Invalid `operation` rejected before any file access. ✅
