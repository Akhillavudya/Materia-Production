# 2026-06-22 — NEB correctness fixes (climb, reaction coordinate, endpoints, warnings)

**Area:** `backend/app/services/simulation/neb.py` (ML-potential NEB migration-barrier service)
**Context:** hardening the NEB tool before the desktop-app build. Resolves the deferred review
findings from 2026-06-20 (climb-off, reaction-coordinate PBC, endpoint handling).

---

## Symptoms / risks
1. **Climbing image silently never activated** for small step budgets, so the reported barrier was a
   lower bound — yet the run could still print "with climbing image".
2. **Reaction coordinate (MEP x-axis) distorted** whenever the migrating atom crossed a periodic
   cell boundary — exactly the diffusion/hop case NEB is for.
3. **Endpoints had to be VASP-format** (`read(..., format="vasp")`), so a CIF endpoint failed.
4. Both endpoints relaxed into the **same overwritten log**; endpoint convergence wasn't reported.
5. A meaningless barrier (barrierless path / saddle at an endpoint / unconverged band) was reported
   **without any warning**.

## Root causes
1. `climb_start_steps` was hard-coded to 200 and clamped to `max_steps`. With `max_steps ≤ 200`,
   phase A consumed the whole budget and the `if opt.nsteps < max_steps` gate was False → climb off.
2. `_reaction_coordinate` summed raw `norm(cur − prev)` with no minimum-image convention.
3. `read(..., format="vasp")` forced one format.
4. One shared `endpoint_relax.log`; no `converged()` capture.
5. No post-run sanity checks.

## Fixes
- **Climb budget:** replaced `climb_start_steps` with `climb_fraction` (default 0.5, clamped
  0.1–0.9). Phase A runs for `int(max_steps * climb_fraction)` steps, so phase B (climb on) **always**
  gets budget. Phase-A force target is clamped to never be tighter than the final `fmax`.
- **Reaction coordinate:** use `ase.geometry.find_mic` (minimum-image) per image step; falls back to
  raw Cartesian if unavailable. Verified: a hop across the boundary now reads 0.5 Å, not 4.5 Å.
- **Endpoint reading:** new `_read_structure()` goes through `pymatgen.Structure.from_file`
  (auto-detects POSCAR/CONTCAR/CIF/XYZ/JSON).
- **Endpoint relax:** per-endpoint log (`endpoint_initial_relax.log` / `endpoint_final_relax.log`)
  and `endpoint_converged` captured + reported.
- **Sanity warnings:** `summary["warnings"]` (and appended to the message) for: saddle-at-endpoint /
  barrierless; band not converged within `max_steps`; climb requested but never activated; an
  endpoint that didn't finish relaxing. Also reject identical endpoints (same coords, different file).

## Verify
- Helpers unit-tested: MIC coordinate (0.5 vs 4.5 Å), identical-endpoint rejection, POSCAR+CIF read.
- Full end-to-end MACE run (Al, n_images=3, max_steps=6): `climb_used=True` (would have been False
  under the old code), all artifacts written (path CSV, saddle POSCAR, traj, MEP plot, results JSON),
  and the warnings correctly fired for the deliberately under-converged run.

## Still open (intentionally not changed)
- **Per-job wallclock for heavy NEB on the server** (Bug 2 from the review): a single NEB can hold a
  one-worker queue for up to `max_job_wallclock_s` (24 h). Left as-is because the app is moving to a
  **desktop / single-user** model where this multi-tenant concern doesn't apply. Revisit if NEB is
  ever exposed on the shared Oracle deployment.

## Lesson
Two-phase optimizers must budget by *fraction*, never an absolute step count that can swallow the
whole run. And any periodic-cell distance (reaction coordinate, displacement) must use the
minimum-image convention — raw Cartesian silently lies the moment an atom wraps an edge.
