# T2 — Structure-tool correctness (results)

**Tier:** T2 (supporting) · **Date:** 2026-06-25 · **Plan:** `docs/VALIDATION_PLAN.md` §3
**Suite:** `backend/tests/validation/test_structure_tools.py`
**Run:** `cd backend && ../venv/bin/python -m pytest tests/validation/test_structure_tools.py`
**Result:** ✅ **23 / 23 passed** (after 1 bug fix — see below)

Deterministic checks of the five structure transforms against pymatgen ground truth.
No ML potentials, no network, no ATAT — fast unit checks that double as the Step-9
regression net.

## Pass/fail table

| Tool | Check | Cases | Status |
|------|-------|-------|--------|
| `make_supercell` | atom count = n × original; lattice vectors scaled; composition preserved | uniform `2`, per-axis `2 2 1`, 3×3 matrix `2 0 0 0 2 0 0 0 1` | ✅ |
| `add_vacuum` | realised inter-image gap = requested thickness; correct slab placement | side = both / top / bottom | ✅ |
| `make_slab` | **exactly** the requested atomic-plane count; vacuum applied; `min_slab_size` ignored when `layers` set | layers = 3, 4, 5, 6 (Cu 111) | ✅ |
| `add_adsorbate` | adsorbate placed **above** the surface (never buried); correct atom count | CO ontop, CO2 ontop | ✅ (fixed) |
| `generate_sqs` | partial-substitution composition matches target; rejects bad fraction / missing element | `Si->S:0.25` on MgSi2Se4-like | ✅ |
| `convert_structure` | POSCAR / CIF / XYZ round-trip preserves lattice, composition, atom count; rejects unknown format | poscar, cif, xyz | ✅ |

> SQS is checked at the pure-Python substitution layer only — the full `mcsqs` search
> needs the ATAT binaries, which live in the Docker image (not on the dev host).

## Bug found & fixed: adsorbate buried in slab

**Symptom.** `add_adsorbate` (geometric mode) on a `make_slab` output placed the CO
molecule's carbon at z = 13.77 Å — *below* the slab top (14.42 Å) — i.e. inside the
slab instead of 2 Å above it.

**Root cause.** `make_slab` with `layers=N` trims excess planes from the top, producing
an **asymmetric** plain `Structure`. `AdsorbateSiteFinder.find_adsorption_sites` then
returns inequivalent sites on *both* the top and bottom surfaces. `place_adsorbate`
used `position_index=0` = `coords[0]`, whose order is not height-sorted, so it could
pick a lower-surface (buried) site.

**Fix.** `place_adsorbate` now sorts candidate sites by height along the c (out-of-plane)
normal before indexing, so `position_index=0` is always the true top site.
(`backend/app/services/structure/adsorption.py`.) Postmortem:
`docs/issues_solve/2026-06-25-adsorbate-buried-in-asymmetric-slab.md`.

**Note on `distance`.** pymatgen measures the adsorption `distance` along the local
surface normal against the coordinating ensemble, not as a naive z-offset from the
single topmost atom — so a `distance=2.0` request realises a vertical gap of ~1.15 Å
above the top atom even on a native pymatgen `Slab`. This is expected pymatgen
behaviour, not a Materia defect; the test asserts a positive physical gap rather than
an exact 2.0 Å.
