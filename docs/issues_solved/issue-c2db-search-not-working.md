# Issue — C2DB search not working (2D materials never returned)

**Date solved:** 2026-07-03
**Area:** backend search / Docker deployment
**Reported by:** PhD-student testing

---

## Symptom
Searching for a 2D material (e.g. "MoS2 as a 2D material") never returned C2DB
results. Either nothing from C2DB showed up at all, or the user got Materials
Project (bulk/3D) hits instead of the 2D monolayer they asked for. No error was
shown — the search just silently skipped C2DB.

## Root cause (why the bug came)
Two independent problems stacked on top of each other:

1. **The C2DB database file was never inside the running container.**
   `data/c2db/c2db.db` (71 MB) lives at the **repo root**, but the backend image
   is built from the `./backend` context, so `COPY . .` never baked it in. And
   `docker-compose.yml` mounted `pre_trained_models` and `storage` into the
   `api`/`worker` services but **not** the C2DB db. Inside the container the code
   looks for `C2DB_DB=/data/c2db/c2db.db`, found nothing, so `is_available()`
   returned `False` and C2DB was skipped on every search — silently.

2. **The `dimensionality` filter was a dead parameter.**
   Search ran the providers in a fixed "first-hit-wins" order (MP → C2DB → OQMD)
   and never looked at `dimensionality`. So even with the db mounted, whenever MP
   was configured and returned a bulk hit for the same formula, MP won and C2DB
   was never reached — the "2D" request had no effect.

## How we fixed it
1. **Mounted the db read-only into both services** (`docker-compose.yml`):
   `- ./data/c2db:/data/c2db:ro` on `api` and `worker`. Matches the code's
   default `C2DB_DB` path, so no env var change was needed. Kept as a mount
   (not baked into the image) because it's large, static, read-only data.

2. **Made 2D queries prefer C2DB** (`backend/app/services/search/service.py`):
   added an `_is_2d()` helper and a `_2D_ORDER` (C2DB → MP → OQMD). `search()`
   now uses that order when `dimensionality` is 2D, and the default bulk-first
   order otherwise.

3. **Taught the agent to set `dimensionality='2D'`** for 2D/monolayer requests
   (`backend/app/agent/tool_schemas.py` tool description +
   `backend/app/tools/contracts.py` field description), otherwise the reorder
   never triggers.

## Files changed
- `docker-compose.yml` — C2DB volume mount on `api` + `worker`
- `backend/app/services/search/service.py` — 2D-aware provider ordering
- `backend/app/agent/tool_schemas.py` — search_materials description
- `backend/app/tools/contracts.py` — `dimensionality` field description

## How to verify
```bash
docker compose up -d --build
docker compose exec api ls -la /data/c2db/c2db.db      # mount present
# In the app: "find me MoS2 as a 2D material" → results should say source: C2DB
```
Isolated check:
```
_is_2d: "2D"/"2d"/"2" → True ; "3D"/None → False
dim='2D' → C2DB tried first ; dim='3D'/None → MP first (default order)
```

## Lesson
A provider that's "available only if a file exists" fails **silently** when that
file isn't shipped — always confirm large data assets are actually mounted into
the container, not just present in the repo. And a query parameter that no code
reads is worse than no parameter: it looks supported but does nothing.
