"""Native function-calling agent for Materia (redesign §15).

The model itself decides when to call the four tools and writes the final
answer. There is **no** regex/JSON-from-prose planning anymore — tool calls
arrive as structured data from the provider (`agent/llm.py` → Gemini | Ollama),
the loop executes them, feeds results back, and repeats until the model returns a
plain answer.

Streaming SSE contract (unchanged — consumed by `api/chat.py` and the frontend):
    data: {"type":"status","value":...}   data: {"type":"token","value":...}
    data: [TOOL_START:<tool>]             data: [TOOL_END:<tool>:<status>]
    data: [FILES:{...}]                   data: [JOB:{...}]
    data: [DONE]                          data: [SESSION:<id>]
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, AsyncGenerator

from app.agent.llm import get_provider
from app.agent.providers.base import ToolCall
from app.agent.tool_schemas import TOOL_SPECS
from app.agent.tool_registry import CALLABLE_TOOL_MAP, TOOL_MAP
from app.core.context import set_request_identity
from app.core.logging import get_logger
from app.services.storage.file_service import (
    get_session_dir,
    list_new_files,
    find_best_poscar,
    _session_dir_var,
)

logger = get_logger(__name__)

# Safety cap on tool-call rounds per user turn (prevents runaway loops).
MAX_TURNS = 6

# Streamed text larger than this between tool rounds is unusual — kept only as a
# guard so a misbehaving model can't flood the stream.
THINKING_STATUS = "🧠 Thinking…"


SYSTEM_PROMPT = """\
You are Materia AI, an expert computational-materials-science assistant. You help \
users search materials databases, generate VASP inputs, and run atomistic \
simulations by calling the tools provided to you.

You have exactly four tools:
- search_materials — find materials by formula / element / properties.
- generate_vasp_inputs — build POSCAR + INCAR + KPOINTS for a material (fast).
- optimize_structure — relax a session structure with an ML potential (async job).
- run_md_simulation — run NVT/NPT molecular dynamics (async job).

Rules:
- When the user names a material by formula (e.g. "MoS2", "NaCl"), call \
search_materials FIRST, then pass the real `material_id` and `source` from the \
results to generate_vasp_inputs. Never invent an id.
- When the user gives a database id directly (e.g. "mp-19306"), you may call \
generate_vasp_inputs without searching.
- optimize_structure and run_md_simulation operate on a structure already in the \
session and are long-running: they return a job_id immediately. After calling \
one, tell the user the job has started and that progress appears in the job \
dashboard — do NOT claim final results you do not have.
- After a search, present the results as a compact Markdown table (id, formula, \
source, band gap, formation energy).
- For conceptual questions, greetings, or anything answerable from the \
conversation, just reply directly — do not call a tool.
- Be concise, accurate, and scientific. Use Markdown.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Argument resolution helpers (carried over — still useful as safety nets even
# though the model usually passes concrete values).
# ─────────────────────────────────────────────────────────────────────────────

POSCAR_ARG_KEYS = ["poscar_path", "poscar_name"]


def resolve_args(tool_name: str, tool_args: dict, session_dir: str) -> dict:
    """Resolve 'auto'/missing structure-file args to the best POSCAR in session."""
    resolved = dict(tool_args)
    for key in POSCAR_ARG_KEYS:
        if key not in resolved:
            continue
        val = resolved[key]
        if val in ("auto", "", None) or not Path(str(val)).exists():
            best = find_best_poscar(session_dir)
            if best:
                resolved[key] = best
                logger.info("[Agent] Resolved %s → %s", key, best)
    return resolved


def pick_material_from_results(step_results: list[dict]) -> dict | None:
    for result in reversed(step_results):
        if result.get("tool") != "search_materials":
            continue
        for material in result.get("materials", []):
            if material.get("has_structure", True):
                return material
    return None


def auto_fill_material_args(tool_args: dict, step_results: list[dict]) -> dict:
    """Fill material_id/source for generate_vasp_inputs from a prior search."""
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
    return resolved


def normalize_tool_status(status: str) -> str:
    return "success" if status == "ok" else (status or "unknown")


# ─────────────────────────────────────────────────────────────────────────────
# Trim a tool result before feeding it back to the model — keep the payload
# small (esp. material searches) while the full result still goes to the
# frontend via the [FILES:] event.
# ─────────────────────────────────────────────────────────────────────────────

_MATERIAL_LLM_FIELDS = (
    "id", "formula", "source", "band_gap_eV", "formation_energy_eV_per_atom",
    "energy_above_hull_eV_per_atom", "spacegroup_symbol", "dimensionality",
    "has_structure",
)


def _result_for_llm(result: dict) -> dict:
    compact = {k: v for k, v in result.items()
               if k not in ("materials", "files", "potentials")}
    materials = result.get("materials")
    if materials:
        compact["materials"] = [
            {k: m.get(k) for k in _MATERIAL_LLM_FIELDS if k in m}
            for m in materials[:10]
        ]
    if "files" in result:
        compact["files"] = result["files"]
    return compact


# ─────────────────────────────────────────────────────────────────────────────
# Tool execution — runs one tool call, emits the SSE side-channel events, and
# returns the raw result dict (for the [FILES:] payload + LLM feedback).
# ─────────────────────────────────────────────────────────────────────────────

async def _execute_tool(
    tc: ToolCall,
    queue: asyncio.Queue,
    session_id: str,
    session_dir: str,
    user_id: int | None,
    step_results: list[dict],
) -> dict:
    tool_name = tc.name
    tool_args = dict(tc.args or {})
    tool_meta = TOOL_MAP.get(tool_name)
    tool_fn = CALLABLE_TOOL_MAP.get(tool_name)

    if not tool_meta or not tool_fn:
        await queue.put(f"data: [TOOL_END:{tool_name}:error]\n\n")
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    label = tool_meta["label"]
    await queue.put(f"data: [TOOL_START:{tool_name}]\n\n")
    await queue.put(f"data: {json.dumps({'type': 'status', 'value': f'⚙ {label}…'})}\n\n")

    try:
        tool_args = resolve_args(tool_name, tool_args, session_dir)
        if tool_name == "generate_vasp_inputs":
            tool_args = auto_fill_material_args(tool_args, step_results)

        t_before = time.time()

        _sdir, _uid, _sid = session_dir, user_id, session_id

        def _run_tool():
            # ContextVar propagation async→thread is unreliable; set explicitly.
            _session_dir_var.set(_sdir)
            set_request_identity(_uid, _sid)
            return tool_fn(**tool_args)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_tool)

        status = normalize_tool_status(
            result.get("status", "unknown")) if isinstance(result, dict) else "unknown"
        new_files = list_new_files(session_id, t_before)

        files_payload = {
            "tool": tool_name,
            "label": label,
            "status": status,
            "msg": result.get("message", "") if isinstance(result, dict) else str(result),
            "files": new_files,
        }
        if isinstance(result, dict):
            for key in (
                "materials", "source_used", "sources_tried", "total_matching",
                "returned", "formula", "n_sites", "task", "encut", "kmesh",
                "elements", "files_written", "source", "material_id",
                "job_id", "type", "track",
            ):
                if key in result:
                    files_payload[key] = result[key]

        await queue.put(f"data: [TOOL_END:{tool_name}:{status}]\n\n")
        await queue.put(f"data: [FILES:{json.dumps(files_payload)}]\n\n")

        if isinstance(result, dict) and result.get("job_id"):
            job_event = {
                "job_id": result["job_id"],
                "type": result.get("type"),
                "status": result.get("status", "queued"),
            }
            await queue.put(f"data: [JOB:{json.dumps(job_event)}]\n\n")

        step_results.append(files_payload)
        return result if isinstance(result, dict) else {"status": status, "message": str(result)}

    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        await queue.put(f"data: [TOOL_END:{tool_name}:error]\n\n")
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# The agent loop.
# ─────────────────────────────────────────────────────────────────────────────

async def _agent_loop(
    messages: list[dict],
    session_id: str,
    user_id: int | None,
    session_dir: str,
    queue: asyncio.Queue,
) -> None:
    provider = get_provider()

    conv: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": m["role"], "content": m.get("content", "")} for m in messages
    ]
    step_results: list[dict] = []

    await queue.put(f"data: {json.dumps({'type': 'status', 'value': THINKING_STATUS})}\n\n")

    for _turn in range(MAX_TURNS):
        started_text = False

        async def on_text(delta: str):
            nonlocal started_text
            if not started_text:
                # first token of a streamed answer — clear the spinner
                await queue.put(f"data: {json.dumps({'type': 'status', 'value': ''})}\n\n")
                started_text = True
            await queue.put(f"data: {json.dumps({'type': 'token', 'value': delta})}\n\n")

        result = await provider.run(conv, TOOL_SPECS, on_text)

        if not result.tool_calls:
            break  # final natural-language answer already streamed

        # record the assistant's tool-calling turn
        conv.append({
            "role": "assistant",
            "content": result.text,
            "tool_calls": result.tool_calls,
        })

        for tc in result.tool_calls:
            raw = await _execute_tool(
                tc, queue, session_id, session_dir, user_id, step_results)
            conv.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": _result_for_llm(raw),
            })

        await queue.put(f"data: {json.dumps({'type': 'status', 'value': THINKING_STATUS})}\n\n")
    else:
        # exhausted MAX_TURNS without a final answer
        await queue.put(
            f"data: {json.dumps({'type': 'token', 'value': 'Reached the tool-call limit for this request. Let me know how you would like to proceed.'})}\n\n"
        )

    await queue.put(f"data: {json.dumps({'type': 'status', 'value': ''})}\n\n")
    await queue.put("data: [DONE]\n\n")
    await queue.put(f"data: [SESSION:{session_id}]\n\n")


# ─────────────────────────────────────────────────────────────────────────────
# Public API — called from chat.py token_generator
# ─────────────────────────────────────────────────────────────────────────────

async def run_agent(
    messages: list[dict],
    session_id: str,
    user_id: int | None = None,
) -> AsyncGenerator[str, None]:
    session_dir = str(get_session_dir(session_id))
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _run():
        try:
            await _agent_loop(messages, session_id, user_id, session_dir, queue)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            await queue.put(
                f"data: {json.dumps({'type': 'token', 'value': f'⚠ Agent error: {e}'})}\n\n")
            await queue.put("data: [DONE]\n\n")
            await queue.put(f"data: [SESSION:{session_id}]\n\n")
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(_run())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
