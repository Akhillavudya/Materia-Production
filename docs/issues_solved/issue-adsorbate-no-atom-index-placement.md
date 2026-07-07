# Adsorbate could only go on ontop/bridge/hollow sites, not a specific atom

## Symptom
`add_adsorbate` only let the user drop a molecule on a symmetry-reduced site type
(`ontop` / `bridge` / `hollow`). A user (PhD testing) wanted to place the adsorbate
on a **particular atom** of the slab — "put O on that atom" — identified by its
index. There was no way to do this from the manual panel or from chat, and chat had
no notion of validating a named atom before placing.

## Root cause
`place_adsorbate` was built entirely around pymatgen's `AdsorbateSiteFinder`, which
enumerates geometric site types. The whole stack (service → tool → contract → agent
schema → API endpoint → UI form) only ever passed `site_type`. Targeting a concrete
atom was simply never a supported input.

## How we fixed it
Added an optional **0-based `atom_index`** all the way through:
- `adsorption.place_adsorbate(..., atom_index=None)` — when given, validate the index
  against the slab (`_validate_atom_index`) and place the molecule `distance` Å
  straight above that atom along the surface (c) normal, bypassing `site_type`.
  Out-of-range / non-integer / missing index raises a friendly error ending in
  "Cannot adsorb without a valid position."
- `material_tools.add_adsorbate(..., atom_index=None)` — threads it through; blocks
  `atom_index` in `relax=True` mode (accurate AdsorbML ranks sites itself) with a
  clear message; result detail reads "CO2 on atom #5".
- `contracts.AddAdsorbateInput.atom_index` — declares the field to the agent + UI.
- `tool_schemas` — instructs the agent: if the user names an atom, read the structure,
  confirm the index is valid, pass `atom_index`; if there is no valid atom/position,
  do NOT guess — tell the user it can't adsorb without a valid position.
- `api/upload.py` — manual endpoint accepts `atom_index` (blank → None, non-numeric →
  friendly error, never a 500).
- `toolForms.js` — new "On atom index (blank = use site)" number field.

Index is **0-based** to match pymatgen's internal site ordering (what the agent sees
when it reads the structure). The manual number field left blank falls back to the
existing site_type flow (empty values are dropped before FormData, so the backend
sees `None`).

## Files changed
- `backend/app/services/structure/adsorption.py` — `atom_index` path + `_validate_atom_index`; hoisted the c-normal calc so both paths share it.
- `backend/app/tools/material_tools.py` — `add_adsorbate` param, relax-mode guard, detail wording.
- `backend/app/tools/contracts.py` — `AddAdsorbateInput.atom_index`.
- `backend/app/agent/tool_schemas.py` — agent guidance (validate/refuse).
- `backend/app/api/upload.py` — manual endpoint form field + defensive parse.
- `frontend/src/features/sessions/toolForms.js` — manual "On atom index" field.

## How to verify
`_validate_atom_index` unit-checked directly (valid ints/strings pass; out-of-range,
negative, `"x"`, `None` all raise). Full placement needs the Docker/full stack
(`pymatgen.analysis.adsorption` isn't in the dev env). In the stack: make_slab, then
Add Adsorbate with molecule=O, atom index=5 → one O appears ~2 Å above slab atom 5.
Set atom index to a huge number → error "Cannot adsorb without a valid position."
In chat: "adsorb O on atom 3" → placed; "adsorb O on atom 999" → agent refuses.

## Lesson
When a placement tool hard-codes a taxonomy (site types), adding a "point at a
specific object" mode means an explicit, validated identifier (here a bounds-checked
0-based index) plus an agent instruction to *refuse rather than guess* when the
identifier is missing/invalid — otherwise the LLM will silently fall back to the old
auto-pick and the user won't know their target was ignored.
