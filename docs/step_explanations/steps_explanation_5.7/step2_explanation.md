# Step 5.7 · Step 2 — `compute_phonons` (phonon band structure + DOS)

**Status:** ✅ Done (code) · **needs an image rebuild** to ship (adds `phonopy` + `seekpath`).

## Goal
Add the second tool: **`compute_phonons`** — compute a material's **vibrational spectrum** (phonon band
structure + density of states) and tell whether it is **dynamically stable**, using finite
displacements + the ML potential already in the image (MACE / MatterSim). No DFPT, no DFT.

## What it computes (plain language)
Atoms in a crystal jiggle like masses on springs. The allowed jiggle frequencies are the **phonons**.

1. Build a **supercell** (default 3×3×3) so we capture long-wavelength (low-frequency) modes.
2. **Displace** atoms by a tiny 0.01 Å in each symmetry-unique way.
3. Compute the **forces** that the displacements create — this is the heavy loop, one ML force eval
   per displaced supercell.
4. Phonopy converts forces → **force constants** (the spring stiffnesses).
5. Evaluate them along an automatic high-symmetry **band path** (picked by **seekpath**) and on a
   q-mesh for the **DOS**.
6. Plot band + DOS side by side; save `phonopy.yaml` and CSVs.

**Stability signal:** if the lowest frequency is clearly **negative (imaginary)** — below −0.10 THz —
the structure is **dynamically unstable** at that geometry. We surface `min_frequency_THz` and
`has_imaginary_modes` in the result. (Tiny negative values near the acoustic Γ point are numerical
noise and are *not* flagged.)

## How it's wired (async job, same 8 touch-points)
| Touch-point | Change |
|---|---|
| `domain/jobs.py` | new `JobType.PHONON` |
| `services/simulation/phonon.py` | **new pure service** `run_phonon(...)` |
| `jobs/queue.py` | `TASK_NAMES` + inline map entry |
| `jobs/runners.py` | dispatch branch + `@celery_app.task jobs.phonon` + artifact kinds |
| `tools/contracts.py` | `ComputePhononInput` (supercell / disp_distance / mesh) |
| `agent/tool_registry.py` | registry entry → planner + spinner (**15 tools total**) |
| `tools/material_tools.py` | adapter; parses `"3 3 3"`, can materialize a `material_id`, and applies the atom cap to the **supercell** size |
| `requirements.txt` | **`phonopy`, `seekpath`** added |

The force loop reports progress per displaced supercell and is **cancellable** (`JobCancelled`).

### One important difference from the other tools: the atom cap
A phonon supercell *multiplies* the atom count: a 4-atom cell at 3×3×3 = 108 atoms. So the adapter caps
on `n_primitive × Nx×Ny×Nz` (not the input cell) and rejects oversized supercells up front with a clear
message, protecting the shared worker.

## Outputs (artifacts in the job panel)
`phonon_band_dos.png` (band + DOS plot) · `phonopy.yaml` (force constants + metadata, re-loadable) ·
`phonon_band.csv` (distance + every branch) · `phonon_dos.csv` (frequency, DOS).

## Verification done (real local run — venv has phonopy/seekpath/MACE)
Ran the full pipeline on silicon (no mocks):
- **Bad (compressed) test cell** → min freq −7.74 THz, flagged **unstable** — proving the service
  faithfully reflects the input geometry.
- **Correct Si primitive cell, 3×3×3 (54 atoms)** → min freq **−0.009 THz** (not flagged),
  `has_imaginary_modes = False` ✓ (Si *is* stable), and **max band frequency 14.84 THz** vs the
  experimental Si optical phonon ≈ 15.5 THz — excellent ML agreement ✓.
- All four artifacts written (yaml 9 KB, dos 3.7 KB, band 34 KB, **png 156 KB**) ✓.
- Registry builds (15 tools, callable), Celery task `jobs.phonon` registered ✓.

## Note on rebuilds
This step **adds two dependencies** (`phonopy`, `seekpath`), so it goes live only after the next
**image rebuild** — which we'll batch with Step 3 (ATAT) at the end, per the user's "don't rebuild
every time" rule. The code is import-guarded, so until then the tool returns a friendly
"Missing dependency" instead of crashing. (Locally these libs are already in the venv, hence the live
test above.)
