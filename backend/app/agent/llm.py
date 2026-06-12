"""LLM provider factory for the Materia agent.

`agent/llm.py` is the single seam behind which the hosted default (Gemini) and
the offline fallback (Ollama) live. The agent in `graph.py` talks only to the
abstract `LLMProvider`, so swapping backends is a config flip
(`MODEL_PROVIDER=gemini|ollama`) with no code change. This replaces the old
regex `TOOL_CALL:`/JSON-from-prose path entirely (redesign §15).
"""

from __future__ import annotations

from functools import lru_cache

from app.agent.providers.base import LLMProvider
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _build_provider(name: str) -> LLMProvider:
    if name == "gemini":
        from app.agent.providers.gemini import GeminiProvider
        return GeminiProvider()
    if name == "ollama":
        from app.agent.providers.ollama import OllamaProvider
        return OllamaProvider()
    raise ValueError(
        f"Unknown MODEL_PROVIDER '{name}'. Use 'gemini' or 'ollama'.")


@lru_cache(maxsize=4)
def _cached_provider(name: str) -> LLMProvider:
    provider = _build_provider(name)
    logger.info("[Agent] LLM provider = %s", provider.name)
    return provider


def get_provider() -> LLMProvider:
    """Return the configured LLM provider (cached per resolved provider name)."""
    return _cached_provider(settings.resolved_provider)
