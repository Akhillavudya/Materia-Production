# T4 — Agent reliability (results)

**Date:** 2026-06-25 · **Plan:** `docs/VALIDATION_PLAN.md` §5
**Harness:** `backend/scripts/validation/t4_agent_reliability.py` · **Suite:** `backend/scripts/validation/t4_prompt_suite.py`
**Providers:** groq, gemini (the free hosted stack; Ollama is the user-side offline option, not benchmarked) · **Cases:** 39

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
| **groq** (llama-3.3-70b-versatile) | 🟡 partial — free **daily token cap** hit; full pass pending | 4/6 clean decisions | 4/4 (100%) | — |

> **gemini** ran 37 of 39 cases; the final two (`C2`, `C3` — conceptual
> "explain X" prompts expecting **no** tool) were not reached because the free
> per-minute quota stopped resetting after 6×65 s waits. Every other conceptual /
> ambiguous / out-of-scope case (`C1`, `A1–A3`, `O1–O4`) passed as no-tool, so the
> two unreached cases are near-certain passes; they will be filled on the next run.
>
> **groq** is blocked by the free **daily token limit** (~100 k tokens/day/key):
> the production system prompt + 23 tool schemas is ~8 k tokens/call, so each key
> allows only ~12 calls/day. The full 39-case Groq pass is deferred until the daily
> quota resets (or with more keys). Numbers below are from a 9-case pilot.

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
> making Gemini a silent no-op as the fallback provider and breaking tool-calling
> when it was primary. Fixed in `app/agent/providers/gemini.py` with
> `thinking_config=ThinkingConfig(thinking_budget=0)`. Postmortem:
> `docs/issues_solve/2026-06-25-gemini-thinking-empty-tool-calls.md`. The 100% above
> is post-fix.

## groq — 9-case pilot (partial)

Clean model decisions before the daily cap:

| id | Prompt | Expected (first tool) | groq chose | Verdict |
|----|--------|-----------------------|------------|---------|
| S4 | full VASP input set for mp-149 | generate_vasp_inputs | generate_vasp_inputs (args ok) | ✅ |
| S11 | 2×2×2 supercell | make_supercell | make_supercell (args ok) | ✅ |
| S18 | relax with MACE | optimize_structure | optimize_structure (args ok) | ✅ |
| S19 | NVT MD at 500 K | run_md_simulation | run_md_simulation (args ok) | ✅ |
| M1 | full VASP set for **NaCl** | search_materials (search first) | generate_vasp_inputs | ❌ skipped search-first |
| A1 | "Generate VASP inputs." (no material) | NONE (ask) | generate_vasp_inputs | ❌ didn't clarify |
| S1 | find NaCl | search_materials | — (provider function-call format error) | ⚠ formatting error |
| O1 | weather in Paris | NONE | — (tried a non-existent `brave_search`, rejected) | ⚠ hallucinated tool |
| C1 | what is a POSCAR | NONE | — (429 rate limit) | n/a (quota) |

**Groq read (preliminary):** strong on direct single-tool / compute / structure
selection with **correct arguments** (S4, S11, S18, S19), but weaker than Gemini on
two judgement behaviours — it **skips the search-first rule** for bare formulas
(M1) and **does not ask for clarification** on under-specified prompts (A1) — and it
occasionally emits a malformed function call (S1) or reaches for a tool it was
never given (O1). These are exactly the differentiator cases T4 is designed to
surface; the full 39-case pass will quantify them.

## Headline

On the **free hosted stack**, Gemini (gemini-2.5-flash) achieves **100%
tool-selection and 100% argument accuracy** across 37/39 curated prompts spanning
single-tool, multi-tool, structure-editing, compute-job, ambiguous, out-of-scope,
and conceptual categories — including correct search-before-generate sequencing and
correct refusal/clarification on prompts that should **not** trigger a tool. This is
a measurement neither reference tool (Masgent, ChatMat) reports. Groq results are
partial pending its daily-quota reset.

## Reproduce

```
cd backend
../venv/bin/python scripts/validation/t4_agent_reliability.py --providers gemini
../venv/bin/python scripts/validation/t4_agent_reliability.py --providers groq      # needs daily-quota headroom
# pilot subset:
../venv/bin/python scripts/validation/t4_agent_reliability.py --providers gemini --ids S1,S4,M1,A1
```

Keys are read from `backend/.env` (`GROQ_API_KEYS` / `GEMINI_API_KEYS`,
comma-separated, rotated across accounts as each hits its rate limit; falls back to
the single `GROQ_API_KEY` / `GEMINI_API_KEY`). Per-row data: `T4_agent_reliability.csv`.
