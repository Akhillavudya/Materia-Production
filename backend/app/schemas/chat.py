"""Request/response schemas for chat and session endpoints."""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class SessionOut(BaseModel):
    id: str
    title: str


class MessageOut(BaseModel):
    role: str
    content: str
    tool_result: str | None = None
