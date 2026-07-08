"""ML-potential model management (desktop Part C / C2).

Lets the desktop first-run screen list the ML checkpoints, see which are present,
trigger downloads, and poll progress. These routes only make sense where the heavy
simulations run locally, so they are gated on ``enable_heavy_tools`` — on the lite
web edition (gate off) they return 404 and the model UI never appears.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import get_current_user
from app.database.models import User
from app.services import model_manager, ollama_manager

router = APIRouter(prefix="/models", tags=["models"])


def _require_local_models() -> None:
    """Block these routes on the lite web edition (no local heavy compute)."""
    if not settings.enable_heavy_tools:
        raise HTTPException(
            status_code=404,
            detail="Model management is only available in the desktop app.",
        )


class DownloadRequest(BaseModel):
    # "recommended" | "all" | explicit list of model names.
    models: list[str] | str = "recommended"


@router.get("")
async def get_models(current_user: User = Depends(get_current_user)):
    """List every model with on-disk availability and live download progress."""
    _require_local_models()
    models = model_manager.list_models()
    present = sum(1 for m in models if m["exists"])
    return {"models": models, "present": present, "total": len(models)}


@router.post("/download")
async def download_models(
    body: DownloadRequest,
    current_user: User = Depends(get_current_user),
):
    """Start background downloads; returns the models actually queued."""
    _require_local_models()
    names = model_manager.resolve_names(body.models)
    if not names:
        raise HTTPException(status_code=400, detail="No known models in request.")
    queued = model_manager.start_downloads(names)
    return {"queued": queued, "requested": names}


# ── Offline chat brain (Ollama) ───────────────────────────────────────────────
# Parallel to the checkpoint routes above, but for the local LLM the agent falls
# back to offline. It lives in a separately-installed Ollama server, so instead of
# streaming a file we report server/model state and drive `ollama pull`.


@router.get("/llm")
async def get_llm(current_user: User = Depends(get_current_user)):
    """Offline-brain state: Ollama server reachable, model present, pull progress."""
    _require_local_models()
    return ollama_manager.status()


@router.post("/llm/pull")
async def pull_llm(current_user: User = Depends(get_current_user)):
    """Start `ollama pull <model>` in the background; returns the resulting status."""
    _require_local_models()
    return ollama_manager.start_pull()
