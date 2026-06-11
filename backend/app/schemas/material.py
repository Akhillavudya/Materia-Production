"""HTTP request/response DTOs for material search and file operations.

Absorbs the request models that used to live in `tools/schemas.py`. The unified
`MaterialCard` itself lives in `app.domain.material_card`.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class MaterialSearchRequest(BaseModel):
    formula:         Optional[str]   = None
    element:         Optional[str]   = None
    elements:        Optional[str]   = None
    min_gap:         Optional[float] = None
    max_gap:         Optional[float] = None
    max_formation_e: Optional[float] = None
    dimensionality:  Optional[str]   = None
    limit:           int             = Field(default=10, ge=1, le=50)


class MaterialSearchResponse(BaseModel):
    status:         str
    source_used:    Optional[str] = None
    sources_tried:  List[str]     = []
    materials:      List[dict]    = []
    total_matching: int           = 0
    returned:       int           = 0
    message:        str           = ""


class RenameRequest(BaseModel):
    new_name: str
