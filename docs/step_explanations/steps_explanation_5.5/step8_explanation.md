# Step 5.5 · Step 8 — `analyze_symmetry` (read-only tool)

**Status:** ✅ Done

## Goal
Add a dedicated, **read-only** tool that reports a structure's symmetry — space group, point group,
crystal system, and primitive/conventional site counts — and can optionally save the standard cell.

## Why it's a separate tool (not a build_structure operation)
`build_structure` is for operations that **modify** the structure and overwrite the active POSCAR.
`analyze_symmetry` mainly **inspects** — it answers "what's the space group?" without changing
anything. Mixing an inspector into a builder would muddy what each tool means, so it gets its own
entry point. (It *can* optionally write a standard cell — see below — but its default is read-only.)

## What it reports
- **Space group** symbol + number (e.g. `Fd-3m (#227)`),
- **point group**, **crystal system**, **lattice type**,
- number of **symmetry operations**,
- site counts for the current / primitive / conventional cells, and whether the input is primitive.

The `symprec` tolerance (Å) controls how strict the symmetry detection is.

## Optional write
Set `write="primitive"` or `write="conventional"` to also save that **standard cell** as the active
POSCAR — handy because Miller-plane and many DFT conventions assume the conventional cell. The written
cell is subject to the atom cap.

## What changed
- **`services/structure/builder.py`** — `analyze_symmetry(structure, symprec)` and
  `standard_structure(structure, kind, symprec)` via `SpacegroupAnalyzer`.
- **`tools/material_tools.py`** — the `analyze_symmetry` tool (resolve → analyze → optional write).
- **`tools/contracts.py` + `tool_registry.py` + `tool_schemas.py`** — registered the new tool
  (3-spot pattern). Agent-facing tools now total **10**.

## Verified
- Conventional diamond Si → `Fd-3m (#227)`, point group `m-3m`, cubic, 192 symmetry ops; primitive=2 /
  conventional=8 sites. ✅
- End-to-end: read-only (no files written); `write=primitive` wrote the active POSCAR; invalid `write`
  rejected. ✅
- Registered + callable; schema props `[poscar_path, material_id, source, symprec, write]`. ✅
