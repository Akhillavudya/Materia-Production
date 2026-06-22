# Step 5.5 · Step 7 — `convert` operation (format conversion)

**Status:** ✅ Done
**Superseded 2026-06-22 (Step 12):** the `convert` operation is now a standalone `convert_structure`
tool (same behaviour — writes a format file, does not touch the active POSCAR). See
`step12_explanation.md`.

## Goal
Add the fourth `build_structure` operation: **`convert`** — write the current structure in a different
file format (POSCAR ↔ CIF ↔ XYZ ↔ CSSR ↔ JSON). A small but universally useful utility.

## Why it matters (plain language)
Every code and collaborator wants structures in *their* format: VASP uses POSCAR, most databases and
papers use CIF, visualization/MD tools often want XYZ, and JSON is handy for scripting. `convert` lets
a user get the active structure out in whatever format they need without leaving Materia.

## How it differs from the other operations
The supercell/vacuum/slab operations **transform geometry** and overwrite the active POSCAR so they
chain. `convert` does **not** change geometry or the active structure — it just emits a *new file* in
the chosen format. So it is handled by a dedicated early-return branch (`_convert_structure`) that
writes `<formula>.<ext>` and reports the filename, rather than going through `write_poscar`.

## Format notes
- poscar→`.vasp`, cif→`.cif`, xyz→`.xyz`, cssr→`.cssr`, json→`.json`.
- **XYZ** is produced via ASE (`extxyz`), because pymatgen's native XYZ is molecule-oriented and would
  drop the lattice; extxyz keeps the cell.

## What changed
- **`services/structure/builder.py`** — `CONVERT_EXT` map + `to_format(structure, fmt)` (validates the
  format; ASE path for xyz).
- **`tools/material_tools.py`** — `convert` in `_BUILD_OPERATIONS`, the `to_format` param, and the
  `_convert_structure` helper (early return; writes the format file).
- **`tools/contracts.py`** — `to_format` field.
- **`agent/tool_schemas.py`** — description now lists `convert`.

## Verified
- All 5 formats serialize (CIF has `data_`, XYZ has element symbols, JSON parses). ✅
- Invalid format (`pdf`/`png`) rejected with a friendly list. ✅
- End-to-end: `convert to_format=cif` wrote `Si.cif` into the session. ✅
- `to_format` present in the agent schema. ✅
