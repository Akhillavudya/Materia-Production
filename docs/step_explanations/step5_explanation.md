# Step 5 — Invite-only access (lab members only)

**Status:** ✅ Implemented (2026-06-17)
**Goal:** Turn off open signup so only your PhD students can create accounts — using a
**shared invite code** you hand out (and can rotate/revoke).

---

## The analogy
Until now Materia had an **open front door**: anyone who found the URL could create an
account (`/auth/signup` accepted any email + password). Step 5 fits a **keycard reader**
on that door. No keycard (invite code) → no account. Your trusted students get the code;
strangers who stumble on the URL simply can't get in.

We deliberately chose the *simplest* keycard for a small lab — **one (or a few) shared
codes** — instead of heavier machinery (admin-created accounts, email-domain checks). You
can still layer those on later.

---

## How it works now

There are **three modes**, chosen by the `SIGNUP_MODE` environment variable:

| Mode | Who can register | When to use |
|------|------------------|-------------|
| `open` | anyone | local development (the default off-server) |
| `invite` | only someone with a valid code from `INVITE_CODES` | **your lab (production default)** |
| `closed` | nobody via the form | if you ever want to create every account by hand |

**Production safety-by-default:** if `ENV=production` and you don't set `SIGNUP_MODE`, it
**defaults to `invite`** — so a public URL is never accidentally open. And if the mode is
`invite` but you forgot to set any codes, the app **refuses to boot** with a clear message
(better a loud stop than a silently locked-out lab).

### The signup flow
1. The browser calls a tiny public endpoint **`GET /api/auth/config`** → `{ "signup_mode": "invite" }`.
2. The signup form uses that to **show an "Invite code" field** only when needed.
3. On submit, the code travels with the email/password to `POST /api/auth/signup`.
4. The backend checks it with a **constant-time comparison** (`secrets.compare_digest`) against
   every configured code — a wrong or missing code returns `403 "A valid invite code is required"`.

> Security note: the code is checked on the **backend** — that's the real lock. The frontend
> field is just convenience. The `/auth/config` endpoint only ever reveals the *mode*, never
> the codes themselves.

---

## 📁 Files that changed & why

**Backend (the real gate):**
- `app/core/config.py` — added `signup_mode` + `invite_codes` settings, the production
  "default to invite" logic, and a **fail-fast** check (invite mode with no codes = refuse to start).
- `app/schemas/auth.py` — `SignupRequest` gains an optional `invite_code` field.
- `app/api/auth.py` — `_enforce_signup_allowed()` applies the gate before creating a user
  (constant-time code match); new public `GET /auth/config` so the UI can adapt.
- `backend/.env.example` — documents `SIGNUP_MODE` and `INVITE_CODES`.

**Frontend (where students type the code):**
- `frontend/src/api/auth.js` — `signup()` now sends `invite_code`; new `getAuthConfig()`.
- `frontend/src/features/auth/AuthScreen.jsx` — fetches the mode, shows the **Invite code**
  field in invite mode, and hides "create an account" when signups are `closed`. (Also bumped
  the password hint to **12 characters** to match the backend rule — it previously said 8.)

---

## How to operate it (production)

In your server env (e.g. the api container):
```bash
ENV=production
SIGNUP_MODE=invite
INVITE_CODES=lab2026,visitor-7f3a     # share these with your students
```
- **Add a student:** just give them a code. They register themselves.
- **Revoke access for new signups:** remove/rotate a code in `INVITE_CODES` and restart the api.
  (This blocks *new* registrations with that code; it does not delete existing accounts.)
- **One-per-student codes** let you tell who used which, and revoke individually.

---

## Verified
- `GET /api/auth/config` → `{"signup_mode":"invite"}`.
- Signup with **no code** → `403`. With a **wrong code** → `403`. With a **correct code** → `201` (account created).
- Existing **login** flow unchanged for already-registered users.

## Not included (intentionally, can add later)
- Email-domain allowlist (`@university.edu` only).
- Admin UI / CLI to create accounts for `closed` mode.
- The optional Caddy front-door password (a separate, outer layer from Step 2).
