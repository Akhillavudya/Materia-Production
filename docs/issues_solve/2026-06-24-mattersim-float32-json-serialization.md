# MatterSim jobs fail: "Object of type float32 is not JSON serializable"

**Date:** 2026-06-24
**Area:** async jobs / simulation calculators (MatterSim vs MACE)

## Symptom
Running **Geometry optimization** (and any heavy sim) with a **MatterSim** model
fails immediately with the job card showing:

```
Optimization failed: (builtins.TypeError) Object of type float32 is not JSON serializable
[SQL: UPDATE jobs SET progress=%(progress)s::JSONB WHERE jobs.id = %(jobs_id)s]
[parameters: [{'progress': {'step': 0, 'total': 1000, 'pct': 0.0,
               'energy': np.float32(-21.917307), 'fmax': 1.364038, ...}}]]
```

The **same job with the default MACE model runs fine**. The simulation itself was
*not* broken — MatterSim loaded and computed energy/forces correctly. The failure
was purely on the **DB write of the progress dict**.

## Root cause
- MACE's `ASE` calculator returns `get_potential_energy()` as a **Python `float`**.
- MatterSim returns it as a **`numpy.float32`** scalar.
- `round(np.float32, 6)` **keeps the numpy type** (numpy round is type-preserving),
  so `energy` stayed `np.float32` in the progress payload.
- The progress dict is written to the Postgres **JSONB** `jobs.progress` column.
  SQLAlchemy/psycopg JSON-encodes it and `json` cannot serialize `np.float32`,
  so the whole job is marked **failed** at step 0.
- The SSE `publish()` path (`json.dumps`) hit the same error but was wrapped in
  try/except, so it silently dropped events — masking the cause.
- Secondary latent bug: the final `result`/`results.json` also carried the
  numpy energy, so even past the progress write a MatterSim job would have failed
  again in `mark_succeeded` (and `results.json` was silently skipped).

This is why **only MatterSim** broke: it was the only calculator leaking a numpy
scalar into a JSONB write.

## Fix
Two layers — fix at the source, plus a durable safety net at the DB boundary.

1. **Source coercion** — cast energy to native `float` where it is read:
   - `services/simulation/optimization.py`: `e = float(opt_atoms.get_potential_energy())`
   - `services/simulation/md.py`: `e = float(...)`, `T = float(...)`
   `_get_fmax()` already returned a native float.

2. **Central sanitizer at the JSONB write boundary** — `app/jobs/store.py` gains
   `to_jsonable()` which recursively converts any numpy scalar (`.item()`) /
   array / nested dict-list to native Python types. Applied in:
   - `update_progress()` (progress JSONB)
   - `mark_succeeded()` (result + artifacts JSONB)
   - `mark_cancelled()` (result + artifacts JSONB)
   `app/jobs/progress.py` reuses the same `to_jsonable` for the progress payload
   (covers both the DB write and the SSE publish).

   This means **any** future service that leaks a numpy value into a job result
   is neutralised in one place — not just MatterSim, not just energy.

## Verification
- `to_jsonable` round-trips nested `np.float32/np.float64/np.int64` → `json.dumps` OK.
- End-to-end `run_optimization(..., calculator={'type':'mattersim','model':'mattersim-v1.0.0-1M'})`:
  status `converged`, returned result is `json.dumps`-able, callback `energy` is
  native `float`, `results.json` written.
- Loaded + computed energy on **all 6 models** (4 MACE + 2 MatterSim) — all OK.
  Confirmed MACE → `float`, MatterSim → `float32` (the exact asymmetry).

## Lesson
When a value crosses a serialization boundary (JSONB column, SSE `json.dumps`,
`results.json`), never trust that a library returns native Python types. ML
potentials commonly return `np.float32`. Sanitize once at the boundary
(`store.to_jsonable`) rather than chasing every producer. And guard try/except
blocks (the `publish` swallow) hid the real error — log, don't silently drop, on
serialization failures.
