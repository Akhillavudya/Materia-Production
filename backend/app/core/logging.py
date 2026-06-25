"""Application logging configuration.

Provides a single `configure_logging()` entry point (called once at startup)
and a `get_logger()` helper so modules stop using bare `print()` for diagnostics.

Every log line carries a **request id** (Step 6): the request-context middleware
stamps a short id onto each incoming HTTP request and stores it in a
`ContextVar`. The `_RequestIdFilter` copies that id onto every log record so a
crash deep in the agent can be traced back to the exact request that caused it —
the user only ever sees the id, never the stack trace.
"""

import logging
import os
import uuid
from contextvars import ContextVar

_CONFIGURED = False

# Per-request correlation id. Defaults to "-" outside of any request (startup,
# the Celery worker, ad-hoc scripts) so log lines are always well-formed.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    """Generate a short, human-readable request id (first 8 hex of a uuid4)."""
    return uuid.uuid4().hex[:8]


def set_request_id(request_id: str) -> None:
    """Bind `request_id` to the current context (called by the middleware)."""
    _request_id.set(request_id)


def get_request_id() -> str:
    """Return the request id bound to the current context (or '-')."""
    return _request_id.get()


class _RequestIdFilter(logging.Filter):
    """Inject the current request id onto every record as `record.request_id`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


def configure_logging() -> None:
    """Initialise root logging once, honouring the LOG_LEVEL env var."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(request_id)s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, ensuring logging is configured first."""
    configure_logging()
    return logging.getLogger(name)
