"""Search orchestration (redesign §8).

Composes the providers by priority (MP → C2DB → OQMD), normalises everything to
`MaterialCard`, and routes structure re-fetches by the card's id prefix. Default
behaviour is *first-hit wins* — the first provider that returns results stops the
chain. Provider failures are isolated: one source erroring never aborts the chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.domain.material_card import MaterialCard, Source
from app.services.search.base import MaterialProvider, MaterialQuery
from app.services.search.providers.c2db import C2DBProvider
from app.services.search.providers.mp import MPProvider
from app.services.search.providers.oqmd import OQMDProvider

logger = get_logger(__name__)

# Priority order from the spec (bulk/3D first).
_DEFAULT_ORDER: list[Source] = [Source.MP, Source.C2DB, Source.OQMD]

# For 2D queries, C2DB (a dedicated 2D-materials db) is the authoritative source,
# so try it first — otherwise MP's bulk hit for the same formula shadows it.
_2D_ORDER: list[Source] = [Source.C2DB, Source.MP, Source.OQMD]


def _is_2d(dimensionality: str | None) -> bool:
    """True when the query explicitly asks for a 2D material ("2D"/"2d"/"2")."""
    if not dimensionality:
        return False
    return dimensionality.strip().lower().rstrip("d") == "2"


@dataclass
class SearchResult:
    cards: list[MaterialCard] = field(default_factory=list)
    source_used: Source | None = None
    sources_tried: list[Source] = field(default_factory=list)


class SearchService:
    def __init__(self, providers: list[MaterialProvider] | None = None):
        if providers is None:
            providers = [MPProvider(), C2DBProvider(), OQMDProvider()]
        self._by_source = {p.source: p for p in providers}

    # ── search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: MaterialQuery,
        order: list[Source] | None = None,
    ) -> SearchResult:
        """First-hit-wins search across providers in priority order.

        An explicit `order` always wins; otherwise a 2D query prefers C2DB and
        every other query uses the default bulk-first order.
        """
        if order is None:
            order = _2D_ORDER if _is_2d(query.dimensionality) else _DEFAULT_ORDER
        result = SearchResult()
        for source in order:
            provider = self._by_source.get(source)
            if provider is None:
                continue
            result.sources_tried.append(source)

            if not provider.is_available():
                logger.info("Search: %s unavailable, skipping", source.value)
                continue

            try:
                cards = provider.search(query)
            except Exception as e:
                logger.warning("Search: %s errored: %s", source.value, e)
                continue

            if cards:
                logger.info("Search: %d hit(s) in %s", len(cards), source.value)
                result.cards = cards
                result.source_used = source
                return result

        return result

    # ── structure re-fetch (routed by id prefix) ──────────────────────────────

    def get_structure(self, material_id: str, source: str | None = None):
        """Return a pymatgen Structure for a canonical/native id, or None.

        Routes by the id prefix (``mp-`` / ``c2db-`` / ``oqmd-``); an explicit
        `source` overrides the prefix when provided.
        """
        src = self._resolve_source(material_id, source)
        if src is None:
            logger.warning("Search: cannot route id %r to a provider", material_id)
            return None
        provider = self._by_source.get(src)
        if provider is None:
            return None
        # MP refetches by the full "mp-…" id; the others strip their prefix
        # inside their own get_structure.
        return provider.get_structure(material_id)

    @staticmethod
    def _resolve_source(material_id: str, source: str | None) -> Source | None:
        if source:
            try:
                return Source(source.lower().strip())
            except ValueError:
                pass
        mid = str(material_id).lower()
        if mid.startswith("mp-") or mid.startswith("mp:"):
            return Source.MP
        if mid.startswith("c2db-") or mid.startswith("c2db:"):
            return Source.C2DB
        if mid.startswith("oqmd-") or mid.startswith("oqmd:"):
            return Source.OQMD
        return None


# Module-level singleton — providers are cheap/stateless.
search_service = SearchService()
