"""LLM provider factory for the Materia agent.

`agent/llm.py` is the single seam behind which the hosted default (Groq) and the
other backends (Gemini, local Ollama) live. The agent in `graph.py` talks only to
the abstract `LLMProvider`, so swapping backends is a config flip
(`MODEL_PROVIDER=groq|gemini|ollama`) with no code change. This replaces the old
regex `TOOL_CALL:`/JSON-from-prose path entirely (redesign §15).

On top of that, when the resolved provider has a configured fallback chain
(Groq → Gemini → Ollama), `get_provider()` returns a `FallbackProvider`: if a
backend errors at request time — quota/429, network, missing key — or returns an
empty turn, the same turn is transparently retried down the chain so a hosted
outage or rate limit degrades gracefully instead of failing the request.
"""

from __future__ import annotations

from functools import lru_cache

from app.agent.providers.base import LLMProvider, LLMResult, OnText, ToolSpec
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Primary provider → ordered fallback chain tried (in order) when it fails.
_FALLBACK_CHAIN: dict[str, list[str]] = {
    "gemini": ["groq", "ollama"],
    "groq": ["gemini", "ollama"],
}

# Text streamed before this many characters is held back so that a provider
# which dies after only a stray token (e.g. a Gemini "thinking" fragment before
# a 429) can still be cleanly replaced by the next backend without the user
# having seen anything. Healthy turns cross it almost immediately.
_COMMIT_THRESHOLD = 24


def _build_provider(name: str) -> LLMProvider:
    if name == "groq":
        from app.agent.providers.groq import GroqProvider
        return GroqProvider()
    if name == "gemini":
        from app.agent.providers.gemini import GeminiProvider
        return GeminiProvider()
    if name == "ollama":
        from app.agent.providers.ollama import OllamaProvider
        return OllamaProvider()
    raise ValueError(
        f"Unknown MODEL_PROVIDER '{name}'. Use 'groq', 'gemini' or 'ollama'.")


@lru_cache(maxsize=4)
def _cached_provider(name: str) -> LLMProvider:
    provider = _build_provider(name)
    logger.info("[Agent] LLM provider = %s", provider.name)
    return provider


class FallbackProvider(LLMProvider):
    """Run a turn on `primary`, walking `fallback_names` if it fails or comes up empty.

    A backend is replaced by the next one in the chain when it raises (quota/429,
    connection refused, missing key) or returns an empty turn (no text and no tool
    calls) — but only while nothing user-visible has streamed yet. Streamed text is
    buffered up to `_COMMIT_THRESHOLD`; once committed, switching mid-answer would
    duplicate output, so a later error is re-raised instead. Fallback providers are
    built lazily, so their dependencies (e.g. the `ollama` client) are only needed
    when actually used.
    """

    def __init__(self, primary_name: str, fallback_names: list[str]):
        self._chain = [primary_name, *fallback_names]
        self.name = "->".join(self._chain)

    async def run(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
        on_text: OnText,
    ) -> LLMResult:
        last_err: Exception | None = None

        for i, name in enumerate(self._chain):
            is_last = i == len(self._chain) - 1
            pending: list[str] = []
            committed = False

            async def buffered_on_text(delta: str) -> None:
                nonlocal committed
                if committed:
                    await on_text(delta)
                    return
                pending.append(delta)
                if sum(len(p) for p in pending) >= _COMMIT_THRESHOLD:
                    committed = True
                    for held in pending:
                        await on_text(held)
                    pending.clear()

            try:
                provider = _cached_provider(name)
                result = await provider.run(messages, tools, buffered_on_text)
            except Exception as err:  # noqa: BLE001
                last_err = err
                if committed:
                    # Real content already streamed — can't cleanly switch.
                    raise
                logger.warning(
                    "[Agent] Provider '%s' failed (%s)%s.",
                    name, err,
                    "" if is_last else f"; falling back to '{self._chain[i + 1]}'")
                continue

            # Flush any text held below the commit threshold on a clean run.
            if not committed and pending:
                for held in pending:
                    await on_text(held)

            # Empty turn (no text, no tool calls) is never useful — try the next
            # backend rather than letting the agent loop emit an empty bubble.
            if not result.text and not result.tool_calls and not committed and not is_last:
                logger.warning(
                    "[Agent] Provider '%s' returned an empty turn; "
                    "falling back to '%s'.", name, self._chain[i + 1])
                continue

            return result

        raise RuntimeError(
            "All language-model providers are currently unavailable "
            f"(last error from '{self._chain[-1]}': {last_err})."
        ) from last_err


@lru_cache(maxsize=4)
def _cached_fallback(primary_name: str, fallback_key: str) -> LLMProvider:
    return FallbackProvider(primary_name, fallback_key.split(","))


def get_provider() -> LLMProvider:
    """Return the configured LLM provider (wrapped with a fallback chain if any)."""
    name = settings.resolved_provider
    chain = [n for n in _FALLBACK_CHAIN.get(name, []) if n != name]
    if chain:
        return _cached_fallback(name, ",".join(chain))
    return _cached_provider(name)
