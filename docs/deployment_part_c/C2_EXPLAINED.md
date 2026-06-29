# Part C / C2 — Models + online LLM + verified local job

**Status:** ✅ DONE (Linux, local). Productionises the C1 spike so a clean install
can fetch its own ML‑potential checkpoints, set a BYOK chat key, and run the heavy
simulations locally. Parent plan: `PART_C_DESKTOP_PLAN.md` §3.

---

## 🪜 Big picture (read this first if you're new)

Imagine Materia Desktop is a **brand‑new microwave** you just unboxed.

- **C1** proved the microwave *turns on and can actually cook* — we plugged it in
  once on our own bench and heated one real meal (a frozen MACE job ran to
  completion inside the packaged app). That was the scary "does the hardware even
  work" test.
- **C2** is everything that makes it usable by *someone else who just bought it*:
  the **recipe books don't fit in the box**, so the microwave offers to download
  them the first time you switch it on; you have to **plug in your own electricity**
  (your AI key); and one rare accessory (SQS) isn't included, so the screen politely
  says "not available" instead of sparking.

In software terms, C2 turns "it works on my machine, fully set up" into "a stranger
can install it clean and get going." Three concrete jobs:

1. **Ship the app small, fetch the heavy bits on first run** (the ML models).
2. **Make the user's own online AI key actually work inside the desktop window.**
3. **Decide what to do about the one tool we can't bundle** (SQS/ATAT).

---

## 📚 Core concepts (the new ideas, in plain words)

**What is a "model" / "checkpoint" here?**
The heavy simulations (relaxing a crystal, molecular dynamics, etc.) need a trained
neural‑network "physics brain" called an **ML interatomic potential** (MACE,
MatterSim). A **checkpoint** is just the saved file of that trained brain — a big
`.model`/`.pth` file (~18–95 MB each). The code that loads them is the *calculator
factory*; it looks in a folder and grabs the checkpoint file inside.

**Why download them instead of shipping them?**
All six checkpoints together are hundreds of MB. Stuffing them into the installer
would make the download enormous and force everyone to re‑download them on every app
update. So we ship the *app* small and **download the models once, on first run**,
onto the user's disk — the same idea as a game that downloads its big texture packs
after you install it. (Analogy: you buy the bookshelf; you choose which heavy books
to put on it later.)

**Where do they go? (`PRE_TRAINED_MODELS_DIR`)**
An environment variable that tells the backend which folder holds the models. The
Electron shell points it at a writable per‑user spot (`userData/models`) so the
install directory itself can stay read‑only.

**Background thread + "polling" (how the progress bar works).**
Downloading 90 MB takes a while. If the web request that *starts* the download had
to wait for it to finish, the UI would freeze. Instead:
- the backend kicks the download off in a **background thread** (a worker running
  alongside the main program) and immediately replies "started";
- the thread keeps updating a little in‑memory note: "downloaded X of Y bytes";
- the frontend **polls** — i.e. asks "how's it going?" every 1.5 seconds — and draws
  the progress bar from the answer. (Analogy: you order a pizza and hang up; you
  don't hold the phone for 30 minutes — you glance at the tracker now and then.)

**The `.part` file + atomic rename (why a crash can't corrupt things).**
We write the incoming bytes to `mattersim.pth.part`. Only when the whole file has
arrived *and* looks valid do we **rename** it to the real `mattersim.pth`. Renaming
is instant and all‑or‑nothing, so the app never sees a half‑finished file and
mistakes it for a working model. (Analogy: you write a letter on scrap paper and
only drop it in the mailbox once it's complete — never a half‑sentence.)

**Single source of truth (one registry).**
Before C2 the download URLs lived in two separate scripts; that's how lists drift
out of sync. Now every URL/size/filename lives in **one** place
(`model_manager.py`) and both the desktop UI *and* the old command‑line scripts read
from it. Change a URL once, everywhere updates.

**BYOK = "Bring Your Own Key".**
Materia doesn't pay for your AI usage; you paste your own free Google Gemini key
(with Groq as an automatic backup). The simulations run locally; only the *chat
brain* talks to the internet, using your key.

**The `file://` problem (a subtle desktop‑only bug we fixed).**
A normal website talks to its backend with a relative address like `/api`. But the
desktop app loads its screen from a local file (`file://…/index.html`) and runs the
backend on a random local port chosen at launch. A relative `/api` there resolves to
the nonsense `file:///api/...` and fails. The fix: hand the real address
(`http://127.0.0.1:<port>/api`) to the page and make *every* network call use it —
including login/signup, which had been hard‑coded to `/api`.

**The "heavy‑tools gate" (one app, two editions).**
The same codebase ships as a small **web** edition (no local simulations) and the
**desktop** edition (all simulations). A single switch, `ENABLE_HEAVY_TOOLS`,
decides which. We reuse it so the new model screen *only* exists on desktop: on web
the `/api/models` routes simply return **404** and the UI never shows the screen.

**Graceful degradation.**
When a feature can't run, it should explain itself, not crash. SQS needs an external
program (ATAT) we don't ship, so instead of exploding it returns a clear "ATAT not
found" message. The other 22 tools keep working.

---

## What C2 had to add (and why)

C1 proved the hard part — a PyInstaller‑frozen backend that loads torch/MACE and
runs one real job. But it cheated on three things the plan flagged for C2:

1. **Models were symlinked in.** A real install can't ship hundreds of MB of
   checkpoints inside the installer, so they must be **downloaded on first run**.
2. **BYOK login/keys were only proven via curl**, not the actual GUI over `file://`.
3. **ATAT/SQS** bundling was undecided.

---

## 1. First‑run model download

### Backend — one registry, background downloads
- **`backend/app/services/model_manager.py`** (new) is the single source of truth
  for *where each checkpoint comes from*: name → calculator type, folder, filename,
  release URL, approx size, and whether it's in the trimmed **recommended** set
  (`mace-mp-0b3-medium` + `mattersim-v1.0.0-1M`).
- Downloads run in **daemon threads** with live, pollable progress held in memory.
  Each writes to a `*.part` file and renames on success, so a crash never leaves a
  half‑file that the factory's `_has_checkpoint` would treat as "present". A
  sub‑1 MB result is rejected as a likely HTML error page.
- It **reuses the calculator factory's path maps + `_has_checkpoint`**, so what we
  download is exactly what the simulations later load — no drift.
- The two operator CLI scripts (`download_mace.py`, `download_mattersim_5m.py`) are
  now **thin wrappers** over `model_manager.download_sync`, so the URLs live in one
  place only.

### Backend — API
- **`backend/app/api/models.py`** (new), mounted at `/api/models`:
  - `GET /api/models` → every model with `exists` + live `status/downloaded/total`.
  - `POST /api/models/download` → body `{models: "recommended" | "all" | [names]}`,
    starts background downloads, returns those queued (dedupes present/in‑flight).
- **Gated on `enable_heavy_tools`.** On the lite web edition (gate off) both routes
  return **404**, so the model UI never appears there. Verified: heavy ON → 200,
  heavy OFF → 404.

### Frontend
- **`frontend/src/api/models.js`** — `listModels()` / `downloadModels(selection)`.
- **`frontend/src/features/models/ModelSetup.jsx`** — a screen that lists every
  model with a type badge, "Recommended" pill, size, and a per‑model state:
  *Installed ✓* / live **progress bar** / *Download* / *Retry* on failure. It polls
  every 1.5 s only while something is downloading. Buttons: "Download recommended",
  per‑model, and "Download all remaining". "Continue / Skip for now" never blocks —
  chat works without any model.
- **First‑run gate (`App.jsx`):** when logged in **on desktop** (`isDesktop`) and
  `present === 0`, the screen pops once. Also re‑openable any time via a new
  **"Models"** item in the sidebar (desktop‑only).

**Verified end‑to‑end:** redirecting the model root to a temp dir and downloading
`mattersim-v1.0.0-1M` went `absent → downloading (13.6/17.9 MB) → present`, the
`.pth` landed at 17.9 MB, and no `.part` remained.

## 2. BYOK online LLM

- The existing **SettingsPanel** key flow (Gemini primary → Groq fallback over the
  internet) is the desktop chat brain unchanged — no local LLM is bundled.
- **Desktop blocker fixed:** `frontend/src/api/auth.js` hard‑coded `const API =
  '/api'` for its *unauthenticated* fetches (signup/login/config). Under the
  desktop's `file://` + dynamic localhost port that resolves to a broken
  `file:///api/...`. It now imports the resolved base (`apiBase`) from `client.js`,
  the same one the authenticated calls already use. `client.js` also exports
  `isDesktop` for the gate above. Web is unaffected (the global is undefined there).

## 3. ATAT / SQS decision — **defer bundling** (as recommended)

`generate_sqs` already degrades gracefully: `services/simulation/sqs.py` checks for
`corrdump/getclus/mcsqs` on PATH and, if missing, returns a clear "ATAT binaries
not found … SQS generation needs ATAT compiled into the image/host" message instead
of crashing. SQS is 1 of 23 tools and ATAT is external C++ (not pip‑installable),
so we ship without it for v1; the other 22 tools (incl. all 6 heavy MLP sims) work.

---

## Files touched (quick map)

| File | New? | What it does |
|------|------|--------------|
| `backend/app/services/model_manager.py` | new | model registry + threaded downloads + progress |
| `backend/app/api/models.py` | new | `/api/models` list + download, heavy‑tools gated |
| `backend/app/main.py` | edit | mount the models router |
| `backend/scripts/download_mace.py` | edit | thin wrapper over the shared registry |
| `backend/scripts/download_mattersim_5m.py` | edit | thin wrapper over the shared registry |
| `frontend/src/api/models.js` | new | `listModels` / `downloadModels` |
| `frontend/src/features/models/ModelSetup.jsx` | new | the first‑run download screen |
| `frontend/src/App.jsx` | edit | first‑run gate + render + sidebar wiring |
| `frontend/src/features/sessions/Sidebar.jsx` | edit | desktop‑only "Models" nav item |
| `frontend/src/api/client.js` | edit | export `apiBase` + `isDesktop` |
| `frontend/src/api/auth.js` | edit | use resolved base (fixes desktop login/keys) |
| `frontend/src/api/index.js` | edit | re‑export the models slice |

---

## Not yet (→ C3)
- electron‑builder cross‑OS installers (.AppImage/.dmg/.exe) + GitHub Actions matrix
  + electron‑updater, shipped unsigned.
- Release must install **CPU‑only torch** (the spike bundle carries CUDA torch).
