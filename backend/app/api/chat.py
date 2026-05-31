# app/api/chat.py

import uuid
import json as json_lib
import sys
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.db import get_db, AsyncSessionLocal
from app.database.models import Session, Message
from app.core.llm import stream_chat
from app.core.agent import run_agent
from app.core.tool_registry import TOOL_MAP
from app.services.file_service import (
    get_session_dir,
    list_new_files,
    list_session_files,
    find_best_poscar,  
    STORAGE_ROOT,
)

router = APIRouter()


# ── schemas ───────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str | None = None
    message:    str

class SessionOut(BaseModel):
    id:    str
    title: str

class MessageOut(BaseModel):
    role:        str
    content:     str
    tool_result: str | None = None


def resolve_tool_args(tool_name: str, tool_args: dict, session_dir: str) -> dict:
    resolved = dict(tool_args)

    poscar_keys = [
        'poscar_path', 'initial_poscar_path', 'final_poscar_path',
        'lower_poscar_path', 'upper_poscar_path',
    ]

    for key in poscar_keys:
        if key not in resolved:
            continue
        val = resolved[key]
        # "auto" means: find best POSCAR automatically
        # also fix paths that don't exist on disk
        if val in ('auto', '', None) or not Path(str(val)).exists():
            best = find_best_poscar(session_dir)   # ← uses imported function
            if best:
                resolved[key] = best
                print(f'[Materia] Resolved {key} → {best}')

    POSCAR_REQUIRED = {
        'generate_vasp_poscar_with_vacancy_defects',
        'generate_vasp_poscar_with_substitution_defects',
        'generate_vasp_poscar_with_interstitial_defects',
        'generate_supercell_from_poscar',
        'generate_sqs_from_poscar',
        'generate_surface_slab_from_poscar',
        'customize_vasp_kpoints_with_accuracy',
        'generate_vasp_inputs_from_poscar',
        'generate_vasp_workflow_of_eos',
        'generate_vasp_workflow_of_elastic_constants',
        'generate_vasp_workflow_of_aimd',
        'generate_vasp_workflow_of_convergence_tests',
        'visualize_structure_from_poscar',
        'run_simulation_using_mlps',
    }

    if tool_name in POSCAR_REQUIRED and 'poscar_path' not in resolved:
        best = find_best_poscar(session_dir)
        if best:
            resolved['poscar_path'] = best
            print(f'[Materia] Auto-added poscar_path → {best}')

    return resolved


    if tool_name in POSCAR_REQUIRED and 'poscar_path' not in resolved:
        best = find_best_poscar(session_dir)
        if best:
            resolved['poscar_path'] = best

    return resolved


# ── GET /api/sessions ─────────────────────────────────────────────────────────

@router.get('/sessions', response_model=list[SessionOut])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Session).order_by(Session.created_at.desc())
    )
    return [SessionOut(id=s.id, title=s.title) for s in result.scalars().all()]


# ── GET /api/sessions/{id}/messages ──────────────────────────────────────────

@router.get('/sessions/{session_id}/messages', response_model=list[MessageOut])
async def get_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail='Session not found')

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id)
    )
    return [
        MessageOut(
            role=m.role,
            content=m.content,
            tool_result=m.tool_result,
        )
        for m in result.scalars().all()
    ]


# ── GET /api/sessions/{id}/files ─────────────────────────────────────────────

@router.get('/sessions/{session_id}/files')
async def get_session_files(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail='Session not found')
    return {"files": list_session_files(session_id)}


# ── GET /api/sessions/{id}/files/grouped ─────────────────────────────────────

@router.get('/sessions/{session_id}/files/grouped')
async def get_session_files_grouped(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail='Session not found')

    session_folder = STORAGE_ROOT / session_id
    if not session_folder.exists():
        return {"groups": []}

    groups: dict[str, list] = {}
    for item in sorted(session_folder.rglob("*")):
        if not item.is_file():
            continue
        parts      = item.relative_to(session_folder).parts
        group_name = parts[0] if len(parts) > 1 else "output"
        groups.setdefault(group_name, []).append({
            "name":     item.name,
            "size_kb":  round(item.stat().st_size / 1024, 2),
            "rel_path": str(item.relative_to(STORAGE_ROOT)),
        })

    return {
        "groups": [
            {"group_name": k, "files": v}
            for k, v in groups.items()
        ]
    }


# ── GET /api/files/download/{rel_path} ───────────────────────────────────────

@router.get('/files/download/{rel_path:path}')
async def download_file(rel_path: str):
    full_path = STORAGE_ROOT / rel_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail='File not found')
    try:
        full_path.resolve().relative_to(STORAGE_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail='Access denied')
    return FileResponse(
        path=str(full_path),
        filename=full_path.name,
        media_type='application/octet-stream',
    )


# ── GET /api/files/content/{rel_path} ────────────────────────────────────────

@router.get('/files/content/{rel_path:path}')
async def get_file_content(rel_path: str):
    full_path = STORAGE_ROOT / rel_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail='File not found')
    try:
        full_path.resolve().relative_to(STORAGE_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail='Access denied')

    ALLOWED_EXTS  = {'', '.txt', '.log', '.csv', '.sh', '.xml',
                     '.json', '.cif', '.xyz', '.html'}
    VASP_NAMES    = {'POSCAR', 'CONTCAR', 'INCAR', 'KPOINTS',
                     'POTCAR', 'OSZICAR', 'OUTCAR', 'XDATCAR'}

    if (full_path.suffix.lower() not in ALLOWED_EXTS
            and full_path.name.upper() not in VASP_NAMES):
        raise HTTPException(status_code=400, detail='File type not readable as text')

    try:
        content = full_path.read_text(encoding='utf-8', errors='replace')
        return {"name": full_path.name, "content": content, "rel_path": rel_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Could not read file: {e}')


# ── POST /api/chat ────────────────────────────────────────────────────────────

@router.post('/chat')
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):

    # 1. resolve or create session
    if request.session_id:
        result = await db.execute(
            select(Session).where(Session.id == request.session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail='Session not found')
    else:
        session = Session(
            id=str(uuid.uuid4()),
            title=request.message[:60].strip(),
        )
        db.add(session)
        await db.commit()

    # 2. load history
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.id)
    )
    history = result.scalars().all()

    # 3. save user message
    db.add(Message(
        session_id=session.id,
        role='user',
        content=request.message,
        tool_result=None,
    ))
    await db.commit()

    # 4. capture before generator (db session may close inside generator)
    session_id  = session.id
    session_dir = str(get_session_dir(session.id))

    messages_for_llm = (
        [{"role": m.role, "content": m.content} for m in history]
        + [{"role": "user", "content": request.message}]
    )

# 5. streaming generator — powered by LangGraph agent
    async def token_generator():
        full_response    = []
        all_tool_results = []

        async for sse in run_agent(messages_for_llm, session_id):
            yield sse

            # capture text for DB
            if sse.startswith('data: {'):
                try:
                    obj = json_lib.loads(sse[6:].strip())
                    if obj.get('type') == 'token':
                        full_response.append(obj['value'])
                except Exception:
                    pass

            # capture tool results for DB — parse carefully
            if sse.startswith('data: [FILES:'):
                try:
                    # format: data: [FILES:{...json...}]\n\n
                    inner = sse[len('data: [FILES:'):]
                    inner = inner.strip()
                    if inner.endswith('\n\n'):
                        inner = inner[:-2]
                    # find the matching closing ] by parsing the JSON object
                    # the JSON object starts with { so find the last }] 
                    last_brace = inner.rfind('}')
                    if last_brace >= 0:
                        json_str = inner[:last_brace+1]
                        all_tool_results.append(json_lib.loads(json_str))
                except Exception as e:
                    print(f'[Materia] FILES parse error: {e}')

        # save ALL tool results as array — fixes reload showing only last card
        assistant_text  = ''.join(full_response)
        tool_result_str = json_lib.dumps(all_tool_results) if all_tool_results else None

        try:
            async with AsyncSessionLocal() as save_db:
                save_db.add(Message(
                    session_id=session_id,
                    role='assistant',
                    content=assistant_text,
                    tool_result=tool_result_str,
                ))
                await save_db.commit()
        except Exception as e:
            print(f'[Materia] DB save error: {e}')

    return StreamingResponse(
        token_generator(),
        media_type='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


 #new code for agentic streaming generator — replaces the previous token_generator function entirely
# # 5. agentic streaming generator
#     async def token_generator():
#         # running conversation — starts with history + user message
#         # we extend this after each tool call so the LLM has full context
#         agent_messages = list(messages_for_llm)

#         all_tool_results = []   # collect every tool result for DB save
#         full_response    = []   # collect all text tokens for DB save

#         MAX_STEPS = 8   # safety cap — prevents infinite loops

#         for step in range(MAX_STEPS):

#             # ── call LLM ─────────────────────────────────────────────────────
#             step_response  = []
#             tool_call_json = None

#             try:
#                 async for token in stream_chat(agent_messages):
#                     if token.startswith("\n__TOOL__:"):
#                         tool_call_json = token[len("\n__TOOL__:"):]
#                         continue
#                     step_response.append(token)
#                     full_response.append(token)
#                     yield f"data: {json_lib.dumps({'type': 'token', 'value': token})}\n\n"

#             except Exception as e:
#                 yield f"data: {json_lib.dumps({'type': 'token', 'value': f'⚠ LLM error: {str(e)}'})}\n\n"
#                 break

#             step_text = "".join(step_response)

#             # ── no tool call → LLM is done or answering a question ───────────
#             if not tool_call_json:
#                 break

#             # ── parse the tool call ───────────────────────────────────────────
#             tool_name = ""
#             try:
#                 tool_info = json_lib.loads(tool_call_json)
#                 tool_name = tool_info.get("tool", "")
#                 tool_args = tool_info.get("args", {})
#             except Exception:
#                 break

#             tool_meta = TOOL_MAP.get(tool_name)

#             if not tool_meta:
#                 yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                 error_msg = f"⚠ Unknown tool: {tool_name}"
#                 yield f"data: {json_lib.dumps({'type': 'token', 'value': error_msg})}\n\n"
#                 # tell LLM the tool failed so it can recover
#                 agent_messages.append({"role": "assistant", "content": step_text})
#                 agent_messages.append({"role": "user",      "content": f"Tool error: {error_msg}. Please continue with remaining steps or explain what went wrong."})
#                 continue

#             # ── guards ────────────────────────────────────────────────────────

#             # NEB guard — requires explicit paths
#             if tool_name == 'generate_vasp_workflow_of_neb':
#                 has_initial = bool(tool_args.get('initial_poscar_path', '').strip())
#                 has_final   = bool(tool_args.get('final_poscar_path',   '').strip())
#                 if not has_initial or not has_final:
#                     yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                     msg = '⚠ NEB requires both initial_poscar_path and final_poscar_path. Please provide both POSCAR files.'
#                     yield f"data: {json_lib.dumps({'type': 'token', 'value': msg})}\n\n"
#                     break

#             # workflow guard — needs a POSCAR to exist
#             WORKFLOW_TOOLS = {
#                 'generate_vasp_workflow_of_eos',
#                 'generate_vasp_workflow_of_elastic_constants',
#                 'generate_vasp_workflow_of_aimd',
#                 'generate_vasp_workflow_of_convergence_tests',
#                 'generate_vasp_inputs_from_poscar',
#                 'generate_supercell_from_poscar',
#                 'generate_surface_slab_from_poscar',
#                 'customize_vasp_kpoints_with_accuracy',
#                 'generate_vasp_poscar_with_vacancy_defects',
#                 'generate_vasp_poscar_with_substitution_defects',
#                 'generate_vasp_poscar_with_interstitial_defects',
#                 'visualize_structure_from_poscar',
#                 'run_simulation_using_mlps',
#             }
#             if tool_name in WORKFLOW_TOOLS:
#                 if not find_best_poscar(session_dir):
#                     yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                     msg = '⚠ No POSCAR found in this session. Generating POSCAR first.'
#                     yield f"data: {json_lib.dumps({'type': 'token', 'value': msg})}\n\n"
#                     agent_messages.append({"role": "assistant", "content": step_text})
#                     agent_messages.append({"role": "user",
#                         "content": "No POSCAR exists yet. Generate the required POSCAR first, then continue with the original request."})
#                     continue   # let LLM recover by generating POSCAR first

#             # ── signal frontend: tool starting ────────────────────────────────
#             yield f"data: [TOOL_START:{tool_name}]\n\n"

#             # ── execute tool ──────────────────────────────────────────────────
#             try:
#                 os.environ["MATERIA_SESSION_RUNS_DIR"] = session_dir
#                 tool_args = resolve_tool_args(tool_name, tool_args, session_dir)

#                 t_before = time.time() - 0.5

#                 from app.tools import tools as mt
#                 tool_fn = getattr(mt, tool_name, None)

#                 if not tool_fn:
#                     raise ValueError(f"Function {tool_name} not found in tools module")

#                 print(f'[Materia] Step {step+1}: {tool_name}({tool_args})')
#                 result = tool_fn(**tool_args)

#                 status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
#                 msg    = result.get("message", "")       if isinstance(result, dict) else str(result)
#                 print(f'[Materia] → {status}: {msg}')

#                 new_files = list_new_files(session_id, t_before)

#                 tool_result_obj = {
#                     "tool":   tool_name,
#                     "label":  tool_meta["label"],
#                     "status": status,
#                     "msg":    msg,
#                     "files":  new_files,
#                 }

#                 all_tool_results.append(tool_result_obj)

#                 yield f"data: [TOOL_END:{tool_name}:{status}]\n\n"
#                 yield f"data: [FILES:{json_lib.dumps(tool_result_obj)}]\n\n"

#                 # ── inject result back into agent context ─────────────────────
#                 # this is the KEY part — LLM now knows the tool succeeded
#                 # and can decide what to do next
#                 agent_messages.append({
#                     "role": "assistant",
#                     "content": step_text
#                 })
#                 agent_messages.append({
#                     "role": "user",
#                     "content": (
#                         f"Tool '{tool_name}' completed with status: {status}.\n"
#                         f"Result: {msg}\n"
#                         f"Files generated: {[f['name'] for f in new_files]}\n\n"
#                         f"Session directory: {session_dir}\n\n"
#                         "Continue with the next step of the user's original request. "
#                         "If all steps are complete, respond with a summary and say DONE."
#                     )
#                 })

#             except Exception as e:
#                 import traceback
#                 print(f'[Materia] Tool error:\n{traceback.format_exc()}')
#                 yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                 err_text = str(e)
#                 yield f"data: {json_lib.dumps({'type': 'token', 'value': f'⚠ {err_text}'})}\n\n"

#                 # inject error into context so LLM can recover
#                 agent_messages.append({"role": "assistant", "content": step_text})
#                 agent_messages.append({
#                     "role": "user",
#                     "content": (
#                         f"Tool '{tool_name}' failed with error: {err_text}\n"
#                         "Please try to recover or continue with the remaining steps."
#                     )
#                 })
#                 continue   # let LLM try to recover, don't break

#         # ── save complete assistant message to DB ─────────────────────────────
#         # use the last tool result for tool_result field
#         # (the file panel shows all tool cards inline in the chat)
#         assistant_text  = "".join(full_response)
#         last_tool_result = all_tool_results[-1] if all_tool_results else None
#         tool_result_str  = json_lib.dumps(last_tool_result) if last_tool_result else None

#         try:
#             async with AsyncSessionLocal() as save_db:
#                 save_db.add(Message(
#                     session_id=session_id,
#                     role='assistant',
#                     content=assistant_text,
#                     tool_result=tool_result_str,
#                 ))
#                 await save_db.commit()
#         except Exception as e:
#             print(f'[Materia] DB save error: {e}')

#         yield "data: [DONE]\n\n"
#         yield f"data: [SESSION:{session_id}]\n\n"

#     return StreamingResponse(
#         token_generator(),
#         media_type='text/event-stream',
#         headers={
#             'Cache-Control':     'no-cache',
#             'X-Accel-Buffering': 'no',
#         }
#     )


# # this is old code before agentic rewrite, kept here for reference and potential reuse of helper functions
#     # 5. streaming generator
#     async def token_generator():
#         full_response   = []
#         tool_call_json  = None
#         tool_result_obj = None  # ← defined here, used throughout

#         try:
#             async for token in stream_chat(messages_for_llm):
#                 if token.startswith("\n__TOOL__:"):
#                     tool_call_json = token[len("\n__TOOL__:"):]
#                     continue
#                 full_response.append(token)
#                 yield f"data: {json_lib.dumps({'type': 'token', 'value': token})}\n\n"

#         except Exception as e:
#             yield f"data: {json_lib.dumps({'type': 'token', 'value': f'⚠ LLM error: {str(e)}'})}\n\n"
# # ── run tool if requested ─────────────────────────────────────────────
#         if tool_call_json:
#             tool_name = ""
#             try:
#                 tool_info = json_lib.loads(tool_call_json)
#                 tool_name = tool_info.get("tool", "")
#                 tool_args = tool_info.get("args", {})

#                 tool_meta = TOOL_MAP.get(tool_name)

#                 if not tool_meta:
#                     yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                     yield f"data: {json_lib.dumps({'type': 'token', 'value': f'⚠ Unknown tool: {tool_name}'})}\n\n"

#                 else:
#                     # ── guard: NEB requires explicit paths ────────────────────
#                     if tool_name == 'generate_vasp_workflow_of_neb':
#                         has_initial = bool(tool_args.get('initial_poscar_path', '').strip())
#                         has_final   = bool(tool_args.get('final_poscar_path',   '').strip())
#                         if not has_initial or not has_final:
#                             yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                             msg = ('⚠ NEB requires both initial_poscar_path and final_poscar_path. '
#                                    'Please generate or upload both structures first, then provide their paths.')
#                             yield f"data: {json_lib.dumps({'type': 'token', 'value': msg})}\n\n"
#                             # skip to save
#                             assistant_text  = ''.join(full_response)
#                             tool_result_str = None
#                             async with AsyncSessionLocal() as save_db:
#                                 save_db.add(Message(
#                                     session_id=session_id,
#                                     role='assistant',
#                                     content=assistant_text,
#                                     tool_result=tool_result_str,
#                                 ))
#                                 await save_db.commit()
#                             yield "data: [DONE]\n\n"
#                             yield f"data: [SESSION:{session_id}]\n\n"
#                             return

#                     # ── guard: workflow tools need POSCAR to exist ────────────
#                     WORKFLOW_TOOLS = {
#                         'generate_vasp_workflow_of_eos',
#                         'generate_vasp_workflow_of_elastic_constants',
#                         'generate_vasp_workflow_of_aimd',
#                         'generate_vasp_workflow_of_convergence_tests',
#                         'generate_vasp_inputs_from_poscar',
#                     }
#                     if tool_name in WORKFLOW_TOOLS:
#                         best_poscar = find_best_poscar(session_dir)
#                         if not best_poscar:
#                             yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                             msg = ('⚠ This workflow requires a POSCAR file. '
#                                    'Please generate a POSCAR first using: '
#                                    '"Generate POSCAR for [formula]"')
#                             yield f"data: {json_lib.dumps({'type': 'token', 'value': msg})}\n\n"
#                             assistant_text  = ''.join(full_response)
#                             async with AsyncSessionLocal() as save_db:
#                                 save_db.add(Message(
#                                     session_id=session_id,
#                                     role='assistant',
#                                     content=assistant_text,
#                                     tool_result=None,
#                                 ))
#                                 await save_db.commit()
#                             yield "data: [DONE]\n\n"
#                             yield f"data: [SESSION:{session_id}]\n\n"
#                             return

#                     yield f"data: [TOOL_START:{tool_name}]\n\n"

#                     os.environ["MATERIA_SESSION_RUNS_DIR"] = session_dir
#                     tool_args = resolve_tool_args(tool_name, tool_args, session_dir)

#                     t_before = time.time() - 0.5

#                     from app.tools import tools as mt
#                     tool_fn = getattr(mt, tool_name, None)

#                     if not tool_fn:
#                         yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                         yield f"data: {json_lib.dumps({'type': 'token', 'value': f'⚠ Tool function not found: {tool_name}'})}\n\n"
#                     else:
#                         print(f'[Materia] Calling {tool_name} with: {tool_args}')
#                         result   = tool_fn(**tool_args)
#                         status   = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
#                         msg      = result.get("message", "")       if isinstance(result, dict) else str(result)
#                         print(f'[Materia] {tool_name} → {status}: {msg}')

#                         new_files = list_new_files(session_id, t_before)

#                         tool_result_obj = {
#                             "tool":   tool_name,
#                             "label":  tool_meta["label"],
#                             "status": status,
#                             "msg":    msg,
#                             "files":  new_files,
#                         }

#                         yield f"data: [TOOL_END:{tool_name}:{status}]\n\n"
#                         yield f"data: [FILES:{json_lib.dumps(tool_result_obj)}]\n\n"

#             except Exception as e:
#                 import traceback
#                 print(f'[Materia] Tool error:\n{traceback.format_exc()}')
#                 yield f"data: [TOOL_END:{tool_name}:error]\n\n"
#                 yield f"data: {json_lib.dumps({'type': 'token', 'value': f'⚠ {str(e)}'})}\n\n"

#         # ── save assistant message to DB ──────────────────────────────────────
#         assistant_text   = "".join(full_response)
#         tool_result_str  = json_lib.dumps(tool_result_obj) if tool_result_obj else None  # ← defined here

#         try:
#             async with AsyncSessionLocal() as save_db:
#                 save_db.add(Message(
#                     session_id=session_id,
#                     role='assistant',
#                     content=assistant_text,
#                     tool_result=tool_result_str,
#                 ))
#                 await save_db.commit()
#         except Exception as e:
#             print(f'[Materia] DB save error: {e}')

#         yield "data: [DONE]\n\n"
#         yield f"data: [SESSION:{session_id}]\n\n"

#     return StreamingResponse(
#         token_generator(),
#         media_type='text/event-stream',
#         headers={
#             'Cache-Control':     'no-cache',
#             'X-Accel-Buffering': 'no',
#         }
#     )
