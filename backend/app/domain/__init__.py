"""Framework-agnostic core domain models.

These Pydantic models / enums are the cross-cutting vocabulary of the platform
(`MaterialCard`, VASP task enums, …). They depend on nothing in `app.*` so any
layer — services, tools, api — can import them without creating cycles.
"""

from app.domain.material_card import (
    Dimensionality,
    MaterialCard,
    Source,
)
from app.domain.vasp import (
    CellRelax,
    VaspInputSet,
    VaspTask,
)

__all__ = [
    "Source",
    "Dimensionality",
    "MaterialCard",
    "VaspTask",
    "CellRelax",
    "VaspInputSet",
]
