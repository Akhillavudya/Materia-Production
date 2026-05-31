# Materia Project AI Agent Instructions

## Purpose
This file helps AI coding agents understand the Materia repository and make productive changes safely.

## Project overview
Materia is a full-stack materials simulation assistant:
- Backend: `backend` using FastAPI
- Frontend: `frontend` using React + Vite
- Core feature: natural-language agent planning and execution of materials-science tools
- Domain: VASP/POSCAR workflows, Materials Project POSCAR generation, structure editing, and simulation input generation

## Key architecture
- `backend/app/main.py` - FastAPI entry point
- `backend/app/api/chat.py` - chat endpoint, session management, streaming SSE
- `backend/app/core/agent.py` - agent orchestration using `langgraph`
- `backend/app/core/llm.py` - Ollama chat streaming and tool-call parsing
- `backend/app/core/tool_registry.py` - tool definitions and call mapping
- `backend/app/tools/tools.py` - actual tool implementations
- `backend/app/services/file_service.py` - session file management and POSCAR resolution
- `backend/app/database/db.py` - SQLite async database setup

## Important conventions
- The backend streams messages using SSE events from `/api/chat`.
- The frontend expects structured messages such as:
  - `[SESSION:<id>]`
  - `[FILES:{...}]`
  - `[TOOL_START:<tool>]`
  - `[TOOL_END:<tool>:<status>]`
  - `[DONE]`
- Tool results are stored in session history as JSON in `Message.tool_result`.
- Uploaded files and generated outputs are saved under `backend/app/storage/runs/{session_id}`.
- `find_best_poscar()` is used to automatically resolve missing POSCAR paths for tools that require structure files.
- The frontend loads sessions via `/api/sessions` and message history via `/api/sessions/{id}/messages`.

## Run and development commands
- Frontend:
  - `cd frontend && npm install`
  - `cd frontend && npm run dev`
- Backend:
  - Create and activate Python virtual environment
  - `cd backend && pip install -r requirements.txt`
  - `cd backend && uvicorn app.main:app --reload`

## Environment variables
- `OLLAMA_BASE_URL` - Ollama API base URL, default `http://localhost:11434`
- `OLLAMA_MODEL` - Ollama model name, default `qwen3:14b`
- `DB_PATH` - SQLite database path, default `materia.db`
- `MP_API_KEY` - Materials Project API key used by POSCAR generation tools

## Notes for AI agents
- Do not assume frontend/backend are isolated; changes may require coordinating API behavior and UI parsing.
- Prefer modifying existing styles and components in `frontend/src/` rather than adding unrelated frameworks.
- Backend tool behavior is sensitive to tool-call formatting and session file paths.
- Avoid altering session storage behavior unless the change is clearly needed and well-tested.
- If editing `app/core/llm.py` or `app/core/agent.py`, preserve the streaming and tool-call parsing conventions.

## Useful files
- `frontend/src/App.jsx`
- `frontend/src/Chat.jsx`
- `frontend/src/api.js`
- `frontend/src/Sidebar.jsx`
- `frontend/src/RightPanel.jsx`
- `backend/app/api/chat.py`
- `backend/app/core/agent.py`
- `backend/app/core/llm.py`
- `backend/app/core/tool_registry.py`
- `backend/app/tools/tools.py`
- `backend/app/services/file_service.py`
- `backend/app/database/db.py`

## If you need more detail
- Review backend session and message models in `backend/app/database/models.py`.
- Review frontend SSE parsing in `frontend/src/api.js`.
