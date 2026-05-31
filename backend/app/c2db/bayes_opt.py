
# app/c2db/bayes_opt.py
# Bayesian Optimization loop over C2DB 2D materials.
#
# Flow:
#   1. Search C2DB for candidate materials matching user filters
#   2. Random initial sampling — generate POSCAR + MACE relax
#   3. Build Gaussian Process surrogate model on observed (features, target) pairs
#   4. Acquisition function (EI or UCB) selects next material
#   5. Evaluate selected material with MACE
#   6. Repeat until max_iterations
#   7. Save ranked candidates CSV + JSON report
 
import os
import json
import logging
import time
from pathlib import Path
from typing import Optional
 
logger = logging.getLogger(__name__)
 
 
def _get_runs_dir() -> str:
    """Get or create the session runs directory."""
    runs_dir = os.environ.get("MATERIA_SESSION_RUNS_DIR")
    if not runs_dir:
        runs_dir = os.path.join(os.getcwd(), "materia_test_run")
        os.environ["MATERIA_SESSION_RUNS_DIR"] = runs_dir
    os.makedirs(runs_dir, exist_ok=True)
    return runs_dir
 
 
def _featurize(entry: dict) -> list[float]:
    """
    Convert a C2DB entry dict to a numeric feature vector for the GP.
    Uses only properties that are commonly available in C2DB.
    Missing values are filled with 0 — GP handles this gracefully.
    """
    return [
        float(entry.get("bandgap_pbe")       or 0.0),
        float(entry.get("heat_of_formation")  or 0.0),
        float(entry.get("energy_above_hull")  or 0.0),
        float(entry.get("magnetic_moment")    or 0.0),
        # encode magnetic state as numeric
        {"NM": 0.0, "FM": 1.0, "AFM": 2.0}.get(
            str(entry.get("magnetic_state") or "NM"), 0.0
        ),
    ]
 
 
def _compute_target(result: dict, objective: str) -> Optional[float]:
    """
    Extract the scalar target value from a MACE relaxation result.
    Returns None if the result is missing the required property.
    """
    if objective == "maximize_bandgap":
        return result.get("bandgap_relaxed")          # filled in after MACE
    elif objective == "minimize_energy":
        e = result.get("final_energy_ev")
        return -e if e is not None else None           # negate for maximization
    elif objective == "minimize_formation":
        hf = result.get("heat_of_formation")
        return -hf if hf is not None else None
    elif objective == "maximize_stability":
        hull = result.get("energy_above_hull")
        return -hull if hull is not None else None
    return None
 
 
def _ei_acquisition(mu: float, sigma: float, best_so_far: float) -> float:
    """
    Expected Improvement acquisition function.
    Returns EI score — higher = more promising candidate.
    """
    import math
    if sigma <= 0:
        return 0.0
    z   = (mu - best_so_far) / sigma
    cdf = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    return (mu - best_so_far) * cdf + sigma * pdf
 
 
def run_c2db_bayesian_optimization(
    objective:             str             = "maximize_bandgap",
    formula:               Optional[str]   = None,
    elements:              Optional[list]  = None,
    bandgap_min:           Optional[float] = None,
    bandgap_max:           Optional[float] = None,
    initial_samples:       int             = 5,
    max_iterations:        int             = 10,
    acquisition_function:  str             = "EI",
    mlp_backend:           str             = "MACE",
    mace_model_path:       Optional[str]   = None,
    fmax:                  float           = 0.05,
    steps:                 int             = 300,
    device:                Optional[str]   = None,
) -> dict:
    """
    Bayesian Optimization over C2DB 2D materials.
 
    Iteratively selects the most promising 2D material to evaluate
    using a Gaussian Process surrogate + EI/UCB acquisition function.
 
    Args:
        objective:            maximize_bandgap | minimize_energy |
                              minimize_formation | maximize_stability
        formula:              Optional formula filter for search space
        elements:             Optional element filter
        bandgap_min/max:      Optional bandgap filter for search space
        initial_samples:      Random evaluations before GP fits (default 5)
        max_iterations:       Total BO iterations including initial (default 10)
        acquisition_function: EI or UCB (default EI)
        mlp_backend:          MACE or CHGNet (default MACE)
        mace_model_path:      MACE model path or 'mace-mp-0'
        fmax:                 Force convergence for relaxation (default 0.05)
        steps:                Max relaxation steps (default 300)
        device:               'cuda', 'cpu', or None for auto
    """
    runs_dir = _get_runs_dir()
    bo_dir   = Path(runs_dir) / "bayesian_optimization"
    bo_dir.mkdir(parents=True, exist_ok=True)
 
    start_time = time.time()
 
    # ── Step 1: build candidate pool from C2DB ────────────────────────────────
    try:
        from .c2db_loader import validate_c2db_config, get_c2db_config
        from .c2db_search import search_c2db_ase_db, search_c2db_cif_folder
 
        valid, err = validate_c2db_config()
        if not valid:
            return {"status": "error", "message": err}
 
        fmt = get_c2db_config()["format"]
        if fmt == "ase_db":
            candidates = search_c2db_ase_db(
                formula=formula, elements=elements,
                bandgap_min=bandgap_min, bandgap_max=bandgap_max,
                max_results=200,
            )
        else:
            candidates = search_c2db_cif_folder(
                formula=formula, elements=elements, max_results=200
            )
 
        if not candidates:
            return {
                "status":  "error",
                "message": "No C2DB candidates found for the given filters.",
            }
 
        total_candidates = len(candidates)
        print(f"[BO] Candidate pool: {total_candidates} materials")
 
    except Exception as e:
        return {"status": "error", "message": f"C2DB search failed: {e}"}
 
    # ── Step 2: generate POSCARs for all candidates ───────────────────────────
    # we resolve POSCARs lazily in the loop to avoid upfront cost
    def get_poscar_for_candidate(entry: dict) -> Optional[str]:
        """Generate POSCAR for one candidate, return path or None on failure."""
        from .c2db_tools import generate_poscar_from_c2db
        cand_dir = str(bo_dir / (entry.get("formula") or entry["id"]).replace("/", "_"))
        os.makedirs(cand_dir, exist_ok=True)
        # temporarily redirect MATERIA_SESSION_RUNS_DIR to candidate folder
        orig = os.environ.get("MATERIA_SESSION_RUNS_DIR")
        os.environ["MATERIA_SESSION_RUNS_DIR"] = cand_dir
        try:
            r = generate_poscar_from_c2db(
                formula=entry.get("formula"),
                db_id=entry.get("db_id"),
                cif_path=entry.get("cif_path"),
            )
            if r.get("status") == "success":
                return r["poscar_path"]
        except Exception as ex:
            logger.warning(f"[BO] POSCAR generation failed for {entry.get('formula')}: {ex}")
        finally:
            if orig:
                os.environ["MATERIA_SESSION_RUNS_DIR"] = orig
            else:
                os.environ.pop("MATERIA_SESSION_RUNS_DIR", None)
        return None
 
    # ── Step 3: relax a candidate and get target value ────────────────────────
    def evaluate_candidate(entry: dict, poscar_path: str) -> Optional[float]:
        """Run MACE relaxation and return the target scalar. None on failure."""
        from .c2db_tools import relax_c2db_structure_with_mace
        orig = os.environ.get("MATERIA_SESSION_RUNS_DIR")
        cand_dir = str(Path(poscar_path).parent)
        os.environ["MATERIA_SESSION_RUNS_DIR"] = cand_dir
        try:
            r = relax_c2db_structure_with_mace(
                poscar_path=poscar_path,
                model_path=mace_model_path or os.environ.get("MACE_MODEL_PATH", "mace-mp-0"),
                fmax=fmax,
                steps=steps,
                device=device,
            )
            if r.get("status") == "success":
                # attach relaxation result to entry for target extraction
                entry["final_energy_ev"]    = r.get("final_energy_ev")
                entry["heat_of_formation"]  = entry.get("heat_of_formation")
                entry["energy_above_hull"]  = entry.get("energy_above_hull")
                return _compute_target(entry, objective)
        except Exception as ex:
            logger.warning(f"[BO] Evaluation failed for {entry.get('formula')}: {ex}")
        finally:
            if orig:
                os.environ["MATERIA_SESSION_RUNS_DIR"] = orig
            else:
                os.environ.pop("MATERIA_SESSION_RUNS_DIR", None)
        return None
 
    # ── Step 4: BO main loop ─────────────────────────────────────────────────
    observed_X      = []   # feature vectors of evaluated materials
    observed_y      = []   # target values of evaluated materials
    evaluated_ids   = set()
    history         = []   # full evaluation log
 
    import random
    random.shuffle(candidates)
 
    actual_initial = min(initial_samples, len(candidates))
    actual_iters   = min(max_iterations,  len(candidates))
 
    print(f"[BO] Starting: {actual_initial} initial + {actual_iters - actual_initial} BO iterations")
 
    for iteration in range(actual_iters):
        # ── pick next candidate ───────────────────────────────────────────────
        if iteration < actual_initial:
            # random initial phase
            candidate = next(
                (c for c in candidates if c["id"] not in evaluated_ids), None
            )
            if not candidate:
                break
            selection_method = "random"
        else:
            # GP-based acquisition
            if len(observed_y) < 2:
                # not enough data for GP yet — still random
                candidate = next(
                    (c for c in candidates if c["id"] not in evaluated_ids), None
                )
                selection_method = "random_fallback"
            else:
                try:
                    from sklearn.gaussian_process import GaussianProcessRegressor
                    from sklearn.gaussian_process.kernels import Matern
                    import numpy as np
 
                    gp = GaussianProcessRegressor(
                        kernel=Matern(nu=2.5),
                        normalize_y=True,
                        n_restarts_optimizer=3,
                    )
                    gp.fit(np.array(observed_X), np.array(observed_y))
 
                    best_so_far = max(observed_y)
 
                    # score all unevaluated candidates
                    unevaluated = [c for c in candidates if c["id"] not in evaluated_ids]
                    if not unevaluated:
                        break
 
                    feats    = np.array([_featurize(c) for c in unevaluated])
                    mu, sigma = gp.predict(feats, return_std=True)
 
                    if acquisition_function.upper() == "UCB":
                        scores = mu + 2.0 * sigma
                    else:  # EI
                        scores = [_ei_acquisition(m, s, best_so_far)
                                  for m, s in zip(mu, sigma)]
 
                    best_idx  = int(max(range(len(scores)), key=lambda i: scores[i]))
                    candidate = unevaluated[best_idx]
                    selection_method = acquisition_function.upper()
 
                except Exception as gp_err:
                    logger.warning(f"[BO] GP failed: {gp_err} — falling back to random")
                    candidate = next(
                        (c for c in candidates if c["id"] not in evaluated_ids), None
                    )
                    selection_method = "random_fallback"
 
        if not candidate:
            break
 
        evaluated_ids.add(candidate["id"])
        formula_str = candidate.get("formula") or candidate["id"]
        print(f"[BO] Iteration {iteration+1}/{actual_iters}: {formula_str} ({selection_method})")
 
        # ── generate POSCAR + evaluate ────────────────────────────────────────
        poscar_path = get_poscar_for_candidate(candidate)
        if not poscar_path:
            history.append({
                "iteration": iteration + 1,
                "formula":   formula_str,
                "c2db_id":   candidate.get("id"),
                "status":    "poscar_failed",
                "target":    None,
                "method":    selection_method,
            })
            continue
 
        target = evaluate_candidate(candidate, poscar_path)
        if target is None:
            history.append({
                "iteration": iteration + 1,
                "formula":   formula_str,
                "c2db_id":   candidate.get("id"),
                "status":    "eval_failed",
                "target":    None,
                "method":    selection_method,
            })
            continue
 
        observed_X.append(_featurize(candidate))
        observed_y.append(target)
 
        history.append({
            "iteration":      iteration + 1,
            "formula":        formula_str,
            "c2db_id":        candidate.get("id"),
            "status":         "success",
            "target":         target,
            "bandgap_pbe":    candidate.get("bandgap_pbe"),
            "heat_of_formation": candidate.get("heat_of_formation"),
            "magnetic_state": candidate.get("magnetic_state"),
            "final_energy_ev": candidate.get("final_energy_ev"),
            "method":         selection_method,
        })
 
    # ── Step 5: build ranked output ───────────────────────────────────────────
    successful = [h for h in history if h["status"] == "success" and h["target"] is not None]
    ranked     = sorted(successful, key=lambda x: x["target"], reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
        r["target_value"] = r.pop("target")
 
    best = ranked[0] if ranked else None
    elapsed = round(time.time() - start_time, 1)
 
    # ── Step 6: save CSV + JSON report ────────────────────────────────────────
    import csv
 
    history_csv = str(bo_dir / "optimization_history.csv")
    if history:
        fieldnames = list(history[0].keys())
        with open(history_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(history)
 
    report_json = str(bo_dir / "report.json")
    report = {
        "objective":       objective,
        "total_evaluated": len(successful),
        "total_candidates": total_candidates,
        "iterations":      actual_iters,
        "elapsed_sec":     elapsed,
        "best_material":   best,
        "ranked_candidates": ranked[:10],  # top 10
        "acquisition_function": acquisition_function,
        "mlp_backend":     mlp_backend,
    }
    with open(report_json, "w") as f:
        json.dump(report, f, indent=2, default=str)
 
    print(f"[BO] Done. Best: {best.get('formula') if best else 'none'} "
          f"target={best.get('target_value') if best else 'N/A'} in {elapsed}s")
 
    return {
        "status":              "success",
        "message":             (
            f"Bayesian Optimization complete. "
            f"Evaluated {len(successful)}/{actual_iters} materials in {elapsed}s. "
            f"Best: {best.get('formula') if best else 'none'} "
            f"(target={best.get('target_value', 'N/A') if best else 'N/A'})."
        ),
        "best_material":       best,
        "ranked_candidates":   ranked,
        "objective":           objective,
        "history_csv":         history_csv,
        "report_json":         report_json,
    }
 
