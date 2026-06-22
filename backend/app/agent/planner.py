"""Pre-execution planner for the Materia agent.

Before running a *multi-step* tool workflow, the agent first asks the model to
sketch an ordered plan (which tools, in what order, to what end). The plan is
shown to the user in the frontend with a Confirm / Cancel gate; only on Confirm
does `graph.run_agent` actually execute the tools.

This is a single, tools-free LLM call that returns structured JSON — it never
runs anything. It is deliberately cheap and best-effort: if the model errors or
returns unparseable output, `make_plan` returns ``None`` and the caller falls
back to running the request directly (no confirmation gate), so planning can
never block a request.

Returned plan shape (after validation)::

    {
      "needs_tools": bool,        # does answering require any tool?
      "summary":     str,         # one-line description of the workflow
      "steps": [                  # ordered, only real tool names
          {"tool": "search_materials", "title": "...", "detail": "..."},
          ...
      ],
      "final_output": str,        # what the user will get at the end
    }

The confirmation gate fires only when ``len(steps) >= 2`` (multi-tool); single
tool calls and plain conversation run straight through.
"""

from __future__ import annotations

import json

from app.agent.llm import get_provider
from app.agent.tool_registry import TOOL_MAP, TOOL_REGISTRY
from app.core.logging import get_logger

logger = get_logger(__name__)


def _tool_catalog() -> str:
    """One ``name — label`` line per real tool, for the planner prompt."""
    return "\n".join(f"- {t['fn_name']} — {t['label']}" for t in TOOL_REGISTRY)


PLANNER_PROMPT = f"""\
You are the PLANNER for Materia AI, a computational-materials-science assistant.
Given the conversation, decide whether answering the user's latest request needs \
any of the tools below, and if so, lay out the ordered steps.

You do NOT execute anything. You only produce a plan. Respond with a SINGLE JSON \
object and nothing else (no prose, no Markdown fences).

Available tools (use these exact names):
{_tool_catalog()}

Planning rules:
- If the request is a greeting, a conceptual question, or anything answerable \
from the conversation without tools, return "needs_tools": false with an empty \
"steps" list.
- When the user names a material by formula (e.g. "MoS2"), the FIRST step must be \
search_materials; a later generate_* step then uses that result. When the user \
gives a database id directly (e.g. "mp-19306"), you may skip the search.
- When the user refers to "this"/"the uploaded"/"my" file, the FIRST step is \
read_file to load and activate it.
- Order the steps the way they must actually run (search before generate; build \
the structure before generating its VASP inputs; load both endpoints before \
compute_neb, etc.). Only list tools that are genuinely needed.
- Keep each step's "title" short (≤6 words) and "detail" to one plain sentence a \
beginner can follow. Do NOT invent ids, paths, or parameters in the detail.
- "final_output" describes the concrete deliverable(s) the user ends up with \
(e.g. "A 2×2×1 MoS2 supercell plus a full VASP input set: POSCAR, INCAR, KPOINTS").

JSON schema to return:
{{
  "needs_tools": true | false,
  "summary": "<one line>",
  "steps": [
    {{"tool": "<exact tool name>", "title": "<short>", "detail": "<one sentence>"}}
  ],
  "final_output": "<what the user gets, or empty if no tools>"
}}
"""


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply (tolerant of fences)."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip ```json … ``` fences
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _validate(raw: dict) -> dict | None:
    """Coerce the model's JSON into the canonical plan shape; drop bad steps."""
    if not isinstance(raw, dict):
        return None

    steps_in = raw.get("steps") or []
    steps: list[dict] = []
    for s in steps_in:
        if not isinstance(s, dict):
            continue
        tool = s.get("tool")
        if tool not in TOOL_MAP:  # ignore hallucinated tool names
            continue
        steps.append({
            "tool": tool,
            "title": str(s.get("title") or TOOL_MAP[tool]["label"]).strip(),
            "detail": str(s.get("detail") or "").strip(),
        })

    needs_tools = bool(raw.get("needs_tools")) and len(steps) > 0
    return {
        "needs_tools": needs_tools,
        "summary": str(raw.get("summary") or "").strip(),
        "steps": steps,
        "final_output": str(raw.get("final_output") or "").strip(),
    }


async def make_plan(messages: list[dict]) -> dict | None:
    """Best-effort: return a validated plan, or ``None`` to skip the gate.

    ``messages`` is the neutral conversation (user/assistant text turns). Tool
    turns, if any, are ignored — the planner reasons from the dialogue only.
    """
    convo = [{"role": "system", "content": PLANNER_PROMPT}]
    for m in messages:
        role = m.get("role")
        if role in ("user", "assistant") and m.get("content"):
            convo.append({"role": role, "content": m["content"]})

    async def _noop(_delta: str) -> None:  # planner output is not streamed
        return None

    try:
        provider = get_provider()
        result = await provider.run(convo, [], _noop)  # no tools → text only
    except Exception as e:  # noqa: BLE001 — planning must never block a request
        logger.warning("[Planner] LLM call failed, skipping plan gate: %s", e)
        return None

    raw = _extract_json(result.text)
    if raw is None:
        logger.warning("[Planner] Could not parse plan JSON; skipping plan gate.")
        return None

    return _validate(raw)
