# issue-sqs-rejects-normal-structures

## Symptom
The SQS tool (`generate_sqs`) refused to work on a normal, fully-ordered structure.
Uploading an ordinary POSCAR/CIF (e.g. SrTiO₃) and asking for a random alloy failed
with:

> "No disordered sublattice found. SQS needs partial site occupancies…"

The only way to run it was to (a) supply a hand-made *disordered* CIF with partial
occupancies, or (b) pass the legacy `substitute="Si->S:0.25"` fraction spec. There
was no way to say *"put 60 % Ti / 40 % Zr on the Ti site of this ordinary crystal"* —
which is exactly the everyday SQS workflow (cf. the reference app
[SimplySQS / atat-sqs-gui](https://github.com/bracerino/atat-sqs-gui)).

## Root cause
`run_sqs()` was written for one input shape only: a CIF that *already* carried
partial site occupancies. It detected disorder, and if it found none it hard-erred.
An ordered structure has no disorder, so it was rejected before anything useful could
happen. There was also no concept of a **sublattice**: the tool couldn't tell the
user *which sites* were available to alloy, and it couldn't accept a per-site target
composition. "Randomise 40 % of the Ti site" simply had no code path.

## How we fixed it
Reworked the SQS flow to the SimplySQS model — **start from a normal ordered
structure, choose a sublattice, give it a composition**:

1. **Sublattice detection.** New `list_sublattices()` uses pymatgen's
   `SpacegroupAnalyzer` to group sites into symmetry-distinct **Wyckoff** sublattices
   and reports each as `{id, element, wyckoff, count}` (SrTiO₃ → Sr 1a, Ti 1b, O 3c).
2. **Per-sublattice composition.** New `_apply_sublattice_composition()` takes a spec
   like `{"Ti": {"Ti": 0.6, "Zr": 0.4}}` (keyed by element *or* by Wyckoff id such as
   `"Ti(1b)"`), normalises it, and injects those partial occupancies onto every site
   of that sublattice — turning the ordered parent into the disordered target the SQS
   represents. The user-facing string form is `"Ti=Ti0.6,Zr0.4 ; Sr=Sr0.6,Ba0.4"`.
3. **Dropped the hard block.** When a structure is still fully ordered (no composition
   given) the tool no longer errors blindly; it lists the available sublattices and
   tells the user how to specify a composition.
4. **MLP relaxation.** After ATAT `mcsqs` finds the best ordering, the SQS supercell is
   relaxed with an ML potential (MACE by default) via the existing `run_optimization`,
   so the output is a physically reasonable structure, not just ideal-lattice
   placement. Controlled by `relax` / `calculator_type`.
5. **UI + chat.** The SQS panel gained a **"Detect sublattices"** button (chips seed the
   composition field) and a composition field + potential picker. A new `list_sublattices`
   agent tool lets the chat flow do the same: *"show the sublattices of SrTiO₃"* →
   *"make an SQS with 40 % Zr on the Ti site"*.

## Files changed
- `backend/app/services/simulation/sqs.py` — `list_sublattices()`, `_sublattice_groups()`,
  `_apply_sublattice_composition()`; `run_sqs()` accepts ordered input + `sublattice_comp`
  + `relax`/`calculator`; informative (not fatal) message when nothing to randomise.
- `backend/app/tools/material_tools.py` — `list_sublattices` tool; `_parse_sublattice_comp()`;
  `generate_sqs` gains `sublattice_comp`/`relax`/`calculator_*`, default resolves the active
  ordered structure.
- `backend/app/tools/contracts.py` — `ListSublatticesInput`; extended `GenerateSqsInput`.
- `backend/app/agent/tool_schemas.py`, `tool_registry.py`, `graph.py` — register + describe
  both tools (drift guard kept in sync); prompt rules for the new workflow.
- `backend/app/jobs/runners.py` — pass `sublattice_comp`/`relax`/`calculator`; map new files.
- `backend/app/api/upload.py` — `POST /sessions/{id}/sqs/sublattices`; extended `/sqs` form.
- `frontend/src/api/tools.js` — `fetchSqsSublattices()`.
- `frontend/src/features/sessions/toolForms.js` — SQS fields (composition, relax, potential,
  `analyze: 'sublattices'`).
- `frontend/src/features/sessions/ToolLaunchPanel.jsx` — "Detect sublattices" button + chips,
  full-width field support.

## How to verify
- `list_sublattices` on ordered SrTiO₃ → 3 sublattices (Sr 1a, Ti 1b, O 3c). ✓ tested
- `_apply_sublattice_composition(st, {"Ti": {"Ti":0.6,"Zr":0.4}})` → Ti site becomes
  `{Ti:0.6, Zr:0.4}`, parent stays SrTiO₃. ✓ tested
- No composition on an ordered cell → active disorder is empty → informative message,
  not a crash. ✓ tested
- Parser accepts `"Ti=Ti0.6,Zr0.4"`, `"Ti: Ti0.6 Zr0.4"`, `"Ti(1b)=…"`, multi-sublattice;
  rejects `"Ti=Ti,Zr"`. ✓ tested
- Full ATAT+MLP run requires the ATAT binaries (Docker image) — smoke-test in the stack.

## Lesson
Design a tool around the *user's starting point*, not the algorithm's convenience.
`mcsqs` internally needs partial occupancies, but the user always starts from an
ordinary crystal — so the tool must own the "ordered → disordered on a chosen
sublattice" step instead of pushing it onto the user. Symmetry (Wyckoff) analysis is
what turns "the structure" into "sites you can choose", which is the missing concept
that made the natural request expressible.
