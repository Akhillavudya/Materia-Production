"""Search provider interface (redesign §8).

Every material source implements `MaterialProvider`; `SearchService` composes
them by priority and normalises every result to a `MaterialCard`.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.domain.material_card import MaterialCard, Source


class MaterialQuery(BaseModel):
    """Normalised search query passed to every provider."""

    formula: Optional[str] = None
    element: Optional[str] = None
    elements: list[str] = Field(default_factory=list)
    min_gap: Optional[float] = None
    max_gap: Optional[float] = None
    max_formation_e: Optional[float] = None
    dimensionality: Optional[str] = None      # "2D" | "3D"
    limit: int = 10


@runtime_checkable
class MaterialProvider(Protocol):
    """One material database behind a uniform interface."""

    source: Source

    def is_available(self) -> bool:
        """Key present / db file exists / endpoint reachable."""
        ...

    def search(self, query: MaterialQuery) -> list[MaterialCard]:
        """Return matching materials as `MaterialCard`s (may be empty)."""
        ...

    def get_structure(self, source_id: str):
        """Return a pymatgen `Structure` for a native id, or None."""
        ...
