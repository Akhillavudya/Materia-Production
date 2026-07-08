# issue-nve-ensemble-gate

## Symptom
Asking for an **NVE** (microcanonical) molecular-dynamics run — either through the chat
agent or the manual MD launcher panel — failed immediately with:

> Invalid ensemble 'nve'. Use: nvt | npt

even though NVE was offered in the UI dropdown and advertised to the LLM as a valid option.
NVT and NPT worked fine.

## Root cause
NVE support was added across every layer *except* the tool's own input gate:

- **Service** — `services/simulation/md.py` fully implements NVE: it seeds Maxwell–Boltzmann
  velocities (required because `VelocityVerlet` has no thermostat to inject kinetic energy),
  builds the `VelocityVerlet` integrator (`_make_dynamics`, line 426), maps `nve → md_nve`
  for VASP emission, and reports the energy-conservation verdict instead of a temperature one.
- **Contract** — `tools/contracts.py:105-111` advertises `"nve"` to the LLM.
- **Frontend** — `features/sessions/toolForms.js:241` lists `nve` in the ensemble dropdown
  and correctly hides the thermostat control for it.
- **VASP preset** — `services/vasp/templates.py:141` defines `md_nve`.

But the tool entrypoint `run_md_simulation` in `tools/material_tools.py` still had the
original guard from when only NVT/NPT existed:

```python
if ensemble not in ("nvt", "npt"):
    return {"status": "error", "message": f"Invalid ensemble '{ensemble}'. Use: nvt | npt"}
```

So a request that the service, schema, UI, and VASP layer were all ready to handle was
rejected at the one boundary that hadn't been updated. This is the classic "feature added
in N-1 of N places" drift — the same failure mode the tool-schema drift guard was created
to prevent, but the ensemble string isn't covered by that guard.

## How we fixed it
Widened the gate to accept `nve` (and fixed the now-stale error string and docstring):

```python
"""Queue an ASE Molecular Dynamics (NVT/NPT/NVE) job for a session structure.
...
"""
if ensemble not in ("nvt", "npt", "nve"):
    return {"status": "error", "message": f"Invalid ensemble '{ensemble}'. Use: nvt | npt | nve"}
```

Nothing downstream needed changing — the tool passes `ensemble` straight into the job
params, and the service already handled `nve` end-to-end. The existing thermostat-default
line (`... or ("langevin" if ensemble == "nvt" else "berendsen")`) is harmless for NVE
because `VelocityVerlet` ignores the thermostat argument.

## Files changed
- `backend/app/tools/material_tools.py` — `run_md_simulation` gate + docstring (lines ~1476-1483).

## How to verify
- Manual launcher: pick **NVE** in the MD panel, launch on a small cell (e.g. 8-atom Si) →
  a job is queued (no "Invalid ensemble" error) and produces `trajectory.xyz` +
  `convergence_report.md` with an energy-conservation verdict.
- Agent: "run an NVE MD on the current structure" → enqueues rather than erroring.
- Quick static check: `python -c "import ast; ast.parse(open('app/tools/material_tools.py').read())"`.

## Lesson
When a new enum value (here an MD ensemble) is threaded through the stack, grep for the
**old whitelist** everywhere, not just the happy-path implementation. Service + schema + UI
+ VASP preset all had `nve`; the single validation guard that still said `("nvt","npt")`
silently gated the whole feature. A value-level contract (e.g. deriving the accepted-ensemble
set from one shared constant) would make this class of drift impossible.
