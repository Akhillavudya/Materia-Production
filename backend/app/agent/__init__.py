"""LangGraph-based planning/execution agent for Materia.

Public entry point:
    from app.agent import run_agent
"""

from app.agent.graph import run_agent

__all__ = ["run_agent"]
