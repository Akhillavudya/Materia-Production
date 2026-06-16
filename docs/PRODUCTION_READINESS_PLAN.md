# Materia — Production Readiness Plan

> **Status:** Planning / not yet implemented. Nothing here has been built. Each step is
> implemented **only when you say so**, one at a time.
>
> This document explains, for every step: *what* we do, *why* we do it **before** adding the
> next batch of simulation tools, the *purpose* — with a plain-language **analogy** — and a
> beginner-friendly list of **which files change and why**.

---

## The mental model

Right now Materia is **a brilliant workshop you built in your garage**. The tools work, the
machines run, the science is real. "Going to production" does **not** mean adding more
machines — it means turning the garage into **a proper keycard lab that only your people can
enter**, without breaking your equipment, exposing each other's belongings, or getting hurt.

You are about to install **8 new power tools**:

1. K-points accuracy
2. POSCAR vacancy defects
3. POSCAR substitution defects
4. POSCAR interstitial defects
5. Phonopy (phonons)
6. Mechanical properties
7. SQS generation
8. NEB calculations

**The core principle:** *Do not bolt new power tools onto a shop that has no locks, no fire
exits, and one overloaded stove.* Every new tool is also a new way to overload the server or
trip over a missing safety rail. So we **harden the shop first**, then add the tools onto a
solid foundation.

---

## Your launch model — PRIVATE, lab-only (paper in progress)

- **NOT public.** A paper is being published on this work, so the app and its code stay private.
- **Private code & images** — the GitHub repo stays private; Docker images are **not** published
  to any public registry (built on the server or pushed to a private one).
- **Invite-only access** — open signup is **off**. Only your PhD lab students get accounts (via
  admin-created accounts or invite codes). A stranger who finds the URL cannot get in.
- **Optional front-door password** — a single shared password (or campus VPN/IP allowlist) at the
  proxy so the public can't even *see* Materia exists.
- **BYOK ("Bring Your Own Key")** — each student pastes their own Groq/Gemini API key; you don't
  pay for everyone's AI usage.
- **Desktop app planned** — heavy simulations will eventually run on each user's own CPU/GPU.
  Until then, simulations run on your server.
- **Tentative host: Oracle Cloud "Always Free" Ampere A1** — ARM64, 4 CPU / 24 GB RAM,
  **no free GPU**. Budget ≈ zero.

> **Why "private lab-only" makes this easier:** your students are *trusted*, so we drop all the
> anti-bot / anti-stranger machinery (Step 5 becomes a simple allowlist) and keep only *light*
> guardrails so nobody **accidentally** overloads the shared server (Step 4).

> **One correction up front:** your `backend/.env` is **not** in git and never was — it's
> correctly ignored. There is **no leaked-secret emergency**. The real concern is that secrets are
> *weak* and that users' pasted keys are currently stored **unencrypted** (see Step 1).

---

# The 10 steps

Each step answers: **Purpose · Analogy · Why before the new tools · 📁 Files that change & why.**

---

## 🔴 P0 — Locks on the doors (before any student logs in)

### Step 1 — Secrets & "Bring Your Own Key" encryption
**Purpose:** Use a strong random master secret for logins, and **encrypt** every API key a user
pastes so it's never stored as plain readable text. Refuse to start if the safe is unlocked.

**Analogy:** Today the master key is the word *"key"* on a sticky note
(`JWT_SECRET_KEY = my-super-secret-key`) — anyone guessing it can impersonate any user. And when a
student hands you *their* valuable key, you drop it in an **unlocked drawer** instead of a safe,
because the safe's combination (`FIELD_ENCRYPTION_KEY`) was never set.

**Why before the new tools:** Every tool runs through the agent using the student's key. More
tools = those keys used more often. Secure how they're *stored* before you multiply how often
they're *used*.

**📁 Files that change & why:**
- `backend/app/core/config.py` — the app's "settings sheet." We add an `ENV=production` switch and
  make the app **refuse to boot** if the master secret or encryption key is weak/missing.
- `backend/app/core/encryption.py` — the "safe." Today it silently stores keys as plain text when
  the combination is missing; we make it **lock or stop**, never fall back to plain text in prod.
- `backend/app/core/security.py` — signs login tokens; it just *reads* the strong new secret.
- `backend/app/services/key_service.py` — loads a user's key and decrypts it; verifies it works
  with the safe turned on.
- `backend/.env.example` — the documented template listing the new required secrets (the real
  `.env` stays out of git).

---

### Step 2 — Containerize & deploy (Docker on Oracle, automatic HTTPS)
**Purpose:** Package the whole app into a portable container, put it behind a front-door proxy
that gives HTTPS (the 🔒) for free, and make the frontend talk to your real server instead of
`localhost`.

**Analogy:** Today the shop runs only on *your* workbench, set up *your* way. Docker puts the whole
shop — machines, wiring, plumbing — into a **shipping container** you drop onto the Oracle VM and it
just works. **Caddy** (the proxy) is the **front door with a guard** that also hands you HTTPS
automatically — and it's where the optional lab-only password lives.

**Why before the new tools:** You want to test each new tool in the *real* environment, not just
your laptop. Build the container now so every future tool is verified where students actually use it.

**📁 Files that change & why (mostly new files):**
- `backend/Dockerfile` *(new)* — the recipe that packs the backend into a container, built for
  Oracle's **ARM64** chip.
- `docker-compose.yml` *(new)* — the "one button" that starts all the pieces together: web API,
  simulation worker, database, Redis, and the Caddy front door.
- `Caddyfile` *(new)* — the front-door config: HTTPS + (optional) lab-only password + sends `/api`
  to the backend and everything else to the frontend.
- `scripts/fetch_models.sh` *(new)* — downloads the big AI model files (398 MB) separately instead
  of stuffing them in the container.
- `frontend/vite.config.js` + `frontend/src/api/client.js` — today the frontend has your home
  address (`localhost`) hardcoded; we change it to a **label it can swap** so production points at
  the Oracle server.

---

### Step 3 — Real database (PostgreSQL), no silent fallback
**Purpose:** Use Postgres in production and **stop the app from silently falling back to SQLite**.

**Analogy:** SQLite is a **single paper notebook** — fine for one writer. Production has two workers
(web API *and* simulation worker) scribbling at once → smudges, lost data. Postgres is a **filing
system with a librarian** who coordinates many writers safely. The hidden danger: forget to plug in
Postgres and the app *quietly* uses the paper notebook. We make it **shout and stop** instead.

**Why before the new tools:** Each new tool writes job records to the database. More tools = more
concurrent writes. Fix the foundation before piling weight on it.

**📁 Files that change & why:**
- `backend/app/core/config.py` — require a real `DATABASE_URL` when in production; no quiet SQLite
  fallback.
- `backend/app/database/db.py` — the database connection; we add **"keep-alive" settings**
  (`pool_pre_ping`, `pool_recycle`) so connections don't go stale and crash.
- The existing Alembic migration runs automatically on deploy (no new file; wired into
  `docker-compose.yml` from Step 2).

---

### Step 4 — Light guardrails so nobody *accidentally* overloads the server ⚠️
**Purpose:** Cap how big and how many simulations one person can run at once, limit file sizes, and
auto-clean old results — sized for a trusted lab, not hostile strangers.

**Analogy:** Your Oracle free machine is a **small kitchen with one stove**. A well-meaning student
might fat-finger *"1,000,000 steps on a 5,000-atom crystal"* — like accidentally ordering 10,000
pizzas and jamming the only oven for everyone. Light guardrails are a **sensible menu**: a max order
size, a couple of orders per person at a time, and tidy-up of old leftovers (disk).

**Why before the new tools — this is the critical one:** Every new tool (phonons, NEB, SQS…) is
*heavier* and spawns *many* sub-calculations: NEB runs many images, phonons run many displaced
structures, SQS searches many configurations. Add them *before* caps exist and one accidental click
takes the shared server down for the whole lab. **Caps first, tools second.**

**📁 Files that change & why:**
- `backend/app/tools/contracts.py` — the "order form" for each tool. We add **sane maximums**
  (max steps, max MD steps, max atoms) so an impossible order is rejected *before* it reaches the
  stove.
- `backend/app/tools/material_tools.py` — where jobs get queued; we add a **"you already have N jobs
  running" check** per user.
- `backend/app/api/chat.py` + `backend/app/api/upload.py` — add gentle rate limits and a **file-size
  cap** (and stream uploads to disk instead of loading the whole file into memory).
- `backend/app/services/storage/file_service.py` — add a **per-user storage budget** and
  **auto-cleanup** of old job files so the disk never silently fills up.

---

### Step 5 — Invite-only access (lab members only)
**Purpose:** Turn **off** open signup so only your PhD students can get in — via admin-created
accounts or invite codes.

**Analogy:** Instead of a shop with an open door, it's a **keycard office**. No keycard, no entry —
a stranger who finds the address simply can't make an account. (This *replaces* the public version's
email-verification/anti-bot machinery, which you don't need for a trusted lab.)

**Why before the new tools:** You want the lab gate in place before exposing any tools, new or old —
so the audience is always exactly "your people."

**📁 Files that change & why:**
- `backend/app/api/auth.py` — the signup/login door. We **disable open signup** and accept only an
  **invite code** (or admin-created accounts) instead.
- `backend/app/core/config.py` — holds the allowlist/invite settings (e.g. allowed email domain or
  the invite code).
- `Caddyfile` *(optional, from Step 2)* — adds the single shared **front-door password** so the
  public can't even see the login page.

---

## 🟡 P1 — Safety rails (before the lab relies on it daily)

### Step 6 — Global error handling (don't leak your internals)
**Purpose:** On a crash, show a clean "something went wrong" to the user while real technical
details go only to your private logs.

**Analogy:** Today a jammed machine sometimes **prints its whole internal blueprint** onto the
customer's receipt (raw errors with file paths) — confusing *and* a security leak.

**Why before the new tools:** New, complex tools fail in new, complex ways. Capture failures cleanly
and privately *before* adding eight more sources of them.

**📁 Files that change & why:**
- `backend/app/main.py` — the app's "front desk." We add **one catch-all handler** that turns any
  unexpected crash into a tidy, generic message, and we hide the auto-generated `/docs` page in
  production.
- `backend/app/api/chat.py` — one spot currently echoes a raw error (with file paths) to the user;
  we replace it with a safe message.
- `backend/app/core/logging.py` — make logs structured and add a request ID so you can trace what
  actually happened in private.

---

### Step 7 — Health checks & knowing when it's down
**Purpose:** Add a heartbeat endpoint so a free uptime monitor alerts you the moment the server
dies, plus basic error reporting.

**Analogy:** Right now there's **no smoke detector** — you'd learn about a 3 a.m. fire from an angry
student. `/health` is a heartbeat a monitor pings every minute and texts you when it flatlines.

**Why before the new tools:** Heavier tools make crashes more likely; you need to hear it from a
monitor, not a frustrated student.

**📁 Files that change & why:**
- `backend/app/api/health.py` *(new)* — two tiny endpoints: `/health` (am I alive?) and `/ready`
  (can I reach the database and Redis?).
- `backend/app/main.py` — registers those endpoints; optionally wires in **Sentry** (free tier) to
  record what broke.

---

### Step 8 — Lock down CORS & add security headers
**Purpose:** Allow only *your* website to talk to the backend (today it allows *any* site), and add
standard browser-safety headers.

**Analogy:** CORS today says *"any website on Earth may use my cash register."* We narrow it to
*"only my own website."* Security headers are the **"fire exit / no smoking" signs** every legit
shop posts.

**Why before the new tools:** A one-time front-door hardening — do it once now and every future tool
inherits the protection.

**📁 Files that change & why:**
- `backend/app/main.py` — tighten the CORS rule to your domain only, and add a small **security-
  headers** layer (HSTS, etc.).
- `Caddyfile` *(from Step 2)* — enforces HTTPS at the front door so these headers actually matter.

---

## 🟢 P2 — Do alongside / right before the new tools land

### Step 9 — A minimum test net + automated checks (CI)
**Purpose:** Write a small set of automated tests for the critical paths and have a robot run them
on every change.

**Analogy:** You're about to install **8 new power tools, one by one**. Without tests, adding one is
like **renovating with the lights off** — you won't notice you broke the plumbing until water's on
the floor. Tests are **tripwires** that beep the instant something that used to work breaks. CI is
the robot inspector that trips those wires automatically before the change reaches the lab.

**Why before the new tools — huge for you:** Each new tool risks silently breaking an existing one.
A test net means: add a tool → run tests → if something old broke, you know in seconds. This is what
makes adding 8 tools *safe* instead of *scary*.

**📁 Files that change & why (mostly new):**
- `backend/tests/` *(new)* — small tests for: login works, the new size-caps reject bad orders, file
  paths can't escape a user's folder, and a key encrypts/decrypts correctly.
- `frontend/src/**/*.test.js` *(new)* — a couple of tests for login/token handling.
- `.github/workflows/ci.yml` *(new)* — the robot inspector: runs the tests + linters on every change.
- `backend/pyproject.toml` *(new/updated)* — config for `ruff`, a fast Python style checker.

---

### Step 10 — Backups, model files, and a deploy runbook
**Purpose:** Back up the database nightly, fetch the large AI model files with a script, and write
down how to deploy.

**Analogy:** Your one free VM is a **single hard drive holding your life's work** — if it dies,
everything's gone. Backups are **photocopies in another building**. The 398 MB models are too heavy
for the toolbox, so a **"go fetch them" script** brings them in. The runbook is the **instruction
manual** so future-you can rebuild from scratch.

**Why before the new tools:** Some new tools may need extra model files or data. Establish the
"fetch out-of-band" pattern now so each new tool just plugs into a documented system.

**📁 Files that change & why (mostly new):**
- `scripts/backup.sh` *(new)* — a nightly job that copies the database to a safe second location
  (Oracle Object Storage free tier or a second disk).
- `scripts/fetch_models.sh` *(from Step 2)* — reused to pull model files on a fresh server.
- `docs/DEPLOY.md` *(new)* — the step-by-step rebuild manual.
- `README.md` — expand from one line into real setup instructions.

---

# The big-picture payoff: your desktop-app pivot 🎯

Once the desktop app runs simulations on each user's own machine, **Step 4's "one stove" problem
mostly disappears** — every student brings their own kitchen. Your Oracle server shrinks to a
**front desk**: logins, chat orchestration, light storage — nearly free to run forever. So this plan
does double duty: it makes the *private lab* deployment safe **and** builds the lean front desk the
desktop future depends on.

---

# Suggested order of work

```
Step 1  →  Step 3  →  Step 2  →  Step 4  →  Step 5     (P0: locks, guardrails, lab-only gate)
Step 6  →  Step 7  →  Step 8                            (P1: safety rails)
Step 9  →  Step 10                                      (P2: test net & backups)
─────────────────────────────────────────────────────
THEN: add the 8 new simulation tools, one by one,
      each landing on a hardened, tested, lab-only foundation.
```

**The single most important rule:** do **not** add the new simulation tools until **Step 4
(size caps)** is in place — otherwise each heavier tool becomes a new way for one accidental click
to take down the shared lab server.

> **Implementation rule for this project:** each step is built **only when you ask**, as one small,
> independently verifiable change. Before any commit, the exact git commands are shown to you first,
> and no AI attribution is added to commit messages (per `CLAUDE.md`).
