"""Provider-neutral LLM interface for the Materia agent (redesign §15).

The agent drives a native function-calling loop over an abstract `LLMProvider`,
so the hosted default (Gemini) and the offline fallback (Ollama) are drop-in
interchangeable. There is **no** regex/JSON-from-prose extraction anywhere —
tool calls come back as structured data from the model.

Neutral conversation format (a list of plain dicts):

    {"role": "system",    "content": str}                       # first only
    {"role": "user",      "content": str}
    {"role": "assistant", "content": str}                       # plain answer
    {"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}
    {"role": "tool",      "tool_call_id": str, "name": str, "content": <json>}

Each provider translates this neutral form into its own wire format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolCall:
    """A single tool/function call requested by the model."""
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResult:
    """One assistant turn: any streamed text plus any requested tool calls."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ToolSpec:
    """Provider-neutral declaration of a callable tool."""
    name: str
    description: str
    parameters: dict[str, Any]   # JSON Schema for the arguments object


# Callback the providers invoke with each streamed text delta.
OnText = Callable[[str], Awaitable[None]]


class LLMProvider(ABC):
    """A chat model that supports native tool/function calling + streaming."""

    name: str = "base"

    @abstractmethod
    async def run(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        on_text: OnText,
    ) -> LLMResult:
        """Run one assistant turn.

        Streams any natural-language text through ``on_text`` as it arrives and
        returns the aggregated text together with any tool calls the model made.
        The caller executes the tools, appends ``role:"tool"`` results to
        ``messages``, and calls ``run`` again until no tool calls remain.
        """
        raise NotImplementedError
