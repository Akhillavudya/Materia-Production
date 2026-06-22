"""File upload endpoints."""

import asyncio
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session_for_user
from app.core.config import settings
from app.core.context import set_request_identity
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.database.db import get_db
from app.database.models import User
from app.repositories import session_repository
from app.schemas.upload import UploadedFileOut
from app.services.storage.file_service import (
    STORAGE_ROOT,
    get_session_dir,
    get_upload_dir,
    is_upload_allowed,
    sanitize_filename,
    set_session_dir,
)
from app.services.structure.activation import (
    StructureParseError,
    activate_structure,
    is_structure_file,
)

router = APIRouter()

_MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024


def _too_large(content: bytes) -> bool:
    return len(content) > _MAX_UPLOAD_BYTES


def _activate_uploads(session_id: str, items: list[tuple[str, str]]) -> dict:
    """Auto-activate a freshly-uploaded structure (U1).

    - exactly one structure file  → parse it and write the active POSCAR.
    - several structure files      → don't guess; ask the user which to activate.
    - none / unreadable            → just leave them stored (with a reason).
    `items` are (name, rel_path) pairs for the files that were stored.
    """
    structures = [(n, rp) for n, rp in items if is_structure_file(n)]
    if not structures:
        return {"status": "none"}
    if len(structures) > 1:
        return {"status": "multiple", "candidates": [n for n, _ in structures]}

    name, rel_path = structures[0]
    try:
        info = activate_structure(STORAGE_ROOT / rel_path, get_session_dir(session_id))
        return {"status": "activated", "file": name, **info}
    except StructureParseError as e:
        return {"status": "unreadable", "file": name, "error": str(e)}
    except Exception as e:  # noqa: BLE001 — never let activation 500 the upload
        return {"status": "unreadable", "file": name, "error": str(e)}


@router.post("/sessions/{session_id}/upload")
@limiter.limit("30/minute")
async def upload_files(
    request: Request,
    session_id: str,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload one or more files into the session's uploads/ folder."""
    await get_session_for_user(session_id, current_user, db)

    upload_dir = get_upload_dir(session_id)
    uploaded: list[UploadedFileOut] = []
    errors: list[str] = []

    for file in files:
        original_name = file.filename or "unnamed"
        safe_name = sanitize_filename(original_name)

        if not is_upload_allowed(safe_name):
            errors.append(f"{original_name}: file type not allowed")
            continue

        dest = upload_dir / safe_name
        try:
            content = await file.read()
            if _too_large(content):
                errors.append(f"{original_name}: exceeds {settings.max_upload_mb} MB limit")
                continue
            dest.write_bytes(content)
            uploaded.append(UploadedFileOut(
                name=safe_name,
                size_kb=round(dest.stat().st_size / 1024, 2),
                rel_path=str(dest.relative_to(STORAGE_ROOT)),
                group_name="uploads",
            ))
        except Exception as e:
            errors.append(f"{original_name}: {e}")
        finally:
            await file.close()

    if not uploaded and errors:
        raise HTTPException(status_code=400, detail=f"Upload failed: {'; '.join(errors)}")

    activation = _activate_uploads(session_id, [(u.name, u.rel_path) for u in uploaded])
    return {"files": uploaded, "activation": activation, "errors": errors}


@router.post("/sessions/create-and-upload")
@limiter.limit("30/minute")
async def create_session_and_upload(
    request: Request,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new session then upload files into it (used before first message)."""
    first_name = files[0].filename if files else "Uploaded files"
    session = await session_repository.create(
        db,
        session_id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=f"Upload: {first_name[:50]}",
    )

    upload_dir = get_upload_dir(session.id)
    uploaded: list[dict] = []

    for file in files:
        safe_name = sanitize_filename(file.filename or "unnamed")
        if not is_upload_allowed(safe_name):
            continue
        dest = upload_dir / safe_name
        content = await file.read()
        if _too_large(content):
            continue
        dest.write_bytes(content)
        uploaded.append({
            "name": safe_name,
            "size_kb": round(dest.stat().st_size / 1024, 2),
            "rel_path": str(dest.relative_to(STORAGE_ROOT)),
            "group_name": "uploads",
        })
        await file.close()

    activation = _activate_uploads(
        session.id, [(u["name"], u["rel_path"]) for u in uploaded])
    return {"session_id": session.id, "files": uploaded, "activation": activation}


async def _store_endpoint(session_id: str, slot: str, upload: UploadFile):
    """Store one NEB endpoint upload under a unique, slot-prefixed name.

    Prefixing with the slot guarantees the initial and final files never collide
    (a common case: both named ``POSCAR``) and that ``find_structure_in_session``
    resolves each by an exact, unambiguous name.
    """
    base = sanitize_filename(upload.filename or f"{slot}_POSCAR")
    if not is_upload_allowed(base):
        raise HTTPException(status_code=400,
                            detail=f"{slot} structure: file type not allowed ({base})")
    safe = f"neb_{slot}_{base}"
    content = await upload.read()
    await upload.close()
    if _too_large(content):
        raise HTTPException(status_code=400,
                            detail=f"{slot} structure exceeds {settings.max_upload_mb} MB limit")
    dest = get_upload_dir(session_id) / safe
    dest.write_bytes(content)
    return safe


async def _store_optional(session_id: str, upload: UploadFile | None) -> str | None:
    """Store an optional single-structure upload for a direct tool launch.

    Returns the stored safe name when a file is supplied (so the tool runs on
    exactly that structure), or ``None`` when no file is given — in which case
    the tool auto-detects the session's active structure (poscar_name=None).
    """
    if upload is None or not (upload.filename or "").strip():
        return None
    safe = sanitize_filename(upload.filename or "structure")
    if not is_upload_allowed(safe):
        raise HTTPException(status_code=400,
                            detail=f"structure: file type not allowed ({safe})")
    content = await upload.read()
    await upload.close()
    if _too_large(content):
        raise HTTPException(status_code=400,
                            detail=f"structure exceeds {settings.max_upload_mb} MB limit")
    dest = get_upload_dir(session_id) / safe
    dest.write_bytes(content)
    return safe


async def _run_tool_launch(session_id: str, user_id: int, call):
    """Run a synchronous ``material_tools`` launch in a worker thread.

    Mirrors ``launch_neb``: ContextVars don't propagate async→thread, so set the
    session dir + request identity inside the thread before invoking the tool.
    Raises HTTP 400 if the tool returns an error envelope.
    """
    def _run():
        set_session_dir(str(get_session_dir(session_id)))
        set_request_identity(user_id, session_id)
        return call()

    result = await asyncio.get_running_loop().run_in_executor(None, _run)
    if isinstance(result, dict) and result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "Launch failed"))
    return result


@router.post("/sessions/{session_id}/optimize")
@limiter.limit("10/minute")
async def launch_optimize(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    fmax: float = Form(0.02),
    cell_relax: str = Form("none"),
    optimizer: str = Form("FIRE"),
    max_steps: int = Form(1000),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch a geometry-optimization job from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    from app.tools import material_tools
    return await _run_tool_launch(session_id, current_user.id, lambda: material_tools.optimize_structure(
        poscar_name=name,
        fmax=float(fmax),
        cell_relax=cell_relax,
        optimizer=optimizer,
        max_steps=int(max_steps),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
    ))


@router.post("/sessions/{session_id}/md")
@limiter.limit("10/minute")
async def launch_md(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    ensemble: str = Form("nvt"),
    temperature: float = Form(300.0),
    nsw: int = Form(2000),
    timestep: float = Form(1.0),
    pressure: float = Form(0.0),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch a molecular-dynamics (NVT/NPT) job from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    from app.tools import material_tools
    return await _run_tool_launch(session_id, current_user.id, lambda: material_tools.run_md_simulation(
        poscar_name=name,
        ensemble=ensemble,
        temperature=float(temperature),
        nsw=int(nsw),
        timestep=float(timestep),
        pressure=float(pressure),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
    ))


@router.post("/sessions/{session_id}/phonons")
@limiter.limit("10/minute")
async def launch_phonons(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    supercell: str = Form("3 3 3"),
    disp_distance: float = Form(0.01),
    mesh: int = Form(20),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch a phonon (phonopy) job from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    from app.tools import material_tools
    return await _run_tool_launch(session_id, current_user.id, lambda: material_tools.compute_phonons(
        poscar_name=name,
        supercell=supercell,
        disp_distance=float(disp_distance),
        mesh=int(mesh),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
    ))


@router.post("/sessions/{session_id}/elastic")
@limiter.limit("10/minute")
async def launch_elastic(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    fmax: float = Form(0.01),
    max_steps: int = Form(300),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch an elastic / mechanical-properties job from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    from app.tools import material_tools
    return await _run_tool_launch(session_id, current_user.id, lambda: material_tools.compute_elastic_tensor(
        poscar_name=name,
        fmax=float(fmax),
        max_steps=int(max_steps),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
    ))


@router.post("/sessions/{session_id}/sqs")
@limiter.limit("10/minute")
async def launch_sqs(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    supercell: str = Form("2 2 2"),
    target_comp: str | None = Form(None),
    n_parallel: int = Form(4),
    time_budget_s: int = Form(600),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch an SQS (special quasi-random structure) job from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    from app.tools import material_tools
    return await _run_tool_launch(session_id, current_user.id, lambda: material_tools.generate_sqs(
        cif_name=name,
        target_comp=(target_comp or None),
        supercell=supercell,
        n_parallel=int(n_parallel),
        time_budget_s=int(time_budget_s),
    ))


@router.post("/sessions/{session_id}/neb")
@limiter.limit("10/minute")
async def launch_neb(
    request: Request,
    session_id: str,
    initial: UploadFile = File(...),
    final: UploadFile = File(...),
    n_images: int = Form(7),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    climb: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch an NEB job from two uploaded endpoint structures (UI workflow panel).

    Stores both files in the session, then calls the same ``compute_neb`` tool the
    agent uses — bypassing chat/file-resolution so the user explicitly picks the
    initial and final states. Returns the queued-job envelope (job_id) for the
    dashboard to track.
    """
    await get_session_for_user(session_id, current_user, db)

    initial_name = await _store_endpoint(session_id, "initial", initial)
    final_name = await _store_endpoint(session_id, "final", final)

    from app.tools import material_tools

    def _run():
        # Async→thread ContextVars don't propagate; set identity explicitly
        # (same pattern the agent graph uses before invoking a tool).
        set_session_dir(str(get_session_dir(session_id)))
        set_request_identity(current_user.id, session_id)
        return material_tools.compute_neb(
            poscar_name=initial_name,
            final_poscar_name=final_name,
            n_images=int(n_images),
            calculator_type=calculator_type,
            calculator_model=calculator_model or None,
            climb=bool(climb),
        )

    result = await asyncio.get_running_loop().run_in_executor(None, _run)
    if isinstance(result, dict) and result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "NEB launch failed"))
    return result
