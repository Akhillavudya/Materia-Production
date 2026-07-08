# issue-groq-free-tier-413-removed

## Symptom
Groq was configured as a hosted fallback provider (chain `gemini → groq → ollama`),
but **every** real agent request to Groq failed before the model ran:

> Request too large for model `llama-3.3-70b-versatile` … service tier `on_demand`
> on tokens per minute (TPM): Limit …  (HTTP **413 Payload Too Large**)

So Groq contributed **zero** working requests in production, and the T4 reliability
benchmark could never complete a Groq pass. It appeared "present but partial" while
actually being non-functional as a fallback.

## Root cause
Every Materia agent call ships the full tool contract to the model:
`SYSTEM_PROMPT` (~2 k tokens) + **23 tool schemas** (~8.6 k tokens) ≈ **10.6 k tokens
per call**. Groq's **free** tier (`on_demand`) enforces a per-request
**tokens-per-minute (TPM)** ceiling that this payload exceeds, so Groq returns 413
*before* inference — a hard structural limit, not a transient daily-quota issue that
extra keys or waiting would fix. A trimmed 5-tool payload passes, confirming schema
size is the blocker.

Earlier docs mis-described the blocker as a "daily token cap (~100 k tokens/day)".
That framing implied headroom/rotation could eventually complete a pass; the real
limit is per-request TPM, which cannot. Because Gemini's free tier is *request*-metered
(not token-metered), the same 10.6 k-token payload is fine on Gemini — which is why
Gemini was already the primary and scored 37/37 on T4.

Net: Groq could not serve a single real call, so it was never actually providing
resilience. The real resilience is Gemini multi-key rotation (`_keypool.py`, web) +
Ollama (desktop-offline).

## How we fixed it
Removed Groq entirely rather than leaving a dead fallback:

- **Provider layer:** deleted `agent/providers/groq.py`; `_FALLBACK_CHAIN` is now
  `{"gemini": ["ollama"]}`; `_build_provider` no longer knows `groq`; `_keypool.py`
  docstring is Gemini-only.
- **Config:** dropped `groq_api_key` / `groq_model` settings, the `groq` auto-resolve
  branch, and the factory line; `resolved_provider` is now gemini-else-ollama.
- **Key handling / API:** removed `groq` from `KEY_ENV_MAP`; the production BYOK gate
  and `NEED_API_KEY` marker in `api/chat.py` now reference **gemini**.
- **Dependencies:** removed the `groq` SDK from `requirements.txt`,
  `requirements-test.txt`, and the desktop PyInstaller `HIDDEN_IMPORTS` / `COPY_METADATA`.
- **Frontend:** removed the Groq entry from `ApiKeyForm` `SERVICE_INFO` and from
  `SettingsPanel` (provider list, onboarding bullet, key-pool flag).
- **Docs:** `AGENTS.md`, `docs/information.md`, and `docs/validation_results/T4_agent_reliability.md`
  now describe Gemini-only, with a short "why Groq was dropped" note carrying the
  corrected 413/TPM explanation.

## Files changed
- `backend/app/agent/llm.py`, `backend/app/agent/providers/groq.py` (deleted),
  `backend/app/agent/providers/_keypool.py`, `backend/app/agent/graph.py`
- `backend/app/core/config.py`, `backend/app/services/key_service.py`, `backend/app/api/chat.py`
- `backend/requirements.txt`, `backend/requirements-test.txt`, `backend/tests/unit/test_encryption.py`
- `frontend/src/features/chat/ApiKeyForm.jsx`, `frontend/src/features/settings/SettingsPanel.jsx`
- `desktop/scripts/build_backend.py`, `desktop/README.md`
- `AGENTS.md`, `docs/information.md`, `docs/validation_results/T4_agent_reliability.md`

## How to verify
- `python -c "from app.agent.llm import _FALLBACK_CHAIN, _build_provider"` →
  chain is `{'gemini': ['ollama']}`; `_build_provider('groq')` raises `ValueError`.
- `import app.agent.graph` succeeds (import-time schema/registry drift guard passes).
- `grep -rniI groq backend/app frontend/src` → no live references (only doc history).
- Backend unit suite green: `python -m pytest tests/unit -q`
  (deselect `test_heavy_tools_gate.py::test_enabled_passes_the_gate`, which needs a
  local Postgres).

## Lesson
A "fallback" that can't serve one real request is worse than no fallback — it looks
like resilience while providing none, and it hid behind an inaccurate "daily cap"
story. When a free tier is **token**-metered, a fixed large per-call payload (here the
23-tool schema, ~10.6 k tokens) can breach a **per-request** ceiling *before* inference,
which no amount of quota rotation fixes. Measure the provider against the *actual*
production payload, not a trimmed probe, before trusting it as a backup.
