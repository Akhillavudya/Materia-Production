"""Request/response schemas for the API-key manager."""

from pydantic import BaseModel


class ApiKeyIn(BaseModel):
    service: str    # "mp", "openai", "anthropic", ...
    key_value: str


class ApiKeyOut(BaseModel):
    service: str
    exists: bool    # never echo the actual key back to the frontend
