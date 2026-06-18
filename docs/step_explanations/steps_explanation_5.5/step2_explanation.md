# Step 5.5 · Step 2 — Expose the modifiers (functional/vdw/soc/hubbard_u/dipole/charge)

**Status:** ✅ Done · **Commit:** `f2d3d3a`

## Goal
Turn on the modifier wiring from Step 0 so the agent/user can stack orthogonal knobs on **any** task —
e.g. *"HSE06 band structure with spin-orbit"* = `task=band, functional=hse06, soc=true`.

## The modifiers
| Modifier | Values | What it does |
|---|---|---|
| `functional` | pbe / hse06 / scan | exchange-correlation method (accuracy vs. cost) |
| `vdw` | none / d3 / d3bj / optb88 / df2 | van-der-Waals dispersion correction |
| `soc` | bool | spin-orbit coupling (noncollinear) |
| `hubbard_u` | bool | DFT+U for transition-metal d-electrons (curated U values) |
| `dipole` | bool | dipole correction along c (slabs / charged cells) |
| `charge` | float | net cell charge → sets `NELECT` |

## Why "base task + modifiers" (not 20 separate task names)
The knobs are *orthogonal* — most apply to any calculation. Making them flags means combinations are
possible (HSE06 band, +U relaxation) and impossible combos can't happen (HSE06 and SCAN can't both be
on, because they're one `functional` field). It also keeps the agent's tool list small.

## What changed
- **`tools/contracts.py`** — 6 modifier fields added to `GenerateVaspInputsInput`.
- **`services/vasp/service.py`** — `build_input_set` takes a `modifiers` dict; resolves
  `charge → NELECT` from POTCAR valence counts (`_compute_nelect`); collects modifier `warnings`
  (`_modifier_warnings`); threads the rest into `generate_incar`.
- **`domain/vasp.py`** — `VaspInputSet` now reports the applied `modifiers` + `nelect`.
- **`tools/material_tools.py`** — validates `functional`/`vdw`, builds the modifiers dict, and (new)
  **enforces the atom cap on the VASP path**.
- **`agent/tool_schemas.py`** — the tool description now explains tasks + stackable modifiers.

## The one bit of real chemistry: charge → NELECT
`NELECT = Σ(valence electrons from POTCAR) − charge`. Example: Si has 4 valence e⁻; a 2-atom cell has
8. Requesting `charge=+1` removes one electron → `NELECT=7`. VASP then adds a compensating uniform
background. A warning is emitted so the user knows the cell is charged.

## Verified
- hse06+band (LHFCALC + line-mode KPOINTS), soc+static (LSORBIT + warning), vdw=d3 (IVDW=11),
  +U on Fe (LDAU, U=5.3), **charge=+1 → NELECT=7**, dipole (LDIPOL). ✅
- Default call = no-op (no modifiers, no NELECT, no HSE tags). ✅
- All 6 params present in the agent schema; invalid `functional`/`vdw` rejected. ✅
