# Ollama silently truncated the tool list (4k default context) → offline agent picked wrong tools

## Symptom

After fixing the qwen3 "thinking" no-op (see
`issue-ollama-qwen3-thinking-no-toolcalls.md`), the offline agent *called* tools but chose
**badly** — 16/39 (41%) on the T4 suite. Two signatures stood out:

- `search_materials` (the **first** tool in the schema list) **never fired once** (0/7). On
  "Find materials with the formula NaCl" qwen3 replied, in prose:
  *"None of the provided functions can be used to find materials with the formula NaCl."*
- It **over-selected the last tools** in the list — `generate_sqs` (7×) and `compute_neb`
  (6×) — for unrelated prompts (MD → `compute_neb`, "just a POSCAR" → `generate_sqs`), even
  at `temperature=0` (so it was deterministic, not random).

"Front of the list invisible, end of the list over-picked" is the fingerprint of a prompt
being **cut off**, not of a weak model.

## Root cause (why the bug came)

**Ollama's default context window (`num_ctx`) is ~4096 tokens.** The agent request is far
bigger: `SYSTEM_PROMPT` (~2k) + **23 tool schemas (~8.6k)** + the offline routing primer
≈ **11k tokens**. Ollama silently truncates anything past `num_ctx`, so qwen3 received only
a fraction of the tool definitions. It literally could not see `search_materials` and the
other early tools, so it "reasoned" that no matching function existed and fell back to
whatever tools survived near the end of the window.

This is invisible because Ollama neither errors nor warns on truncation — the request
succeeds, just with a chopped prompt. (Contrast Groq, which *rejected* the same ~10.6k-token
payload with an HTTP 413 — see `T4_agent_reliability.md`. Ollama fails silently instead.)

## How we fixed it

Set an explicit large context on the chat call so the whole payload fits:

```python
options={"temperature": 0.0, "num_ctx": 16384}
```

`qwen3:14b` supports 32k+ context, so 16384 comfortably holds the ~11k-token payload with
headroom. Effect on the T4 suite:

| Config | Tool-selection | Arg accuracy | Latency |
|--------|----------------|--------------|---------|
| default `num_ctx` (~4k) | 16/39 (41%) | 33% | 12.7 s |
| `num_ctx=16384` | **36/39 (92%)** | **100%** | **2.4 s** |

`search_materials` went from 0/7 → correct on every case, and the `generate_sqs`/`compute_neb`
anchoring disappeared. Latency also dropped ~5× (the truncated model had been flailing).

## Files changed

- `backend/app/agent/providers/ollama.py` — added `num_ctx=16384` (and `temperature=0`) to
  the streamed `chat()` `options`, plus a compact offline tool-routing primer injected
  **only** by this provider (`_with_offline_primer`), so the shared `SYSTEM_PROMPT` that
  gives Gemini 100% is never touched.

## How to verify

```bash
cd backend
MODEL_PROVIDER=ollama ../venv/bin/python scripts/validation/t4_agent_reliability.py \
    --providers ollama --tag ollama          # → 36/39 (92%)
```

Quick single-case check: "Find materials with the formula NaCl." must now call
`search_materials({"formula": "NaCl"})` instead of answering in prose.

## Lesson

**On Ollama, always set `num_ctx` to fit your prompt — the default is small and truncation
is silent.** Any agent with a non-trivial system prompt + many tool schemas will blow past
4k tokens and get quietly chopped, and the failure *looks like* a dumb model making bad
tool choices rather than a config problem. When a local model "can't see" tools that are
demonstrably in the request, suspect context truncation before blaming the model. A
provider that hard-errors on oversize input (Groq's 413) is easier to debug than one that
silently truncates (Ollama).
