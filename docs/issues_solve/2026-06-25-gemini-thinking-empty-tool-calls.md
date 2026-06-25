# Gemini returns empty turns (no text, no tool call) → dead fallback provider

**Date:** 2026-06-25
**Area:** agent LLM provider (`app/agent/providers/gemini.py`), surfaced by T4 validation

## Symptom
While building the T4 agent-reliability benchmark, every Gemini call came back
empty: `LLMResult(text="", tool_calls=[])`. No exception, no 429 — just nothing.
Groq on the identical prompts + schema returned correct tool calls. A minimal
Gemini call (`"Say hello"`, no tools) worked fine and returned `"hello"`, so the
key and client were healthy.

## Root cause
`gemini-2.5-flash` has **"thinking" enabled by default**. With our tool set (23
function declarations) and the long agent system prompt in the request, the model
spent the **entire** response budget on internal thinking and finished with:

```
finish_reason = STOP
content.parts = None        # no text part, no function_call part
```

i.e. a well-formed but empty turn. Reproduced exactly:

- full config (tools + system_instruction, thinking ON, default) → `parts=None`
- same config + `thinking_config=ThinkingConfig(thinking_budget=0)` → returns
  `function_call(name="search_materials", args={"formula": "NaCl"})` ✓

Because Gemini is the **fallback** provider in the production chain
(groq → gemini → ollama), and `FallbackProvider` treats an empty turn as a failed
backend, Gemini was *silently a no-op*: it always returned empty and fell straight
through to Ollama. When Gemini was the **primary** provider, tool calling was
broken outright (the agent loop saw no tool calls and just emitted the empty/short
text answer).

## Fix
Disable thinking in the provider's `GenerateContentConfig`:

```python
thinking_config=types.ThinkingConfig(thinking_budget=0),
```

The model then emits the function call / answer directly. Side benefit: lower
latency (no thinking phase), which is what you want for an interactive
tool-calling chat agent.

## Verification
- Direct probe: `gemini-2.5-flash` with the production system prompt + 23 tools now
  returns the correct `search_materials(formula="NaCl")` instead of an empty turn.
- T4 benchmark: Gemini went from 0/N (all empty) to **19/19 = 100%** tool-selection
  with all key args correct on the cases that ran before the per-minute quota reset
  (`docs/validation_results/T4_agent_reliability.md`).

## Lesson
"Thinking" models can return a **valid, empty** turn when the thinking budget is
consumed before any output — no error to catch. For native function-calling agents
on `gemini-2.5-*`, set `thinking_budget=0` (or a deliberate budget) explicitly; do
not rely on the default. Also: an empty-turn fallback masks the problem — the chain
kept working via Ollama, so this hid for a while. Worth a log line when a provider
returns an empty turn (the FallbackProvider already warns on this — that warning was
the breadcrumb).
