"""Gemini provider — native function calling over Google AI Studio (free tier).

Default hosted backend for the agent. Uses streaming `generate_content_stream`
with manual function-call handling (automatic function calling disabled), so the
agent loop in `graph.py` stays in control of tool execution and SSE emission.
"""

from __future__ import annotations

import os
import uuid

from google import genai
from google.genai import types

from app.agent.providers.base import LLMProvider, LLMResult, OnText, ToolCall, ToolSpec
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _api_key() -> str | None:
    """Resolve the Gemini key — per-user env override wins over startup config."""
    return os.getenv("GEMINI_API_KEY") or settings.gemini_api_key


def _to_contents(messages: list[dict]) -> tuple[str, list[types.Content]]:
    """Translate the neutral conversation into (system_instruction, contents)."""
    system_parts: list[str] = []
    contents: list[types.Content] = []

    for msg in messages:
        role = msg["role"]
        content = msg.get("content") or ""

        if role == "system":
            if content:
                system_parts.append(content)
            continue

        if role == "user":
            contents.append(types.Content(
                role="user", parts=[types.Part(text=content)]))
            continue

        if role == "assistant":
            parts: list[types.Part] = []
            if content:
                parts.append(types.Part(text=content))
            for tc in msg.get("tool_calls", []):
                parts.append(types.Part.from_function_call(
                    name=tc.name, args=tc.args or {}))
            if parts:
                contents.append(types.Content(role="model", parts=parts))
            continue

        if role == "tool":
            response = msg.get("content")
            if not isinstance(response, dict):
                response = {"result": response}
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=msg.get("name", "tool"), response=response)],
            ))
            continue

    return "\n\n".join(system_parts), contents


def _to_tools(tools: list[ToolSpec]) -> list[types.Tool]:
    declarations = [
        types.FunctionDeclaration(
            name=t.name,
            description=t.description,
            parameters_json_schema=t.parameters,
        )
        for t in tools
    ]
    return [types.Tool(function_declarations=declarations)]


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str | None = None):
        self.model = model or settings.gemini_model

    async def run(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        on_text: OnText,
    ) -> LLMResult:
        key = _api_key()
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add a Gemini key (free at "
                "https://aistudio.google.com/apikey) or set MODEL_PROVIDER=ollama."
            )

        client = genai.Client(api_key=key)
        system_instruction, contents = _to_contents(messages)

        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            tools=_to_tools(tools) if tools else None,
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True),
            # Disable "thinking". gemini-2.5-flash thinks by default, and with our
            # tool set present it routinely spends the whole turn thinking and
            # returns finish_reason=STOP with NO content (empty parts) — no text,
            # no function call. That made Gemini a dead fallback (always empty →
            # straight through to Ollama) and broke tool calling outright when it
            # was primary. thinking_budget=0 makes it emit the function call / text
            # directly (also lower latency). See docs/issues_solve/2026-06-25-*.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        text_acc: list[str] = []
        tool_calls: list[ToolCall] = []

        stream = await client.aio.models.generate_content_stream(
            model=self.model, contents=contents, config=config)

        async for chunk in stream:
            for cand in (chunk.candidates or []):
                if not cand.content or not cand.content.parts:
                    continue
                for part in cand.content.parts:
                    text = getattr(part, "text", None)
                    if text:
                        text_acc.append(text)
                        await on_text(text)
                    fc = getattr(part, "function_call", None)
                    if fc and fc.name:
                        tool_calls.append(ToolCall(
                            id=fc.id or uuid.uuid4().hex,
                            name=fc.name,
                            args=dict(fc.args or {}),
                        ))

        return LLMResult(text="".join(text_acc), tool_calls=tool_calls)
