
# app/core/agent.py
#
# LangGraph agent for MatMind
#
# Graph:
#   planner → step_picker → tool_executor → result_injector
#                 ↑                               |
#                 └──────── done_checker ←────────┘
#                                |
#                           summarizer → END
#
# Key fixes vs previous version:
#   1. ollama_raw() — bypasses stream_chat's SYSTEM_PROMPT for internal calls
#   2. Single-call planner — asks "JSON or []" directly, no broken classifier
#   3. summarizer — template-based, no extra LLM call (fast + reliable)
#   4. Every exit path sends [DONE] + [SESSION:] so frontend never hangs

import asyncio
import httpx
import json
import os
import re
import time
from pathlib import Path
from typing import AsyncGenerator, Any, TypedDict

from langgraph.graph import StateGraph, END

from app.agent.llm import stream_chat          # used only for conversational answers
from app.agent.tool_registry import CALLABLE_TOOL_MAP, TOOL_MAP
from app.core.config import settings
from app.core.logging import get_logger
from app.services.file_service import (
    get_session_dir,
    list_new_files,
    find_best_poscar,
)

logger = get_logger(__name__)

# ── Ollama connection (centralized in app.core.config) ────────────────────────
OLLAMA_BASE_URL = settings.ollama_base_url
OLLAMA_MODEL    = settings.ollama_model


# ─────────────────────────────────────────────────────────────────────────────
# ollama_raw — direct Ollama call with a CUSTOM system prompt.
# DOES NOT use SYSTEM_PROMPT from llm.py.
# Used for planner so Qwen3 doesn't answer as Materia instead of planning.
# ─────────────────────────────────────────────────────────────────────────────

async def ollama_raw(system: str, user: str) -> str:
    """
    Call Ollama with only a system + user message.
    Returns the complete response text with <think> blocks stripped.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    parts = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": True, "options": {"num_predict": 2048}},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        parts.append(token)
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

    raw = "".join(parts)
    # strip Qwen3 <think>...</think> blocks
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# AgentState
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages:        list[dict]   # full conversation for LLM
    session_id:      str
    session_dir:     str
    queue:           Any          # asyncio.Queue[str|None]

    plan:            list[dict]   # [{"tool":..,"args":..,"reason":..}, ...]
    current_step:    dict | None
    completed_steps: list[str]
    step_results:    list[dict]
    error:           str | None
    _last_result:    dict | None  # temp between tool_executor → result_injector


# ─────────────────────────────────────────────────────────────────────────────
# POSCAR helpers (unchanged from your original)
# ─────────────────────────────────────────────────────────────────────────────

POSCAR_ARG_KEYS = [
    "poscar_path", "initial_poscar_path", "final_poscar_path",
    "lower_poscar_path", "upper_poscar_path",
    "film_poscar_path",  "substrate_poscar_path",
]

POSCAR_REQUIRED_TOOLS = {
    "generate_vasp_poscar_with_vacancy_defects",
    "generate_vasp_poscar_with_substitution_defects",
    "generate_vasp_poscar_with_interstitial_defects",
    "generate_supercell_from_poscar",
    "generate_sqs_from_poscar",
    "generate_surface_slab_from_poscar",
    "customize_vasp_kpoints_with_accuracy",
    "generate_vasp_inputs_from_poscar",
    "generate_vasp_workflow_of_eos",
    "generate_vasp_workflow_of_elastic_constants",
    "generate_vasp_workflow_of_aimd",
    "generate_vasp_workflow_of_convergence_tests",
    "visualize_structure_from_poscar",
    "run_simulation_using_mlps",
}


def resolve_args(tool_name: str, tool_args: dict, session_dir: str) -> dict:
    resolved = dict(tool_args)
    

    for key in POSCAR_ARG_KEYS:
        if key not in resolved:
            continue
        val = resolved[key]
        if val in ("auto", "", None) or not Path(str(val)).exists():
            best = find_best_poscar(session_dir)
            if best:
                resolved[key] = best
                logger.info(f"[Agent] Resolved {key} → {best}")
    if tool_name in POSCAR_REQUIRED_TOOLS and "poscar_path" not in resolved:
        best = find_best_poscar(session_dir)
        if best:
            resolved["poscar_path"] = best
            logger.info(f"[Agent] Auto-added poscar_path → {best}")
    return resolved


async def q_put(queue: asyncio.Queue, event: str):
    await queue.put(event)


def pick_material_from_results(step_results: list[dict]) -> dict | None:
    for result in reversed(step_results):
        if result.get("tool") != "search_material":
            continue
        for material in result.get("materials", []):
            if material.get("has_structure", True):
                return material
    return None


def auto_fill_generate_poscar_args(tool_args: dict, step_results: list[dict]) -> dict:
    resolved = dict(tool_args)

    needs_id = resolved.get("material_id") in (None, "", "auto")
    needs_source = resolved.get("source") in (None, "", "auto")

    if not (needs_id or needs_source):
        return resolved

    material = pick_material_from_results(step_results)

    if not material:
        return resolved

    if needs_id:
        resolved["material_id"] = material.get("id")
    if needs_source:
        resolved["source"] = material.get("source")
    if not resolved.get("name"):
        resolved["name"] = material.get("formula")

    return resolved


def normalize_tool_status(status: str) -> str:
    if status == "ok":
        return "success"
    return status or "unknown"


def fmt_material_value(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return str(round(float(value), 4))
    except (TypeError, ValueError):
        return str(value)


# ─────────────────────────────────────────────────────────────────────────────
# NODE 1 — planner
#
# Single ollama_raw() call with a tight JSON-only prompt.
# If plan is empty → stream a conversational answer via stream_chat and close.
# ─────────────────────────────────────────────────────────────────────────────

TOOL_LIST_STR = "\n".join(
    f"- {name}: {meta['arg_desc']}"
    for name, meta in TOOL_MAP.items()
)

PLANNER_SYSTEM = f"""\
You are a task planner for a materials simulation assistant.

Given the user's request, decide if tools are needed and output a JSON plan.

OUTPUT RULES:
- If tools are needed, output ONLY a JSON array.
- If no tools are needed, output exactly [].
- Each step must be: {{"tool": "<fn_name>", "args": {{...}}, "reason": "<one sentence>", "show_summary": true/false}}.

WHEN TO USE TOOLS:
- Search/find materials in databases.
- Generate/create/download/save a POSCAR.
- Read, list, or rename files in the current session.

WHEN NOT TO USE TOOLS:
- General concept questions, explanations, greetings, or small talk.
- Questions already answerable from the visible conversation.

AVAILABLE TOOLS:
{TOOL_LIST_STR}

PLANNING RULES:
- For "find/search materials", use search_material only.
- For "generate/create/save POSCAR for <formula>", use TWO steps:
  1. search_material with the formula/element filters and show_summary false
  2. generate_poscar with {{"material_id": "auto", "source": "auto", "name": "<formula>"}} and show_summary true
- For "generate POSCAR for mp-123 / c2db:42 / oqmd:12345", use generate_poscar directly and infer source if obvious.
- read_file takes {{"name": "filename"}} or {{"name": "auto"}}.
- list_files takes {{}}.

EXAMPLES:
User: "Search MoS2" -> [{{"tool": "search_material", "args": {{"formula": "MoS2", "limit": 10}}, "reason": "Search databases for MoS2", "show_summary": true}}]
User: "Generate POSCAR for NaCl" -> [{{"tool": "search_material", "args": {{"formula": "NaCl", "limit": 5}}, "reason": "Find a NaCl structure", "show_summary": false}}, {{"tool": "generate_poscar", "args": {{"material_id": "auto", "source": "auto", "name": "NaCl"}}, "reason": "Generate a POSCAR from the best matching structure", "show_summary": true}}]
User: "What is in eos_cal.csv?" -> [{{"tool": "read_file", "args": {{"name": "eos_cal.csv"}}, "reason": "Read the requested file", "show_summary": false}}]
User: "List my files" -> [{{"tool": "list_files", "args": {{}}, "reason": "List session files", "show_summary": false}}]
User: "What is DFT?" -> []
"""

async def planner_node(state: AgentState) -> dict:
    queue       = state["queue"]
    user_msg    = state["messages"][-1]["content"]

    await q_put(queue, f"data: {json.dumps({'type': 'status', 'value': '🧠 Planning…'})}\n\n")

    raw = await ollama_raw(PLANNER_SYSTEM, user_msg)
    logger.info(f"[Agent] Planner raw: {raw[:120]!r}")

    # extract JSON array — robust against any leading/trailing prose
    plan = []
    array_match = re.search(r"\[.*\]", raw, re.DOTALL)
    if array_match:
        try:
            parsed = json.loads(array_match.group(0))
            if isinstance(parsed, list):
                plan = [s for s in parsed if isinstance(s, dict) and "tool" in s]
        except json.JSONDecodeError:
            pass

    logger.info(f"[Agent] Plan ({len(plan)} steps): {[s['tool'] for s in plan]}")

    if not plan:
        # ── conversational / explanation answer ───────────────────────────────
        # Use stream_chat (has SYSTEM_PROMPT) so Materia answers naturally.
        await q_put(queue, f"data: {json.dumps({'type': 'status', 'value': ''})}\n\n")
        async for token in stream_chat(state["messages"]):
            if not token.startswith("\n__TOOL__:"):
                await q_put(queue, f"data: {json.dumps({'type': 'token', 'value': token})}\n\n")
        # MUST close the stream here — graph exits to END after this node
        await q_put(queue, f"data: [DONE]\n\n")
        await q_put(queue, f"data: [SESSION:{state['session_id']}]\n\n")

    return {
        "plan":            plan,
        "completed_steps": [],
        "step_results":    [],
        "current_step":    None,
        "error":           None,
        "_last_result":    None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# NODE 2 — step_picker
# Picks the next uncompleted step from plan (handles duplicate tool names).
# ─────────────────────────────────────────────────────────────────────────────

async def step_picker_node(state: AgentState) -> dict:
    usage: dict[str, int] = {}
    for name in state["completed_steps"]:
        usage[name] = usage.get(name, 0) + 1

    counts: dict[str, int] = {}
    next_step = None
    for step in state["plan"]:
        t = step["tool"]
        counts[t] = counts.get(t, 0) + 1
        if counts[t] > usage.get(t, 0):
            next_step = step
            break

    logger.info(f"[Agent] step_picker → {next_step['tool'] if next_step else 'DONE'}")
    return {"current_step": next_step}


# ─────────────────────────────────────────────────────────────────────────────
# NODE 3 — tool_executor
# Runs the Materia tool in a thread pool, streams TOOL_START/END/FILES events.
# ─────────────────────────────────────────────────────────────────────────────

async def tool_executor_node(state: AgentState) -> dict:
    step        = state["current_step"]
    queue       = state["queue"]
    session_id  = state["session_id"]
    session_dir = state["session_dir"]

    tool_name = step["tool"]
    tool_args = dict(step.get("args", {}))
    tool_meta = TOOL_MAP.get(tool_name)

    # ── unknown tool ──────────────────────────────────────────────────────────
    if not tool_meta:
        err = f"⚠ Unknown tool: {tool_name}"
        await q_put(queue, f"data: [TOOL_END:{tool_name}:error]\n\n")
        await q_put(queue, f"data: {json.dumps({'type': 'token', 'value': err})}\n\n")
        return {"error": err, "_last_result": None}

    # ── POSCAR guard (skip for non-structure tools) ───────────────────────────
    NEEDS_POSCAR = {
        "generate_vasp_poscar_with_vacancy_defects",
        "generate_vasp_poscar_with_substitution_defects",
        "generate_vasp_poscar_with_interstitial_defects",
        "generate_supercell_from_poscar",
        "generate_sqs_from_poscar",
        "generate_surface_slab_from_poscar",
        "customize_vasp_kpoints_with_accuracy",
        "generate_vasp_inputs_from_poscar",
        "generate_vasp_workflow_of_eos",
        "generate_vasp_workflow_of_elastic_constants",
        "generate_vasp_workflow_of_aimd",
        "generate_vasp_workflow_of_convergence_tests",
        "visualize_structure_from_poscar",
        "run_simulation_using_mlps",
    }
    if tool_name in NEEDS_POSCAR and not find_best_poscar(session_dir):
        err = f"⚠ No POSCAR found — cannot run {tool_name}"
        await q_put(queue, f"data: [TOOL_END:{tool_name}:error]\n\n")
        await q_put(queue, f"data: {json.dumps({'type': 'token', 'value': err})}\n\n")
        return {"error": err, "_last_result": None}

    # ── NEB guard ─────────────────────────────────────────────────────────────
    if tool_name == "generate_vasp_workflow_of_neb":
        if not tool_args.get("initial_poscar_path") or not tool_args.get("final_poscar_path"):
            err = "⚠ NEB requires both initial_poscar_path and final_poscar_path."
            await q_put(queue, f"data: [TOOL_END:{tool_name}:error]\n\n")
            await q_put(queue, f"data: {json.dumps({'type': 'token', 'value': err})}\n\n")
            return {"error": err, "_last_result": None}

    # ── API-key guard ──────────────────────────────────────────────────────
    mp_api_key = os.environ.get("MP_API_KEY")
    if tool_name == "generate_vasp_poscar" and not mp_api_key:

    

        msg = (
            "Materials Project API key is required before I can generate "
            "POSCAR files. Please save your Materials Project API key below, "
            "then I will retry this request."
        )
        await q_put(queue, f"data: {json.dumps({'type': 'token', 'value': msg})}\n\n")
        await q_put(queue, "data: [NEED_API_KEY:mp]\n\n")
        return {
            "error": msg,
            "plan": [step],
            "_last_result": {
                "tool": tool_name,
                "label": tool_meta["label"],
                "status": "needs_api_key",
                "msg": msg,
                "files": [],
                "show_summary": False,
            },
        }

    # ── show spinner for simulation tools, silent for utility tools ──────────
    show_summary  = step.get("show_summary", True)
    is_utility    = tool_name in ("list_files", "read_file", "rename_file")

    if not is_utility:
        step_reason = step.get("reason", tool_meta["label"])
        intro_token = f"I'll {step_reason.lower().rstrip('.')}.\n"
        await q_put(queue, f"data: {json.dumps({'type': 'token', 'value': intro_token})}\n\n")

    await q_put(queue, f"data: [TOOL_START:{tool_name}]\n\n")
    if not is_utility:
        label = tool_meta["label"]
        await q_put(queue, f"data: {json.dumps({'type': 'status', 'value': f'⚙ {label}…'})}\n\n")

    try:
        tool_args = resolve_args(tool_name, tool_args, session_dir)
        if tool_name == "generate_poscar":
            tool_args = auto_fill_generate_poscar_args(tool_args, state["step_results"])
            if tool_args.get("material_id") in (None, "", "auto") or tool_args.get("source") in (None, "", "auto"):
                raise ValueError("No material was selected for POSCAR generation. Search for a material first.")

        if tool_name == "generate_vasp_poscar" and mp_api_key:
            tool_args["mp_api_key"] = mp_api_key

        t_before = time.time()

        tool_fn = CALLABLE_TOOL_MAP.get(tool_name)
        if not tool_fn:
            raise ValueError(f"Function {tool_name} is not registered as a callable tool")

        _sdir = session_dir   # capture for closure

        def _run_tool():
            # Set session dir inside the thread — ContextVar propagation
            # from async→thread is unreliable; explicit set is guaranteed.
            from app.tools.utils import _session_dir_var
            _session_dir_var.set(_sdir)
            return tool_fn(**tool_args)

        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_tool)

        status    = normalize_tool_status(result.get("status",  "unknown")) if isinstance(result, dict) else "unknown"
        msg       = result.get("message", "")        if isinstance(result, dict) else str(result)
        new_files = list_new_files(session_id, t_before)

        # ── for read_file: pass file content/metadata to the answer step ───────
        if tool_name == "read_file":
            content = result.get("content", "") if isinstance(result, dict) else str(result)
            if not content and status != "success":
                content = msg or "The requested file could not be read."
            await q_put(queue, f"data: [TOOL_END:{tool_name}:{status}]\n\n")
            tool_result_obj = {
                "tool":         tool_name,
                "label":        tool_meta["label"],
                "status":       status,
                "msg":          msg,
                "files":        [],
                "file_name":    result.get("name") if isinstance(result, dict) else None,
                "rel_path":     result.get("rel_path") if isinstance(result, dict) else None,
                "file_content": content,
                "truncated":    result.get("truncated", False) if isinstance(result, dict) else False,
                "show_summary": False,
            }
            return {"error": None, "_last_result": tool_result_obj}

        # ── for list_files: just pass file list as context ────────────────────
        if tool_name == "list_files":
            files_list = result.get("files", []) if isinstance(result, dict) else []
            await q_put(queue, f"data: [TOOL_END:{tool_name}:{status}]\n\n")
            tool_result_obj = {
                "tool":         tool_name,
                "label":        tool_meta["label"],
                "status":       status,
                "msg":          msg,
                "files":        [],
                "files_list":   files_list,   # pass to result_injector for context
                "show_summary": False,
            }
            return {"error": None, "_last_result": tool_result_obj}

        # ── standard material/simulation tool ─────────────────────────────────
        tool_result_obj = {
            "tool":         tool_name,
            "label":        tool_meta["label"],
            "status":       status,
            "msg":          msg,
            "files":        new_files,
            "show_summary": show_summary,
        }
        if isinstance(result, dict):
            for key in (
                "materials",
                "source_used",
                "sources_tried",
                "total_matching",
                "returned",
                "formula",
                "n_sites",
                "lattice_a",
                "lattice_b",
                "lattice_c",
                "poscar_path",
                "named_path",
                "files_written",
                "source",
                "material_id",
            ):
                if key in result:
                    tool_result_obj[key] = result[key]

        await q_put(queue, f"data: [TOOL_END:{tool_name}:{status}]\n\n")
        await q_put(queue, f"data: [FILES:{json.dumps(tool_result_obj)}]\n\n")

        return {"error": None, "_last_result": tool_result_obj}

    except Exception as e:
        import traceback
        traceback.print_exc()
        err = str(e)
        await q_put(queue, f"data: [TOOL_END:{tool_name}:error]\n\n")
        await q_put(queue, f"data: {json.dumps({'type': 'token', 'value': f'⚠ {err}'})}\n\n")
        return {"error": err, "_last_result": None}

# ─────────────────────────────────────────────────────────────────────────────
# NODE 4 — result_injector
# Records completed step. Prevents re-running.
# ─────────────────────────────────────────────────────────────────────────────

async def result_injector_node(state: AgentState) -> dict:
    last      = state.get("_last_result")
    tool_name = state["current_step"]["tool"] if state["current_step"] else ""

    new_results   = list(state["step_results"])
    new_completed = list(state["completed_steps"])

    if last:
        new_results.append(last)
    new_completed.append(tool_name)   # mark done even on error

    return {
        "step_results":    new_results,
        "completed_steps": new_completed,
        "_last_result":    None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# NODE 5 — done_checker  (routing function)
# ─────────────────────────────────────────────────────────────────────────────

def done_checker_node(state: AgentState) -> str:
    completed_counts: dict[str, int] = {}
    for name in state["completed_steps"]:
        completed_counts[name] = completed_counts.get(name, 0) + 1

    plan_counts: dict[str, int] = {}
    for step in state["plan"]:
        t = step["tool"]
        plan_counts[t] = plan_counts.get(t, 0) + 1

    for tool, needed in plan_counts.items():
        if completed_counts.get(tool, 0) < needed:
            logger.info("[Agent] done_checker → continue")
            return "continue"

    logger.info("[Agent] done_checker → done")
    return "done"


# ─────────────────────────────────────────────────────────────────────────────
# NODE 6 — summarizer
# Template-based summary — NO extra LLM call. Fast and always works.
# Streams a concise done message then closes the SSE stream.
# ─────────────────────────────────────────────────────────────────────────────


async def summarizer_node(state: AgentState) -> dict:
    queue        = state["queue"]
    step_results = state["step_results"]

    await q_put(queue, f"data: {json.dumps({'type': 'status', 'value': ''})}\n\n")

    # File utilities feed their results back into the model so the response is
    # grounded in the actual session file values instead of a generic answer.
    needs_llm_explanation = any(
        r.get("file_content") or r.get("files_list")
        for r in step_results
    )

    if needs_llm_explanation:
        context_parts = []
        for r in step_results:
            if r.get("file_content"):
                file_label = r.get("rel_path") or r.get("file_name") or "requested file"
                truncated_note = "\nNote: content was truncated for chat context." if r.get("truncated") else ""
                context_parts.append(
                    f"File: {file_label}\nRead status: {r.get('status')}\nTool message: {r.get('msg', '')}{truncated_note}\n\nContent and extracted values:\n{r['file_content']}"
                )
            elif r.get("files_list"):
                context_parts.append(
                    "Files in session:\n" + "\n".join(f"- {f}" for f in r["files_list"])
                )

        if context_parts:
            original_question = state["messages"][-1]["content"] if state["messages"] else ""
            context = "\n\n---\n\n".join(context_parts)
            answer = await ollama_raw(
                """
You answer questions about files in a materials-simulation session.
Use only the supplied file content, extracted table summaries, and file list.
If the user asks for a numeric value, report the exact value(s) visible in the supplied data and name the column/file when possible.
If the value is not present, say it is not present in the provided file content.
Do not invent file values. Do not call tools. Keep the answer concise but include enough detail to be useful.
""".strip(),
                f"User question:\n{original_question}\n\nSession file data:\n{context}\n\nAnswer based only on the file data above.",
            )
            if answer:
                await q_put(
                    queue,
                    f"data: {json.dumps({'type': 'token', 'value': answer})}\n\n"
                )

    else:
        material_searches = [
            r for r in step_results
            if r.get("tool") == "search_material" and r.get("show_summary", True)
        ]
        if material_searches:
            lines: list[str] = []
            for r in material_searches:
                lines.append(r.get("msg") or "Material search completed.")
                materials = r.get("materials", [])
                if materials:
                    lines.append("")
                    lines.append("| ID | Formula | Source | Gap (eV) | Formation E |")
                    lines.append("| --- | --- | --- | ---: | ---: |")
                    for m in materials[:10]:
                        lines.append(
                            "| {id} | {formula} | {source} | {gap} | {form} |".format(
                                id=m.get("id", ""),
                                formula=m.get("formula", ""),
                                source=m.get("source", ""),
                                gap=fmt_material_value(m.get("gap_pbe")),
                                form=fmt_material_value(m.get("formation_energy")),
                            )
                        )
                    lines.append("")
                    lines.append("Use one of these IDs if you want me to generate a POSCAR for a specific result.")
                elif r.get("status") != "success":
                    lines.append(r.get("msg") or "No matching materials were found.")

            summary_text = "\n".join(lines)
            await q_put(
                queue,
                f"data: {json.dumps({'type': 'token', 'value': summary_text})}\n\n"
            )

        # simulation tools — show completion summary
        show_any = any(
            r.get("show_summary", True) and r.get("tool") != "search_material"
            for r in step_results
        )
        if show_any and step_results:
            lines = ["**Workflow completed.**\n"]
            for r in step_results:
                if not r.get("show_summary", True) or r.get("tool") == "search_material":
                    continue
                icon   = "✅" if r["status"] == "success" else "⚠"
                label  = r.get("label", r["tool"])
                fcount = len(r.get("files", []))
                fstr   = f" ({fcount} file{'s' if fcount != 1 else ''} generated)" if fcount else ""
                lines.append(f"{icon} {label}{fstr}")

            summary = "\n".join(lines)
            await q_put(
                queue,
                f"data: {json.dumps({'type': 'token', 'value': summary})}\n\n"
            )

    await q_put(queue, f"data: [DONE]\n\n")
    await q_put(queue, f"data: [SESSION:{state['session_id']}]\n\n")
    return {}

# ─────────────────────────────────────────────────────────────────────────────
# Build graph
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(AgentState)

    g.add_node("planner",         planner_node)
    g.add_node("step_picker",     step_picker_node)
    g.add_node("tool_executor",   tool_executor_node)
    g.add_node("result_injector", result_injector_node)
    g.add_node("summarizer",      summarizer_node)

    g.set_entry_point("planner")

    # planner → step_picker if tools needed, else END
    # (DONE/SESSION already sent inside planner_node for the no-tools path)
    g.add_conditional_edges(
        "planner",
        lambda s: "step_picker" if s["plan"] else END,
    )

    g.add_edge("step_picker",     "tool_executor")
    g.add_edge("tool_executor",   "result_injector")

    g.add_conditional_edges(
        "result_injector",
        done_checker_node,
        {"continue": "step_picker", "done": "summarizer"},
    )

    g.add_edge("summarizer", END)
    return g.compile()


AGENT_GRAPH = build_graph()


# ─────────────────────────────────────────────────────────────────────────────
# Public API — called from chat.py token_generator
# ─────────────────────────────────────────────────────────────────────────────


async def run_agent(
    messages:   list[dict],
    session_id: str,
) -> AsyncGenerator[str, None]:
    session_dir = str(get_session_dir(session_id))
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    initial_state: AgentState = {
        "messages":        messages,
        "session_id":      session_id,
        "session_dir":     session_dir,
        "queue":           queue,
        "plan":            [],
        "current_step":    None,
        "completed_steps": [],
        "step_results":    [],
        "error":           None,
        "_last_result":    None,
    }

    # Run the graph in a background task so we can drain the queue
    # concurrently — this is what makes streaming work step-by-step
    async def _run_graph():
        try:
            await AGENT_GRAPH.ainvoke(initial_state)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await queue.put(
                f"data: {json.dumps({'type': 'token', 'value': f'⚠ Agent error: {e}'})}\n\n"
            )
            await queue.put(f"data: [DONE]\n\n")
            await queue.put(f"data: [SESSION:{session_id}]\n\n")
        finally:
            await queue.put(None)   # sentinel — tells consumer to stop

    # Start graph in background — don't await it here
    graph_task = asyncio.create_task(_run_graph())

    # Drain queue as items arrive — this yields SSE events immediately
    # as each node puts them, not after the whole graph finishes
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        # Make sure the graph task is cleaned up even if client disconnects
        if not graph_task.done():
            graph_task.cancel()
            try:
                await graph_task
            except asyncio.CancelledError:
                pass
