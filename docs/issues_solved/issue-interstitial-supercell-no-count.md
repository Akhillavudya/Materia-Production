# Interstitial tool still used a supercell and had no atom count

## Symptom
`create_vacancy` and `create_substitution` had already been reworked (2026-07-03) to
operate on the **current cell** and take a `count` ("how many", a number or `"all"`).
But `create_interstitial` was left behind: it still exposed a `supercell` field and
always inserted **exactly one** atom into an auto-sized supercell. That was
inconsistent for users (the Defect panel had two "How many" tools and one "Supercell"
tool), and there was no way to add, e.g., 3 interstitials.

## Root cause
The earlier count rework only touched the two generator-based defect tools. The
interstitial path used a different pymatgen call — `VoronoiInterstitialGenerator`
followed by `defect.get_supercell_structure(sc_mat=_sc_matrix(supercell))` — which
both enlarges the cell and only realizes the single first defect. There was no
`count` concept and the `supercell` param was baked through all six layers
(builder → tool wrapper → contract → agent schema → UI form → API endpoint).

## How we fixed it
Rewrote `builder.create_interstitial(structure, insert_element, count=1)` to mirror
the vacancy/substitution shape:
- Generate candidate Voronoi sites once (`VoronoiInterstitialGenerator().generate`).
- `_resolve_count(count, len(defects), ...)` bounds "how many" against the number of
  distinct symmetry-inequivalent sites (accepts a number or `"all"`, default 1).
- Insert the first `count` sites' `defect.site.frac_coords` into a **copy of the
  current cell** (`Structure.append`), no supercell enlargement.
- Return a `"3x H interstitial"` / `"H interstitial"` style name.

Then swapped `supercell` → `count` in every layer and removed the now-orphaned
`_sc_matrix` helper (interstitial was its last user; `make_supercell` has its own
parser).

## Files changed
- `backend/app/services/structure/builder.py` — rewrote `create_interstitial`; deleted dead `_sc_matrix`.
- `backend/app/tools/material_tools.py` — tool wrapper `supercell` → `count`.
- `backend/app/tools/contracts.py` — `CreateInterstitialInput`: `supercell` field → `count`.
- `backend/app/agent/tool_schemas.py` — agent description now documents `count` / current-cell.
- `backend/app/api/upload.py` — manual `create_interstitial` endpoint form field `supercell` → `count`.
- `frontend/src/features/sessions/toolForms.js` — Supercell input → "How many (number or all)".

## How to verify
Not runnable in the dev env (`pymatgen.analysis.defects` is a desktop/full-stack
dependency, not installed locally — `py_compile` passes on all six files). In the
full Docker stack: load e.g. FCC Al, run **Interstitial** with `insert_element=H`,
`count=3` → the active POSCAR should gain 3 H atoms at distinct Voronoi sites with
the original lattice unchanged; the assistant/manual card should read "3x H
interstitial". Also confirm the agent picks `count` (not `supercell`) from a prompt
like "add 2 Li interstitials".

## Lesson
When a rework establishes a new convention across a family of tools, sweep the whole
family in the same pass — a sibling left on the old shape (here `supercell` vs
`count`) reads as a bug to users and drags dead helpers (`_sc_matrix`) along with it.
