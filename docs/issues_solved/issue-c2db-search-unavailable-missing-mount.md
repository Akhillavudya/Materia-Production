# Issue: C2DB search "unavailable" in the Docker stack (Al2Mg2S5 not found)

## Symptom
On the Docker stack (`:8080`), searching a 2D material such as `Al2Mg2S5` returned
`not_found`. The backend log showed:

```
Search: mp unavailable, skipping
Search: c2db unavailable, skipping
tried: ['mp', 'c2db', 'oqmd']  ->  returned 0
```

The same search on the dev backend (`:5173` / uvicorn `:8000`) worked fine and returned
`c2db-12868` (Al2Mg2S5, 2D, P-3m1).

## Root cause
Two independent "unavailable" reasons in the container:
- **c2db unavailable** — the `api`/`worker` containers had **no `/data/c2db` mount**. The
  provider checks `os.path.exists(C2DB_DB)` (default `/data/c2db/c2db.db`); with nothing
  mounted the file is absent, so `is_available()` is `False` and C2DB is skipped. The
  containers were started with a manual `docker run` whose mount list omitted the C2DB
  volume that `docker-compose.yml` defines (`./data/c2db:/data/c2db:ro`).
- **mp unavailable** — no server-side `MP_API_KEY`; Materials Project search is BYOK
  (per-user key), so with no user key in that code path MP is skipped too. That part is
  by design.

The dev backend worked because `backend/.env` sets `C2DB_DB` to the host file
(`.../data/c2db/c2db.db`) and holds an `MP_API_KEY`.

## How we fixed it
Recreated `api` and `worker` from `materia-backend:dev` adding the missing volume (Postgres
+ Redis kept, same secrets reused):

```
-v /home/roy/Desktop/Materia-Production/data/c2db:/data/c2db:ro
```

Default `C2DB_DB=/data/c2db/c2db.db` already matches the mount target, so no env change was
needed.

## Files changed
No source change. Operational fix (added a bind mount when recreating the containers).
Memory `step5-5-local-run` updated to list the C2DB mount as REQUIRED on both api+worker so
it stops getting dropped on future rebuilds.

## How to verify
```
docker exec api sh -c 'ls -l /data/c2db/c2db.db'        # file present
docker exec api python - <<'PY'
import tempfile
from app.services.storage.file_service import set_session_dir
set_session_dir(tempfile.mkdtemp())
from app.tools.material_tools import search_materials, generate_poscar
r = search_materials(formula='Al2Mg2S5', limit=5)
print(r['status'], r['source_used'], r['returned'])          # ok c2db 1
c = r['materials'][0]
print(generate_poscar(material_id=c['id'], source=c['source'])['status'])  # success
PY
```

## Lesson
The `search_materials` provider chain fails **silently** ("... unavailable, skipping") when
a data source isn't wired up — a `not_found` can mean "data not mounted", not "material
doesn't exist". When recreating containers by hand, mirror **all** volumes from
`docker-compose.yml` (models, POTCAR, **and C2DB**), not just the ones you remember. C2DB is
the only free/local search source; without its mount, every 2D-only material looks missing.
