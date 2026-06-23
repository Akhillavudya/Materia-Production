"""Reference-data endpoints (redesign §13).

These were previously agent tools (`list_available_calculators`) or implicit
knowledge. They are static metadata the UI can fetch directly, not workflow steps.
"""

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.database.models import User
from app.domain.vasp import CellRelax, VaspTask
from app.services.simulation.calculator_factory import list_available_models

router = APIRouter()

# All tasks whose templates are wired in services/vasp/service.py.
_AVAILABLE_TASKS = [
    VaspTask.STATIC, VaspTask.RELAXATION, VaspTask.BAND, VaspTask.DOS,
    VaspTask.AIMD, VaspTask.ELASTIC, VaspTask.PHONON_DFPT, VaspTask.DIELECTRIC,
    VaspTask.BADER, VaspTask.ELF, VaspTask.WORKFUNCTION,
]


@router.get("/calculators")
async def get_calculators(current_user: User = Depends(get_current_user)):
    """List locally available MACE / MatterSim models with availability flags."""
    models = list_available_models()
    mace_ok = [m for m in models["mace"] if m["exists"]]
    msim_ok = [m for m in models["mattersim"] if m["exists"]]
    return {
        "models": models,
        "available": {"mace": len(mace_ok), "mattersim": len(msim_ok)},
    }


@router.post("/calculators/test")
async def test_calculators(current_user: User = Depends(get_current_user)):
    """Load + single-point eval each present model — a REAL health check.

    Unlike /calculators (disk-existence only), this confirms each checkpoint
    actually loads and runs. Heavier (loads models), so it's POST and on-demand.
    """
    from scripts.test_models import test_one  # local import: pulls in ASE/MACE

    models = list_available_models()
    results = []
    for calc_type, entries in models.items():
        for m in entries:
            if not m["exists"]:
                results.append({"type": calc_type, "model": m["name"],
                                "ok": None, "error": "not on disk"})
                continue
            results.append(test_one(calc_type, m["name"]))
    passed = sum(1 for r in results if r["ok"] is True)
    failed = sum(1 for r in results if r["ok"] is False)
    return {"results": results, "passed": passed, "failed": failed}


@router.get("/vasp/tasks")
async def get_vasp_tasks(current_user: User = Depends(get_current_user)):
    """List the supported VASP tasks and the cell-relaxation option schema."""
    return {
        "tasks": [t.value for t in _AVAILABLE_TASKS],
        "cell_relax": [c.value for c in CellRelax],
    }
