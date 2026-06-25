# SQS (and 4 other tools) unusable by the agent: missing from the LLM tool schema

**Date:** 2026-06-25
**Area:** agent tool declaration (function-calling schema vs. executor registry)

## Symptom
Asking the agent to "substitute 25% of Se with S in MgSc2Se4 using SQS" failed.
The agent flailed and gave up, saying things like:
- "the `generate_sqs` tool does not accept a `poscar_name` argument"
- "the `substitutions` argument is also not recognized"
- "it expects the input structure to already have partial site occupancies"
- finally falling back to `create_substitution` ("replaces only one atom") and
  declaring it "cannot directly create a structure with a specific percentage".

Meanwhile `generate_sqs` **does** have a `substitute` parameter (e.g.
`"Se->S:0.25"`) added on 2026-06-23, and the underlying partial-occupancy
generation works fine.

## Root cause
There are **two** tool registries and they had drifted:

1. `app/agent/tool_registry.py` → `TOOL_REGISTRY` / `CALLABLE_TOOL_MAP`
   — used for **execution** and for the **planner's** tool list. Had all **23** tools.
2. `app/agent/tool_schemas.py` → `_TOOL_MODELS` → `TOOL_SPECS`
   — the JSON schemas actually **declared to the LLM** for native function calling
   (`provider.run(conv, TOOL_SPECS, ...)` in `graph.py`). Had only **18** tools.

Five tools were executable + listed to the planner but had **no parameter schema
declared to the model**:
`generate_sqs`, `compute_phonons`, `compute_elastic_tensor`, `compute_neb`,
`list_migration_paths`.

So the model knew the tool *existed* (the planner prompt lists every
`TOOL_REGISTRY` tool by name) but had no argument schema. It therefore **guessed**
argument names (`poscar_name`, `substitutions`), which failed Pydantic validation,
and concluded the capability didn't exist. SQS was the visible casualty; the other
four heavy tools had the same latent breakage.

## Fix
Add the 5 missing tools to `app/agent/tool_schemas.py`:
- import the 5 contracts (`ComputeElasticInput`, `ComputePhononInput`,
  `GenerateSqsInput`, `ComputeNebInput`, `ListMigrationPathsInput`),
- add a model-facing `_TOOL_DESCRIPTIONS` entry for each (the SQS one explicitly
  documents `substitute="Se->S:0.25"` so the model reaches for it),
- add them to `_TOOL_MODELS`.

`TOOL_SPECS` is now built from the same 23 tools as the executor registry.

## Verification
- `tool_schemas.TOOL_NAMES` == `tool_registry.CALLABLE_TOOL_MAP` keys → both 23,
  with **no** "executable but not declared" gap (was 5).
- `generate_sqs` schema now exposes `substitute` with its description.
- Generation logic itself confirmed correct: `_apply_partial_substitutions` on an
  ordered MgSc2Se4 with `Se->S:0.25` yields each Se site → `{Se:0.75, S:0.25}`,
  composition `Mg1 Sc2 Se3 S1`. `_parse_substitutions` accepts both `0.25` and `25%`.

## Lesson
When tool execution and tool *declaration* live in separate lists, they will
drift — and the failure is silent + confusing (the model improvises bad args
instead of erroring clearly). Either derive both from one list, or add a startup
assertion that the declared-to-LLM set equals the executable set. A quick guard:
`assert TOOL_NAMES == set(CALLABLE_TOOL_MAP)` would have caught this at import.
