# Ollama (qwen3) spent every turn "thinking" and never called a tool

## Symptom

While building a T4-style agent-reliability benchmark for the **offline** provider
(Ollama / `qwen3:14b`), the model returned **no tool calls at all** on tool-requiring
prompts — it streamed prose instead. The first 4-case pilot scored **0/4** tool-selection,
and every turn was slow (**34–60 s**):

```
✗ [S1] ollama: (none)   (want search_materials)      33.98s
✗ [S4] ollama: (none)   (want generate_vasp_inputs)  55.07s
✗ [M1] ollama: (none)   (want search_materials)      59.83s
✗ [A1] ollama: generate_vasp_inputs (want NONE)      27.95s
```

On the desktop app this means the offline chat "works" (it replies) but the **agent is a
no-op** — it can't drive any of the 23 tools when there is no Gemini key / no network.

## Root cause (why the bug came)

`qwen3` is a **reasoning model** — thinking is **on by default**. With the 23-tool schema
present, the model spent the entire turn emitting a long `<think>…</think>` chain and then
answered in natural language, never reaching the function-call. The `OllamaProvider.run()`
chat call did not disable thinking, so the tool-calling turn was drowned by reasoning tokens
(hence both the empty tool list *and* the 34–60 s latencies).

This is the **same failure mode** we already hit and fixed on Gemini — gemini-2.5-flash also
ships with thinking on and returned empty tool-less turns until we set a 0 thinking budget
(`issue`/postmortem: `docs/issues_solve/2026-06-25-gemini-thinking-empty-tool-calls.md`).
The offline provider had the identical latent bug; it only surfaced once we benchmarked it.

## How we fixed it

Pass `think=False` to the Ollama chat call so `qwen3` skips chain-of-thought and goes
straight to tool-calling (Ollama's `think` flag is the native equivalent of Gemini's 0
thinking budget):

```python
async for chunk in await client.chat(
    model=self.model,
    messages=_to_messages(messages),
    tools=_to_tools(tools) if tools else None,
    think=False,          # <-- disable qwen3 chain-of-thought
    stream=True,
):
```

Effect on the same 4-case pilot: the model **now calls tools** and latency dropped ~4×
(8–14 s vs 34–60 s). This fix alone lifted the full T4 suite from **0% → 41%**. The
*remaining* gap turned out **not** to be model quality but a second config bug — Ollama was
silently truncating the 23-tool schema at its ~4k default context window; fixing that
(`num_ctx=16384`) took the offline model to **92%**. See the follow-on postmortem
`issue-ollama-context-window-truncation.md` and the benchmark
`docs/validation_results/T4_agent_reliability_ollama.md`. Gemini (100%) stays the
recommended default; Ollama is now a genuinely capable offline fallback.

## Files changed

- `backend/app/agent/providers/ollama.py` — added `think=False` to the streamed `chat()` call.
- `backend/scripts/validation/t4_agent_reliability.py` — made the harness benchmark the
  keyless Ollama provider (no `KEY_ENV` entry) and added a `--tag` suffix so an Ollama run
  writes `T4_agent_reliability_ollama.*` instead of overwriting the canonical Gemini report.

## How to verify

```bash
cd backend
MODEL_PROVIDER=ollama ../venv/bin/python scripts/validation/t4_agent_reliability.py \
    --providers ollama --ids S1,S4,M1,A1 --tag ollama
```

Before the fix: `(none)` first tools, 34–60 s/turn. After: tools are called, ~8–14 s/turn.
(Requires the Ollama server running on `localhost:11434` with `qwen3:14b` pulled.)

## Lesson

**Reasoning-model defaults are a tool-calling trap.** Any "thinking"-capable model
(Gemini, qwen3, and future ones) will happily burn the whole turn reasoning and return no
function call unless thinking is explicitly disabled for the tool-calling path. When adding
a new `LLMProvider`, the checklist must include: *does this model have thinking on by
default, and is it turned off in the agent path?* Benchmarking each provider (not just the
hosted default) is what surfaced this — the offline path had shipped silently broken.
