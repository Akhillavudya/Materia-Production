"""Ollama provider — native tool calling for offline/local development.

Fallback backend (e.g. `qwen3`, which supports native tools). Same neutral
interface as the Gemini provider; no regex/JSON-from-prose extraction.
"""

from __future__ import annotations

import json
import uuid

from ollama import AsyncClient

from app.agent.providers.base import LLMProvider, LLMResult, OnText, ToolCall, ToolSpec
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _to_messages(messages: list[dict]) -> list[dict]:
    """Translate the neutral conversation into Ollama chat messages."""
    out: list[dict] = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content")

        if role in ("system", "user"):
            out.append({"role": role, "content": content or ""})
            continue

        if role == "assistant":
            entry: dict = {"role": "assistant", "content": content or ""}
            tcs = msg.get("tool_calls", [])
            if tcs:
                entry["tool_calls"] = [
                    {"function": {"name": tc.name, "arguments": tc.args or {}}}
                    for tc in tcs
                ]
            out.append(entry)
            continue

        if role == "tool":
            payload = content if isinstance(content, str) else json.dumps(content)
            out.append({
                "role": "tool",
                "content": payload,
                "tool_name": msg.get("name", "tool"),
            })
            continue

    return out


def _to_tools(tools: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or settings.ollama_model
        self.host = host or settings.ollama_base_url

    async def run(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        on_text: OnText,
    ) -> LLMResult:
        client = AsyncClient(host=self.host)

        text_acc: list[str] = []
        tool_calls: list[ToolCall] = []

        async for chunk in await client.chat(
            model=self.model,
            messages=_to_messages(messages),
            tools=_to_tools(tools) if tools else None,
            stream=True,
        ):
            message = chunk.get("message") if isinstance(chunk, dict) else chunk.message
            if message is None:
                continue

            token = (message.get("content") if isinstance(message, dict)
                     else message.content) or ""
            if token:
                text_acc.append(token)
                await on_text(token)

            tcs = (message.get("tool_calls") if isinstance(message, dict)
                   else getattr(message, "tool_calls", None)) or []
            for tc in tcs:
                fn = tc["function"] if isinstance(tc, dict) else tc.function
                name = fn["name"] if isinstance(fn, dict) else fn.name
                args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    id=uuid.uuid4().hex, name=name, args=dict(args or {})))

        return LLMResult(text="".join(text_acc), tool_calls=tool_calls)
