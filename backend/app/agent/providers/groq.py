"""Groq provider — native function calling over Groq's free hosted tier.

Default hosted backend for the agent (redesign §15). Groq serves open models
(Llama 3.3 70B, Qwen, …) over an OpenAI-compatible chat-completions API with
native tool calling and a far more generous free tier than Gemini's. Uses
streaming with manual tool-call assembly so the agent loop in `graph.py` keeps
control of tool execution and SSE emission.
"""

from __future__ import annotations

import json
import os
import uuid

from groq import AsyncGroq

from app.agent.providers.base import LLMProvider, LLMResult, OnText, ToolCall, ToolSpec
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _to_messages(messages: list[dict]) -> list[dict]:
    """Translate the neutral conversation into OpenAI-style chat messages."""
    out: list[dict] = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content")

        if role in ("system", "user"):
            out.append({"role": role, "content": content or ""})
            continue

        if role == "assistant":
            entry: dict = {"role": "assistant", "content": content or None}
            tcs = msg.get("tool_calls", [])
            if tcs:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args or {}),
                        },
                    }
                    for tc in tcs
                ]
            out.append(entry)
            continue

        if role == "tool":
            payload = content if isinstance(content, str) else json.dumps(content)
            out.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", msg.get("name", "tool")),
                "content": payload,
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


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, model: str | None = None):
        self.model = model or settings.groq_model

    async def run(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        on_text: OnText,
    ) -> LLMResult:
        # Read os.environ FIRST so a per-request BYOK key (injected by
        # key_service.load_user_keys_into_env) is honoured; fall back to the
        # boot-time settings value. Mirrors the gemini provider.
        key = os.getenv("GROQ_API_KEY") or settings.groq_api_key
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add a Groq key (free at "
                "https://console.groq.com/keys) or set MODEL_PROVIDER=gemini|ollama."
            )

        # max_retries: the SDK retries transient 429/5xx with exponential backoff and
        # honours the server's Retry-After header, smoothing over free-tier per-minute
        # bursts before the agent falls back to the next provider.
        client = AsyncGroq(api_key=key, max_retries=3)

        text_acc: list[str] = []
        # Streamed tool calls arrive as deltas keyed by index; the name lands in
        # one chunk and the JSON arguments accumulate across several.
        tool_buf: dict[int, dict] = {}

        stream = await client.chat.completions.create(
            model=self.model,
            messages=_to_messages(messages),
            tools=_to_tools(tools) if tools else None,
            temperature=0.0,
            stream=True,
        )

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text_acc.append(delta.content)
                await on_text(delta.content)
            for tcd in (delta.tool_calls or []):
                slot = tool_buf.setdefault(
                    tcd.index, {"id": "", "name": "", "args": ""})
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function:
                    if tcd.function.name:
                        slot["name"] = tcd.function.name
                    if tcd.function.arguments:
                        slot["args"] += tcd.function.arguments

        tool_calls: list[ToolCall] = []
        for idx in sorted(tool_buf):
            slot = tool_buf[idx]
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                logger.warning(
                    "[Agent] Groq sent invalid tool args for %s: %r",
                    slot["name"], slot["args"])
                args = {}
            tool_calls.append(ToolCall(
                id=slot["id"] or uuid.uuid4().hex,
                name=slot["name"],
                args=dict(args or {}),
            ))

        return LLMResult(text="".join(text_acc), tool_calls=tool_calls)
