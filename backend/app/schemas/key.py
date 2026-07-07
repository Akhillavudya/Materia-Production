"""Request/response schemas for the API-key manager."""

from pydantic import BaseModel


class ApiKeyIn(BaseModel):
    service: str    # "mp", "openai", "anthropic", ...
    key_value: str


class KeyHint(BaseModel):
    index: int      # position in the user's pool (used to delete one key)
    hint: str       # masked tail, e.g. "••••ab12" — never the real key


class ApiKeyOut(BaseModel):
    service: str
    exists: bool                 # true when the user has ≥1 key for the service
    count: int = 0               # how many keys are pooled for rotation
    keys: list[KeyHint] = []     # masked hints, one per stored key
