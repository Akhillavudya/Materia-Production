# Step 5.5 · Step 9 — Point-defect tools (vacancy / substitution / interstitial)

**Status:** ✅ Done · the **last build step** and the only one needing a new dependency.

## Goal
Add three separate tools — `create_vacancy`, `create_substitution`, `create_interstitial` — that build
a **point defect** in a supercell and save it as the active POSCAR.

## What point defects are (plain language)
Real crystals aren't perfect. The three basic "mistakes" are:
- **Vacancy** — an atom is *missing*.
- **Substitution** — one atom is *swapped* for a different element (a dopant).
- **Interstitial** — an *extra* atom is squeezed into a gap between atoms.

These control conductivity, colour, diffusion, and doping — central to semiconductor and battery
research. Each defect is built inside a **supercell** so the defect doesn't interact with its own
periodic image.

## The dependency
These are the only tools that need **`pymatgen-analysis-defects`** (now uncommented in
`requirements.txt`). It was already present in the dev venv (v2026.3.20) and imports cleanly, so the
risk to the ARM Docker build is isolated to this one package — verified before any Docker change.

## Design note (deviation from the plan's `charge` column)
The plan listed a `charge` argument on each defect tool. We deliberately **left it out**: a defect
tool only produces a *geometry* (the defective POSCAR). Charge is a VASP/INCAR concern (`NELECT`),
already handled in one place by `generate_vasp_inputs(charge=…)`. So to make a **charged** defect, the
user runs the defect tool, then `generate_vasp_inputs` with a `charge` — no duplicated NELECT logic.
Every defect tool's message reminds the user of this.

## What changed
- **`services/structure/builder.py`** — `create_vacancy` / `create_substitution` /
  `create_interstitial` using the package's `VacancyGenerator` / `SubstitutionGenerator` /
  `VoronoiInterstitialGenerator`, plus a `_sc_matrix` helper (supercell spec → diagonal matrix; omit to
  auto-size for defect isolation). Each returns `(defect_structure, defect_name)`.
- **`tools/material_tools.py`** — three thin tools sharing a `_finish_defect` helper (atom cap →
  write active POSCAR → envelope with the charge reminder).
- **`tools/contracts.py` + `tool_registry.py` + `tool_schemas.py`** — registered all three (3-spot).
  Agent-facing tools now total **13**.
- **`backend/requirements.txt`** — `pymatgen-analysis-defects` uncommented.

## Verified
- From conventional diamond Si (8 atoms) in a 2×2×2 supercell (64 atoms):
  - vacancy → 63 atoms (`v_Si`), substitution Si→Al → `AlSi63` (64), interstitial H → `Si64H` (65). ✅
- All three registered + callable; **13 tools** total; `pymatgen-analysis-defects` imports in the venv. ✅
- Output supercell is subject to the atom cap (large supercells rejected). ✅
