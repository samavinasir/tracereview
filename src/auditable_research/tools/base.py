from abc import ABC, abstractmethod

from ..models import SearchQuery, SourceRecord


class ResearchTool(ABC):
    name: str

    @abstractmethod
    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        """Search a research provider and return normalized records."""

    async def fetch_full_text(self, source: SourceRecord) -> SourceRecord:
        """Optionally attach licensed, provider-accessible full-text sections."""
        return source
