# Step 5.7 · Step 3 — `generate_sqs` (Special Quasi-random Structures via ATAT mcsqs)

**Status:** ✅ Done (code) · **needs an image rebuild** to ship (compiles ATAT into the image).

## Goal
Add the third tool: **`generate_sqs`** — turn a **disordered alloy** (a structure with partial site
occupancies, e.g. Li(Ni₀.₈Mn₀.₁Co₀.₁)O₂) into a small, fully-ordered **supercell** that statistically
mimics the random solid solution, so it can be used in a real DFT calculation.

## Why an SQS (plain language)
You can't tell VASP "this site is 80 % Ni, 10 % Mn, 10 % Co" — every atom must be a concrete element.
A **Special Quasi-random Structure** is the cleverest way to pick *which* atom goes *where* in a finite
box: it matches the pair/triplet correlations of a truly random alloy as closely as possible. ATAT's
**`mcsqs`** searches for that arrangement by Monte-Carlo, minimising an **objective function** (closer
to −1 = better match).

## Pipeline (adapted from the reference notebook, de-interactived)
1. Read a **disordered CIF** from the session.
2. **Detect disordered sublattices** → a full-occupancy *parent* structure + an occupancy spec
   (`sqs_sublattices.json`). An optional `target_comp` overrides the CIF occupancies.
3. Write ATAT inputs: **`rndstr.in`** (in *absolute Å* — see below) + **`sqscell.out`** (the supercell).
4. If no `cutoff` is given, **recommend one** from a nearest-neighbour shell analysis of the active sites.
5. **`corrdump` + `getclus`** set up the cluster correlations.
6. Launch **N parallel `mcsqs`** searches, polling each log's objective; **stop** when the best drops
   below `target_objective`, the `time_budget_s` runs out, or the job is cancelled.
7. Take the best `bestsqs` and **convert it to a POSCAR**.

### Two things the notebook lacked, that we added
- **`bestsqs → POSCAR` converter** (`bestsqs_to_structure`): the notebook *called*
  `convert_bestsqs_to_poscar(...)` but never defined it. ATAT's `bestsqs.out` is *3 coordinate-system
  vectors + 3 supercell vectors + atom lines*; we rebuild the lattice as `supercell @ coord_system`
  and place atoms by `xyz @ coord_system`.
- **Absolute-Å `rndstr.in`**: the notebook had a *normalized* variant (lattice ÷ max parameter), which
  makes `bestsqs.out` come back in scaled units. We write the **real Å lattice vectors** instead, so the
  converted POSCAR is already in physical units — no rescaling guesswork.
- **Job-friendly monitor**: the notebook used a bare `signal` handler + `while` loop. We replaced it
  with the job's `ProgressReporter` (cooperative `JobCancelled`) and a hard **time budget**, and we
  terminate all `mcsqs` children on stop.

## How it's wired (async job, same 8 touch-points + Dockerfile)
| Touch-point | Change |
|---|---|
| `domain/jobs.py` | new `JobType.SQS` |
| `services/simulation/sqs.py` | **new pure service** `run_sqs(...)` + helpers |
| `jobs/queue.py` | `TASK_NAMES` + inline map entry |
| `jobs/runners.py` | dispatch branch + `@celery_app.task jobs.sqs` + artifact kinds |
| `tools/contracts.py` | `GenerateSqsInput` (target_comp / supercell / cutoff / n_parallel / …) |
| `agent/tool_registry.py` | registry entry → planner + spinner (**16 tools total**) |
| `tools/material_tools.py` | adapter; parses `target_comp` `"Li:1,Ni:0.8,…"` and the supercell |
| `backend/Dockerfile` | **compiles ATAT** (`corrdump`/`getclus`/`mcsqs`) into `/usr/local/bin` |

If the ATAT binaries are missing from PATH, the service returns a **clear error** rather than crashing.

## Outputs (artifacts in the job panel)
`POSCAR` (the SQS supercell) · `bestsqs_final.out` · `rndstr.in` · `sqscell.out` ·
`parent_structure.cif` · `sqs_sublattices.json` · `bestcorr.out` · `mcsqs_progress.csv`.

## Verification done (pure-Python parts — ATAT not installable locally)
ATAT binaries aren't on this machine, so the mcsqs search itself is tested at rebuild. Everything else
was validated against the **reference workflow files**:
- **`bestsqs → Structure` converter** on the reference `bestsqs_final.out` → **120 atoms**, composition
  **Ni24 Mn3 Co3 Li30 O60** — i.e. the TM sublattice is exactly Ni0.8/Mn0.1/Co0.1 over 5×2×1 ✓.
- **Absolute-Å round-trip**: a 4 Å cell × 2×2×2 fake `bestsqs.out` → lattice **abc = [8,8,8]**, 8 atoms,
  `is_valid = True` ✓ (proving the converter is unit-correct; the reference file's tiny abc was just
  its normalization).
- **Sublattice detection** on the reference `input.cif` → TM sites [3,4,5], parent Ni, occupancies
  Co0.1/Mn0.1/Ni0.8 ✓.
- **Generated `rndstr.in` disordered lines match the reference exactly** (`Co=0.1,Mn=0.1,Ni=0.8`), with
  the real Å lattice (a=2.86, c=14.16); **`sqscell.out` matches exactly** ✓.
- ATAT-absent **guard** returns a clean error; registry builds (16 tools), Celery task `jobs.sqs`
  registered, `py_compile` clean ✓.

## Note on rebuilds
This step adds the **ATAT compile layer** to the Dockerfile (the one Dockerfile change in Step 5.7), so
it ships only after the next **image rebuild**. The ATAT source URL/version is pinned via
`ARG ATAT_URL` / `ARG ATAT_VERSION` — if upstream moves, update those. We'll do the single rebuild +
smoke test (phonopy + seekpath + ATAT all at once) in **Step 4**.
