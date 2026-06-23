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
    "results_json": "data", "plot_energy": "plot", "plot_temp": "plot",
    "plot_convergence": "plot",
    "elastic_tensor_csv": "data", "stress_csv": "data", "mechanical_json": "data",
    "phonon_plot": "plot", "phonopy_yaml": "data", "band_csv": "data", "dos_csv": "data",
    "bestsqs_out": "data", "rndstr_in": "data", "sqscell_out": "data",
    "parent_cif": "structure", "sublattices_json": "data",
    "bestcorr_out": "data", "mcsqs_progress_csv": "data",
    "neb_mep": "plot", "neb_path_csv": "data", "neb_traj": "trajectory",
    "saddle_poscar": "structure",
    "adsorption_csv": "data",
    "convergence_report": "report", "convergence_json": "data",
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
                generate_vasp_inputs=spec.get("emit_vasp_inputs", False),
                progress_callback=reporter,
            )
            _attach_opt_plot(result, spec["output_dir"],
                             fmax_target=params.get("fmax", 0.02))
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
                relax_mode=params.get("relax_mode", "full"),
                calculator=calc,
                generate_vasp_inputs=spec.get("emit_vasp_inputs", True),
                progress_callback=reporter,
            )
        elif job_type is JobType.PHONON:
            from app.services.simulation.phonon import run_phonon
            result = run_phonon(
                poscar_path=spec["poscar_path"],
                output_dir=spec["output_dir"],
                supercell=tuple(params.get("supercell", (3, 3, 3))),
                disp_distance=params.get("disp_distance", 0.01),
                mesh=params.get("mesh", 20),
                calculator=calc,
                progress_callback=reporter,
            )
        elif job_type is JobType.SQS:
            from app.services.simulation.sqs import run_sqs
            result = run_sqs(
                cif_path=spec["poscar_path"],   # resolved disordered structure file
                output_dir=spec["output_dir"],
                target_comp=params.get("target_comp"),
                substitutions=params.get("substitutions"),
                supercell=tuple(params.get("supercell", (2, 2, 2))),
                cutoff=params.get("cutoff"),
                n_parallel=params.get("n_parallel", 4),
                target_objective=params.get("target_objective", -0.99),
                occ_threshold=params.get("occ_threshold", 0.05),
                time_budget_s=params.get("time_budget_s", 600),
                progress_callback=reporter,
            )
        elif job_type is JobType.NEB:
            from app.services.simulation.neb import run_neb
            result = run_neb(
                poscar_path=spec["poscar_path"],
                final_poscar_path=params["final_poscar_path"],
                output_dir=spec["output_dir"],
                n_images=params.get("n_images", 7),
                fmax=params.get("fmax", 0.05),
                max_steps=params.get("max_steps", 300),
                spring_k=params.get("spring_k", 1.0),
                climb=params.get("climb", True),
                relax_endpoints=params.get("relax_endpoints", True),
                optimizer=params.get("optimizer", "FIRE"),
                calculator=calc,
                progress_callback=reporter,
            )
        elif job_type is JobType.ADSORPTION:
            from app.services.structure.adsorption import relax_adsorption
            result = relax_adsorption(
                poscar_path=spec["poscar_path"],
                molecule=params["molecule"],
                output_dir=spec["output_dir"],
                calculator=calc,
                distance=params.get("distance", 2.0),
                site_types=tuple(params.get("site_types", ("ontop", "bridge", "hollow"))),
                max_configs=params.get("max_configs", 6),
                fmax=params.get("fmax", 0.05),
                max_steps=params.get("max_steps", 200),
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


def _attach_opt_plot(result: dict, output_dir: str, fmax_target: float | None = None) -> None:
    """Generate the relaxation convergence plot and add it to result['files'] (O1)."""
    try:
        from app.services.simulation.plots import generate_optimization_plot
        out = Path(output_dir)
        plot = generate_optimization_plot(
            energy_csv=str(out / "opt_energy.csv"),
            output_dir=str(out),
            fmax_target=fmax_target,
        )
        if plot.get("convergence_png"):
            result.setdefault("files", {})["plot_convergence"] = plot["convergence_png"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Optimization plot generation failed: %s", exc)


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


@celery_app.task(name="jobs.phonon", bind=True)
def run_phonon_job(self, job_id: str) -> None:      # noqa: ARG001
    _run(job_id, JobType.PHONON)


@celery_app.task(name="jobs.sqs", bind=True)
def run_sqs_job(self, job_id: str) -> None:         # noqa: ARG001
    _run(job_id, JobType.SQS)


@celery_app.task(name="jobs.neb", bind=True)
def run_neb_job(self, job_id: str) -> None:         # noqa: ARG001
    _run(job_id, JobType.NEB)


@celery_app.task(name="jobs.adsorption", bind=True)
def run_adsorption_job(self, job_id: str) -> None:  # noqa: ARG001
    _run(job_id, JobType.ADSORPTION)
