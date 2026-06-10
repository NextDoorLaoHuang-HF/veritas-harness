import json

import requests
from urllib.parse import urlencode
from research.backends.protocol import BackendError, ResearchBackend, SearchResult, ScrapeResult


class ReaderSelfhostBackend(ResearchBackend):
    def __init__(self, url: str = "http://localhost:3099", api_key: str = "", timeout: int = 30):
        self.base_url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_search_url(self, query: str, count: int = 10, **kwargs) -> str:
        params = {"q": query, "count": count, "format": "json"}
        if "site" in kwargs and kwargs["site"]:
            params["site"] = kwargs["site"]
        return f"{self.base_url}/search?{urlencode(params)}"

    def _parse_search_result(self, raw: dict) -> SearchResult:
        return SearchResult(
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            snippet=raw.get("snippet", ""),
            source=raw.get("source", ""),
            published=raw.get("published"),
        )

    def _health_url(self) -> str:
        return f"{self.base_url}/health"

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = self._headers()
        extra_headers = kwargs.pop("headers", {})
        headers.update(extra_headers)
        try:
            resp = requests.request(method, url, headers=headers,
                                    timeout=kwargs.get("timeout", self.timeout))
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout as e:
            raise BackendError(f"Request timed out: {url}") from e
        except requests.exceptions.ConnectionError as e:
            raise BackendError(f"Connection failed: {url}") from e
        except requests.exceptions.HTTPError as e:
            raise BackendError(f"HTTP {resp.status_code}: {url}") from e
        except requests.exceptions.RequestException as e:
            raise BackendError(f"Request failed: {url}") from e

    def search(self, query: str, count: int = 10, **kwargs) -> list[SearchResult]:
        url = self._build_search_url(query, count, **kwargs)
        resp = self._request("GET", url)
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise BackendError(f"Invalid JSON response from {url}") from e
        raw_results = data.get("results", data.get("data", []))
        if isinstance(raw_results, list):
            return [self._parse_search_result(r) for r in raw_results]
        return []

    def scrape(self, url: str, **kwargs) -> ScrapeResult:
        params = {"url": url, "format": kwargs.get("format", "markdown")}
        headers = self._headers()
        if kwargs.get("browser"):
            headers["x-engine"] = "browser"
        if kwargs.get("wait_for"):
            headers["x-wait-for"] = str(kwargs["wait_for"])
        full_url = f"{self.base_url}/read?{urlencode(params)}"
        timeout = kwargs.get("timeout", self.timeout)
        resp = self._request("GET", full_url, timeout=timeout, headers=headers)
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise BackendError(f"Invalid JSON response from {full_url}") from e
        final_url = data.get("url") or data.get("finalUrl") or url
        return ScrapeResult(
            title=data.get("title", ""),
            url=final_url,
            markdown=data.get("markdown", ""),
            text=data.get("text", ""),
            page_type=data.get("pageType", data.get("page_type", "unknown")),
            content_quality=data.get("contentQuality", data.get("content_quality", "unknown")),
            metadata=data.get("metadata", {}),
        )

    def health(self) -> dict:
        resp = self._request("GET", self._health_url())
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise BackendError(f"Invalid JSON response from health endpoint") from e
