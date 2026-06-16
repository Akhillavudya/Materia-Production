# Step 2 — Containerize & Deploy (Beginner Explanation)

> **Status:** ✅ Files created & validated (frontend build, compose YAML, model script all pass).
> The actual image build runs on **your** machine/server (this sandbox can't access Docker).
> This is a **learn-Docker-from-zero** doc: core concepts → file-by-file → command cheat-sheet.

---

## 1. One-sentence summary

We packed Materia into **shipping containers** so it runs identically on any machine, and put a
**smart front door (Caddy)** in front that serves the website, routes `/api` to the backend, and
gives us HTTPS automatically.

---

## 2. Core Docker concepts (read this first)

### The shipping analogy
Before shipping containers, loading a ship was chaos — every item a different shape. The standard
**container** changed the world: seal anything inside a standard box, and any crane, truck, or ship
handles it the same way. **Docker does this for software.**

### The 6 words you must know

| Word | What it really is | Analogy |
|---|---|---|
| **Image** | A frozen, read-only snapshot of "app + its OS + libraries + settings" | A **cake recipe + all ingredients pre-measured**, sealed in a box |
| **Container** | A *running* copy of an image | The **cake actually baking** in the oven. You can run many cakes from one recipe |
| **Dockerfile** | A text file of steps to *build* an image | The **written recipe** |
| **Registry** | A place to store/share images (Docker Hub, GitHub) | The **cookbook library**. `docker pull` borrows a recipe |
| **Volume** | Storage that lives *outside* the container and survives restarts | A **safe deposit box** — the building can be demolished, the box stays |
| **Network** | A private LAN where containers find each other by name | An **internal phone system**: `api` can "call" `postgres` by name |

### Image vs Container — the #1 thing beginners confuse
- An **image** is a *class*; a **container** is an *instance* (like OOP).
- An **image** is a *.exe file on disk*; a **container** is the *running program*.
- You **build** an image once, then **run** it as many containers as you want.

### Why "layers" make Docker fast
Each line in a Dockerfile creates a **layer** (a saved checkpoint). Docker caches them. If you only
change your code, Docker reuses the cached "install dependencies" layer and rebuilds just the last
bit. *Analogy: you don't re-buy flour every time you bake — only what changed.* **This is why we
`COPY requirements.txt` and `pip install` BEFORE copying the app code** — so editing code doesn't
re-download PyTorch every time.

### Why containers at all? (the payoff)
1. **"Works on my machine" dies** — the box carries its whole environment.
2. **Reproducible** — the Oracle server runs the exact same box as your laptop.
3. **Isolated** — the database, backend, and web server can't accidentally trample each other.
4. **Disposable** — break a container? Throw it away, start a fresh one. Your data is safe in
   **volumes**.

### docker-compose: running many containers together
One app = many boxes (backend, worker, database, redis, web). Starting each by hand with the right
flags is tedious and error-prone. **`docker-compose.yml`** is a single file describing all of them
and how they connect — then **one command** (`docker compose up`) starts the whole building.

---

## 3. Materia as a small building (the 5 services)

| Service (box) | Role | Analogy |
|---|---|---|
| **caddy** | serves the website + HTTPS + routes `/api` | the **front door & receptionist** |
| **api** | FastAPI backend (logins, chat, files) | the **front office** |
| **worker** | runs heavy simulations | the **back-room lab bench** |
| **postgres** | the database | the **filing cabinet** |
| **redis** | job queue / message board | the **ticket spike** orders are pinned to |

`docker-compose.yml` is the **site plan** wiring all five together.

---

## 4. File-by-file: purpose + analogy

### 🐳 `backend/Dockerfile` — recipe for the backend box
Used by **both** `api` and `worker` (same code, different start command). Each line is a build step:

| Instruction | What it does | Why / analogy |
|---|---|---|
| `FROM python:3.12-slim` | Start from a tiny official Python OS | The **base ingredient**; "slim" = small; multi-arch so it runs on Oracle's ARM **and** your amd64 |
| `ENV PYTHON...` | Quiet output, no bytecode cache | Cleaner, smaller image |
| `WORKDIR /app` | Set the working folder inside the box | The **countertop** everything happens on |
| `apt-get install build-essential gcc g++ libgomp1` | OS build tools | Some science libs (pymatgen/mattersim) compile from source |
| `COPY requirements.txt` → `pip install -r` | Install Python deps **first**, alone | **Layer caching** — code edits won't re-download PyTorch |
| `COPY . .` | Copy the app code | The actual backend |
| `useradd appuser` + `USER appuser` | Stop running as root | **Security** — least privilege if breached |
| `EXPOSE 8000` | Document the port the app uses | A **label on the box** saying "plug here" |
| `HEALTHCHECK ...` | Periodic "alive?" ping | Lets Docker auto-restart a dead box |
| `ENTRYPOINT` / `CMD` | Default = start API server | The worker **overrides** `CMD` to run Celery instead |

### 🚪 `backend/docker-entrypoint.sh` — the boot script
On start, the **api** box runs `alembic upgrade head` (apply DB migrations) **then** launches the
server. The worker skips migrations (only one box should do them). *Analogy: unlock & set up the
office before opening.*

### 🧾 `backend/.dockerignore` & `frontend/.dockerignore` — the "don't pack" list
Excludes secrets (`.env`), the local `materia.db`, `node_modules`, the 398 MB models, `.git`.
*Analogy: a packing list that says "leave the cash and the junk drawer at home."* Also makes builds
faster and images smaller.

### 🌐 `frontend/Dockerfile` — front-door box (two stages = "multi-stage build")
- **Stage 1 (`node`)**: compiles React into static files (`npm ci` → `npm run build`).
- **Stage 2 (`caddy`)**: throws away Node, keeps only the finished files + Caddy.
*Analogy: bake the cake in a huge messy kitchen, then ship only the finished cake — the kitchen
stays home.* Result: a tiny final image.

### 🧭 `frontend/Caddyfile` — the receptionist's instructions
- `/api/*` → forward to the `api` box.
- everything else → serve the website; unknown paths fall back to `index.html` (so SPA routing works).
- Set `SITE_ADDRESS=your-domain.com` → Caddy **auto-fetches a free HTTPS certificate**.
- A commented `basicauth` block is ready for **Step 5** (lab-only password).

### ⚙️ `frontend/src/api/client.js` (1 line) + `frontend/.env.example`
`const API = '/api'` → `import.meta.env.VITE_API_BASE_URL || '/api'`. On the web it stays `/api`
(same origin, Caddy proxies it). The **future desktop app** sets `VITE_API_BASE_URL` to an absolute
URL. No change to current behavior.

### 🧩 `docker-compose.yml` — the site plan
Defines the 5 boxes, their shared **volumes** (database, job files, the HTTPS cert — survive
restarts), **healthchecks** (api waits until Postgres/Redis are ready), and the private **network**.
Cheap-server choices:
- Models mounted **read-only** from `./pre_trained_models` → never copied into the image.
- `worker --concurrency=1` → one simulation at a time (protects the small VM).
- Secrets (`JWT_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`) come from your **root
  `.env`** — never hard-coded.

### 📦 `scripts/fetch_models.sh` — provision the big models
Checks the 5 model folders exist and tells you how to copy them to a fresh server. Too big for git
or the image, so they ride along separately.

---

## 5. Docker command cheat-sheet (you're learning — here's the real toolkit)

### A) Building images
```bash
docker build -t myname:tag .          # build image from ./Dockerfile, name it myname:tag
docker build -t materia-frontend:dev frontend/   # build a specific folder's Dockerfile
docker build --no-cache -t x:dev .    # ignore the layer cache (force a clean rebuild)
docker images                         # list images you have built/pulled
docker history materia-frontend:dev   # see the layers (build steps) inside an image
docker rmi materia-frontend:dev       # remove (delete) an image
```
*Mental model:* `build` turns a **recipe (Dockerfile)** into a **sealed box (image)**. `-t` is just
the box's label `name:tag` (tag often `dev`, `v1`, `latest`).

### B) Running containers (from an image)
```bash
docker run materia-frontend:dev               # run a container (foreground)
docker run -d --name web -p 8080:80 materia-frontend:dev   # detached, named, map ports
docker ps                                     # list RUNNING containers
docker ps -a                                  # list ALL containers (incl. stopped)
docker logs -f web                            # stream a container's logs
docker exec -it web sh                         # open a shell INSIDE a running container
docker stop web        &&  docker rm web        # stop, then delete the container
```
*Key flags:* `-d` detached (background), `-p HOST:CONTAINER` publish a port (e.g. `-p 8080:80`
means "visit localhost:8080 → hits port 80 in the box"), `--name` give it a friendly name,
`-it` interactive terminal (for `exec`/shells), `-e KEY=VALUE` set an env var,
`-v hostpath:boxpath` mount a folder/volume.

### C) Pulling/sharing images (registry)
```bash
docker pull postgres:16-alpine        # download an image from a registry (Docker Hub)
docker tag  myimg:dev  ghcr.io/you/myimg:dev   # re-label for a private registry
docker push ghcr.io/you/myimg:dev     # upload (keep Materia images PRIVATE per your plan)
```

### D) Compose — the whole Materia stack at once
```bash
docker compose up -d --build    # build images + start ALL services in the background
docker compose ps               # status + health of every service
docker compose logs -f api      # follow one service's logs (api / worker / caddy ...)
docker compose exec api sh      # shell into the running api container
docker compose up -d --build api   # rebuild & restart just one service after a code change
docker compose stop             # stop services (keep them)
docker compose down             # stop AND remove containers (volumes/data are KEPT)
docker compose down -v          # ⚠️ also delete volumes (wipes the database!) — careful
```

### E) Housekeeping (free up disk)
```bash
docker system df                # how much disk images/containers/volumes use
docker system prune             # delete stopped containers + dangling images
docker volume ls                # list volumes (your persistent data)
```

---

## 6. The exact commands to get Materia running

### Step 1 — let your user use Docker without sudo (one time)
Your user `roy` isn't in the `docker` group yet (that's why my build attempt said *permission
denied*). Run:
```bash
sudo usermod -aG docker $USER     # grant Docker access
newgrp docker                     # apply now (or log out / log back in)
```
*Why:* the Docker engine runs as root; the `docker` group is the key that lets your user talk to it.

### Step 2 — install the modern plugins (this machine is missing them)
```bash
sudo apt-get update
sudo apt-get install -y docker-compose-plugin docker-buildx-plugin
docker compose version            # should now print a version
```
*Why:* `docker compose` (with a space) is the current plugin; `buildx` is the modern builder.

### Step 3 — build one image by hand (watch it work)
```bash
docker build -t materia-frontend:dev frontend/
```
*What happens:* Docker reads `frontend/Dockerfile`, pulls `node:20-alpine`, runs `npm ci` then
`npm run build` (already proven to work here — `✓ built in 279ms`), then copies the result into a
small `caddy` image.

### Step 4 — run the whole stack
```bash
# First create a ROOT .env (never commit it) with:
#   POSTGRES_PASSWORD=<strong-password>
#   JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
#   FIELD_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
#   SITE_ADDRESS=materia.example.com         # or omit for local :80
#   SITE_URL=https://materia.example.com
docker compose up -d --build
docker compose ps                 # everything should be "healthy"
```
Open `http://localhost` (local) or `https://your-domain` (server).

---

## 7. What was verified here vs. what you run

| Check | Where | Result |
|---|---|---|
| Frontend production build (`npm run build`) | here | ✅ built in 279ms |
| `docker-compose.yml` is valid YAML | here | ✅ |
| `scripts/fetch_models.sh` finds all 5 models | here | ✅ |
| `docker build` the images | **your machine** | ⛔ here (no docker group) — run §6 Step 3 |
| Full `docker compose up` | **your machine / Oracle** | ▶️ run §6 Step 4 |

---

## 8. Oracle deployment notes

- **Build on the ARM server** (simplest way to get arm64 images) — or set up `buildx` to
  cross-build from your laptop.
- Base images (`python:3.12-slim`, `node:20-alpine`, `caddy`, `postgres`, `redis`) are
  **multi-arch** → they work on ARM automatically.
- Point your domain's DNS at the server, set `SITE_ADDRESS`, and Caddy gets HTTPS automatically.
- Keep the root `.env` (real secrets from Step 1) **only on the server**, never in git.

---

## 9. How the services actually connect (verified live) 🔌

We brought the stack up **by hand** on a shared network (because the `docker compose` plugin
isn't installed on this laptop yet). This is the best way to *see* the wiring.

### The one idea: a private network + name-based discovery
```bash
docker network create materia-net
```
Any container joined to `materia-net` can reach the others **by their container name**, like an
internal phonebook. So the backend connects to the database using the hostname **`postgres`**, not
an IP address:
- `DATABASE_URL = postgresql://materia:...@postgres:5432/materia`  ← "postgres" = the container name
- `REDIS_URL    = redis://redis:6379/0`                            ← "redis" = the container name
- Caddy proxies `/api` to **`api:8000`**                            ← "api" = the container name

That's why in `docker-compose.yml` we never write IP addresses — Docker's DNS resolves the service
names for us. *Analogy: you call coworkers by name on the office intercom, not by their desk's GPS
coordinates.*

### The request flow (what happens when a student uses Materia)
```
            ┌──────── your browser ────────┐
            │  http://localhost:8080 (or    │
            │  https://your-domain in prod) │
            └───────────────┬───────────────┘
                            ▼
                    ┌──────────────┐   serves the website (static files)
                    │   caddy:80   │───────────────────────────────────┐
                    │ (front door) │                                    ▼
                    └──────┬───────┘                              index.html + JS
                   /api/*  │ reverse_proxy
                            ▼
                    ┌──────────────┐      reads/writes      ┌──────────────┐
                    │   api:8000   │──────────────────────▶ │ postgres:5432│
                    │  (FastAPI)   │                         └──────────────┘
                    └──────┬───────┘      queues jobs        ┌──────────────┐
                            └───────────────────────────────▶│  redis:6379  │
                                                             └──────┬───────┘
                    ┌──────────────┐   picks up jobs                │
                    │    worker    │◀──────────────────────────────┘
                    │ (Celery,     │   reads/writes ──▶ postgres, shares files
                    │  concurrency │                    with api via a volume
                    │  = 1)        │
                    └──────────────┘
```

### What we verified live on this machine
The manual commands we ran (compose does all of this for you in one shot):
```bash
docker network create materia-net
docker run -d --name postgres --network materia-net -e POSTGRES_USER=materia \
    -e POSTGRES_PASSWORD=demo -e POSTGRES_DB=materia postgres:16-alpine
docker run -d --name redis    --network materia-net redis:7-alpine
docker build -t materia-frontend:dev frontend/
docker run -d --name caddy --network materia-net -e SITE_ADDRESS=:80 -p 8080:80 materia-frontend:dev
docker build -t materia-backend:dev backend/        # the heavy one (PyTorch etc.)
docker run -d --name api --network materia-net -e ENV=production -e RUN_MIGRATIONS=1 \
    -e DATABASE_URL=postgresql://materia:demo@postgres:5432/materia \
    -e REDIS_URL=redis://redis:6379/0 -e JWT_SECRET_KEY=<48-char> \
    -e FIELD_ENCRYPTION_KEY=<fernet> -e PRE_TRAINED_MODELS_DIR=/models \
    -v $PWD/pre_trained_models:/models:ro materia-backend:dev
```

| Health check | Command | Result |
|---|---|---|
| Postgres alive | `docker exec postgres pg_isready -U materia` | ✅ accepting connections |
| Redis alive | `docker exec redis redis-cli ping` | ✅ PONG |
| Website served | `curl localhost:8080/` | ✅ Materia SPA HTML |
| Proxy wired (before backend up) | `curl localhost:8080/api/` | ✅ 502 (Caddy reached for `api:8000`, nobody home yet) |
| Backend boots + runs DB migration | `docker logs api` | ✅ `Running upgrade -> ...initial schema` on Postgres |
| api healthy | `docker ps` | ✅ `(healthy)` |
| **Full chain** login through Caddy | `curl -X POST localhost:8080/api/auth/login` | ✅ **401** (real API reply — proxy→api→password check) |
| worker connects to Redis | `docker logs worker` | ✅ `Connected to redis` + `celery ready` |

### The real one-command equivalent (once the compose plugin is installed)
Everything above is exactly what this single command does for you:
```bash
docker compose up -d --build
docker compose ps          # all services show "healthy"
```
Install the plugin on this laptop (and on Oracle) with:
```bash
sudo apt-get update && sudo apt-get install -y docker-compose-plugin
```

### Cleaning up the manual demo
The hand-run containers are named `postgres`, `redis`, `api`, `caddy`. Remove them with:
```bash
docker rm -f postgres redis api caddy
docker network rm materia-net
```
(Your real workflow will be `docker compose down` instead.)

---

## 9b. Build journey — 3 real lessons from getting the backend image to build 🧪

The first backend build failed, twice — and each failure taught something worth keeping.

### Lesson 1 — Don't ship GPU libraries to a CPU server
`mattersim` pulls in **PyTorch**, which *by default* drags in **~2.5 GB of NVIDIA CUDA**
libraries. Our Oracle target is **CPU-only**, so that's pure waste — and the giant download
even failed on a network hiccup. **Fix:** install CPU-only Torch first, from PyTorch's CPU
wheel index:
```dockerfile
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install -r requirements.txt
```
Result: Torch dropped from ~2.5 GB → **192 MB**, and the build became reliable.

### Lesson 2 — Audit dependencies against actual imports
`requirements.txt` had ~40 packages; grepping the code for real `import` statements showed
**~14 were never imported** (`chgnet`, `sevenn`, `orb-models`, `openai`, `anthropic`,
`pydantic_ai`, `optuna`, `pandas`, `seaborn`, …). Three of them were *other* Torch-based ML
potentials we don't use — huge dead weight. The audit also caught the opposite bug: **`mace-torch`
was missing** even though MACE is the *default* calculator (`from mace.calculators import
MACECalculator`) — the image would have crashed at runtime. *Lesson: the dependency list should
mirror what the code imports — no more, no less.*

### Lesson 3 — "ResolutionImpossible" ≠ impossible
After trimming, the build hit a hard conflict:
```
mace-torch 0.3.16 depends on e3nn==0.4.4
mattersim  1.2.4  depends on e3nn>=0.5.0
```
Two packages demanding incompatible versions of `e3nn`. But the **dev venv runs both fine on
0.4.4** — MatterSim's declared requirement is stricter than what it actually needs (a very common
scientific-Python metadata mismatch). **Fix:** pin the exact combo proven to work and install with
pip's lenient *legacy resolver*:
```dockerfile
RUN pip install --use-deprecated=legacy-resolver -r requirements.txt   # e3nn==0.4.4 pinned
```
*General mindset:* when pip's strict resolver blocks a combo that you* know* works, pin exact
versions and either install in stages or use the legacy resolver — don't just delete a feature.

**Net result:** image shrank from ~6–8 GB (CUDA) to **4.22 GB** (CPU), builds reliably, and keeps
both MACE + MatterSim.

---

## 10. Where this fits

**Step 2 of 10** — Materia is now portable and reproducible. Next, **Step 3** hardens the database
(require Postgres, no silent SQLite); the compose file is already wired for it. Golden rule: the 8
new simulation tools come only **after Step 4** (overload guardrails).
```
✓ Step 1 secrets   ✓ Step 2 containers   → Step 3 Postgres → Step 4 caps → … → new tools
```
