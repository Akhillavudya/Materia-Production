/# Deployment — Part C: Electron desktop app (PLAN)

**Status:** 📋 PLAN — not started. Web (Part B) deploy intentionally deferred; we go to
desktop now and **launch web + desktop together after the paper** (per
`materia-going-public`). Current testing = web FULL stack over a Cloudflare tunnel for
PhD students, so the "users in hands" goal is already met without Oracle.
**Parent plan:** `docs/DEPLOYMENT_AND_DESKTOP_ROADMAP.md` (§2, Part C)
**Goal:** ship Materia as a cross‑platform desktop app with **ALL 23 tools**, running
the 6 heavy ML‑potential simulations on the **user's own CPU/GPU**.

---

## 0. The core idea (one paragraph)

Wrap the **existing React SPA** (no rewrite) in an **Electron** shell. On launch,
Electron spawns the **existing FastAPI backend** as a local child process bound to
`127.0.0.1`, running in the already‑proven **`JOB_BACKEND=inline`** mode (no
Celery/Redis) with **`ENABLE_HEAVY_TOOLS=true`** and a **local SQLite** DB. The chat
"brain" stays **online (BYOK Groq/Gemini)** — only the *simulations* run locally. So
the desktop app is "the same Materia, but the heavy physics runs on your machine."

```
┌─────────────────────────── Electron app ───────────────────────────┐
│  Renderer (Chromium)            Main process                        │
│  ┌───────────────────┐          ┌──────────────────────────────┐   │
│  │ existing React SPA │──HTTP──▶ │ spawns bundled Python backend│   │
│  │ (Vite build)       │ 127.0.0.1│ uvicorn app.main:app :PORT   │   │
│  └───────────────────┘          │ JOB_BACKEND=inline           │   │
│         │ online                 │ ENABLE_HEAVY_TOOLS=true      │   │
│         ▼ BYOK                   │ SQLite + local storage       │   │
│   Groq / Gemini (cloud)          └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### What's already done for us (de‑risks the backend side)
- **Inline jobs work without a broker** — `JOB_BACKEND=inline` runs heavy jobs in a
  daemon thread ([[local-dev-no-docker]], [[phase-4-jobs-done]]). No Celery/Redis to bundle.
- **The heavy‑tools switch defaults to ON** — desktop just leaves `ENABLE_HEAVY_TOOLS`
  unset/true; Part A already supports it ([[deploy-desktop-roadmap-approved]]).
- **SQLite fallback** — backend runs on SQLite when `DATABASE_URL` is unset (`DB_PATH`).
- **Dev mode skips strict secret checks** — `ENV != production` means no forced
  JWT/Fernet strength gate (we still generate local secrets, see C1.5).

### The genuinely new / risky work (where to spend caution)
1. **Bundling the scientific Python stack with PyInstaller** (torch + MACE + MatterSim
   + pymatgen + phonopy). This is the §4 "honest risk." **Spike it first.**
2. **729 MB of model checkpoints** can't ship inside the installer → **first‑run download**.
3. **ATAT binaries** (`mcsqs`/`corrdump`/`getclus`) for SQS are external C++ programs,
   not pip packages — must be shipped per‑OS or SQS degrades gracefully.
4. **API base URL** — Electron loads the SPA from `file://`, so the SPA's default
   relative `/api` won't reach the backend. The desktop build must set
   `VITE_API_BASE_URL=http://127.0.0.1:<port>` (`frontend/src/api/client.js:8`).
5. **Single local user** — no signup UX on desktop; auto‑provision + auto‑login one
   local account.

---

## 1. Repo layout (new top‑level `desktop/`)

```
desktop/
  package.json            # electron + electron-builder + electron-updater
  electron/
    main.js               # app lifecycle; spawn/kill backend; create window
    backend.js            # locate + launch the PyInstaller backend, pick a free port,
                          # wait for /health, expose the port to the renderer
    preload.js            # contextBridge: expose backend port / app version
  build/                  # icons, entitlements, electron-builder config
  resources/
    backend/              # PyInstaller output (the frozen FastAPI app) — per‑OS, CI‑built
  scripts/
    build_backend.py      # PyInstaller spec/driver (freezes backend/app -> onedir)
```

The **React SPA stays in `frontend/`** and is built with a desktop flag; its `dist/`
is copied into the Electron package at build time. **No SPA rewrite.**

---

## 2. C1 — Local spike (Linux only): shell + bundled backend  ⟵ DO FIRST

**Goal:** prove the hardest thing cheaply — a PyInstaller‑frozen backend that loads
torch/MACE and runs **one real local heavy job**, driven by a minimal Electron shell,
on *your* Linux box. No cross‑OS, no installers, no auto‑update yet.

**C1.1 — Freeze the backend with PyInstaller**
- Add `pyinstaller` to a `backend/requirements-desktop.txt` (= full `requirements.txt`).
- Write `desktop/scripts/build_backend.py` producing a **onedir** bundle of
  `uvicorn app.main:app`. Expect to fight **hidden imports** and **data files**:
  - hidden imports: `uvicorn` workers, `pymatgen` data, `ase`, `mace`, `mattersim`,
    `e3nn`, `phonopy`, `asyncpg`/`aiosqlite`, alembic migration modules.
  - data: alembic `versions/`, pymatgen's bundled data, any `.json`/`.cfg` resources.
- **Acceptance:** `./dist/backend/materia-backend` starts uvicorn and `GET /health`
  returns ok — outside any Python env.

**C1.2 — Minimal Electron shell**
- `desktop/electron/backend.js`: pick a free port, spawn the frozen backend with env
  `ENV=development`, `ENABLE_HEAVY_TOOLS=true`, `JOB_BACKEND=inline`,
  `DATABASE_URL=` (SQLite), `DB_PATH=<userData>/materia.db`,
  `PRE_TRAINED_MODELS_DIR=<userData>/models`, storage under `<userData>`.
- Poll `/health` until ready, then `loadURL` the SPA pointed at that port.
- On quit, **kill the backend child** (and any inline job threads die with it).

**C1.3 — Point the SPA at the local backend**
- Build the SPA with `VITE_API_BASE_URL=http://127.0.0.1:<port>` — but the port is
  dynamic. Options (pick in spike): (a) fixed port with fallback, or (b) inject the
  chosen port via `preload.js` + a tiny runtime shim that sets the base URL before the
  app boots. **(b) is cleaner**; decide during the spike.

**C1.4 — Models for the spike**
- Just **symlink/copy** your existing `pre_trained_models/` into the userData models
  dir so the spike isn't blocked on the download UX (that's C2).

**C1.5 — Single local user + local secrets**
- On first run, generate a stable `JWT_SECRET_KEY` + `FIELD_ENCRYPTION_KEY` into the
  userData dir (so encrypted BYOK keys survive restarts). Auto‑create one local user
  and auto‑login (e.g. `SIGNUP_MODE=open` + a one‑time bootstrap call, token cached by
  the shell). Confirm the exact mechanism against `app/api/auth.py` during the spike.

**C1 acceptance (the go/no‑go gate):** from a built Electron app on Linux, open the
real UI, set a BYOK key, and **run a real `optimize_structure` (MACE) job to completion
locally** — results render in the timeline. If PyInstaller + torch proves too painful,
fall back options to evaluate *before* C3: a Briefcase/Nuitka freeze, or shipping a
self‑contained Python (python‑build‑standalone) + venv instead of a single freeze.

---

## 3. C2 — Models + online LLM + verified local job (productionize C1)

- **First‑run model download UX:** reuse the layout from `scripts/fetch_models.sh`
  (the 4 MACE + 2 MatterSim folders). A first‑run screen downloads ~729 MB (or a
  trimmed default set — e.g. ship only `mace-mp-0b3-medium` + `mattersim-1M` first,
  ~offer others on demand) into `<userData>/models`. Show progress; verify checkpoints
  with the same `_has_checkpoint` logic the factory uses.
- **BYOK online LLM:** wire the existing **SettingsPanel** key flow
  ([[groq-primary-fallback-chain]]); Gemini primary → Groq fallback over the internet.
  No local LLM bundled (Ollama path stays optional/unused).
- **ATAT/SQS decision:** either bundle prebuilt `mcsqs/corrdump/getclus` per OS under
  `resources/atat/` and add to PATH, or let SQS degrade with the existing
  "ATAT not found" message. Recommend **defer ATAT bundling** (SQS is 1 of 23 tools).
- **Acceptance:** clean machine → install → download models → set key → run MACE +
  MatterSim jobs; chat works online.

---

## 4. C3 — Cross‑OS installers + auto‑update (ship it)

- **electron‑builder** targets: `.AppImage` (Linux), `.dmg` (macOS), `.exe`/NSIS (Windows).
- **GitHub Actions matrix** (ubuntu/macos/windows runners): build the PyInstaller
  backend *per OS* (native — no cross‑compiling torch), then electron‑builder packages
  each. Publish to a **GitHub Release** on tag.
- **electron‑updater** auto‑updates from GitHub Releases. **Ship UNSIGNED first** (one
  OS warning click‑through; document it in the README).
- **Acceptance:** tag → CI produces 3 installers → fresh installs on each OS launch and
  run a local job → publishing a new tag auto‑updates an installed client.

**Status — implemented 2026‑06‑29 (not yet release‑tested):**
- `desktop/electron-builder.yml` — appId `ai.materia.desktop`, 3 targets, frozen backend
  via `extraResources` (unpacked), SPA+shell in asar, GitHub publish → `Materia-Production`.
- `desktop/package.json` — added `electron-builder` (dev) + `electron-updater` (runtime),
  `pack`/`dist` scripts; lockfile updated.
- `desktop/electron/main.js` — `electron-updater` checks the Release feed on launch
  (packaged builds only).
- `desktop/build-assets/icon.png` — 1024² placeholder; electron-builder auto-derives
  `.icns`/`.ico`.
- `.github/workflows/desktop-release.yml` — `v*` tag → matrix → CPU torch + freeze +
  SPA + `electron-builder --publish always`; `workflow_dispatch` = no-publish dry run
  that uploads installers as artifacts.
- **Caveats (v1):** unsigned (one OS warning); **macOS auto-update needs signing** so mac
  updates are manual re-download for now; Win/Linux auto-update works.
- **Remaining go/no-go:** push a `v*` tag (or run the dry-run workflow) → confirm all 3
  installers build green and a fresh install runs a local MACE job. C4 (CUDA) + C5
  (signing) deferred.

---

## 5. C4 — GPU/CUDA pack (DEFERRED)

CPU torch ships first and works everywhere. A later optional CUDA build improves heavy‑job
speed on NVIDIA machines. Out of scope until after launch.

---

## 6. Risks & mitigations (the honest list)

| Risk | Mitigation |
|------|-----------|
| PyInstaller + torch/MACE bundling pain | **C1 spike first**; fallbacks: python‑build‑standalone, Nuitka, Briefcase |
| 729 MB models too big for installer | First‑run download (C2); ship a trimmed default set |
| ATAT (SQS) not pip‑installable | Defer bundling; SQS degrades gracefully on web‑less binaries |
| `file://` SPA can't reach `/api` | Build with `VITE_API_BASE_URL=127.0.0.1:<port>`; inject dynamic port via preload |
| Unsigned app warnings | Accept for v1 (documented); paid signing deferred (roadmap §5) |
| Stale bundled Chromium CVEs | Low — loads only the local app; electron‑updater pushes Electron bumps |
| Orphaned backend process | Main process owns the child; kill on quit/crash |

## 7. Timeline (student, part‑time — from roadmap §3)
- C1 ~1 week · C2 3–5 days · C3 ~1 week · C4 later.
- **Launch web (Part B Oracle flip) + desktop together** after the paper.

## 8. Sequencing vs Part B
Independent. Part B artifacts are built and parked on `feat/deploy-part-a-heavy-tools-gate`
([[deploy-desktop-roadmap-approved]]); the Oracle flip is a ~half‑day operator task done
at launch time. Nothing in Part C touches Part B.

---

### Beginner takeaway
> The desktop app is **not a new program** — it's the *same* Materia website packaged
> with its own little engine inside. Electron is the picture frame (a browser), and it
> quietly starts the Python backend on your own computer so the heavy physics runs on
> *your* CPU/GPU instead of a tiny free server. The only thing that still uses the
> internet is the AI chat. The one genuinely hard step is squeezing the scientific
> Python stack into a clickable file — so we test *that* first, on one OS, before
> building the fancy cross‑platform installers.
