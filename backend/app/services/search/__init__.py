"""Provider-based material search layer."""

from app.services.search.base import MaterialProvider, MaterialQuery
from app.services.search.service import SearchResult, SearchService, search_service

__all__ = [
    "MaterialProvider",
    "MaterialQuery",
    "SearchService",
    "SearchResult",
    "search_service",
]
