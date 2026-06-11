"""C2DB provider — local ASE `.db` of 2D materials (~17k), no network."""

from __future__ import annotations

import os

from app.core.logging import get_logger
from app.domain.material_card import MaterialCard, Source
from app.services.search.base import MaterialQuery
from app.services.search.mappers import c2db_row_to_card

logger = get_logger(__name__)

C2DB_DB = os.environ.get("C2DB_DB", "/data/c2db/c2db.db")


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

            if query.element and query.element not in formula_db:
                continue
            if query.elements and not all(e in formula_db for e in query.elements):
                continue

            gap = kv.get("gap")
            if query.max_gap is not None and (gap is None or gap > query.max_gap):
                continue
            if query.min_gap is not None and (gap is None or gap < query.min_gap):
                continue

            cards.append(c2db_row_to_card(row))
            if len(cards) >= query.limit:
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
