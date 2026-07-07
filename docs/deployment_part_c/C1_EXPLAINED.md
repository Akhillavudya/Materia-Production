# Part C / C1 — Desktop Spike, Explained (every file + the big picture)

**Status:** ✅ DONE & verified on Linux, 2026-06-27. Local-only, not committed.
**Read the plan first:** `PART_C_DESKTOP_PLAN.md`. This document explains *what was
actually built in C1*, file by file, in beginner-friendly language.

---

## 0. The one-paragraph big picture


The Materia **desktop app is not a new program** — it is the *exact same* web app
(React frontend + FastAPI backend) repackaged so the heavy physics runs on the
user's own computer instead of a tiny free server. We use **Electron** as a
"picture frame": it is really just a Chromium browser plus a Node.js process. When
you open the app, the Node side **starts the Python backend as a hidden local
program**, waits until it is ready, then shows the **same React UI** in the window —
but pointed at `http://127.0.0.1:<port>` instead of a website. The only thing that
still uses the internet is the AI chat (your BYOK Gemini/Groq key).

```
┌────────────────────────── Materia Desktop (one window) ──────────────────────────┐
│                                                                                   │
│   ELECTRON RENDERER (Chromium)            ELECTRON MAIN (Node.js)                 │
│   ┌──────────────────────────┐            ┌──────────────────────────────────┐   │
│   │  the EXISTING React SPA   │            │  main.js   (app lifecycle)        │   │
│   │  (frontend/, built to     │            │  backend.js(spawns the engine)    │   │
│   │   resources/spa/)         │            │     │ spawns                      │   │
│   │                           │  HTTP      │     ▼                             │   │
│   │  fetch(window.__MATERIA   │──────────▶ │  materia-backend  (frozen Python) │   │
│   │   _API__ + "/...")        │ 127.0.0.1  │  = uvicorn app.main:app           │   │
│   └──────────────────────────┘  :<port>   │     JOB_BACKEND=inline            │   │
│              ▲                              │     ENABLE_HEAVY_TOOLS=true       │   │
│              │ preload.js injects the URL  │     SQLite + local files          │   │
│              └────────────────────────────┤  (heavy sims run in a thread here)│   │
│                                            └──────────────────────────────────┘   │
│   AI chat only ───────────────────────────────────────────▶ Gemini / Groq (cloud)│
└───────────────────────────────────────────────────────────────────────────────┘
```

**Which backend?** The *same* `backend/app` FastAPI code as the web app — nothing was
forked. We only changed how it is *started* (env vars) and *packaged* (frozen by
PyInstaller). **Which frontend?** The *same* `frontend/` React SPA — built once with a
relative base path so it works from a local file, and taught to read its API URL at
runtime. So desktop and web share 100% of the product code; they differ only in
*deployment*.

---

## 1. Why this is the same code with two "modes"

There is a single backend with two switches:

| Switch | Web edition | Desktop edition (C1) |
|---|---|---|
| `ENABLE_HEAVY_TOOLS` | `false` — the 6 heavy sims refuse and say "use desktop" | `true` — heavy sims run locally |
| `JOB_BACKEND` | `inline` (no broker needed) | `inline` — jobs run in a background **thread** inside the process |
| Database | PostgreSQL | local **SQLite** file |
| How it's started | Docker container | a **frozen executable** Electron launches |

Because the job system already supports `inline` mode (a job runs in a daemon thread,
no Celery/Redis), the desktop needs **no message broker** — that is the key reason the
whole thing fits in a single bundled program.

---

## 2. The two halves we had to build/package

C1 = prove we can produce, and run, **(A) a frozen backend** and **(B) an Electron
shell that drives it**, then **(C) run one real simulation** through the whole chain.

### A) Freezing the backend (turning Python into a clickable program)

"Freezing" = using **PyInstaller** to bundle the Python interpreter + every library
(torch, MACE, pymatgen, FastAPI, …) + our `app/` code into one folder that runs on a
machine with **no Python installed**. We used **onedir** (a folder, not a single file)
because the science stack is multi-GB and a single-file build would unpack gigabytes
to a temp dir on every launch.

### B) The Electron shell

Electron has two processes: **main** (Node.js, can touch the filesystem and spawn
programs) and **renderer** (Chromium, shows the UI). Main starts the backend; renderer
shows the React app; a tiny **preload** script safely passes the backend's URL from
main to renderer.

---

## 3. Every file, explained

### New folder: `desktop/`

#### `desktop/scripts/run_backend.py`  — the frozen program's entry point
This is the `.py` PyInstaller turns into the `materia-backend` executable. It:
- sets `PYDANTIC_DISABLE_PLUGINS=1` **before any import** (see gotcha #1 below),
- reads `MATERIA_HOST`/`MATERIA_PORT` from the environment,
- imports the **existing** `app.main:app` and runs it with uvicorn.
No new server logic — it's just a clean, import-safe "main()" for the bundle. The app's
own startup hook creates the SQLite tables (`Base.metadata.create_all`), so there is no
database migration step on desktop.

#### `desktop/scripts/build_backend.py`  — the freezer (build tool)
A Python script that calls PyInstaller with the right options. The important parts:
- `--onedir` output to `desktop/resources/backend/materia-backend/`.
- `--paths backend` so `import app...` resolves.
- **`--collect-all`** for packages that ship data files or import by string name:
  pymatgen, ase, mace, mattersim, e3nn, phonopy, seekpath, spglib, matplotlib, uvicorn,
  **passlib, celery, kombu, google.genai, groq**, etc. (`collect-all` grabs a package's
  code + data + every submodule).
- **`--copy-metadata`** for libraries that look up their own version at runtime
  (torch, numpy, ase, …) — without the metadata copied in, that lookup crashes.
- **`--exclude-module`** logfire/IPython/pytest — dev-only packages that aren't used
  and break or bloat the freeze.
You re-run this whenever backend code changes, because the old code is baked into the
binary.

#### `desktop/electron/backend.js`  — boots the local engine
Node module the main process uses. It:
1. finds the frozen executable (dev path now; `process.resourcesPath` when packaged),
2. picks a **free TCP port** (so two installs / other apps never collide),
3. generates **once and persists** local secrets (`JWT_SECRET_KEY`, a Fernet
   `FIELD_ENCRYPTION_KEY`) into Electron's `userData/secrets.json`, so your encrypted
   BYOK API keys still decrypt after a restart,
4. spawns the backend with desktop env: `ENABLE_HEAVY_TOOLS=true`, `JOB_BACKEND=inline`,
   SQLite (`DB_PATH`), models dir, storage dir — all under `userData` so the install
   folder can stay read-only,
5. polls `GET /health` until the server answers, then returns the chosen port.
It also exposes `stopBackend()` to kill the child on quit.

#### `desktop/electron/preload.js`  — the safe bridge
Runs in an isolated context before the SPA loads. It reads the port (passed as a
`--materia-port=NNNNN` launch argument) and exposes
`window.__MATERIA_API__ = "http://127.0.0.1:<port>/api"` to the page. This is how the
React app learns where its backend is, **without** disabling Chromium's security
(context isolation stays on).

#### `desktop/electron/main.js`  — the conductor
The Electron entry point. On launch: `startBackend()` → create the window (with the
preload script and the port argument) → `loadFile(resources/spa/index.html)`. On every
exit path (`window-all-closed`, `before-quit`, `quit`) it calls `stopBackend()` so no
orphan Python process is left running.

#### `desktop/package.json`  — manifest + build scripts
Declares Electron as the dependency and three scripts:
- `build:backend` → freeze the backend,
- `build:spa` → build the React app with `--base=./` (see §4) into `resources/spa`,
- `start` → launch Electron.

#### `desktop/.gitignore`
Ignores `node_modules/`, `build/`, and `resources/` (the frozen backend is ~5 GB and
the SPA is generated) — only source is tracked.

#### `desktop/README.md`
Short operator doc: status, layout, and the exact build/run commands.

### New backend file

#### `backend/requirements-desktop.txt`
`-r requirements.txt` (the full 23-tool stack) **plus** `pyinstaller`. Installed into the
project `venv` before freezing.

### Two **small, web-safe** edits to existing code

#### `frontend/src/api/client.js`
The API base URL now resolves as: **`window.__MATERIA_API__` (desktop) → build-time
`VITE_API_BASE_URL` → `/api` (web default)**. The global is undefined in the browser, so
the web app is completely unaffected. This is what lets the *same* SPA talk to a
same-origin `/api` on the web and a dynamic `127.0.0.1:<port>/api` on desktop.

#### `backend/app/services/storage/file_service.py`
`STORAGE_ROOT` now uses the `STORAGE_ROOT` environment variable when set, otherwise the
old source-relative path. Needed because inside a frozen binary the source-relative path
isn't a writable location; the desktop points it at a writable `userData/storage`. Web
and Docker don't set the variable, so their behaviour is unchanged.

---

## 4. The non-obvious traps we hit (and the lessons)

PyInstaller does **static** analysis — it only sees `import x` it can read in the source.
Anything imported by *string name* at runtime is invisible and must be forced in. Three
real failures, each fixed:

1. **`logfire` → "OSError: could not get source code".** An orphan package registered a
   *pydantic plugin* that calls `inspect.getsource()` at startup. A frozen binary has no
   `.py` source on disk, so it crashed. **Fix:** `PYDANTIC_DISABLE_PLUGINS=1` at the very
   top of `run_backend.py` (+ exclude logfire). *Lesson: frozen apps have no source code —
   anything that introspects source breaks.*
2. **`No module named 'passlib.handlers.bcrypt'`.** passlib loads its hashers by string
   via a registry. **Fix:** `--collect-all passlib`. *Lesson: plugin/registry packages
   need their submodules force-collected.*
3. **`No module named 'celery.fixups'`.** celery imports fixups by string when you build
   a `Celery()` object — which `queue.py` does at import time, even though desktop never
   uses celery (`JOB_BACKEND=inline`). **Fix:** `--collect-all celery kombu`. *Lesson:
   import-time side effects get bundled even for code paths you never run.*

A fourth, non-error caveat: **bundle size = 5.2 GB** because the dev venv has **CUDA
torch**. The desktop release should install **CPU-only torch** first (much smaller, runs
on every machine); a GPU pack is the deferred C4.

The `--base=./` flag on the SPA build matters too: Electron loads the page from a local
file, so the default absolute asset paths (`/assets/...`) would point at the filesystem
root and fail. Relative paths (`./assets/...`) fix it.

---

## 5. Exactly how it was verified (the proof)

1. Froze the backend → ran the executable **with a clean, empty environment** (no venv,
   no Python on PATH): `/health` → ok, `/ready` → `{database: ok, redis: skipped
   (inline)}`, `/api/auth/config` → `heavy_tools_enabled: true`.
2. Drove it over HTTP with a small script: **signup → create session + upload a 2-atom Si
   POSCAR → launch `optimize_structure` (MACE)** → polled the job: it ran **inline in the
   frozen process**, loaded torch + MACE (`mace-mp-0b3-medium`), and **succeeded**
   (`converged`, `final_energy = −7.5885 eV`). This is the decisive result: heavy physics
   really runs inside the frozen binary.
3. Launched the **Electron shell** (`npm start`): `main.js` spawned the backend on a
   dynamic free port (e.g. 33097), `/health` returned 200, and the window loaded the SPA
   against that port. (Clicking through a job in the GUI is the only step left for an
   interactive check.)

---

## 6. Where data lives at runtime (desktop)

Everything mutable is under Electron's `userData` directory (per-OS standard location):
- `materia.db` — SQLite database,
- `models/` — downloaded model checkpoints (first-run download is **C2**),
- `storage/` — generated VASP inputs and job outputs,
- `secrets.json` — locally generated JWT + Fernet keys (chmod 600).

The install directory itself can be read-only — nothing is written next to the program.

---

## 7. What's next

- **C2:** first-run model download UX (reuse `scripts/fetch_models.sh` layout), verify the
  BYOK Gemini/Groq key flow, decide on ATAT/SQS bundling. Likely also make the release use
  CPU-only torch.
- **C3:** `electron-builder` + a GitHub Actions matrix to produce `.AppImage` / `.dmg` /
  `.exe`, plus `electron-updater` auto-update (ship unsigned first).
- **C4 (deferred):** optional CUDA/GPU pack for faster heavy jobs on NVIDIA machines.
