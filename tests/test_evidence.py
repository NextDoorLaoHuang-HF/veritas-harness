import json
import pytest
from pathlib import Path
from research.evidence import collect_evidence, EvidenceItem


class TestEvidenceItem:
    def test_fields(self):
        item = EvidenceItem(url="https://x.com", status="scraped", label="S1", date="2026-05-01")
        assert item.url == "https://x.com"
        assert item.status == "scraped"

    def test_default_date(self):
        item = EvidenceItem(url="https://x.com", status="search-only", label="S2")
        assert item.date is None


class TestCollectEvidence:
    def test_empty_dir(self, tmp_path):
        items = collect_evidence(str(tmp_path))
        assert items == []

    def test_search_only_sources(self, tmp_path):
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [
                {"url": "https://a.com", "title": "A", "snippet": "s", "source": "a.com", "published": "2026-01-01"},
                {"url": "https://b.com", "title": "B", "snippet": "s", "source": "b.com"},
            ]
        }))
        items = collect_evidence(str(tmp_path))
        urls = {i.url for i in items}
        assert "https://a.com" in urls
        assert "https://b.com" in urls
        assert all(i.status == "search-only" for i in items)

    def test_scraped_sources(self, tmp_path):
        (tmp_path / "scrape-manifest.tsv").write_text(
            "url\tfile\nhttps://a.com/article\tscrape-1.json\n"
        )
        (tmp_path / "scrape-1.json").write_text(json.dumps({
            "url": "https://a.com/article",
            "status": 200,
            "contentQuality": "full",
        }))
        items = collect_evidence(str(tmp_path))
        assert len(items) == 1
        assert items[0].status == "scraped"

    def test_failed_scrape(self, tmp_path):
        (tmp_path / "scrape-manifest.tsv").write_text(
            "url\tfile\nhttps://x.com/fail\tscrape-1.json\n"
        )
        (tmp_path / "scrape-1.json").write_text(json.dumps({
            "url": "https://x.com/fail",
            "status": 500,
            "contentQuality": "empty",
            "blockedReason": "timeout",
        }))
        items = collect_evidence(str(tmp_path))
        assert len(items) == 1
        assert items[0].status == "failed"

    def test_mixed_sources(self, tmp_path):
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [
                {"url": "https://search-only.com", "title": "S", "snippet": "s", "source": "s.com"},
            ]
        }))
        (tmp_path / "scrape-manifest.tsv").write_text(
            "url\tfile\nhttps://scraped.com\tscrape-1.json\n"
        )
        (tmp_path / "scrape-1.json").write_text(json.dumps({
            "url": "https://scraped.com", "status": 200, "contentQuality": "full",
        }))
        items = collect_evidence(str(tmp_path))
        assert len(items) == 2
        statuses = {i.status for i in items}
        assert "scraped" in statuses
        assert "search-only" in statuses
