"""Response schema for file uploads."""

from pydantic import BaseModel


class UploadedFileOut(BaseModel):
    name: str
    size_kb: float
    rel_path: str
    group_name: str = "uploads"
