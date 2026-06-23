"""
backend/app/services/simulation/report.py
==========================================
Shared **convergence / diagnostics report** builder for the heavy simulation
services (optimize, MD, NEB, elastic, phonon).

Why this exists (plain language)
--------------------------------
A heavy job like NEB is not one run — it is several phases stitched together
(relax the initial endpoint, relax the final endpoint, then optimize the band in
two sub-phases). To a user watching a single progress bar this looks like the job
"ran three times" and "overshot" its step budget. It also never said the one thing
that matters: *did the energy actually converge, or do I need more steps?*

This module gives every heavy service a tiny, dependency-free way to record what
happened phase-by-phase and emit a human-readable ``convergence_report.md`` plus a
machine-readable ``convergence.json``. The markdown is the "detail file": a table
of phases (steps taken vs budget, converged?, final force, energy change) followed
by a plain-language **Verdict** that tells the user whether to rerun with a bigger
``max_steps``.

Nothing here imports ASE / pymatgen / numpy — it only formats numbers the services
already computed, so it is cheap and safe to import anywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── One phase of a multi-phase job ────────────────────────────────────────────

@dataclass
class PhaseRecord:
    """A single phase of a heavy job (e.g. one optimizer run)."""
    name: str
    step_budget: Optional[int] = None
    steps_taken: Optional[int] = None
    converged: Optional[bool] = None          # None = "not a convergence phase"
    final_fmax: Optional[float] = None         # eV/Å, if force-based
    fmax_target: Optional[float] = None
    energy_start: Optional[float] = None       # eV
    energy_end: Optional[float] = None         # eV
    notes: list[str] = field(default_factory=list)

    @property
    def hit_budget(self) -> bool:
        """True if the phase stopped because it ran out of steps (not converged)."""
        if self.converged:
            return False
        if self.step_budget is None or self.steps_taken is None:
            return False
        return self.steps_taken >= self.step_budget

    @property
    def delta_e(self) -> Optional[float]:
        if self.energy_start is None or self.energy_end is None:
            return None
        return self.energy_end - self.energy_start

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "step_budget": self.step_budget,
            "steps_taken": self.steps_taken,
            "converged": self.converged,
            "final_fmax_eV_A": self.final_fmax,
            "fmax_target_eV_A": self.fmax_target,
            "energy_start_eV": self.energy_start,
            "energy_end_eV": self.energy_end,
            "delta_e_eV": self.delta_e,
            "hit_step_budget": self.hit_budget,
            "notes": list(self.notes),
        }


# ── The full report for one job ────────────────────────────────────────────────

# Absolute ceiling for a "rerun with more steps" recommendation. Mirrors
# settings.max_opt_steps but kept as a plain constant so this module stays free of
# the settings import (and works in scripts / tests).
_MAX_RECOMMENDED_STEPS = 5000


@dataclass
class ConvergenceReport:
    """Collects phases + job metadata and renders the report artifacts."""
    tool: str                                  # e.g. "compute_neb"
    title: str                                 # human title, e.g. "NEB migration barrier"
    formula: Optional[str] = None
    calculator: Optional[dict] = None
    phases: list[PhaseRecord] = field(default_factory=list)
    # Headline numbers the service wants surfaced at the top (free-form).
    summary: dict = field(default_factory=dict)
    # Final verdict lines (the service may append its own, e.g. "barrier = 0.3 eV").
    verdict_lines: list[str] = field(default_factory=list)
    elapsed_s: Optional[float] = None

    def add_phase(self, name: str, **kwargs) -> PhaseRecord:
        rec = PhaseRecord(name=name, **kwargs)
        self.phases.append(rec)
        return rec

    # ── Convergence helpers (shared logic, no numpy needed) ───────────────────

    @staticmethod
    def energy_converged(
        energies: list[float],
        n_atoms: int,
        tol_per_atom: float = 1e-3,
    ) -> tuple[Optional[bool], Optional[float]]:
        """Is the energy series still drifting?

        Compares the mean of the last ~10% of the series against the prior window
        (the same drift signal used by the MD service). Returns
        ``(converged, drift_per_atom_eV)``. ``converged`` is None when there is too
        little data to judge.
        """
        if not energies or len(energies) < 4 or not n_atoms:
            return None, None
        k = max(1, len(energies) // 10)
        tail = sum(energies[-k:]) / k
        head = sum(energies[:k]) / k
        drift = (tail - head) / n_atoms
        return (abs(drift) <= tol_per_atom), drift

    def recommend_steps(self, phase: PhaseRecord) -> Optional[int]:
        """Suggest a larger budget for a phase that hit its cap without converging."""
        if not phase.hit_budget or phase.step_budget is None:
            return None
        return min(phase.step_budget * 2, _MAX_RECOMMENDED_STEPS)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _auto_verdict(self) -> list[str]:
        """Build verdict lines from the phase records if the service added none."""
        lines: list[str] = []
        unconverged = [p for p in self.phases if p.converged is False]
        capped = [p for p in self.phases if p.hit_budget]
        if not unconverged:
            conv_phases = [p for p in self.phases if p.converged is True]
            if conv_phases:
                lines.append("All convergence phases reached their force threshold.")
        for p in capped:
            rec = self.recommend_steps(p)
            if rec:
                lines.append(
                    f"Phase '{p.name}' stopped at its step limit "
                    f"({p.steps_taken}/{p.step_budget}) WITHOUT converging — "
                    f"rerun with max_steps = {rec} to converge the energy."
                )
        return lines

    def to_json(self) -> dict:
        return {
            "tool": self.tool,
            "title": self.title,
            "formula": self.formula,
            "calculator": self.calculator,
            "elapsed_s": self.elapsed_s,
            "summary": self.summary,
            "phases": [p.to_dict() for p in self.phases],
            "verdict": self.verdict_lines or self._auto_verdict(),
        }

    def to_markdown(self) -> str:
        L: list[str] = []
        L.append(f"# {self.title} — convergence report")
        L.append("")
        if self.formula:
            L.append(f"- **Material:** {self.formula}")
        if self.calculator:
            ct = self.calculator.get("type")
            cm = self.calculator.get("model")
            L.append(f"- **ML potential:** {ct}" + (f" ({cm})" if cm else ""))
        L.append(f"- **Tool:** `{self.tool}`")
        if self.elapsed_s is not None:
            L.append(f"- **Wall time:** {self.elapsed_s}s")
        L.append("")

        # Headline summary numbers.
        if self.summary:
            L.append("## Summary")
            L.append("")
            for k, v in self.summary.items():
                L.append(f"- **{k}:** {v}")
            L.append("")

        # Phase table.
        if self.phases:
            L.append("## Phases")
            L.append("")
            L.append("| # | Phase | Steps (taken / budget) | Converged | Final force (eV/Å) | ΔE (eV) |")
            L.append("|---|-------|------------------------|-----------|--------------------|---------|")
            for i, p in enumerate(self.phases, 1):
                steps = (
                    f"{p.steps_taken} / {p.step_budget}"
                    if p.step_budget is not None else
                    (str(p.steps_taken) if p.steps_taken is not None else "—")
                )
                if p.converged is True:
                    conv = "✅ yes"
                elif p.converged is False:
                    conv = "❌ no (hit limit)" if p.hit_budget else "❌ no"
                else:
                    conv = "—"
                fmax = f"{p.final_fmax:.4f}" if p.final_fmax is not None else "—"
                de = f"{p.delta_e:+.4f}" if p.delta_e is not None else "—"
                L.append(f"| {i} | {p.name} | {steps} | {conv} | {fmax} | {de} |")
            L.append("")
            # Per-phase notes.
            noted = [(i, p) for i, p in enumerate(self.phases, 1) if p.notes]
            if noted:
                L.append("### Phase notes")
                L.append("")
                for i, p in noted:
                    for n in p.notes:
                        L.append(f"- *Phase {i} ({p.name}):* {n}")
                L.append("")

        # Verdict — the plain-language "do I need more steps?" answer.
        verdict = self.verdict_lines or self._auto_verdict()
        L.append("## Verdict")
        L.append("")
        if verdict:
            for line in verdict:
                L.append(f"- {line}")
        else:
            L.append("- Nothing to flag.")
        L.append("")
        return "\n".join(L)


def write_report(output_dir: str, report: ConvergenceReport) -> dict:
    """Write convergence_report.md + convergence.json into ``output_dir``.

    Returns a ``files``-style dict (keys ``convergence_report`` / ``convergence_json``)
    that a service can merge into its result so the job runner persists them as
    artifacts automatically. Best-effort: never raises (a report failure must not
    fail the science).
    """
    out: dict = {}
    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / "convergence_report.md"
        md_path.write_text(report.to_markdown())
        out["convergence_report"] = str(md_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[report] markdown write failed: {exc}")
    try:
        json_path = out_dir / "convergence.json"
        json_path.write_text(json.dumps(report.to_json(), indent=2))
        out["convergence_json"] = str(json_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[report] json write failed: {exc}")
    return out
