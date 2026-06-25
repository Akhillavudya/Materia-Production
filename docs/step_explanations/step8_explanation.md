# Step 8 — Lock down CORS & add security headers

## The one-sentence purpose
Make sure **only your own website** is allowed to call the backend (today it
already reads an allowlist, but we harden it), and stamp the standard
**browser-safety headers** on every response.

## Two ideas, kept separate

### 1. CORS — "whose website may use my cash register?"
**CORS** (Cross-Origin Resource Sharing) is the browser rule that decides which
*other* websites' JavaScript is allowed to call your API. If it says "anyone"
(`*`), then a malicious `evil.com` a logged-in student visits could quietly fire
requests at Materia using their session.

Materia already restricts this to `settings.allowed_origins` (driven by the
`ALLOWED_ORIGINS` env, set from `SITE_URL` in compose) — good. Step 8 **adds a
boot-time guard**: in production, if `ALLOWED_ORIGINS` is empty or contains `*`,
the app **refuses to start**. (A wildcard is also outright incompatible with
`allow_credentials=True`, so this catches a real footgun.)

### 2. Security headers — "the fire-exit / no-smoking signs"
Small headers every legit site posts so the browser enforces extra safety:

| Header | Plain meaning |
|---|---|
| `X-Content-Type-Options: nosniff` | "Don't guess file types" — stops a `.txt` being run as a script. |
| `X-Frame-Options: DENY` | "Don't let another site embed me in an invisible iframe" — blocks click-jacking. |
| `Referrer-Policy: strict-origin-when-cross-origin` | Don't leak full URLs (which can carry ids) to other sites. |
| `Permissions-Policy: geolocation=(), microphone=(), camera=()` | "This app never needs your camera/mic/location" — pre-emptively denies them. |
| `Strict-Transport-Security` *(prod only)* | "Always use HTTPS for the next year." Only sent in production, where Caddy actually terminates HTTPS — sending it in plain-HTTP dev would wrongly pin `localhost` to https. |

## Why before the new tools
This is a **one-time front-door hardening**. Do it once now and **every** future
tool's endpoint inherits the protection automatically — no per-tool work.

## 📁 Files that changed & why

| File | What & why |
|---|---|
| `app/core/middleware.py` | `SecurityHeadersMiddleware` adds the headers above to every response (`setdefault`, so it never clobbers a header a route set deliberately). HSTS is gated on `settings.is_production`. |
| `app/main.py` | Registers `SecurityHeadersMiddleware` just inside the request-context net. CORS stays restricted to `settings.allowed_origins`. |
| `app/core/config.py` | Production guard: reject empty / wildcard `ALLOWED_ORIGINS` at boot. |
| `frontend/Caddyfile` | The front door that terminates **HTTPS** — which is what makes HSTS and secure cookies meaningful. (HTTPS is auto-provisioned via Let's Encrypt when `SITE_ADDRESS` is a real domain.) |

## How it was verified
- Every response (incl. `/health`) carries `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and `X-Request-ID`.
- `Strict-Transport-Security` is **absent** in dev and **present**
  (`max-age=31536000; includeSubDomains`) when `ENV=production`.
- With `ENV=production` and `ALLOWED_ORIGINS=*`, the app **refuses to boot** with a
  clear message naming `ALLOWED_ORIGINS`.
