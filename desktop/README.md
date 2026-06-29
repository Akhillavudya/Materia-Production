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

## Status — C3: installers + auto-update (wired)
- **electron-builder** (`electron-builder.yml`) packages three targets: `.AppImage`
  (Linux), `.dmg` (macOS), `.exe`/NSIS (Windows). The frozen backend ships **unpacked**
  via `extraResources` (too big for asar); the SPA + Electron shell go in the app archive.
- **GitHub Actions** (`.github/workflows/desktop-release.yml`): push a `v*` tag →
  ubuntu/macos/windows matrix builds the PyInstaller backend **natively per OS with
  CPU-only torch**, builds the SPA, and `electron-builder --publish always` uploads the
  installers to a GitHub Release. `workflow_dispatch` does a no-publish dry run that
  uploads the installers as build artifacts.
- **electron-updater** checks that Release feed on launch (packaged builds only) and
  downloads updates in the background.

### Release locally / cut a release
```bash
# one-time per machine: CPU torch + freezer (don't reuse the CUDA dev venv for a release)
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision torchaudio
pip install --use-deprecated=legacy-resolver -r backend/requirements-desktop.txt

cd desktop
python scripts/build_backend.py     # freeze backend → resources/backend/
npm run build:spa                   # build SPA → resources/spa/
npm install
npm run pack                        # local unpacked build (no publish), or:
# tag + push to let CI build all 3 OS and publish:
#   (bump desktop/package.json "version" to match) → git tag v0.1.0 && git push prod v0.1.0
```

### Unsigned v1 — caveats (documented on purpose)
- The app is **not code-signed**. Users click through one OS warning on first launch
  (macOS: right-click → Open; Windows SmartScreen: More info → Run anyway).
- **macOS auto-update needs a signed app**, so mac users update by re-downloading the
  `.dmg` until signing lands. Windows (NSIS) and Linux (AppImage) auto-update normally.
- Signing + notarisation is deferred (roadmap §5).

## Known follow-ups
- **CUDA pack (C4):** CPU torch ships first and runs everywhere; an optional CUDA build
  for NVIDIA machines is deferred until after launch.
- **Code signing (C5):** removes the OS warnings and unlocks macOS auto-update.
