# Step 5.5 · Step 1 — Seven new VASP base tasks

**Status:** ✅ Done · **Commit:** `d7a1fe7`

## Goal
Add seven single-directory calculation types alongside the existing static/relaxation/band/DOS:
**aimd, elastic, phonon_dfpt, dielectric, bader, elf, workfunction.**

## What each task is (plain language)
| Task | Answers the question… | Key INCAR |
|---|---|---|
| `aimd` | how do atoms move at temperature T? | `IBRION=0`, MD thermostat |
| `elastic` | how stiff is the material? | `IBRION=6`, `NFREE` |
| `phonon_dfpt` | what are its vibrations (Γ-point)? | `IBRION=8`, `LEPSILON` |
| `dielectric` | how does it respond to light/fields? | `LOPTIC`, `CSHIFT` |
| `bader` | how is charge split between atoms? | `LAECHG` |
| `elf` | where are electrons localized (bonds/lone pairs)? | `LELF` |
| `workfunction` | how much energy to remove an electron from a surface? | `LVTOT`/`LVHAR`/`LDIPOL` |

## What changed
- **`templates.py`** — 7 new INCAR templates (AIMD reuses the existing `md_nvt` template).
- **`domain/vasp.py`** — extended the `VaspTask` enum (+ docstring).
- **`services/vasp/service.py`** — `_TASK_TO_TEMPLATE` mapping; KPOINTS logic now picks: line-mode
  (band), **Γ-only (aimd)**, denser mesh (dos/dielectric/phonon), regular mesh otherwise.
- **`api/catalog.py`** — `/api/vasp/tasks` now lists all 11 tasks.
- **`tools/material_tools.py` + `tools/contracts.py`** — the invalid-task message and the `task`
  description now derive from the enum (no drift).

## Why these were easy
All seven are "one folder, one INCAR/KPOINTS/POSCAR" calculations — only the VASP flags differ. That
is exactly the shape the existing generator already produces, so they slot straight in. (The genuinely
different ones — NEB, finite-displacement phonons — need *multiple* folders and were deferred.)

## Verified
- All 7 new tasks + 4 core tasks generate via `build_input_set` with the correct INCAR tag *values*
  (whitespace-insensitive check). ✅
- AIMD → `kmesh=[1,1,1]` (Γ-only); dielectric/phonon → denser mesh. ✅
- Catalog + agent tool layer import cleanly; 11 tasks exposed. ✅
