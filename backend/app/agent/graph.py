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
    data: [PLAN:{...}]                    (multi-tool confirmation gate; planner.py)
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
users search materials databases, work with their uploaded structures, generate \
VASP inputs, and run atomistic simulations by calling the tools provided to you.

Your tools:
- search_materials — find materials by formula / element / properties.
- generate_vasp_inputs — build the FULL VASP input set (POSCAR + INCAR + KPOINTS) (fast).
- generate_poscar — build ONLY a POSCAR, nothing else (fast).
- generate_kpoints — write ONLY a KPOINTS file at an accuracy level (Low/Medium/High/\
Custom kppa; Γ-centered by default) (fast).
- make_supercell — replicate a cell into a supercell (fast).
- add_vacuum — add vacuum padding along an axis, e.g. for 2D layers (fast).
- make_slab — cut a surface slab along a Miller index; set `layers` for an exact \
atomic-layer count; vacuum included (fast). For an in-plane supercell or a different \
vacuum, chain make_supercell / add_vacuum afterwards.
- add_adsorbate — adsorb a molecule (CO2, CO, H2O, O, H…) onto the active slab; \
geometric by default (fast), or relax=true for an accurate ML-relaxed adsorption-energy \
job (async).
- convert_structure — write a structure in another format (poscar/cif/xyz/cssr/json) (fast).
- analyze_symmetry — report space group / symmetry of a session structure (fast).
- create_vacancy / create_substitution / create_interstitial — make point-defect \
structures from a session structure (fast).
- read_file — read/parse a file the user uploaded; for a structure it becomes the \
active structure for later steps.
- list_files — list the files in the current session.
- list_models — list the available ML potentials (MACE, MatterSim) and variants.
- optimize_structure — relax a session structure with an ML potential (async job).
- run_md_simulation — run NVT/NPT molecular dynamics (async job).
- compute_elastic_tensor — compute the elastic tensor + mechanical moduli (K, G, E, \
ν, Pugh, Born stability) with an ML potential (async job).
- compute_phonons — compute the phonon band structure + DOS via finite displacements \
with an ML potential; reports min frequency / dynamic stability (async job).
- generate_sqs — generate a Special Quasi-random Structure for a DISORDERED input \
(partial site occupancies) via ATAT mcsqs (async job).
- compute_neb — compute a migration/diffusion barrier (Nudged Elastic Band) between \
TWO session structures (an initial state and a final state) with an ML potential; \
returns the forward/reverse activation barrier and a minimum-energy-path plot \
(async job). Needs both endpoints: poscar_name (initial) and final_poscar_name (final).

Rules:
- When the user names a material by formula (e.g. "MoS2", "NaCl"), call \
search_materials FIRST, then pass the real `material_id` and `source` from the \
results to generate_vasp_inputs / generate_poscar. Never invent an id.
- When the user gives a database id directly (e.g. "mp-19306"), you may generate \
inputs without searching.
- POSCAR only → generate_poscar. Full VASP input set → generate_vasp_inputs.
- When the user refers to "this", "the uploaded", or "my" file/structure (or has \
just uploaded one), call read_file FIRST to load and activate it, then run the \
requested workflow (optimize_structure, run_md_simulation, generate_vasp_inputs…). \
Use list_files when the user asks what files/structures exist.
- Respect a user-named model (e.g. "MatterSim Large", "MACE-MP") by passing \
calculator_type / calculator_model; afterwards state which model was used. The \
only supported potentials are MACE and MatterSim — if the user asks for another, \
say so and offer list_models. Use list_models for "what models can I use".
- optimize_structure, run_md_simulation, compute_elastic_tensor, compute_phonons, \
generate_sqs, and compute_neb operate on a structure already in the session and are \
long-running: they return a job_id immediately. After calling one, tell the user the \
job has started and that progress appears in the job dashboard — do NOT claim final \
results you do not have.
- compute_neb is special: it needs TWO endpoint structures in the session. Pass the \
initial state as poscar_name and the final state as final_poscar_name. If the user \
only gives one structure, ask them for (or help them build) the second endpoint \
before calling it.
- IMPORTANT: you CAN compute elastic constants, phonons, SQS, and NEB migration \
barriers yourself — they run with an ML potential (MACE/MatterSim) as background \
jobs. When the user asks to "compute the elastic tensor", "compute phonons / phonon \
band structure", "generate an SQS", or "run an NEB / compute the migration (diffusion) \
barrier between two structures", CALL compute_elastic_tensor / compute_phonons / \
generate_sqs / compute_neb. Do NOT say you cannot compute them and do NOT tell the \
user to run VASP/DFT on a separate resource — that is wrong for these properties. \
(generate_vasp_inputs is only for when the user explicitly wants DFT input files.)
- NEVER fabricate a job, a job_id, or a "job started" confirmation. A job exists \
ONLY if you actually called optimize_structure / run_md_simulation / \
compute_elastic_tensor / compute_phonons / generate_sqs / compute_neb in THIS turn \
and it returned a real job_id. Report exactly the job_id the tool returned — never \
invent, guess, or reuse one. If you did not call the tool, or the tool returned a \
status of "error", say plainly that no job was started and state why (e.g. the \
job-quota limit, no active structure, or a tool error) — do not pretend it \
succeeded.
- If you intend to start a job, you MUST emit the tool call. Describing the action \
in prose is not the same as doing it; only a real tool call runs anything.
- After a search, present the results as a compact Markdown table (id, formula, \
crystal system, source, band gap, formation energy). If the result includes a \
`polymorphs_csv`, tell the user that the full list of all matches (metadata only) \
was saved to that CSV so they can browse every polymorph and pick one.
- Map the user's stated values to the closest tool parameter and just call the \
tool. NEVER refuse a request by claiming a parameter "does not exist" when one \
covers it — e.g. "a 30 second time budget" → time_budget_s=30, "2x2x1 supercell" \
→ supercell="2 2 1". If a detail truly has no matching parameter, call the tool \
with the parameters that do apply rather than refusing.
- Surface workflows: make_slab cuts the slab (set `layers` for an exact atomic-layer \
count; vacuum is included). For an in-plane supercell chain make_supercell after it, and \
for a different vacuum gap chain add_vacuum — each is its own tool. To put a molecule on a \
surface (e.g. "add CO2 on top"), first ensure a slab is the active structure (make_slab), \
then call add_adsorbate. A full "Cu(100) 2x2, 4 layers, CO2 on top" request = \
search_materials → make_slab(miller='1 0 0', layers=4) → make_supercell('2 2 1') → \
add_adsorbate.
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
    "energy_above_hull_eV_per_atom", "spacegroup_symbol", "crystal_system",
    "dimensionality", "has_structure",
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


def _call_signature(tc: ToolCall) -> str:
    """Stable (name + args) fingerprint used to suppress duplicate tool calls (BS2)."""
    try:
        args = json.dumps(tc.args or {}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        args = str(tc.args)
    return f"{tc.name}:{args}"


# ─────────────────────────────────────────────────────────────────────────────
# Confirmed-plan execution helpers — show the user the FINAL deliverable only.
# A structure file from an early step (e.g. an intermediate supercell POSCAR) is
# hidden once a LATER step produced its own structure; everything non-structure
# (INCAR/KPOINTS/POTCAR, CSVs, plots) is always kept. Net effect: the final
# structure + all VASP files, with intermediate structures suppressed.
# ─────────────────────────────────────────────────────────────────────────────

_STRUCTURE_NAMES = {"POSCAR", "CONTCAR"}
_STRUCTURE_EXTS = {"cif", "vasp", "xyz", "cssr"}


def _is_structure_file(f: dict) -> bool:
    name = str(f.get("name", "")).upper()
    if name in _STRUCTURE_NAMES:
        return True
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in _STRUCTURE_EXTS


def compute_final_files(step_results: list[dict]) -> list[dict]:
    """Final deliverable files: drop structure files superseded by a later step."""
    last_struct_step = -1
    for i, s in enumerate(step_results):
        if any(_is_structure_file(f) for f in s.get("files", []) or []):
            last_struct_step = i

    final: list[dict] = []
    seen: set[str] = set()
    for i, s in enumerate(step_results):
        for f in s.get("files", []) or []:
            rel = f.get("rel_path")
            if rel in seen:
                continue
            if _is_structure_file(f) and i != last_struct_step:
                continue  # intermediate structure — hidden
            seen.add(rel)
            final.append(f)
    return final


def _plan_guidance(plan: dict) -> str:
    """Render the user-approved plan as a system instruction for execution."""
    lines = ["The user reviewed and APPROVED the following plan. Execute it now, "
             "calling the tools in order. Do not ask for confirmation again."]
    if plan.get("summary"):
        lines.append(f"Goal: {plan['summary']}")
    for i, step in enumerate(plan.get("steps", []), 1):
        title = step.get("title") or step.get("tool")
        lines.append(f"{i}. {step.get('tool')} — {title}")
    if plan.get("final_output"):
        lines.append(f"Deliverable: {plan['final_output']}")
    lines.append("After the tools finish, write a short summary of what was produced.")
    return "\n".join(lines)


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
    emit_files: bool = True,
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
                "returned", "polymorphs_csv", "formula", "n_sites", "task", "encut", "kmesh",
                "elements", "files_written", "source", "material_id",
                "job_id", "type", "track", "calculator", "models",
                "file_type", "source_file", "content_preview",
            ):
                if key in result:
                    files_payload[key] = result[key]

        await queue.put(f"data: [TOOL_END:{tool_name}:{status}]\n\n")
        # When executing a confirmed plan we DEFER per-step file cards and flush
        # only the final deliverable at the end (so intermediate structures are
        # hidden). The payload is still recorded in step_results either way.
        if emit_files:
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
    plan: dict | None = None,
) -> None:
    provider = get_provider()

    conv: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": m["role"], "content": m.get("content", "")} for m in messages
    ]
    # Confirmed-plan execution: inject the approved plan as a final instruction
    # and DEFER per-step file cards so only the final deliverable is shown.
    defer_files = bool(plan and plan.get("steps"))
    if defer_files:
        conv.append({"role": "user", "content": _plan_guidance(plan)})
    step_results: list[dict] = []
    produced_text = False
    executed_calls: set[str] = set()   # (tool+args) fingerprints already run (BS2)
    started_job_msg: str | None = None  # set when a tool enqueues a real job this request

    await queue.put(f"data: {json.dumps({'type': 'status', 'value': THINKING_STATUS})}\n\n")

    for _turn in range(MAX_TURNS):
        started_text = False

        async def on_text(delta: str):
            nonlocal started_text, produced_text
            if not started_text:
                # first token of a streamed answer — clear the spinner
                await queue.put(f"data: {json.dumps({'type': 'status', 'value': ''})}\n\n")
                started_text = True
            produced_text = True
            await queue.put(f"data: {json.dumps({'type': 'token', 'value': delta})}\n\n")

        try:
            result = await provider.run(conv, TOOL_SPECS, on_text)
        except Exception as e:  # noqa: BLE001 — provider/rate-limit failure this turn
            import traceback
            traceback.print_exc()
            # If a job was already enqueued this request, the real work is underway —
            # don't bury it under a scary "all backends down" error. Otherwise show
            # the friendly provider error.
            if started_job_msg:
                await queue.put(f"data: {json.dumps({'type': 'token', 'value': (chr(10) + chr(10) + started_job_msg + ' (I could not write a summary just now — watch the job panel for progress.)')})}\n\n")
            else:
                await queue.put(f"data: {json.dumps({'type': 'token', 'value': _friendly_error(e)})}\n\n")
            break

        if not result.tool_calls:
            # final answer — guard against an empty bubble if nothing streamed
            if not produced_text:
                await queue.put(
                    f"data: {json.dumps({'type': 'token', 'value': 'I could not generate a response just now. Please try again or rephrase your request.'})}\n\n"
                )
            break  # final natural-language answer already streamed

        # record the assistant's tool-calling turn
        conv.append({
            "role": "assistant",
            "content": result.text,
            "tool_calls": result.tool_calls,
        })

        for tc in result.tool_calls:
            sig = _call_signature(tc)
            if sig in executed_calls:
                # Identical call already ran in this request — don't repeat it
                # (prevents duplicate jobs / runaway loops, BS2). Tell the model
                # so it stops re-issuing and moves on to a final answer.
                dup = {
                    "status": "skipped",
                    "message": (
                        f"'{tc.name}' was already run with identical arguments in "
                        "this request — skipping the repeat. Use the previous "
                        "result instead of calling it again."
                    ),
                }
                await queue.put(f"data: [TOOL_END:{tc.name}:skipped]\n\n")
                conv.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": _result_for_llm(dup),
                })
                continue
            executed_calls.add(sig)

            raw = await _execute_tool(
                tc, queue, session_id, session_dir, user_id, step_results,
                emit_files=not defer_files)
            if isinstance(raw, dict) and raw.get("job_id"):
                started_job_msg = (
                    f"✓ Your {raw.get('type') or tc.name} job was queued "
                    f"(id {raw['job_id']})."
                )
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

    # Confirmed-plan flush: emit the single final-deliverable card now that all
    # steps have run (per-step cards were deferred above).
    if defer_files:
        final_files = compute_final_files(step_results)
        if final_files:
            final_payload = {
                "tool": "final_output",
                "label": "Final structure & inputs",
                "status": "success",
                "files": final_files,
            }
            await queue.put(f"data: [FILES:{json.dumps(final_payload)}]\n\n")

    await queue.put(f"data: {json.dumps({'type': 'status', 'value': ''})}\n\n")
    await queue.put("data: [DONE]\n\n")
    await queue.put(f"data: [SESSION:{session_id}]\n\n")


# ─────────────────────────────────────────────────────────────────────────────
# Public API — called from chat.py token_generator
# ─────────────────────────────────────────────────────────────────────────────

def _friendly_error(e: Exception) -> str:
    """Map a raw provider/agent error to a short user-facing message.

    Raw provider dumps (e.g. Google's verbose 429 quota JSON) never reach the
    chat — the full error is logged server-side via the traceback instead.
    """
    text = str(e).lower()
    if any(s in text for s in ("429", "quota", "rate limit", "resource_exhausted",
                               "too many requests", "unavailable")):
        return ("⚠ The language model is busy or rate-limited right now. Wait a few "
                "seconds and try again. Tip: add a **Gemini** key in ⚙️ Settings as a "
                "backup provider so requests fall back automatically when Groq is "
                "rate-limited.")
    return "⚠ Something went wrong while generating a response. Please try again."


async def run_agent(
    messages: list[dict],
    session_id: str,
    user_id: int | None = None,
    plan: dict | None = None,
) -> AsyncGenerator[str, None]:
    session_dir = str(get_session_dir(session_id))
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _run():
        try:
            await _agent_loop(messages, session_id, user_id, session_dir, queue, plan)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            await queue.put(
                f"data: {json.dumps({'type': 'token', 'value': _friendly_error(e)})}\n\n")
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
