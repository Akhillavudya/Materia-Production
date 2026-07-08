# Materia — Complete Codebase Audit / Paper Fact Base

> **Purpose.** A single reference document capturing every verified fact about the
> Materia codebase needed to write the academic paper (RSC Digital Discovery style).
> Every non-trivial claim carries a `(path:lines)` citation into this repository.
> Status labels: **[IMPLEMENTED]** working now · **[PARTIAL]** exists but incomplete ·
> **[PLANNED]** not built yet. Anything unverifiable is marked
> **UNKNOWN — verify with author**. Audit date: 2026-07-07, repo `Materia-Production`
> at commit `bd8854a` (main == prod/main).

---

# 0. Project identity & positioning

- **Official name:** "Materia" — the backend calls itself "Materia Production Backend"
  (backend/app/core/config.py:61); the README title is "MateriaAI" (README.md:1, the
  README is otherwise empty); the desktop product name is "Materia"
  (desktop/electron-builder.yml:14). The agent introduces itself as "Materia AI"
  (backend/app/agent/graph.py:64).
- **Former names:** UNKNOWN — verify with author. NOTE: **"Masgent" is NOT a former
  name of this project** — it is the closest *competitor* system, used as a reference
  paper for the related-work comparison (docs/paper/paper_outline.md:6, 101-131). The
  git remote history shows an earlier repo name "MateriaProject" (per project memory);
  confirm with author before stating any naming lineage in the paper.
- **One-line description:** a self-hosted, conversational AI platform for computational
  materials science — an LLM agent with 23 native-function-calling tools that searches
  materials databases, builds/edits crystal structures, generates complete VASP input
  decks, and runs ML-potential simulations (relaxation, MD, elastic, phonons, SQS, NEB,
  adsorption) as tracked background jobs, all behind a streaming chat web UI and a
  desktop app (backend/app/agent/graph.py:63-176; backend/app/agent/tool_registry.py:37-61).
- **Intended users:** materials-science researchers/students. Current deployment is a
  private, invite-gated lab instance (docker-compose.yml SIGNUP_MODE=invite); public
  open-signup launch is planned post-publication (docs/deployment/DEPLOYMENT_GUIDE.md,
  "Phase 2 — going public").
- **Self-hosted premise:** the entire stack — frontend, backend, database, job queue,
  ML-potential weights, local 2D-materials database — runs from one `docker compose up`
  on the operator's own server (docker-compose.yml); LLM access is BYOK (users bring
  free Gemini keys) or fully offline via Ollama (backend/app/core/config.py:143-163).

### Differentiators (evidence for the comparison table, all [IMPLEMENTED] unless noted)

| Capability | Status | Evidence |
|---|---|---|
| Structure manipulation (supercell, vacuum, slab, adsorbate, 3 defect types, symmetry, format conversion) | [IMPLEMENTED] | backend/app/tools/material_tools.py:714-1141 |
| Multi-database search (MP + C2DB + OQMD, unified card model) | [IMPLEMENTED] | backend/app/services/search/service.py:23-87 |
| MLP simulations (6 models: 4× MACE, 2× MatterSim; relax/MD/elastic/phonon/SQS/NEB/adsorption) | [IMPLEMENTED] | backend/app/services/simulation/calculator_factory.py:41-56; backend/app/jobs/runners.py:89-197 |
| VASP workflow templating (11 tasks × orthogonal modifiers) | [IMPLEMENTED] | backend/app/domain/vasp.py:20-32; backend/app/services/vasp/service.py:22-35 |
| Streaming UX (SSE token + tool-card protocol, plan-confirm gate) | [IMPLEMENTED] | backend/app/api/chat.py:259-346; frontend/src/api/chat.js:1-139 |
| Self-hosting (compose stack, Caddy auto-HTTPS, Postgres, Redis, Celery) | [IMPLEMENTED] | docker-compose.yml |
| Desktop app (Electron + PyInstaller-frozen backend, installers, auto-update) | [IMPLEMENTED] locally; installers hand-delivered, no public release pre-paper | desktop/electron/main.js; desktop/electron-builder.yml |
| HPC execution (SLURM submission, remote DFT runs) | [PLANNED] — Materia *generates* VASP decks but never executes DFT | backend/app/services/vasp/service.py (generation only); docs/paper/paper_outline.md:128-131 |
| Lightweight ML utilities (PCA/CVAE etc.) | [PLANNED] (Masgent-lead feature, not present) | docs/paper/paper_outline.md:132 |
| Workflow templating beyond VASP input sets (e.g. multi-step pipeline files) | [PARTIAL] — the plan-gate composes multi-tool workflows conversationally, but there is no persisted/reusable workflow template artifact | backend/app/agent/planner.py:1-28 |

---

# 1. System architecture (high-level)

**Layered design** (post-June-2026 restructure):

```
Browser (React SPA)  ──SSE/REST──▶  Caddy (static + /api reverse proxy)
                                        │
                                        ▼
                              FastAPI web process (api service)
                              ├── api/        thin HTTP routers
                              ├── agent/      LLM loop, planner, tool schemas, providers
                              ├── tools/      23 agent tools (pure adapters)
                              ├── services/   search / structure / vasp / simulation / storage
                              ├── jobs/       enqueue side (Celery producer)
                              └── database/   async SQLAlchemy (Postgres or SQLite)
                                        │ Celery task by name (Redis broker)
                                        ▼
                              Celery worker process (worker service)
                              └── jobs/runners.py → services/simulation/* (torch, MACE/MatterSim, phonopy, ATAT)
```

The web process **never imports torch/ASE-heavy runners**; it dispatches Celery tasks
by string name so the ML stack loads only in the worker (backend/app/jobs/queue.py:1-9).
All job state lives in the `jobs` DB table, not the broker, so jobs survive restarts
(backend/app/database/models.py:92-121).

### Directory tree (depth ~3, storage/build dirs excluded)

```
Materia-Production/
├── AGENTS.md                     # ⚠ STALE — describes retired LangGraph/Ollama design (see §12)
├── README.md                     # one line only ("# MateriaAI")
├── docker-compose.yml            # postgres + redis + api + worker + caddy
├── backend/
│   ├── Dockerfile                # python:3.12-slim + ATAT build + CPU torch
│   ├── docker-entrypoint.sh      # optional alembic upgrade, then exec
│   ├── requirements.txt / requirements-test.txt / pyproject.toml
│   ├── app/
│   │   ├── main.py               # FastAPI factory
│   │   ├── agent/                # graph.py, planner.py, llm.py, tool_registry.py,
│   │   │   └── providers/        # base.py, gemini.py, ollama.py, _keypool.py
│   │   ├── api/                  # auth, chat, upload (manual tools), jobs, keys, files,
│   │   │                         # catalog, models, system, health, deps
│   │   ├── core/                 # config, security, encryption, middleware, limiter, logging, context
│   │   ├── database/             # db.py, models.py, migrations/ (alembic, 1 revision)
│   │   ├── domain/               # jobs.py, vasp.py, material_card.py
│   │   ├── jobs/                 # queue.py, runners.py, store.py, progress.py, worker.py
│   │   ├── repositories/         # user/session/message/api_key/job repos
│   │   ├── schemas/              # pydantic request/response models
│   │   ├── services/
│   │   │   ├── search/           # service.py + providers/{mp,c2db,oqmd}.py + mappers.py
│   │   │   ├── structure/        # builder.py, adsorption.py, activation.py
│   │   │   ├── vasp/             # service.py, incar.py, kpoints.py, poscar.py, potcar.py, templates.py
│   │   │   ├── simulation/       # optimization, md, elastic, phonon, sqs, neb, neb_path,
│   │   │   │                     # calculator_factory, plots, report
│   │   │   ├── storage/          # file_service.py (session dirs, path safety)
│   │   │   ├── key_service.py    # BYOK multi-key pool
│   │   │   └── model_manager.py  # first-run checkpoint downloads (desktop)
│   │   ├── storage/runs/         # per-session artifacts (runtime, gitignored)
│   │   ├── scripts/validation/   # T1/T3/T4/T5 benchmark harnesses
│   │   └── tests/{unit,validation}/
├── frontend/
│   ├── Dockerfile + Caddyfile    # build SPA → serve via Caddy, /api proxy
│   └── src/
│       ├── api/                  # fetch/SSE clients per resource
│       ├── features/             # auth, chat, files, sessions, settings, viewer, models, landing
│       ├── components/, hooks/, styles/
├── desktop/
│   ├── electron/                 # main.js, backend.js, preload.js
│   ├── electron-builder.yml      # AppImage / dmg / NSIS + GitHub publish
│   ├── scripts/build_backend.py  # PyInstaller freeze
│   └── resources/{backend,spa}/  # frozen backend + built SPA (build outputs)
├── pre_trained_models/           # 4 MACE + 2 MatterSim checkpoints (~398 MB)
├── data/c2db/                    # local C2DB ASE .db (~71 MB, 2D materials)
├── scripts/fetch_models.sh
├── docs/                         # deployment guide, validation results, issue postmortems, paper outline
└── .github/workflows/            # ci.yml, desktop-release.yml
```

### Data-flow walkthrough of one full request

User asks *"Generate VASP inputs for MoS2"*:

1. **POST /api/chat** (`backend/app/api/chat.py:259-296`) — JWT auth resolves the user;
   a session row is created/loaded, the user message is persisted, and the user's BYOK
   keys are decrypted into `os.environ` for this request
   (backend/app/services/key_service.py:77-82).
2. **Plan phase** — `make_plan()` (backend/app/agent/planner.py:134-164) makes one
   tools-free LLM call with a JSON-only planner prompt listing the 23 real tool names
   (planner.py:46-83). The reply is parsed tolerantly (`_extract_json`, planner.py:86-103)
   and validated: hallucinated tool names are dropped (planner.py:106-131). If the plan
   has **≥2 steps**, the backend streams `[PLAN:{...}]` and stops — the UI shows a
   PlanCard with Confirm/Cancel (chat.py:196, 330-336; frontend/src/features/chat/PlanCard.jsx).
   0–1-step plans (or planner failure — planning is best-effort and never blocks) run
   straight through (planner.py:8-13; chat.py:338-340).
3. **Execute phase** — `run_agent()` → `_agent_loop()` (backend/app/agent/graph.py:469-608):
   the system prompt + optional session-structure note + history (+ approved plan as an
   instruction, graph.py:358-370, 494-498) go to the provider chain. The provider
   returns streamed text plus **native structured tool calls** (no regex parsing —
   backend/app/agent/providers/base.py:1-17).
4. **Tool execution** — for each `ToolCall`, `_execute_tool()` (graph.py:378-462) looks
   the function up in `CALLABLE_TOOL_MAP` (tool_registry.py:77-81), runs it in a thread
   executor with the session dir + user identity re-bound via ContextVars
   (graph.py:409-416; backend/app/core/context.py; file_service.py:189-209), emits
   `[TOOL_START]`/`[TOOL_END]` SSE, diffs the session folder for **files created after
   the call started** (`list_new_files`, file_service.py:116-134), and emits a
   `[FILES:{...}]` card. Here the model actually calls `search_materials` first
   (system-prompt rule, graph.py:108-111), then `generate_vasp_inputs` with the found
   `mp-…` id.
5. **Result feedback** — the tool's dict result is trimmed for the LLM (top-10 materials,
   selected fields only — graph.py:287-305) and appended as a `role:"tool"` turn;
   the loop re-invokes the model (max 6 rounds, graph.py:56) until it answers in prose.
   Duplicate (tool+args) calls within one request are suppressed (graph.py:308-314, 547-569).
6. **Streamed response** — tokens stream as `{"type":"token"}` events; `[DONE]` and
   `[SESSION:<id>]` close the stream (graph.py:606-608). `chat.py:_stream_agent`
   simultaneously accumulates tokens + FILES cards and persists the assistant message
   with its `tool_result` JSON at the end (chat.py:229-256).

---

# 2. Backend

- **Framework:** FastAPI on uvicorn; app factory in backend/app/main.py:40. In
  production the OpenAPI explorer (/docs, /redoc, /openapi.json) is disabled
  (main.py:34-38).
- **Middleware** (order matters, outermost last-added: main.py:43-55): CORS
  (origins from `ALLOWED_ORIGINS`), SlowAPI rate limiting, security headers, and a
  request-context middleware providing request IDs + catch-all 500 handling
  (backend/app/core/middleware.py). Known HTTP errors return
  `{"detail", "request_id"}` without leaking internals (main.py:60-79).
- **Routers** (all under `/api` except health): auth, chat, upload, keys, files,
  catalog, jobs, models, system; health/ready at root for container probes
  (main.py:82-94).

### Key endpoints

| Path | Method | Purpose | Notes |
|---|---|---|---|
| /api/auth/signup, /login, /google, /me (GET/PATCH), /config | POST/GET | JWT auth, Google Identity sign-in, public gate hints | auth.py:78-227; signup rate-limited 10/min |
| /api/chat | POST | The agent SSE stream (plan phase + execute phase) | chat.py:259-346; 30/min limit |
| /api/sessions, /sessions/{id}/messages, /files, /files/grouped, /export/{txt,json} | GET | Session history, file listings, transcript export | chat.py:42-190 |
| /api/files/download/{rel_path}, /files/content/{rel_path} | GET | Artifact download / text preview (ownership-checked, extension-allowlisted) | chat.py:106-143; deps.py:31-55 |
| /api/files/{rel_path}/rename | POST | Rename an artifact | files.py:22 |
| /api/sessions/{id}/upload, /sessions/create-and-upload | POST | Structure upload (sanitized names, extension allow/block lists, 25 MB cap) | upload.py:70-158; file_service.py:20-95 |
| /api/sessions/{id}/{optimize,md,phonons,elastic,sqs,neb,migration-paths,sqs/sublattices} | POST | **Manual launchers** for async sims (same tool functions as the agent) | upload.py:224-538 |
| /api/sessions/{id}/{make_supercell,add_vacuum,make_slab,add_adsorbate,convert_structure,generate_vasp_inputs,generate_poscar,generate_kpoints,create_vacancy,create_substitution,create_interstitial} | POST | Manual launchers for instant tools; each posts an assistant "action card" into chat history so manual + conversational use share one timeline | upload.py:578-956, `_log_manual_run` upload.py:547 |
| /api/jobs, /jobs/{id}, /jobs/{id}/cancel, /jobs/{id}/stream | GET/POST | Job dashboard: list/inspect/cancel + per-job SSE (1 s DB polling) | jobs.py:34-134 |
| /api/keys (POST/GET/DELETE …/{service}/{index}) | — | BYOK key pool CRUD (masked hints only) | keys.py:31-90 |
| /api/models, /models/download | GET/POST | Desktop first-run checkpoint manager; 404 when heavy tools off | models.py:34-55 |
| /api/system | GET | Compute device / build-variant badge (desktop) | system.py:24-42 |
| /api/catalog/calculators, /calculators/test, /vasp/tasks | GET/POST | Discovery endpoints for UI dropdowns | catalog.py:24-60 |
| /health, /ready | GET | Liveness + DB/Redis readiness | health.py:29-64 |

- **Async model:** the web process is fully async (async SQLAlchemy via asyncpg/aiosqlite,
  config.py:180-191). Tool functions are synchronous and run in
  `loop.run_in_executor` threads (graph.py:415-416). Long simulations never run in
  the web process at all — they are Celery tasks (§9 of this doc / backend/app/jobs/).
- **Auth/session handling:** OAuth2 bearer JWT (HS256, 1440-min expiry default),
  bcrypt password hashing (core/security.py:19-50). Production refuses to boot with
  weak/missing JWT secret, missing Fernet key, non-Postgres DB, wildcard CORS, or an
  empty invite-code list (config.py:223-269). Signup modes: open / invite
  (constant-time code comparison, auth.py:37-43) / closed; production defaults to
  invite (config.py:275-279). Google sign-in verifies the ID token server-side with
  google-auth and only auto-creates users when SIGNUP_MODE=open (auth.py:117-192).

---

# 3. Agent architecture

**Headline correction for the paper:** the current agent is **NOT LangGraph** and does
**NOT use raw-httpx JSON forcing**. Those describe a retired design (still echoed in the
stale AGENTS.md:22-28 — do not cite it). The shipped agent (redesign §15) is a
**native function-calling loop** over a provider-neutral `LLMProvider` interface:
tool calls arrive as structured data from the model, never parsed from prose
(backend/app/agent/graph.py:1-15; providers/base.py:1-17). LangGraph appears nowhere in
requirements.txt.

### 3.1 The agent loop (graph.py) [IMPLEMENTED]

- One "graph" = a simple bounded loop (`MAX_TURNS = 6`, graph.py:56): model turn →
  execute all requested tool calls → feed results back → repeat until the model
  answers with no tool calls (graph.py:506-586).
- **System prompt** (graph.py:63-176) enumerates all 23 tools with behavioural rules:
  search-before-generate for bare formulas, read_file-first for uploads, job-honesty
  rules ("NEVER fabricate a job_id", graph.py:144-153), SQS/NEB-specific guidance,
  results-table formatting, and a no-tool path for conceptual questions (graph.py:173-175).
- **Session-state injection:** a second system message tells the model which structure
  is already active ("SESSION STATE: … {formula}, {n} atoms") so it never asks the
  user to re-upload (graph.py:221-247).
- **Import-time drift guard:** the module raises at import if the set of tools declared
  to the LLM (`TOOL_SPECS`) differs from the executable set (`CALLABLE_TOOL_MAP`) —
  added after four tools were once executable but undeclared, causing silent
  bad-argument failures (graph.py:30-44; postmortem
  docs/issues_solve/2026-06-25-sqs-and-5-tools-missing-from-llm-schema.md).
- **Duplicate-call suppression:** a (name + sorted-args) fingerprint set skips identical
  repeat calls within one request and tells the model why (graph.py:308-314, 547-569).
- **Friendly error mapping:** provider 429/quota errors become a short user message;
  raw provider dumps never reach chat (graph.py:615-628). If a job was already enqueued
  before the provider died, the job confirmation is surfaced instead of the error
  (graph.py:520-530).

### 3.2 Planner (planner.py) [IMPLEMENTED]

- A **separate, tools-free LLM call** that returns a JSON plan:
  `{needs_tools, summary, steps:[{tool,title,detail}], final_output}` (planner.py:14-27).
- It is isolated from the execution system prompt: it gets its own PLANNER_PROMPT with
  only a one-line-per-tool catalog derived from the registry (planner.py:41-83), so
  planning judgments can't be polluted by execution rules, and the plan can be shown
  to the user *before* anything runs.
- **JSON forcing mechanism (actual):** the same provider abstraction is called with an
  empty tool list (`provider.run(convo, [], _noop)` — planner.py:153-154), the prompt
  demands "a SINGLE JSON object and nothing else", and `_extract_json` tolerantly strips
  markdown fences and brackets the first `{…}` (planner.py:86-103). Illustrative snippet:

  ```python
  result = await provider.run(convo, [], _noop)   # no tools → text only
  raw = _extract_json(result.text)                 # fence-tolerant JSON pull
  return _validate(raw)                            # drop hallucinated tool names
  ```

- Planning is deliberately best-effort: any error/unparseable output returns `None` and
  the request runs without the gate — "planning can never block a request"
  (planner.py:8-13, 155-158).
- The **confirmation gate** fires only for plans with ≥2 steps (chat.py:196, 330-336);
  the plan is persisted to chat history as markdown + a `{"plan": …}` tool_result so it
  survives reloads (chat.py:199-212, 334-335). On Confirm the frontend re-POSTs /chat
  with `plan` set; the backend injects the approved plan as an instruction and
  **defers per-step file cards**, emitting one final "Final structure & inputs" card
  with intermediate structure files suppressed (graph.py:317-370, 494-498, 594-604).

### 3.3 Tool-calling mechanism [IMPLEMENTED]

- **Native function calling on every provider**: Gemini `FunctionDeclaration`s with
  streaming and automatic-function-calling disabled so the loop stays in control
  (providers/gemini.py:76-135); Ollama chat `tools` (providers/ollama.py:76-117).
- **Schemas from a single source of truth:** every tool's argument schema is the
  Pydantic model in tools/contracts.py, converted to provider-neutral JSON Schema by
  tool_schemas.py (`_clean_schema` drops titles/defaults and flattens Optional anyOf —
  tool_schemas.py:252-305). The registry (labels + callables) derives from the same
  contracts (tool_registry.py:1-81), so prompt, schema, and executor cannot drift.
- **Validation & errors:** tools validate/normalize their own args and return a uniform
  `{"status": "error", "message": …}` envelope instead of raising (e.g.
  material_tools.py:394-417); unexpected exceptions inside `_execute_tool` are caught,
  traced server-side, and surfaced as `[TOOL_END:…:error]` (graph.py:458-462).
- **Multi-step dependency passing:** three mechanisms — (a) the *active POSCAR
  convention*: every structure-producing tool writes `POSCAR` (+ a tagged
  `POSCAR_<formula>_<tag>` copy) into the session root, and every consumer defaults to
  it via `find_structure_in_session` (file_service.py:277-326; material_tools.py:680-711);
  (b) `resolve_args` fills "auto"/missing poscar args with the best session POSCAR
  (graph.py:206-218); (c) `auto_fill_material_args` back-fills material_id/source for
  generate_vasp_inputs from the most recent search result (graph.py:260-274).
- **No-tool path:** when a turn returns zero tool calls the streamed text *is* the
  answer; an empty-bubble guard emits a fallback message if nothing streamed
  (graph.py:532-538). The planner also short-circuits pure conversation with
  `needs_tools:false` (planner.py:57-60).

### 3.4 Provider layer & resilience [IMPLEMENTED]

- `get_provider()` returns the configured backend wrapped in a **FallbackProvider**
  chain: Gemini→Ollama (llm.py:27-29, 141-147). A backend is replaced when it raises
  (429/quota/network/missing key) *or returns an empty turn*, but only while <24 streamed
  characters are held in a commit buffer — once real text has streamed, switching would
  duplicate output, so errors re-raise (llm.py:33-37, 60-133). On web there is no Ollama
  server, so Gemini is effectively the sole provider; Ollama is the desktop-offline backend.
- **Multi-key rotation** (providers/_keypool.py): the Gemini provider first rotates
  through a pool of free keys (user BYOK key first, then operator `GEMINI_API_KEYS`) on
  429/invalid-key errors, with a round-robin cursor remembering the last good key; only
  when all keys are exhausted does the request drop to Ollama (_keypool.py:1-126). This
  is the real resilience layer on web.
- Provider auto-resolution when `MODEL_PROVIDER` unset: gemini if a Gemini key exists,
  else ollama (config.py:167-174).

### 3.5 Conversation/session memory [IMPLEMENTED]

- Every user/assistant turn is persisted in the `messages` table (role, content,
  tool_result JSON, timestamps — database/models.py:59-72); history is replayed as
  plain text turns to the LLM on each request (chat.py:287-294). Tool-result cards are
  re-rendered from `tool_result` on reload. There is **no vector memory / summarizer**;
  context is the raw message history. Session files persist on disk per session
  (§9). Job terminal states are back-written into any persisted chat job card so
  reloads show the true status (jobs/store.py:182-215).

---

# 4. Tool registry & capabilities inventory

Source of truth: `backend/app/agent/tool_registry.py:37-61` (23 tools) and the
callable implementations in `backend/app/tools/material_tools.py`. All 23 are
**registered to the LLM AND executable** (the import-time guard enforces this,
graph.py:35-44). All are [IMPLEMENTED].

**Shared contract:** every tool returns a plain dict envelope with `status`
("success" | "ok" | "error" | "not_found" | "queued") + human `message`, plus
tool-specific fields; async tools return `{status:"queued", job_id, type,
track:"/api/jobs/<id>", message}` (material_tools.py:132-141). Files are reported
via `files_written` names and discovered by the agent loop as session-dir diffs
(`list_new_files`, file_service.py:116-134) with **paths relativized to
STORAGE_ROOT** (`rel_to_storage`, file_service.py:224-229) so the frontend builds
download URLs without absolute paths.

### Instant (synchronous) tools

| Tool | Purpose | Required inputs | Optional inputs | Returns |
|---|---|---|---|---|
| search_materials (material_tools.py:218-297) | Search MP→C2DB→OQMD, first-hit-wins; stability-sorted; writes all-polymorphs CSV when matches > display limit | ≥1 of formula/element/elements | min_gap, max_gap, max_formation_e, dimensionality ("2D" reorders to C2DB-first), limit (1-20) | status, source_used, sources_tried, materials[MaterialCard], total_matching, returned, polymorphs_csv |
| generate_vasp_inputs (373-469) | Full POSCAR+INCAR+KPOINTS(+POTCAR/.spec) set; 11 tasks × modifiers | material_id+source OR poscar_path (defaults to active) | task, cell_relax, functional (pbe/hse06/scan), vdw (d3/d3bj/optb88/df2), soc, hubbard_u, dipole, solvent (vaspsol/++), charge→NELECT, **overrides (e.g. ENCUT) | status, task, formula, n_sites, encut, kmesh, elements, potentials, modifiers, nelect, warnings, files, files_written |
| generate_poscar (476-510) | POSCAR only | material_id+source OR poscar_path | — | formula, n_sites, lattice a/b/c, files_written |
| generate_kpoints (535-604) | KPOINTS by kppa accuracy (Low 1000 / Medium 3000 / High 5000 / Custom) or exact mesh | — (active POSCAR default) | accuracy_level, custom_kppa, explicit_mesh, gamma_centered, material_id/source/poscar_path | accuracy_level, kppa or mesh, files_written |
| make_supercell (714-748) | Replicate cell (uniform / per-axis / full 3×3 matrix); pre-build atom-cap check | scaling | material_id/source/poscar_path | operation, formula, n_sites_before/after, lattice_abc, files_written |
| add_vacuum (751-784) | Set exact vacuum gap along axis; side both/top/bottom | — | axis, thickness (Å), side, structure source | same build envelope |
| make_slab (787-830) | Cut slab along Miller index; `layers` = complete structural repeat units (stoichiometry-preserving), vacuum included | — | miller, layers, min_slab_size, min_vacuum_size, center, lll_reduce, shift, structure source | same build envelope |
| add_adsorbate (855-956) | Place molecule on slab: fast geometric (auto site or atom_index) — or relax=true → AdsorbML-style **async job** | molecule | site_type, atom_index, distance, relax, calculator_*, material_type auto/bulk/slab (+miller/layers/vacuum for bulk), structure source | build envelope, or queued-job envelope (JobType.ADSORPTION) |
| convert_structure (959-975) | Write structure as poscar/cif/xyz/cssr/json (does NOT change active POSCAR) | — | to_format, structure source | operation, formula, format, files_written |
| analyze_symmetry (982-1033) | Space group, point group, crystal system, sym ops; optional primitive/conventional cell write | — | symprec, write, structure source | space_group_symbol/number, point_group, crystal_system, n_symmetry_ops, files_written |
| create_vacancy (1068-1090) | Remove `count` atoms of an element ("3" or "all", default 1) — edits current cell | — | element, count, structure source | defect, defect_name, formula, n_sites, files_written |
| create_substitution (1093-1116) | Replace count atoms from_element→to_element | from_element, to_element | count, structure source | same defect envelope |
| create_interstitial (1119-1141) | Insert count atoms at Voronoi interstitial sites | insert_element | count, structure source | same defect envelope |
| read_file (1217-1300) | Parse an upload; ordered structures are *activated* as POSCAR; disordered → `<formula>_disordered.cif` for SQS; text files → 4000-char preview | — (newest upload default) | filename | file_type, formula/n_sites/lattice/elements/disordered OR content_preview/n_lines/size_kb |
| list_files (1327-1360) | Session file inventory with type labels | — | — | files[{name,type,uploaded,time,size_kb,rel_path,description}] |
| list_models (1367-1393) | Available ML potentials with variants, defaults, on-disk availability, aliases | — | — | default_calculator, models[] |
| list_sublattices (1759-1775) | Symmetry-distinct Wyckoff sublattices, pre-SQS site picker | — | cif_name, symprec | delegated to sqs.list_sublattices |

### Async (job-enqueueing) tools — all return job envelopes and run in the Celery worker

| Tool | Purpose | Key inputs (defaults) | Job type |
|---|---|---|---|
| optimize_structure (1400-1456) | ASE geometry relaxation with MLP; optional VASP-handoff INCAR/KPOINTS | fmax 0.02, cell_relax none/shape/full, optimizer FIRE/BFGS/LBFGS (BFGS auto-swapped to FIRE for cell DOF), max_steps ≤ MAX_OPT_STEPS, calculator_type/model | optimize |
| run_md_simulation (1463-1518) | ASE MD; NVT (langevin/nose-hoover) or NPT (berendsen/bussi) | ensemble, temperature 300 K, nsw ≤ MAX_MD_STEPS, timestep 1 fs, thermostat, pressure, log_interval | md |
| compute_elastic_tensor (1525-1580) | 6×6 elastic tensor via strain-stress; Hill K/G/E/ν, Pugh, universal anisotropy, Born stability; 2D-aware (in-plane N/m moduli) | fmax 0.01, max_steps 300, relax_mode positions/shape/full | elastic |
| compute_phonons (1598-1667) | Finite-displacement phonon band + DOS via phonopy/seekpath; dynamic-stability verdict; atom cap applies to the supercell | supercell "3 3 3", disp_distance 0.01 Å, mesh 20 | phonon |
| generate_sqs (1778-1861) | ATAT mcsqs SQS from a NORMAL ordered structure via sublattice_comp ("Ti=Ti0.6,Zr0.4"), legacy substitute ("Si->S:0.25") or disordered CIF; N parallel searches; MLP-relaxed result | supercell "2 2 2", cutoff auto, n_parallel 4, target_objective −0.99, time_budget_s 600, relax true | sqs |
| compute_neb (1958-2083) | NEB migration barrier: two endpoints OR migrating_element auto-vacancy-endpoints; deep endpoint relax, IDPP, two-phase climbing image, Hessian TS check, VASP-deck zip | n_images 8, fmax 0.05, endpoint_fmax 0.03, spring_k 1.0, climb true, run_frequencies true | neb |

**Universal safeguards on async tools:** heavy-tools gate (`ENABLE_HEAVY_TOOLS=false` →
friendly "run it in the desktop app" refusal — the single backstop for agent, manual
panel, and direct API paths, material_tools.py:83-94), per-user active-job quota
(default 3, material_tools.py:96-106), atom cap (default 512, material_tools.py:340-360),
and parameter clamping to server caps (e.g. material_tools.py:1428-1429).

### Present-but-unregistered / discrepancies

- **list_migration_paths** (material_tools.py:1868-1922) is implemented and reachable via
  the manual REST endpoint POST /api/sessions/{id}/migration-paths (upload.py:421-449)
  but is **deliberately NOT in the agent registry** (dropped when NEB gained the
  migrating_element auto-endpoint mode, 2026-07-06; contracts still carry its unused
  `ListMigrationPathsInput`, contracts.py:229-241). Label [PARTIAL] (manual-only).
- Files named `optimize_structure_tool.py`, `run_md_tool.py`, `md_plots.py` **do not
  exist** in this codebase (they belong to a pre-restructure layout). Their successors
  are material_tools.py + services/simulation/{optimization,md,plots}.py.
- **NVE ensemble [IMPLEMENTED]** (fixed 2026-07-07): the MD *service* implements NVE with
  energy-conservation reporting (md.py — "nve" handling around lines 143, 346-358, 426),
  the Pydantic contract advertises `"nve"` to the LLM (contracts.py:106-108), the frontend
  MD launcher offers it (toolForms.js:241), and a `md_nve` VASP preset exists
  (templates.py:141). The tool gate previously rejected everything except nvt|npt; it now
  accepts `nve` (material_tools.py:1481-1483), so NVE runs end-to-end from both the agent
  and the manual launcher. Postmortem: docs/issues_solved/issue-nve-ensemble-gate.md.

### Multi-database search details

| DB | Access method | Matching / normalization | Pitfalls handled |
|---|---|---|---|
| Materials Project | Live REST via mp-api `MPRester`, requires user MP key injected per-request from BYOK store (providers/mp.py:23-56; key_service.py:20-26) | formula/elements/band-gap kwargs to `materials.summary.search`; results stability-sorted by `energy_above_hull` with an explicit None-check (a falsy 0.0 hull once sorted ground states LAST — fixed) (mp.py:60-70) | 200-result cap; conventional unit cell on refetch (mp.py:78-81) |
| C2DB | **Local ASE SQLite db** (~17k 2D materials) mounted at /data/c2db/c2db.db, no network (providers/c2db.py:1-14; docker-compose.yml volumes) | formula matched via `db.select(formula=…)`; element filters parse formulas into element sets with pymatgen Composition — substring matching once wrongly matched "S" in "Se" (c2db.py:17-54) | availability = file existence; structures rebuilt via AseAtomsAdaptor (c2db.py:69-82) |
| OQMD | Public REST (oqmdapi/formationenergy), no key (providers/oqmd.py:23-70) | composition query param; structure rebuilt from unit_cell + "El @ x y z" site strings (oqmd.py:72-96) | **blocking urllib** — acceptable only because the whole tool runs in an executor thread; flagged for async httpx follow-up (oqmd.py:3-7) |

Orchestration: first-hit-wins in order MP→C2DB→OQMD; "2D" queries reorder to
C2DB-first so MP bulk hits don't shadow monolayers; provider errors are isolated and
never abort the chain; structure re-fetch routes by id prefix (mp-/c2db-/oqmd-)
(services/search/service.py:22-122). All providers normalize into one `MaterialCard`
Pydantic model with canonical prefixed ids and None-not-zero missing data
(domain/material_card.py:1-67).

### VASP / DFT input generation

- **11 tasks:** static, relaxation, band (line-mode HighSymmKpath KPOINTS), dos (dense
  mesh), aimd (Γ-only), elastic (IBRION=6), phonon_dfpt (IBRION=8), dielectric, bader,
  elf, workfunction (domain/vasp.py:20-32; services/vasp/service.py:22-41, 117-132).
- **Orthogonal modifiers** stack on any task: functional pbe/hse06/scan, vdW
  d3/d3bj/optb88/df2, SOC, DFT+U (curated Dudarev U table, POTCAR-ordered LDAU arrays,
  LMAXMIX=4 — incar.py:101-131), dipole correction, VASPsol/++ implicit solvation, and
  net `charge` resolved to a concrete NELECT from POTCAR ZVALs (vasp/service.py:87-105,
  175-189). Human-facing warnings accompany costly/caveated combos (service.py:192-211).
- **INCAR:** template-merged tags with section formatting; automatic ISPIN=2 + per-site
  MAGMOM when magnetic elements are present; NCORE emitted only when explicitly
  configured so decks stay portable (incar.py:70-88).
- **KPOINTS:** density presets per task (40/60 pts·Å⁻¹ scale), Γ vs Monkhorst-Pack,
  explicit-mesh mode, line-mode for bands with graceful fallback (kpoints.py:9-131).
- **POTCAR:** licensed files are never shipped. Default output is a human-readable
  `POTCAR.spec` (recommended `_sv/_pv/_d` labels, ZVAL, ENMAX, ENCUT floor = ⌈max
  ENMAX × 1.3⌉ from a curated 66-element table). A **real POTCAR** is assembled only
  when `PMG_VASP_PSP_DIR` points at an operator-mounted licensed PAW library, in which
  case authoritative ENMAX/ZVAL are read from the files (potcar.py:1-201; compose mounts
  `${POTCAR_DIR}:/potcar:ro`). ENCUT defaults to 520 eV (MP-consistent) with the POTCAR
  floor surfaced as a warning (vasp/service.py:81-93).
- **No job scripts / no execution:** Materia writes input decks only; SLURM generation
  and DFT execution are [PLANNED] (docs/paper/paper_outline.md:128-131).

### MLP simulation stack

- **Potentials:** 4 MACE variants (mace-mp-0b3-medium default, mace-mpa-0-medium,
  mace-omat-0-medium, MACE-matpes-pbe-omat-ft) + 2 MatterSim (v1.0.0-1M default "small",
  v1.0.0-5M "large"), loaded from local checkpoints under pre_trained_models/
  (calculator_factory.py:41-104). Natural-language aliases ("MatterSim Large",
  "MACE-MP") resolve through a shared alias table; unsupported requests return a
  friendly error rather than enqueueing a doomed job (calculator_factory.py:205-256;
  material_tools.py:150-166).
- **Engine:** ASE throughout (FIRE/BFGS/LBFGS optimizers, FrechetCellFilter-style cell
  relaxation modes, Langevin/Nosé-Hoover/Berendsen/Bussi dynamics); phonopy+seekpath
  for phonons; ATAT mcsqs (compiled into the Docker image from source, with build-time
  binary checks) for SQS (backend/Dockerfile:28-45; sqs.py:1-36); AdsorbML-style
  enumerate-relax-rank for adsorption (structure/adsorption.py); CatTSunami-recipe NEB
  (IDPP, two-phase climbing image, Hessian saddle check) (neb.py:1-31).
- **Device:** auto cuda>mps>cpu with `MATERIA_DEVICE` override (desktop CPU build pins
  cpu) (calculator_factory.py:344-363). Torch is CPU-only in the web/server image
  (backend/Dockerfile:50-70).
- **Outputs per job** (examples): optimization → CONTCAR, trajectory .traj/.xyz,
  opt_energy.csv, results.json, convergence PNG, optional INCAR/KPOINTS handoff
  (optimization.py docstring:15-27); MD → trajectory, md_energy/temp CSVs+PNGs,
  results.json with drift/⟨T⟩ stats, CONTCAR, VASP-MD deck (md.py docstring:13-27);
  every heavy job also writes a plain-language convergence_report.md
  (simulation/report.py; runners.py:39 artifact kinds).

---

# 5. LLM / model layer

| Model | Provider / how invoked | Role | Native tools? | Notes / limitations |
|---|---|---|---|---|
| **gemini-2.5-flash** (default) | Google AI Studio free tier via `google-genai` SDK, streaming `generate_content_stream`, temperature 0 (providers/gemini.py:111-160) | Primary: planning AND tool-calling AND response | ✅ FunctionDeclarations | "Thinking" must be disabled (`thinking_budget=0`) — with the tool set present it otherwise burns the whole turn thinking and returns an empty turn, silently breaking tool calling (gemini.py:126-134; postmortem docs/issues_solve/2026-06-25-gemini-thinking-empty-tool-calls.md). Chosen primary because its free tier is request-metered, so the ~8k-token tool schema per call doesn't drain quota, and T4 measured 100% tool selection (config.py:143-152) |
| **qwen3:14b** | Local Ollama server via `ollama` AsyncClient (providers/ollama.py:69-117; config.py:161-163) | Offline fallback (desktop only) | ✅ (qwen3 supports native tools) | Requires a local Ollama install; quality/latency unbenchmarked (T4 explicitly did not benchmark Ollama). No Ollama server runs on web, so Gemini is the sole web provider |

> **Groq removed (2026-07-07).** Earlier builds carried a Groq `llama-3.3-70b-versatile`
> fallback, but its free tier is token-metered and 413s on the full 23-tool schema
> (~10.6k tokens/call), so it could never complete a real production call. It was dropped
> entirely; the provider file, SDK dependency, config, key mapping, and UI entries are gone.
> Resilience is now Gemini multi-key rotation (web) + Ollama (desktop-offline).

- **One model does everything per request** — there is no separate cheap-planner model;
  the planner and executor share `get_provider()` (planner.py:153; graph.py:477).
- **BYOK:** users store any number of keys per provider (mp/gemini/openai/
  anthropic recognized), Fernet-encrypted at rest, newline-packed in one row, injected
  into `os.environ` per request; user keys take priority over operator pool keys
  (key_service.py:1-126; database/models.py:75-89). In production, chat refuses to run
  until a Gemini key exists, emitting `[NEED_API_KEY:gemini]` (chat.py:302-313).
- OpenAI/Anthropic keys are storable but **no OpenAI/Anthropic provider exists** —
  [PARTIAL] placeholder (key_service.py:20-26 vs llm.py:39-50).

---

# 6. Frontend (web)

- **Stack:** React 19 + Vite 8, plain JS (no TS), no router library and no global state
  manager — view switching and state live in App.jsx/Chat.jsx hooks
  (frontend/package.json; frontend/src/App.jsx). Markdown chat rendering via
  react-markdown + remark-gfm/breaks/math + rehype-katex (KaTeX), with a
  math-delimiter normalizer (features/chat/Chat.jsx:11-58). Icons: lucide-react.
- **Feature-folder layout:** `api/` (one fetch module per resource incl. the SSE chat
  client), `features/{auth, chat, files, sessions, settings, viewer, models, landing}`
  (§1 tree). Vitest unit tests exist for the API token client (api/client.test.js).

### SSE protocol — event inventory (frontend/src/api/chat.js:1-139; emitted in graph.py/chat.py)

| Event | Payload | UI rendering |
|---|---|---|
| `{"type":"token","value"}` | text delta | appended to the assistant markdown bubble |
| `{"type":"status","value"}` | spinner label ("🧭 Planning…", "🧠 Thinking…", "⚙ <label>…", "" to clear) | inline status/spinner line |
| `[TOOL_START:<name>]` | tool name | ToolStatus card appears with spinner (features/chat/ToolStatus.jsx) |
| `[TOOL_END:<name>:<status>]` | name + success/error/skipped | card resolves to ✓/✗ |
| `[FILES:{json}]` | {tool,label,status,msg,files[],materials?,job_id?,…} | FileCard block: per-file chips with view/download, search tables, job chips (features/files/FileCard.jsx) |
| `[PLAN:{json}]` | validated plan | PlanCard with step list + Confirm/Cancel; Confirm re-POSTs /chat with `plan` (features/chat/PlanCard.jsx) |
| ~~`[JOB:{json}]`~~ | — | **Removed 2026-07-07.** This event had no frontend consumer; job awareness comes from the `job_id` carried inside the `[FILES:]` payload + polling /api/jobs. The redundant emission was deleted from graph.py. |
| `[NEED_API_KEY:<service>]` | service hint | inline ApiKeyForm to save a key (features/chat/ApiKeyForm.jsx) |
| `[SESSION:<id>]` | session id | binds the new chat to a session id for subsequent calls |
| `[DONE]` | — | stream close / input re-enable |

The **atomic-event design** — separate TOOL_START (intro/spinner), TOOL_END (status
flip), and FILES (card body) events per tool call, emitted in-order from a single
asyncio queue (graph.py:378-462) — is what makes tool cards render sequentially:
intro → spinner → resolved card with files, interleaved with streaming text.

- **Async jobs UI:** AsyncJobsPanel polls `GET /api/jobs?session_id=…`, re-polling while
  any job is active, with per-job cancel (features/sessions/AsyncJobsPanel.jsx:45-70).
  Per-job SSE streaming (`/api/jobs/{id}/stream`) exists server-side (jobs.py:74-134);
  whether any component consumes it: UNKNOWN — verify with author (the panel uses
  polling).
- **Manual tool launchers:** ToolLaunchPanel (709 lines) + declarative form specs in
  sessions/toolForms.js drive the /api/sessions/{id}/<tool> endpoints; results post
  assistant "action cards" into chat history so manual and conversational runs share
  one timeline (upload.py:534-576).

### 3D visualization (3Dmol.js) [IMPLEMENTED]

- 3Dmol.js 2.1.0 is lazy-loaded once from CDN with SRI (features/viewer/threeDmol.js) —
  note this is a **runtime external dependency** of the SPA.
- **Inline StructureViewer** — modal over any structure file: fetches the file text via
  /api/files/content and renders POSCAR/CIF/XYZ (StructureViewer.jsx:1-40).
- **StructureWorkspace** — full-screen VESTA-style visualizer opened from the sidebar:
  render styles, unit-cell + supercell boundary, atom/bond sizing, labels, axes, spin,
  PNG export (StructureWorkspace.jsx:6-15). **Coordination polyhedra are computed
  client-side** (3Dmol can't draw them): per-cation neighbor gathering across periodic
  images → convex hull → custom mesh, mirroring VESTA's polyhedral rendering
  (features/viewer/polyhedra.js:1-15).
- **MD / NEB trajectories [IMPLEMENTED, animation not scrubber]:** simulations write
  multi-frame extXYZ (`trajectory.xyz`, and the NEB `neb_path.xyz`). The viewer detects a
  multi-frame .xyz and plays it as a **looping animation** via 3Dmol's `addModelsAsFrames`
  + `viewer.animate({loop:'forward'})` (StructureViewer.jsx:217-240). There is **no manual
  frame-scrubber slider** — playback is automatic loop, not step-by-step control.
- **Other UI features:** collapsible Sidebar with session list (sessions/Sidebar.jsx),
  file panel with drag-resize inline FileViewer, profile dropdown, light-theme settings
  pages, landing page, first-run ModelSetup gate (desktop), Google sign-in button
  (features/*). A **"Search chats" modal exists** — a centered, Escape-dismissable modal
  opened from the nav item, focus-trapped input (Sidebar.jsx:70-127).

---

# 7. Desktop

A real Electron desktop app exists — not just "run the web app locally". [IMPLEMENTED]
as code + local builds; **distribution is deliberately manual (no public GitHub Release
or version tag) until the paper is out**.

- **Shell:** Electron main process starts the bundled backend, opens a 1400×900 window
  on the local SPA (`file://` with `--base=./` asset paths), and tears the backend down
  on quit (desktop/electron/main.js:1-70). contextIsolation on, nodeIntegration off;
  the backend port is passed to the renderer via preload args (main.js:27-35).
- **Backend packaging:** the FastAPI app is frozen with **PyInstaller** (onedir) by
  desktop/scripts/build_backend.py:24 and shipped unpacked under
  `resources/backend/materia-backend/` (too large for asar) — resolved at runtime via
  `process.resourcesPath` (electron-builder.yml:22-31; backend.js:49-58).
- **Runtime differences from web:** `JOB_BACKEND=inline` (heavy jobs run in a daemon
  thread — no Celery/Redis at all, queue.py:59-73); SQLite + all mutable state under
  Electron's userData dir via `STORAGE_ROOT` (file_service.py:13-18); JWT/Fernet
  secrets generated once and persisted locally so encrypted BYOK keys survive restarts;
  backend bound to 127.0.0.1 on a dynamically chosen free port, health-checked before
  the window opens (backend.js:1-46).
- **First-run model download (C2):** installers ship **without** the ~700 MB of
  checkpoints; `model_manager.py` holds the canonical URL registry (MACE GitHub
  releases, MatterSim raw GitHub) and streams downloads with pollable progress;
  /api/models + ModelSetup.jsx gate first use (services/model_manager.py:1-60;
  api/models.py; features/models/ModelSetup.jsx). Routes 404 on the web edition
  when heavy tools are off (models.py:20-26).
- **Installers (C3):** electron-builder targets Linux AppImage, macOS dmg, Windows NSIS;
  unsigned for v1 (documented trade-off); auto-update via electron-updater against
  GitHub Releases (packaged builds only; macOS auto-apply needs signing, so effectively
  Windows/Linux) (electron-builder.yml:33-63; main.js:12-21). CI matrix workflow:
  .github/workflows/desktop-release.yml.
- **CPU/GPU variants (C4):** build flavour stamped into package.json
  (`materiaVariant: cpu|gpu`); CPU build pins `MATERIA_DEVICE=cpu` to avoid CUDA-JIT
  crashes from bundled CPU torch; GPU build auto-detects; /api/system powers a
  "Running on GPU/CPU" badge (desktop/package.json:7-9; backend.js:22-33;
  api/system.py:24-42; calculator_factory.py:344-391).
- **Strategic status:** the 2026-07-07 decision made the **web app ship all 23 tools
  server-side** (ENABLE_HEAVY_TOOLS=true in compose), so the earlier "lite web +
  desktop for heavy sims" split (HEAVY_DISABLED_NOTE, graph.py:185-195) is currently
  dormant infrastructure; desktop remains a parallel offering computed on the user's
  own machine (docker-compose.yml:44; per project memory/deployment plan).

---

# 8. Deployment & self-hosting

### Dev vs prod

- **Dev (no Docker):** run uvicorn **from `backend/`** (module path `app.main:app`);
  storage is CWD-independent — STORAGE_ROOT defaults to the *module-relative*
  `backend/app/storage/runs` ("absolute path — never depends on the CWD",
  file_service.py:8-18). SQLite file `backend/materia.db` (config.py:101); an empty
  `DATABASE_URL=` env override forces the SQLite fallback; `JOB_BACKEND=inline` skips
  Redis/Celery (config.py:116; queue.py:52-54). Frontend: `npm run dev` (Vite, port
  5173 — default CORS origins config.py:91-93). NOTE for the paper: there is **no
  "data/ at project root" runtime convention** — the only project-root `data/` is the
  read-only C2DB database (data/c2db/), and generated artifacts live under
  app/storage/runs/.
- **Prod:** `docker compose up -d --build` (docker-compose.yml:1). Five services:

| Service | Image/build | Role | Ports/volumes |
|---|---|---|---|
| postgres | postgres:16-alpine | source of truth DB | pgdata volume, healthcheck pg_isready |
| redis | redis:7-alpine | Celery broker/backend + progress pub/sub | healthcheck ping |
| api | ./backend | FastAPI web (runs `alembic upgrade head` on boot via RUN_MIGRATIONS=1, docker-entrypoint.sh) | models:ro, c2db:ro, POTCAR_DIR→/potcar:ro, shared materia_storage |
| worker | ./backend (same image) | `celery … --concurrency=1` — one long simulation at a time, all cores given to it via OMP/MKL env set before torch import (jobs/worker.py:17-36) | same volumes minus POTCAR |
| caddy | ./frontend (multi-stage: node build → caddy:2-alpine) | serves SPA, reverse-proxies /api and /health,/ready to api:8000, automatic Let's Encrypt HTTPS from SITE_ADDRESS | 80/443; caddy_data volume persists certs (frontend/Caddyfile) |

- **Backend image details:** python:3.12-slim multi-arch (built on Oracle ARM64 or
  amd64); ATAT 3.50 compiled from source with binary existence checks; CPU-only torch —
  PyTorch CPU wheel index on x86_64, default PyPI on aarch64 (no aarch64 CPU-index
  wheels); pip legacy resolver to reconcile mace-torch's e3nn==0.4.4 pin against
  mattersim's metadata; non-root `appuser` (backend/Dockerfile).

### Environment variables (complete inventory)

| Variable | Controls | Cite |
|---|---|---|
| ENV | production ⇒ fail-fast secret validation, invite default, docs hidden | config.py:63-64, 272-318 |
| JWT_SECRET_KEY / JWT_ALGORITHM / ACCESS_TOKEN_EXPIRE_MINUTES | auth tokens (≥32-char non-placeholder enforced in prod) | config.py:37-43, 67-69 |
| FIELD_ENCRYPTION_KEY | Fernet key for BYOK keys at rest (prod refuses plaintext) | config.py:46-54; encryption.py:19-32 |
| SIGNUP_MODE / INVITE_CODES | open/invite/closed registration gate | config.py:80-88, 256-264 |
| GOOGLE_CLIENT_ID | enables "Continue with Google" | config.py:72-78 |
| ALLOWED_ORIGINS | CORS allowlist (wildcard rejected in prod) | config.py:90-93, 250-255 |
| DATABASE_URL / DB_PATH | Postgres DSN (async+sync URL derivation) vs SQLite fallback | config.py:95-101, 179-220 |
| ENABLE_HEAVY_TOOLS | the 6-ML-tool + adsorbate-relax execution gate | config.py:103-112 |
| REDIS_URL / JOB_BACKEND / MAX_JOB_WALLCLOCK_S | broker, celery-vs-inline, 24 h task time limit | config.py:114-117; queue.py:39-47 |
| MAX_OPT_STEPS / MAX_MD_STEPS / MAX_ATOMS / MAX_ACTIVE_JOBS_PER_USER / MAX_UPLOAD_MB | compute caps & quotas (5000 / 50000 / 512 / 3 / 25) | config.py:119-126 |
| STORAGE_ROOT | artifact root override (desktop userData) | file_service.py:13-18 |
| VASP_NCORE / PMG_VASP_PSP_DIR / PMG_VASP_FUNCTIONAL | INCAR NCORE emission; licensed POTCAR mount; PAW folder (PBE_54) | config.py:128-141 |
| MODEL_PROVIDER / GEMINI_API_KEY(S) / GEMINI_MODEL / OLLAMA_BASE_URL / OLLAMA_MODEL | LLM stack + multi-key pool | config.py:143-163 |
| PRE_TRAINED_MODELS_DIR | checkpoint root (compose mounts /models) | calculator_factory.py:31-36 |
| C2DB_DB | C2DB path (default /data/c2db/c2db.db) | providers/c2db.py:14 |
| OQMD_TIMEOUT | OQMD request timeout (120 s) | providers/oqmd.py:24 |
| MATERIA_DEVICE / MATERIA_VARIANT | force cpu/cuda/mps; desktop build flavour | calculator_factory.py:344-353; system.py:33-36 |
| POSTGRES_PASSWORD / SITE_ADDRESS / SITE_URL / POTCAR_DIR | compose-level operator secrets/domain | docker-compose.yml:3-9 |
| RUN_MIGRATIONS | api container applies alembic on boot | docker-entrypoint.sh |

- **External runtime dependencies:** a free Gemini LLM key (BYOK) or a local
  Ollama; Materials Project API key (BYOK, required for MP search — C2DB/OQMD work
  without it); MLP checkpoints (~398 MB, fetched by scripts/fetch_models.sh or the
  desktop model manager); the C2DB .db file (~71 MB); licensed VASP POTCAR library
  (optional, operator-mounted, never committed); ATAT binaries (baked into the image).
- **Hardware assumptions:** production target is an Oracle Cloud Always-Free **Ampere
  A1 (ARM64, 4 OCPU / 24 GB RAM, no GPU)** — heavy sims run CPU-only, serialized to one
  at a time (DEPLOYMENT_GUIDE.md "Step 1"; worker concurrency=1). GPU (CUDA/MPS) is
  auto-used when present (dev box / desktop GPU build).
- **HPC boundary:** Materia runs MLP simulations itself; **DFT stays manual** — the
  user downloads the generated POSCAR/INCAR/KPOINTS/POTCAR(.spec) (and NEB image-folder
  decks, neb.py) and submits them to their own VASP/cluster. No SSH/SLURM integration
  exists [PLANNED].

---

# 9. Data & persistence

### Database (SQLAlchemy; async asyncpg for web, sync psycopg2 for worker — config.py:180-191)

Schema (backend/app/database/models.py):

| Table | Columns (essentials) | Purpose |
|---|---|---|
| users | id, email (unique), hashed_password, full_name, is_active, created_at | accounts (models.py:27-38) |
| sessions | id (uuid str), user_id FK, title, created_at; index (user_id, created_at) | chat sessions (41-56) |
| messages | id, session_id FK, role, content, tool_result (Text/JSON), created_at; index (session_id, id) | full transcript incl. tool cards (59-72) |
| api_keys | id, user_id FK, service, key_value (encrypted, newline-packed multi-key), created/updated; unique (user_id, service) | BYOK store (75-89) |
| jobs | id (uuid hex), user_id, session_id, type, status, spec JSONB, progress JSONB, result JSONB, artifacts JSONB, error, calculator JSONB, spec_hash, created/started/finished_at; indexes on (session_id, created_at) and (user_id, status) | async-job source of truth (92-121) |

JSON columns use JSONB on Postgres, plain JSON on SQLite (models.py:20). Migrations:
Alembic with a single revision `651c27ad893e_initial_schema_with_jobs.py`
(database/migrations/versions/), applied automatically by the api container.
`store.to_jsonable()` sanitizes NumPy scalars before every JSONB write (fixes
MatterSim float32 crashes — store.py:40-63).

### On-disk artifact layout

`STORAGE_ROOT = backend/app/storage/runs/` (or $STORAGE_ROOT/runs), one folder per
session id (file_service.py:13-51):

```
runs/<session-id>/
├── POSCAR                      # the ACTIVE structure (chaining convention)
├── POSCAR_<formula>[_<tag>]    # labeled history copies (slab111, 2x2x1, vac-…, ads-co2…)
├── KPOINTS, <formula>.cif …    # instant-tool outputs
├── <formula>_polymorphs.csv    # search overflow metadata
├── uploads/                    # user uploads (sanitized names)
├── vasp_inputs/<task>/         # POSCAR+INCAR+KPOINTS+POTCAR(.spec) per task
├── optimization/ | md_simulation/ | elastic/ | phonon/ | sqs/ | neb/ | adsorption/
│   └── (CONTCAR, trajectory.{traj,xyz}, *.csv, *.png, results.json,
│        convergence_report.md, phonopy.yaml, bestsqs.out, neb VASP zip, …)
```

Path safety: filename sanitization, traversal rejection, absolute paths only inside the
session, ownership checks on every file route (file_service.py:54-95, 232-274;
api/deps.py:31-55; unit tests tests/unit/test_path_safety.py).

### Reproducibility / logging of tool calls

- Every tool invocation the agent makes is persisted as part of the assistant message's
  `tool_result` (the full FILES card list — chat.py:245-256); manual launches write
  equivalent action cards (upload.py:547-576).
- Every job row keeps the **complete validated spec** (input path, params, calculator
  {type, model}), progress history, result summary, artifact list, timestamps, and a
  spec_hash for dedup/idempotency (models.py:106-121; material_tools.py:109-127).
- Heavy jobs write results.json + convergence_report.md alongside raw CSV/trajectory
  data, so any reported number can be traced to files (simulation service docstrings).
- Sessions export as txt/json via API (chat.py:148-190).

---

# 10. Benchmarks & evaluation (honest status)

A five-tier validation plan (docs/VALIDATION_PLAN.md) **has actually been run** (T1-T5,
dated 2026-06-25), with results committed under docs/validation_results/. Numbers below
are copied from those result files — they are measured, not projected.

- **T1 — MLP accuracy vs Materials Project DFT [RUN]:** 6 potentials × 10 materials =
  60 full relaxations (same code path as the app) + Birch-Murnaghan EOS bulk moduli.
  Overall mean |Δvolume| = **2.65 %**, mean |ΔK| = **8.3 %** vs MP; best geometry:
  mace-omat-0-medium (2.38 %), best stiffness: mattersim-v1.0.0-1M (3.7 %); known
  outliers (magnetic Fe bulk modulus) documented; carbon pinned to diamond deliberately
  (docs/validation_results/T1_mlp_accuracy.md; harness
  backend/scripts/validation/t1_mlp_accuracy.py; parity plots committed).
- **T2 — structure-tool correctness [RUN]:** 23/23 deterministic pytest checks of the
  transforms vs pymatgen ground truth (supercell math, exact vacuum gaps, exact slab
  layer counts, adsorbate placement, SQS substitution composition, format round-trips);
  one real bug found & fixed (adsorbate buried below asymmetric-slab top — sites now
  height-sorted) (docs/validation_results/T2_structure_tools.md;
  backend/tests/validation/test_structure_tools.py).
- **T3 — VASP input fidelity [RUN]:** 21/21 pytest checks (KPOINTS density
  monotonicity & style, POTCAR.spec ordering/labels/ENCUT floor, INCAR presets, ISIF
  map, magnetism auto-detect, DFT+U ordering, modifier tags). ENCUT 520 eV matches
  pymatgen MPRelaxSet exactly; POTCAR label match rate vs MPRelaxSet = 11/16 (69 %),
  with the 5 deviations documented as intentional (docs/validation_results/T3_vasp_inputs.md;
  backend/scripts/validation/t3_potcar_mp_diff.py).
- **T4 — agent tool-selection reliability [RUN, Gemini-only]:**
  39-prompt curated suite (single/multi/structure/compute/ambiguous/out-of-scope/
  conceptual), grading the *first* tool call against expectations with argument
  matching; nothing executed. **Gemini: 37/37 tool-selection (100 %), 22/22 argument
  accuracy (100 %), mean latency 2.09 s** (2 conceptual cases unreached due to
  per-minute quota — near-certain passes). Gemini is the only benchmarked provider:
  Groq was dropped (its token-metered free tier 413s on the ~10.6k-token full-tool
  payload, so it could never complete the suite or a real production call), and Ollama
  is an unbenchmarked desktop-offline fallback. Per-tool/category tables exist for
  per-category reporting via the registry (docs/validation_results/T4_agent_reliability.md;
  harness backend/scripts/validation/t4_agent_reliability.py, suite t4_prompt_suite.py).
- **T5 — performance/scaling [RUN]:** 6 models × Si supercells 8→1024 atoms = 48
  timed energy+force evaluations on CUDA (warm-up excluded, cache bypassed,
  CUDA-synchronized). Asymptotic scaling near-linear: MatterSim-1M t∝N^0.83 …
  MACE variants ~N^0.93 (vs DFT O(N³)); throughput at 1024 atoms: MatterSim-1M
  ≈ 9,776 atoms/s, MACE family ≈ 3,72x-3,744 atoms/s; peak GPU memory recorded
  per point; DFT-time estimates and speedups tabulated (up to ~2.4×10⁵× at 1024
  atoms — note these DFT baselines are *estimates*, label them as such)
  (docs/validation_results/T5_performance.md/.csv). Exact GPU model: the doc says
  only "Device: CUDA" — UNKNOWN — verify with author (project records suggest an
  RTX A4000).
- **CI regression net [RUN continuously]:** GitHub Actions on every push/PR — ruff
  (F,E9) + 22 backend unit tests (auth, caps, config, encryption, health, heavy-tools
  gate, path safety) + frontend lint (advisory)/vitest/build, kept <2 min via
  requirements-test.txt that skips the torch stack (.github/workflows/ci.yml;
  backend/tests/unit/).
- **Not measured / do not claim:** end-to-end multi-turn agent success rates (T4 is
  single-turn first-tool grading); Ollama/qwen3 reliability; production-load
  performance on the Oracle A1 (T5 ran on CUDA, the server is CPU ARM); NEB/phonon/
  elastic accuracy vs DFT references.

---

# 11. Reproducibility, validation & error handling

- **Schema validation:** all 23 tool argument schemas are Pydantic models with typed
  fields, ranges (`ge/le/gt`), Literals, and model-facing descriptions
  (tools/contracts.py); server caps are baked into the schemas themselves
  (e.g. `max_steps ≤ settings.max_opt_steps`, contracts.py:92).
- **Defaults & clamping:** tools normalize and clamp every numeric input
  (e.g. fmax ≥ 0.001, nsw ≤ cap, n_images 3-15) rather than erroring
  (material_tools.py:1428-1429, 1487-1490, 1999-2003).
- **Ambiguity handling:** system-prompt rules make the agent ask rather than guess
  (no valid adsorption site → refuse; unclear SQS sublattice → list_sublattices first;
  NEB with one endpoint → ask for the second) (graph.py:113-135; tool_schemas.py:109-124);
  T4 measured 3/3 correct clarification behaviors on Gemini.
- **Confirmation steps:** the ≥2-step plan gate is an explicit human-in-the-loop
  checkpoint before multi-tool workflows run (§3.2).
- **Cross-tool consistency:** single structure-resolution path (`_resolve_structure` /
  `find_structure_in_session`) and the active-POSCAR convention keep every tool
  operating on the same current structure; supercell atom counts are predicted before
  building; phonon caps apply to the supercell, NEB caps to one image
  (material_tools.py:308-360, 628-637, 1635-1650, 2034-2048).
- **Job-system integrity:** DB-as-source-of-truth, cooperative cancellation via
  `JobCancelled` raised inside the progress callback, 1 s-throttled progress writes
  with phase labels (fixes the "NEB ran 3×" progress illusion), wallclock time limit,
  acks-late + prefetch 1 (domain/jobs.py:42-49; jobs/progress.py:35-86; queue.py:39-47).
- **Fail-fast configuration:** production boot validation (secrets, DB, CORS, invite
  codes — config.py:223-269); import-time tool-registry drift guard (graph.py:30-44);
  Docker build fails if ATAT binaries are missing (Dockerfile:41-45).
- **Error surfaces:** uniform tool error envelopes; friendly provider-error mapping;
  request-id-tagged generic 500s; file-read errors logged privately and never echoed
  with paths (chat.py:139-143).

---

# 12. Limitations & future work

Per component, current honest limitations:

- **Agent:** single-model loop capped at 6 tool rounds; no self-reflection/multi-agent
  roles; T4 covers only single-turn first-tool selection; prompt-injection via uploaded
  file contents is not specifically mitigated beyond preview truncation — UNKNOWN/verify.
- **LLM stack:** Gemini is the sole hosted provider (Groq removed 2026-07-07 — its
  token-metered free tier 413s on the ~10.6k-token full-tool payload); OpenAI/Anthropic
  keys storable but no provider implementation [PARTIAL]; Ollama path unbenchmarked
  (desktop-offline only).
- **Simulations:** MLP-only — no DFT execution, no error-based DFT/ML routing
  (ChatMat-lead feature) [PLANNED]; NVE ensemble implemented in the service but blocked
  by the tool's nvt|npt validation [PARTIAL — bug candidate] (§4); no server wallclock
  cap tuning per job type (single global 24 h); worker concurrency=1 serializes all
  users' heavy jobs on the shared server.
- **Search:** OQMD provider is blocking urllib (flagged for async httpx, oqmd.py:3-7);
  MP requires a user key; C2DB is a static local snapshot (freshness = whenever the
  operator downloaded it).
- **VASP:** input generation only — no SLURM scripts, no execution, no result ingestion
  (OUTCAR parsing) [PLANNED]; POTCAR match to MPRelaxSet intentionally 69 % (documented
  deviations).
- **Frontend:** no router/state library (fine at current size); ~16 pre-existing
  react-hooks lint violations (advisory in CI — ci.yml comment); **3Dmol.js is loaded
  from cdnjs.cloudflare.com at runtime** via a dynamically injected, SRI-pinned `<script>`
  (features/viewer/threeDmol.js) — it is **not** bundled as an npm dep. Consequence: the
  desktop app's structure viewer **fails when offline** (`script.onerror` →
  "Failed to load 3Dmol.js"), despite desktop's local-compute promise. Trajectories play
  as an auto-looping animation, not a manual scrubber (§6).
- **Ops:** Step 10 of the production-readiness plan (backups/runbook) not found in
  docs/ — [PLANNED] per project memory; single-node compose (managed Postgres → S3 →
  LB/replicas ladder planned before public launch, per project memory); README.md is
  effectively empty; **no LICENSE file exists** (root listing, §1) — must be chosen
  before the post-paper open-sourcing (may be intentional under the pre-publication
  embargo). AGENTS.md was **rewritten 2026-07-07** to match the shipped architecture
  (previously described the retired LangGraph/Ollama design) [IMPLEMENTED].
- **Desktop:** unsigned installers (one OS warning); macOS auto-update requires signing
  [PLANNED — roadmap C5]; **SQS/ATAT is deferred by design** in the frozen desktop backend
  (desktop/README.md:57) — the SQS service checks `shutil.which` for the ATAT binaries
  (corrdump/getclus/mcsqs) and degrades gracefully when they are absent (sqs.py:53,99).

---

# 13. Comparison-table source data (Materia column, evidence-backed)

Competitor cells must come only from the two internal reference docs (per
docs/paper/paper_outline.md:105-107 the author marks unsourceable competitor cells
"unverified"). Materia facts with citations:

| Capability | Materia | Evidence |
|---|---|---|
| Conversational streaming web UI (tool cards, plan gate) | **Yes** | api/chat.py:259-346; frontend/src/api/chat.js |
| Local/self-hosted LLM option (fully offline agent) | **Yes** (Ollama qwen3:14b, native tools) | providers/ollama.py; config.py:164-166 |
| Multi-provider failover + multi-key rotation | **Yes** | agent/llm.py:27-133; providers/_keypool.py |
| BYOK encrypted key management (multi-key per provider) | **Yes** | services/key_service.py; core/encryption.py |
| Multi-database unified search (3 sources, one card model) | **Yes** | services/search/service.py:23-87; domain/material_card.py |
| 2D-materials support (dedicated DB + 2D-aware elastic) | **Yes** | providers/c2db.py; simulation/elastic.py:20-29 |
| Structure manipulation suite (9 transform/defect tools) | **Yes** | material_tools.py:714-1141 |
| VASP input generation (11 tasks × 7 modifier axes, POTCAR policy) | **Yes** | domain/vasp.py:20-32; vasp/service.py; vasp/potcar.py |
| MLP simulations: relax, MD, elastic, phonon, SQS, NEB, adsorption; 6 models | **Yes** | jobs/runners.py:89-197; calculator_factory.py:41-56 |
| Async job system (queue, progress, cancel, dashboard, restart-safe) | **Yes** | jobs/*; database/models.py:92-121; api/jobs.py |
| Plan→confirm human gate for multi-tool workflows | **Yes** | agent/planner.py; api/chat.py:196, 330-336 |
| 3D visualization incl. coordination polyhedra | **Yes** | features/viewer/StructureWorkspace.jsx; polyhedra.js |
| Web + desktop distribution | **Yes** (desktop installers hand-delivered pre-paper) | docker-compose.yml; desktop/ |
| Auth, invite gating, rate limiting, quotas | **Yes** | api/auth.py; core/config.py:119-126 |
| Quantitative agent-reliability benchmark | **Yes** (T4; Gemini 37/37, the sole provider) | docs/validation_results/T4_agent_reliability.md |
| MLP-vs-DFT accuracy benchmark (6 models) | **Yes** (T1) | docs/validation_results/T1_mlp_accuracy.md |
| Performance-scaling benchmark | **Yes** (T5) | docs/validation_results/T5_performance.md |
| Actually runs DFT | **No** (generates inputs only) | vasp/service.py (no execution path) |
| HPC/SLURM script generation & submission | **No** [PLANNED] | absent from codebase; paper_outline.md:131 |
| Error-based DFT/ML routing | **No** [PLANNED] | absent |
| Multi-agent roles | **No** (single agent loop) | agent/graph.py |
| Lightweight ML utilities (PCA/CVAE) | **No** [PLANNED] | absent |
| Open-source | On publication (embargoed; repo private, no LICENSE yet) | root listing; project policy |

A ready-made draft of this table with ChatMat/Masgent columns lives at
docs/paper/paper_outline.md:109-133.

---

## Open questions / verify with author

> **Resolved during the 2026-07-07 follow-up pass** (kept here for the record, no longer
> open): **NVE** was a real gate bug — now fixed, runs end-to-end (§3, postmortem
> issue-nve-ensemble-gate.md). **`[JOB:]` SSE event** was redundant dead code — removed;
> job_id rides inside `[FILES:]`. **Trajectory playback** exists as an auto-looping 3Dmol
> animation (no manual scrubber). **Search-chats modal** exists (Sidebar.jsx:70-127).
> **Desktop SQS/ATAT** is deferred by design with a graceful `shutil.which` fallback.
> **Desktop offline** — the 3Dmol viewer is CDN-loaded, so it fails without internet (a
> real desktop limitation, not yet fixed). **AGENTS.md** rewritten to match reality.

Still genuinely needing the author (facts/decisions not derivable from code):

1. **Naming lineage** — was the project ever itself named something else (e.g.
   "MateriaProject" repo name)? "Masgent" is a competitor paper, *not* a former name;
   the paper must not conflate them (README.md:1; docs/paper/paper_outline.md:6).
2. **License** — no LICENSE file exists; is this intentional under the embargo, and
   which license will accompany the post-paper open-sourcing?
3. **Backups/runbook (Step 10)** — production-readiness Step 10 appears unwritten;
   confirm status before any operations claims.
4. **T4 Gemini remaining 2 cases** (C2, C3 conceptual) — run them so the headline can
   say 39/39 instead of 37/37 with a footnote.
5. **Desktop viewer offline** — decide whether to bundle 3Dmol.js locally (adds an npm
   dep + CSP change) so the desktop structure viewer works without internet, or accept
   the online-only limitation and document it.

*(Resolved: T5 GPU = NVIDIA RTX A4000 — doc updated. Groq T4 full pass — moot; Groq
removed 2026-07-07.)*
