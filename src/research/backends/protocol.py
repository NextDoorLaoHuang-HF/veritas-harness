from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str
    published: str | None = None


@dataclass
class ScrapeResult:
    title: str
    url: str
    markdown: str
    text: str
    page_type: str
    content_quality: str
    metadata: dict = field(default_factory=dict)


class BackendError(Exception):
    pass


class ResearchBackend(ABC):
    @abstractmethod
    def search(self, query: str, count: int = 10, **kwargs) -> list[SearchResult]:
        ...

    @abstractmethod
    def scrape(self, url: str, **kwargs) -> ScrapeResult:
        ...

    @abstractmethod
    def health(self) -> dict:
        ...
