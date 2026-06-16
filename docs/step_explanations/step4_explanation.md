# Step 4 — Compute Caps & Quotas (Beginner Explanation)

> **Status:** ✅ Implemented & verified (param caps reject over-limit values; quota/atom/upload
> guards in place; full app imports clean).
> **This is the gate:** the 8 new simulation tools come only **after** this step.

---

## 1. One-sentence summary

We put **sensible limits** on how big and how many simulations a user can run, how large an upload
can be, and how fast requests can come — so a single user (or a fat-fingered number) can't melt the
small/free server.

---

## 2. The big analogy

Your Oracle free box is a **small kitchen with one stove**. Without limits, a well-meaning student
could order *"simulate 1,000,000 steps on a 5,000-atom crystal"* — like ordering 10,000 pizzas and
jamming the only oven for everyone. Step 4 is the **menu with portion limits**: a max order size, a
few orders per person at a time, and a cap on how much you can drop in the pantry (disk).

For your **trusted lab**, these are deliberately *generous* (not adversarial) — just enough to stop
**accidents** from taking the server down.

---

## 3. The limits we added (all env-overridable)

| Limit | Default | What it stops | Env var |
|---|---|---|---|
| Max optimization steps | 5,000 | A runaway geometry relaxation | `MAX_OPT_STEPS` |
| Max MD steps (`nsw`) | 50,000 | A runaway molecular-dynamics run | `MAX_MD_STEPS` |
| Max atoms | 512 | A huge structure that OOMs the box | `MAX_ATOMS` |
| Active jobs per user | 3 | Job spam (queueing dozens at once) | `MAX_ACTIVE_JOBS_PER_USER` |
| Upload size per file | 25 MB | Filling the disk via uploads | `MAX_UPLOAD_MB` |
| Chat / upload rate | 30/min | Request floods | (slowapi) |

A bigger deployment just raises these via environment variables — no code change.

---

## 4. File-by-file: what changed & why

### 📄 `backend/app/core/config.py` — "the rulebook"
Added the six limits as settings (read from env, with safe defaults). One place to tune them.

### 📄 `backend/app/tools/contracts.py` — "the order form"
The tool schema now advertises the ceilings (`max_steps ≤ 5000`, `nsw ≤ 50000`). So when the AI
agent fills out an order, an over-limit value is **rejected up front** with a clear validation error
(the agent then retries with a sane value).

### 📄 `backend/app/tools/material_tools.py` — "the kitchen checks"
Three guards where jobs are actually started:
- **Clamp** `max_steps`/`nsw` to the ceiling (belt-and-suspenders with the contract).
- **`_enforce_atom_cap()`** — reads the structure and refuses anything above the atom limit, *before*
  queuing, with a friendly message.
- **Per-user job quota** in `_enqueue_job()` — if you already have 3 jobs running/queued, it asks you
  to wait instead of piling on.

### 📄 `backend/app/jobs/store.py` — "the order counter"
New `count_active_for_user()` — counts your queued+running jobs (used by the quota check above).

### 📄 `backend/app/api/upload.py` — "the loading dock"
- Rejects any file larger than the size limit (25 MB).
- Rate-limited to 30 uploads/min.

### 📄 `backend/app/api/chat.py` — "the front counter"
- Rate-limited to 30 messages/min. (Renamed the request body to `body` so the rate-limiter can read
  the real HTTP request — a small, mechanical rename.)

---

## 5. Why this is the gate before new tools

Your 8 upcoming tools are **heavier** and each spawns *many* sub-calculations:
- **NEB** runs many images, **phonons** run many displaced structures, **SQS** searches many
  configurations.

Add them *before* these caps and the **first curious click** could launch something that takes the
shared server down for the whole lab. With caps in place, each new tool inherits the guardrails
automatically. **Caps first, tools second.**

---

## 6. What we verified

| Check | Result |
|---|---|
| `max_steps` / `nsw` over the cap | ✅ rejected by the contract |
| within-cap values | ✅ accepted |
| atom-cap helper present & wired | ✅ |
| per-user job counter present | ✅ |
| upload size + rate limits | ✅ in place |
| full app imports (routes + limiter) | ✅ |

---

## 7. Intentionally deferred (small follow-ups)

- **Per-session disk quota + old-artifact cleanup (TTL).** The capped `nsw` × capped atoms already
  bounds trajectory file sizes, so this is lower-risk; worth adding before fully opening up.
- Tuning the exact numbers once you see real lab usage.

---

## 8. Where this fits

**Step 4 of 10 — the compute gate.** Done means the server is protected. Next is **Step 5
(invite-only access)**, then the foundation is ready and we can start adding your **8 new simulation
tools, one at a time**, each landing on a capped, tested, hardened base.

**Commit:** `limit: cap simulation params/atoms, per-user job quota, upload size + chat/upload rate limits`
