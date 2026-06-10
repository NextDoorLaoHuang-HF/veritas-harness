import json
from unittest.mock import patch, Mock

import pytest
import requests

from research.backends.protocol import BackendError, SearchResult, ScrapeResult, ResearchBackend
from research.backends.reader_selfhost import ReaderSelfhostBackend


class TestSearchResult:
    def test_fields(self):
        r = SearchResult(title="t", url="u", snippet="s", source="src", published="2026-01-01")
        assert r.title == "t"
        assert r.url == "u"
        assert r.published == "2026-01-01"

    def test_published_none(self):
        r = SearchResult(title="t", url="u", snippet="s", source="src", published=None)
        assert r.published is None


class TestScrapeResult:
    def test_fields(self):
        r = ScrapeResult(
            title="t", url="u", markdown="md", text="txt",
            page_type="article", content_quality="full", metadata={},
        )
        assert r.page_type == "article"
        assert r.content_quality == "full"


class TestBackendInterface:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ResearchBackend()


class TestReaderSelfhostBackend:
    def test_init_defaults(self):
        backend = ReaderSelfhostBackend()
        assert backend.base_url == "http://localhost:3099"
        assert backend.api_key == ""

    def test_init_custom(self):
        backend = ReaderSelfhostBackend(url="http://example.com", api_key="xyz")
        assert backend.base_url == "http://example.com"
        assert backend.api_key == "xyz"

    def test_headers(self):
        backend = ReaderSelfhostBackend(api_key="secret")
        headers = backend._headers()
        assert headers["Authorization"] == "Bearer secret"
        assert headers["Accept"] == "application/json"

    def test_headers_no_key(self):
        backend = ReaderSelfhostBackend(api_key="")
        headers = backend._headers()
        assert "Authorization" not in headers

    def test_build_search_url_no_site(self):
        backend = ReaderSelfhostBackend()
        url = backend._build_search_url("hello world", count=5)
        assert "q=hello+world" in url
        assert "count=5" in url
        assert "format=json" in url

    def test_build_search_url_with_site(self):
        backend = ReaderSelfhostBackend()
        url = backend._build_search_url("hello", count=10, site="example.com")
        assert "site=example.com" in url

    def test_parse_search_result(self):
        backend = ReaderSelfhostBackend()
        raw = {
            "title": "Hello World",
            "url": "https://example.com/page",
            "snippet": "A snippet",
            "source": "example.com",
            "published": "2026-05-01",
        }
        result = backend._parse_search_result(raw)
        assert result.title == "Hello World"
        assert result.url == "https://example.com/page"
        assert result.source == "example.com"

    def test_parse_search_result_missing_published(self):
        backend = ReaderSelfhostBackend()
        raw = {"title": "t", "url": "u", "snippet": "s", "source": "src"}
        result = backend._parse_search_result(raw)
        assert result.published is None

    def test_health_url(self):
        backend = ReaderSelfhostBackend()
        assert backend._health_url() == "http://localhost:3099/health"


class TestBackendError:
    def test_is_exception(self):
        assert issubclass(BackendError, Exception)

    def test_can_raise_with_message(self):
        with pytest.raises(BackendError, match="backend error"):
            raise BackendError("backend error")


class TestReaderSelfhostSearchMocked:
    def test_search_success(self):
        mock_resp = Mock(spec=requests.Response)
        mock_resp.json.return_value = {
            "results": [
                {"title": "R1", "url": "https://a.com", "snippet": "s1", "source": "a.com", "published": "2026-01-01"},
                {"title": "R2", "url": "https://b.com", "snippet": "s2", "source": "b.com"},
            ]
        }
        with patch("research.backends.reader_selfhost.requests.request", return_value=mock_resp):
            backend = ReaderSelfhostBackend()
            results = backend.search("test")
            assert len(results) == 2
            assert results[0].title == "R1"
            assert results[1].title == "R2"

    def test_search_empty_results(self):
        mock_resp = Mock(spec=requests.Response)
        mock_resp.json.return_value = {}
        with patch("research.backends.reader_selfhost.requests.request", return_value=mock_resp):
            backend = ReaderSelfhostBackend()
            results = backend.search("test")
            assert results == []

    def test_search_connection_error(self):
        with patch("research.backends.reader_selfhost.requests.request",
                   side_effect=requests.exceptions.ConnectionError):
            backend = ReaderSelfhostBackend()
            with pytest.raises(BackendError, match="Connection failed"):
                backend.search("test")

    def test_search_timeout(self):
        with patch("research.backends.reader_selfhost.requests.request",
                   side_effect=requests.exceptions.Timeout):
            backend = ReaderSelfhostBackend()
            with pytest.raises(BackendError, match="timed out"):
                backend.search("test")

    def test_search_http_error(self):
        mock_resp = Mock(spec=requests.Response)
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_resp)
        with patch("research.backends.reader_selfhost.requests.request", return_value=mock_resp):
            backend = ReaderSelfhostBackend()
            with pytest.raises(BackendError, match="HTTP 500"):
                backend.search("test")

    def test_search_invalid_json(self):
        mock_resp = Mock(spec=requests.Response)
        mock_resp.json.side_effect = json.JSONDecodeError("bad json", "", 0)
        with patch("research.backends.reader_selfhost.requests.request", return_value=mock_resp):
            backend = ReaderSelfhostBackend()
            with pytest.raises(BackendError, match="Invalid JSON"):
                backend.search("test")


class TestReaderSelfhostScrapeMocked:
    def test_scrape_success(self):
        mock_resp = Mock(spec=requests.Response)
        mock_resp.json.return_value = {
            "title": "Article",
            "url": "https://example.com/article",
            "markdown": "# Content",
            "text": "Content",
            "pageType": "article",
            "contentQuality": "full",
            "metadata": {"key": "val"},
        }
        with patch("research.backends.reader_selfhost.requests.request", return_value=mock_resp):
            backend = ReaderSelfhostBackend()
            result = backend.scrape("https://example.com/article")
            assert result.title == "Article"
            assert result.page_type == "article"
            assert result.metadata == {"key": "val"}

    def test_scrape_fallback_url(self):
        mock_resp = Mock(spec=requests.Response)
        mock_resp.json.return_value = {
            "title": "A", "markdown": "md", "text": "t", "pageType": "article",
            "contentQuality": "full", "metadata": {},
        }
        with patch("research.backends.reader_selfhost.requests.request", return_value=mock_resp):
            backend = ReaderSelfhostBackend()
            result = backend.scrape("https://example.com/orig")
            assert result.url == "https://example.com/orig"

    def test_scrape_browser_header(self):
        mock_resp = Mock(spec=requests.Response)
        mock_resp.json.return_value = {"title": "A", "markdown": "md", "text": "t",
                                       "pageType": "article", "contentQuality": "full", "metadata": {}}
        with patch("research.backends.reader_selfhost.requests.request", return_value=mock_resp) as mocked:
            backend = ReaderSelfhostBackend()
            backend.scrape("https://example.com", browser=True)
            call_headers = mocked.call_args[1]["headers"]
            assert call_headers.get("x-engine") == "browser"


class TestReaderSelfhostHealthMocked:
    def test_health_success(self):
        mock_resp = Mock(spec=requests.Response)
        mock_resp.json.return_value = {"status": "ok"}
        with patch("research.backends.reader_selfhost.requests.request", return_value=mock_resp):
            backend = ReaderSelfhostBackend()
            result = backend.health()
            assert result == {"status": "ok"}

    def test_health_connection_error(self):
        with patch("research.backends.reader_selfhost.requests.request",
                   side_effect=requests.exceptions.ConnectionError):
            backend = ReaderSelfhostBackend()
            with pytest.raises(BackendError):
                backend.health()
