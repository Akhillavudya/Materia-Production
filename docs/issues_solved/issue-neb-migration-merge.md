# Merge migration-path + NEB into one tool (drop auto-supercell, add images/animation, Hessian, VASP decks)

## Symptom
NEB was split across **two** tools in both the chat agent and the manual panel:
`compute_neb` (the barrier job) and `list_migration_paths` (a hop-listing preview).
The NEB card already listed hops internally, so the standalone "Migration Paths"
card was redundant and confusing. NEB also silently **auto-grew a supercell**
("hop space"), which diverged from the PhD advisor's VTST workflow (the user
prepares the cell). Finally, the intermediate NEB images were never surfaced, there
was no transition-state confirmation, and no VASP decks for a cluster run.

## Root cause (why it was like this)
The migration-path preview and the auto-supercell were added early to make the
element-mode NEB "just work" without the user thinking about cell size. That
convenience turned into two problems: (1) a second agent tool the model had to
choose between (and sometimes mis-picked), and (2) a hidden cell change that made
the reported barrier depend on an invisible heuristic instead of the user's cell —
the opposite of the VTST recipe (`nebmake.pl A B N` on a fixed, user-prepared box).

## How we fixed it
- **One tool everywhere.** Removed `list_migration_paths` from the agent
  (`tool_registry.py` + `tool_schemas.py`) and deleted the manual "Migration Paths"
  card. Kept the `list_migration_paths` Python function + `/migration-paths`
  endpoint purely as the NEB card's "List hops" helper.
- **Removed auto-supercell** everywhere (`neb_path.supercell_for_migration`
  deleted; `auto_supercell`/`min_cell_length` dropped from the tool, contracts,
  HTTP routes, and frontend). The small-cell warning now points users to
  `make_supercell` instead of the removed heuristic.
- **Intermediate images** — `_write_outputs` now writes a nebmake-style `neb/00..0N/
  POSCAR` chain plus **one** `neb_path.xyz` animation (all frames). The 3D viewer
  detects `.xyz` and plays it as a looping trajectory (`addModelsAsFrames` +
  `animate`).
- **Transition-state confirmation (Step 5)** — `_saddle_frequencies` runs an ASE
  finite-difference Hessian on the saddle image (cell fixed, positions only) over
  the migrating atom + nearest neighbours; **exactly one imaginary mode = true TS**.
- **Energy-profile categorization** — `_classify_profile` labels the MEP as
  single-peak / symmetric double-well ("M") / asymmetric multi-peak.
- **VASP decks per stage** — `_write_vasp_inputs` emits endpoint-relax (ISIF=3 / 2),
  NEB (IMAGES/SPRING/LCLIMB, IBRION=3), and Hessian (IBRION=5) decks, bundled with
  the image folders into `neb_vasp_inputs.zip`.
- New params `run_frequencies` / `emit_vasp_inputs` (default true) gate the last two,
  plumbed through the tool, contract, HTTP route, and job runner.

## Files changed
- `backend/app/services/simulation/neb_path.py` — deleted `supercell_for_migration`.
- `backend/app/services/simulation/neb.py` — new `_classify_profile`,
  `_saddle_frequencies`, `_write_vasp_inputs`; `_write_outputs` writes 00..0N +
  `neb_path.xyz`; new `run_frequencies`/`emit_vasp_inputs`/`migrating_element`
  params; reworded small-cell warning; report + summary carry profile/TS verdict.
- `backend/app/tools/material_tools.py` — dropped supercell from
  `list_migration_paths`/`_build_neb_endpoints`/`compute_neb`; added the two new
  gates; `migrating_element` passed into job params.
- `backend/app/tools/contracts.py` — updated `ComputeNebInput` /
  `ListMigrationPathsInput`.
- `backend/app/agent/tool_registry.py`, `tool_schemas.py` — removed the
  `list_migration_paths` agent tool (both places, to satisfy the drift guard).
- `backend/app/api/upload.py` — updated both NEB routes.
- `backend/app/jobs/runners.py` — new artifact kinds + plumb new params.
- `frontend/src/api/neb.js`, `features/sessions/toolForms.js`,
  `ToolLaunchPanel.jsx`, `AsyncJobsPanel.jsx`,
  `features/viewer/StructureViewer.jsx`.

## How to verify
1. App import: the `graph.py` drift guard passes with 23 tools (was 24);
   `compute_neb` present, `list_migration_paths` gone from registry + schemas.
2. Manual NEB card, **element mode**, on a cell already ≥ ~8 Å: job yields
   `neb/00..0N/POSCAR`, `neb_path.xyz` (animates in the viewer), `neb_mep` plot,
   `saddle_frequencies.csv` with an imaginary-mode verdict, `profile_type` in the
   summary, and `neb_vasp_inputs.zip` with endpoint/NEB/Hessian INCARs.
3. Two-file mode: same outputs, no supercell.
4. "List hops" still returns ranked pairs; picking a chip fills source/dest.
5. Agent chat: a migration-barrier request calls `compute_neb` directly.
6. Toggling frequencies/VASP-decks off produces a clean run without those artifacts.

## Lesson
A "helpful" hidden transformation (auto-supercell) and a second discoverability
tool (the hop preview) each looked convenient in isolation but pulled the workflow
away from the established VTST recipe and gave the agent an extra branch to get
wrong. Collapsing to one tool over a user-prepared cell made behaviour predictable
and matched the domain workflow. When you remove a hidden safety net, replace it
with an explicit, actionable warning (here: "run make_supercell first") rather than
silence — and always edit `tool_registry.py` **and** `tool_schemas.py` together so
the import-time drift guard stays green.
