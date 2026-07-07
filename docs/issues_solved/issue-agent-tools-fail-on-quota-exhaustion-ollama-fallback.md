# Issue: agent "doesn't recognise tools" once Gemini + Groq quotas are exhausted

## Symptom
After a lot of testing in one day, the chat agent started refusing tool calls with
confabulated messages, e.g.:

> "there is no `generate_poscar()` function available in the provided tools… the available
> functions focus on modifying existing structures (make_supercell, generate_sqs,
> compute_neb)…" — and then "the function `make_supercell()` is not available."

`search_materials` (the first, cheap call) still worked; the failure appeared on later steps.
"This never happened before."

## Root cause
Not a schema/tool bug — all 23 tools were registered and served correctly. The backend log
showed the real story:

```
Provider 'gemini' failed (429 … free_tier_requests, limit: 20/day, model gemini-2.5-flash); falling back to 'groq'.
Provider 'groq'   failed (429 … tokens per day (TPD): Limit 100000, Used ~99,400);          falling back to 'ollama'.
TypeError: generate_poscar() got an unexpected keyword argument 'formula'
TypeError: make_supercell() got an unexpected keyword argument 'poscar_name'
```

1. **Gemini** hit its free-tier **20-requests/day** cap → 429.
2. **Groq** hit its **100k-tokens/day** cap → 429.
3. Every turn then fell through to the local **Ollama `qwen3:14b`** fallback, which is a weak
   tool-caller: it invented wrong argument names (`formula`, `poscar_name`), the tool raised
   `TypeError`, and the model then hallucinated that the tools don't exist.

So the "tools not recognised" text was Ollama confabulating after both hosted quotas were gone.
It "never happened before" because both daily free quotas had never been fully drained in a
single day before.

Secondary finding: the operator had **3 spare Gemini keys + 4 spare Groq keys** in
`backend/.env` (`GEMINI_API_KEYS` / `GROQ_API_KEYS`), but the providers only ever read the
**single** `GEMINI_API_KEY` / `GROQ_API_KEY`. The plural lists were dead config, so the spare
quota was never used.

## How we fixed it
Added **multi-key rotation** so a provider tries the next key in its own pool on a 429 (or a
dead/invalid key) before dropping to the next provider:

- New `app/agent/providers/_keypool.py`: `build_pool()` (singular key first, then the plural
  list, de-duped), a round-robin cursor that remembers the last good key, `should_rotate()`
  (rotate on 429/quota/invalid-key, NOT on a genuine bad request), and `run_with_rotation()`
  which only rotates before any text has streamed.
- `gemini.py` / `groq.py`: build the pool from `GEMINI_API_KEY(+S)` / `GROQ_API_KEY(+S)` and
  run through `run_with_rotation`. Groq client now `max_retries=0` so a 429 rotates immediately
  instead of the SDK sleeping on an exhausted key.
- `config.py`: documented the `*_API_KEYS` env vars.

Effect: daily headroom goes from 1 key to **4 Gemini + 5 Groq keys** (incl. the singular),
i.e. ~4×20 Gemini requests and ~5×100k Groq tokens per day before Ollama is ever reached.

## Files changed
- `backend/app/agent/providers/_keypool.py` (new)
- `backend/app/agent/providers/gemini.py`
- `backend/app/agent/providers/groq.py`
- `backend/app/core/config.py`
- `backend/.env` already held the keys (not committed).

## How to verify
```
# unit: KEYA 429 → rotate to KEYB; next request starts at KEYB; bad-arg not rotated
# live: a real request logs "gemini key 1/4 unavailable (…); rotating to next key"
grep 'rotating to next key' <dev-backend log>
```
A real Gemini call now streams a normal answer instead of falling to Ollama, as long as any
key in the pool has quota.

## Lesson
When the agent suddenly "can't find" **core** tools and invents wrong arg names, read the
provider log first — it's almost always **quota exhaustion → weak local fallback**, not a code
regression. And if spare keys exist in config, make sure the code actually rotates through them;
a comma-separated `*_KEYS` var is worthless unless something reads it. All quotas are per
key/project/org, so extra keys only help if they belong to different projects/orgs.
