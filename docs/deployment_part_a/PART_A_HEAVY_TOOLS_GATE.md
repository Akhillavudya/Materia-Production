# Deployment — Part A: The Heavy‑Tools Gate

**Status:** ✅ DONE — 2026‑06‑26
**Scope:** the shared `ENABLE_HEAVY_TOOLS` switch that lets the **same codebase**
run as a light web app *or* a full desktop app.
**Parent plan:** `docs/DEPLOYMENT_AND_DESKTOP_ROADMAP.md` (§2, Part A)

---

## 1. Why this exists (the one‑paragraph version)

Materia has 23 tools. Most are **instant** (search a database, write VASP input
files, build a slab, make a defect) — they finish in well under a second and use
almost no resources. But **6 of them are "heavy" simulations** (optimize, MD,
elastic, phonons, NEB, SQS). Those load **PyTorch + a machine‑learned potential
(MACE / MatterSim)** and grind for minutes on CPU/GPU.

We want to host the web app on a **free Oracle Cloud server (4 CPU, no GPU, ~$0
budget)**. If a single user clicked "Run molecular dynamics" there, it could peg
that shared server for everyone. So the plan is:

| Surface | Heavy tools | Where compute runs |
|---------|-------------|--------------------|
| **Web** (Oracle) | **disabled** | n/a — points users to desktop |
| **Desktop** (Electron, later) | **enabled** | the user's *own* CPU/GPU |

Part A builds the **switch** that makes this split possible. Parts B (deploy web)
and C (build desktop) come after.

> **Design decision (important).** The heavy tools are **NOT hidden or removed**
> on the web. Every tool stays **visible**. We only block the *execution*: when a
> user (or the AI) tries to actually run a heavy simulation, they get a friendly
> message telling them to install the desktop app. "Show everything, gate the
> click" — so web users can see the full capability and know exactly what the
> desktop app unlocks.

---

## 2. The switch

A single environment variable:

```
ENABLE_HEAVY_TOOLS=true    # default (dev + desktop) — heavy tools run
ENABLE_HEAVY_TOOLS=false   # web edition — heavy tools are gated
```

- Defaults to **ON**, so local development and the future desktop app "just work"
  with no extra config.
- The web deployment (Part B) will set it to `false`.

---

## 3. Defence in depth — 4 layers

The golden rule for a safety gate: **don't trust a single check.** A job could be
started three different ways — by the AI agent in chat, by a button in the manual
tools panel, or by someone calling the HTTP API directly. So the gate is enforced
at **4 independent layers**. Even if a future edit accidentally breaks one, the
others still hold.

```
            ┌─────────────────────────────────────────────────┐
            │  Layer 1 — CONFIG: read ENABLE_HEAVY_TOOLS       │
            └─────────────────────────────────────────────────┘
                                  │ settings.enable_heavy_tools
        ┌─────────────────────────┼─────────────────────────────┐
        ▼                         ▼                             ▼
 ┌──────────────┐        ┌─────────────────┐          ┌──────────────────┐
 │ Layer 3 — AI │        │ Layer 4 —       │          │ (direct API call)│
 │ system note  │        │ FRONTEND badge  │          │                  │
 │ (graph.py)   │        │ + Run lock      │          │                  │
 └──────┬───────┘        └────────┬────────┘          └────────┬─────────┘
        │ agent calls tool        │ button posts            │ POST /sessions/.../optimize
        ▼                         ▼                          ▼
            ┌─────────────────────────────────────────────────┐
            │  Layer 2 — BACKSTOP: _enqueue_job() refuses      │  ← the real guarantee
            │  every job when the switch is off                │
            └─────────────────────────────────────────────────┘
```

Layers 3 and 4 are **UX niceties** (they make the experience clean). Layer 2 is
the **actual security guarantee** — nothing can start a heavy job without going
through it.

---

### Layer 1 — Config flag
**File:** `backend/app/core/config.py`

- New helper `_env_bool(name, default)` parses `1/true/yes/on` (any case); an
  unset variable falls back to the default.
- New setting `enable_heavy_tools: bool = True`, populated from
  `ENABLE_HEAVY_TOOLS` in `get_settings()`.

This is the single source of truth that the other three layers read via
`settings.enable_heavy_tools`.

---

### Layer 2 — Backstop (the real gate)
**File:** `backend/app/tools/material_tools.py`, function `_enqueue_job()`

**Why here?** *Every* heavy tool — no matter who triggers it — funnels through
this one function to create and dispatch a job. The agent path, the manual‑panel
path, and the direct‑API path **all** call it. Guard this one spot and you guard
them all.

When `enable_heavy_tools` is `false`, `_enqueue_job()` returns **before** creating
any job:

```python
return {
    "status": "error",
    "message": "“optimize” is a long-running simulation that runs on the machine,
                not in the web app. To run it, install the Materia desktop app …",
}
```

**Why `status: "error"` specifically (not a new status like "unavailable")?**
The manual‑launch endpoints in `api/upload.py` already have a helper
(`_run_tool_launch`) that turns an `"error"` envelope into an **HTTP 400** — which
the frontend's existing `catch` block already displays. By reusing `"error"` we
plug straight into machinery that already exists, so the message reaches the user
on every path with zero extra code. (Using a brand‑new status would have silently
slipped through as a fake "success".)

---

### Layer 3 — AI system note
**File:** `backend/app/agent/graph.py`

The heavy tools stay **fully declared** to the language model (we did **not**
filter `TOOL_SPECS`). That keeps the model aware of the capability — and keeps the
import‑time "drift guard" happy (it checks that every declared tool is also
executable).

Instead, when the switch is off we **append `HEAVY_DISABLED_NOTE` to the system
prompt**. It tells the agent: *these simulations don't run on this server — point
the user to the desktop app instead of pretending a job started.* So the AI gives
a helpful answer ("you'll need the desktop app for that; meanwhile I can still
search, build structures, generate VASP inputs…") rather than fabricating a fake
job id or dumping a raw error.

If the model ignores the note and calls the tool anyway, **Layer 2 still refuses
it.** The note just makes the conversation graceful.

---

### Layer 4 — Frontend signal
**Files:** `backend/app/api/auth.py`, `frontend/src/api/auth.js`,
`frontend/src/features/sessions/toolForms.js`,
`frontend/src/features/sessions/ToolLaunchPanel.jsx`

1. `GET /auth/config` now returns `heavy_tools_enabled` (a public, non‑secret
   hint), alongside the existing signup/Google fields.
2. The frontend fetches it (`getAuthConfig`). The fallback default is `true`, so a
   failed/slow network call never *wrongly* locks the tools.
3. In `toolForms.js`, the 6 heavy cards are tagged `heavy: true`
   (optimize / md / phonons / elastic / sqs / neb).
4. In `ToolLaunchPanel.jsx`, when `heavy_tools_enabled` is false a heavy card:
   - **stays visible** with a small **"Desktop app"** badge in its header,
   - its **Run** button reads **"Available in desktop app"**, and
   - clicking it shows the desktop‑install message **instead of launching**
     (a short‑circuit *before* any network call — clean UX, no scary red error).

---

## 4. What about `add_adsorbate`?

`add_adsorbate` is a **hybrid**:

- **Default (instant):** it places the molecule geometrically — fast, no torch.
  This **stays usable on the web.**
- **`relax=true` (heavy):** it runs an ML‑potential relaxation to find the lowest
  adsorption energy — that path enqueues a job.

So `add_adsorbate` is **deliberately NOT tagged `heavy`** in the frontend (its
instant mode is useful). Its heavy `relax=true` path is still safe because it goes
through **Layer 2** — `_enqueue_job()` refuses it on the web with the same
desktop‑install message. One backstop covers the edge case for free.

---

## 5. Files changed

| File | Layer | Change |
|------|-------|--------|
| `backend/app/core/config.py` | 1 | `_env_bool()` helper + `enable_heavy_tools` setting |
| `backend/app/tools/material_tools.py` | 2 | `_enqueue_job()` refuses heavy jobs when off |
| `backend/app/agent/graph.py` | 3 | `HEAVY_DISABLED_NOTE` appended to system prompt when off |
| `backend/app/api/auth.py` | 4 | `/auth/config` returns `heavy_tools_enabled` |
| `frontend/src/api/auth.js` | 4 | config fallback includes `heavy_tools_enabled: true` |
| `frontend/src/features/sessions/toolForms.js` | 4 | `heavy: true` on the 6 heavy cards |
| `frontend/src/features/sessions/ToolLaunchPanel.jsx` | 4 | badge + Run lock + desktop message |
| `backend/tests/unit/test_heavy_tools_gate.py` | — | 3 new regression tests |

---

## 6. How it was verified

- **Unit tests** — `tests/unit/test_heavy_tools_gate.py` pins the gate:
  - `_env_bool` parsing,
  - off ⇒ `_enqueue_job` returns `status:"error"`, no `job_id`, "desktop" in the
    message,
  - on ⇒ the gate is passed (no desktop message).
  Full backend unit net: **25/25 pass** (the prior 22 + these 3).
- **Live import check** — with `ENABLE_HEAVY_TOOLS=false`, the agent module
  imports cleanly (drift guard intact) and `_enqueue_job` refuses a sample
  `OPTIMIZE` job with the desktop message and no job id.
- **Frontend** — `vite build` completes clean.

### How to reproduce locally
```bash
# Backend tests (uses the project venv; SQLite + inline jobs)
cd backend
env DATABASE_URL= JOB_BACKEND=inline ../venv/bin/python -m pytest tests/unit -q

# See the web behaviour by hand
ENABLE_HEAVY_TOOLS=false ...run the backend...   # heavy tools refuse + UI shows badge
ENABLE_HEAVY_TOOLS=true  ...run the backend...    # everything runs (default)
```

---

## 7. The beginner takeaway

> **One switch, four locks.** A free server can't be trusted to run heavy physics
> simulations, so we added a single env flag and enforced it in four places — the
> real lock being the one spot (`_enqueue_job`) that *every* job must pass through.
> The clever part isn't the lock itself; it's **reusing the existing
> `"error"` → HTTP 400 → frontend‑catch plumbing** so one tiny change lights up the
> right message on every path, and **keeping the tools visible** so web users see
> the full product and know what the desktop app adds.

**Next:** Part B — build `docker-compose.web.yml` (drop worker + redis), set
`ENABLE_HEAVY_TOOLS=false`, mount POTCAR, and deploy to Oracle.
