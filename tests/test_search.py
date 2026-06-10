import json
import pytest
from pathlib import Path
from research.search import build_run_dir, dedup_results, run_search


class TestBuildRunDir:
    def test_custom_path(self):
        assert build_run_dir("/custom/path") == Path("/custom/path")

    def test_auto_generate(self, tmp_path, monkeypatch):
        monkeypatch.setattr("research.search.RUN_DIR_BASE", str(tmp_path / ".research/runs"))
        result = build_run_dir(None, "my topic")
        assert result.parent == tmp_path / ".research/runs"


class TestDedupResults:
    def test_removes_duplicates(self):
        from research.backends.protocol import SearchResult
        results = [
            SearchResult(title="a", url="https://x.com/a", snippet="s1", source="x.com"),
            SearchResult(title="b", url="https://x.com/b", snippet="s2", source="x.com"),
            SearchResult(title="a dup", url="https://x.com/a", snippet="s3", source="x.com"),
        ]
        deduped = dedup_results(results)
        assert len(deduped) == 2
        assert deduped[0].url == "https://x.com/a"

    def test_empty_list(self):
        assert dedup_results([]) == []

    def test_single_result(self):
        from research.backends.protocol import SearchResult
        r = SearchResult(title="t", url="https://x.com", snippet="s", source="x.com")
        assert dedup_results([r]) == [r]


class TestRunSearchCli:
    def test_run_search_no_scrape(self, tmp_path, monkeypatch):
        class FakeArgs:
            query = ["test query"]
            run_dir = str(tmp_path / "runs" / "test")
            limit = 10
            scrape = False
            json = False
            output = None
            opencli_sites = None
            opencli_public_only = False
            opencli_timeout = 30
            backend = "opencli"
            legal_type = None

        monkeypatch.setattr("research.backends.opencli.OpenCLIBackend", _make_mock_backend)
        result = run_search(FakeArgs())
        assert result["count"] > 0
        assert "results" in result
        assert "query" in result

    def test_run_search_json_output(self, tmp_path, monkeypatch, capsys):
        out_path = tmp_path / "out.json"
        class FakeArgs:
            query = ["test"]
            run_dir = str(tmp_path / "runs" / "test2")
            limit = 10
            scrape = False
            json = True
            output = str(out_path)
            opencli_sites = None
            opencli_public_only = False
            opencli_timeout = 30
            backend = "opencli"
            legal_type = None

        monkeypatch.setattr("research.backends.opencli.OpenCLIBackend", _make_mock_backend)
        run_search(FakeArgs())
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "results" in data

    def test_run_search_scrape_writes_manifest(self, tmp_path, monkeypatch):
        class FakeArgs:
            query = ["test"]
            run_dir = str(tmp_path / "runs" / "with_scrape")
            limit = 3
            scrape = True
            json = False
            output = None
            opencli_sites = None
            opencli_public_only = None
            opencli_timeout = None
            backend = "opencli"
            legal_type = None

        monkeypatch.setattr("research.backends.opencli.OpenCLIBackend", _make_mock_backend)
        result = run_search(FakeArgs())
        run_dir = Path(FakeArgs.run_dir)
        assert result["scraped"]
        assert (run_dir / "scrape-manifest.tsv").exists()
        assert (run_dir / "scrape-1.json").exists()

    def test_multi_query_keeps_per_query_results(self, tmp_path, monkeypatch):
        class FakeArgs:
            query = ["alpha", "beta"]
            run_dir = str(tmp_path / "runs" / "multi_query")
            limit = 2
            scrape = False
            json = False
            output = None
            opencli_sites = None
            opencli_public_only = None
            opencli_timeout = None
            backend = "opencli"
            legal_type = None

        monkeypatch.setattr("research.backends.opencli.OpenCLIBackend", _make_mock_backend)
        run_search(FakeArgs())
        q1 = json.loads((Path(FakeArgs.run_dir) / "query-1.json").read_text())
        q2 = json.loads((Path(FakeArgs.run_dir) / "query-2.json").read_text())
        assert all("alpha" in r["snippet"] for r in q1["results"])
        assert all("beta" in r["snippet"] for r in q2["results"])

    def test_config_defaults_are_used(self, tmp_path, monkeypatch):
        constructed = {}

        class FakeArgs:
            query = ["configured"]
            run_dir = None
            limit = None
            scrape = False
            json = False
            output = None
            opencli_sites = None
            opencli_public_only = None
            opencli_timeout = None
            backend = "opencli"
            legal_type = None

        def fake_backend(*args, **kwargs):
            constructed.update(kwargs)
            return _make_mock_backend()

        monkeypatch.setattr("research.search.load_config", lambda: {
            "api_keys": {"yuandian_key": ""},
            "opencli": {
                "public_only": False,
                "timeout": 17,
                "inter_command_delay": 0,
                "default_sites": "",
            },
            "search": {"default_limit": 2, "max_concurrent": 1},
            "run_dir": {"base": str(tmp_path / "configured-runs")},
        })
        monkeypatch.setattr("research.backends.opencli.OpenCLIBackend", fake_backend)

        result = run_search(FakeArgs())
        run_dir = Path(result["run_dir"])
        q1 = json.loads((run_dir / "query-1.json").read_text())

        assert run_dir.parent == tmp_path / "configured-runs"
        assert result["count"] == 2
        assert q1["count"] == 2
        assert constructed["timeout"] == 17


def _make_mock_backend(*args, **kwargs):
    from research.backends.protocol import SearchResult, ScrapeResult
    class MockBackend:
        def search(self, query, count=10, **kw):
            return [SearchResult(
                title=f"Result {i}",
                url=f"https://example.com/{i}",
                snippet=f"Snippet {i} for {query}",
                source="example.com",
                published="2026-01-01",
            ) for i in range(count)]
        def scrape(self, url, **kw):
            return ScrapeResult(
                title="Scraped",
                url=url,
                markdown="# Scraped\nContent",
                text="Scraped Content",
                page_type="article",
                content_quality="full",
                metadata={},
            )
        def health(self):
            return {"status": "ok"}
    return MockBackend()
