# 2026-06-24 — Structure viewer renders empty (0 atoms) for some POSCARs

## Symptom
In the new VESTA-style Structure Viewer, a CO2-on-Cu adsorption slab
(`CuBCO2 ads-co2`) rendered the **unit-cell box but no atoms** — the header read
"0 atoms". The same structure displayed correctly in VESTA. Other POSCARs (Si,
LiFePO4, etc.) rendered fine.

## Root cause
The viewer handed the raw POSCAR text to `viewer.addModel(content, 'vasp')` and
trusted **3Dmol.js's VASP parser**. That parser is fragile: it parses the
lattice (lines 2–4) first, then bails with an early `return atoms` (empty) on
minor formatting quirks. Confirmed by porting 3Dmol's parser to Node:

- coordinate-mode line read at a fixed index `lines[7].trim()`; if it isn't
  `C…`/`D…` it logs "Unknown vasp mode" and returns **zero atoms** while the cell
  is already built — exactly our symptom (box, no atoms).
- a single **stray blank line** before the mode line (or any layout shift)
  pushes a non-mode string into `lines[7]` → unknown mode → 0 atoms.
- also bails on negative scale and on symbol/count length mismatch.

Standard pymatgen POSCARs avoided the trap; the adsorbate-builder output did not.

## Approach
Stop depending on 3Dmol's VASP reader. We already had a hand-rolled
`parsePoscar` in `viewer/polyhedra.js` (used for coordination polyhedra), so make
it the single source of truth for POSCAR geometry and feed 3Dmol a format it
parses reliably (**XYZ**).

## Fix
`frontend/src/features/viewer/`:
- **polyhedra.js** — `parsePoscar` hardened: strips/ignores **blank lines**
  (`.filter(l => l.length)`), tolerates VASP4/5, selective dynamics,
  Direct/Cartesian, and trailing per-line element labels (`Number` on first 3
  cols, NaN-guarded). Added `replicateAtoms(atoms, lattice, na,nb,nc)` and
  `toXyz(atoms)`.
- **StructureWorkspace.jsx** — `renderScene` now: for `vasp`, parse → replicate
  for supercell → `addModel(toXyz(atoms), 'xyz')`, and draw the cell ourselves
  via new `drawCellBox()` (12 parallelepiped edges). CIF/XYZ still use 3Dmol's
  own parser + `addUnitCell`/`replicateUnitCell`. The parsed `geom` (lattice +
  base atoms) now drives both the cell box and the polyhedra, so atoms, cell and
  polyhedra share identical coordinates.

## Verify
Node tests against `parsePoscar`/`toXyz`/`replicateAtoms`:
- CuBCO2 reconstruction with a stray blank line + Cartesian coords + element
  labels → **11 atoms** (previously 0 via 3Dmol).
- Real files: `POSCAR` 65, `POSCAR_Si` 8, LiFePO4 run 28 atoms.
- `replicateAtoms(...,2,2,1)` → 44 (= 11×4).
- `npm run build` passes.

## Lesson
Don't trust third-party structure parsers for the happy path only — 3Dmol's VASP
reader fails closed (silently drops all atoms) on benign formatting. When we
already own a parser for a format, use it as the source of truth and feed the
render engine its most robust input format (XYZ). Fail-closed parsers are worse
than loud ones: the cell drew, so the failure looked like a render bug, not a
parse bug.
