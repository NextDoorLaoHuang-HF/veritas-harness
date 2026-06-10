from research.backends.opencli import (
    OpenCLIBackend,
    detect_category,
    select_sites,
    SITE_COMMANDS,
)
from research.backends.protocol import SearchResult


def test_detect_category_ai():
    assert detect_category("latest LLM agent benchmark") == "ai"


def test_select_sites_auto_routes_without_category():
    sites = select_sites("latest LLM agent benchmark")
    assert "arxiv" in sites
    assert "hackernews" in sites


def test_select_sites_public_only_filters_cookie_sites():
    sites = select_sites("latest LLM agent benchmark", public_only=True)
    assert "reddit" not in sites
    assert "arxiv" in sites


def test_site_commands_use_non_default_search_command():
    assert SITE_COMMANDS["aibase"]["search"] == "news"
    assert SITE_COMMANDS["bbc"]["search"] == "news"


def test_search_uses_configured_sites(monkeypatch):
    seen = []

    def fake_search_site(self, site, query, count):
        seen.append(site)
        return [
            SearchResult(
                title=site,
                url=f"https://example.com/{site}",
                snippet=query,
                source=site,
            )
        ]

    monkeypatch.setattr(OpenCLIBackend, "_search_site", fake_search_site)
    backend = OpenCLIBackend(sites=["arxiv"], inter_command_delay=0)
    results = backend.search("general query", count=5)
    assert seen == ["arxiv"]
    assert results[0].source == "arxiv"


def test_search_site_uses_site_command(monkeypatch):
    calls = []

    def fake_run_opencli(args, timeout=30):
        calls.append(args)
        return [{"title": "AIBase item", "url": "https://aibase.com/item", "snippet": "s"}]

    monkeypatch.setattr("research.backends.opencli._run_opencli", fake_run_opencli)
    backend = OpenCLIBackend(inter_command_delay=0)
    results = backend._search_site("aibase", "agent", 3)
    assert calls[0][:2] == ["aibase", "news"]
    assert results[0].url == "https://aibase.com/item"
