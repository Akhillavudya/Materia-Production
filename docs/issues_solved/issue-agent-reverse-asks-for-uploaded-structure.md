# issue-agent-reverse-asks-for-uploaded-structure

## Symptom
A user (PhD tester) uploaded a structure file, then asked the agent to do something
with it (e.g. "optimize this", "generate VASP inputs", "make a 2×2×1 supercell").
Instead of acting, the agent **asked the user to provide/upload a structure** — one
they had *already* uploaded moments earlier. The uploaded structure was in fact active
in the session, so the request should have just run.

## Root cause (why the bug came)
The chat endpoint sent the LLM **only the conversation text history**:

```python
messages_for_llm = [{"role": m.role, "content": m.content} for m in history]
```

Nothing in that payload told the model that a structure had been uploaded or was
active. The pieces underneath were all fine:

- uploads auto-activate a POSCAR (`_activate_uploads` → `activate_structure`), and
- the tools fall back to the active structure when no file is named
  (`find_structure_in_session(None)` / `find_best_poscar`).

But the **agent could not see any of that state**. With no signal that a structure
existed, the model did the "safe" thing and asked the user for one — a reverse-ask for
something already present. The system prompt even says to operate on "a structure
already in the session", but the model had no way to know one *was* in the session.

## How we fixed it
Inject a live, per-turn **session-state note** describing the active structure, so the
agent (and the planner) know a structure is present and use it by default.

1. New helper `session_structure_context(session_dir)` in `app/agent/graph.py`:
   - uses `find_best_poscar` to locate the active structure;
   - returns a one-line note like
     `SESSION STATE: an ACTIVE structure is already loaded in this session: POSCAR
     (NaCl, 2 atoms). … operate on this active structure — do NOT ask the user to
     provide or upload a structure …`;
   - returns `None` when the session genuinely has no structure (so the agent still
     asks in that legitimate case).

2. `_agent_loop` (executing agent) appends this note as a second system message right
   after the main system prompt — this is where the user-facing reply is generated, so
   it is what actually stops the reverse-ask.

3. The planner (`make_plan`) now accepts an optional `context` string and appends it to
   its prompt; `chat.py` passes the same note in, so the plan-gate won't propose a
   redundant "upload a structure" step.

## Files changed
- `backend/app/agent/graph.py` — added `session_structure_context()`; inject it in
  `_agent_loop`.
- `backend/app/agent/planner.py` — `make_plan(messages, context=None)` appends context
  to the planner prompt.
- `backend/app/api/chat.py` — import the helper + `get_session_dir`; pass the active-
  structure context into `make_plan`.

## How to verify
- Unit-level: `session_structure_context()` on an empty temp dir returns `None`; after
  writing a `POSCAR` it returns a note naming the file, formula, and atom count.
- End-to-end: upload a POSCAR, then say "optimize this" (or "generate VASP inputs")
  **without** naming a file → the agent runs the tool on the active structure instead
  of asking for one. In a fresh session with no structure, asking still prompts for a
  file (unchanged).

## Lesson
An LLM agent can only reason about state it can *see*. Auto-activating an upload and
adding tool-side fallbacks is not enough if the model is never told the state exists —
it will make conservative, wrong choices (like asking for a file that is already
present). Inject the relevant live session state (active structure, key files) into the
prompt each turn, and make the injection self-suppressing (`None` when there is nothing
to say) so it never fabricates a structure that is not there.
