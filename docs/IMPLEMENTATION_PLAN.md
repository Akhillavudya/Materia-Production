# Materia — From-Scratch Implementation Plan

> **What this document is.** A phase-by-phase blueprint for building Materia *from
> day one*, in the order I would build it if I were starting today with an empty
> repository. It is **not** a history of how the code actually evolved — it is the
> clean, dependency-driven path. Every file path named here is a **real path that
> exists in the repo today**, so you can map each step onto the running system.
>
> **How to read it.** Each phase has: a one-line **Goal**, a plain-language
> **Why this comes here** (the learning angle), the **Files you create** (with the
> job each file does), and a **Verify before moving on** checkpoint. Build phases
> in order — each one only depends on the phases above it, never below.
>
> **Out of scope (on purpose).** Production hardening — the managed-Postgres + S3
> object-storage "ops flip" — is intentionally left out. That becomes a later
> phase you will add when you are ready to deploy. Everything below runs locally
> on SQLite + the filesystem.

---

## The mental model (read this first)

Materia is an **AI chat assistant for computational materials science**. A user
talks to it in plain English ("relax MoS2 with MACE", "make VASP inputs for
mp-19306"); an LLM decides which **tools** to call; the tools do real
materials-science work (search databases, write VASP input files, run ML-potential
simulations); long simulations run as **async jobs** so the chat never blocks.

The whole system is built in **layers**, and we build from the bottom up because
each layer only knows about the ones below it:

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React)         ← Phase 9                          │
├─────────────────────────────────────────────────────────────┤
│  API routers (FastAPI)    ← spread across phases             │
│  Agent (LLM + tool loop)  ← Phase 8                          │
│  Tools (4 core actions)   ← Phase 6                          │
│  Async jobs (Celery)      ← Phase 7                          │
│  Services (search/vasp/simulation/storage)  ← Phase 5        │
│  Domain models            ← Phase 5                          │
│  Persistence + Auth       ← Phases 2–4                       │
│  Core (config/logging)    ← Phase 1                          │
│  Scaffolding              ← Phase 0                           │
└─────────────────────────────────────────────────────────────┘
```

**Golden rule of the layering:** the web process must stay lightweight. Heavy
scientific libraries (ASE, MACE, pymatgen calculators) are only imported inside
the **job worker**, never at the top of an API file. You will see this rule
enforced again and again below — it is why simulations are jobs, not direct calls.

---

## Phase 0 — Project scaffolding & configuration

**Goal:** an empty-but-runnable skeleton: folders, dependency lists, environment
template, and a `.gitignore` that protects secrets.

**Why this comes here.** Before any code, you fix *where things live* and *how
secrets are kept out of git*. Getting this right once saves you from leaking a
`.env` or committing a 600 MB SQLite file later.

**Files you create**

| File | What it does |
|------|--------------|
| `backend/requirements.txt` | The full Python dependency list, grouped by purpose: web (`fastapi`, `uvicorn`), persistence (`sqlalchemy`, `alembic`, `asyncpg`), jobs (`celery[redis]`), auth (`passlib`, `python-jose`, `cryptography`), LLM (`google-genai`, `ollama`), and the materials-science core (`ase`, `pymatgen`, `mp-api`, `chgnet`, `mattersim`). |
| `backend/.env.example` | A committed *template* of every environment variable the app reads (DB URL, JWT secret, Gemini key, Redis URL…). Real values live in `backend/.env`, which is **git-ignored**. |
| `.gitignore` | Blocks `.env`, `storage/`, `*.db`, `venv/`, `__pycache__/`, and nested `.git` folders — the secret-and-bloat shield. |
| `backend/README.md`, `README.md` | One-line pointers so the repo is self-describing. |
| `frontend/package.json` | Declares the React 19 + Vite frontend and its markdown/math render deps (`react-markdown`, `remark-gfm`, `katex`). |
| `frontend/vite.config.js`, `frontend/index.html`, `frontend/eslint.config.js` | Vite dev-server config, the HTML entry point, and lint rules. |

**Verify before moving on:** `pip install -r backend/requirements.txt` succeeds in
a fresh `venv`, and `npm install` succeeds in `frontend/`. Nothing runs yet — you
are only proving the toolchain is sane.

---

## Phase 1 — Core backend skeleton

**Goal:** a FastAPI app that boots and answers `GET /`, with centralized config,
logging, rate-limiting, and the cryptographic primitives everything else reuses.

**Why this comes here.** Every later layer reads configuration and writes logs. If
config is scattered (each module calling `os.getenv` its own way) you get drift and
bugs. So we make **one** settings object and **one** logging setup first.

**Files you create**

| File | What it does |
|------|--------------|
| `backend/app/__init__.py`, `backend/app/main.py` | The **application factory**. `main.py` builds the `FastAPI` app, wires CORS + the rate-limit middleware, includes every router under `/api`, and runs `init_db()` on startup. Right now it only mounts `GET /`. |
| `backend/app/core/config.py` | The single `Settings` object. Reads the environment **once** and exposes typed fields + smart properties: `resolved_provider` (gemini vs ollama auto-detect), `database_url` / `database_url_sync` (async vs sync driver), `is_postgres`. **Per-user** secrets are deliberately *not* here. |
| `backend/app/core/logging.py` | `configure_logging()` + `get_logger(__name__)` — uniform structured logs across web and worker. |
| `backend/app/core/limiter.py` | The SlowAPI rate limiter instance shared by the app and route decorators. |
| `backend/app/core/security.py` | Password hashing (bcrypt via passlib) and JWT encode/decode helpers. |
| `backend/app/core/encryption.py` | Symmetric field encryption (Fernet) for secrets stored in the DB — used later to encrypt user API keys at rest. |
| `backend/app/core/context.py` | Request-scoped `ContextVar`s carrying the current user id / session id, so deep service code can know "who am I acting for" without threading it through every call. |

**Plain-language note.** Think of Phase 1 as laying the *utilities* of a house —
electricity (config), plumbing (logging), and locks (security/encryption) — before
any rooms exist.

**Verify before moving on:** `uvicorn app.main:app` starts and `curl localhost:8000/`
returns `{"message": "Materia backend is running"}`.

---

## Phase 2 — Database & persistence

**Goal:** define the data model, an async DB engine, repositories that own all SQL,
and Alembic migrations so the schema is versioned.

**Why this comes here.** Auth, sessions, messages, and jobs all need tables. We
introduce persistence before the features that use it, and we hide raw SQL behind
**repositories** so the rest of the app never writes queries inline.

**Files you create**

| File | What it does |
|------|--------------|
| `backend/app/database/models.py` | SQLAlchemy ORM tables: `User`, `Session`, `Message`, `ApiKey`, `Job`. Uses a `JSONType` that becomes indexable `JSONB` on Postgres but plain `JSON` on SQLite, and stores naive-UTC timestamps consistently. |
| `backend/app/database/db.py` | The async engine + session factory and `init_db()` (creates tables for dev). One place that reads `settings.database_url`. |
| `backend/app/database/__init__.py` | Package marker / convenience exports. |
| `backend/alembic.ini`, `backend/app/database/migrations/env.py`, `…/script.py.mako` | Alembic config + environment so schema changes are real, reviewable migration files, not silent `create_all`. |
| `backend/app/database/migrations/versions/651c27ad893e_initial_schema_with_jobs.py` | The **initial migration** that creates all five tables — your schema "version 1". |
| `backend/app/repositories/__init__.py` | Package marker. |
| `backend/app/repositories/user_repository.py` | All reads/writes for users (lookup by email, create). |
| `backend/app/repositories/session_repository.py` | Chat-session CRUD (create, list by user, rename, delete). |
| `backend/app/repositories/message_repository.py` | Append + fetch chat messages for a session. |
| `backend/app/repositories/api_key_repository.py` | Store/fetch per-user encrypted provider keys. |
| `backend/app/repositories/job_repository.py` | CRUD for `Job` rows — the persistence half of the async system (Phase 7 builds on this). |

**Signal to watch (the learning angle):** consistency of **timezone-aware vs naive
datetimes**. We standardize on naive-UTC everywhere; mixing the two is a classic
source of "off by a timezone" bugs.

**Verify before moving on:** `alembic upgrade head` creates `materia.db` with all
five tables; a throwaway script can insert and read a `User` through the repository.

---

## Phase 3 — Authentication & per-user API keys

**Goal:** users can register, log in (JWT), and store their own provider keys
(e.g. Materials Project) encrypted at rest.

**Why this comes here.** Every meaningful action is scoped to a user, and some
tools need the *user's own* Materials Project key. With persistence (Phase 2) and
crypto (Phase 1) in place, auth is now a thin layer on top.

**Files you create**

| File | What it does |
|------|--------------|
| `backend/app/schemas/__init__.py`, `backend/app/schemas/auth.py` | Pydantic request/response shapes for register/login/token. |
| `backend/app/schemas/key.py` | Shapes for setting/listing user API keys. |
| `backend/app/api/deps.py` | FastAPI dependencies: `get_db`, `get_current_user` (decodes the JWT and loads the user). Reused by every protected route. |
| `backend/app/api/auth.py` | `/api/auth/*` — register, login, "who am I". Issues JWTs via `core/security`. |
| `backend/app/services/key_service.py` | The bridge that, at request time, decrypts the user's stored keys and injects them into `os.environ` so downstream library calls (mp-api, Gemini) just work — keeping secrets out of global config. |
| `backend/app/api/keys.py` | `/api/keys/*` — set/list/delete the current user's provider keys (values encrypted via `core/encryption`). |

**Verify before moving on:** register → login returns a JWT → calling a protected
route with that JWT succeeds, without it returns 401. Stored keys are unreadable in
the raw DB (ciphertext, not plaintext).

---

## Phase 4 — Storage & file management

**Goal:** a per-session working directory on disk where structures and simulation
outputs live, plus endpoints to upload and download files.

**Why this comes here.** Tools and jobs (later) constantly read/write structure
files (POSCAR, CONTCAR, plots). They need a **session-scoped sandbox** and a
single helper that knows how to find "the best POSCAR" in it. Build that home
before anything writes to it.

**Files you create**

| File | What it does |
|------|--------------|
| `backend/app/services/storage/__init__.py` | Package marker. |
| `backend/app/services/storage/file_service.py` | The storage brain: `get_session_dir(session_id)`, `list_new_files(since)`, `find_best_poscar(dir)`, `rel_to_storage(path)`, plus the `_session_dir_var` ContextVar so worker threads know which session they are writing into. All run artifacts land under `app/storage/runs/<session-id>/`. |
| `backend/app/schemas/upload.py` | Pydantic shapes for upload responses. |
| `backend/app/api/upload.py` | `/api/upload` — accept a user file (e.g. a POSCAR) into the session directory. |
| `backend/app/api/files.py` | `/api/files/*` — list and download files from a session directory. |

**Plain-language note.** Each chat session gets its own folder, like a lab bench.
Tools put their results on that bench; the frontend reads from it; nothing leaks
between users because the folder is keyed by session id.

**Verify before moving on:** upload a POSCAR via `/api/upload`, then list and
download it via `/api/files`; confirm it physically exists under
`app/storage/runs/<session-id>/`.

---

## Phase 5 — Domain models & materials-science services

**Goal:** the scientific engine — typed domain objects plus the three service
families that do real work: **search** databases, **generate VASP** inputs, and
**run simulations**.

**Why this comes here.** These services are *pure* (no HTTP, no LLM) and are what
the tools in Phase 6 orchestrate. Building them before the tools means the tools
stay thin wrappers. This is the biggest phase — build it in the sub-order below.

### 5a. Domain models

| File | What it does |
|------|--------------|
| `backend/app/domain/__init__.py` | Package marker. |
| `backend/app/domain/material_card.py` | The normalized "material" record (id, formula, source, band gap, formation energy, spacegroup, dimensionality, `has_structure`) that every search provider maps *into* — one shape regardless of source. |
| `backend/app/domain/vasp.py` | Typed VASP concepts (task types: static/relaxation/band/dos; cell-relax modes) shared by the VASP service. |
| `backend/app/domain/jobs.py` | `JobType` (optimize/md) and `JobStatus` (queued/running/succeeded/failed/cancelled) enums — the shared vocabulary the job system speaks. |

### 5b. Search service (multi-provider, normalized)

| File | What it does |
|------|--------------|
| `backend/app/services/search/__init__.py` | Package marker. |
| `backend/app/services/search/base.py` | The `SearchProvider` interface every backend implements. |
| `backend/app/services/search/mappers.py` | Convert raw provider payloads → `MaterialCard`. |
| `backend/app/services/search/providers/mp.py` | Materials Project provider (uses the user's MP key). |
| `backend/app/services/search/providers/oqmd.py` | OQMD provider. |
| `backend/app/services/search/providers/c2db.py` | C2DB provider (2D materials). |
| `backend/app/services/search/service.py` | The orchestrator: takes a query (formula/element/filters), tries providers in order, merges + de-dupes into a single ranked list of cards. |

### 5c. VASP input generation

| File | What it does |
|------|--------------|
| `backend/app/services/vasp/__init__.py` | Package marker. |
| `backend/app/services/vasp/poscar.py` | Build/parse POSCAR structure files. |
| `backend/app/services/vasp/incar.py` | Build INCAR parameter files per task; portable NCORE handling (omit unless explicitly set). |
| `backend/app/services/vasp/kpoints.py` | Build KPOINTS meshes. |
| `backend/app/services/vasp/potcar.py` | Assemble a real POTCAR when a licensed PAW dir is configured; otherwise emit a `POTCAR.spec` (labels + recommended ENMAX) — POTCARs are **never** shipped. |
| `backend/app/services/vasp/templates.py` | Task presets (static/relaxation/band/dos) tying the above together. |
| `backend/app/services/vasp/service.py` | The public entry that, given a structure + task, writes the full input set into the session directory. |

### 5d. Simulation services (pure, ML-potential)

| File | What it does |
|------|--------------|
| `backend/app/services/simulation/__init__.py` | Package marker. |
| `backend/app/services/simulation/calculator_factory.py` | Resolve a user-facing model name ("MACE-MP", "MatterSim Large") into a concrete ASE calculator; the single place that knows the supported potentials. |
| `backend/app/services/simulation/optimization.py` | `run_optimization(...)` — relax a structure to a force threshold, emitting progress via a callback. Pure function: no DB, no HTTP. |
| `backend/app/services/simulation/md.py` | `run_md(...)` — NVT/NPT molecular dynamics, same callback-driven progress contract. |
| `backend/app/services/simulation/plots.py` | Turn MD/optimization CSV logs into energy/temperature PNG plots. |

### 5e. Catalog API (expose search to the frontend)

| File | What it does |
|------|--------------|
| `backend/app/schemas/material.py` | API shapes for material search responses. |
| `backend/app/api/catalog.py` | `/api/catalog/*` — lets the frontend browse/search materials directly (separate from the agent path). |

**Signal to watch:** the simulation functions take a `progress_callback` and
return a plain result dict. That **callback contract** is what lets Phase 7 stream
progress without the services knowing anything about Celery or the database.

**Verify before moving on:** from a Python REPL, search a formula and get
`MaterialCard`s; generate a VASP input set into a temp dir; run a tiny
optimization on a 2-atom cell and get a result dict + output files. All without
starting the web server.

---

## Phase 6 — Tools layer (the agent's hands)

**Goal:** wrap the Phase 5 services into a small, fixed set of **tools** with
strict typed inputs — the only actions the LLM is allowed to take.

**Why this comes here.** The agent shouldn't call services directly; it calls a
curated, validated surface. Defining tool **contracts** as the single source of
truth means the LLM's tool schema can never drift from the real function
signatures.

**Files you create**

| File | What it does |
|------|--------------|
| `backend/app/tools/__init__.py` | Package marker. |
| `backend/app/tools/contracts.py` | Pydantic input models for every tool (`SearchMaterialsInput`, `GenerateVaspInputsInput`, `OptimizeStructureInput`, `RunMdSimulationInput`, `GeneratePoscarInput`, `ReadFileInput`, `ListFilesInput`, `ListModelsInput`) + `args_and_desc()` which derives the arg list and human-readable descriptions from the model fields. **Single source of truth.** |
| `backend/app/tools/material_tools.py` | The callable tools themselves — thin functions that validate args against the contracts, call the Phase 5 services, write into the session dir, and return a result dict. The long ones (`optimize_structure`, `run_md_simulation`) don't compute inline — they **enqueue a job** (wired in Phase 7) and return a `job_id` immediately. |
| `backend/app/tools/prompt.txt` | Supporting tool/usage text. |

**Plain-language note.** A "tool" here is just a safe, well-labeled button the AI
can press. The contracts are the button's spec sheet; `material_tools.py` is the
wiring behind the button.

**Verify before moving on:** call `search_materials(formula="NaCl")` and
`generate_poscar(...)` directly as Python functions and confirm they return clean
dicts and write the expected files.

---

## Phase 7 — Async job system

**Goal:** run long simulations (optimize, MD) out-of-process so the chat responds
instantly and progress survives restarts.

**Why this comes here.** Tools exist (Phase 6) and the simulation services are
pure (Phase 5). Now we add the machinery that lets `optimize_structure` /
`run_md_simulation` return a `job_id` in milliseconds while the real work runs in a
Celery worker, with all state in the `jobs` table (not the broker) so a restart
never loses a job.

**Files you create**

| File | What it does |
|------|--------------|
| `backend/app/jobs/__init__.py` | Package marker. |
| `backend/app/jobs/queue.py` | The Celery app (Redis broker). Defines how tasks are dispatched. |
| `backend/app/jobs/store.py` | The job state machine over the DB: `load_job`, `mark_running/succeeded/failed/cancelled`, `get_status`. The worker's only way to touch job state. |
| `backend/app/jobs/progress.py` | `ProgressReporter` — the object passed as the simulation `progress_callback`; it writes progress JSON to the job row and publishes live updates. This is the bridge between pure services and the DB. |
| `backend/app/jobs/runners.py` | The actual task bodies (`run_optimize_job`, `run_md_job`): load spec → mark running → call `run_optimization`/`run_md` with a `ProgressReporter` → persist result + artifacts → mark terminal. **Only the worker imports this** (it pulls in ASE/MACE). |
| `backend/app/jobs/worker.py` | The worker entry point you launch alongside the web server. |
| `backend/app/api/jobs.py` | `/api/jobs/*` — list jobs, get one job's status/progress, fetch artifacts, cancel. What the frontend dashboard polls. |

Then go back and **wire the enqueue side** into `tools/material_tools.py`: the long
tools build a job spec, create a `Job` row via `job_repository`, dispatch the
Celery task, and return `{job_id, type, status: "queued"}`.

**Signal to watch (overfitting-of-architecture check):** notice the deliberate
split — the **web process never imports `runners.py`**. If you ever find ASE
imported at module load in an API file, the lightweight-web invariant is broken and
boot time / memory will balloon.

**Verify before moving on:** start Redis + the worker; call `optimize_structure`
through the tool — it returns a `job_id` instantly; `/api/jobs/<id>` shows
`queued → running → succeeded` with artifacts. Kill and restart the worker
mid-job: state is recovered from the DB.

> **Dev convenience:** `config.job_backend = "inline"` runs jobs in a thread with no
> broker, so you can build and test Phases 6–8 before standing up Redis.

---

## Phase 8 — Agent layer (the brain + the chat endpoint)

**Goal:** a native function-calling agent that, given the conversation and the tool
schemas, decides which tools to call, executes them, streams tokens + tool events
over SSE, and writes the final answer.

**Why this comes here.** It sits on top of *everything*: tools (6), jobs (7),
storage (4), persistence (2). With a pluggable provider, the agent defaults to
**Gemini (free)** and falls back to **Ollama** on rate limits/outages — no
regex/JSON-from-prose planning; tool calls arrive as structured data.

**Files you create**

| File | What it does |
|------|--------------|
| `backend/app/agent/__init__.py` | Package marker. |
| `backend/app/agent/providers/base.py` | The `LLMProvider` interface + the `ToolCall` data shape. Defines `run(conversation, tool_specs, on_text)` so the loop is provider-agnostic. |
| `backend/app/agent/providers/gemini.py` | Gemini provider (Google AI Studio free tier) with native function calling — the default. |
| `backend/app/agent/providers/ollama.py` | Local Ollama provider (e.g. `qwen3:14b`) — the offline fallback. |
| `backend/app/agent/llm.py` | `get_provider()` — resolves Gemini vs Ollama from `settings.resolved_provider` and owns the **Gemini → Ollama fallback** on 429/errors. |
| `backend/app/agent/tool_schemas.py` | `TOOL_SPECS` — the tool definitions in the shape providers expect, generated from the Phase 6 contracts. |
| `backend/app/agent/tool_registry.py` | Maps tool name → metadata + the callable in `material_tools`. Derived from the contracts so the schema and the executor never drift. |
| `backend/app/agent/graph.py` | The agent loop. Holds the `SYSTEM_PROMPT` (Materia's behavior rules), runs up to `MAX_TURNS` rounds of "ask model → execute tool calls → feed results back", trims tool results before sending them back to the model, and emits the SSE side-channel: `[TOOL_START]`, `[TOOL_END]`, `[FILES:…]`, `[JOB:…]`, `[DONE]`, `[SESSION:…]`. |
| `backend/app/schemas/chat.py` | Request/response shapes for the chat endpoint. |
| `backend/app/api/chat.py` | `/api/chat` — loads session history, calls `run_agent(...)`, and streams the SSE response to the browser; persists the user + assistant messages. |

**Plain-language note.** The provider is the "voice box" (talks to an LLM); the
registry/schemas are the "menu" of actions; `graph.py` is the "conductor" that
loops between thinking and doing until the assistant has a final answer. The SSE
events are how the browser shows live "⚙ Searching…", file cards, and job chips as
they happen.

**Verify before moving on:** with a `GEMINI_API_KEY` set, POST to `/api/chat`
"search for NaCl and make VASP inputs" — you should see streamed tokens, a
`search_materials` tool round, then a `generate_vasp_inputs` round, file events,
and a final Markdown table. Unset the key (or force a 429) → it falls back to
Ollama and still completes.

---

## Phase 9 — Frontend (React + Vite)

**Goal:** the chat UI: auth screen, streaming chat, structure viewer, file panel,
and the async-job dashboard.

**Why this comes here last.** It is a pure consumer of the `/api/*` contracts. With
the backend complete and streaming, the UI is "just" rendering events.

**Files you create (grouped by feature)**

| Area | Files | What it does |
|------|-------|--------------|
| Entry/shell | `frontend/index.html`, `frontend/src/main.jsx`, `frontend/src/App.jsx` | Mount React, route between landing / auth / app. |
| API client | `frontend/src/api/client.js`, `…/index.js`, `…/auth.js`, `…/chat.js`, `…/sessions.js`, `…/files.js`, `…/jobs.js`, `…/keys.js`, `…/c2db.js` | Typed fetch wrappers — one module per backend router, including the SSE parser for `/api/chat`. |
| Landing/auth | `frontend/src/features/landing/Landing.jsx` (+`.css`), `frontend/src/features/auth/AuthScreen.jsx`, `frontend/src/components/Logo.jsx` | Marketing landing + login/register. |
| Chat | `frontend/src/features/chat/Chat.jsx`, `…/ToolStatus.jsx`, `…/UploadButton.jsx`, `…/ApiKeyForm.jsx` | The streaming conversation, live tool-status chips, file upload, and the per-user key form. |
| Sessions/jobs | `frontend/src/features/sessions/Sidebar.jsx`, `…/RightPanel.jsx`, `…/AsyncJobsPanel.jsx`, `…/JobDashboard.jsx` | Chat history sidebar + the async-job dashboard that polls `/api/jobs`. |
| Files/viewer | `frontend/src/features/files/FilePanel.jsx`, `…/FileCard.jsx`, `frontend/src/features/viewer/StructureViewer.jsx` | Browse session files and render structures. |
| Styles | `frontend/src/styles/index.css`, `…/App.css` | Global + app styling; Markdown + KaTeX math rendering for assistant replies. |

**Verify the whole system:** register in the UI → ask the assistant to search a
material and generate VASP inputs → watch tool chips stream, files appear in the
panel → start an optimization → watch it move `queued → running → succeeded` in the
job dashboard and download the artifacts.

---

## Build-order cheat sheet

```
0  Scaffolding ........... requirements, .env.example, .gitignore, package.json
1  Core ................. main, config, logging, limiter, security, encryption, context
2  Persistence .......... models, db, repositories, alembic + initial migration
3  Auth + keys .......... schemas/auth, deps, api/auth, key_service, api/keys
4  Storage .............. storage/file_service, api/upload, api/files
5  Science engine ....... domain/*, services/search/*, services/vasp/*,
                          services/simulation/*, api/catalog
6  Tools ................ tools/contracts, tools/material_tools
7  Async jobs ........... jobs/{queue,store,progress,runners,worker}, api/jobs
                          (then wire enqueue into material_tools)
8  Agent ................ agent/providers/*, agent/llm, tool_schemas,
                          tool_registry, graph, schemas/chat, api/chat
9  Frontend ............. api/*, features/*, components, styles
```

**Two invariants to never break while building:**

1. **Layering points downward only.** A file may import from phases above it in the
   stack, never below. If `api/chat.py` starts importing a simulation service
   directly, you have skipped the tool/job boundary.
2. **Keep the web process light.** ASE/MACE/heavy science imports belong in the job
   worker (`jobs/runners.py` and the simulation services it calls), never at module
   load in an API or agent file.

> **Later (not in this plan):** production hardening — managed PostgreSQL, S3/object
> storage for artifacts, and the ops flip away from local SQLite + filesystem. Add
> that as the final phase when you move from "runs on my machine" to "deployed".
