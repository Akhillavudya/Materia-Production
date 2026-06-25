# Step 6 — Global error handling (don't leak your internals)

## The one-sentence purpose
When something crashes, the **user** sees a tidy "something went wrong" while the
**real** technical detail (file paths, stack traces, secrets in error text) goes
*only* to your private server logs.

## The analogy
Imagine a vending machine that jams. Today it prints its **entire internal wiring
diagram** onto the customer's receipt — confusing for them, and a gift to anyone
trying to break in (it reveals folder paths, library versions, sometimes secrets).
Step 6 puts a **front-desk clerk** in front of the machine: on any jam the clerk
hands the customer a clean note — *"Sorry, error #1340a5d8, we're on it"* — and
quietly writes the messy details in the **back-office logbook** only you can read.

That short code (`1340a5d8`) is the **request id**. When a student says "it broke!",
you ask for the id, grep your logs for it, and jump straight to the exact failure.

## Why before the new tools
You're about to add 8 heavier tools (phonons, NEB, SQS…). Complex tools fail in
complex new ways. Build the *one* clean failure funnel **now**, so all 8 new
failure sources are caught privately instead of spraying internals at users.

## 📁 Files that changed & why

| File | What & why |
|---|---|
| `app/core/logging.py` | Rebuilt so **every log line carries a request id**. A `ContextVar` holds the id for the current request; a logging *filter* stamps it onto each record. Format is now `time | LEVEL | request_id | module | message`. Outside any request (startup, worker) the id is `-`. |
| `app/core/middleware.py` *(new)* | `RequestContextMiddleware` — the outermost net. It (1) mints/propagates a request id per request, (2) wraps the whole call in a `try/except` so **any** unhandled exception becomes a generic `500 {"detail":"Internal server error.","request_id":…}` with the full traceback logged privately, and (3) echoes the id on the `X-Request-ID` response header. *(This file also holds the Step 8 security-headers middleware.)* |
| `app/main.py` | Registers the middleware (correct outer→inner order), adds explicit handlers for `HTTPException` (keeps its real status/message — those are safe) and validation errors (422, safe — they describe the client's own bad input), and **hides `/docs`, `/redoc`, `/openapi.json` in production** so the full route map isn't published. |
| `app/api/chat.py` | The one spot that echoed a raw exception (`Could not read file: {e}` — could contain absolute paths) now logs the real reason privately and returns a flat `"Could not read file."`. |

## What "safe vs unsafe" means here
- **Safe to show the user:** `HTTPException` (you chose the message: "Not found",
  "File type not readable"), and `422` validation errors (they're about *their*
  input). These keep their detail + gain a `request_id`.
- **Never show the user:** anything *unexpected* (a `RuntimeError`, a DB driver
  error, a `KeyError` deep in the agent). These are funnelled to the generic 500.

## How it was verified
- Unhandled crash returns `500 {"detail":"Internal server error.","request_id":…}`
  and the secret string in the exception **did not** appear in the response body
  (it appeared only in the server log).
- `HTTPException`/422 still carry their real, safe messages **plus** a request id.
- In `ENV=production`, `/docs` and `/openapi.json` return **404**.
