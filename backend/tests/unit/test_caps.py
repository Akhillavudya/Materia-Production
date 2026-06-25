"""Compute caps (Step 4) enforced at the contract layer (Step 9 regression net).

An impossible order — a million optimizer steps, more MD steps than the cap —
must be rejected *before* it ever reaches the job queue. These tests pin that the
``le=settings.max_*`` bounds on the tool contracts actually bite.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.tools.contracts import OptimizeStructureInput, RunMdSimulationInput


def test_optimize_steps_at_cap_accepted():
    c = OptimizeStructureInput(max_steps=settings.max_opt_steps)
    assert c.max_steps == settings.max_opt_steps


def test_optimize_steps_over_cap_rejected():
    with pytest.raises(ValidationError):
        OptimizeStructureInput(max_steps=settings.max_opt_steps + 1)


def test_optimize_steps_zero_rejected():
    with pytest.raises(ValidationError):
        OptimizeStructureInput(max_steps=0)


def test_md_steps_over_cap_rejected():
    with pytest.raises(ValidationError):
        RunMdSimulationInput(nsw=settings.max_md_steps + 1)


def test_md_steps_within_cap_accepted():
    c = RunMdSimulationInput(nsw=10)
    assert c.nsw == 10
