import json
import pytest
from pathlib import Path
from research.scrape import run_scrape


class TestRunScrape:
    def test_basic_scrape(self, tmp_path, monkeypatch):
        class FakeArgs:
            url = ["https://example.com/article"]
            run_dir = str(tmp_path / "runs" / "scrape_test")
            timeout = None
            json = False
            output = None

        monkeypatch.setattr("research.scrape.OpenCLIBackend", _make_mock_backend)
        result = run_scrape(FakeArgs())
        assert "url" in result
        assert result["status"] == 200

    def test_json_output(self, tmp_path, monkeypatch):
        out_path = tmp_path / "scrape_out.json"
        class FakeArgs:
            url = ["https://example.com/article"]
            run_dir = str(tmp_path / "runs" / "scrape_json")
            timeout = None
            json = True
            output = str(out_path)

        monkeypatch.setattr("research.scrape.OpenCLIBackend", _make_mock_backend)
        run_scrape(FakeArgs())
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["url"] == "https://example.com/article"

    def test_multiple_urls(self, tmp_path, monkeypatch):
        class FakeArgs:
            url = ["https://a.com", "https://b.com"]
            run_dir = str(tmp_path / "runs" / "multi")
            timeout = None
            json = False
            output = None

        monkeypatch.setattr("research.scrape.OpenCLIBackend", _make_mock_backend)
        result = run_scrape(FakeArgs())
        assert result["count"] == 2
        assert len(result["results"]) == 2
        assert all(r["status"] == 200 for r in result["results"])
        assert result["manifest"].endswith("scrape-manifest.tsv")

    def test_yuandian_url_routing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("research.scrape.YuandianBackend", _make_mock_yuandian)
        monkeypatch.setattr("research.scrape.OpenCLIBackend", _make_mock_backend)
        class FakeArgs:
            url = ["yuandian://law/detail?id=abc123"]
            run_dir = str(tmp_path / "runs" / "yuandian")
            timeout = None
            json = False
            output = None

        result = run_scrape(FakeArgs())
        assert result["status"] == 200
        assert result["pageType"] == "legal"
        assert result["title"] == "工伤保险条例"

    def test_mixed_urls(self, tmp_path, monkeypatch):
        monkeypatch.setattr("research.scrape.OpenCLIBackend", _make_mock_backend)
        monkeypatch.setattr("research.scrape.YuandianBackend", _make_mock_yuandian)
        class FakeArgs:
            url = ["https://example.com/article", "yuandian://law/detail?id=abc123"]
            run_dir = str(tmp_path / "runs" / "mixed")
            timeout = None
            json = False
            output = None

        result = run_scrape(FakeArgs())
        assert result["count"] == 2
        assert len(result["results"]) == 2
        manifest = tmp_path / "runs" / "mixed" / "scrape-manifest.tsv"
        lines = manifest.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_config_defaults_are_used(self, tmp_path, monkeypatch):
        constructed = {}

        class FakeArgs:
            url = ["https://example.com/article"]
            run_dir = None
            timeout = None
            json = False
            output = None

        def fake_backend(*args, **kwargs):
            constructed.update(kwargs)
            return _make_mock_backend()

        monkeypatch.setattr("research.scrape.load_config", lambda: {
            "opencli": {"timeout": 23},
            "run_dir": {"base": str(tmp_path / "configured-runs")},
        })
        monkeypatch.setattr("research.scrape.OpenCLIBackend", fake_backend)

        result = run_scrape(FakeArgs())
        run_dirs = list((tmp_path / "configured-runs").iterdir())

        assert result["status"] == 200
        assert constructed["timeout"] == 23
        assert len(run_dirs) == 1
        assert (run_dirs[0] / "scrape-manifest.tsv").exists()


def _make_mock_backend(*args, **kwargs):
    from research.backends.protocol import ScrapeResult
    class MockBackend:
        def scrape(self, url, **kw):
            return ScrapeResult(
                title="Test Article",
                url=url,
                markdown="# Test\nContent",
                text="Test Content",
                page_type="article",
                content_quality="full",
                metadata={},
            )
    return MockBackend()


def _make_mock_yuandian(*args, **kwargs):
    from research.backends.protocol import ScrapeResult
    class MockBackend:
        def scrape(self, url, **kw):
            return ScrapeResult(
                title="工伤保险条例",
                url=url,
                markdown='{"name": "工伤保险条例"}',
                text='{"name": "工伤保险条例"}',
                page_type="legal",
                content_quality="full",
                metadata={},
            )
    return MockBackend()
