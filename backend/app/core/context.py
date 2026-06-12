"""Request-scoped identity for tool execution.

Agent tools run in a worker thread with no FastAPI request available, but the two
long tools need the owning ``user_id`` / ``session_id`` to create a job row. The
graph sets these ContextVars before invoking a tool (the same pattern as the
session-dir var in `file_service`).
"""

from contextvars import ContextVar

_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)
_current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)


def set_request_identity(user_id: int | None, session_id: str | None) -> None:
    _current_user_id.set(user_id)
    _current_session_id.set(session_id)


def get_user_id() -> int | None:
    return _current_user_id.get()


def get_session_id() -> str | None:
    return _current_session_id.get()
