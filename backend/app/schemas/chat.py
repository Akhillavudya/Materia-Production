"""Request/response schemas for chat and session endpoints."""

from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = ""
    # When present, this is the EXECUTE phase: the user confirmed a previously
    # proposed multi-tool plan, so run it instead of planning again. Shape:
    # {"summary": str, "steps": [{"tool", "title", "detail"}], "final_output": str}
    plan: dict[str, Any] | None = None


class SessionOut(BaseModel):
    id: str
    title: str


class MessageOut(BaseModel):
    role: str
    content: str
    tool_result: str | None = None
