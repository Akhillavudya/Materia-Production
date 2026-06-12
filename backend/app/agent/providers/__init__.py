"""LLM provider adapters for the agent's native function-calling loop."""

from app.agent.providers.base import LLMProvider, LLMResult, OnText, ToolCall, ToolSpec

__all__ = ["LLMProvider", "LLMResult", "OnText", "ToolCall", "ToolSpec"]
