# Step 5.7 · Step 1 — `compute_elastic_tensor` (mechanical properties)

**Status:** ✅ Done (code) · runs on the **current image** (no new dependency).

## Goal
Add the first of the three new tools: **`compute_elastic_tensor`** — measure how **stiff** and how
**ductile** a material is, using the ML potential already in the image (MACE / MatterSim). No DFT, no
VASP run needed for the property itself.

## What it computes (plain language)
Push on a crystal a little and see how hard it pushes back — that's stiffness. We do it numerically:

1. **Relax the cell** to equilibrium (shape + volume + atoms).
2. **Symmetry-refine** the relaxed cell so the strains are applied to a clean lattice.
3. Apply small **strains** (±0.5 %, ±1 %) one "mode" at a time and **relax the atoms** inside each
   strained box, reading the **stress**.
4. Because *stress = C · strain*, the **slope** of stress-vs-strain gives the **6×6 elastic tensor C**
   (in GPa). We symmetrise it.
5. From **C** we derive the engineering numbers via the Voigt/Reuss/**Hill** averages:

| Quantity | Meaning |
|---|---|
| **K** (bulk modulus) | resistance to uniform compression |
| **G** (shear modulus) | resistance to shape change |
| **E** (Young's modulus) | stiffness under stretch |
| **ν** (Poisson ratio) | how much it thins when stretched |
| **K/G** (Pugh ratio) | **> 1.75 ≈ ductile**, below ≈ brittle |
| **AU** (universal anisotropy) | how direction-dependent the stiffness is |
| Born check | eigenvalues of C all positive ⇒ **mechanically stable** |

## 2D materials (the user asked for this explicitly)
A monolayer (graphene, MoS₂) lives in a box with a big **vacuum gap** along one axis, so its
out-of-plane elastic constants are meaningless. The service **auto-detects** that case (one axis with
> 7.5 Å of vacuum) and switches mode:

- relaxes the cell **in-plane only** (freezes the vacuum direction via a `FrechetCellFilter` mask),
- strains only the in-plane modes (xx, yy, xy),
- reports **2D moduli in N/m** (1 GPa·Å = 0.1 N/m): 2D Young's modulus, 2D Poisson ratio, 2D shear
  `C66`, and the 2D layer/area modulus, with the **2D Born criteria** (C11>0, C66>0, C11·C22−C12²>0).

## How it's wired (same pattern as `optimize` / `run_md`)
It's CPU-heavy, so it's an **async job**, not a synchronous tool:

| Touch-point | Change |
|---|---|
| `domain/jobs.py` | new `JobType.ELASTIC` |
| `services/simulation/elastic.py` | **new pure service** `run_elastic(...)` |
| `jobs/queue.py` | `TASK_NAMES` + inline map entry |
| `jobs/runners.py` | dispatch branch + `@celery_app.task jobs.elastic` + artifact kinds |
| `tools/contracts.py` | `ComputeElasticInput` |
| `agent/tool_registry.py` | registry entry → planner prompt + spinner label (**14 tools total**) |
| `tools/material_tools.py` | thin adapter (validate → `_enqueue_job`); reuses atom-cap, calc-resolve, and can materialize a `material_id` to the active POSCAR first |

The service honours the job's `ProgressReporter` for **live progress** and **cooperative cancellation**
(`JobCancelled` is checked every optimizer step), and respects the atom cap before enqueueing.

## Outputs (artifacts in the job panel)
`CONTCAR` (relaxed cell) · `elastic_tensor.csv` (the 6×6 C) · `elastic_stress.csv` (raw stress vs
strain) · `mechanical_properties.json` (K/G/E/ν/… or the 2D set) · `INCAR` + `KPOINTS` (VASP `elastic`
task handoff, optional).

## Verification done
- **Property math** checked against a known cubic crystal (C11=166, C12=64, C44=80 GPa) →
  K=98.0, G=66.79, E=163.27, ν=0.2223, Pugh=1.467, stable=True ✓ (textbook values).
- **Tensor fit** round-trips synthetic `stress = C·strain` with **0.0** max error ✓.
- **2D detection**: bulk Si → 3D; graphene-like sheet → 2D (vacuum axis c) ✓.
- **Strain**: +1 % xx grows `a` from 5.43 → 5.4843 Å ✓.
- Registry builds (14 tools, callable), Celery task `jobs.elastic` registered, worker-side import OK ✓.

## Note on rebuilds
**No image rebuild needed** for this step — it uses only ASE + pymatgen + numpy, all already in the
image. Phonons (Step 2) is the first one that adds a dependency.
