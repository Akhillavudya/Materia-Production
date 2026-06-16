# Making the Agent Reliable: Groq Primary + Fallback Chain

**Date:** 2026-06-15
**Commit:** `3693fee` — *agent: add Groq provider as primary with Groq→Gemini→Ollama fallback*

This document explains, in plain language, a problem that showed up while using
the Materia chat agent and exactly how it was fixed. It doubles as a learning
note, so it walks through the *why* as much as the *what*.

---

## 1. The problem (what you saw)

While chatting with the assistant, three bad things happened:

1. **A wall of red error text in the chat.** Instead of an answer, the chat
   showed Google's raw error: `429 Too Many Requests ... You exceeded your
   current quota ... GenerateRequestsPerDayPerProjectPerModel-FreeTier ...
   gemini-2.5-flash`.

2. **Empty reply bubbles.** You'd send a message and get a blank agent bubble
   (just the spinner icon, no text). Sometimes you had to send the same thing
   several times before a real answer came.

3. **It felt slower / flakier than before**, when local Ollama was being used.

### Why it happened (the root cause)

The agent doesn't make **one** call to the language model per question — it runs
a small **loop**. For example, *"make a POSCAR for NaCl"* becomes roughly:

```
You ask  →  model calls search_materials  →  model reads the result
         →  model calls generate_poscar    →  model writes the final answer
```

That's **4 separate calls** to the model for one question.

The model was **Gemini's free tier** (`gemini-2.5-flash`), which allows only
about **10 requests per minute** and **~250 per day**. A handful of multi-step
questions burns through that budget, and then every call comes back as a
`429 Too Many Requests` error. That's a capacity problem, not a code bug.

On top of that, there were two smaller code weaknesses that turned a rate-limit
into *ugly* behavior instead of *graceful* behavior:

- **The fallback had a hole.** The code was *supposed* to fall back to local
  Ollama when Gemini failed — but only if the failure happened *before* any text
  had streamed to you. `gemini-2.5-flash` is a "thinking" model: it often emits
  one tiny fragment, *then* hits the 429. Because a fragment had already
  streamed, the code thought "too late to switch" and showed you the raw error.

- **Empty turns became empty bubbles.** When a throttled model returned nothing
  (no text, no tool call), the loop simply stopped and streamed nothing — the
  blank bubble.

---

## 2. The decision

We discussed options for a *free* model with good tool-calling and a more
generous limit. The honest finding: **there is no truly "unlimited" free hosted
API** — every free tier is capped somehow. But some are far more generous than
Gemini's. The best fit was **Groq**:

- Free tier, no credit card.
- Very fast.
- Strong **native tool-calling** (Llama 3.3 70B, Qwen, …).
- OpenAI-compatible API, so it slots into the existing code with minimal effort.

**Chosen strategy:** make **Groq the primary** model, and keep **Gemini and the
local Ollama as automatic backups**. So the order is:

```
Groq   →   Gemini   →   Ollama (local)
(primary)  (backup)     (last-resort, always available offline)
```

If Groq is busy, the request quietly slides to Gemini; if that fails too, to
your local Ollama. You only ever see a clean answer — or, in the worst case, a
short polite "try again" message.

---

## 3. What was actually changed

The codebase already had a clean design: the agent talks to an abstract
`LLMProvider`, so a new backend is a "drop-in" part. That made this a small,
contained change.

| File | What changed | Why |
|---|---|---|
| `backend/app/agent/providers/groq.py` *(new)* | A `GroqProvider` that streams tokens and assembles tool calls from Groq. | The new primary backend. |
| `backend/app/core/config.py` | Added `groq_api_key` / `groq_model`; auto-detect order is now **groq → gemini → ollama**. | So Groq is picked up automatically when a key is present. |
| `backend/app/agent/llm.py` | Single fallback replaced by an ordered **chain**, plus the resilience fixes below. | The heart of the fix. |
| `backend/app/agent/graph.py` | Friendly error messages + a guard so an empty model turn never becomes a blank bubble. | Better user experience on failures. |
| `backend/requirements.txt` | Added `groq`. | Dependency. |

### The three resilience fixes (the important part)

1. **Closed the fallback hole with a "buffer window."**
   Streamed text is now held back until about **24 characters** have arrived.
   If a backend dies after only a stray fragment, *nothing has reached you yet*,
   so the code can cleanly switch to the next backend with no duplicated text.
   Healthy answers cross 24 characters almost instantly, so normal streaming
   feels unchanged.

2. **Empty turns now fall through the chain.**
   If a backend returns nothing useful, the next backend is tried instead of
   showing a blank bubble.

3. **No more raw error dumps.**
   Google's verbose 429 JSON never reaches the chat. If *every* backend fails,
   you get a short, friendly message; the full error is logged on the server for
   debugging only.

---

## 4. How it was verified

The fallback logic was tested with stand-in "fake" providers covering the four
key situations — all passed:

| Scenario | Expected | Result |
|---|---|---|
| Primary returns 429 | Falls to next backend, streams clean answer | ✅ |
| Primary returns an empty turn | Falls to next backend | ✅ |
| Primary streams a stray token then 429 | Buffered → clean fallback, **no duplicated text** | ✅ |
| All backends fail | One friendly error message (no raw dump) | ✅ |

The full agent package also imports cleanly, and the Groq message/tool
translation produces correct OpenAI-format payloads.

---

## 5. How to turn it on

The code is live, but Groq isn't *used* until a key is configured. In
`backend/.env`:

```env
MODEL_PROVIDER=groq
GROQ_API_KEY=gsk_...          # free, no card, at https://console.groq.com/keys
# optional — this is already the default:
GROQ_MODEL=llama-3.3-70b-versatile
```

> Note: `MODEL_PROVIDER` was previously set to `gemini`, which *forces* Gemini.
> It must be changed to `groq` (or removed, so auto-detect picks Groq once the
> key is present).

No code change is needed to switch backends later — it's purely a config flip,
because everything sits behind the `LLMProvider` interface.

---

## 6. One-paragraph summary

The agent makes several model calls per question, which quickly exhausted
Gemini's small free quota and produced raw `429` errors and blank bubbles. We
added **Groq** (a fast, more generous free model with strong tool-calling) as the
primary, with **Gemini and local Ollama as automatic fallbacks**, and hardened
the fallback logic so a busy or failing model is replaced invisibly — the user
sees a clean answer or, at worst, a polite "try again."
