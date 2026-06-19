"""Job runners — executed inside the Celery worker (or an inline dev thread).

Each runner: load spec → mark running → run the pure simulation service with a
`ProgressReporter` → persist result + artifacts → mark terminal. The web process
never imports this module (it would pull in ASE/MACE); only the worker does.
"""

from __future__ import annotations

from pathlib import Path

from app.core.logging import get_logger
from app.domain.jobs import JobStatus, JobType
from app.jobs import store
from app.jobs.progress import ProgressReporter
from app.jobs.queue import celery_app
from app.services.storage.file_service import rel_to_storage

logger = get_logger(__name__)

# Map a logical artifact key to a coarse "kind" the dashboard can group/icon by.
_ARTIFACT_KIND = {
    "contcar": "structure", "trajectory_traj": "trajectory",
    "trajectory_xyz": "trajectory", "energy_csv": "data", "temp_csv": "data",
    "log": "log", "incar": "vasp", "kpoints": "vasp",
    "plot_energy": "plot", "plot_temp": "plot",
    "elastic_tensor_csv": "data", "stress_csv": "data", "mechanical_json": "data",
}


def _artifacts_from_files(files: dict) -> list[dict]:
    out: list[dict] = []
    for name, path in (files or {}).items():
        if not path:
            continue
        p = Path(path)
        if not p.exists():
            continue
        out.append({
            "name": p.name,
            "rel_path": rel_to_storage(p),
            "kind": _ARTIFACT_KIND.get(name, "file"),
        })
    return out


def _finalize(job_id: str, result: dict) -> None:
    """Translate a service result dict into the job's terminal DB state."""
    status = result.get("status")
    files = result.pop("files", {}) or {}
    artifacts = _artifacts_from_files(files)

    if status == "error":
        store.mark_failed(job_id, result.get("message", "Simulation failed."))
    elif status == "cancelled":
        store.mark_cancelled(job_id, result=result, artifacts=artifacts)
    else:
        store.mark_succeeded(job_id, result=result, artifacts=artifacts)


def _run(job_id: str, job_type: JobType) -> None:
    job = store.load_job(job_id)
    if job is None:
        logger.error("Job %s not found", job_id)
        return
    if job["status"] == JobStatus.CANCELLED.value:
        store.mark_cancelled(job_id)
        return

    store.mark_running(job_id)
    reporter = ProgressReporter(job_id)
    spec = job["spec"]
    params = spec.get("params", {})
    calc = job.get("calculator") or spec.get("calculator") or {"type": "mace"}

    try:
        if job_type is JobType.OPTIMIZE:
            from app.services.simulation.optimization import run_optimization
            result = run_optimization(
                poscar_path=spec["poscar_path"],
                output_dir=spec["output_dir"],
                fmax=params.get("fmax", 0.02),
                cell_relax=params.get("cell_relax", "none"),
                optimizer=params.get("optimizer", "FIRE"),
                max_steps=params.get("max_steps", 1000),
                calculator=calc,
                generate_vasp_inputs=spec.get("emit_vasp_inputs", True),
                progress_callback=reporter,
            )
        elif job_type is JobType.MD:
            from app.services.simulation.md import run_md
            result = run_md(
                poscar_path=spec["poscar_path"],
                output_dir=spec["output_dir"],
                ensemble=params.get("ensemble", "nvt"),
                temperature=params.get("temperature", 300.0),
                nsw=params.get("nsw", 10000),
                timestep=params.get("timestep", 1.0),
                thermostat=params.get("thermostat", "langevin"),
                pressure=params.get("pressure", 0.0),
                log_interval=params.get("log_interval", 10),
                calculator=calc,
                generate_vasp_inputs=spec.get("emit_vasp_inputs", True),
                progress_callback=reporter,
            )
            _attach_md_plots(result, spec["output_dir"])
        elif job_type is JobType.ELASTIC:
            from app.services.simulation.elastic import run_elastic
            result = run_elastic(
                poscar_path=spec["poscar_path"],
                output_dir=spec["output_dir"],
                fmax=params.get("fmax", 0.01),
                strains=params.get("strains"),
                max_steps=params.get("max_steps", 300),
                symprec=params.get("symprec", 0.01),
                calculator=calc,
                generate_vasp_inputs=spec.get("emit_vasp_inputs", True),
                progress_callback=reporter,
            )
        else:
            raise ValueError(f"Unknown job type: {job_type}")
    except Exception as exc:  # noqa: BLE001 — any failure → job failed, not a crash
        logger.exception("Job %s crashed", job_id)
        store.mark_failed(job_id, str(exc))
        return

    _finalize(job_id, result)
    reporter.publish({"type": "done", "status": store.get_status(job_id)})


def _attach_md_plots(result: dict, output_dir: str) -> None:
    """Generate MD energy/temperature plots and add them to result['files']."""
    try:
        from app.services.simulation.plots import generate_md_plots
        out = Path(output_dir)
        plots = generate_md_plots(
            energy_csv=str(out / "md_energy.csv"),
            temp_csv=str(out / "md_temp.csv"),
            output_dir=str(out),
        )
        files = result.setdefault("files", {})
        if plots.get("energy_png"):
            files["plot_energy"] = plots["energy_png"]
        if plots.get("temp_png"):
            files["plot_temp"] = plots["temp_png"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("MD plot generation failed: %s", exc)


# ── Celery task registration (imported by the worker only) ────────────────────

@celery_app.task(name="jobs.optimize", bind=True)
def run_optimize_job(self, job_id: str) -> None:   # noqa: ARG001 (celery self)
    _run(job_id, JobType.OPTIMIZE)


@celery_app.task(name="jobs.md", bind=True)
def run_md_job(self, job_id: str) -> None:          # noqa: ARG001
    _run(job_id, JobType.MD)


@celery_app.task(name="jobs.elastic", bind=True)
def run_elastic_job(self, job_id: str) -> None:     # noqa: ARG001
    _run(job_id, JobType.ELASTIC)
