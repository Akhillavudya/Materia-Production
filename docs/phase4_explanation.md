# Phase 4 — The Async Job System, Explained for Beginners

This document explains **every file** added or changed in Phase 4, what it does,
why it exists, and how it all fits together. It assumes you have **never used
Redis or Celery** before. We will build up the ideas with a single running
analogy: **a restaurant**.

---

## 1. The problem we are solving (read this first)

Before Phase 4, when you asked Materia to "relax this structure", the calculation
ran **inside the web request**. Imagine ordering food at a restaurant and the
**waiter walks into the kitchen and cooks your meal himself** while you — and
everyone else — wait. The waiter can't take any other orders for 20 minutes. If
he trips, your food is gone and there's no record you ordered.

That is exactly what was wrong:

- A 10,000-step molecular-dynamics run held the web connection open for minutes
  to hours.
- The same process that cooks (runs the simulation) also serves chat — so one
  big job freezes everything.
- If the server restarts, the job vanishes. No progress, no cancel, no history.

**The fix (Phase 4):** separate the people who *take orders* from the people who
*cook*. The waiter takes your order, writes it on a ticket, and **immediately**
goes back to serving. A separate cook picks up the ticket and cooks. You get a
buzzer that tells you when your food is ready.

Mapping the analogy to real components:

| Restaurant thing      | Real component                         | What it is |
|-----------------------|----------------------------------------|------------|
| Waiter                | **FastAPI web app** (`uvicorn`)        | Takes requests, never cooks |
| Order ticket          | A **row in the `jobs` database table** | The single source of truth |
| Ticket rail / spike   | **Redis** (the message broker)         | Holds "tickets to cook" |
| Cook                  | **Celery worker** (separate process)   | Picks up tickets and cooks |
| The recipe            | **The simulation services** (ASE/MACE) | The actual science code |
| Buzzer that lights up  | **Progress updates + SSE stream**      | Tells the browser what's happening |

Two new words you now understand:

- **Redis** = a very fast in-memory notebook. We use it as the **ticket rail**:
  the waiter pins a ticket ("cook job #123") and the cook grabs it. Redis is also
  used to broadcast live progress ("step 50 of 100").
- **Celery** = the system that runs **background workers** (the cooks). It knows
  how to read tickets off the Redis rail and call the right Python function.

> Important rule we follow everywhere: **the database is the source of truth, not
> Redis.** Redis just carries the short message "go cook #123". Everything we
> actually care about (status, progress, results) is written to the `jobs` table,
> so a restart never loses anything.

---

## 2. The big picture flow (one diagram)

```
   Browser                Web app (waiter)          Redis (rail)      Worker (cook)         Database (tickets)
      │  "relax MoS2"          │                          │                 │                      │
      ├───────POST /chat──────►│                          │                 │                      │
      │                        │ tool: optimize_structure │                 │                      │
      │                        ├─ create job row ─────────┼─────────────────┼──────────────────────► (status=queued)
      │                        ├─ enqueue "cook #123" ────►│                 │                      │
      │◄──"job #123 queued"────┤                          │                 │                      │
      │                        │                          │  "cook #123" ───►│                      │
      │                        │                          │                 ├─ mark running ───────► (status=running)
      │                        │                          │                 ├─ run simulation       │
      │                        │                          │◄─ progress ──────┤ (writes every step) ─► (progress=...)
      │  GET /jobs/123/stream  │                          │                 │                      │
      ├───────(SSE)───────────►│ reads job row every 1s ──┼─────────────────┼──────────────────────► (reads status/progress)
      │◄── step 50/100 ────────┤                          │                 │                      │
      │◄── step 100/100 ───────┤                          │                 ├─ write results ──────► (status=succeeded)
      │◄── done + files ───────┤                          │                 │                      │
```

Keep this picture in mind while reading the file-by-file section below.

---

## 3. File-by-file walkthrough

Files are grouped by the layer they live in. For each: **what it is**, **why it
exists**, and **its role in the flow**.

### 3.1 Configuration & dependencies

#### `backend/app/core/config.py` (changed)
- **What:** the app's settings, read from environment variables.
- **Why:** the job system needs to know *where Postgres is*, *where Redis is*,
  and *which backend to use*. We added `DATABASE_URL`, `REDIS_URL`, `JOB_BACKEND`,
  and `MAX_JOB_WALLCLOCK_S`.
- **Analogy:** the restaurant's address book — "the ticket rail is at this phone
  number (Redis), the filing cabinet is here (Postgres)."
- **Key detail:** it exposes **two** database URLs:
  - `database_url` (async, `asyncpg`) — used by the web app.
  - `database_url_sync` (sync, `psycopg2`) — used by the worker.
  Why two? See §4. If `DATABASE_URL` is not set, it quietly falls back to a local
  **SQLite** file so the app still runs on your laptop without Postgres.

#### `backend/requirements.txt` (changed)
- **What:** the list of Python packages.
- **Why:** we now need `celery[redis]` (the cook system), `redis` (the client to
  talk to the rail), `asyncpg` + `psycopg2-binary` (Postgres drivers), and
  `alembic` (database migrations).

---

### 3.2 The vocabulary (domain models)

#### `backend/app/domain/jobs.py` (new)
- **What:** plain data definitions — `JobType` (optimize | md), `JobStatus`
  (queued → running → succeeded/failed/cancelled), `JobSpec` (what to run),
  `JobProgress`, `JobRecord` (what the API returns), and a `JobCancelled`
  exception.
- **Why:** so every part of the system speaks the **same language**. Instead of
  loose dictionaries with typo-prone keys, these are validated shapes.
- **Analogy:** the **standard order form**. Every ticket has the same fields
  (table number, dish, notes) so the cook never has to guess.
- **The one clever bit — `JobCancelled`:** this is an exception the cook "raises"
  to itself to stop early when you press Cancel. It lets the science code stop
  cleanly *without* the science code needing to know anything about jobs/Redis.

---

### 3.3 The database (the filing cabinet)

#### `backend/app/database/models.py` (changed — added `Job`)
- **What:** the `Job` table definition: `id`, `user_id`, `session_id`, `type`,
  `status`, `spec`, `progress`, `result`, `artifacts`, `error`, `spec_hash`,
  timestamps.
- **Why:** this table **is the source of truth**. Every order, its progress, and
  its result live here permanently.
- **Analogy:** the filing cabinet of order tickets. Even if the kitchen burns
  down and restarts, the tickets survive.
- **Key detail — `JSONType`:** columns like `spec`/`progress`/`result` store JSON.
  On PostgreSQL they become `JSONB` (fast, indexable); on SQLite they're plain
  JSON. One line of code, both databases supported.

#### `backend/app/repositories/job_repository.py` (new)
- **What:** the **async** functions the web app uses to talk to the `jobs` table:
  `create`, `get_owned`, `list_for_user`, `request_cancel`, `find_active_duplicate`.
- **Why:** we keep all SQL in one place (the "repository" pattern). Routes and
  tools never write raw SQL.
- **Analogy:** the **front-desk clerk** who files and retrieves tickets for the
  waiter. Note: "owned" everywhere means *a user can only see their own jobs*.

#### `backend/app/jobs/store.py` (new)
- **What:** the **sync** version of the same idea, but for the **worker**:
  `create_job`, `load_job`, `mark_running`, `update_progress`, `get_status`,
  `mark_succeeded`, `mark_failed`, `mark_cancelled`.
- **Why does a second one exist?** The cook (Celery worker) is a **synchronous**
  program; it cannot use the web app's async database connection. So it has its
  own small, plain (sync) connection to the same filing cabinet.
- **Analogy:** the clerk uses a computer (async); the cook in the back uses a
  paper logbook (sync). Both write to the *same* cabinet, just with different
  pens.

#### Alembic — `backend/alembic.ini` + `backend/app/database/migrations/` (new)
- **What:** **database migrations** — versioned scripts that build/upgrade the
  database schema. The first one (`..._initial_schema_with_jobs.py`) creates all
  tables including `jobs`.
- **Why:** in production you don't let the app "just create tables"; you run
  controlled, reviewable upgrades. Alembic is the standard tool for this.
- **Analogy:** **renovation permits** for the building. Instead of knocking down
  walls on a whim, each change is a numbered, approved plan you can apply or roll
  back.
- **How you use it:** `alembic upgrade head` brings any database up to the latest
  schema.

---

### 3.4 The job engine (the `jobs/` package — the heart of Phase 4)

#### `backend/app/jobs/queue.py` (new)
- **What:** creates the **Celery app** (pointed at Redis) and gives us one helper:
  `enqueue(job_type, job_id)`.
- **Why:** this is the **ticket rail**. The web app calls `enqueue(...)` which
  pins a tiny message — *"run task `jobs.optimize` for id 123"* — onto Redis.
- **Important design choice:** the web app sends the task **by name** ("jobs.optimize")
  and does **not** import the heavy science code. The waiter writes "Dish #7" on
  the ticket; he doesn't need to know the recipe. Only the cook knows recipes.
- **Dev convenience:** if `JOB_BACKEND=inline`, there's no Redis/cook at all — it
  just runs the job in a background thread. Good for quick local testing; not for
  production.

#### `backend/app/jobs/runners.py` (new)
- **What:** the actual **task implementations** the worker runs:
  `run_optimize_job` and `run_md_job` (registered as Celery tasks `jobs.optimize`
  / `jobs.md`). The shared `_run` function does the choreography:
  1. load the job's spec from the DB,
  2. `mark_running`,
  3. build a `ProgressReporter`,
  4. call the real simulation service (`run_optimization` / `run_md`),
  5. `_finalize` — write result + artifacts and set the final status.
- **Why:** this is **the cook following the recipe**. It is the *only* part that
  imports ASE/MACE (the science). It translates a ticket into a finished meal and
  files the result.
- **Analogy:** the cook reads the ticket, gets the ingredients, cooks, plates the
  dish, and marks the ticket "served".

#### `backend/app/jobs/progress.py` (new)
- **What:** the `ProgressReporter`. The simulation calls it every logged step; it
  (a) writes progress to the DB, (b) publishes it to a Redis channel `job:<id>`,
  and (c) checks whether you pressed Cancel (and raises `JobCancelled` if so).
- **Why:** so you can watch a long job live, and stop it. It **throttles** writes
  (at most ~once per second) so a 10,000-step run doesn't hammer the database.
- **Analogy:** the cook glancing up every minute to update the **order screen**
  ("50% plated") and to check if the customer **cancelled**. He doesn't update the
  screen on every single stir — that'd be wasteful.

#### `backend/app/jobs/worker.py` (new)
- **What:** the **worker entry point**. Importing it loads the Celery app and the
  runners (which registers the tasks).
- **Why:** this is the program you actually start to *be a cook*:
  `celery -A app.jobs.worker:celery_app worker --concurrency=1`.
  `--concurrency=1` means "one big dish at a time per cook" — right for GPU jobs.
- **Analogy:** **hiring and stationing a cook** in the kitchen. Until you run
  this, tickets pile up on the rail with nobody cooking.

#### `backend/app/jobs/__init__.py` (new)
- Just marks `jobs/` as a Python package and documents what's inside. (The empty
  signboard on the kitchen door.)

---

### 3.5 The science code (lightly changed)

#### `backend/app/services/simulation/optimization.py` & `md.py` (changed)
- **What changed:** each gained a `progress_callback` parameter. They already had
  a natural "every step" hook (`opt.attach(...)` / `dyn.attach(...)`); now that
  hook also calls the reporter and can be **interrupted** by `JobCancelled`
  (returning a "cancelled" status with whatever was computed so far).
- **Why:** so the worker can show live progress and honor cancellation **without
  the science code knowing anything about Redis, Celery, or jobs.** It just calls
  a function it was handed.
- **Analogy:** the recipe now has a line that says "every few minutes, tell
  whoever gave you this clipboard how it's going, and if they say stop, stop."

---

### 3.6 The tools (where a chat turn becomes a job)

#### `backend/app/tools/material_tools.py` (changed)
- **What changed:** `optimize_structure` and `run_md_simulation` no longer cook.
  They validate inputs, find the structure file, then call the new helper
  `_enqueue_job(...)`, which: reads who you are (from context, §3.7), creates the
  job row, calls `enqueue(...)`, and returns `{status: "queued", job_id, track}`.
- **Why:** this is the moment **the waiter writes the ticket and walks away**.
  Returns in milliseconds instead of blocking for an hour.
- **Analogy:** the waiter stops cooking your meal at the table and starts using
  the ticket system like everyone else.

#### `backend/app/core/context.py` (new)
- **What:** two `ContextVar`s holding the current `user_id` and `session_id`, with
  `set_request_identity()` / `get_user_id()` / `get_session_id()`.
- **Why this is needed:** the tool runs in a background **thread**, far from the
  web request, so it can't see "who is logged in". But a job must be *owned* by a
  user. The graph sets these just before running a tool, and the tool reads them.
- **Analogy:** the waiter clips your **table number** to the order before handing
  it off, so the kitchen knows whose meal this is.

---

### 3.7 The agent (wiring the identity + announcing the job)

#### `backend/app/agent/graph.py` (changed)
- **What changed:** the agent state and `run_agent` now carry `user_id`; right
  before a tool runs, it calls `set_request_identity(user_id, session_id)`; and
  when a tool returns a `job_id`, it emits a special stream event
  `data: [JOB:{...}]` so the browser knows a job started.
- **Why:** to connect "the logged-in user" to "the job that gets created", and to
  tell the UI to start watching.

#### `backend/app/api/chat.py` (changed)
- **What changed:** one line — passes `user_id=current_user.id` into `run_agent`.
- **Why:** that's the source of the identity everything downstream needs.

---

### 3.8 The API (how the browser asks about jobs)

#### `backend/app/api/jobs.py` (new)
- **What:** four endpoints:
  - `GET /api/jobs` — list *your* jobs (optionally filter by session/status).
  - `GET /api/jobs/{id}` — one job's full record.
  - `POST /api/jobs/{id}/cancel` — request cancellation.
  - `GET /api/jobs/{id}/stream` — **SSE**: it re-reads the job row once a second
    and streams status/progress until the job finishes.
- **Why:** the dashboard needs to read state and stream progress. Note there is
  **no public "create job"** endpoint — jobs are only created by the agent tools,
  keeping the agent the single orchestrator.
- **Analogy:** the **order-status screen** and the **cancel button** at the
  counter. ("SSE" just means the server keeps the line open and pushes updates,
  instead of you refreshing.)

#### `backend/app/main.py` (changed)
- **What changed:** registers the new jobs router (`/api/jobs`).
- **Why:** so the endpoints actually exist on the running server.

---

### 3.9 The frontend (what you see)

#### `frontend/src/api/jobs.js` (new)
- **What:** browser helpers — `listAsyncJobs`, `getAsyncJob`, `cancelAsyncJob`,
  `streamAsyncJob` — that call the `/api/jobs` endpoints with your auth token.
- **Why:** the UI shouldn't sprinkle `fetch()` calls everywhere; these wrap them
  cleanly. (`streamAsyncJob` uses `fetch` streaming because the simple browser
  `EventSource` can't send the login token.)

#### `frontend/src/features/sessions/AsyncJobsPanel.jsx` (new)
- **What:** the **live "Simulations" panel** in the right sidebar (Jobs tab). It
  polls your jobs (fast while any are active, slow when idle), shows a progress
  bar + step/energy/temperature, and a **Cancel** button.
- **Why:** so you can watch a relaxation/MD run live and cancel it.
- **Analogy:** the screen above the counter showing "Order #123 — 60% — cooking".

#### `frontend/src/features/sessions/RightPanel.jsx` (changed)
- **What changed:** mounts `AsyncJobsPanel` above the existing `JobDashboard` in
  the Jobs tab.
- **Why:** the old `JobDashboard` shows *fast tool history* (searches, VASP input
  generation). The new panel shows *long-running simulations*. They coexist.

#### `frontend/src/api/index.js` (changed)
- One line — re-exports the new `jobs.js` helpers so other code can import them.

---

## 4. Two questions beginners always ask

**Q: Why are there TWO database connections (`asyncpg` and `psycopg2`)?**
The web app is **async** (it juggles many requests at once on one thread, like a
waiter taking many orders without standing still). Async code needs an async
driver: `asyncpg`. The Celery worker is **synchronous** (one cook, one dish, start
to finish) and uses a normal driver: `psycopg2`. Same database, two doors.

**Q: Why Postgres instead of the SQLite file we had?**
SQLite is one notebook that only **one** writer can scribble in at a time. Now we
have two writers at once — the web app *and* the worker (writing progress every
second). They'd collide and lock. PostgreSQL is built for many simultaneous
writers. (We kept SQLite as an automatic fallback so the app still boots on a
laptop with nothing installed — but it's not for real multi-process use.)

---

## 5. How to connect it all and run it

You need **four things running**: PostgreSQL, Redis, the web app, and the worker.

### Step 0 — install the new Python packages
```bash
cd backend
../venv/bin/pip install -r requirements.txt
```

### Step 1 — start PostgreSQL and create a database
Using Docker is the easiest:
```bash
docker run -d --name materia-pg -e POSTGRES_USER=materia \
  -e POSTGRES_PASSWORD=materia -e POSTGRES_DB=materia -p 5432:5432 postgres:16
```

### Step 2 — start Redis (the ticket rail)
```bash
docker run -d --name materia-redis -p 6379:6379 redis:7
```

### Step 3 — point the app at them (in `backend/.env`)
```ini
DATABASE_URL=postgresql://materia:materia@localhost:5432/materia
REDIS_URL=redis://localhost:6379/0
JOB_BACKEND=celery
```

### Step 4 — build the database schema
```bash
cd backend
../venv/bin/alembic upgrade head
```

### Step 5 — start the web app (the waiter)
```bash
cd backend
../venv/bin/uvicorn app.main:app --reload
```

### Step 6 — start the worker (the cook) in a SECOND terminal
```bash
cd backend
../venv/bin/celery -A app.jobs.worker:celery_app worker --loglevel=info --concurrency=1
```

### Step 7 — start the frontend (a THIRD terminal)
```bash
cd frontend
npm install
npm run dev
```

Now open the app, ask Materia to *"relax this structure with MACE"*, and watch the
**Simulations** panel: the job goes **queued → running** (with a live progress bar)
**→ succeeded**, and the output files appear — all without freezing the chat.

### The lazy shortcut (no Docker, no Redis, no Postgres)
For a quick local test you can skip steps 1, 2, and 6 entirely:
```ini
# in backend/.env — leave DATABASE_URL unset (uses SQLite) and:
JOB_BACKEND=inline
```
With `inline`, the job runs in a background thread inside the web app (no real
cook, no rail). It proves the flow end-to-end but does **not** give you the
production benefits (isolation, survival across restarts, multiple workers). Use
the full setup above for anything real.

---

## 6. One-paragraph recap

A chat request hits the **web app** (waiter). The `optimize_structure` /
`run_md_simulation` **tool** writes a **job row** in the database (the ticket),
then **enqueues** a tiny message on **Redis** (pins the ticket to the rail) and
immediately replies `job_id`. A separate **Celery worker** (cook) pulls the
message, marks the job *running*, calls the **simulation service** (the recipe),
and through the **ProgressReporter** writes progress to the database every second
(and checks for cancellation). When done it writes results + artifacts and marks
the job *succeeded*. The browser's **AsyncJobsPanel** reads `/api/jobs` and the
**SSE stream** to show live progress. The database is always the source of truth,
so nothing is ever lost.
