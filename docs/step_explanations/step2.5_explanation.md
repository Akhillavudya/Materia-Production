# Step 2.5 — BYOK Key Management (Beginner Explanation)

> **Status:** ✅ Implemented & verified live (key save/list/delete + encryption + no-key prompt
> all tested through the running stack).
> This doc explains *what* we built, *why*, and *file-by-file* — with analogies.

---

## 1. One-sentence summary

We gave Materia a real **Settings panel** where each user pastes their **own** API keys (Groq /
Gemini for chat, Materials Project for search), wired the backend so those keys are actually
*loaded* and *encrypted*, and made a missing key show a friendly *"add your key"* prompt instead of
a cryptic *"something went wrong."*

---

## 2. Why this step suddenly appeared (the bug you found)

You signed up, typed *"search for silicon,"* and got **"something went wrong."** Investigating
revealed three real gaps:

1. **No ignition slot.** The app had no Settings page to paste a key at all — only a half-built
   inline prompt that the backend **never actually triggered**.
2. **A disconnected wire.** The backend's key loader (`KEY_ENV_MAP`) knew about `mp`, `gemini`,
   `openai`, `anthropic` — but **not `groq`**, even though Groq is the *default* chat provider. So
   a pasted Groq key would be saved and then **never used**.
3. **A silent failure.** With no LLM key (and no local Ollama in the container), the agent failed
   *before* it could even prompt you — so you got a generic error with no way forward.

**Analogy:** the car's key wiring existed under the dash, but there was **no ignition slot** to put
a key in — and one wire (Groq) wasn't even connected. This step connects the wire and mounts a
visible ignition + a labeled key drawer.

---

## 3. Core concept: "BYOK" (Bring Your Own Key)

Materia doesn't pay for everyone's AI. Each user supplies their **own** free API key:
- **Groq** *or* **Gemini** → needed to **chat** (the LLM brain).
- **Materials Project (MP)** → needed to **search** for materials by formula/properties.

A key is like a **personal membership card** to an outside service. Materia stores it in a **safe**
(encrypted with the Step 1 `FIELD_ENCRYPTION_KEY`) and swipes it on your behalf when you chat or
search. It never shows the key back to you, and never stores it as plain text.

---

## 4. File-by-file: what changed & why

### Backend

| File | What changed | Why / analogy |
|---|---|---|
| `services/key_service.py` | Added `"groq": "GROQ_API_KEY"` to `KEY_ENV_MAP` | **Connect the missing wire** — now a saved Groq key is loaded into the agent |
| `repositories/api_key_repository.py` | New `delete()` | Lets a user **remove** a key |
| `api/keys.py` | New `GET /keys` (list) + `DELETE /keys/{service}` | The settings drawer needs to **show which keys are set** and **remove** them. List returns only `exists` flags — **never the key value** |
| `api/chat.py` | If no LLM key (in production), emit a friendly message + `[NEED_API_KEY:groq]` instead of failing | Turns *"something went wrong"* into *"add your key to start chatting"* |

### Frontend

| File | What changed | Why / analogy |
|---|---|---|
| `features/settings/SettingsPanel.jsx` *(new)* | The **⚙️ Settings drawer** — 3 slots (Groq / Gemini / MP), each with paste / replace / remove + a "✓ set / not set" badge and a link to get a free key | The **visible ignition + key drawer** |
| `features/sessions/Sidebar.jsx` | Added a **⚙️ button** (bottom-left, next to sign-out) | The **button on the dashboard** that opens the drawer |
| `App.jsx` | State + mounts the panel as a modal | Wires the button to the drawer |
| `api/keys.js` | Added `listKeys()` and `deleteKey()` | The frontend's phone line to the new endpoints |
| `features/chat/ApiKeyForm.jsx` | Added friendly `groq` + `gemini` entries (it only knew `mp`) | So the **inline** prompt (when a key is missing mid-chat) is also clear |

---

## 5. How a key flows through the system (the happy path)

```
You paste a Groq key in ⚙️ Settings
        │  POST /api/keys {service:"groq", key_value:"gsk_..."}
        ▼
Backend ENCRYPTS it (Fernet)  ──►  stored in Postgres as "gAAAAA…"  (never plain text)
        │
You send a chat message
        │  POST /api/chat
        ▼
Backend loads YOUR keys → decrypts → sets GROQ_API_KEY in the environment for this request
        ▼
Agent calls Groq with your key → replies → streams back to your browser
```

---

## 6. What we verified live (on the running stack)

| Check | Result |
|---|---|
| Chat with **no** LLM key | ✅ friendly nudge + `[NEED_API_KEY:groq]` (no generic error) |
| `GET /api/keys` | ✅ lists all slots with `exists` flags |
| Save Groq key → list | ✅ `groq: true` |
| Stored **encrypted** in DB | ✅ `gAAAAA…` ciphertext, **not** the raw key |
| `DELETE /api/keys/groq` → list | ✅ `groq: false` |

*(This also re-confirmed Step 1's encryption is working in production mode.)*

---

## 7. How to use it (you, in the browser)

1. Hard-refresh **http://localhost:8080** (Ctrl+Shift+R — the JS changed).
2. Click **⚙️ Settings** (bottom-left).
3. Paste your free **Groq** key (console.groq.com) → it flips to **✓ set**.
4. Add your **Materials Project** key too (for search).
5. Chat — *"search for silicon"* now works.

---

## 8. Known follow-ups (intentionally deferred)

- The **inline mid-chat prompt** currently fires for a missing *LLM* key. Making the **MP search**
  tool emit `[NEED_API_KEY:mp]` mid-chat is a small future enhancement — for now you add the MP key
  proactively in Settings.
- A **first-run banner** ("add a key to start") could be added later; the Settings badge already
  shows what's missing.

---

## 9. Where this fits

**Step 2.5 of the plan** — inserted because without it *no one could actually use the chatbot*. It
sits between Step 2 (containers) and Step 3 (Postgres hardening). Golden rule still holds: the 8 new
simulation tools come only **after Step 4** (overload guardrails).

**Commit:** `feat: BYOK key management — settings panel, list/delete key API, groq wiring, no-key prompt`
