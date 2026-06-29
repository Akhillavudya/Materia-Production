"""System / compute-device endpoint (desktop Part C / C4 — the GPU pack).

``GET /api/system`` tells the UI which device the heavy ML‑potential simulations
will run on (GPU vs CPU), plus the build variant. The desktop "Running on …" badge
reads this so a user can confirm their GPU build is actually using the GPU — and,
if it silently fell back to CPU (wrong driver, no NVIDIA card), see that too.

Gated on ``enable_heavy_tools`` like /api/models: only the desktop edition runs
simulations locally, so on the lite web edition this 404s and the badge hides itself.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.services.simulation.calculator_factory import device_info

router = APIRouter(prefix="/system", tags=["system"])


@router.get("")
def get_system() -> dict:
    """Compute-device + build-variant info for the local backend."""
    if not settings.enable_heavy_tools:
        # Lite web edition doesn't run sims locally → no device to report.
        raise HTTPException(status_code=404, detail="System info unavailable on this edition")

    info = device_info()
    # The Electron shell stamps the build variant (cpu|gpu) into the env so the UI
    # can explain *why* a GPU build is on CPU ("this is the CPU build — install the
    # GPU build") vs ("GPU build, but no usable GPU detected").
    variant = os.environ.get("MATERIA_VARIANT", "").strip().lower() or "cpu"
    return {
        "variant": variant,
        "device": info["device"],
        "cuda_available": info["cuda_available"],
        "gpu_name": info["gpu_name"],
        "torch_version": info["torch_version"],
    }
