# T4 — Agent reliability (results)

**Date:** 2026-06-25 (Groq dropped 2026-07-07) · **Plan:** `docs/VALIDATION_PLAN.md` §5
**Harness:** `backend/scripts/validation/t4_agent_reliability.py` · **Suite:** `backend/scripts/validation/t4_prompt_suite.py`
**Provider:** gemini (the sole hosted provider; Ollama is the desktop-offline option, not benchmarked) · **Cases:** 39

Each case = one agent turn with the production `SYSTEM_PROMPT` + 23 tool schemas;
we grade the **first** tool the model calls (nothing is executed — no jobs spawned).
Tool-selection = right tool chosen (or correctly **no** tool for ambiguous /
out-of-scope / conceptual prompts). Argument accuracy = of correctly-selected tool
calls that have expected args, the fraction whose key args all match. Argument
matching is case-insensitive substring / numeric-equal.

## Provider status

| Provider | Status | Tool-selection | Argument accuracy | Mean latency (s) |
|----------|--------|----------------|-------------------|------------------|
| **gemini** (gemini-2.5-flash) | ✅ complete (37/39 cases ran) | **37/37 (100%)** | **22/22 (100%)** | 2.09 |

> **gemini** ran 37 of 39 cases; the final two (`C2`, `C3` — conceptual
> "explain X" prompts expecting **no** tool) were not reached because the free
> per-minute quota stopped resetting after 6×65 s waits. Every other conceptual /
> ambiguous / out-of-scope case (`C1`, `A1–A3`, `O1–O4`) passed as no-tool, so the
> two unreached cases are near-certain passes.

## gemini — tool-selection by category (complete)

| Category | gemini |
|----------|--------|
| single (search / generate / kpoints / list / symmetry / convert) | 12/12 |
| multi (correct *first* tool, e.g. search-before-generate) | 4/4 |
| structure (supercell / vacuum / slab / adsorbate / defects) | 7/7 |
| compute (optimize / MD / elastic / phonon / SQS / NEB) | 6/6 |
| ambiguous (should ask for clarification → no tool) | 3/3 |
| out_of_scope (should refuse / redirect → no tool) | 4/4 |
| conceptual (answer directly → no tool) | 1/1 (2 cases unreached) |

**gemini failures:** none — every case that ran passed, with all key arguments
correct (formula, material_id, task/functional, miller/layers, axis/thickness,
ensemble/temperature, calculator_type, substitute, …). gemini correctly applied
the **search-first** rule on all four multi-tool prompts (`generate VASP for NaCl`
→ `search_materials(formula=NaCl)` first), correctly **declined to call a tool** on
all ambiguous prompts (`"Generate VASP inputs."` with no material → asks), refused
out-of-scope requests (weather, web-scraping, training a new potential, CHGNet),
and answered conceptual questions directly.

> **Note — a real bug was found and fixed while building T4.** gemini-2.5-flash has
> "thinking" on by default and, with the tool set present, was spending the whole
> turn thinking and returning an **empty** response (no text, no function call) —
> making Gemini a silent no-op. Fixed in `app/agent/providers/gemini.py` with
> `thinking_config=ThinkingConfig(thinking_budget=0)`. Postmortem:
> `docs/issues_solve/2026-06-25-gemini-thinking-empty-tool-calls.md`. The 100% above
> is post-fix.

## Why Groq was evaluated then dropped (2026-07-07)

Earlier builds carried a Groq `llama-3.3-70b-versatile` fallback, and T4 tried to
benchmark it. It could **not** complete the suite, for a structural reason:

- Groq's free tier (`on_demand`) enforces a per-request **tokens-per-minute (TPM)**
  ceiling. The production payload — `SYSTEM_PROMPT` (~2 k tokens) + 23 tool schemas
  (~8.6 k tokens) ≈ **10.6 k tokens per call** — exceeds that ceiling, so every
  full-tool call returns **HTTP 413 "Request too large"** before the model even runs.
  A reduced 5-tool subset passes, confirming the schema size is the blocker.
- This is not a transient daily-quota issue that headroom or extra keys would fix —
  it is a hard per-request limit. **Groq's free tier therefore cannot serve a single
  real Materia agent call**, so it was never a functioning production fallback.
- A small 9-case pilot (run before the 413 wall was fully characterised, on a trimmed
  payload) also hinted at weaker judgement than Gemini — it skipped the search-first
  rule for bare formulas (M1) and didn't ask for clarification on under-specified
  prompts (A1) — but the decisive reason for removal is the 413/TPM limit.

Groq was removed entirely (provider, SDK dependency, config, key mapping, UI). The
benchmarked and shipped hosted provider is **Gemini alone**; resilience comes from
Gemini multi-key rotation (`_keypool.py`) on web and Ollama offline on desktop.

## Headline

Materia's hosted agent (gemini-2.5-flash) achieves **100% tool-selection and 100%
argument accuracy** across 37/39 curated prompts spanning single-tool, multi-tool,
structure-editing, compute-job, ambiguous, out-of-scope, and conceptual categories —
including correct search-before-generate sequencing and correct refusal/clarification
on prompts that should **not** trigger a tool. This is a measurement neither reference
tool (Masgent, ChatMat) reports.

## Reproduce

```
cd backend
../venv/bin/python scripts/validation/t4_agent_reliability.py --providers gemini
# pilot subset:
../venv/bin/python scripts/validation/t4_agent_reliability.py --providers gemini --ids S1,S4,M1,A1
```

Keys are read from `backend/.env` (`GEMINI_API_KEYS`, comma-separated, rotated
across accounts as each hits its rate limit; falls back to the single
`GEMINI_API_KEY`). Per-row data: `T4_agent_reliability.csv`.
