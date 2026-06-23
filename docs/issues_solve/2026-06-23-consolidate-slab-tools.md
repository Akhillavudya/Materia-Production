# 2026-06-23 — Consolidate slab tools (drop build_slab, keep make_slab)

## Symptom / request
The codebase had **two** slab tools doing overlapping things:
- `make_slab` — cut an (hkl) slab, exact `layers` param, vacuum included.
- `build_slab` — bundled exact layers **+** in-plane supercell **+** vacuum, and also
  wrote a CIF + provenance-JSON sidecar.

`build_slab` had been added when a general notebook flow was pasted in, but the user
did not actually want a separate bundled tool: supercell and vacuum already have their
own tools (`make_supercell`, `add_vacuum`). Two tools for one job confused the agent's
tool selection and duplicated logic.

## Decision (confirmed with user)
- **Keep `make_slab`** as the single slab tool (exact `layers` + included vacuum).
- **Delete `build_slab`** entirely.
- In-plane supercell → `make_supercell`; precise vacuum → `add_vacuum`. "All other
  things in their respective tool."
- **POSCAR only** — drop build_slab's CIF + provenance-JSON outputs.

## Changes
- **`services/structure/builder.py`** — moved the exact-layer-count helpers
  (`_PLANE_TOL`, `_normal_unit`, `_plane_groups`, `_enforce_layer_count`) IN from the
  deleted module so `make_slab(layers=…)` is self-contained. (make_slab already used
  them via a lazy import.)
- **Deleted `services/structure/slab_builder.py`** — its only live consumer was the
  helper import above; `build_slab`/`export_slab`/`_validate_slab`/`_parse_supercell_2d`
  were now dead.
- **`tools/material_tools.py`** — removed the `build_slab` tool fn; updated `make_slab`
  and `add_adsorbate` docstrings to point at make_supercell/add_vacuum.
- **`tools/contracts.py`** — removed `BuildSlabInput`.
- **`agent/tool_registry.py`**, **`agent/tool_schemas.py`** — removed the import,
  schema text, and registry entries; rewrote make_slab guidance to describe chaining
  make_supercell/add_vacuum.
- **`agent/graph.py`** — system-prompt surface-workflow guidance now uses
  `make_slab → make_supercell → add_vacuum` (kept the "never refuse for a missing
  parameter" rule).

Tool count: 23 → 22.

## Verify
- `make_slab` exact-layer test on fcc Cu(100): requested 3/4/5/6 → exactly 3/4/5/6
  planes (6/8/10/12 atoms). The old 4→6 bug stays fixed. ✓
- `grep` for `build_slab|BuildSlabInput|slab_builder|export_slab` across `app/` and the
  frontend → no live references (only this/earlier postmortems & memory). ✓
- `py_compile` clean on all 7 touched files. ✓

## Lesson
A pasted "general flow" doesn't have to become a tool. Prefer small composable tools
(slab / supercell / vacuum) over one bundled mega-tool: fewer overlapping choices for
the agent, less duplicated geometry code, and the exact-layer logic lives in one place.
