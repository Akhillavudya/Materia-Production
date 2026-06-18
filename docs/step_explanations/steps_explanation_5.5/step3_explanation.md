# Step 5.5 · Step 3 — Implicit solvent (VASPsol / VASPsol++)

**Status:** ✅ Done

## Goal
Add a `solvent` modifier so a calculation can be run in **implicit solvation** instead of vacuum —
essential for electrochemistry, catalysis, and surfaces in water.

## What "implicit solvent" means (plain language)
Instead of placing thousands of explicit water molecules around your system (slow), the solvent is
modelled as a smooth dielectric medium that surrounds the atoms. VASPsol does exactly this.
**VASPsol++** goes further: it adds an *electrolyte* (dissolved ions) via a linearized
Poisson–Boltzmann model — needed for charged interfaces, the electric double-layer, and pH/potential
effects.

| `solvent` | Tags | Use case |
|---|---|---|
| `none` | — | vacuum (default) |
| `vaspsol` | `LSOL`, `EB_K=78.4` (water permittivity) | molecule/surface in solvent |
| `vaspsol++` | + `LRHOB`, `NC_K` (electrolyte) | charged interfaces, double-layer |

## The important caveat ⚠️
These tags only work with the **VASPsol-patched VASP binary**. A stock VASP build silently ignores
`LSOL`. So the tool **emits a warning** every time solvation is requested, telling the user they need
the patched executable. Pairing `solvent=vaspsol++` with `charge` (→ NELECT) is the recipe for a
charged electrochemical interface.

## What changed
- **`tools/contracts.py`** — new `solvent` field.
- **`tools/material_tools.py`** — validates `solvent` ∈ {none, vaspsol, vaspsol++} and adds it to the
  modifiers dict.
- **`services/vasp/service.py`** — `_modifier_warnings` now warns about the patched-binary
  requirement (and the charge pairing).
- **`agent/tool_schemas.py`** — tool description mentions `solvent`.

(The actual `LSOL`/`EB_K`/`LRHOB`/`NC_K` tag injection was already scaffolded in Step 0's
`_SOLVENT_TAGS`; this step just exposes and guards it.)

## Verified
- `vaspsol` → LSOL + EB_K + patched-binary warning. ✅
- `vaspsol++` → LSOL + LRHOB + NC_K. ✅
- `vaspsol++` + `charge=+1` → LSOL + NELECT=7 (charged interface). ✅
- Default (`none`) = no LSOL, not listed in applied modifiers. ✅
- Invalid value (`water`) rejected with a friendly message; `solvent` present in the agent schema. ✅
