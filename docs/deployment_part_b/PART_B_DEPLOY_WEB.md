# Deployment — Part B: Deploy the lite web edition to Oracle

**Status:** 🟡 IN PROGRESS — artifacts built 2026‑06‑26, server provisioning is the hands‑on step
**Scope:** ship the **15 instant tools** as a free, low‑maintenance web app; heavy
simulations stay gated (Part A) and live in the desktop app (Part C).
**Parent plan:** `docs/DEPLOYMENT_AND_DESKTOP_ROADMAP.md` (§2, Part B)

---

## 1. What changed in the repo (the build artifacts)

Two editions now live side‑by‑side. **Nothing from the full edition was deleted** —
the full stack was only *renamed* for clarity.

| File | Edition | Services | Image |
|------|---------|----------|-------|
| `docker-compose.full.yml` | **FULL** — all 23 tools | postgres + **redis** + api + **worker** + caddy | full `backend/Dockerfile` (torch + MACE + MatterSim + ATAT) |
| `docker-compose.web.yml` | **LITE WEB** — 15 instant tools | postgres + api + caddy | slim `backend/Dockerfile.web` (torch‑free) |

New files:
- `docker-compose.web.yml` — the lite stack (no worker, no redis).
- `backend/Dockerfile.web` — slim, **torch‑free** image. Drops PyTorch, MACE,
  MatterSim, phonopy, seekpath, matplotlib, and the ATAT C++ build. Smaller and far
  faster to build on the free ARM server.
- `backend/requirements-web.txt` — the slim dependency set the image installs.

Renamed:
- `docker-compose.yml` → `docker-compose.full.yml` (use this for dev / desktop / any
  box that should actually run simulations).

### Why a torch‑free image is safe
Every `torch`/`mace`/`mattersim`/`phonopy`/`seekpath`/`matplotlib` import in the
codebase is **lazy** (inside a function, guarded by `try/except ImportError`) and
lives only in the **heavy, gated** code paths. A repo‑wide check confirms **zero
top‑level imports** of the ML stack, so `import app.main` succeeds without it.

Two guards keep it that way:
1. **Build‑time:** `Dockerfile.web` runs `import app.main` during the build — if a
   future edit adds a top‑level torch import to a startup path, **the build fails**
   instead of crashing in production.
2. **Runtime:** even if the model ever tried to call a heavy tool, Part A's
   `_enqueue_job()` backstop refuses it with the "use the desktop app" message.

> Verified locally on 2026‑06‑26: `app.main` imports cleanly with the **entire ML
> stack blocked** at import (simulating the slim image) — no torch needed to boot.

---

## 2. The web edition's configuration (defence recap)

The lite stack sets, on the `api` service:

| Env | Value | Why |
|-----|-------|-----|
| `ENV` | `production` | enforces strong secrets + non‑wildcard CORS at boot |
| `ENABLE_HEAVY_TOOLS` | `false` | Part A gate — heavy sims refuse, point to desktop |
| `JOB_BACKEND` | `inline` | no Celery/Redis; gated tools never enqueue anyway |
| `DATABASE_URL` | postgres DSN | SQLite is rejected in production |
| `ALLOWED_ORIGINS` | `${SITE_URL}` | exact origin; wildcard is rejected |
| `PMG_VASP_PSP_DIR` | `/potcar` | `generate_vasp_inputs` assembles a real POTCAR |
| `SIGNUP_MODE` | `invite` (default) | closed by default; open only during first smoke test |

POTCAR PAW files are **mounted read‑only at runtime** (`${POTCAR_DIR}:/potcar:ro`),
never baked into the image or committed (per `potcar-runtime-mount`).

---

## 3. Server runbook (Oracle Cloud Always‑Free A1)

> Do these on the Oracle instance. ARM64, 4 CPU / 24 GB RAM, no GPU.

### 3.1 Provision the instance
1. Oracle Cloud → Compute → create an **Ampere A1 (ARM)** VM, image **Ubuntu 22.04/24.04**.
2. Add your SSH key; note the **public IP**.
3. **Networking → open ports 80 and 443** in *both* places (often missed):
   - the VCN **Security List** (ingress rules for `0.0.0.0/0` tcp 80, 443), and
   - the instance's host firewall (Ubuntu ships iptables rules):
     ```bash
     sudo iptables -I INPUT -p tcp --dport 80  -j ACCEPT
     sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```

### 3.2 Install Docker + compose plugin
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker   # so you can run docker without sudo
```

### 3.3 Get the code + POTCAR
```bash
git clone <your-prod-remote> materia && cd materia
# Upload your licensed POTCAR tree to the server (NOT in git), e.g. /opt/potcar
#   PBE_54/<ELEMENT>/POTCAR ...  (whatever your PMG_VASP_FUNCTIONAL expects)
```

### 3.4 Point a (free) domain at the IP
Create an **A record** `materia.yourdomain` → the instance public IP (free options:
DuckDNS, a subdomain, Cloudflare DNS, etc.). Wait for it to resolve (`dig +short materia.yourdomain`).
Caddy needs this to obtain the Let's Encrypt HTTPS cert automatically.

### 3.5 Create the root `.env` (NEVER commit it)
```bash
cat > .env <<'EOF'
POSTGRES_PASSWORD=<strong-random>
JWT_SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
FIELD_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
SITE_ADDRESS=materia.yourdomain
SITE_URL=https://materia.yourdomain
POTCAR_DIR=/opt/potcar
# Start OPEN just long enough to create your own account (see 3.7), then flip to invite.
SIGNUP_MODE=open
INVITE_CODES=lab2026
# GOOGLE_CLIENT_ID=...   # optional
EOF
chmod 600 .env
```
> Generate the secrets once and **keep them stable** — rotating `JWT_SECRET_KEY`
> logs everyone out; rotating `FIELD_ENCRYPTION_KEY` makes stored API keys
> undecryptable.

### 3.6 Build + launch the lite stack
```bash
docker compose -f docker-compose.web.yml up -d --build
docker compose -f docker-compose.web.yml ps        # all healthy?
docker compose -f docker-compose.web.yml logs -f api
```
First boot runs `alembic upgrade head` automatically (`RUN_MIGRATIONS=1`).

### 3.7 Smoke test over HTTPS
```bash
curl -fsS https://materia.yourdomain/health   # -> ok
curl -fsS https://materia.yourdomain/ready    # -> ready (DB reachable)
curl -fsS https://materia.yourdomain/api/auth/config   # heavy_tools_enabled: false
```
Then in a browser at `https://materia.yourdomain`:
1. Sign up (works because `SIGNUP_MODE=open` right now), log in.
2. Run an **instant** tool — e.g. *search a material* or *generate VASP inputs* —
   and confirm POTCAR assembly works (no "POTCAR.spec only" downgrade).
3. Try a **heavy** tool (e.g. *optimize* / *run MD*): it must stay **visible** with
   the **"Desktop app"** badge and show the desktop‑install message instead of
   starting a job. (Confirms the Part A gate is live in production.)

### 3.8 Lock the door LAST
Only after your own account exists and the smoke test passes:
```bash
# edit .env: SIGNUP_MODE=invite   (INVITE_CODES already set)
docker compose -f docker-compose.web.yml up -d   # recreates api with the new env
```
New users now need an invite code; you are not locked out.

---

## 4. Day‑2 operations

```bash
# update to a new build
git pull && docker compose -f docker-compose.web.yml up -d --build

# logs / status
docker compose -f docker-compose.web.yml logs -f api
docker compose -f docker-compose.web.yml ps

# DB backup (Step 10 territory)
docker compose -f docker-compose.web.yml exec postgres \
  pg_dump -U materia materia | gzip > backup-$(date +%F).sql.gz
```

Persistent state lives in named volumes: `pgdata` (database), `materia_storage`
(generated files), `caddy_data` (HTTPS cert). Back up `pgdata` and `materia_storage`.

---

## 5. Verification done in this branch
- Both compose files parse; `web` = postgres+api+caddy, `full` = postgres+redis+api+worker+caddy.
- `app.main` imports with the **entire ML stack blocked** → slim image boots torch‑free.
- `Dockerfile.web` bakes the same import as a **build‑time** regression guard.

## 6. What's left (operator‑side, not code)
- Provision the Oracle A1 box, install Docker, open 80/443, upload POTCAR, point DNS.
- Build/launch on the server, smoke‑test over HTTPS, flip `SIGNUP_MODE=invite` last.

**Next:** Part C — Electron desktop app (all 23 tools, local compute).
