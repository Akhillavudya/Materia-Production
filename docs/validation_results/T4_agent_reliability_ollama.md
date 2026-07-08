# T4 — Agent reliability (results)

**Date:** 2026-07-08 · **Plan:** `docs/VALIDATION_PLAN.md` §5
**Harness:** `backend/scripts/validation/t4_agent_reliability.py` · **Suite:** `backend/scripts/validation/t4_prompt_suite.py`
**Provider:** ollama (`qwen3:14b`) — the desktop-offline fallback, **not** the hosted default. **Cases:** 39

> Companion to the hosted-provider report `T4_agent_reliability.md` (gemini-2.5-flash =
> **100%** on the same suite). Benchmarks the **offline** brain the desktop app falls back
> to with no Gemini key / no network. Same suite, same harness (`--providers ollama
> --tag ollama`).

Each case = one agent turn with the production `SYSTEM_PROMPT` + 23 tool schemas; we grade the **first** tool the model calls (nothing is executed, no jobs spawned). Tool-selection = right tool chosen (or correctly no tool for ambiguous/out-of-scope/conceptual). Argument accuracy = of correctly-selected tool calls with expected args, the fraction whose key args all match.

## Headline

`qwen3:14b` reaches **92% tool-selection (36/39)** with **100% argument accuracy (20/20)**
at **2.4 s/turn** — a strong offline fallback, close to gemini-2.5-flash's 100%. It handles
every single-tool (12/12) and structure-editing (7/7) case, and correctly declines on
ambiguous/conceptual prompts. Gemini stays the recommended default, but the offline path is
now genuinely capable rather than a token gesture.

### How it got here — two provider-scoped fixes (Gemini untouched)

This started at an effective **0%** and climbed to **92%** via three changes inside
`app/agent/providers/ollama.py` only (the shared `SYSTEM_PROMPT` was never edited):

| Step | Change | Tool-selection |
|------|--------|----------------|
| baseline | qwen3 thinking on, default 4k context | **0/39** — prose, no tool calls |
| + `think=False` | disable chain-of-thought | 16/39 (41%) |
| + `num_ctx=16384` | **stop Ollama truncating the tool list** (the big one) | **36/39 (92%)** |

The decisive fix was **`num_ctx`**: Ollama's default context is ~4096 tokens, but the
payload (`SYSTEM_PROMPT` ~2k + 23 tool schemas ~8.6k + routing primer) is ~11k tokens, so
Ollama silently truncated the request and qwen3 never saw most of the tools — it would say
*"none of the provided functions can be used…"* for `search_materials` while over-calling
the last tools in the list (`generate_sqs` / `compute_neb`). Raising `num_ctx` to fit the
whole payload fixed selection **and** collapsed latency (12.7 s → 2.4 s). Also added a
temperature=0 + a compact offline tool-routing primer. Postmortems:
`docs/issues_solved/issue-ollama-context-window-truncation.md` and
`docs/issues_solved/issue-ollama-qwen3-thinking-no-toolcalls.md`.

## Aggregate per provider

| Provider | Tool-selection | Argument accuracy | Mean latency (s) |
|----------|----------------|-------------------|------------------|
| ollama | 36/39 (92%) | 20/20 (100%) | 2.40 |

## Tool-selection by category

| Category | ollama |
|----------|------|
| single | 12/12 |
| multi | 3/4 |
| structure | 7/7 |
| compute | 5/6 |
| ambiguous | 3/3 |
| out_of_scope | 3/4 |
| conceptual | 3/3 |

## Failures (tool or argument)

| Provider | id | Prompt | Expected | Got (first tool) | Why |
|----------|----|--------|----------|------------------|-----|
| ollama | S22 | Substitute 25% of the Se with S in my structure using SQS. | generate_sqs | list_sublattices | wrong tool |
| ollama | M3 | Optimize the structure of silicon with MatterSim. | search_materials | optimize_structure | wrong tool |
| ollama | O4 | Relax my structure with the CHGNet potential. | list_models|NONE | optimize_structure | wrong tool |

**Notes.** Multi-tool prompts grade the correct *first* tool (the search-before-generate decision); the plan→confirm gate then sequences the rest. Ambiguous/out-of-scope/conceptual cases pass when the agent correctly calls no tool (asks/clarifies/answers directly). Argument matching is case-insensitive substring / numeric-equal.

### The 3 remaining misses (all subtle judgement calls)

- **S22** (`generate_sqs` → `list_sublattices`): asked to substitute 25% Se with S *via SQS*;
  qwen3 picked the sublattice-listing tool, which is genuinely the *first step* of the SQS
  workflow — wrong final tool but not nonsensical.
- **M3** (`search_materials` → `optimize_structure`): "optimize silicon with MatterSim" — it
  jumped straight to relaxing instead of resolving "silicon" via search first. It got the
  other three multi-tool search-first prompts (M1/M2/M4) right.
- **O4** (`list_models`/NONE → `optimize_structure`): "relax with the CHGNet potential" —
  CHGNet isn't a supported calculator, so it should list models / decline; it tried anyway.

None are gross mismatches — they're borderline calls a strong model can differ on. All 20
correctly-selected tool calls that had checkable arguments had **every** key argument right.

