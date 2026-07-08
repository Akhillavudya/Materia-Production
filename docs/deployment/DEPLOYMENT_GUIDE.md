# Materia — Deployment Guide (Beginner-Friendly)

> **Read this first.** This guide is written for someone who has never deployed a web
> app before. It explains **what you do now** (a *private* launch, before the paper is
> published) and **what you do later** (flipping it *public*, after publication).
>
> There are two things people can use:
> - **Web app** — you host it on a cloud server; users open a URL in their browser.
> - **Desktop app** — an installer (`.exe` / `.dmg` / `.AppImage`) users run on their own PC.
>
> Both ship **all 23 tools**. The only differences are *where the heavy simulations run*
> (web = on your server's CPU; desktop = on the user's own machine) and *who can sign up*.

---

## The big picture (why this is safe for the embargo)

- **Hosting is NOT the same as publishing your code.** When you deploy the web app, the
  server runs a *compiled* frontend + the backend program. Nobody can see or download your
  source code. The desktop app ships a *frozen binary* (the Python code is bundled, not
  readable). **Your GitHub repo stays private the whole time.**
- **Going public later is basically one setting.** You do **not** rebuild or re-deploy from
  scratch. You change one line in a config file and restart one container. Details in
  [Phase 2](#phase-2--after-the-paper-going-public).

---

## Key vocabulary (so the rest makes sense)

| Term | Plain meaning |
|---|---|
| **Docker / container** | A box that holds the app + everything it needs, so it runs the same anywhere. |
| **docker compose** | A tool that starts *several* containers together (database, app, web server…). |
| **`.env` file** | A secret settings file (passwords, keys). **Never** put it on GitHub. |
| **Invite mode** | New users must type a secret code to register. This keeps it private. |
| **Open mode** | Anyone can register. This is "public". |
| **Caddy** | A small web server that automatically gives you free HTTPS (the padlock 🔒). |
| **Oracle A1** | A free cloud computer (ARM chip, 4 CPUs, 24 GB RAM, no graphics card). |
| **POTCAR** | Licensed VASP files. We never commit them; they're copied to the server by hand. |

---

# Phase 1 — NOW (private launch, before the paper)

Goal: **a working web app that only invited people can use, plus desktop installers you
hand out directly.** Nobody outside your circle can get in, and your code stays private.

## 1A. Web app — step by step

### Step 1 — Get a free cloud computer (Oracle A1)
1. Sign up at Oracle Cloud (Always-Free tier). Create an **Ampere A1** instance:
   Ubuntu 24.04, ARM64, 4 CPUs / 24 GB RAM. Add your SSH key so you can log in.
2. **Open the network ports 80 and 443** in **two** places (this is the #1 thing beginners
   miss on Oracle — miss either one and the site is unreachable):
   - **VCN Security List** (in the Oracle web console): add ingress rules for TCP **80** and **443**.
   - **The server's own firewall** (over SSH):
     ```bash
     sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
     sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```
3. Install Docker + the compose plugin on the server (Docker's official install script).
4. Get a domain name (free options: DuckDNS, or a Cloudflare-managed domain) and point an
   **A record** at your server's public IP. Caddy needs a real domain to issue the HTTPS
   certificate automatically.

### Step 2 — Copy the private files to the server
These files are **not** in the repo (they're git-ignored or licensed), so you copy them by
hand with `scp` or `rsync` from your laptop to the server's project folder:
- `pre_trained_models/` — the ML model checkpoints (~398 MB). Put at the project root.
- `data/c2db/` — the 2D-materials search database (~71 MB). Put at the project root.
- The licensed **POTCAR** folder — put it somewhere like `/opt/potcar`.

### Step 3 — Write the secret settings (`.env`)
In the project folder on the server, create a file named `.env` (then `chmod 600 .env` so
only you can read it). Fill it in:

```env
POSTGRES_PASSWORD=<any strong password>
JWT_SECRET_KEY=<run: python -c "import secrets;print(secrets.token_urlsafe(48))">
FIELD_ENCRYPTION_KEY=<run: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
SITE_ADDRESS=materia.yourdomain.com        # your domain — Caddy uses it for HTTPS
SITE_URL=https://materia.yourdomain.com    # same domain — used for security (CORS)
SIGNUP_MODE=invite                         # <-- PRIVATE: people need a code to join
INVITE_CODES=lab-code-1,lab-code-2         # the secret codes you hand out
POTCAR_DIR=/opt/potcar                     # where you put the POTCAR folder in Step 2
# optional: GOOGLE_CLIENT_ID=...   MODEL_PROVIDER=gemini
```

> ⚠️ **Generate `JWT_SECRET_KEY` and `FIELD_ENCRYPTION_KEY` once and never change them.**
> If you change them later, everyone gets logged out and every saved API key becomes
> unreadable. Treat them like permanent passwords.

### Step 4 — Build and start everything
From the project folder on the server:
```bash
docker compose build      # builds the app (see the note below about the ARM chip)
docker compose up -d      # starts: database + redis + backend + worker + web server
```
The first start automatically sets up the database tables (Alembic migrations run on boot).

> 🧪 **One thing to watch — the ARM chip.** Oracle A1 uses an ARM processor, and PyTorch's
> "CPU-only" download page doesn't always have ARM versions. If `docker compose build`
> fails while installing `torch`, that's the known risk. The fix is a ~2-line change in
> `backend/Dockerfile` to install torch from the normal PyPI index instead (which *does*
> have ARM versions). If you hit this, ask Claude to apply "the ARM torch PyPI fallback"
> and re-run the build.

### Step 5 — Check it works (smoke test)
```bash
curl -s localhost/health        # should say ok
curl -s localhost/api/auth/config   # should show: heavy_tools_enabled: true, signup_mode: invite
```
Then in a browser:
1. Open `https://materia.yourdomain.com` — you should see the padlock 🔒 (Caddy issued HTTPS).
2. Register using one of your invite codes. A wrong/blank code should be **rejected**.
3. Run an **instant** tool (e.g. build a structure) — confirms the basics + POTCAR work.
4. Run a **heavy** tool on a **small** cell (e.g. optimize an 8-atom silicon) — confirms the
   ML simulations run on the server. Watch it happen with:
   ```bash
   docker compose logs -f worker
   ```

### Step 6 — Day-to-day
- **Update the app:** `git pull && docker compose up -d --build`
- **Back up your data:** the important state lives in Docker volumes — the Postgres database
  (`pgdata`), the job outputs (`materia_storage`), and the HTTPS certificate (`caddy_data`).
  Schedule a `pg_dump` of the database.

## 1B. Desktop app — step by step (private hand-off)

You already have the desktop build (Parts C1–C4). For the **private** phase you do **not**
publish a public release. Instead:

1. **Do NOT push a git tag that starts with `v`** (like `v0.1.0`). That would trigger the CI
   to publish a **public** GitHub Release — which you don't want before the paper.
2. Go to GitHub → **Actions** → the **"Desktop Release"** workflow → **"Run workflow"**
   (this is the `workflow_dispatch` manual button). It builds all the installers
   (Windows / macOS / Linux, CPU and GPU variants) **without publishing** them.
3. When it finishes, download the installers from that run's **Artifacts** section.
4. Hand the `.exe` / `.dmg` / `.AppImage` files to your lab members directly (private drive,
   internal share, USB — whatever).
5. Because the installers are unsigned, users click through **one** OS security warning the
   first time. That's normal and documented in `desktop/README.md`.

*(Alternative: build locally with `cd desktop && npm run dist -- --publish never`.)*

---

# Phase 2 — AFTER the paper (going public)

When the paper is published and the embargo lifts, you flip both surfaces to public. This
is deliberately tiny — **no rebuild, no data loss.**

### Web → public (one setting)
On the server, edit `.env`:
```env
SIGNUP_MODE=open      # was: invite
```
Then:
```bash
docker compose up -d   # recreates just the backend container, ~seconds
```
That's it. Now **anyone** can register (the invite codes are simply ignored). All existing
accounts, saved keys, and sessions are untouched because `JWT_SECRET_KEY` and
`FIELD_ENCRYPTION_KEY` didn't change.

### Desktop → public (one tag)
1. Bump the version in `desktop/package.json`.
2. Push a git tag that starts with `v`, e.g.:
   ```bash
   git tag v0.1.0 && git push prod v0.1.0
   ```
That triggers the CI to build **and publish** the installers to public GitHub Releases, and
turns on auto-update for users. Done.

### Before a *large* public crowd (not blockers — do these when traffic grows)
The lab-scale setup is fine for a URL you share with a handful of people. Before real
public traffic, plan for:
- **Per-user key isolation:** today decrypted user API keys are briefly written to a shared
  process environment. Safe at low concurrency, but make it request-scoped before scale.
- **Scale ladder:** managed Postgres → object storage (S3) for job outputs → load balancer
  with multiple app replicas. Heavy simulations run one-at-a-time on the single worker, so
  a busy public site would need more workers / a bigger machine.

---

## Quick reference — the one-line differences

| | **Now (private)** | **After paper (public)** |
|---|---|---|
| Web signup | `SIGNUP_MODE=invite` + codes | `SIGNUP_MODE=open` |
| Web go-live action | `docker compose up -d` | edit `.env`, `docker compose up -d` |
| Desktop distribution | manual `workflow_dispatch` artifacts | push a `v*` tag → public Releases |
| Code repo | private | (you decide when to open it) |
| Tools available | all 23 | all 23 (no change) |

---

## Where to get help
- The full technical plan lives at `~/.claude/plans/few-days-i-was-sharded-coral.md`.
- If any step breaks, write a short postmortem in `docs/issues_solved/` (per project rule).
