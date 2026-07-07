# NEB migration barrier comes out several times too high (3.7 eV vs 0.4 eV)

## Symptom
Running the NEB tool on a migration hop returned a **forward barrier ≈ 3.7 eV**
when the expected (reference / DFT) value was **≈ 0.4 eV** — nearly an order of
magnitude too high. When asked, the model explained it as the migrating ion not
having enough **"hop space"**, which was the right instinct but the tool did
nothing about it.

## Root cause (why the bug came)
A NEB barrier is only meaningful if **both endpoints are true local minima of the
same potential, measured in the same box, in a cell big enough that the moving ion
and the vacancy it leaves do not interact with their own periodic images.** The
reference notebook (`NEB.ipynb`) satisfied all of that by hand; Materia's tool did
not:

1. **No hop space (dominant cause).** The tool built the vacancy-mediated
   endpoints from *whatever structure was active* — usually a unit cell or a small
   DFT cell. In a small box the moving ion squeezes straight past its neighbours
   (and sees its own periodic image), so the saddle-point energy is spuriously
   huge. The notebook always started from a large supercell (`POSCAR_opt`, ~48
   atoms).
2. **Endpoints not relaxed to true minima.** The tool relaxed each endpoint with a
   single loose FIRE pass to `fmax = 0.05` at a **fixed cell**. The notebook did a
   two-stage **FIRE (0.1) → BFGS (0.03)** relaxation, and relaxed the **cell** of
   the initial endpoint too. Endpoints left off their minima give wrong reference
   energies `E[initial]`/`E[final]`, and a strained band on top.
3. **Climbing image amplified the error.** With the band starting from a bad,
   strained geometry, the climbing image dutifully pinned one image to the
   (inflated) saddle — making the wrong barrier look "converged".

The vacancy-mediated **endpoint geometry itself was already correct** (remove the
destination atom; move the source atom into it) — matching the notebook. Only the
*preparation* was missing.

## How we fixed it
Made the migration/NEB workflow satisfy every criterion automatically ("full auto"
prep), matching the notebook recipe:

- **Auto-supercell for hop space** — `neb_path.supercell_for_migration()` grows the
  cell so every lattice vector ≥ `min_cell_length` (default **8 Å**), capped to the
  server atom limit. `list_migration_paths` and `compute_neb` apply the **same**
  supercell so the site labels the user picks line up with the endpoints built.
- **Deep, shared-cell endpoint relaxation** in `neb.py` — full **cell+ion** relax
  of the initial endpoint (`FrechetCellFilter`) to reach the MLP's equilibrium box,
  copy that box onto the final endpoint (`set_cell(..., scale_atoms=True)`), then
  ion-only relax the final. Each stage is **FIRE (0.1) → BFGS (`endpoint_fmax`,
  default 0.03)**.
- **Defaults + guardrails** — default images 7 → **8**; a **hop-space warning** when
  the shortest lattice vector < 8 Å (covers the two-file mode where the user brings
  their own endpoints); new params surfaced: `auto_supercell`, `min_cell_length`,
  `endpoint_fmax`.
- **Manual tools** — a new **Migration Paths** card lists candidate hops, and the
  **NEB** card gained an "auto-build from a migrating element" mode where clicking a
  hop chip sets source→dest. New `POST /sessions/{id}/migration-paths`; `/neb`
  extended to accept a hop.

## Endpoint criteria (what any structure needs for a correct barrier)
1. Initial & final share the **same box, same atom count, same composition**.
2. Both are **true local minima of the same MLP** you run NEB with (relax to
   `fmax ≤ 0.03`).
3. The base is a **supercell** large enough (each lattice vector ≳ 8–10 Å, ~2× the
   hop distance) so the ion + vacancy don't self-interact.
4. The base **cell is at the MLP's equilibrium** (relax cell+ions before building
   endpoints).
5. A **short, nearest-neighbour hop** (the shortest candidate pair).

If a user brings their **own optimised** initial+final files (two-file mode), prep
is skipped — but the same five criteria must already hold, and the tool now warns
when the cell looks too small or an endpoint didn't converge.

## Files changed
- `backend/app/services/simulation/neb_path.py` — `supercell_for_migration()`.
- `backend/app/services/simulation/neb.py` — `_relax_endpoint()` two-stage relax,
  shared-cell recipe, hop-space warning, `endpoint_fmax` param, default images 8.
- `backend/app/tools/material_tools.py` — supercell prep in `list_migration_paths`
  + `_build_neb_endpoints`; `auto_supercell`/`min_cell_length`/`endpoint_fmax` on
  `compute_neb`.
- `backend/app/tools/contracts.py` — new fields on `ComputeNebInput` /
  `ListMigrationPathsInput`.
- `backend/app/jobs/runners.py` — pass `endpoint_fmax`; default images 8.
- `backend/app/api/upload.py` — `POST /migration-paths`; `/neb` hop mode.
- `frontend/src/api/neb.js` — `listMigrationPaths()` + two-mode `launchNeb()`.
- `frontend/src/features/sessions/toolForms.js` — Migration Paths card + expanded
  NEB card.
- `frontend/src/features/sessions/ToolLaunchPanel.jsx` — list-hops button, hop
  chips, NEB element/files mode.

## How to verify
1. **Unit geometry** (no MLP needed):
   ```python
   from app.services.simulation import neb_path
   from pymatgen.core import Structure, Lattice
   s = Structure(Lattice.cubic(3.0), ['Mg','Mg'], [[0,0,0],[0.5,0.5,0.5]])
   sc, f = neb_path.supercell_for_migration(s, min_cell_length=8.0, max_atoms=200)
   # → factors (3,3,3), 54 atoms, abc ≈ 9 Å
   ini, fin = neb_path.build_migration_endpoints(sc, 'Mg', 1, 28)
   # → 53 atoms each, identical cell
   ```
2. **End-to-end**: run `compute_neb(migrating_element="Mg")` (or the Migration
   Paths → NEB cards) on the notebook's SSE system with the shortest NN hop; the
   forward barrier should drop from ~3.7 eV toward ~0.4 eV, and the convergence
   report should show the supercell factor + tight endpoint relax.
3. Frontend: pick element → **List hops** → click a chip → **Run NEB**; confirm the
   job enqueues and the message reports the auto-built hop + supercell.

## Lesson
For any defect-migration barrier, the **hard part is preparing the cell, not
running the band**: a big-enough supercell + endpoints relaxed to a tight `fmax` in
one shared, equilibrium cell. A wrong-by-10× barrier is almost always an
unprepared cell (no hop space) or unconverged endpoints — not the NEB itself. Bake
the preparation into the tool so the user gets the notebook-quality answer by
default.
