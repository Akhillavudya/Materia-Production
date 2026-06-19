# 2026-06-19 — Trio (elastic/phonon/SQS) rebuild: ATAT silently broken + agent never calls the tools

Two separate, independently-shipped bugs surfaced when rebuilding the image and smoke-testing the
three Step-5.7 simulation tools (`compute_elastic_tensor`, `compute_phonons`, `generate_sqs`).

---

## Bug 1 — ATAT never compiled; image shipped with no SQS binaries

### Symptom
The previously-running image had been up 20h with a non-functional `generate_sqs`. Re-running the
backend build returned **exit 0 (success)** yet produced an image with no `mcsqs`/`corrdump`/`getclus`.

### Root cause (three compounding issues in `backend/Dockerfile`)
1. **Missing `tcsh`.** ATAT's `makefile` runs `./foolproof.sh`, which needs `/bin/csh`. Without it the
   compile died immediately: `/bin/csh cannot be found … make: *** [makefile:9: all] Error 1`.
2. **Failure was masked.** The ATAT `RUN` step ended in `… && corrdump --help >/dev/null 2>&1 || true`.
   Because `&&`/`||` are left-associative, a failure anywhere in the chain short-circuited to `|| true`,
   so the layer (and the whole build) reported success despite producing zero binaries.
3. **Non-root perms.** Even once compiled, `getclus` installs as `0750` root-owned, but the image runs
   as non-root `appuser`. The SQS service checks `shutil.which("getclus")`, which tests the executable
   bit *for the current user* → returned `None` → SQS would degrade to "ATAT not found".

### Fix
- Add `tcsh` to the apt install layer.
- Replace `|| true` with explicit `test -x /usr/local/bin/{mcsqs,corrdump,getclus}` so a broken ATAT
  **fails the build loudly**.
- `chmod -R a+rX /usr/local/bin` so `appuser` can execute every ATAT binary.

### Verify
Validated the ATAT compile in a throwaway `python:3.11-slim-trixie` container *before* the full rebuild
(`/bin/csh -> /etc/alternatives/csh`, all binaries produced). After rebuild, inside the worker as
`appuser`: `shutil.which` finds all three; `generate_sqs` on a disordered CuAu (2×2×1) returned
objective −1.2475 in 6.2s with all artifacts.

### Lesson
Never let a compile-from-source layer end in `|| true`. Assert the produced artifacts exist (`test -x`)
so the build fails instead of silently shipping a broken capability.

---

## Bug 2 — Agent refused to run elastic/phonon and never called the trio tools

### Symptom
In the chat UI, "Compute the elastic tensor…" got *"I cannot directly compute … you would need to run
the VASP calculation on a separate computational resource"* and only generated VASP input files.
"Compute the phonon band structure (2×2×2 supercell)" built a supercell via `make_supercell` and again
offered VASP inputs. **No trio tool was ever called; no job was enqueued.** (The services themselves
worked fine when called directly — this was purely agent routing.)

### Root cause
`backend/app/agent/graph.py` `SYSTEM_PROMPT` "Your tools:" list documented only **8 of the 16**
registered tools. The entire trio and the Step-5.5 structure tools were missing. The full function
schemas *were* passed to the LLM (built from `_TOOL_SPECS`), but the prompt framed the assistant's
identity as "generate VASP inputs, you run DFT elsewhere" and listed only `optimize_structure` /
`run_md_simulation` as runnable — so the model apologized and fell back to VASP-input generation.

### Fix
- List all 16 tools in the prompt, with the trio clearly described as ML-potential **async jobs**.
- Add a rule: "you CAN compute elastic / phonons / SQS yourself (ML potential, background job); do NOT
  tell the user to run VASP/DFT on a separate resource — `generate_vasp_inputs` is only for when they
  explicitly want DFT input files."
- Extend the async-job and no-fabrication rules to include the trio.

### Verify
Rebuilt (Dockerfile/requirements unchanged → only the source layer rebuilt, fast) and recreated
`api`/`worker`. Confirmed the new prompt is baked in (`compute_elastic_tensor` listed, no-DFT rule
present). Re-test in the UI on http://localhost:8080.

### Lesson
Registering a tool in `_TOOL_SPECS` is necessary but **not sufficient** — if it isn't also documented in
the `SYSTEM_PROMPT`, the model won't choose it. Every new tool needs both. (Applies to NEB next.)

---

## Bug 3 — Disordered CIF upload rejected, so SQS was unreachable from the UI

### Symptom
Uploading a disordered CIF (the CuAu test structure for SQS) was rejected, even though ordered `.cif`
files upload fine. The SQS tool could therefore never be exercised through the chat UI.

### Root cause
Both structure-entry paths funnel through `write_poscar()`, and **POSCAR cannot represent partial
occupancies** — pymatgen raises `ValueError: Disordered structure with partial occupancies cannot be
converted into POSCAR!`.
- `services/structure/activation.py::activate_structure` (used by the **upload** auto-activate) let that
  `ValueError` escape its `except StructureParseError` handler → the upload endpoint 500'd.
- `tools/material_tools.py::_read_structure_file` (the agent's **read_file** tool) caught it but returned
  `status:"error"` → the agent told the user it couldn't read the file.

### Fix
- Both paths now branch on `structure.is_ordered`: **disordered → write a `<formula>_disordered.cif`**
  (preserves occupancies) instead of a POSCAR, and report `disordered: True` with a message that it's
  ready for `generate_sqs` (not for optimize/MD/VASP, which need an ordered cell).
- `upload.py::_activate_uploads` also catches any `Exception` now (returns `unreadable`) so activation can
  never 500 an upload.
- `generate_sqs` auto-detect (no `cif_name`) now prefers a `*_disordered.cif` (then any `.cif`) over the
  POSCAR-biased default resolver, so it won't grab a leftover ordered POSCAR from earlier in the session.

### Verify
In the worker: `activate_structure` on the disordered CuAu CIF returns `disordered: True` and writes
`CuAu_disordered.cif`; the SQS auto-detect picks that CIF even when a competing `POSCAR` is present.

### Lesson
POSCAR is an ordered-only format. Any structure-ingest path that canonicalises to POSCAR will reject
disordered inputs — disorder-consuming tools (SQS) need a CIF-preserving path end-to-end.

---

## Bug 4 — Provider rate-limits + agent quirks during SQS testing

### Symptoms (from a UI session)
1. "The language model is busy or rate-limited right now, and the backup models could not pick up the
   request" — repeatedly.
2. Agent refused a valid request: *"the `generate_sqs` tool does not have a `time_budget` parameter"*
   (it has `time_budget_s`).
3. A single turn showed both *"I've started a job…"* AND the rate-limit error — contradictory.

### Root causes
1. **BYOK + no real fallback.** The chain is groq→gemini→ollama. The Docker deploy has **no Ollama**, and
   the user typically has only a Groq key, so a Groq free-tier 429 (worsened by rapid repeated requests)
   has nothing to fall back to → "all providers unavailable".
2. **Parameter-name pedantry.** llama-3.3-70b refused over the exact name `time_budget` vs `time_budget_s`
   instead of mapping the user's intent.
3. **Mid-stream failure after a job started.** The job is enqueued in turn N; the *summary* turn N+1
   streams text past the 24-char commit threshold and then Groq 429s — `FallbackProvider` can't switch
   after commit, so it re-raises and `_friendly_error` is appended after the real "I've started a job"
   text.

### Fixes (all in `backend/app/agent/` + `tools/contracts.py`)
1. `providers/groq.py`: `AsyncGroq(..., max_retries=3)` — SDK retries transient 429/5xx with backoff and
   honours `Retry-After`, smoothing per-minute bursts before falling back.
2. `_friendly_error` now tells the user the actionable fix: add a **Gemini** key in Settings as a backup
   provider.
3. `contracts.py`: `time_budget_s` description spells out "a '30 second time budget' means
   time_budget_s=30"; `SYSTEM_PROMPT` adds a rule: map user values to the closest parameter and NEVER
   refuse by claiming a parameter "does not exist".
4. `graph.py` agent loop: wrap `provider.run` in try/except and track `started_job_msg`; if a provider
   fails *after* a job was enqueued this request, emit a coherent "✓ Your <type> job was queued (id …) —
   I couldn't write a summary just now, watch the job panel" instead of the scary all-down error.

### Note (not a code bug)
The fundamental constraint is BYOK free-tier limits. Practical guidance for the user: add a Gemini key as
a second provider, and don't fire many heavy requests back-to-back.
