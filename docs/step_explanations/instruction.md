# Materia — How to Run the Whole Stack Yourself (Runbook)

> A clear, copy-paste guide to start Materia in Docker and use the chatbot.
> Covers: how many images there are, which to start first and why, the two ways to run it,
> how to use the chatbot, how it works, and troubleshooting.

---

## 1. What the stack is — 4 images, 5 containers

Materia is **not one program** — it's a few containers working together. There are **4 images**,
but **5 running containers** (the backend image runs **twice**: once as the web API, once as the
worker).

| # | Container | Image | Role | Analogy |
|---|---|---|---|---|
| 1 | `postgres` | `postgres:16-alpine` | Database (users, sessions, jobs, keys) | the **filing cabinet** |
| 2 | `redis` | `redis:7-alpine` | Job queue / message bus | the **ticket spike** |
| 3 | `api` | `materia-backend:dev` | FastAPI backend (login, chat, files) | the **front office** |
| 4 | `worker` | `materia-backend:dev` *(same image!)* | Celery worker that runs simulations | the **back-room lab bench** |
| 5 | `caddy` | `materia-frontend:dev` | Serves the website + routes `/api` + HTTPS | the **front door & receptionist** |

> So `api` and `worker` are the **same image** started with a **different command**.

---

## 2. Which to start first (the order matters)

Each box depends on the ones before it, so start them in this order:

```
1. network   →  2. postgres + redis   →  3. api   →  4. worker   →  5. caddy
   (the wiring)     (foundations)          (needs DB+redis;       (needs DB+redis;   (needs api)
                                            runs DB migrations)    shares files w/ api)
```

**Why this order:** `api` can't migrate the database until `postgres` is up; the `worker` and `api`
must both be running before jobs can flow; `caddy` proxies to `api`, so `api` should exist first.

---

## 3. Option A — the EASY way: `docker compose` (recommended)

One command starts everything in the right order, with the correct shared storage and healthchecks.
This is also exactly how you'll run it on the Oracle server.

```bash
# one-time: install the compose plugin (this laptop doesn't have it yet)
sudo apt-get update && sudo apt-get install -y docker-compose-plugin 

# create a ROOT .env file (NEVER commit it) next to docker-compose.yml:
cat > .env <<'EOF'
POSTGRES_PASSWORD=change-this-password
JWT_SECRET_KEY=PUT_A_LONG_RANDOM_STRING_HERE
FIELD_ENCRYPTION_KEY=PUT_A_FERNET_KEY_HERE
SITE_ADDRESS=:80
SITE_URL=http://localhost
EOF
# generate the two keys:
#   JWT:    python3 -c "import secrets; print(secrets.token_urlsafe(48))"
#   FERNET: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# build + start ALL services
docker compose up -d --build

# check health
docker compose ps
```

Then open **http://localhost** (port 80). To stop: `docker compose down` (data is kept in volumes).

> ⚠️ If you switch to compose, first remove the hand-run containers to avoid name clashes:
> `docker rm -f api worker caddy postgres redis && docker network rm materia-net`

---

## 4. Option B — the MANUAL way (what we've been doing)

Use this only until the compose plugin is installed. Copy-paste the whole block. It generates
secrets, starts everything in order, and — importantly — mounts the **shared storage volume on BOTH
api and worker** (skipping this makes jobs fail) and **starts the worker** (skipping this leaves
jobs stuck "queued").

```bash
cd ~/Desktop/Materia-Production

# secrets (reuse the SAME ones for api + worker so saved keys stay readable)
JWT=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
FERNET=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# (build the images once, if you haven't)
docker build -t materia-backend:dev backend/
docker build -t materia-frontend:dev frontend/

# 1) private network
docker network create materia-net 2>/dev/null || true

# 2) foundations: postgres + redis (no host ports -> no clash with local installs)
docker run -d --name postgres --network materia-net \
  -e POSTGRES_USER=materia -e POSTGRES_PASSWORD=demo -e POSTGRES_DB=materia \
  postgres:16-alpine
docker run -d --name redis --network materia-net redis:7-alpine
sleep 5

# shared settings for api + worker (note the shared storage volume!)
COMMON="--network materia-net -e ENV=production \
  -e DATABASE_URL=postgresql://materia:demo@postgres:5432/materia \
  -e REDIS_URL=redis://redis:6379/0 \
  -e JWT_SECRET_KEY=$JWT -e FIELD_ENCRYPTION_KEY=$FERNET \
  -e PRE_TRAINED_MODELS_DIR=/models \
  -v $PWD/pre_trained_models:/models:ro \
  -v materia_storage:/app/app/storage"

# 3) api (runs DB migrations on boot)
docker run -d --name api $COMMON -e RUN_MIGRATIONS=1 materia-backend:dev

# 4) worker (MUST be started; shares storage with api)
docker run -d --name worker $COMMON materia-backend:dev \
  celery -A app.jobs.worker:celery_app worker --loglevel=info --concurrency=1

# 5) caddy (front door on http://localhost:8080)
docker run -d --name caddy --network materia-net -e SITE_ADDRESS=:80 -p 8080:80 \
  materia-frontend:dev

sleep 8
docker ps    # all five should be Up
```

Open **http://localhost:8080** (manual mode uses port 8080).

---

## 5. How to USE the chatbot (after it's running)

Materia is **BYOK** — you bring your own free API key.

1. Open the site (http://localhost:8080 manual, or http://localhost with compose).
2. **Sign up** — email + a password of **at least 12 characters**.
3. Click **⚙️ Settings** (bottom-left of the sidebar) and paste:
   - a **Groq** key (free at console.groq.com) — needed to **chat**, and/or a **Gemini** key,
   - a **Materials Project** key (free at materialsproject.org) — needed to **search** materials.
   Each flips to **✓ set**.
4. **Chat.** Try: *"search for silicon"*, or *"generate a POSCAR for NaCl and optimize it"*.
   Long simulations run in the background — watch them go **queued → running → done** in the job
   panel on the right.

---

## 6. How it works (request flow)

```
  Browser ──▶ caddy ──/api──▶ api ──▶ postgres   (saves users, sessions, jobs, keys)
                │                │
            (website)            └──▶ redis  ──▶  worker  (runs MACE/MatterSim simulation,
                                                            writes results to shared storage)
```
- You chat → `api` calls your LLM (Groq/Gemini) with **your** key.
- You ask for a simulation → `api` puts a job on `redis` → `worker` picks it up, runs it on CPU,
  writes outputs to the **shared storage volume** → results appear in your job panel.

---

## 7. Everyday commands

```bash
docker ps                       # what's running + health
docker logs -f api              # follow backend logs
docker logs -f worker           # watch a simulation run
docker exec postgres pg_isready -U materia      # DB alive?
docker exec redis redis-cli ping                # redis alive? -> PONG

# stop everything (manual mode)
docker rm -f api worker caddy postgres redis && docker network rm materia-net
# (compose mode: docker compose down)
```

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Jobs stuck on **"queued"**, never run | The **worker isn't running** | Start the worker (step 4 above) |
| Jobs go to **"failed"** instantly | `api` & `worker` **don't share storage** → worker can't find the POSCAR | Ensure **both** mount `-v materia_storage:/app/app/storage` |
| Chat says *"add your API key"* | No LLM key set (BYOK) | ⚙️ Settings → paste a Groq or Gemini key |
| Search says it failed | No Materials Project key | ⚙️ Settings → paste your MP key |
| `worker` shows **"unhealthy"** (manual mode) | It inherits the API's HTTP healthcheck | Cosmetic — it still works. Compose fixes this with a Celery healthcheck |
| Login lost after a restart | `JWT_SECRET_KEY` changed | Reuse the same secret (compose `.env` keeps it stable) |

---

## 9. The golden rule

The simplest, least error-prone way is **`docker compose up -d`** — it always starts the worker,
mounts the shared storage, and uses stable secrets from your `.env`. The manual `docker run` path
works but it's easy to forget the worker or the shared volume (the two bugs above). Once the compose
plugin is installed, prefer Option A everywhere — including Oracle.
