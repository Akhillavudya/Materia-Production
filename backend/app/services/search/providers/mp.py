"""Materials Project provider — bulk/3D, live REST API (requires a user key).

The key is injected into ``os.environ["MP_API_KEY"]`` per request by
`services.key_service`.
"""

from __future__ import annotations

import os

from app.core.logging import get_logger
from app.domain.material_card import MaterialCard, Source
from app.services.search.base import MaterialQuery
from app.services.search.mappers import mp_doc_to_card

logger = get_logger(__name__)


class MPProvider:
    source = Source.MP

    def is_available(self) -> bool:
        return bool(os.environ.get("MP_API_KEY", ""))

    def search(self, query: MaterialQuery) -> list[MaterialCard]:
        api_key = os.environ.get("MP_API_KEY", "")
        if not api_key:
            return []

        from mp_api.client import MPRester

        kwargs: dict = {}
        if query.formula:
            kwargs["formula"] = query.formula
        if query.elements:
            kwargs["elements"] = list(query.elements)
        elif query.element:
            kwargs["elements"] = [query.element]
        if query.max_gap is not None or query.min_gap is not None:
            kwargs["band_gap"] = (
                query.min_gap if query.min_gap is not None else 0.0,
                query.max_gap if query.max_gap is not None else 100.0,
            )

        fields = [
            "material_id", "formula_pretty", "band_gap",
            "formation_energy_per_atom", "energy_per_atom",
            "symmetry", "energy_above_hull", "elements",
        ]

        with MPRester(api_key=api_key, mute_progress_bars=True) as mpr:
            docs = mpr.materials.summary.search(**kwargs, fields=fields)

        if not docs:
            return []

        docs_sorted = sorted(docs, key=lambda d: d.energy_above_hull or 999)
        return [mp_doc_to_card(d) for d in docs_sorted[: query.limit]]

    def get_structure(self, source_id: str):
        key = os.environ.get("MP_API_KEY", "")
        if not key:
            return None
        try:
            from mp_api.client import MPRester
            with MPRester(api_key=key, mute_progress_bars=True) as mpr:
                return mpr.get_structure_by_material_id(
                    source_id, conventional_unit_cell=True
                )
        except Exception as e:
            logger.warning("MP get_structure error for %s: %s", source_id, e)
            return None
