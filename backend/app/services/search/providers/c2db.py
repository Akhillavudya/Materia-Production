"""C2DB provider — local ASE `.db` of 2D materials (~17k), no network."""

from __future__ import annotations

import os

from app.core.logging import get_logger
from app.domain.material_card import MaterialCard, Source
from app.services.search.base import MaterialQuery
from app.services.search.mappers import c2db_row_to_card

logger = get_logger(__name__)

C2DB_DB = os.environ.get("C2DB_DB", "/data/c2db/c2db.db")


def _formula_elements(formula: str) -> set[str]:
    """Element symbols present in a formula string (e.g. 'MoS2' → {'Mo', 'S'}).

    Uses pymatgen Composition for correctness, with a regex fallback so a single
    odd formula never breaks the whole search.
    """
    try:
        from pymatgen.core import Composition
        return {el.symbol for el in Composition(formula).elements}
    except Exception:  # noqa: BLE001
        import re
        return set(re.findall(r"[A-Z][a-z]?", formula or ""))


class C2DBProvider:
    source = Source.C2DB

    def is_available(self) -> bool:
        return os.path.exists(C2DB_DB)

    def search(self, query: MaterialQuery) -> list[MaterialCard]:
        from ase.db import connect

        db = connect(C2DB_DB)
        rows = db.select(formula=query.formula) if query.formula else db.select()

        cards: list[MaterialCard] = []
        for row in rows:
            kv = row.key_value_pairs or {}
            formula_db = row.formula

            # Element membership must be by actual chemical element, NOT substring —
            # a substring test wrongly matches "S" inside "Se" (or "Sc" inside a
            # formula that only contains Se). Parse the formula into element symbols.
            elem_set = _formula_elements(formula_db)
            if query.element and query.element not in elem_set:
                continue
            if query.elements and not all(e in elem_set for e in query.elements):
                continue

            gap = kv.get("gap")
            if query.max_gap is not None and (gap is None or gap > query.max_gap):
                continue
            if query.min_gap is not None and (gap is None or gap < query.min_gap):
                continue

            cards.append(c2db_row_to_card(row))
            if len(cards) >= 200:   # full set (capped); tool slices for display (S1)
                break

        return cards

    def get_structure(self, source_id: str):
        try:
            from ase.db import connect
            from pymatgen.io.ase import AseAtomsAdaptor

            db_id = int(str(source_id).replace("c2db-", "").replace("c2db:", ""))
            db = connect(C2DB_DB)
            row = db.get(id=db_id)
            if row is None:
                return None
            return AseAtomsAdaptor.get_structure(row.toatoms())
        except Exception as e:
            logger.warning("C2DB structure retrieval error: %s", e)
            return None
