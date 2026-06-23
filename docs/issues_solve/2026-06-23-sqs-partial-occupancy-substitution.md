# 2026-06-23 — SQS could not create partial occupancies from an ordered structure

## Symptom
A request like **"Substitute 25% of Si with S in MgSi2Se4 using SQS"** never produced
an SQS. The agent fetched MgSi2Se4, then repeatedly failed calling `generate_sqs` —
at one point inventing a non-existent `source` argument — and gave up ("the
generate_sqs tool does not accept a source parameter… language model is busy").
(See screenshot `49377.jpg`.)

## Root cause
Two layered problems, but one real one:

1. **Semantic gap (the real bug).** `generate_sqs` / `run_sqs` could *only* consume a
   structure that was **already disordered** (a CIF with partial site occupancies).
   MgSi2Se4 fetched from a database is fully **ordered**. So sublattice detection
   (`_build_parent_and_sublattices`) skipped every site (`site.is_ordered → continue`),
   found no disordered sublattice, and returned an error. There was **no parameter** to
   express "make 25% of Si sites partially S", i.e. to *create* the disorder SQS needs.
   `target_comp` only *restricts* already-disordered occupancies; it cannot introduce them.

2. **Model flailing (a symptom).** Because no real argument matched the user's intent,
   the LLM hallucinated arguments (`source`) and looped.

## Fix
Added a first-class **partial-substitution** path to SQS:

- **Service** (`services/simulation/sqs.py`): new `substitutions` arg on `run_sqs` +
  `_apply_partial_substitutions()`. Each spec `{"from":"Si","to":"S","fraction":0.25}`
  rewrites every ordered `Si` site to `{Si:0.75, S:0.25}` via `Structure.replace`,
  producing exactly the disordered sublattice the existing pipeline already handles.
  Validates the fraction is in (0,1) and that the `from` element is present.
- **Tool** (`tools/material_tools.py`): new `substitute` param on `generate_sqs` +
  `_parse_substitutions()` accepting `"Si->S:0.25"`, `"Si->S=25%"`, `"Si:S:0.25"`,
  `"Si->S:25"`, and comma lists. When `substitute` is given (and no explicit
  `cif_name`), the tool starts from the active **ordered** POSCAR instead of hunting
  for a disordered CIF.
- **Contract** (`tools/contracts.py`): documented `substitute` on `GenerateSqsInput`
  with the MgSi2Se4 example, so the model picks it instead of inventing args.
- **Runner** (`jobs/runners.py`): threads `substitutions` through to `run_sqs`.
- Sharpened the "No disordered sublattice found" error to point at `substitute`.

## Verify
- `_apply_partial_substitutions` on an ordered MgSi2Se4-like cell → `type_0` sublattice
  `{Si:0.75, S:0.25}` detected by `_build_parent_and_sublattices`. ✓
- Parser handles `0.25`, `25%`, `25`, `Si:S:0.25`, multi-entry lists; rejects junk. ✓
- Missing-element and out-of-range fraction raise clear errors. ✓
- `py_compile` clean on all four files. ✓
- ATAT mcsqs end-to-end not run locally (binaries live in the worker image only).

## Lesson
When the model "hallucinates a parameter," check first whether the tool can actually
do what the user asked. Here the missing capability — not a prompt problem — was the
root cause. Expose the user's intent as a real, documented argument and the model stops
guessing.
