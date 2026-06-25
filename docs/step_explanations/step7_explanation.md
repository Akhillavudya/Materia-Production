# Step 7 — Health checks & knowing when it's down

## The one-sentence purpose
Add a **heartbeat** the server can be pinged on, so a free uptime monitor texts
*you* the moment it dies — instead of you finding out from an angry student.

## The analogy
Right now there's **no smoke detector** in the lab. If a fire starts at 3 a.m.,
the first you hear of it is a furious message the next morning. Step 7 installs two
detectors:

- **`/health` — the pulse check.** "Is the web process breathing at all?" It
  touches **nothing** external, so it answers instantly and stays green even if the
  database hiccups. This is what the Docker container and a cheap uptime ping use.
- **`/ready` — the "can I actually do my job?" check.** It verifies the **database**
  and **Redis** (the job broker) are reachable. If one is down it returns **503**
  *and tells you which one* — so the alert says "Redis is unreachable," not just
  "something's wrong."

Why two? A server can be **alive but not ready** — e.g. the web process is up but
Postgres is restarting. `/health` stays green (don't kill/restart the web process),
while `/ready` goes red (don't send it real traffic yet). That distinction is
exactly what container orchestrators and good monitors want.

## Why before the new tools
Heavier tools make crashes more likely. You want to hear it from a **monitor**, not
a frustrated student — and you want to know *what* broke at a glance.

## 📁 Files that changed & why

| File | What & why |
|---|---|
| `app/api/health.py` *(new)* | The two endpoints. `/health` → `{"status":"ok"}`. `/ready` runs `SELECT 1` against the DB and pings Redis (the Redis client is imported lazily and **skipped** when `JOB_BACKEND=inline`, since there's no broker then). Returns `200 {"status":"ready", checks:{…}}` when both pass, `503 {"status":"degraded", …}` otherwise. Both are **unauthenticated** so a monitor can hit them with no login. |
| `app/main.py` | Mounts the health router at **root** (`/health`, `/ready`) — *not* under `/api` — so the container `HEALTHCHECK` and external monitors hit them directly. |
| `backend/Dockerfile` | `HEALTHCHECK` now curls `/health` (was `/`) — a purpose-built liveness path. |
| `frontend/Caddyfile` | Added a `@health` matcher forwarding `/health` and `/ready` to the backend, so an external monitor can ping `https://your-domain/health` through the front door. |

## How to wire up the actual alert (operator, ~2 min)
1. Sign up for a free uptime monitor (UptimeRobot / BetterStack / Healthchecks.io).
2. Add an HTTP monitor for `https://your-domain/health`, interval 1–5 min.
3. (Optional, sharper) add a second monitor for `/ready` so you catch
   "alive but DB/Redis down" too. Add your phone/email/Telegram as the alert target.

## Optional: Sentry (error reporting)
The plan mentions Sentry's free tier for capturing *what* broke (not just *that* it
broke). It's **not** wired in yet to avoid adding a dependency you may not want. To
add later: `pip install sentry-sdk`, set `SENTRY_DSN`, and call
`sentry_sdk.init(dsn=…)` once in `main.py`. The request-id from Step 6 makes those
reports easy to correlate.

> ⚠️ Note: if you later enable the Caddy front-door **basicauth** (Step 5), it
> guards the whole site including `/health`. Either point the monitor at an
> authenticated URL, or move basicauth to a path matcher that excludes `/health`.

## How it was verified
- `GET /health` → `200 {"status":"ok","service":"Materia Production Backend"}`.
- `GET /ready` → `200 {"status":"ready","checks":{"database":"ok","redis":"skipped (inline backend)"}}`
  on the local inline stack; against the real Docker stack it pings Postgres + Redis.
