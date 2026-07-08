# Materia Project AI Agent Instructions

## Purpose
This file helps AI coding agents understand the Materia repository and make productive
changes safely. For a deep, provenance-cited reference (every claim tied to a
`file:line`), read **`docs/information.md`** — that is the authoritative fact base and
should win if this summary and the code ever disagree.

## Project overview
Materia is a full-stack conversational assistant for computational materials science:
- **Backend**: `backend/` — FastAPI (async, uvicorn). **Native function-calling agent**
  over a pluggable LLM provider chain. Postgres in production (async `asyncpg` + a sync
  `psycopg2` path for the Celery worker), with a SQLite fallback for local dev / desktop.
- **Frontend**: `frontend/` — React 19 + Vite 8, streaming SSE chat UI, no router/state lib.
- **Desktop**: `desktop/` — Electron shell + PyInstaller-frozen backend; jobs run inline.
- **Domain**: VASP/POSCAR input generation, multi-database material search
  (MP, C2DB, OQMD), and ML-potential (MACE / MatterSim) simulations run as async jobs.

> **Heads-up on a retired design.** Earlier versions used a LangGraph
> planner→picker→executor graph and an Ollama-only LLM. **That is gone.** The shipped
> agent is a single native function-calling loop (`agent/graph.py`, `MAX_TURNS=6`) driven
> by whichever provider `model_provider` resolves to. Do not reintroduce LangGraph or
> regex/JSON-forcing planning.

---

## Backend layout (`backend/app/`)

| Path | Responsibility |
|------|---------------|
| `main.py` | App factory, middleware, router registration |
| `api/` | HTTP route handlers — thin layer, no business logic (`auth`, `chat`, `keys`, `upload`, `files`, `jobs`, `models`, `catalog`, `system`, `health`) |
| `api/deps.py` | Shared ownership / path-safety helpers |
| `agent/graph.py` | The native function-calling agent loop + `SYSTEM_PROMPT`; import-time schema/registry drift guard |
| `agent/planner.py` | Optional tools-free JSON planner for the ≥2-step plan→confirm gate (best-effort; calls the same provider with no tools) |
| `agent/llm.py` | `FallbackProvider` chain wrapper + streaming buffer |
| `agent/providers/` | Provider abstraction: `base.py`, `gemini.py`, `ollama.py`, `_keypool.py` (multi-key 429 rotation) |
| `agent/tool_registry.py` | Tool name → callable map |
| `agent/tool_schemas.py` | LLM-facing JSON schemas, derived from the Pydantic contracts |
| `tools/contracts.py` | **Single source of truth** — Pydantic input models for all 23 tools |
| `tools/material_tools.py` | All 23 agent-callable tool implementations |
| `domain/` | Framework-free types: `jobs.py`, `material_card.py`, `vasp.py` |
| `jobs/` | Async job system: `queue.py`, `runners.py`, `worker.py` (Celery), `store.py`, `progress.py` |
| `services/search/` | Multi-DB search: `providers/` (MP, C2DB, OQMD) + `service.py` orchestrator, `mappers.py` |
| `services/vasp/` | VASP inputs: `incar.py`, `kpoints.py`, `poscar.py`, `potcar.py`, `templates.py`, `service.py` |
| `services/simulation/` | ML-potential runners: `optimization.py`, `md.py`, `phonon.py`, `elastic.py`, `sqs.py`, `neb.py`, `neb_path.py`, `calculator_factory.py`, `report.py`, `plots.py` |
| `services/structure/` | `builder.py`, `adsorption.py`, `activation.py` |
| `services/storage/file_service.py` | Session dirs, POSCAR/CONTCAR resolution, path-safety guards |
| `services/key_service.py` | Load user BYOK keys before tool calls |
| `services/model_manager.py` | ML-checkpoint registry (desktop first-run download gate) |
| `core/config.py` | Centralized `Settings` — single source of truth for env vars + production fail-fast validation |
| `core/security.py` / `core/encryption.py` | JWT auth; Fernet field-level encryption for stored keys |
| `database/models.py` | SQLAlchemy ORM: `User`, `Session`, `Message`, `ApiKey`, `Job` |
| `database/db.py` | Async engine + session factory |
| `alembic/` | Migrations (applied on boot when `RUN_MIGRATIONS=1`) |

---

## Frontend layout (`frontend/src/`)

| Path | Contents |
|------|---------|
| `api/client.js` | Base HTTP client — auth headers, 401 handler, `authRequest`, `downloadBlob` |
| `api/chat.js` | `streamChat` — the SSE parser (see protocol below) |
| `api/` slices | `auth`, `sessions`, `files`, `keys`, `c2db`, `jobs`, `models`, `neb`, `system`, `tools`; barrel in `index.js` |
| `features/auth/` | AuthScreen (email + "Continue with Google") |
| `features/chat/` | Chat, ToolStatus, ApiKeyForm, plan/confirm cards |
| `features/files/` | FileCard (incl. async JobCard), FilePanel, inline FileViewer |
| `features/sessions/` | Sidebar, RightPanel, ToolLaunchPanel, AsyncJobsPanel |
| `features/viewer/` | 3Dmol.js structure viewer + client-side coordination polyhedra |
| `features/settings/` | Multi-key BYOK settings |
| `features/models/` | Desktop first-run model setup |
| `features/landing/` | Landing / greeting |

---

## SSE event protocol (`/api/chat` response stream)

```
data: {"type":"token","value":"..."}    — text token
data: {"type":"status","value":"..."}   — spinner label
data: [TOOL_START:<tool_name>]
data: [TOOL_END:<tool_name>:<status>]
data: [FILES:{...json...}]              — tool result card (job_id/type ride INSIDE this)
data: [PLAN:{...json...}]               — proposed multi-tool plan (confirm gate)
data: [NEED_API_KEY:<service>]
data: [SESSION:<session_id>]
data: [DONE]
```

There is **no** `[JOB:]` event — a queued job's `job_id` travels inside the `[FILES:]`
payload, which is what both `api/chat.py` and the frontend consume.

---

## Environment variables (see `core/config.py` for the full list)

| Variable | Default | Notes |
|----------|---------|-------|
| `JWT_SECRET_KEY` | — | **Required** for auth (fail-fast in prod) |
| `FIELD_ENCRYPTION_KEY` | — | Fernet key for stored user API keys |
| `DATABASE_URL` | SQLite fallback | Postgres in prod; sync/async URLs derived automatically |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker/result backend |
| `JOB_BACKEND` | `celery` | `celery` (web) or `inline` (dev / desktop, no broker) |
| `MODEL_PROVIDER` | auto | `gemini` (default) → `ollama` fallback chain (Ollama = desktop-offline only) |
| `GEMINI_API_KEY` / `GEMINI_API_KEYS` | — | Usually per-user BYOK at runtime; `_KEYS` (comma list) feeds the rotation pool |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `…:11434` / `qwen3:14b` | Local fallback |
| `ENABLE_HEAVY_TOOLS` | `true` | Gates the ML-potential simulation tools |
| `SIGNUP_MODE` | `open` (dev) / `invite` (prod) | `open` \| `invite` \| `closed` |
| `INVITE_CODES` | — | Required when `SIGNUP_MODE=invite` (app refuses to boot if empty) |
| `PMG_VASP_PSP_DIR` | — | Licensed POTCAR tree, mounted read-only; else POTCAR.spec |
| `MAX_ATOMS` / `MAX_MD_STEPS` | `512` / `50000` | Simulation guardrails |

---

## Run commands
```bash
# Backend (local dev, SQLite + inline jobs)
cd backend && source ../venv/bin/activate
uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev

# Full stack (Docker: postgres + redis + api + worker + caddy)
docker compose up -d --build
```

---

## Key conventions for AI agents
- **Config first**: all env reads go through `app.core.config.settings` — never add raw `os.getenv()` calls to new code.
- **One tool, three files stay in sync**: a new tool needs a Pydantic model in `tools/contracts.py`, a schema entry in `agent/tool_schemas.py`, AND a registry entry in `agent/tool_registry.py`. The `graph.py` import-time drift guard will refuse to start if they disagree.
- **Provider-neutral**: talk to the LLM through the `LLMProvider` abstraction, never a vendor SDK directly. Respect the Gemini→Ollama fallback and the multi-key rotation in `_keypool.py` (Gemini is the sole web provider; Ollama is desktop-offline only).
- **Long tools enqueue**: simulations return a `job_id` immediately via `jobs/`, they do not block the request.
- **SSE protocol**: any change to the event format must be reflected in both `agent/graph.py` (emit) and `api/chat.js` (parse).
- **No secrets in git**: `.env`, `*.db`, `data/`, `pre_trained_models/`, licensed POTCARs are gitignored — never stage them.
- **POSCAR resolution**: `services/storage/file_service.py` auto-resolves session structures (CONTCAR-preferred) — do not add parallel logic elsewhere.
- **Postmortems**: after fixing any bug, add `docs/issues_solved/issue-<slug>.md` (symptom / root cause / fix / files / verify / lesson) per `CLAUDE.md`.
