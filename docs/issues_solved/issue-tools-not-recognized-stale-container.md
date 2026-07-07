# Issue: agent says `generate_poscar()` / `search_materials()` "not recognized"

## Symptom
In the chat (screenshot, `localhost:5173` dev UI), after confirming a plan the agent
replied in prose instead of calling a tool:

> "The function `generate_poscar()` is not recognized in the provided tools, and the
> argument `structure_id` is not valid for any available function."

> "The function `search_materials()` is not recognized in the provided toolset. The
> available functions that accept a `source` parameter are: `compute_elastic_constants`,
> `compute_phonons`, `generate_sqs` ..."

Note the tell-tale signs: it named a **non-existent** tool (`compute_elastic_constants`
— the real one is `compute_elastic_tensor`) and claimed those tools take a `source`
parameter (they don't). That is the model **confabulating** tool names, not the backend
missing a tool.

## Root cause
The tool registry was **not** actually broken. Verified against the current code:

- `backend/app/agent/tool_schemas.py` registers all **23** tools; `search_materials`
  and `generate_poscar` are both present and produce valid JSON Schema.
- `graph.py` always passes the full `TOOL_SPECS` to the provider
  (`provider.run(conv, TOOL_SPECS, ...)`); the `ENABLE_HEAVY_TOOLS` gate only appends a
  system-prompt note, it never removes tool schemas.

So the tools were always declared. The symptom came from the **runtime**, not the schema:
the running backend serving that dev session was out of sync with the fixed source (a
stale process from mid-edit), and/or the BYOK LLM returned a degraded/hallucinated turn
that refused the call and invented tool names. Either way the model was not faithfully
using the tool list it was given.

## How we fixed it
Rebuilt the full-web Docker images from the fixed source and recreated the app
containers so the live backend matches the code, then **verified inside the container**
that the agent is handed all 23 tools:

```
docker exec api python -c "from app.agent.tool_schemas import TOOL_NAMES; print(len(TOOL_NAMES))"
# -> 23, incl. search_materials + generate_poscar; enable_heavy_tools: True
```

`postgres` + `redis` were kept (data preserved); `api`/`worker`/`caddy` were recreated
from the new `materia-backend:dev` / `materia-frontend:dev` images, reusing the same
`JWT_SECRET_KEY` + `FIELD_ENCRYPTION_KEY` so logins and saved BYOK keys still work.

## Files changed
No source fix was required for this symptom — the schemas were already correct. The
resolution was operational (rebuild + recreate). Related UX edits already in the working
tree (`graph.py` active-structure injection, `planner.py` context) are separate.

## How to verify
1. Open `http://localhost:8080`, sign in (invite `lab2026`), add a BYOK LLM key in Settings.
2. Ask: "search Al2Mg2S5" → agent calls `search_materials` and returns a table.
3. Ask: "generate poscar of c2db-12868" → agent calls `generate_poscar` (no "not recognized").

## Lesson
When the agent claims a **core** tool is "not recognized" and lists **made-up** tool
names/params, suspect a **runtime mismatch or a bad LLM turn**, not the schema — confirm
first with `docker exec api python -c "...TOOL_NAMES..."`. Editing source never changes an
already-running container: after any fix you must **rebuild the image AND recreate the
container** (see memory `step5-5-local-run`). A stale `api` process is the most common
cause of "my fix didn't take".
