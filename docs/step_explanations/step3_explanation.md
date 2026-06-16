# Step 3 — Postgres Hardening (Beginner Explanation)

> **Status:** ✅ Implemented & verified (prod fail-fast on bad DB, pooling applied, Celery
> healthcheck pings OK).
> This doc explains *what* changed, *why*, and *file-by-file* — with analogies.

---

## 1. One-sentence summary

We made Materia **refuse to run on the wrong database in production**, keep its database
connections **healthy over time**, and report the **worker's real health** — so the production
database is reliable instead of a silent foot-gun.

---

## 2. The big analogy

A database is the building's **filing cabinet**. Two things were unsafe:

1. **A flimsy backup cabinet that opens automatically.** If `DATABASE_URL` wasn't set, the app
   *silently* fell back to **SQLite** — a single-writer paper notebook. With the API *and* the
   worker both writing at once, that notebook tears (data corruption). Now the app **won't open
   for business** in production unless a proper PostgreSQL cabinet is connected.
2. **Stale phone lines.** Database connections sit idle and can go dead (the DB server hangs up
   after a while). Without a check, the next request grabs a dead line and errors. We added
   **pre-ping** ("is this line still alive?") and **recycle** ("replace lines older than 30 min").

Plus a small cleanup: the **worker** was being reported "unhealthy" because it was checked like a
web server — we now ask it the right question (a Celery "are you alive?" ping).

---

## 3. Core concepts (quick)

| Term | Plain meaning | Analogy |
|---|---|---|
| **PostgreSQL** | A real multi-user database server | A proper filing room with a librarian coordinating many writers |
| **SQLite** | A single-file database, one writer at a time | A single paper notebook |
| **Connection pool** | A reusable set of open DB connections | A bank of phone lines kept open to the filing room |
| **pre-ping** | Test a connection before using it | "Hello, still there?" before talking |
| **pool_recycle** | Drop connections older than N seconds | Hang up & redial old lines before they go dead |
| **Healthcheck** | A periodic "are you OK?" probe Docker runs | A pulse check on each container |

---

## 4. File-by-file: what changed & why

### 📄 `backend/app/core/config.py` — "the building inspector"
Added two more checks that run **only in production** (`ENV=production`):
- `DATABASE_URL` **must be set** — no silent SQLite fallback.
- It **must be PostgreSQL** — reject SQLite explicitly.

If either fails, the app **refuses to start** with a clear message. Local dev is unaffected (it
can still use SQLite). *Analogy: the inspector won't let the building open on a flimsy cabinet.*

### 📄 `backend/app/database/db.py` — "the phone switchboard"
When the database is PostgreSQL, the connection engine now uses:
- `pool_pre_ping=True` — check each line is alive before use,
- `pool_recycle=1800` — replace any line older than 30 minutes,
- `pool_size=5`, `max_overflow=10` — a sensible number of lines for one small server.

*Analogy: keep the phone lines to the filing room fresh and never hand someone a dead line.*
(SQLite dev keeps its simple default — these only apply to Postgres.)

### 📄 `docker-compose.yml` — "the pulse monitor"
The **worker** previously inherited the image's HTTP healthcheck (`curl :8000`), but the worker
runs **Celery**, not a web server — so it always looked "unhealthy." Now it uses Celery's own
ping (`celery ... inspect ping`), which reports the worker's **true** health.

---

## 5. Why this matters before the new tools

Every new simulation tool (defects, phonons, NEB, …) writes job rows to the database and runs on
the worker. A flaky database or a worker that *looks* dead would make those tools unreliable in
confusing ways. Hardening the foundation first means the new tools sit on solid ground.

---

## 6. What we verified

| Check | Result |
|---|---|
| Dev still boots (SQLite allowed) | ✅ |
| Prod + **no** `DATABASE_URL` | ✅ refuses to start |
| Prod + **SQLite** `DATABASE_URL` | ✅ refuses to start (must be PostgreSQL) |
| Prod + PostgreSQL + secrets | ✅ boots; `pool_pre_ping=True`, `recycle=1800` |
| Worker Celery healthcheck | ✅ `celery@…: OK / pong` |
| Full app import | ✅ |

---

## 7. Where this fits

**Step 3 of 10.** The database is now production-grade. Next up is **Step 4 — compute caps &
quotas** (the gate that must be in place *before* the 8 new simulation tools), then Step 5
(invite-only access). The `docker-compose.yml` is fully wired for this hardened setup.

**Commit:** `harden: require PostgreSQL in production, add DB connection pooling, fix worker healthcheck`
