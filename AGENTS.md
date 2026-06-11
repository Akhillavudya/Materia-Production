# Materia Project AI Agent Instructions

## Purpose
This file helps AI coding agents understand the Materia repository and make productive changes safely.

## Project overview
Materia is a full-stack materials simulation assistant:
- **Backend**: `backend/` — FastAPI + SQLite (async), LangGraph agent, Ollama LLM
- **Frontend**: `frontend/` — React 19 + Vite, streaming SSE chat UI
- **Domain**: VASP/POSCAR workflows, multi-database material search (MP, C2DB, OMat24, OQMD), MLP simulations

---

## Backend layout (`backend/app/`)

| Path | Responsibility |
|------|---------------|
| `main.py` | App factory, middleware, router registration |
| `api/` | HTTP route handlers — thin layer, no business logic |
| `api/auth.py` | Signup / login / me |
| `api/chat.py` | Chat, session CRUD, file serving, SSE streaming |
| `api/keys.py` | User API-key store |
| `api/upload.py` | File upload |
| `api/deps.py` | **Shared** ownership / path-safety helpers (used by chat + upload) |
| `agent/` | LangGraph planning and execution |
| `agent/graph.py` | Full agent graph (planner → step_picker → tool_executor → summarizer) |
| `agent/llm.py` | Ollama streaming (`stream_chat`) |
| `agent/tool_registry.py` | Tool metadata + callable map |
| `core/config.py` | Centralized `Settings` — single source of truth for env vars |
| `core/security.py` | JWT auth, password hashing, `get_current_user` dependency |
| `core/encryption.py` | Fernet field-level encryption for stored API keys |
| `core/limiter.py` | SlowAPI rate limiter |
| `core/logging.py` | Logging configuration (`configure_logging`, `get_logger`) |
| `database/models.py` | SQLAlchemy ORM: `User`, `Session`, `Message`, `ApiKey` |
| `database/db.py` | Async engine, session factory, `init_db` |
| `repositories/` | **All** raw DB queries live here — routes never build `select()` directly |
| `schemas/` | Pydantic request/response models (`auth.py`, `chat.py`, `key.py`, `upload.py`) |
| `services/file_service.py` | Session storage, POSCAR resolution, upload guards |
| `services/key_service.py` | Load user API keys into `os.environ` before tool calls |
| `services/search_service.py` | All material search: MP, C2DB, OQMD functions + `search_all_sources` orchestrator |
| `services/md_service.py` | ASE MD simulation runner |
| `services/optimization_service.py` | ASE geometry optimization runner |
| `services/calculator_factory.py` | MACE / MatterSim calculator factory |
| `services/incar_kpoints_service.py` | VASP INCAR / KPOINTS generator |
| `tools/material_tools.py` | **All** agent-callable tools: search, POSCAR, VASP inputs, optimize, MD |

---

## Frontend layout (`frontend/src/`)

| Path | Contents |
|------|---------|
| `api/client.js` | Base HTTP client — auth headers, 401 handler, `authRequest`, `downloadBlob` |
| `api/auth.js` | signup, login, getMe |
| `api/sessions.js` | fetchSessions, fetchMessages, fetchJobs, download exports |
| `api/chat.js` | `streamChat` — full SSE parser |
| `api/files.js` | fetchSessionFilesGrouped, fetchFileContent, downloadFile, uploadFiles |
| `api/keys.js` | saveApiKey |
| `api/c2db.js` | searchC2DB |
| `api/index.js` | Barrel re-export of all slices |
| `features/auth/` | AuthScreen |
| `features/chat/` | Chat, ToolStatus, ApiKeyForm, UploadButton |
| `features/files/` | FileCard, FilePanel |
| `features/sessions/` | Sidebar, RightPanel, JobDashboard |
| `features/viewer/` | StructureViewer |
| `styles/` | index.css, App.css |
| `App.jsx` | Root layout and auth gate |
| `main.jsx` | React entry point |

---

## SSE event protocol (`/api/chat` response stream)

```
data: {"type":"token","value":"..."}   — text token
data: {"type":"status","value":"..."}  — spinner label
data: [FILES:{...json...}]             — tool result card
data: [TOOL_START:<tool_name>]
data: [TOOL_END:<tool_name>:<status>]
data: [NEED_API_KEY:<service>]
data: [SESSION:<session_id>]
data: [DONE]
```

Tool results are persisted to `Message.tool_result` as a JSON array.

---

## Environment variables
Copy `backend/.env.example` to `backend/.env` and fill in real values.

| Variable | Default | Notes |
|----------|---------|-------|
| `JWT_SECRET_KEY` | — | **Required** for auth |
| `FIELD_ENCRYPTION_KEY` | — | Fernet key for stored user API keys |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | Comma-separated CORS origins |
| `DB_PATH` | `materia.db` | SQLite file path |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | — |
| `OLLAMA_MODEL` | `qwen3:14b` | — |
| `MP_API_KEY` | — | Can be set per-user at runtime |

---

## Run commands
```bash
# Backend
cd backend && source ../venv/bin/activate
uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

---

## Key conventions for AI agents
- **Config first**: all env reads go through `app.core.config.settings` — never add raw `os.getenv()` calls to new code.
- **Repository pattern**: add new queries to `app/repositories/`, not inline in routes.
- **Schemas**: add new request/response shapes to `app/schemas/`, not as inline `BaseModel` inside route files.
- **Logging**: use `get_logger(__name__)` — no bare `print()`.
- **Frontend API**: add new API calls as a new slice in `src/api/` and re-export from `src/api/index.js`.
- **SSE protocol**: any change to the event format must be reflected in both `agent/graph.py` (emit) and `api/chat.js` (parse).
- **No secrets in git**: `.env`, `*.db`, `data/`, `pre_trained_models/` are gitignored.
- **POSCAR resolution**: `find_best_poscar()` in `file_service.py` auto-resolves missing paths — do not add parallel logic elsewhere.
