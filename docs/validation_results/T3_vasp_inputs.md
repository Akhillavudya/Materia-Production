# T3 — VASP input fidelity (results)

**Tier:** T3 (supporting) · **Date:** 2026-06-25 · **Plan:** `docs/VALIDATION_PLAN.md` §4
**Suite:** `backend/tests/validation/test_vasp_inputs.py`
**Run:** `cd backend && ../venv/bin/python -m pytest tests/validation/test_vasp_inputs.py`
**Result:** ✅ **21 / 21 passed** (no bugs found)

Verifies that generated INCAR / KPOINTS / POTCAR(.spec) are correct and, where a
ground truth exists, agree with pymatgen.

## Pass/fail table

| Input | Check | Status |
|-------|-------|--------|
| KPOINTS | realised k-point density monotonic across Low/Med/High and within band of requested kppa | ✅ |
| KPOINTS | Γ-centred vs Monkhorst-Pack style honoured | ✅ |
| KPOINTS | `Custom` requires `custom_kppa`; invalid accuracy level rejected | ✅ |
| POTCAR.spec | element ordering = POSCAR order (first appearance) | ✅ |
| POTCAR.spec | curated labels correct; ENCUT floor = ⌈max ENMAX × 1.3⌉ | ✅ |
| POTCAR.spec | unknown element degrades gracefully (bare label + warning) | ✅ |
| INCAR | optimization preset: IBRION 2, NSW>0, EDIFFG<0, ENCUT 520, EDIFF 1E-6 | ✅ |
| INCAR | static preset: IBRION −1, NSW 0 | ✅ |
| INCAR | cell-relax → ISIF map (none→2, shape→5, full→3) | ✅ |
| INCAR | magnetism auto-detect (Fe → ISPIN 2, one MAGMOM per site); non-magnetic stays spin-free | ✅ |
| INCAR | DFT+U tags in POTCAR element order (Fe U=5.3, O none), LMAXMIX 4 | ✅ |
| INCAR | orthogonal modifiers: SCAN→METAGGA, HSE06→LHFCALC, vdW d3→IVDW 11; inert at defaults | ✅ |

## ENCUT agreement with pymatgen MPRelaxSet

Materia default `ENCUT = 520 eV` — **matches** MPRelaxSet exactly.

## POTCAR-label diff vs pymatgen MPRelaxSet (intentional deviations)

**Harness:** `backend/scripts/validation/t3_potcar_mp_diff.py`
**Match rate: 11 / 16 = 69 %** over the Tier-1 + common-element set.

| Element | Materia | MP (MPRelaxSet) | Status |
|---------|---------|-----------------|--------|
| Si | Si | Si | match |
| Al | Al | Al | match |
| Cu | Cu | Cu_pv | **deviation** |
| Fe | Fe | Fe_pv | **deviation** |
| Mg | Mg | Mg_pv | **deviation** |
| O | O | O | match |
| Na | Na_pv | Na_pv | match |
| Cl | Cl | Cl | match |
| C | C | C | match |
| Ga | Ga_d | Ga_d | match |
| As | As | As | match |
| Ti | Ti_sv | Ti_pv | **deviation** |
| Zn | Zn | Zn | match |
| Ni | Ni | Ni_pv | **deviation** |
| Co | Co | Co | match |
| Mn | Mn_pv | Mn_pv | match |

**Why the deviations are not bugs.** Materia's curated table follows the **VASP-
recommended** PAW potentials (e.g. `Cu`, `Fe`, `Ni`, `Ti_sv`). The Materials Project
deliberately uses a different, historically-frozen set (often the `_pv` semicore
variants) so that *all* MP-database energies stay mutually consistent — a database
constraint Materia does not share. Both are valid; they target different goals
(VASP's current accuracy recommendation vs MP cross-entry comparability).

> A future option (not required for launch) is a `--potcar-set mp` switch to mirror
> MP labels exactly when a user wants to reproduce MP energies. Logged as a roadmap
> item, not a validation gap.

## Scope notes
- Real `POTCAR` assembly (vs the `.spec`) needs the licensed PAW library mounted at
  `PMG_VASP_PSP_DIR` (runtime-only, never on the dev host) — not exercised here.
- KPOINTS densities use Materia's accuracy levels (kppa Low 1000 / Med 3000 /
  High 5000); MP's relax default is `reciprocal_density=64`. Different by design —
  Materia exposes an explicit accuracy knob.
