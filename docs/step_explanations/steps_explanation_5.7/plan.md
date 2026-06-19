# Step 5.7 — Plan: Phonons, Mechanical (elastic) & SQS tools

**Status:** 🚧 In progress (started 2026-06-19).
**Goal:** Add the **last three simulation tools** to Materia — **phonon band/DOS**, **elastic /
mechanical properties**, and **special quasi-random structures (SQS)** — each as a proper
**async job** that runs on the worker (like `optimize` / `run_md`). After these, no more *new* tools;
focus shifts to **quality of the existing tools**. (NEB is intentionally deferred to a later step.)

> This folder holds the **plan** (this file) plus a **per-step explanation** (`stepN_explanation.md`)
> for each implementation step. Step 5.7 slots into the launch-hardening roadmap **between Step 5.5
> (more VASP + structure tools, shipped) and Step 6** — feature work, hence the half-step number.

---

## The analogy
Step 5.5 taught Materia to **write recipes** (VASP inputs) and **prepare ingredients** (build/modify
structures). Step 5.7 teaches it to actually **measure three physical properties** with the
ML-potential "instruments" already in the image:

1. **Phonons** — *how does the crystal vibrate?* (finite-displacement supercell + forces → band/DOS).
   Tells you thermal/vibrational stability (imaginary modes = unstable).
2. **Mechanical / elastic** — *how stiff and ductile is it?* (strain the cell, read the stress →
   the 6×6 elastic tensor → bulk **K**, shear **G**, Young's **E**, Poisson **ν**, Pugh's K/G,
   anisotropy **AU**).
3. **SQS** — *how do I model a random alloy in a small cell?* (a special quasi-random structure that
   mimics a disordered solid solution — e.g. Li(Ni,Mn,Co)O₂ — in a finite supercell).

---

## Design decisions (locked with the user, 2026-06-19)
1. **All three are async JOBS**, not synchronous tools — they are CPU-heavy (many force evaluations /
   parallel optimizers). They reuse the existing job system: `JobType` → `queue.py` → `runners.py` →
   a **pure service** in `services/simulation/`, returning the standard `{status, message, files}` dict.
2. **Phonons & Mechanical use the ML potential** already in the image (MatterSim / MACE via
   `calculator_factory`) — no DFT, no VASP run needed for the property itself.
3. **SQS uses ATAT `mcsqs`** (user's choice over pure-Python `icet`) — matches the reference workflow
   exactly. This requires **compiling ATAT into the Docker image** (the only step needing a Dockerfile
   change) and adapting the notebook's interactive/parallel monitor loop to the job system
   (`ProgressReporter` + cooperative `JobCancelled` + the existing wall-clock cap).
4. **Mechanical needs NO new Python deps** (pure ASE + pymatgen + numpy) — it ships and is testable on
   the **current** image. **Phonons** adds `phonopy` + `seekpath`. **SQS** adds the ATAT binaries.
5. **`elastool` is NOT used** — the reference notebook `pip install`s it but never calls it; the
   elastic tensor is hand-rolled with numpy. We keep that (lean).
6. **Build order = least → most infra risk** (Mechanical → Phonons → SQS), so each step is
   independently shippable and image rebuilds happen **only when the user asks**.
7. **Incremental** — one verifiable step + one commit each (no AI attribution), plus a beginner-
   friendly `stepN_explanation.md`. **Bugs the user has seen are tackled AFTER the three tools.**

---

## The 8 wiring touch-points per tool (mirrors the existing `optimize` / `md` jobs)
1. `domain/jobs.py` — new `JobType` (`ELASTIC`, `PHONON`, `SQS`)
2. `services/simulation/<name>.py` — new **pure service** → `{status, message, files}`
3. `jobs/runners.py` — dispatch branch + `@celery_app.task` + artifact-kind keys
4. `jobs/queue.py` — `TASK_NAMES` + `_run_inline` map entries
5. `tools/contracts.py` — Pydantic input model
6. `agent/tool_registry.py` — `_TOOL_SPECS` entry (auto-drives planner prompt + `ToolStatus` label)
7. `tools/material_tools.py` — thin adapter (validate → `_enqueue_job`), reusing
   `_resolve_structure` / `_enforce_atom_cap` / `_resolve_calculator`
8. `requirements.txt` / `Dockerfile` — deps (Steps 2 & 3 only)

---

## Build order (one commit per step; rebuild image only on request)
| Step | Tool | New deps | Doc |
|---|---|---|---|
| 1 | **`compute_elastic_tensor`** (Mechanical) — relax cell → symmetry-refine → 6 strain modes × 4 strains → ions-only relax each → fit 6×6 **C** → Voigt/Reuss/Hill → **K, G, E, ν, Pugh, AU** | none (runs on current image) | `step1_explanation.md` |
| 2 | **`compute_phonons`** (Phonopy) — supercell → finite displacements → forces via ML potential → force constants → seekpath band + mesh DOS → `phonon_band_dos.png` + `phonopy.yaml` | `phonopy`, `seekpath` | `step2_explanation.md` |
| 3 | **`generate_sqs`** (ATAT mcsqs) — parse disordered CIF → sublattices → `rndstr.in`/`sqscell.out` → NN-shell cutoff → `corrdump`/`getclus` → N parallel `mcsqs` (monitored, cancellable, wall-clock capped) → best `bestsqs` → **POSCAR** | ATAT binaries in Dockerfile | `step3_explanation.md` |
| 4 | Frontend surfacing (artifact kinds for plots/data; tool labels come free from the registry) + ONE image rebuild + smoke test | — | `step4_explanation.md` |

---

## Interactive → parameters (de-interactiving the notebooks)
The reference notebooks ask via `input()`; in Materia these become **job params** chosen by the agent:
- **Phonons:** `supercell` (default `"3 3 3"`), `disp_distance` (0.01 Å), `mesh` (20³), full seekpath
  band path by default, `calculator_type`/`model`.
- **Mechanical:** `fmax`, strain amplitudes (`±0.005, ±0.01`), `calculator_type`/`model`.
- **SQS:** `target_comp`, `supercell`, `cutoff` (auto-recommended from NN-shell analysis if omitted),
  `n_parallel`, `target_objective`.

## Things we must add that the notebooks lack
- **SQS `bestsqs → POSCAR` converter** — the reference calls `convert_bestsqs_to_poscar(...)` but never
  defines it; we write it.
- **SQS monitor loop** rewritten off the notebook's bare `signal`/`while` into the job's
  `ProgressReporter`, cooperative `JobCancelled`, and `settings.max_job_wallclock_s`.

---

## Open question (resolve at Step 1)
- **2D materials for the elastic tensor:** bulk-3D only for the first pass, or also handle 2D
  (in-plane-only moduli, near-zero out-of-plane C-components)? Default assumption: **3D only**, add a
  guard/warning for clearly 2D cells.

---

## Not included (intentionally — deferred)
- **NEB** (climbing-image minimum-energy path) — the user will add it in a later step; needs
  initial+final structures, image interpolation, and a multi-folder `00/ 01/ …` layout.
- Any *new* tools beyond these three — after Step 5.7 the focus is **quality of existing tools**.

---

## Running verification checklist
- [ ] **Step 1** — `compute_elastic_tensor` enqueues a job; produces a symmetric 6×6 C, sensible
      K/G/E/ν/Pugh/AU for a known material (e.g. Si); atom-capped; runs on the current image.
- [ ] **Step 2** — `compute_phonons` enqueues a job; emits `phonon_band_dos.png` + `phonopy.yaml`;
      `phonopy`/`seekpath` import-guarded so code lands before the rebuild.
- [ ] **Step 3** — `generate_sqs` enqueues a job; ATAT pipeline runs end-to-end on a disordered CIF;
      best SQS converted to POSCAR; cancellable and wall-clock capped.
- [ ] **Step 4** — plots/data show in `AsyncJobsPanel`; single backend image rebuild + in-container
      smoke test (new deps import, ATAT binaries on `PATH`).
