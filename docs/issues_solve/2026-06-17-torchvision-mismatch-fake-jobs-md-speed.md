# Simulation Jobs Debugging — torchvision mismatch, fake job IDs, slow MD

**Date:** 2026-06-17
**Area:** Docker backend image · Celery worker · agent LLM provider · MD performance
**Status:** ✅ Resolved (one follow-up left to the user: add a Groq API key)

This session fixed three separate issues that surfaced while rebuilding the Docker
stack from scratch and running simulations through the job dashboard. They are
documented together because they were diagnosed in one debugging chain.

---

## Issue 1 — Geometry-optimization job failed: `operator torchvision::nms does not exist`

### Symptom
A geometry-optimization (relaxation) job submitted from the chat failed almost
immediately. The Jobs panel showed:

> Geometry optimization — **Failed**
> ⚠️ Calculator error: `operator torchvision::nms does not exist`

The user initially suspected "torch is not installed."

### Why it happened (root cause)
torch **was** installed — the real problem was a **build mismatch between torch and
torchvision**:

| package | version in image | source |
|---------|------------------|--------|
| torch | `2.12.0+cpu` | PyTorch CPU wheel index (`download.pytorch.org/whl/cpu`) |
| torchvision | `0.27.0` (generic) | regular PyPI, pulled in transitively by **mattersim** |
| torchaudio | `2.11.0` (generic) | regular PyPI |

`torchvision` ships **compiled C++ operators** (such as `nms`) that are registered
against a *specific torch build*. When torch comes from the CPU index but
torchvision comes from default PyPI, the two builds don't match, the C++ operator
registration silently fails, and any code path that touches it explodes at runtime
with `operator torchvision::nms does not exist`.

`mattersim` is the package that dragged torchvision in — the Dockerfile only
pinned `torch` to the CPU index, so torchvision/torchaudio leaked in from PyPI.

### How we approached it
1. Read the Jobs-panel error carefully — it said `torchvision::nms`, **not** "no
   torch". That reframed the problem from "missing dependency" to "version mismatch".
2. Inspected the built image directly:
   ```bash
   docker run --rm materia-backend:dev pip list | grep -iE '^torch|torchvision|torchaudio'
   docker run --rm materia-backend:dev python -c "from torchvision.ops import nms"
   ```
   Confirmed the mismatch and reproduced the exact error.
3. Found the source: `pip show torchvision` → `Required-by: mattersim`.

### The fix
Install the **whole torch family together from the same CPU index, before**
`requirements.txt`, so all three are mutually compatible `+cpu` builds and
`mattersim` reuses them instead of pulling generic wheels.

`backend/Dockerfile`:
```dockerfile
RUN pip install --upgrade pip \
    && pip install --retries 5 --timeout 120 \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision torchaudio \
    && pip install --retries 5 --timeout 120 \
        --use-deprecated=legacy-resolver -r requirements.txt
```

### Verification
```text
torch 2.12.0+cpu | torchvision 0.27.0+cpu | nms OK ✅
```
Verified both in the image and inside the live running worker container.

### Lesson
> When you install **torch from a special index** (CPU or CUDA), install
> **torchvision and torchaudio from that same index in the same command**. Never
> let a downstream package pull torchvision from default PyPI — mismatched builds
> compile fine but crash at runtime with `operator torchvision::nms does not exist`.

---

## Issue 2 — Optimise "started a job and gave an ID" but nothing ran (fabricated job)

### Symptom
After fixing Issue 1, the user re-ran "optimise this structure as full relaxations".
The assistant replied that it had started a relaxation job and printed a job ID —
but the Jobs panel stayed empty. The user called it "fake information".

### Why it happened (root cause)
The assistant **hallucinated** the job. Proof from the database — only two jobs had
*ever* existed:
```text
type     | status
---------+--------
optimize | failed     (the Issue-1 one)
md       | running
```
No optimize job row was created for the re-run; the logs only showed
`Enqueued md job …`. The assistant generated a confirmation sentence with a
made-up ID **instead of actually calling the tool**.

The reason it misbehaved: **no working LLM provider**. The provider chain was
effectively dead:

| provider | status | reason |
|----------|--------|--------|
| groq (primary) | ❌ | `GROQ_API_KEY is not set` — fails every request |
| gemini (fallback) | ⚠️ | `503 UNAVAILABLE — high demand` (free tier overloaded) |
| ollama (last resort) | ❌ | `OLLAMA_BASE_URL` unset — unreachable |

With only an overloaded Gemini doing the work, it sometimes *narrates* a tool call
(writing prose that looks like a confirmation) rather than emitting a real function
call. The backend streams that text verbatim, so the user sees a confident but fake
"job started".

### How we approached it
1. Checked the source of truth — the `jobs` table — and confirmed no optimize row
   was created.
2. Grepped the api logs for provider behavior and found the groq-missing-key
   warnings and the gemini `503`.
3. Confirmed ollama was unreachable (`OLLAMA_BASE_URL` unset) and read how each
   provider resolves its key (`app/agent/providers/*.py`).

### The fix (partial — mitigation shipped, root cure pending)
- **Mitigation (shipped):** added an anti-hallucination guardrail to the agent
  system prompt (`app/agent/graph.py`) forbidding it from inventing a job/job_id,
  requiring it to report only the real id a tool returned, and to state plainly
  when no job was started and why.
- **Root cure (DONE):** added a Groq key via BYOK and fixed the provider so it
  actually reads it (see Issue 4). Groq is now the working primary provider —
  fast and reliable at tool-calling — which stops the agent narrating instead of
  acting. Verified end-to-end on 2026-06-17.

### Lesson
> A prompt guardrail *reduces* fabrication but cannot eliminate it. The real cure
> for "the AI claims it did something it didn't" is a **reliable LLM provider with
> solid tool-calling**. Always sanity-check agent claims against the source of
> truth (here, the `jobs` DB table) — the dashboard reads the DB and correctly
> showed nothing, which exposed the lie.

---

## Issue 3 — MD simulation very slow (~800 steps in 5 minutes)

### Symptom
A molecular-dynamics job took ~5 minutes to complete only ~800 of its steps.

### Why it happened (root cause)
This one was **real and working** — just CPU-bound:
- The job requested `nsw = 10000` steps (the old default).
- Each MD step is one full MACE force evaluation on CPU (~hundreds of ms).
- At ~2.7 steps/sec, 10000 steps ≈ **60 minutes**. The "800 steps in 5 min"
  observation matched exactly.
- torch was using only **10 of 20** CPU cores.

### How we approached it
1. Read the live job progress from the DB: `step 1140 / 10000 (11.4%)`, with energy
   and temperature updating — confirming real physics, not a hang.
2. Checked `torch.get_num_threads()` in the worker → 10 (host has 20 cores).

### The fix
Two code changes (rebuilt + redeployed):
1. **Use all CPU cores** — `app/jobs/worker.py` sets
   `OMP_NUM_THREADS`/`MKL`/`OpenBLAS`/`NUMEXPR` from `os.cpu_count()` **before**
   torch loads, plus `torch.set_num_threads(...)`. Verified: `OMP_NUM_THREADS=20,
   torch threads=20`. (On Oracle ARM it auto-uses the 4 cores there.)
2. **Lower the default MD step count** from `10000` → `2000` in
   `contracts.py`, `material_tools.py`, and `services/simulation/md.py`. Users can
   still request more, up to the `max_md_steps` ceiling. Verified: `default nsw = 2000`.

### Lesson
> "More steps" ≠ "better". For demos/CPU, 2000 MD steps is plenty; 10000 just costs
> 5× the wait. And on a single-job worker, give torch **all** the cores — the env
> vars must be set **before** numpy/torch import (native libs read them at load
> time), which is why the setup lives at the very top of `worker.py`.

---

## Issue 4 — BYOK Groq key saved but never used (agent kept falling back to Gemini)

### Symptom
The user pasted a valid Groq key in Settings (stored fine), but every chat still
logged `GROQ_API_KEY is not set` and fell back to Gemini. Jobs ran (via Gemini),
but Groq — the intended primary provider — was never used.

### Why it happened (root cause)
A real code bug in `app/agent/providers/groq.py`. The provider read the key from
the **boot-time settings object**:
```python
key = settings.groq_api_key          # read ONCE at app startup
```
But BYOK works by injecting the user's key into `os.environ["GROQ_API_KEY"]`
**per request** (`key_service.load_user_keys_into_env`). The groq provider never
looked at `os.environ`, so it never saw the pasted key. The **gemini** provider
did it correctly — `os.getenv("GEMINI_API_KEY") or settings.gemini_api_key` — which
is exactly why Gemini worked with BYOK and Groq didn't. Step 2.5 wired the key into
the env map but the groq provider was never updated to read from there.

### How we approached it
1. Confirmed the key was actually stored: `api_keys` table had a `groq` row for the
   user, encrypted, created seconds before the failing job.
2. Confirmed `chat.py` calls `load_user_keys_into_env(...)` before `run_agent(...)`.
3. Read `groq.py` and spotted it read `settings.groq_api_key` (static) instead of
   `os.getenv(...)` (per-request) — unlike the working gemini provider.

### The fix
`app/agent/providers/groq.py` — read the env var first, mirroring gemini:
```python
import os
...
key = os.getenv("GROQ_API_KEY") or settings.groq_api_key
```

### Verification
Re-sent a chat after redeploy:
```text
[Agent] LLM provider = groq            # no fallback
POST https://api.groq.com/openai/v1/chat/completions "HTTP/1.1 200 OK"  (x2)
optimize job e8a558329c48 -> succeeded in 33s
  "Optimization converged. Formula: Si6V3, E = -64.602028 eV, fmax = 0.0074 eV/Å"
```
Full BYOK → Groq → tool-call → job → success path confirmed.

### Lesson
> Any value that can be set **per-request** (BYOK keys) must be read **at call time**
> from the live source (`os.environ`), never from a config object captured at boot.
> When one provider works with BYOK and another doesn't, diff how each reads its key.

---

## Deploy notes carried out of this session
- The stack is hand-wired with individual `docker run` commands on the
  `materia-net` network (no `docker compose` installed locally). Recreating
  api/worker requires replaying the exact network/volumes/env — capture these with
  `docker inspect <name>` before removing a container.
- Rebuilding an image does **not** affect already-running containers; you must
  `docker rm -f` + `docker run` (or `compose up --force-recreate`) to pick up a new
  image.
- Containers run with `--restart no`, so they do **not** survive a reboot. For
  Oracle, use `--restart unless-stopped` (or a compose `restart:` policy).

## Open follow-up
- [x] Make Groq the working primary provider (the true cure for Issue 2). Done via
      BYOK + the `groq.py` env-read fix (Issue 4) — verified groq tool-calling
      end-to-end on 2026-06-17.
