# Step 1 — Secrets & "Bring Your Own Key" Encryption (Beginner Explanation)

> **Status:** ✅ Done and committed (`eb19538`).
> This document explains, in plain language, *what* we changed, *why*, and *what each file
> does* — with analogies — so you understand it even without the technical background.

---

## 1. The one-sentence summary

We made Materia **refuse to start in production unless its secrets are strong**, and we made
sure that when a user pastes their own API key, it gets **locked in a safe (encrypted)**
instead of left in an unlocked drawer (plaintext).

---

## 2. The big analogy

Think of Materia as a **lab building**.

- The **master key** (`JWT_SECRET_KEY`) is what proves "this person really logged in." If the
  master key is weak — ours was literally the word *"my-super-secret-key"* — anyone can copy it
  and walk in pretending to be any user.
- The **safe** (`FIELD_ENCRYPTION_KEY`) is where we store the valuable keys your PhD students
  hand us (their Groq/Gemini API keys). Before this step, if the safe's combination wasn't set,
  we just **tossed their keys in an open drawer** — readable by anyone who opened the database.

Step 1 does two things:
1. **Forces a strong master key and a working safe before the building opens** — *in production*.
2. **Never pretends to lock the safe.** If the safe isn't set up in production, the building
   simply won't open, instead of quietly storing keys in the open.

And crucially: **none of this gets in your way while developing on your laptop.** Dev mode stays
relaxed; only `ENV=production` turns on the strict rules.

---

## 3. Two words you'll see everywhere

| Word | Plain meaning | Analogy |
|------|---------------|---------|
| **Secret** | A long random password the app uses internally (not a user password) | The master key to the building |
| **Encryption** | Scrambling data so only someone with the key can read it | Locking something in a safe |
| **Fernet** | The specific "safe" technology we use (a Python encryption library) | The brand of safe |
| **Fail-fast** | Crash *immediately at startup* with a clear message, instead of running in a broken/unsafe state | A car that won't start if the brakes are missing — better than failing on the highway |
| **`ENV`** | A setting that says "is this my laptop (development) or the real server (production)?" | A sign on the door: "Practice Room" vs "Live Lab" |

---

## 4. File-by-file: what changed and why

### 📄 `backend/app/core/config.py` — "the settings sheet"
**Its job:** the single place that reads all startup settings from the environment.

**What we added:**
- A new `ENV` setting and an `is_production` flag, so the app knows whether it's on your laptop
  or the real server.
- Three small helpers:
  - a list of **banned weak secrets** (placeholders like `"my-super-secret-key"`, `"changeme"`),
  - `_is_strong_secret(...)` → "is this master key long enough and not a placeholder?",
  - `_valid_fernet(...)` → "is this safe combination actually a real, usable one?"
- A `_validate_production(...)` check that runs **only when `ENV=production`**. If the master key
  is weak or the safe key is missing/broken, it **raises a clear error and the app won't start**.

**Analogy:** This is the **building inspector**. On the real server, the inspector checks the
locks *before* opening day and refuses to open the doors if anything's unsafe — and it tells you
exactly what to fix, with the command to generate a proper key.

**Why it matters:** Before, a weak/missing secret would *silently* let the building run wide open.
Now it's impossible to deploy the unsafe version by accident.

---

### 📄 `backend/app/core/encryption.py` — "the safe"
**Its job:** lock (encrypt) and unlock (decrypt) the API keys users paste in.

**What we changed:**
- Added a `_require_fernet()` gate. In **production**, if the safe key isn't configured, it
  **raises an error** instead of returning the key as plaintext. In **dev**, it still allows the
  plaintext fallback so you can work without setting up encryption.
- Tightened the "unlock" code: it used to catch *every possible error* and silently hand back the
  raw text. We narrowed it to only the one expected case (a value that was saved as plaintext
  before encryption existed). Catching everything was hiding real bugs.

**Analogy:** The safe used to have a fake-lock mode — if you forgot the combination, it would just
swing open and *pretend* it was locked. Now, on the real server, the safe **refuses to fake it**.

**Why it matters:** Your students' API keys are real money to them. Leaking them would be the worst
thing the app could do. This guarantees they're encrypted in production.

---

### 📄 `backend/app/core/security.py` — "the ID-card printer"
**Its job:** create and verify login tokens (the proof that someone is logged in), and hash
passwords.

**What we changed:**
- If there's **no master key in development**, it now makes a **temporary one** (and logs a
  warning) so the app still boots on your laptop. The catch: those temporary logins reset every
  time you restart — totally fine for dev.
- In production this branch is never reached, because the inspector in `config.py` already stopped
  the app if the key was missing.

**Analogy:** On your home practice machine, if you didn't bring the master key, it prints a
**temporary guest badge** so you can keep working. The real lab never uses guest badges.

**Why it matters:** Convenience for you in dev, zero compromise in production.

---

### 📄 `backend/.env.example` — "the instruction card"
**Its job:** a template that shows which settings exist (the real `.env` with actual secrets is
never committed to git).

**What we changed:**
- Documented the new `ENV` setting.
- Marked `JWT_SECRET_KEY` and `FIELD_ENCRYPTION_KEY` as **required in production**, with the exact
  copy-paste commands to generate strong values:
  - Master key → `python -c "import secrets; print(secrets.token_urlsafe(48))"`
  - Safe key → `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**Analogy:** The laminated card taped inside the door telling future-you exactly which keys to cut
and how.

---

### 📄 `backend/app/services/key_service.py` — *no change needed*
This file loads a user's saved keys and was already routing through the safe (`decrypt_value`). So
it **automatically inherited** the new protection without any edits. (Listed only so you know we
checked it.)

---

## 5. How we proved it works (the tests we ran)

| Test | What we checked | Result |
|------|-----------------|--------|
| Dev boot | App starts on a laptop with no special keys set | ✅ Boots fine |
| Round-trip | With the safe key set, lock a value then unlock it | ✅ Scrambled, then perfectly recovered |
| Prod fail-fast | `ENV=production` with weak/missing secrets | ✅ Refuses to start, prints exactly what to fix |
| Prod weak placeholder | `ENV=production` with the old `my-super-secret-key` | ✅ Caught and rejected |
| Prod success | `ENV=production` with strong keys | ✅ Starts normally |
| No broken imports | The whole app still loads | ✅ Clean |

---

## 6. One thing to remember for deployment day

When you set up the Oracle server later, you'll generate **one** `JWT_SECRET_KEY` and **one**
`FIELD_ENCRYPTION_KEY` and put them in the server's private `.env`.

⚠️ **Treat the `FIELD_ENCRYPTION_KEY` like a safe combination you can never change.** If you change
it after users have saved API keys, those saved keys become unreadable (the safe won't open with a
new combination). For a brand-new deployment this is a non-issue — just generate it once and keep
it safe.

---

## 7. Where this fits in the bigger plan

This was **Step 1 of 10** in `docs/PRODUCTION_READINESS_PLAN.md`. It's the first "lock on the
door." Next steps build on it (real database, containerized deploy, overload guardrails, lab-only
access, and so on) — and remember the golden rule: **the 8 new simulation tools come only after
Step 4 (the overload guardrails) is in place.**

**Commit:** `eb19538 — backend: fail-fast on weak production secrets, never store API keys as plaintext`
