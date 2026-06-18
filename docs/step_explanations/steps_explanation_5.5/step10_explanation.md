# Step 5.5 · Step 10 — Frontend surfacing

**Status:** ✅ Done

## Goal
Make sure the new tools show up sensibly in the UI.

## What we found (and why this step is small)
- **There is no VASP task/modifier form to update.** Materia's UI is **chat-driven** — the user types a
  request and the LLM agent chooses the task + modifiers. The `/api/vasp/tasks` endpoint exists for a
  possible future form, but **nothing in the frontend consumes it**, so there was nothing to wire.
- The one place tools *do* surface is the **live tool spinner** in chat (`ToolStatus.jsx`), which shows
  a friendly label while each tool runs.

## The real fix: stale tool labels
`ToolStatus.jsx`'s `TOOL_LABELS` map was **out of date** — it still listed *pre-redesign* tool names
(`generate_vasp_poscar`, `generate_supercell_from_poscar`, …) that no longer exist. Current tools fell
back to auto-formatting their function name. We replaced the map with the **current 13 tools**,
including the 5 new ones (`build_structure`, `analyze_symmetry`, `create_vacancy`,
`create_substitution`, `create_interstitial`), so the spinner reads cleanly, e.g. "Creating vacancy
defect…". Labels mirror those in `app/agent/tool_registry.py`.

## What we deliberately left alone
- **`JobDashboard.jsx`** also has a stale `TOOL_LABELS`, but it is about **async jobs** — only
  `optimize_structure` / `run_md_simulation` ever become jobs. The new VASP/structure tools are
  **synchronous** (never jobs), so they never appear there. Updating it is unrelated to Step 5.5 and
  would risk an unrelated `job.tool_name` cleanup, so it's out of scope.

## What changed
- **`frontend/src/features/chat/ToolStatus.jsx`** — replaced the stale `TOOL_LABELS` with the current
  13-tool map.

## Verified
- `TOOL_LABELS` parses to 13 keys; all 5 new tools present. ✅
- ESLint passes on the file (exit 0). ✅
- Full frontend build is exercised by the Step 11 Docker image rebuild.
