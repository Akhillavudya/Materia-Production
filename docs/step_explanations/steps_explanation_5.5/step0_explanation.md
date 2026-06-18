# Step 5.5 · Step 0 — Modifier scaffolding (no behavior change)

**Status:** ✅ Done · **Commit:** `b948595`

## Goal
Lay the plumbing for "modifiers" (orthogonal INCAR knobs) **without changing any output yet**. This
is a safety-first checkpoint: prove we can add the wiring and the existing four tasks still produce
*byte-identical* INCAR files.

## The analogy
Before adding new buttons to a control panel, you first run the new wiring behind the panel and
confirm every existing button still does exactly what it did. Step 0 is that wiring pass.

## What changed
- **`services/vasp/templates.py`** — added inert modifier tag-groups: `_FUNCTIONAL_TAGS`
  (pbe/hse06/scan), `_VDW_TAGS`, `_SOLVENT_TAGS`, `_SOC_TAGS`, `_DIPOLE_TAGS`, and a curated
  `_HUBBARD_U` table. The default option of each (`pbe`/`none`/disabled) maps to an **empty dict**.
- **`services/vasp/incar.py`** — `generate_incar` now accepts `functional`/`vdw`/`soc`/`hubbard_u`/
  `solvent`/`dipole` and layers them via a new `_modifier_tags` helper (`_hubbard_tags` builds the
  element-ordered LDAU arrays). With defaults, `_modifier_tags` returns `{}` → nothing is added.

## Why "byte-identical" matters
Defaults are inert by construction (empty dicts), so a current user sees **zero** change. That is the
acceptance test for this step — it lets us land the infrastructure with no risk before any feature
is switched on in Steps 2–3.

## Verified
- Dumped all 4 tasks × cell-relax modes × magnetic/non-magnetic + override kwargs **before vs after**
  → `diff` empty (byte-identical). ✅
- Calling `generate_incar(..., functional=hse06, vdw=d3, soc=True, solvent=vaspsol, dipole=True,
  hubbard_u=True)` injects every expected tag (`LHFCALC`, `IVDW`, `LSORBIT`, `LSOL`, `LDIPOL`,
  `LDAU`, `LDAUU`) — proving the wiring is live, not dead. ✅
