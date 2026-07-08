"""Shared multi-key rotation for the hosted Gemini provider.

Gemini's free tier is quota-capped per key (requests/day). An operator can supply
several free keys via ``GEMINI_API_KEYS`` (comma-separated) to multiply the daily
budget. Instead of falling straight through to the next *provider* (Ollama) on a
429, the provider first rotates to the next *key* in its own pool. Only when every
key is exhausted does the request drop to the next provider (see ``agent/llm.py``).

This is the real resilience layer on web, where Gemini is the sole provider (there
is no Ollama server on the hosted deployment).

A per-pool round-robin cursor remembers the last good key, so an exhausted key is
not retried first on every subsequent request.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable

from app.agent.providers.base import LLMResult, OnText
from app.core.logging import get_logger

logger = get_logger(__name__)

# pool name → index of the last key that worked (round-robin start point).
_cursors: dict[str, int] = {}
_lock = threading.Lock()


def build_pool(singular: str | None, plural: str | None) -> list[str]:
    """Ordered, de-duplicated key pool from a singular + a plural env value.

    ``singular`` (the key a per-request BYOK override writes to) is placed first
    so a user's own key is always tried before the operator's shared pool.
    ``plural`` is a comma-separated list; blanks are ignored.
    """
    ordered: list[str] = []
    if singular and singular.strip():
        ordered.append(singular.strip())
    for k in (plural or "").split(","):
        k = k.strip()
        if k:
            ordered.append(k)
    seen: set[str] = set()
    pool: list[str] = []
    for k in ordered:
        if k not in seen:
            seen.add(k)
            pool.append(k)
    return pool


def _ordered_from_cursor(pool_name: str, pool: list[str]) -> list[str]:
    """Rotate the pool so it starts at the last-known-good key."""
    with _lock:
        start = _cursors.get(pool_name, 0) % len(pool)
    return pool[start:] + pool[:start]


def _remember(pool_name: str, key: str, pool: list[str]) -> None:
    with _lock:
        try:
            _cursors[pool_name] = pool.index(key)
        except ValueError:
            pass


def should_rotate(err: Exception) -> bool:
    """True when trying a *different* key might succeed — i.e. the current key is
    rate-limited (429/quota) or dead (invalid/expired/unauthorised). A genuine
    bad request (schema/400) fails on every key, so it is NOT rotated."""
    s = f"{type(err).__name__} {err}".lower()
    return any(t in s for t in (
        # quota / rate limit
        "ratelimit", "rate limit", "rate_limit", "429",
        "resource_exhausted", "quota", "too many requests",
        # dead / invalid key — skip it and try the next
        "api key not valid", "api_key_invalid", "invalid api key",
        "invalid_api_key", "unauthenticated", "permission_denied",
        "401", "403",
    ))


async def run_with_rotation(
    pool_name: str,
    pool: list[str],
    on_text: OnText,
    attempt: Callable[[str, OnText], Awaitable[LLMResult]],
) -> LLMResult:
    """Run ``attempt(key, on_text)`` against each key, rotating past 429s.

    Rotation only happens *before any text has streamed* on an attempt — once a
    key has emitted user-visible tokens, switching would duplicate output, so a
    later error is re-raised for the outer provider-fallback to handle. Non
    rate-limit errors are re-raised immediately (rotating keys won't fix a bad
    request or a missing-key config). When the pool holds a single key this is a
    thin pass-through with identical behaviour to before.
    """
    ordered = _ordered_from_cursor(pool_name, pool)
    last_err: Exception | None = None

    for i, key in enumerate(ordered):
        is_last = i == len(ordered) - 1
        emitted = {"v": False}

        async def guarded(delta: str, _e=emitted) -> None:
            _e["v"] = True
            await on_text(delta)

        try:
            result = await attempt(key, guarded)
        except Exception as err:  # noqa: BLE001 — classify then rotate or re-raise
            last_err = err
            if not emitted["v"] and not is_last and should_rotate(err):
                logger.warning(
                    "[Agent] %s key %d/%d unavailable (%s); rotating to next key.",
                    pool_name, i + 1, len(ordered), type(err).__name__)
                continue
            raise
        _remember(pool_name, key, pool)
        return result

    # Unreachable when pool is non-empty (the last key re-raises), but keeps the
    # type-checker happy and guards an empty pool.
    raise last_err or RuntimeError(f"No API keys available for '{pool_name}'.")
