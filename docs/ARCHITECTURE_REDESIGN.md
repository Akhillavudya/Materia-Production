# Materia — Production Architecture Review & Redesign

> Status: **Design proposal (no code).** Target: reduce the platform to four
> production tools — `search_materials`, `generate_vasp_inputs`,
> `optimize_structure`, `run_md_simulation` — on a maintainable, scalable,
> correct, deployable foundation.

---

## 1. Executive Summary

The codebase has already had one restructure (clean `api / agent / core /
database / repositories / schemas / services / tools` layering). The layering is
sound. The **problems are not the folders — they are four architectural gaps**:

1. **No async job model.** `optimize_structure` and `run_md_simulation` run
   inside the HTTP/SSE request via `loop.run_in_executor(None, …)`. A
   10,000-step MD holds an HTTP connection (and a default-pool thread) open for
   minutes-to-hours, on the same process that serves chat. No persistence, no
   recovery, no cancellation, no progress, no GPU isolation. **This is the #1
   production blocker.**
2. **Tool sprawl + dead code.** 11 registered tools where the spec wants 4. The
   agent (`graph.py`) still carries ~14 phantom tool names
   (`generate_vasp_workflow_of_eos`, `…_neb`, `…_sqs`, surface-slab, defects…)
   in its guard sets — none of those functions exist. POSCAR generation is split
   across `generate_poscar`, `generate_vasp_poscar` (alias),
   `customize_vasp_kpoints_with_accuracy`, and `generate_vasp_inputs_from_poscar`.
3. **MaterialCard is an un-validated dict** duplicated three times across MP /
   C2DB / OQMD with inconsistent keys (`c2db_uid` vs `c2db_url`, `oqmd_url`
   present only for OQMD, `magnetic` is `str(...)` in C2DB but `None` elsewhere).
4. **VASP generation is incomplete and non-portable.** No POSCAR or POTCAR
   output from the input generator, no band-structure/DOS tasks, and hardcoded
   `NCORE=4`/`NPAR=4` that will mis-parallelise or crash on other machines.

The redesign keeps the good layering, **removes ~7 tools**, introduces a
**unified `MaterialCard` Pydantic model**, a **provider-based search layer**, a
**complete VASP input package**, and a **persistent async job system** for the
two long-running tools.

---

## 2. Current Architecture (as-is)

```
Browser (React/Vite)
   │  POST /api/chat  (SSE stream)
   ▼
FastAPI app  ──► LangGraph agent (planner→step_picker→tool_executor→…)
                     │  Ollama qwen3:14b plans JSON via regex extraction
                     ▼
              material_tools.py  (11 tools, one file)
                     ▼
              services/  search, vasp(incar/kpoints), optimization, md, calc factory
                     ▼
              SQLite (users, sessions, messages, api_keys)  +  per-session file dir
```

What works and stays:
- Layer separation `api → services → repositories`, `agent → tools → services`.
- Auth (JWT), Fernet-encrypted per-user API keys, rate limiting, structured logging.
- ASE optimization/MD services and the MACE/MatterSim calculator factory are
  *functionally* solid — they just run in the wrong place (inline) and emit
  ad-hoc dicts.
- Per-session storage directory with path-safety guards.

What is broken or redundant — see §3.

---

## 3. Dead Code & Redundancy (remove / merge)

| Item | Location | Action | Reason |
|---|---|---|---|
| `generate_poscar` | `material_tools.py` | **Merge** into `generate_vasp_inputs` | POSCAR is just one of the VASP inputs |
| `generate_vasp_poscar` (alias) | `material_tools.py`, `tool_registry.py` | **Delete** | Pure alias |
| `customize_vasp_kpoints_with_accuracy` | `material_tools.py` | **Merge** into `generate_vasp_inputs` | KPOINTS is part of the input set |
| `generate_vasp_inputs_from_poscar` | `material_tools.py` | **Replace** with `generate_vasp_inputs` | Doesn't emit POSCAR/POTCAR |
| `list_files` / `read_file` / `rename_file` | `material_tools.py` | **Demote** to plain REST endpoints, not agent tools | File I/O is not a scientific tool; the agent shouldn't plan it |
| `list_available_calculators` | `material_tools.py` | **Demote** to a metadata REST endpoint | Reference data, not a workflow step |
| `POSCAR_REQUIRED_TOOLS`, `NEEDS_POSCAR`, NEB guard | `graph.py` | **Delete** | Reference ~14 functions that no longer exist |
| `generate_vasp_poscar` API-key guard + `mp_api_key` kwarg | `graph.py` | **Delete/rewrite** | Bug: `generate_poscar` doesn't accept `mp_api_key`; guard targets dead alias |
| `get_c2db_structure` compat alias | `search_service.py` | **Delete** | Unused |
| Inline `loop.run_in_executor(None, …)` for optimize/MD | `graph.py` | **Replace** with job dispatch | See §11 |
| `materia.db`, `masgent.db` committed | repo root | **Delete + gitignore** | Already staged for deletion; never commit DBs |
| `frontend/src/api.js` (flat) + `frontend/src/api/*` | frontend | **Delete** flat `api.js` | Superseded by `api/` slices |

Net tool count: **11 → 4** agent tools, with file/calculator utilities moved to
REST endpoints the UI calls directly.

---

## 4. Target System Architecture

Three planes: **Web/API**, **Agent/Orchestration**, **Compute (workers)**.
The key change is that compute is split off the request path.

```
                         ┌───────────────────────────────────────────┐
                         │                BROWSER (React)             │
                         │  chat stream · file panel · job dashboard  │
                         └───────────────┬───────────────────────────┘
                                         │ HTTPS
              ┌──────────────────────────┼──────────────────────────────┐
              │                    FASTAPI (web)                          │
              │  /auth  /chat(SSE)  /sessions  /files  /keys  /jobs       │
              │     │                  │                        │         │
              │     │            Agent (tool-calling)           │         │
              │     │   search_materials ─┐  generate_vasp_inputs (sync)  │
              │     │   optimize_structure├─► enqueue Job ──┐    │         │
              │     │   run_md_simulation ─┘                │    │         │
              └─────┼───────────────────────────────────────┼────┼───────┘
                    │                                        │    │
            ┌───────▼────────┐                       ┌───────▼────▼──────┐
            │  PostgreSQL     │◄──────status/results──┤   Job Queue        │
            │ users/sessions/ │                       │ (Redis broker)     │
            │ messages/keys/  │                       └───────┬────────────┘
            │ jobs            │                               │ dispatch
            └───────┬─────────┘                       ┌───────▼────────────┐
                    │                                  │  COMPUTE WORKER(s) │
            ┌───────▼─────────┐                        │ GPU-pinned process │
            │ Object/File store│◄──artifacts───────────┤ ASE + MACE/MatterSim│
            │ (per-session dir │                        │ writes progress→DB │
            │  / S3 later)     │                        │ writes files→store │
            └──────────────────┘                        └────────────────────┘
```

Responsibilities by layer:

- **API layer (`api/`)** — thin HTTP. Validates request schemas, enforces
  auth/ownership, calls a service or the agent, streams SSE. No business logic.
- **Agent layer (`agent/`)** — turns a natural-language turn into an ordered call
  of the **four** tools. Fast tools (`search_materials`, `generate_vasp_inputs`)
  execute inline and return data. Long tools (`optimize_structure`,
  `run_md_simulation`) **enqueue a Job and return a `job_id` immediately**.
- **Tool layer (`tools/`)** — the four public tool functions. Pure adapters:
  validate args → call a service / enqueue a job → return a typed result. No ASE,
  no HTTP, no SQL.
- **Service layer (`services/`)** — all domain logic: search providers, VASP
  generation, ASE optimization/MD. Pure Python, framework-agnostic, unit-testable.
- **Job system (`jobs/`)** — queue, worker entrypoint, and runners that invoke
  the simulation services and persist progress/artifacts.
- **Repositories (`repositories/`)** — every SQL query, including `jobs`.
- **Domain models (`schemas/` + `domain/`)** — Pydantic request/response **and**
  the cross-cut
  ting `MaterialCard`, `JobRecord`, `VaspInputSet`.

---

## 5. Target Folder Structure

```
backend/app/
├── main.py
├── core/                       # cross-cutting infra (unchanged role)
│   ├── config.py               # Settings (+ REDIS_URL, JOB_BACKEND, STORAGE_ROOT)
│   ├── security.py  encryption.py  limiter.py  logging.py
│
├── api/                        # thin HTTP only
│   ├── deps.py
│   ├── auth.py  chat.py  keys.py  upload.py
│   ├── files.py                # NEW: list/read/rename/download (moved off agent)
│   ├── jobs.py                 # NEW: GET /jobs, /jobs/{id}, /jobs/{id}/stream, cancel
│   └── catalog.py              # NEW: GET /calculators, /vasp/tasks (reference data)
│
├── agent/
│   ├── graph.py                # 4-tool planner; long tools enqueue jobs
│   ├── llm.py                  # provider client (see §15 on Claude tool-calling)
│   └── tool_registry.py        # exactly 4 tools, schema derived from Pydantic
│
├── tools/                      # 4 adapters only
│   ├── material_tools.py       # search_materials, generate_vasp_inputs,
│   │                           #   optimize_structure, run_md_simulation
│   └── contracts.py            # Pydantic in/out models for each tool
│
├── domain/                     # framework-agnostic core models
│   ├── material_card.py        # the unified MaterialCard (§7)
│   ├── vasp.py                 # VaspTask enum, VaspInputSet, CellRelax enum
│   └── jobs.py                 # JobType, JobStatus enums, JobSpec/JobResult
│
├── services/
│   ├── search/                 # SEARCH LAYER (§8)
│   │   ├── base.py             # MaterialProvider protocol
│   │   ├── providers/
│   │   │   ├── mp.py  c2db.py  oqmd.py
│   │   ├── mappers.py          # raw source dict → MaterialCard
│   │   └── service.py          # priority orchestration MP→C2DB→OQMD
│   │
│   ├── vasp/                   # VASP GENERATION (§9)
│   │   ├── poscar.py  incar.py  kpoints.py  potcar.py
│   │   ├── templates.py        # task presets: static/relax/band/dos
│   │   └── service.py          # build_input_set(structure, task, options)
│   │
│   ├── simulation/            # OPTIMIZATION + MD (§10)
│   │   ├── calculator_factory.py
│   │   ├── optimization.py     # run_optimization (pure compute)
│   │   ├── md.py               # run_md (pure compute)
│   │   └── plots.py
│   │
│   ├── storage/
│   │   └── file_service.py     # session dirs, artifact paths, path safety
│   └── key_service.py
│
├── jobs/                       # ASYNC EXECUTION (§11)
│   ├── queue.py                # enqueue/inspect (Celery or ARQ wrapper)
│   ├── worker.py               # worker entrypoint (separate process)
│   ├── runners.py              # optimize_job / md_job: service + DB progress
│   └── progress.py             # ProgressReporter → jobs table + SSE channel
│
├── repositories/
│   ├── user_repository.py  session_repository.py
│   ├── message_repository.py  api_key_repository.py
│   └── job_repository.py       # NEW
│
├── schemas/                    # HTTP request/response DTOs
│   └── auth.py chat.py key.py upload.py job.py(NEW) material.py(NEW)
│
└── database/
    ├── db.py  models.py        # + Job model
    └── migrations/             # NEW: Alembic
```

Frontend gains one feature folder: `features/jobs/` (job dashboard already
exists as `sessions/JobDashboard.jsx` — formalise it against `/api/jobs`).

---

## 6. Data Flow Diagrams

### 6.1 Search → VASP inputs (synchronous, fast)

```
User: "generate VASP relaxation inputs for MoS2"
  │
  ▼ agent plan = [search_materials, generate_vasp_inputs]
search_materials(formula=MoS2)
  │  SearchService: MP.search → (empty?) → C2DB.search → (hit)
  │  mappers → list[MaterialCard]
  ▼  returns top card  (id="c2db-…", source="c2db")
generate_vasp_inputs(material_id=…, source=…, task="relaxation")
  │  SearchService.get_structure(card) → pymatgen Structure
  │  VaspService.build_input_set(structure, task=relaxation, cell_relax=full)
  │     ├─ poscar.py   → POSCAR
  │     ├─ incar.py    → INCAR  (NCORE auto from settings, MAGMOM, ENCUT)
  │     ├─ kpoints.py  → KPOINTS
  │     └─ potcar.py   → POTCAR.spec  (element→PBE potential + ENMAX; metadata only)
  ▼  writes to <session>/vasp_inputs/<task>/ ; returns VaspInputSet summary
```

### 6.2 Optimization / MD (asynchronous, long)

```
User: "relax it with MACE to 0.01 eV/Å"
  │
  ▼ agent → optimize_structure(...) tool
tool validates args → JobRepo.create(job_type=optimize, status=queued, spec=…)
  │                    queue.enqueue(optimize_job, job_id)
  ▼ returns { job_id, status:"queued" }  (HTTP returns in ms)
agent streams: "Started optimization — job <id>. Track it in the dashboard."

        ── meanwhile, separate WORKER process ──
worker picks job → status=running
  run_optimization(structure, fmax, optimizer, calc) 
     every N steps → ProgressReporter.update(job_id, step, energy, fmax)
                          → UPDATE jobs SET progress=… ; PUBLISH job:<id>
  on finish → write CONTCAR/traj/energy.csv/plots to <session>/optimization/
              status=succeeded, result=summary, artifacts=[…]

Frontend: GET /api/jobs/{id}/stream (SSE) → live step/energy/fmax + final files
```

---

## 7. Unified `MaterialCard` Model

One Pydantic model, produced by **every** provider via `mappers.py`. Identity is
canonical and source-routable.

```python
class Source(str, Enum):
    MP = "mp"; C2DB = "c2db"; OQMD = "oqmd"

class Dimensionality(str, Enum):
    BULK = "3D"; LAYERED = "2D"; UNKNOWN = "unknown"

class MaterialCard(BaseModel):
    # Identity
    id: str                       # canonical: "mp-19306" | "c2db-<uid>" | "oqmd-12345"
    source: Source
    source_id: str                # native id used to re-fetch the structure
    # Composition
    formula: str                  # reduced/pretty, e.g. "MoS2"
    elements: list[str]
    n_atoms: int | None
    dimensionality: Dimensionality = Dimensionality.UNKNOWN
    # Electronic / energetics (all eV or eV/atom, None if unavailable)
    band_gap_eV: float | None = None
    formation_energy_eV_per_atom: float | None = None
    energy_above_hull_eV_per_atom: float | None = None
    energy_per_atom_eV: float | None = None
    is_stable: bool | None = None
    # Structure / symmetry
    spacegroup_symbol: str | None = None
    spacegroup_number: int | None = None
    magnetic: bool | None = None
    density_g_cm3: float | None = None
    has_structure: bool = True
    # Provenance
    source_url: str | None = None
    retrieved_at: datetime
```

Rules:
- Missing data is `None`, never `0` or `"None"` (fixes the C2DB `str(...)` bug).
- `id` always round-trips: `SearchService.get_structure(id)` parses the prefix to
  route to the right provider — no `source` ambiguity, no `_infer_source` guessing.
- Energies normalised to **eV / eV-per-atom** across all sources in `mappers.py`.

---

## 8. Search Layer Design

Provider pattern. Each source implements one interface; the service composes them
by priority and normalises everything to `MaterialCard`.

```python
class MaterialProvider(Protocol):
    source: Source
    def is_available(self) -> bool: ...                 # key present / db file / reachable
    def search(self, q: MaterialQuery) -> list[MaterialCard]: ...
    def get_structure(self, source_id: str) -> Structure | None: ...
```

- `providers/mp.py` — Materials Project via `mp_api`. Requires user key (injected
  by `key_service`). Bulk/3D.
- `providers/c2db.py` — local ASE `.db`. 2D materials. No network.
- `providers/oqmd.py` — OQMD REST. No key. **Wrap network in a timeout + async
  client**; today's blocking `urllib` + 120 s timeout must not sit on an event
  loop thread. Move OQMD calls behind `httpx.AsyncClient` or run in the worker.

**Interaction policy (priority + fallback, configurable):**

```
search_materials(query):
    order = [MP, C2DB, OQMD]                 # priority from spec
    for provider in order:
        if not provider.is_available(): record_skipped; continue
        cards = provider.search(query)
        if cards: return Result(cards, source_used=provider.source, tried=…)
    return Result([], source_used=None, tried=…)
```

- Default = **first-hit wins** (current behaviour, matches the spec's priority).
- Add an optional `mode="aggregate"` that merges across sources and dedupes by
  reduced formula + spacegroup, sorted by `energy_above_hull` — useful when the
  user wants the *best* structure regardless of source. Off by default.
- Provider failures are isolated: one source erroring never aborts the chain;
  the error is recorded in `sources_tried` and the next source runs.

---

## 9. VASP Generation Design

Single entry point produces the **complete** input set; templates per task.

```python
class VaspTask(str, Enum):
    STATIC = "static"; RELAXATION = "relaxation"
    BAND = "band"; DOS = "dos"
    # (md_nvt / md_npt handled by the MD service, not user-facing VASP gen)

class VaspService:
    def build_input_set(self, structure, task: VaspTask,
                        cell_relax: CellRelax = "none",
                        overrides: dict | None = None) -> VaspInputSet
```

Outputs written to `<session>/vasp_inputs/<task>/`:
- **POSCAR** — from `poscar.py` (pymatgen `Poscar`).
- **INCAR** — `incar.py` merges `_COMMON + task_template + cell_relax(ISIF) +
  magnetism + overrides`. **Fixes:** `NCORE` derived from
  `settings.vasp_ncore` (default = auto/unset, not hardcoded 4); add `band` (ICHARG=11,
  LORBIT=11, line-mode) and `dos` (NEDOS, ISMEAR=-5, denser k-mesh) templates.
- **KPOINTS** — `kpoints.py`. Gamma mesh by density; line-mode path for `band`
  (via pymatgen `HighSymmKpath`); denser regular mesh for `dos`.
- **POTCAR.spec** (metadata only — never ship licensed POTCARs) — `potcar.py`
  emits, per element: recommended PBE potential label (e.g. `Mo_pv`, `S`),
  `ENMAX`, valence count, and the implied `ENCUT` floor. A real POTCAR is only
  assembled if the deploy provides a licensed `PMG_VASP_PSP_DIR`.
- **input_summary.json** — machine-readable manifest (task, ISIF, ENCUT, k-mesh,
  element potentials) for the UI and for downstream provenance.

Validation: reject unknown task/cell_relax, warn on metals with `ISMEAR=0`,
ensure `ENCUT ≥ max(ENMAX)` from POTCAR spec.

---

## 10. Optimization & MD Service Design

The existing `optimization.py` / `md.py` compute logic is good and stays largely
intact, with three changes:

1. **Pure compute, no I/O policy.** They accept a `Structure` (or path) + config
   and a `progress_callback`, and return a typed `JobResult`. They do **not**
   decide where files go — the runner passes the output dir.
2. **Progress callback.** Replace the silent in-memory `energy_log` append with
   `progress_callback(step, energy, fmax/temperature)` so the worker can persist
   live progress (every `log_interval`) to the `jobs` table + SSE channel.
3. **Calculator config validated up front.** `calculator_factory` already
   resolves MACE (primary) / MatterSim (fallback). Add an explicit
   *primary→fallback* policy: if MACE load fails, log and fall back to MatterSim
   only when `allow_fallback=True`.

Outputs unchanged (CONTCAR, trajectory.traj/.xyz, energy.csv, plots, optional
VASP handoff inputs) but written under the **job's** artifact directory.

---

## 11. Job Execution Architecture (async)

The core fix. Long tools become jobs; the web process never blocks.

**Components**
- **Broker/queue:** Redis + a Python task framework. Recommendation: **Celery**
  (mature, mature GPU-worker story) or **ARQ** (async-native, lighter). Either
  reads `JOB_BACKEND` from config; default Celery.
- **`jobs` table = source of truth** (not the broker). The broker only carries
  "run job X"; all state lives in Postgres so status survives restarts.
- **Worker process(es):** separate from the web app, GPU-pinned. Each runner:
  1. marks `running`, 2. loads structure, 3. runs the simulation service with a
  `ProgressReporter`, 4. writes artifacts to the session store, 5. marks
  `succeeded`/`failed` with a result summary.
- **Progress + live updates:** `ProgressReporter` writes throttled progress to
  `jobs.progress` and `PUBLISH`es to a Redis channel `job:<id>`; the API's
  `GET /jobs/{id}/stream` (SSE) relays it to the dashboard.

**Lifecycle**

```
queued ──pick──► running ──ok──► succeeded
   │                │
   │ cancel         ├─error──► failed
   ▼                └─timeout─► failed (max wall-clock from JobSpec)
 cancelled
```

**Tool behaviour change**

```
optimize_structure(...) / run_md_simulation(...):
    spec = build JobSpec from validated args (+ resolved input structure path)
    job  = JobRepo.create(user, session, type, spec, status=queued)
    queue.enqueue(runner, job.id)
    return { "job_id": job.id, "status": "queued", "track": "/api/jobs/<id>" }
```

The agent then says *"started optimization, job &lt;id&gt;"* instead of stalling
the stream. Idempotency: a `(session, type, spec_hash)` dedupe key prevents
double-submits on retry.

**Why not FastAPI BackgroundTasks?** They die with the web process, share its
event loop/GPU, can't be cancelled or surveyed, and don't survive a deploy.
Unacceptable for multi-minute GPU jobs.

---

## 12. Database Design

Keep `users / sessions / messages / api_keys`. Add **`jobs`**. Move to
**PostgreSQL** for production (SQLite write-locking is unsafe with a separate
worker writing progress concurrently). Introduce **Alembic** migrations.

```
jobs
─────────────────────────────────────────────────────────────────────
 id              UUID  PK
 user_id         FK users.id            (index)
 session_id      FK sessions.id         (index)
 type            ENUM(optimize, md)
 status          ENUM(queued,running,succeeded,failed,cancelled)  (index)
 spec            JSONB                  # validated tool args + input path
 progress        JSONB                  # {step, total, energy, fmax|temp, pct}
 result          JSONB  NULL            # summary: final_energy, converged, …
 artifacts       JSONB  NULL            # [{name, rel_path, kind}]
 error           TEXT   NULL
 calculator      JSONB                  # {type, model, device}
 spec_hash       STRING (index)         # idempotency / dedupe
 created_at  started_at  finished_at    DATETIME
 INDEX (session_id, created_at), (user_id, status)
```

Optional later: `material_cache` (source, source_id, card JSONB, fetched_at) to
avoid re-hitting MP/OQMD for repeat searches.

`messages.tool_result` stays for chat replay; job-heavy results live in `jobs`
and are referenced by `job_id`.

---

## 13. API Contracts

Existing (keep): `/api/auth/*`, `/api/chat` (SSE), `/api/sessions*`,
`/api/files/*`, `/api/keys*`, `/api/upload`.

New / changed:

```
# Reference data (was agent tools)
GET  /api/calculators                 → {mace:[…], mattersim:[…]}  (availability)
GET  /api/vasp/tasks                  → [static, relaxation, band, dos] + option schema

# Jobs
GET  /api/jobs?session_id=&status=    → [JobRecord]                 (owned by user)
GET  /api/jobs/{id}                   → JobRecord (status, progress, result, artifacts)
GET  /api/jobs/{id}/stream            → SSE: progress events + terminal status
POST /api/jobs/{id}/cancel            → 202; sets status=cancelled / signals worker
# (jobs are *created* by the agent tools, not by a public POST, to keep the
#  agent the single orchestrator; a direct POST /api/jobs can be added later)

# Files (moved off the agent)
GET  /api/sessions/{id}/files[/grouped]
GET  /api/files/content/{rel_path}    GET /api/files/download/{rel_path}
POST /api/files/{rel_path}/rename
```

`JobRecord` response = projection of the `jobs` row (no internal spec_hash).

SSE event contract for `/chat` stays, with one addition: when a long tool is
dispatched, emit `data: [JOB:{json}]` carrying `{job_id, type, status}` so the
frontend can attach the dashboard without parsing prose.

---

## 14. Tool Contracts (the four)

All four defined as Pydantic in/out models in `tools/contracts.py`; the
`tool_registry` schema is **derived from these** (no hand-written `arg_desc`
drift). `status` is always one of `ok | not_found | invalid | error` (+ `queued`
for the async pair).

### 14.1 `search_materials`
```
in:  formula?:str  element?:str  elements?:list[str]
     min_gap?:float  max_gap?:float  max_formation_e?:float
     dimensionality?: "2D"|"3D"  limit:int=10  mode:"first"|"aggregate"="first"
out: { status, source_used: Source|None, sources_tried:[Source],
       materials: list[MaterialCard], total_matching:int, returned:int, message }
```

### 14.2 `generate_vasp_inputs`
```
in:  material_id?:str  source?:Source           # OR
     poscar_path?:str                            # use an existing session structure
     task: "static"|"relaxation"|"band"|"dos" = "relaxation"
     cell_relax: "none"|"shape"|"full" = "none"
     overrides?: dict                            # raw INCAR tag overrides
out: { status, task, files:{poscar,incar,kpoints,potcar_spec,summary},
       encut:int, kmesh:[int,int,int], elements:[…], message }
```
Exactly one of (`material_id`+`source`) or `poscar_path` required.

### 14.3 `optimize_structure`  *(async → job)*
```
in:  poscar_name?:str  fmax:float=0.02
     cell_relax:"none"|"shape"|"full"="none"
     optimizer:"FIRE"|"BFGS"|"LBFGS"="FIRE"  max_steps:int=1000
     calculator_type:"mace"|"mattersim"="mace"  calculator_model?:str
     allow_fallback:bool=true  emit_vasp_inputs:bool=true
out: { status:"queued", job_id, type:"optimize", track:"/api/jobs/<id>", message }
final (via job): { converged, steps, final_energy, final_fmax, formula,
                   n_sites, elapsed_s, artifacts:{contcar,trajectory,energy_csv,…} }
```

### 14.4 `run_md_simulation`  *(async → job)*
```
in:  poscar_name?:str  ensemble:"nvt"|"npt"="nvt"
     temperature:float=300  nsw:int=10000  timestep:float=1.0
     thermostat:str="langevin"  pressure:float=0.0
     calculator_type:"mace"|"mattersim"="mace"  calculator_model?:str
     log_interval:int=10  emit_vasp_inputs:bool=true
out: { status:"queued", job_id, type:"md", track:"/api/jobs/<id>", message }
final (via job): { steps_completed, total_time_ps, formula, n_sites,
                   final_energy, mean_temperature, ensemble, thermostat,
                   elapsed_s, artifacts:{trajectory,energy_csv,temp_csv,
                   plots,contcar,…} }
```

Input-structure resolution (`auto`, CONTCAR-vs-POSCAR preference) moves into
`storage/file_service` as one well-tested helper, shared by both tools.

---

## 15. Agent & LLM Notes

- The planner is a hand-rolled state machine driving Ollama `qwen3:14b` with
  **regex JSON extraction** — brittle, and the prompt still references dead tools.
  Rebuild the registry around the four tools with schemas derived from the
  Pydantic contracts.
- For production-grade, reliable structured tool-calling, the strongest option is
  **native tool use via the Claude API** (`claude-opus-4-8` for hard planning,
  `claude-haiku-4-5` for cheap/fast routing) instead of regex-parsing a local
  model's free text. Keep the provider behind `agent/llm.py` so Ollama stays a
  drop-in for local/offline dev and Claude is the hosted default. This removes
  the entire fragile "extract `[...]` from prose" path.
- Tool-result envelopes should be uniform (`status/message/data`) so the
  summarizer is template-driven (it already is for the happy path).

---

## 16. Scalability, Correctness, Deployment

- **Process model:** `web` (gunicorn/uvicorn, N replicas) + `worker` (1..M,
  GPU-pinned, concurrency=1 per GPU) + Redis + Postgres. Web and worker share the
  service layer code but run independently — a stuck MD can't take down chat.
- **Storage:** keep per-session dirs for dev; abstract behind `storage/` so S3 +
  signed URLs drop in for multi-node prod (workers and web won't share a local FS).
- **Correctness:** Pydantic at every boundary (tool args, MaterialCard, JobSpec);
  no more ad-hoc dicts. Energies normalised in one place (`mappers.py`).
- **Observability:** structured logs already exist; add `job_id` to the log
  context and a `/healthz` (web + worker + redis + db).
- **Config additions:** `REDIS_URL`, `JOB_BACKEND`, `STORAGE_BACKEND`,
  `STORAGE_ROOT`, `VASP_NCORE`, `MAX_JOB_WALLCLOCK_S`, `PMG_VASP_PSP_DIR`(opt).

---

## 17. Phased Migration (no big-bang)

1. **Domain models** — add `MaterialCard`, `VaspInputSet`, `JobSpec/Record`
   Pydantic models; wire `mappers.py` so search returns real cards. (No behaviour
   change for users.)
2. **Tool consolidation** — collapse the 4 POSCAR/VASP tools into
   `generate_vasp_inputs`; delete aliases and the dead guard sets in `graph.py`;
   move file/calculator utilities to REST.
3. **Search providers** — split `search_service.py` into `search/providers/*` +
   `service.py`; make OQMD non-blocking.
4. **Job system** — add `jobs` table + Alembic + Redis + worker; convert
   `optimize_structure` / `run_md_simulation` to enqueue; add `/api/jobs*` and the
   dashboard SSE.
5. **VASP completeness** — POTCAR spec, band/dos templates, portable NCORE.
6. **Agent** — Claude tool-calling provider behind `agent/llm.py`; retire regex
   planning.
7. **Postgres + S3** — flip config for multi-node deploy.

Each phase is independently shippable and testable.
```

