"""Chat, session, and file-serving endpoints."""

import json as json_lib
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import make_plan, run_agent
from app.agent.graph import session_structure_context
from app.api.deps import get_session_for_rel_path, get_session_for_user
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.database.db import AsyncSessionLocal, get_db
from app.database.models import User
from app.repositories import message_repository, session_repository
from app.schemas.chat import ChatRequest, MessageOut, SessionOut
from app.services.storage.file_service import (
    STORAGE_ROOT,
    get_session_dir,
    list_session_files,
)
from app.services.key_service import load_user_keys_into_env

router = APIRouter()
logger = get_logger(__name__)

_CONTENT_ALLOWED_EXTS = {"", ".txt", ".log", ".csv", ".tsv", ".sh", ".xml",
                         ".json", ".cif", ".xyz", ".html", ".py", ".md",
                         ".yaml", ".yml", ".toml", ".cfg", ".ini", ".dat",
                         ".in", ".out", ".inp", ".vasp", ".pdb", ".text"}
_VASP_NAMES = {"POSCAR", "CONTCAR", "INCAR", "KPOINTS",
               "POTCAR", "OSZICAR", "OUTCAR", "XDATCAR"}


# ── GET /api/sessions ─────────────────────────────────────────────────────────

@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = await session_repository.list_for_user(db, current_user.id)
    return [SessionOut(id=s.id, title=s.title) for s in sessions]


# ── GET /api/sessions/{id}/messages ──────────────────────────────────────────

@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_session_for_user(session_id, current_user, db)
    messages = await message_repository.list_for_session(db, session_id)
    return [MessageOut(role=m.role, content=m.content, tool_result=m.tool_result)
            for m in messages]


# ── GET /api/sessions/{id}/files ─────────────────────────────────────────────

@router.get("/sessions/{session_id}/files")
async def get_session_files(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_session_for_user(session_id, current_user, db)
    return {"files": list_session_files(session_id)}


# ── GET /api/sessions/{id}/files/grouped ─────────────────────────────────────

@router.get("/sessions/{session_id}/files/grouped")
async def get_session_files_grouped(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_session_for_user(session_id, current_user, db)

    session_folder = STORAGE_ROOT / session_id
    if not session_folder.exists():
        return {"groups": []}

    groups: dict[str, list] = {}
    for item in sorted(session_folder.rglob("*")):
        if not item.is_file():
            continue
        parts = item.relative_to(session_folder).parts
        group_name = parts[0] if len(parts) > 1 else "output"
        groups.setdefault(group_name, []).append({
            "name": item.name,
            "size_kb": round(item.stat().st_size / 1024, 2),
            "rel_path": str(item.relative_to(STORAGE_ROOT)),
        })

    return {"groups": [{"group_name": k, "files": v} for k, v in groups.items()]}


# ── GET /api/files/download/{rel_path} ───────────────────────────────────────

@router.get("/files/download/{rel_path:path}")
async def download_file(
    rel_path: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _session, full_path = await get_session_for_rel_path(rel_path, current_user, db)
    return FileResponse(
        path=str(full_path),
        filename=full_path.name,
        media_type="application/octet-stream",
    )


# ── GET /api/files/content/{rel_path} ────────────────────────────────────────

@router.get("/files/content/{rel_path:path}")
async def get_file_content(
    rel_path: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _session, full_path = await get_session_for_rel_path(rel_path, current_user, db)

    if (full_path.suffix.lower() not in _CONTENT_ALLOWED_EXTS
            and full_path.name.upper() not in _VASP_NAMES):
        raise HTTPException(status_code=400, detail="File type not readable as text")

    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
        return {"name": full_path.name, "content": content, "rel_path": rel_path}
    except Exception as e:  # noqa: BLE001
        # Log the real reason privately; never echo raw exception text (which can
        # contain absolute filesystem paths) back to the client (Step 6).
        logger.error("Could not read file %s: %s", rel_path, e)
        raise HTTPException(status_code=500, detail="Could not read file.")


# ── GET /api/sessions/{id}/export/txt ────────────────────────────────────────

@router.get("/sessions/{session_id}/export/txt")
async def export_session_txt(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_for_user(session_id, current_user, db)
    messages = await message_repository.list_for_session(db, session.id)
    lines = [f"Session: {session.title} ({session.id})", ""]
    for m in messages:
        lines.append(f"{m.role}: {m.content}")
        if m.tool_result:
            lines.append(f"tool_result: {m.tool_result}")
        lines.append("")
    return {"session_id": session.id, "content": "\n".join(lines)}


# ── GET /api/sessions/{id}/export/json ───────────────────────────────────────

@router.get("/sessions/{session_id}/export/json")
async def export_session_json(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_for_user(session_id, current_user, db)
    messages = await message_repository.list_for_session(db, session.id)
    return {
        "session": {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at.isoformat() if session.created_at else None,
        },
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "tool_result": m.tool_result,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


# ── POST /api/chat ────────────────────────────────────────────────────────────

# A confirmation gate only makes sense for genuinely multi-step workflows.
_PLAN_GATE_MIN_STEPS = 2


def _plan_to_markdown(plan: dict) -> str:
    """Readable assistant message for a proposed plan (persisted to history)."""
    lines = ["Here's my plan — review and confirm to run it:", ""]
    if plan.get("summary"):
        lines.append(f"**{plan['summary']}**")
        lines.append("")
    for i, step in enumerate(plan.get("steps", []), 1):
        title = step.get("title") or step.get("tool")
        detail = step.get("detail")
        lines.append(f"{i}. **{title}** — {detail}" if detail else f"{i}. **{title}**")
    if plan.get("final_output"):
        lines.append("")
        lines.append(f"_You'll get:_ {plan['final_output']}")
    return "\n".join(lines)


async def _save_assistant(session_id: str, text: str, tool_result: str | None) -> None:
    try:
        async with AsyncSessionLocal() as save_db:
            await message_repository.add(
                save_db,
                session_id=session_id,
                role="assistant",
                content=text,
                tool_result=tool_result,
            )
    except Exception as e:  # noqa: BLE001
        logger.error("DB save error: %s", e)


async def _stream_agent(messages, session_id, user_id, plan=None):
    """Run the agent, relay its SSE, and persist the assistant turn at the end."""
    full_response: list[str] = []
    all_tool_results: list[dict] = []

    async for sse in run_agent(messages, session_id, user_id=user_id, plan=plan):
        yield sse

        if sse.startswith("data: {"):
            try:
                obj = json_lib.loads(sse[6:].strip())
                if obj.get("type") == "token":
                    full_response.append(obj["value"])
            except Exception:
                pass

        if sse.startswith("data: [FILES:"):
            try:
                inner = sse[len("data: [FILES:"):].strip().rstrip("\n")
                last_brace = inner.rfind("}")
                if last_brace >= 0:
                    all_tool_results.append(json_lib.loads(inner[: last_brace + 1]))
            except Exception as e:
                logger.warning("FILES parse error: %s", e)

    assistant_text = "".join(full_response)
    tool_result_str = json_lib.dumps(all_tool_results) if all_tool_results else None
    await _save_assistant(session_id, assistant_text, tool_result_str)


@router.post("/chat")
@limiter.limit("30/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    is_execute = body.plan is not None

    # 1. resolve or create session
    if body.session_id:
        session = await get_session_for_user(body.session_id, current_user, db)
    elif is_execute:
        raise HTTPException(status_code=400,
                            detail="Plan execution requires an existing session_id.")
    else:
        session = await session_repository.create(
            db,
            session_id=str(uuid.uuid4()),
            user_id=current_user.id,
            title=(body.message[:60].strip() or "New chat"),
        )

    await load_user_keys_into_env(current_user.id, db)

    # 2. load history. The PLAN phase persists the new user message; the EXECUTE
    #    phase reuses the message already saved when the plan was proposed.
    history = await message_repository.list_for_session(db, session.id)
    messages_for_llm = [{"role": m.role, "content": m.content} for m in history]
    if not is_execute:
        await message_repository.add(
            db, session_id=session.id, role="user",
            content=body.message, tool_result=None,
        )
        messages_for_llm.append({"role": "user", "content": body.message})

    session_id = session.id
    user_id = current_user.id
    plan_in = body.plan

    # 3. streaming generator
    async def token_generator():
        # BYOK gate: in a hosted deployment the user must supply their own LLM key.
        if settings.is_production and not (
            os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY")
        ):
            nudge = (
                "I don't have an LLM API key yet. Add your free Groq or Gemini key in "
                "Settings (or below) to start chatting."
            )
            yield f"data: [SESSION:{session_id}]\n\n"
            yield f'data: {json_lib.dumps({"type": "token", "value": nudge})}\n\n'
            yield "data: [NEED_API_KEY:groq]\n\n"
            yield "data: [DONE]\n\n"
            return

        # EXECUTE phase — the user already confirmed the plan; just run it.
        if is_execute:
            async for sse in _stream_agent(
                messages_for_llm, session_id, user_id, plan=plan_in):
                yield sse
            return

        # PLAN phase — propose a plan first; gate only on multi-tool workflows.
        yield f"data: [SESSION:{session_id}]\n\n"
        yield f'data: {json_lib.dumps({"type": "status", "value": "🧭 Planning…"})}\n\n'
        struct_ctx = session_structure_context(str(get_session_dir(session_id)))
        plan = await make_plan(messages_for_llm, context=struct_ctx)
        yield f'data: {json_lib.dumps({"type": "status", "value": ""})}\n\n'

        if (plan and plan.get("needs_tools")
                and len(plan.get("steps", [])) >= _PLAN_GATE_MIN_STEPS):
            yield f"data: [PLAN:{json_lib.dumps(plan)}]\n\n"
            yield "data: [DONE]\n\n"
            await _save_assistant(
                session_id, _plan_to_markdown(plan), json_lib.dumps({"plan": plan}))
            return

        # No gate needed (0–1 tools or plain chat) — run directly.
        async for sse in _stream_agent(messages_for_llm, session_id, user_id):
            yield sse

    return StreamingResponse(
        token_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
