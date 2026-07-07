"""File upload endpoints."""

import asyncio
import json
import time
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
from app.repositories import message_repository, session_repository
from app.schemas.upload import UploadedFileOut
from app.services.storage.file_service import (
    STORAGE_ROOT,
    find_structure_in_session,
    get_session_dir,
    get_upload_dir,
    is_upload_allowed,
    list_new_files,
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
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.optimize_structure(
        poscar_name=name,
        fmax=float(fmax),
        cell_relax=cell_relax,
        optimizer=optimizer,
        max_steps=int(max_steps),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
    ))
    await _log_manual_run(db, session_id, tool="optimize_structure",
                          label="Geometry optimization", result=result, t_before=t_before)
    return result


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
    thermostat: str = Form("langevin"),
    pressure: float = Form(0.0),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch a molecular-dynamics (NVT/NPT/NVE) job from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.run_md_simulation(
        poscar_name=name,
        ensemble=ensemble,
        temperature=float(temperature),
        nsw=int(nsw),
        timestep=float(timestep),
        thermostat=thermostat,
        pressure=float(pressure),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
    ))
    await _log_manual_run(db, session_id, tool="run_md_simulation",
                          label="Molecular dynamics", result=result, t_before=t_before)
    return result


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
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.compute_phonons(
        poscar_name=name,
        supercell=supercell,
        disp_distance=float(disp_distance),
        mesh=int(mesh),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
    ))
    await _log_manual_run(db, session_id, tool="compute_phonons",
                          label="Phonons", result=result, t_before=t_before)
    return result


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
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.compute_elastic_tensor(
        poscar_name=name,
        fmax=float(fmax),
        max_steps=int(max_steps),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
    ))
    await _log_manual_run(db, session_id, tool="compute_elastic_tensor",
                          label="Elastic / mechanical", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/sqs/sublattices")
@limiter.limit("30/minute")
async def detect_sublattices(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    symprec: float = Form(0.1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the symmetry-distinct sublattices of the active/uploaded structure.

    Powers the SQS panel's "Detect sublattices" button: the user sees which sites
    (Sr, Ti, O…) they can turn into a random alloy before launching the search.
    Synchronous and fast — no job is enqueued.
    """
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    from app.tools import material_tools
    return await _run_tool_launch(session_id, current_user.id, lambda: material_tools.list_sublattices(
        cif_name=name,
        symprec=float(symprec),
    ))


@router.post("/sessions/{session_id}/sqs")
@limiter.limit("10/minute")
async def launch_sqs(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    supercell: str = Form("2 2 2"),
    sublattice_comp: str | None = Form(None),
    target_comp: str | None = Form(None),
    n_parallel: int = Form(4),
    time_budget_s: int = Form(600),
    relax: bool = Form(True),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch an SQS (special quasi-random structure) job from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.generate_sqs(
        cif_name=name,
        sublattice_comp=(sublattice_comp or None),
        target_comp=(target_comp or None),
        supercell=supercell,
        n_parallel=int(n_parallel),
        time_budget_s=int(time_budget_s),
        relax=bool(relax),
        calculator_type=calculator_type,
        calculator_model=(calculator_model or None),
    ))
    await _log_manual_run(db, session_id, tool="generate_sqs",
                          label="SQS (random alloy)", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/migration-paths")
@limiter.limit("30/minute")
async def list_migration_paths(
    request: Request,
    session_id: str,
    element: str = Form(...),
    cutoff: float = Form(5.0),
    structure: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List candidate migration hops for ``element`` (NEB pre-flight, no job).

    Powers the NEB card's "List hops" button: the user picks the migrating element
    and gets the ranked source→dest site pairs to choose from before launching a
    (long) NEB. Analyses the structure exactly as supplied (no auto-supercell) —
    prepare a larger cell with make_supercell first if the ion needs more hop space.
    Synchronous and fast.
    """
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    from app.tools import material_tools
    return await _run_tool_launch(session_id, current_user.id,
        lambda: material_tools.list_migration_paths(
            element=element,
            cutoff=float(cutoff),
            poscar_name=name,
        ))


@router.post("/sessions/{session_id}/neb")
@limiter.limit("10/minute")
async def launch_neb(
    request: Request,
    session_id: str,
    initial: UploadFile = File(None),
    final: UploadFile = File(None),
    structure: UploadFile = File(None),
    migrating_element: str | None = Form(None),
    source_site: int | None = Form(None),
    dest_site: int | None = Form(None),
    endpoint_fmax: float = Form(0.03),
    n_images: int = Form(8),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    climb: bool = Form(True),
    run_frequencies: bool = Form(True),
    emit_vasp_inputs: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch an NEB job from the UI workflow panel — two ways to pick the hop.

    • **Migrating element** (``migrating_element`` + optional ``source_site`` /
      ``dest_site`` from ``/migration-paths``): the tool builds the vacancy-mediated
      endpoints from the cell as supplied (run make_supercell first for hop space).
    • **Two endpoint files** (``initial`` + ``final``): the user supplies their own
      (already optimised) end states.

    Either way it calls the same ``compute_neb`` tool the agent uses.
    """
    await get_session_for_user(session_id, current_user, db)

    from app.tools import material_tools

    if migrating_element and migrating_element.strip():
        # Hop mode: analyse/build from a (possibly uploaded) base structure.
        base_name = await _store_optional(session_id, structure)
        kwargs = dict(
            poscar_name=base_name,
            migrating_element=migrating_element.strip(),
            source_site=source_site,
            dest_site=dest_site,
        )
    else:
        # Two-file mode: explicit initial + final end states.
        if initial is None or final is None or not (initial.filename or "").strip() \
                or not (final.filename or "").strip():
            raise HTTPException(status_code=400,
                detail="Provide a migrating_element, or both initial and final files.")
        initial_name = await _store_endpoint(session_id, "initial", initial)
        final_name = await _store_endpoint(session_id, "final", final)
        kwargs = dict(poscar_name=initial_name, final_poscar_name=final_name)

    def _run():
        # Async→thread ContextVars don't propagate; set identity explicitly
        # (same pattern the agent graph uses before invoking a tool).
        set_session_dir(str(get_session_dir(session_id)))
        set_request_identity(current_user.id, session_id)
        return material_tools.compute_neb(
            n_images=int(n_images),
            endpoint_fmax=float(endpoint_fmax),
            calculator_type=calculator_type,
            calculator_model=calculator_model or None,
            climb=bool(climb),
            run_frequencies=bool(run_frequencies),
            emit_vasp_inputs=bool(emit_vasp_inputs),
            **kwargs,
        )

    t_before = time.time()
    result = await asyncio.get_running_loop().run_in_executor(None, _run)
    if isinstance(result, dict) and result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "NEB launch failed"))
    await _log_manual_run(db, session_id, tool="compute_neb",
                          label="NEB migration barrier", result=result, t_before=t_before)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Manual structure-tool launchers (Step 2)
#
# These mirror the heavy launchers above but for the instant structure tools
# (make_supercell / add_vacuum / make_slab / add_adsorbate / convert_structure).
# After the tool runs they record one assistant "action" message in the session
# so the manual run shows up in the chat timeline as the same tool card the
# agent produces — tagged ``manual: true``. The agent then reads it back as
# history, so manual and conversational use share one workflow.
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_status(status: str) -> str:
    """Match the agent's card status (``ok`` → ``success``); inline to avoid
    importing the agent graph into the API layer."""
    return "success" if status == "ok" else (status or "unknown")


async def _log_manual_run(
    db: AsyncSession, session_id: str, *, tool: str, label: str,
    result: dict, t_before: float,
) -> None:
    """Persist a manual tool run as an assistant message with a tool card.

    The card JSON matches what ``fetchMessages`` parses on the frontend
    (``{tool, label, status, files}``) plus a ``manual`` flag for the badge.
    ``files`` is scoped to whatever the tool wrote after ``t_before``.
    """
    card = {
        "tool":   tool,
        "label":  label,
        "status": _normalize_status(result.get("status", "unknown")),
        "msg":    result.get("message", ""),
        "files":  list_new_files(session_id, t_before),
        "manual": True,
    }
    # Async-job launches return a job_id (no files yet). Carry it on the card so
    # the chat timeline shows "<tool> — job <id> running" and links to the Jobs
    # tab, instead of rendering nothing.
    if result.get("job_id"):
        card["job_id"] = result["job_id"]
        card["job_type"] = result.get("type")
    content = result.get("message") or f"Ran {label}"
    await message_repository.add(
        db, session_id=session_id, role="assistant",
        content=content, tool_result=json.dumps([card]),
    )


@router.post("/sessions/{session_id}/make_supercell")
@limiter.limit("20/minute")
async def launch_make_supercell(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    scaling: str = Form("2 2 1"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Build a supercell of the active structure from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.make_supercell(
        scaling=scaling,
        poscar_path=name,
    ))
    await _log_manual_run(db, session_id, tool="make_supercell",
                          label="Supercell", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/add_vacuum")
@limiter.limit("20/minute")
async def launch_add_vacuum(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    axis: str = Form("c"),
    thickness: float = Form(15.0),
    side: str = Form("both"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the vacuum gap of the active structure from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.add_vacuum(
        axis=axis,
        thickness=float(thickness),
        side=side,
        poscar_path=name,
    ))
    await _log_manual_run(db, session_id, tool="add_vacuum",
                          label="Add vacuum", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/make_slab")
@limiter.limit("20/minute")
async def launch_make_slab(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    miller: str = Form("1 1 1"),
    layers: int | None = Form(None),
    min_slab_size: float = Form(10.0),
    min_vacuum_size: float = Form(15.0),
    shift: float = Form(0.0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cut a surface slab of the active structure from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.make_slab(
        miller=miller,
        layers=(int(layers) if layers is not None else None),
        min_slab_size=float(min_slab_size),
        min_vacuum_size=float(min_vacuum_size),
        shift=float(shift),
        poscar_path=name,
    ))
    await _log_manual_run(db, session_id, tool="make_slab",
                          label="Make slab", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/add_adsorbate")
@limiter.limit("20/minute")
async def launch_add_adsorbate(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    molecule: str = Form(...),
    site_type: str = Form("ontop"),
    atom_index: str | None = Form(None),
    distance: float = Form(2.0),
    relax: bool = Form(False),
    calculator_type: str = Form("mace"),
    calculator_model: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Adsorb a molecule on the active slab from the UI tool panel.

    ``relax=False`` (default) places the molecule geometrically and returns at
    once; ``relax=True`` enqueues an AdsorbML-style background job (job_id).
    ``atom_index`` (0-based) targets a specific slab atom instead of a site_type.
    """
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    if atom_index in (None, ""):
        ai = None
    else:
        try:
            ai = int(atom_index)
        except ValueError:
            return {"status": "error",
                    "message": f"atom_index must be a whole number, got {atom_index!r}."}
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.add_adsorbate(
        molecule=molecule,
        site_type=site_type,
        atom_index=ai,
        distance=float(distance),
        relax=bool(relax),
        calculator_type=calculator_type,
        calculator_model=calculator_model or None,
        poscar_path=name,
    ))
    await _log_manual_run(db, session_id, tool="add_adsorbate",
                          label="Add adsorbate", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/convert_structure")
@limiter.limit("20/minute")
async def launch_convert_structure(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    to_format: str = Form("cif"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Write the active structure in another file format from the UI tool panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.convert_structure(
        to_format=to_format,
        poscar_path=name,
    ))
    await _log_manual_run(db, session_id, tool="convert_structure",
                          label="Convert format", result=result, t_before=t_before)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Manual VASP-input + defect launchers
#
# Same instant pattern as the structure tools above. The VASP-input tools
# (generate_vasp_inputs / generate_poscar / generate_kpoints) resolve their
# input through ``_resolve_structure``, which — unlike the build/defect tools —
# does NOT auto-detect the session's active POSCAR. So when no file is uploaded
# we resolve the active structure name inside the tool worker thread (where the
# session context is set) via ``_active_structure_name``.
# ─────────────────────────────────────────────────────────────────────────────

def _active_structure_name(name: str | None):
    """The uploaded file name, else the session's active structure file name.

    Must run inside the tool worker thread (session ContextVar set). Returns an
    error envelope when nothing is available, so the caller can surface a 400
    instead of a 500.
    """
    if name:
        return name
    try:
        return find_structure_in_session(None).name
    except FileNotFoundError:
        return {"status": "error",
                "message": ("No active structure in this session. Upload or "
                            "generate a structure first.")}


@router.post("/sessions/{session_id}/generate_vasp_inputs")
@limiter.limit("20/minute")
async def launch_generate_vasp_inputs(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    task: str = Form("relaxation"),
    cell_relax: str = Form("none"),
    functional: str = Form("pbe"),
    vdw: str = Form("none"),
    soc: bool = Form(False),
    hubbard_u: bool = Form(False),
    dipole: bool = Form(False),
    charge: float = Form(0.0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a full VASP input set (POSCAR + INCAR + KPOINTS) from the UI panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools

    def _go():
        resolved = _active_structure_name(name)
        if isinstance(resolved, dict):
            return resolved
        return material_tools.generate_vasp_inputs(
            poscar_path=resolved,
            task=task,
            cell_relax=cell_relax,
            functional=functional,
            vdw=vdw,
            soc=bool(soc),
            hubbard_u=bool(hubbard_u),
            dipole=bool(dipole),
            charge=float(charge),
        )

    result = await _run_tool_launch(session_id, current_user.id, _go)
    await _log_manual_run(db, session_id, tool="generate_vasp_inputs",
                          label="VASP inputs", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/generate_poscar")
@limiter.limit("20/minute")
async def launch_generate_poscar(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate ONLY a POSCAR for the active (or uploaded) structure from the UI panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools

    def _go():
        resolved = _active_structure_name(name)
        if isinstance(resolved, dict):
            return resolved
        return material_tools.generate_poscar(poscar_path=resolved)

    result = await _run_tool_launch(session_id, current_user.id, _go)
    await _log_manual_run(db, session_id, tool="generate_poscar",
                          label="Generate POSCAR", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/generate_kpoints")
@limiter.limit("20/minute")
async def launch_generate_kpoints(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    accuracy_level: str = Form("Medium"),
    gamma_centered: bool = Form(True),
    custom_kppa: int | None = Form(None),
    explicit_mesh: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Write a KPOINTS file at a chosen accuracy level from the UI panel."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools

    def _go():
        # An explicit mesh needs no structure; only resolve one otherwise.
        resolved = None
        if not (explicit_mesh and explicit_mesh.strip()):
            resolved = _active_structure_name(name)
            if isinstance(resolved, dict):
                return resolved
        return material_tools.generate_kpoints(
            accuracy_level=accuracy_level,
            gamma_centered=bool(gamma_centered),
            custom_kppa=(int(custom_kppa) if custom_kppa is not None else None),
            explicit_mesh=(explicit_mesh or None),
            poscar_path=resolved,
        )

    result = await _run_tool_launch(session_id, current_user.id, _go)
    await _log_manual_run(db, session_id, tool="generate_kpoints",
                          label="Generate KPOINTS", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/create_vacancy")
@limiter.limit("20/minute")
async def launch_create_vacancy(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    element: str | None = Form(None),
    count: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create one or more vacancies in the active structure (UI panel)."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.create_vacancy(
        element=(element or None),
        count=(count or None),
        poscar_path=name,
    ))
    await _log_manual_run(db, session_id, tool="create_vacancy",
                          label="Create vacancy", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/create_substitution")
@limiter.limit("20/minute")
async def launch_create_substitution(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    from_element: str = Form(...),
    to_element: str = Form(...),
    count: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Substitute one or more atoms of one element for another (UI panel)."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.create_substitution(
        from_element=from_element,
        to_element=to_element,
        count=(count or None),
        poscar_path=name,
    ))
    await _log_manual_run(db, session_id, tool="create_substitution",
                          label="Create substitution", result=result, t_before=t_before)
    return result


@router.post("/sessions/{session_id}/create_interstitial")
@limiter.limit("20/minute")
async def launch_create_interstitial(
    request: Request,
    session_id: str,
    structure: UploadFile = File(None),
    insert_element: str = Form(...),
    count: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Insert one or more interstitial atoms in the active structure (UI panel)."""
    await get_session_for_user(session_id, current_user, db)
    name = await _store_optional(session_id, structure)
    t_before = time.time()
    from app.tools import material_tools
    result = await _run_tool_launch(session_id, current_user.id, lambda: material_tools.create_interstitial(
        insert_element=insert_element,
        count=(count or None),
        poscar_path=name,
    ))
    await _log_manual_run(db, session_id, tool="create_interstitial",
                          label="Create interstitial", result=result, t_before=t_before)
    return result
