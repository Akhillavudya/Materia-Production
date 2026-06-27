# Materia — Deployment & Desktop Roadmap

**Status:** APPROVED — Option (a), full plan (web first, then Electron desktop).
**Created:** 2026-06-26
**Decision owner:** Akhil (student / sole maintainer, ~$0 budget)
**Build order:** locked in `docs/VALIDATION_PLAN.md` §0a — **deploy web first, desktop last.**

---

## 1. Context — why this exists

Validation (T1–T5) is done and the web app is hardened. The remaining goal is to get Materia
into users' hands. The deploy target is **Oracle Cloud Always-Free Ampere A1** (ARM64, 4 CPU /
24 GB RAM, **no GPU**, ~$0 budget). The ML-potential tools (optimize, MD, elastic, phonon, NEB,
SQS) run through a Celery worker that loads torch + MACE/MatterSim — **one careless click would
exhaust that free shared server.**

**Solution: split Materia into two surfaces.**

| Surface | Tools | Compute | Notes |
|---------|-------|---------|-------|
| **Web (Oracle)** | **15 instant tools** only | Server (light) | search, VASP input generation, structure building, defects, symmetry, file ops. **No worker, no torch at runtime.** |
| **Desktop (Electron)** | **ALL 23 tools** | **User's own CPU/GPU** | Full Materia incl. the 6 heavy ML-potential tools. Cross-platform, click-to-download, auto-updating. |

Same codebase, one switch: env flag **`ENABLE_HEAVY_TOOLS`** (`false` on web, `true` on desktop).
Desktop users lose nothing — they get the complete tool set.

**LLM choice:** **online BYOK** (Groq → Gemini fallback over the internet) on both surfaces. Only
the *simulations* run locally on desktop; the chat "brain" stays in the cloud, so the desktop app
stays small and there's no local LLM to bundle/maintain.

---

## 2. The three parts

### Part A — Shared "heavy-tools" gate (~1–2 days) — DO FIRST
One env flag enforced at **three layers** (defence in depth), default ON (dev/desktop), OFF on web:
1. **Config flag** — `backend/app/core/config.py`: `enable_heavy_tools` via `ENABLE_HEAVY_TOOLS`.
2. **Backstop** — `backend/app/tools/material_tools.py` `_enqueue_job()`: if disabled, return a
   friendly "run this in the desktop app" message instead of enqueuing. Protects **every** path
   (agent, manual panel, direct API) — nothing can start a job on the web server.
3. **LLM filter** — `backend/app/agent/graph.py`: hide the 6 heavy tools from `TOOL_SPECS` per
   request when disabled; inject a one-line system-prompt note so the agent points users to desktop.
4. **Frontend signal** — extend `GET /auth/config` with `heavy_tools_enabled`; hide heavy manual
   launch buttons in `ToolLaunchPanel.jsx` / `AsyncJobsPanel.jsx`.

Heavy set: `optimize_structure, run_md_simulation, compute_elastic_tensor, compute_phonons,
compute_neb, generate_sqs` (+ `add_adsorbate` relax path via the backstop).

### Part B — Deploy lite web to Oracle (~2–4 days)
- `docker-compose.web.yml`: **drop the `worker` (and `redis`)**, keep **postgres + api + caddy**.
- Env: `ENV=production`, `ENABLE_HEAVY_TOOLS=false`, `DATABASE_URL` (postgres), `ALLOWED_ORIGINS`
  + `SITE_ADDRESS` (domain → Caddy auto-HTTPS), stable `JWT_SECRET_KEY`/`FIELD_ENCRYPTION_KEY`,
  and **`PMG_VASP_PSP_DIR=/potcar` with the licensed POTCAR dir mounted read-only** (web does
  `generate_vasp_inputs`, which needs PAW files — per `potcar-runtime-mount`).
- Provision Oracle A1, install Docker, open 80/443, point a (free) domain at the IP.
- Smoke test over HTTPS, **then flip `SIGNUP_MODE=invite` LAST** so you don't lock yourself out.

### Part C — Electron desktop app (~2–4 weeks)
New `desktop/` project wrapping the **existing React SPA** (no rewrite):
- **C1** — Electron shell spawns the bundled Python backend (PyInstaller) on localhost in
  **`JOB_BACKEND=inline`** mode (already supported, no Celery/Redis), `ENABLE_HEAVY_TOOLS=true`,
  local SQLite, single auto-logged-in local user.
- **C2** — first-run model download (reuse `scripts/fetch_models.sh`) into user-data dir;
  online BYOK Groq/Gemini key via existing `SettingsPanel`; verify a real local MACE job.
- **C3** — **GitHub Actions matrix** builds `.exe`/`.dmg`/`.AppImage` on every release;
  **electron-updater** auto-updates all users. Ship **unsigned** first (one click-through warning).
- **C4** — *deferred:* optional GPU/CUDA pack (CPU torch ships first, works everywhere).

---

## 3. Timeline (student, part-time)

| Phase | Estimate | Outcome |
|-------|----------|---------|
| A | 1–2 days | Heavy-tools gate, tested |
| B | 2–4 days | **Web live for the lab (~1 week in)** |
| C1 | ~1 week | Electron shell + local backend (CPU) |
| C2 | 3–5 days | Models + online LLM + local job verified |
| C3 | ~1 week | Cross-OS installers + auto-update (unsigned) |
| C4 | later | GPU pack (deferred) |

Web usable after Part B. Desktop ships ~3–4 weeks after that.

---

## 4. Maintenance & safety — the honest version

This drove the architecture, so it's recorded here.

- **Web is low-maintenance** — no worker/torch/GPU/per-user envs; a small FastAPI + Postgres +
  Caddy stack that runs for a long time with near-zero attention. If desktop ever becomes too
  much, **web survives alone.**
- **Desktop is "managed, best-effort" maintenance** — bundling a scientific Python stack onto
  strangers' mixed OSes is where ongoing cost lives. The plan *minimises* it (CI builds all 3 OSes;
  auto-update pushes one fix to everyone; CPU-first avoids CUDA hell; online LLM avoids bundling a
  model) but does not eliminate it.
- **"Leave it auto-updating on GitHub" = frozen, not self-maintaining.** electron-updater only
  delivers releases *you* publish. Stop publishing → the app simply stays at its last version. It
  **cannot auto-break itself.**
- **An unmaintained desktop app cannot harm a user's PC.** It's a normal user-space app (no kernel
  access, no admin needed to run). Simulations use CPU/GPU like any compute app — hardware is
  thermal-protected. Realistic worst case = a future OS update makes it fail to launch and users
  uninstall it. **Graceful death, never destructive.** Mild theoretical risk: stale bundled
  Chromium security patches — low, because it only loads the local app, not the open web.
- **Cheap safeguards that make walking away safe:** pin all deps (torch/mace/mattersim already
  pinned) so a frozen build stays internally consistent; ship a clean uninstaller; **MIT license +
  "provided as-is, no warranty, best-effort" README** (standard for free student software).

---

## 5. Out of scope / deferred
- Slim torch-free web image (optional optimisation; not needed for launch).
- Paid code-signing / Apple notarisation (add later if budget appears).
- GPU/CUDA desktop pack (Part C4).
- Fully-offline local LLM (Ollama bundling) — **rejected** in favour of online BYOK.

---

## 6. Cross-references
- Full execution plan: `/home/roy/.claude/plans/you-already-now-gleaming-crayon.md`
- Build-order rationale: `docs/VALIDATION_PLAN.md` §0a
- Hardening steps 6–10: `docs/PRODUCTION_READINESS_PLAN.md`
- Memory: `production-readiness-steps`, `potcar-runtime-mount`, `local-dev-no-docker`,
  `groq-primary-fallback-chain`, `desktop-deferred-web-only` (now superseded).
