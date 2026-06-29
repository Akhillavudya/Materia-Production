# Materia Desktop (Part C)

Electron shell that runs the **full 23-tool** Materia backend — including the 6 heavy
ML-potential simulations — **on the user's own CPU/GPU**. It wraps the existing React
SPA (no rewrite) and spawns the existing FastAPI backend (PyInstaller-frozen) on a
local port in `JOB_BACKEND=inline` mode (no Celery/Redis). The chat "brain" stays
online (BYOK Gemini/Groq); only the simulations run locally.

See `docs/deployment_part_c/PART_C_DESKTOP_PLAN.md` for the full plan.

## Status — C1 spike: DONE & verified (Linux)
- Frozen backend boots standalone (no Python installed) → `/health`, `/ready` ok.
- A real `optimize_structure` MACE job runs to completion **inside the frozen binary**
  (torch + MACE load and converge).
- Electron spawns the backend on a dynamic free port and loads the SPA against it.

## Layout
```
desktop/
  package.json            electron + build scripts
  electron/
    main.js               app lifecycle: start backend → window → kill on quit
    backend.js            free port, local secrets, spawn frozen backend, wait /health
    preload.js            exposes window.__MATERIA_API__ (dynamic port) to the SPA
  scripts/
    run_backend.py        frozen entry point (uvicorn app.main:app)
    build_backend.py      PyInstaller driver (onedir)
  resources/              build outputs (git-ignored)
    backend/              frozen backend bundle
    spa/                  built React SPA (relative base)
```

## Build & run (dev, Linux)
```bash
# 1) freeze the backend (uses the project venv with the full ML stack + pyinstaller)
./venv/bin/pip install -r backend/requirements-desktop.txt   # once
cd desktop && npm run build:backend          # → resources/backend/ (large)

# 2) build the SPA with a file://-safe relative base
npm run build:spa                            # → resources/spa/

# 3) install electron + launch the app
npm install
npm start
```

On launch the app stores all mutable state under Electron's `userData` dir:
`materia.db` (SQLite), `models/` (downloaded checkpoints — C2), `storage/` (job
outputs), and `secrets.json` (locally-generated JWT + Fernet keys).

## Status — C2: DONE (Linux)
- **First-run model download:** a screen offers to fetch the ML checkpoints into
  `userData/models` (recommended set or all), with live progress; backed by
  `/api/models` (gated to the desktop edition). See `docs/deployment_part_c/C2_EXPLAINED.md`.
- **BYOK LLM:** the existing SettingsPanel key flow (Gemini→Groq) works in the
  desktop window; fixed an `auth.js` bug that broke login/key-save under `file://`.
- **SQS/ATAT:** deferred — SQS degrades gracefully when ATAT isn't on PATH.

## Known follow-ups
- **Release torch:** the spike bundle uses the venv's CUDA torch (~5 GB). Releases
  should install CPU-only torch first (much smaller).
- **C3:** electron-builder + GitHub Actions matrix (.exe/.dmg/.AppImage) + auto-update.
