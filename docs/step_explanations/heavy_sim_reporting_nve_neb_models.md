# Heavy-simulation convergence reporting, NVE, NEB path builder, model testing

_2026-06-23 — production-hardening pass driven by the PhD tester's SSE/NEB workflow._

This change set makes the heavy simulation tools **transparent and self-diagnosing**,
adds the **NVE** ensemble, lets **NEB build its own migration endpoints** from a
migrating atom, gives the **elastic** tool relaxation options, fixes an element-
matching bug in **C2DB** search, and adds a **real model-test routine** plus the
**MatterSim large (5M)** checkpoint.

## 1. The convergence / diagnostics report (the "detail file")

Every heavy job (optimize, MD, NEB, elastic, phonon) now writes two artifacts:

- `convergence_report.md` — human-readable: a per-phase table (steps taken vs
  budget, converged?, final force, ΔE) and a plain-language **Verdict** that tells
  you whether the energy converged or to *"rerun with max_steps = N"*.
- `convergence.json` — the same data, machine-readable.

Built by `backend/app/services/simulation/report.py` (`ConvergenceReport`). The job
runner persists anything in a service's `files` dict, so no runner changes were
needed.

### Why NEB "looked like it ran 3 times / 150%"
`run_neb` runs **3 optimizers in sequence**: relax initial endpoint → relax final
endpoint → optimize the band (in two sub-phases: a no-climb relax, then the
climbing image). The old progress bar got `total=max_steps` for each with **no
phase label**, so it filled to 100% three times. Now `ProgressReporter` carries
`phase` / `phase_index` / `phase_count`, and each stage is labelled
("Phase 2/4: Relax final endpoint"). The report spells out the steps each phase
took, so the multi-phase run is no longer a mystery.

## 2. NVE ensemble (MD)

`run_md` now supports `ensemble="nve"` (microcanonical, ASE `VelocityVerlet`, no
thermostat). MD also now **initialises velocities** (Maxwell-Boltzmann + remove net
translation/rotation) for all ensembles — required for NVE (without it the atoms
never move). The report's verdict for NVE is **energy conservation** (drift/atom).
A `md_nve` VASP INCAR preset (`MDALGO=0`, `SMASS=-3`) was added for DFT handoff.

## 3. NEB migration-path builder

`backend/app/services/simulation/neb_path.py` implements the tester's notebook
recipe (`/home/roy/Desktop/NEB.ipynb`):

- `find_migration_sites(structure, element)` — labels every atom of the migrating
  element 1..N (e.g. Mg1..Mg8), annotated with its symmetry orbit.
- `list_migration_pairs(structure, element, cutoff)` — all source→dest hops within
  a cutoff, sorted shortest-first.
- `build_migration_endpoints(...)` — vacancy-mediated: **initial** = remove the
  destination atom; **final** = move the source atom into the destination site.

New tool **`list_migration_paths`** previews the candidate hops (no job).
`compute_neb` now accepts either two endpoint files (unchanged) **or**
`migrating_element` (+ optional `source_site`/`dest_site`); when given a migrating
element it auto-builds and relaxes the endpoints. Images use the existing ASE IDPP
interpolation + two-phase climbing band (no VTST dependency).

## 4. Elastic relaxation options

`compute_elastic_tensor` gained `relax_mode`: `"positions"` (ions only) /
`"shape"` (cell shape + ions, fixed volume) / `"full"` (default; shape + volume +
ions). Maps the tester's three mechanical-property optimization options.

## 5. C2DB element-matching fix

`c2db.py` filtered elements by substring, so `"S"` wrongly matched `"Se"` and
`"Sc"` implied `"S"`. It now parses the formula into element symbols via pymatgen
`Composition`. (MP/OQMD were already element-safe.)

## 6. Model testing + MatterSim large (5M)

`backend/scripts/test_models.py` loads **and runs** each model on a 2-atom Si cell
(not just a disk check) and reports PASS/FAIL/SKIP with timings; non-zero exit if a
present model fails. Also exposed at `POST /api/calculators/test`.

This immediately caught real bugs: the MatterSim **1M** checkpoint was stored as an
unzipped archive dir (unloadable), and three MACE dirs were empty but advertised as
available. `list_available_models()` now checks for an actual checkpoint file.

### Downloading MatterSim checkpoints (runtime, never committed)

```bash
# Large (5M) — "mattersim large":
python backend/scripts/download_mattersim_5m.py
# Both 1M + 5M (also fixes a broken 1M install):
python backend/scripts/download_mattersim_5m.py --all --force
# Verify:
python backend/scripts/test_models.py
```

Source: `https://raw.githubusercontent.com/microsoft/mattersim/main/pretrained_models/`.
Files land under `pre_trained_models/matterSim_models/<model>/<model>.pth`
(or `$PRE_TRAINED_MODELS_DIR`). Like POTCAR, these are mounted at runtime — not
baked into the image or committed.

## Verified (local, CUDA)

`test_models.py` → mace-mp-0b3-medium PASS, mattersim 1M PASS, mattersim 5M PASS,
empty MACE variants correctly SKIP (exit 0). Report rendering + NEB endpoint
builder unit-tested.
