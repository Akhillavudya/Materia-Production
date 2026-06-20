# Materia — Production Readiness Plan

> **Status:** Planning / not yet implemented. This document explains *what* we will do,
> *why* we do it **before** adding the next batch of simulation tools, and the *purpose* of
> each step — in plain language with analogies.

---

## The mental model

Right now Materia is **a brilliant workshop you built in your garage**. The tools work, the
machines run, the science is real. "Going to production" does **not** mean adding more
machines — it means turning the garage into **a real shop that strangers can walk into
safely**, without breaking your equipment, stealing each other's belongings, or getting hurt.

You are about to install **7 new power tools**:

1. K-points accuracy
2. POSCAR vacancy defects
3. POSCAR substitution defects
4. POSCAR interstitial defects
5. Phonopy (phonons)
6. Mechanical properties
7. SQS generation
8. NEB calculations

**The core principle of this whole document:** *Do not bolt new power tools onto a shop that
has no locks, no fire exits, and one overloaded stove.* Every new tool is also a new way for a
stranger to overload your free server or trip over a missing safety rail. So we **harden the
shop first**, then add the tools onto a solid foundation.

---

## Your launch model (the assumptions behind this plan)

- **Fully open public signup** — anyone can create an account.
- **BYOK ("Bring Your Own Key")** — each user pastes their *own* Groq/Gemini API key. You, the
  student owner, do **not** pay for everyone's AI usage.
- **A desktop app is planned** so heavy simulations eventually run on each user's *own* CPU/GPU.
  Until that ships, simulations still run on your server.
- **Tentative host: Oracle Cloud "Always Free" Ampere A1** — ARM64, 4 CPU / 24 GB RAM,
  **no free GPU**. Budget ≈ zero.

> **One correction up front:** your `backend/.env` file is **not** in git and never was — it is
> correctly ignored. So there is **no leaked-secret-in-git emergency**. The real concern is that
> secrets are *weak* and that users' pasted keys are currently stored **unencrypted**. (See Step 1.)

---

# The 10 steps

Each step below answers three questions:
**Purpose** (what it achieves) · **Analogy** (so it sticks) · **Why before the new tools**.

---

## 🔴 P0 — Locks on the doors (must do before *anyone* walks in)

### Step 1 — Secrets & "Bring Your Own Key" encryption
**Purpose:** Use a strong, random master secret for logins, and **encrypt** every API key a
user pastes so it is never stored as plain readable text. Refuse to start if the safe is unlocked.

**Analogy:** Today your shop's master key is the word *"key"* written on a sticky note
(`JWT_SECRET_KEY = my-super-secret-key`). Anyone who guesses it can impersonate any customer.
Worse — when a customer hands you *their* valuable key, you drop it in an **unlocked drawer**
instead of a safe, because the safe's combination (`FIELD_ENCRYPTION_KEY`) was never set.

**Why before the new tools:** Every new tool runs through the agent, which uses the user's API
key. The more tools you add, the more often those keys are loaded and used. Securing how keys
are stored *must* come before you multiply how often they're used.

---

### Step 2 — Containerize & deploy (Docker on Oracle, with automatic HTTPS)
**Purpose:** Package the whole app into a portable container that runs identically anywhere, put
it behind a front-door proxy that gives you HTTPS (the 🔒 padlock) for free, and make the
frontend talk to your real server instead of `localhost`.

**Analogy:** Today the shop only runs on *your* workbench, set up *your* way. Docker puts the
entire shop — machines, wiring, plumbing — into a **shipping container** you can drop onto an
empty lot (the Oracle VM) and it just works. **Caddy** (the proxy) is the **front door with a
guard** that also hands you HTTPS automatically.

**Why before the new tools:** You want to test each new tool in the *real* production
environment, not just on your laptop. Setting up the container now means every future tool gets
verified in the same place users will actually run it — no "it worked on my machine" surprises.

---

### Step 3 — Real database (PostgreSQL), no silent fallback
**Purpose:** Use Postgres in production and **stop the app from silently falling back to SQLite**
if the database isn't configured.

**Analogy:** SQLite is a **single paper notebook** — fine for one writer. But production has two
workers (the web API *and* the simulation worker) scribbling at once → smudges, torn pages, lost
data. Postgres is a **proper filing system with a librarian** who safely coordinates many
writers. The hidden danger today: forget to plug in Postgres and the app *quietly* uses the paper
notebook. We make it **shout and stop** instead.

**Why before the new tools:** Each new simulation tool writes job records to the database. More
tools = more concurrent writes. A database that can't handle concurrency will corrupt exactly
when you're busiest. Fix the foundation before piling weight on it.

---

### Step 4 — Protect the free server from overload ⚠️ *(the most important step)*
**Purpose:** Cap how big and how many simulations a user can run, rate-limit requests, limit file
storage, auto-clean old results, and require users to bring their own AI key.

**Analogy:** Your Oracle free machine is a **small kitchen with one stove**. Right now any walk-in
can order *"simulate 1 billion steps on a 10,000-atom crystal"* — like one person ordering 10,000
pizzas and jamming the only oven for days while everyone else starves. They can also dump files
until the pantry (disk) overflows. The fix is a **menu with sensible limits**: max size per
order, a few orders per customer at a time, and "bring your own AI key" so *you* never get the
bill.

**Why before the new tools — this is the critical one:** Every new tool (phonons, NEB, SQS…) is
**heavier** than the current ones and is a **new way to overload the single free stove**. NEB runs
many images; phonons run many displaced structures; SQS searches many configurations. If you add
these *before* the size caps exist, the very first curious user can take your server down. **Caps
first, tools second — non-negotiable.**

---

### Step 5 — Abuse prevention for open signup
**Purpose:** Verify email addresses and throttle signups so bots can't flood you with fake
accounts.

**Analogy:** Open signup is like **leaving free membership cards on the sidewalk** — bots grab
thousands. Email verification asks *"prove this is a real mailbox you own"* before you hand over a
card, filtering out the junk that would otherwise clog your filing cabinet.

**Why before the new tools:** Fake accounts + heavy new tools = amplified abuse. Stop the fake
accounts at the door before you give every account access to more expensive machines.

---

## 🟡 P1 — Safety rails (strongly recommended before opening wide)

### Step 6 — Global error handling (don't leak your internals)
**Purpose:** When something breaks, show users a clean "something went wrong" while the real
technical details go only to your private logs.

**Analogy:** When a machine jams today, it sometimes **prints its entire internal blueprint** onto
the customer's receipt (raw errors with file paths). That's confusing *and* a security leak — it
tells an attacker how your shop is wired.

**Why before the new tools:** New, complex tools fail in new, complex ways. You want those
failures captured cleanly and privately *before* you add seven more sources of them.

---

### Step 7 — Health checks & knowing when it's down
**Purpose:** Add a heartbeat endpoint so a free uptime monitor can alert you the moment the server
dies, plus basic error reporting.

**Analogy:** Right now you have **no smoke detector**. If the shop catches fire at 3 a.m., you find
out when angry users tweet at you. A `/health` endpoint is a heartbeat monitor that texts you the
instant it flatlines.

**Why before the new tools:** Heavier tools make crashes *more* likely. You need to hear about a
crash from a monitor, not from a frustrated user.

---

### Step 8 — Lock down CORS & add security headers
**Purpose:** Allow only *your* website to talk to the backend (today it allows *any* site), and add
the standard browser-safety headers.

**Analogy:** CORS today says *"any website on Earth may reach into my shop and use the cash
register."* We narrow it to *"only my own website."* Security headers are the **"fire exit / no
smoking" signs** every legitimate shop posts.

**Why before the new tools:** This is a one-time hardening of the front door. Do it once, now, and
every future tool inherits the protection automatically.

---

## 🟢 P2 — Do alongside launch (and *definitely* before the new tools land)

### Step 9 — A minimum safety net of tests + automated checks (CI)
**Purpose:** Write a small set of automated tests for the critical paths, and have a robot run them
on every change.

**Analogy:** You're about to install **7 new power tools**. Without tests, adding one is like
**renovating with the lights off** — you won't notice you broke the plumbing until water's on the
floor. Tests are **tripwires** that beep the instant something that used to work stops working. CI
is the robot inspector that trips those wires automatically before the change reaches users.

**Why before the new tools — this one is huge for you:** You said you'll add the 7 tools **one by
one**. Each new tool risks silently breaking an existing one. A test net means: add tool → run
tests → if something old breaks, you find out in seconds, not from a user weeks later. This is what
makes adding 7 tools *safe* instead of *scary*.

---

### Step 10 — Backups, model files, and a deploy runbook
**Purpose:** Back up the database nightly, fetch the large AI model files with a script (instead of
storing them in git), and write down how to deploy the whole thing.

**Analogy:** Your one free VM is a **single hard drive holding your life's work** — if it dies,
everything's gone. Backups are **photocopies stored in another building**. The 398 MB AI models are
too heavy for the toolbox, so we add a **"go fetch them" script** instead. The runbook is the
**instruction manual** so future-you can rebuild the shop from scratch.

**Why before the new tools:** Some new tools may need *additional* model files or data. Establishing
the "fetch models out-of-band" pattern now means each new tool just plugs into an existing,
documented system instead of bloating your repository.

---

# The big-picture payoff: your desktop-app pivot 🎯

Here's the encouraging part. Your plan for a **desktop app where each user runs simulations on
their own computer** is genuinely smart. Once it exists, **Step 4's "one stove, 10,000 pizzas"
problem mostly disappears** — every customer brings their own kitchen. Your Oracle server then
shrinks to just a **front desk**: logins, chat orchestration, and light file storage. That is
nearly free to run forever.

So this entire plan does double duty: it makes the *web* launch safe **and** builds the lean,
compute-light "front desk" that the desktop future depends on.

---

# Suggested order of work

```
Step 1  →  Step 3  →  Step 2  →  Step 4  →  Step 5     (P0: locks & overload protection)
Step 6  →  Step 7  →  Step 8                            (P1: safety rails)
Step 9  →  Step 10                                      (P2: test net & backups)
─────────────────────────────────────────────────────
THEN: add the 7 new simulation tools, one by one,
      each landing on a hardened, tested foundation.
```

**The single most important rule:** do **not** add the new simulation tools until **Step 4
(size caps & quotas)** is in place — otherwise each new, heavier tool becomes a new way for the
first curious stranger to take down your free server.
