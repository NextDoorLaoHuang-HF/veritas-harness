# Veritas / 征实 (Research CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone CLI tool + AI Skill that encapsulates a rigorous web research workflow with evidence auditing and citation verification pipelines.

**Architecture:** Python CLI with abstract `ResearchBackend` interface (first impl: reader-selfhost HTTP). Four atomic commands (search/scrape/verify/finalize) sharing a run directory. Evidence collection extracted as a common module shared by verify and finalize.

**Tech Stack:** Python 3.11+, `requests`, `toml` (config parsing), `argparse` (CLI), `pytest` (tests), `concurrent.futures` (concurrency).

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Project metadata, dependencies, entry point |
| `src/research/__init__.py` | Package marker |
| `src/research/cli.py` | argparse dispatching to subcommands |
| `src/research/config.py` | Config loading (env vars → `$XDG_CONFIG_HOME/research-cli/config.toml` → defaults) |
| `src/research/evidence.py` | `collect_evidence()` — scan RUN_DIR for all evidence artifacts |
| `src/research/backends/__init__.py` | Package marker |
| `src/research/backends/protocol.py` | `SearchResult`, `ScrapeResult` dataclasses; `ResearchBackend` ABC |
| `src/research/backends/reader_selfhost.py` | HTTP implementation of ResearchBackend |
| `src/research/search.py` | Search orchestration (multi-keyword, concurrent, dedup) |
| `src/research/scrape.py` | Scrape orchestration (multi-URL concurrent) |
| `src/research/verify.py` | `check_claims()` + `audit_report()` |
| `src/research/finalize.py` | Draft parsing, source classification, labeling, linkify, status, artifact writing |
| `tests/test_search.py` | Search tests |
| `tests/test_scrape.py` | Scrape tests |
| `tests/test_evidence.py` | Evidence collection tests |
| `tests/test_verify.py` | Claim check + audit tests |
| `tests/test_finalize.py` | Finalize pipeline tests |
| `tests/test_backend_reader_selfhost.py` | Reader-selfhost backend tests |
| `SKILL.md` | AI Agent learning manual |
| `config.toml.example` | Example config file |
| `docs/2026-05-23-research-cli-design.md` | Design spec (exists) |

---

### Task 1: Project skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/research/__init__.py`
- Create: `src/research/cli.py`
- Create: `src/research/config.py`
- Create: `src/research/backends/__init__.py`
- Create: `config.toml.example`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy._Backend"

[project]
name = "research-cli"
version = "0.1.0"
description = "CLI tool for rigorous web research with evidence auditing"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31.0",
    "toml>=0.10.2",
]

[tool.setuptools.packages.find]
where = ["src"]

[project.scripts]
research = "research.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create src/research/__init__.py and src/research/backends/__init__.py**

Empty files.

- [ ] **Step 3: Create src/research/config.py**

```python
import os
import toml
from pathlib import Path

DEFAULTS = {
    "backend": {
        "url": "http://localhost:3099",
        "api_key": "",
    },
    "search": {
        "default_limit": 10,
        "max_concurrent": 4,
    },
    "scrape": {
        "max_concurrent": 4,
        "cache_ttl_ms": 3600000,
    },
    "run_dir": {
        "base": ".research/runs",
    },
    "finalize": {
        "require_completion_time": True,
        "min_evidence_urls": 3,
        "min_evidence_dates": 0,
    },
}

def load_config() -> dict:
    config = dict(DEFAULTS)

    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_path = Path(xdg_config) / "research-cli" / "config.toml"
    if config_path.exists():
        user_config = toml.load(str(config_path))
        for section, values in user_config.items():
            if section in config and isinstance(values, dict):
                config[section].update(values)
            else:
                config[section] = values

    env_map = {
        "READER_API_URL": ("backend", "url"),
        "READER_API_KEY": ("backend", "api_key"),
        "READER_TIMEOUT_SECONDS": ("backend", "timeout"),
    }
    for env_key, (section, key) in env_map.items():
        value = os.environ.get(env_key)
        if value is not None:
            if section not in config:
                config[section] = {}
            config[section][key] = value

    return config
```

- [ ] **Step 4: Create src/research/cli.py (scaffold)**

```python
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(prog="research")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # search
    sp = subparsers.add_parser("search", help="Search the web")
    sp.add_argument("query", nargs="+", help="Search queries")
    sp.add_argument("--run-dir", help="Research run directory (auto-generated if omitted)")
    sp.add_argument("--limit", type=int, default=10, help="Results per query")
    sp.add_argument("--scrape", action="store_true", help="Light-scrape each result")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.add_argument("-o", "--output", help="Output file path")
    sp.add_argument("--site", help="Limit to source domain")
    sp.set_defaults(func=cmd_search)

    # scrape
    sp = subparsers.add_parser("scrape", help="Scrape URLs")
    sp.add_argument("url", nargs="+", help="URLs to scrape")
    sp.add_argument("--run-dir", help="Research run directory (auto-generated if omitted)")
    sp.add_argument("--format", choices=["markdown", "html", "text"], default="markdown")
    sp.add_argument("--browser", action="store_true", help="Force browser rendering")
    sp.add_argument("--wait-for", type=int, help="Render wait time (ms)")
    sp.add_argument("--timeout", type=int, help="Per-request timeout (s)")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.add_argument("-o", "--output", help="Output file path")
    sp.set_defaults(func=cmd_scrape)

    # verify
    sp = subparsers.add_parser("verify", help="Verify evidence in a run directory")
    sp.add_argument("--run-dir", required=True, help="Research run directory")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.add_argument("--allow-repairable", action="store_true", help="Don't fail on repairable issues")
    sp.add_argument("--fix-manifest", action="store_true", help="Auto-fix manifest")
    sp.set_defaults(func=cmd_verify)

    # finalize
    sp = subparsers.add_parser("finalize", help="Finalize a research report")
    sp.add_argument("--run-dir", required=True, help="Research run directory")
    sp.add_argument("--report", help="Draft report file path")
    sp.add_argument("--report-stdin", action="store_true", help="Read draft from stdin")
    sp.add_argument("--output", help="Final report path")
    sp.add_argument("--summary", help="Summary output path")
    sp.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    args.func(args)

def cmd_search(args):
    from research.search import run_search
    result = run_search(args)
    if args.json:
        import json
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)

def cmd_scrape(args):
    from research.scrape import run_scrape
    result = run_scrape(args)
    if args.json:
        import json
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)

def cmd_verify(args):
    from research.verify import run_verify
    result = run_verify(args)
    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))

def cmd_finalize(args):
    from research.finalize import run_finalize
    result = run_finalize(args)
    print(f"FINAL_STATUS={result['status']}")
    print(f"REPORT={result.get('report_path', 'N/A')}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Create config.toml.example**

```toml
[backend]
url = "http://localhost:3099"
api_key = ""

[search]
default_limit = 10
max_concurrent = 4

[scrape]
max_concurrent = 4
cache_ttl_ms = 3600000

[run_dir]
base = ".research/runs"

[finalize]
require_completion_time = true
min_evidence_urls = 3
min_evidence_dates = 0
```

- [ ] **Step 6: Verify imports work**

Run: `python -c "from research.config import load_config; print(load_config()['backend']['url'])"`

Expected: `http://localhost:3099`

---

### Task 2: Backend protocol + reader-selfhost implementation

**Files:**
- Create: `src/research/backends/protocol.py`
- Create: `src/research/backends/reader_selfhost.py`
- Create: `tests/test_backend_reader_selfhost.py`

- [ ] **Step 1: Write the failing test**

`tests/test_backend_reader_selfhost.py`:
```python
import pytest
from research.backends.protocol import SearchResult, ScrapeResult, ResearchBackend
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backend_reader_selfhost.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write minimal implementation**

`src/backends/protocol.py`:
```python
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
```

`src/backends/reader_selfhost.py`:
```python
from urllib.parse import urlencode, urljoin
import requests
from research.backends.protocol import ResearchBackend, SearchResult, ScrapeResult


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

    def search(self, query: str, count: int = 10, **kwargs) -> list[SearchResult]:
        url = self._build_search_url(query, count, **kwargs)
        headers = self._headers()
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
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
        resp = requests.get(full_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return ScrapeResult(
            title=data.get("title", ""),
            url=data.get("url", data.get("finalUrl", url)),
            markdown=data.get("markdown", ""),
            text=data.get("text", ""),
            page_type=data.get("pageType", data.get("page_type", "unknown")),
            content_quality=data.get("contentQuality", data.get("content_quality", "unknown")),
            metadata=data.get("metadata", {}),
        )

    def health(self) -> dict:
        resp = requests.get(self._health_url(), headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backend_reader_selfhost.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/backends/ tests/test_backend_reader_selfhost.py pyproject.toml src/research/__init__.py src/research/cli.py src/research/config.py config.toml.example
git commit -m "feat: project skeleton + backend abstraction with reader-selfhost implementation"
```

---

### Task 3: Search orchestration (search.py)

**Files:**
- Create: `src/research/search.py`
- Create: `tests/test_search.py`

- [ ] **Step 1: Write the failing test**

`tests/test_search.py`:
```python
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
            site = None

        monkeypatch.setattr("research.search.ReaderSelfhostBackend", _make_mock_backend)
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
            site = None

        monkeypatch.setattr("research.search.ReaderSelfhostBackend", _make_mock_backend)
        run_search(FakeArgs())
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "results" in data


def _make_mock_backend(*args, **kwargs):
    from research.backends.protocol import SearchResult
    class MockBackend:
        def search(self, query, count=10, **kw):
            return [SearchResult(
                title=f"Result {i}",
                url=f"https://example.com/{i}",
                snippet=f"Snippet {i}",
                source="example.com",
                published="2026-01-01",
            ) for i in range(count)]
        def scrape(self, url, **kw):
            return None
    return MockBackend()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_search.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write minimal implementation**

`src/search.py`:
```python
import json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from research.backends.reader_selfhost import ReaderSelfhostBackend
from research.backends.protocol import SearchResult

RUN_DIR_BASE = ".research/runs"


def build_run_dir(run_dir: str | None, topic: str = "research") -> Path:
    if run_dir:
        return Path(run_dir)
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic)[:40]
    path = Path(RUN_DIR_BASE) / f"{date_str}-{safe_topic}"
    path.mkdir(parents=True, exist_ok=True)
    print(f"Run directory: {path}")
    return path


def dedup_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for r in results:
        if r.url not in seen:
            seen.add(r.url)
            deduped.append(r)
    return deduped


def run_search(args) -> dict:
    backend = ReaderSelfhostBackend()
    run_dir = build_run_dir(args.run_dir, args.query[0])

    all_results: list[SearchResult] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(backend.search, q, args.limit, site=args.site): q
            for q in args.query
        }
        for future in as_completed(future_map):
            q = future_map[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                print(f"Search failed for '{q}': {e}")

    all_results = dedup_results(all_results)

    run_dir.mkdir(parents=True, exist_ok=True)
    for i, q in enumerate(args.query):
        query_results = [r for r in all_results if q.lower() in r.snippet.lower() or q.lower() in r.title.lower()]
        if not query_results and i == 0:
            query_results = all_results[:args.limit]
        chunk = query_results[:args.limit] if query_results else all_results[:args.limit]
        out_path = run_dir / f"query-{i + 1}.json"
        out_path.write_text(json.dumps({
            "query": q,
            "count": len(chunk),
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source, "published": r.published}
                for r in chunk
            ],
            "provider": "reader-selfhost",
        }, ensure_ascii=False, indent=2))

    return {
        "query": args.query,
        "count": len(all_results),
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source}
            for r in all_results
        ],
        "provider": "reader-selfhost",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_search.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/search.py tests/test_search.py
git commit -m "feat: search orchestration with multi-keyword concurrency and dedup"
```

---

### Task 4: Scrape orchestration (scrape.py)

**Files:**
- Create: `src/research/scrape.py`
- Create: `tests/test_scrape.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scrape.py`:
```python
import json
import pytest
from research.scrape import run_scrape


class TestRunScrape:
    def test_basic_scrape(self, tmp_path, monkeypatch):
        class FakeArgs:
            url = ["https://example.com/article"]
            run_dir = str(tmp_path / "runs" / "scrape_test")
            format = "markdown"
            browser = False
            wait_for = None
            timeout = None
            json = False
            output = None

        monkeypatch.setattr("research.scrape.ReaderSelfhostBackend", _make_mock_backend)
        result = run_scrape(FakeArgs())
        assert "url" in result
        assert result["status"] == 200

    def test_json_output(self, tmp_path, monkeypatch):
        out_path = tmp_path / "scrape_out.json"
        class FakeArgs:
            url = ["https://example.com/article"]
            run_dir = str(tmp_path / "runs" / "scrape_json")
            format = "markdown"
            browser = False
            wait_for = None
            timeout = None
            json = True
            output = str(out_path)

        monkeypatch.setattr("research.scrape.ReaderSelfhostBackend", _make_mock_backend)
        run_scrape(FakeArgs())
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["url"] == "https://example.com/article"

    def test_multiple_urls(self, tmp_path, monkeypatch):
        class FakeArgs:
            url = ["https://a.com", "https://b.com"]
            run_dir = str(tmp_path / "runs" / "multi")
            format = "markdown"
            browser = False
            wait_for = None
            timeout = None
            json = False
            output = None

        monkeypatch.setattr("research.scrape.ReaderSelfhostBackend", _make_mock_backend)
        result = run_scrape(FakeArgs())
        assert result["status"] == 200


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scrape.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write minimal implementation**

`src/scrape.py`:
```python
import json
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from research.backends.reader_selfhost import ReaderSelfhostBackend

RUN_DIR_BASE = ".research/runs"


def _ensure_run_dir(run_dir: str | None) -> Path:
    if run_dir:
        path = Path(run_dir)
    else:
        date_str = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        path = Path(RUN_DIR_BASE) / f"scrape-{date_str}"
        print(f"Run directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_scrape(args) -> dict:
    backend = ReaderSelfhostBackend()
    run_dir = _ensure_run_dir(args.run_dir)

    urls = args.url
    results = {}
    scrape_index = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(
                backend.scrape, url,
                format=args.format,
                browser=args.browser,
                wait_for=args.wait_for,
                timeout=args.timeout,
            ): url
            for url in urls
        }
        for idx, future in enumerate(as_completed(future_map)):
            url = future_map[future]
            try:
                sr = future.result()
                result_data = {
                    "url": sr.url,
                    "status": 200,
                    "title": sr.title,
                    "markdown": sr.markdown,
                    "text": sr.text,
                    "pageType": sr.page_type,
                    "contentQuality": sr.content_quality,
                    "blockedReason": "",
                }
                results[url] = result_data
            except Exception as e:
                result_data = {
                    "url": url,
                    "status": 500,
                    "title": "",
                    "markdown": "",
                    "text": "",
                    "pageType": "error",
                    "contentQuality": "empty",
                    "blockedReason": str(e),
                }
                results[url] = result_data

            fname = f"scrape-{idx + 1}.json"
            (run_dir / fname).write_text(json.dumps(result_data, ensure_ascii=False, indent=2))
            scrape_index.append({"url": url, "file": fname})

    manifest_path = run_dir / "scrape-manifest.tsv"
    manifest_path.write_text("url\tfile\n" + "\n".join(
        f"{e['url']}\t{e['file']}" for e in scrape_index
    ))

    return results.get(urls[0], {"url": urls[0], "status": 200})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scrape.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/scrape.py tests/test_scrape.py
git commit -m "feat: scrape orchestration with multi-URL concurrency"
```

---

### Task 5: Evidence collection (evidence.py)

**Files:**
- Create: `src/research/evidence.py`
- Create: `tests/test_evidence.py`

- [ ] **Step 1: Write the failing test**

`tests/test_evidence.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write minimal implementation**

`src/evidence.py`:
```python
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvidenceItem:
    url: str
    status: str  # scraped | search-only | failed
    label: str = ""
    date: str | None = None


def collect_evidence(run_dir: str) -> list[EvidenceItem]:
    path = Path(run_dir)
    if not path.exists():
        return []

    items: list[EvidenceItem] = []
    seen_urls: set[str] = set()

    # Scan search JSON files
    for f in path.glob("query-*.json"):
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text())
            for r in data.get("results", []):
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    items.append(EvidenceItem(
                        url=url,
                        status="search-only",
                        date=r.get("published"),
                    ))
        except (json.JSONDecodeError, KeyError):
            continue

    # Scan scrape manifest
    manifest = path / "scrape-manifest.tsv"
    if manifest.exists():
        for line in manifest.read_text().strip().split("\n")[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            url, fname = parts[0], parts[1]
            scrape_path = path / fname
            try:
                data = json.loads(scrape_path.read_text())
                content_quality = data.get("contentQuality", data.get("content_quality", ""))
                status_code = data.get("status", 200)
                if status_code != 200 or content_quality in ("empty",):
                    status = "failed"
                else:
                    status = "scraped"
                if url not in seen_urls:
                    seen_urls.add(url)
                    items.append(EvidenceItem(
                        url=url,
                        status=status,
                        date=data.get("published") if status == "scraped" else None,
                    ))
                else:
                    for item in items:
                        if item.url == url:
                            item.status = status
                            break
            except (json.JSONDecodeError, FileNotFoundError):
                if url not in seen_urls:
                    seen_urls.add(url)
                    items.append(EvidenceItem(url=url, status="failed"))

    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_evidence.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/evidence.py tests/test_evidence.py
git commit -m "feat: evidence collection module for scanning RUN_DIR artifacts"
```

---

### Task 6: Verify (verify.py)

**Files:**
- Create: `src/research/verify.py`
- Create: `tests/test_verify.py`

- [ ] **Step 1: Write the failing test**

`tests/test_verify.py`:
```python
import json
import pytest
from research.verify import check_claims, audit_report, AuditVerdict, ClaimResult


class TestCheckClaims:
    def test_all_match(self):
        claims_tsv = "url\tclaimed_status\nhttps://a.com\tscraped\nhttps://b.com\tsearch-only\n"
        evidence = [
            type("E", (), {"url": "https://a.com", "status": "scraped", "label": "S1", "date": "2026-01-01"}),
            type("E", (), {"url": "https://b.com", "status": "search-only", "label": "S2", "date": None}),
        ]
        results = check_claims(claims_tsv, evidence)
        assert all(r.result == "match" for r in results)
        assert len(results) == 2

    def test_mismatch(self):
        claims_tsv = "url\tclaimed_status\nhttps://a.com\tscraped\n"
        evidence = [
            type("E", (), {"url": "https://a.com", "status": "search-only", "label": "", "date": None}),
        ]
        results = check_claims(claims_tsv, evidence)
        assert results[0].result == "mismatch"

    def test_missing_claim(self):
        claims_tsv = "url\tclaimed_status\nhttps://a.com\tscraped\nhttps://b.com\tscraped\n"
        evidence = [
            type("E", (), {"url": "https://a.com", "status": "scraped", "label": "S1", "date": "2026-01-01"}),
        ]
        results = check_claims(claims_tsv, evidence)
        assert any(r.result == "missing" for r in results)


class TestAuditReport:
    def test_perfect_report(self, tmp_path):
        report = tmp_path / "report.md"
        report.write_text(
            "## 结论\n\nContent\n\n"
            "## 关键发现\n\nContent\n\n"
            "## 证据与来源\n\n[S1](https://a.com) source\n\n"
            "## 置信度\n\nHigh\n\n"
            "## 未解决问题\n\nNone\n\n"
            "*完成时间: 2026-05-24T12:00:00Z*"
        )
        verdict = audit_report(str(report))
        assert verdict == AuditVerdict.PASS

    def test_missing_sections(self, tmp_path):
        report = tmp_path / "report.md"
        report.write_text("## 结论\n\nContent\n\n## 关键发现\n\nContent\n")
        verdict = audit_report(str(report))
        assert verdict == AuditVerdict.HARD_FAIL

    def test_missing_completion_time(self, tmp_path):
        report = tmp_path / "report.md"
        report.write_text(
            "## 结论\n\nContent\n\n"
            "## 关键发现\n\nContent\n\n"
            "## 证据与来源\n\n[S1](url)\n\n"
            "## 置信度\n\nHigh\n\n"
            "## 未解决问题\n\nNone\n"
        )
        verdict = audit_report(str(report))
        assert verdict == AuditVerdict.REPAIRABLE


class TestRunVerify:
    def test_verify_integration(self, tmp_path, monkeypatch):
        # Setup RUN_DIR with artifacts
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [{"url": "https://a.com", "title": "A", "snippet": "s", "source": "a.com"}]
        }))
        (tmp_path / "source-claims.tsv").write_text(
            "url\tclaimed_status\nhttps://a.com\tsearch-only\n"
        )
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\nC\n\n## 关键发现\n\nK\n\n"
            "## 证据与来源\n\n[S1](https://a.com)\n\n"
            "## 置信度\n\nH\n\n## 未解决问题\n\nN\n\n"
            "*完成时间: 2026-05-24T12:00:00Z*"
        )

        class FakeArgs:
            run_dir = str(tmp_path)
            json = False
            allow_repairable = True
            fix_manifest = False

        from research.verify import run_verify
        result = run_verify(FakeArgs())
        assert "verdict" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_verify.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write minimal implementation**

`src/verify.py`:
```python
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AuditVerdict(Enum):
    PASS = "pass"
    REPAIRABLE = "repairable"
    HARD_FAIL = "hard_fail"


@dataclass
class ClaimResult:
    url: str
    claimed_status: str
    actual_status: str | None
    result: str  # match | mismatch | missing


def check_claims(claims_tsv: str, evidence: list) -> list[ClaimResult]:
    lines = claims_tsv.strip().split("\n")
    if len(lines) < 2:
        return []
    results = []
    evidence_map = {e.url: e for e in evidence}
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        url, claimed = parts[0], parts[1]
        actual = evidence_map.get(url)
        if actual is None:
            results.append(ClaimResult(url=url, claimed_status=claimed, actual_status=None, result="missing"))
        elif actual.status == claimed:
            results.append(ClaimResult(url=url, claimed_status=claimed, actual_status=actual.status, result="match"))
        else:
            results.append(ClaimResult(url=url, claimed_status=claimed, actual_status=actual.status, result="mismatch"))
    return results


REQUIRED_SECTIONS = ["结论", "关键发现", "证据与来源", "置信度", "未解决问题"]


def audit_report(report_path: str) -> AuditVerdict:
    path = Path(report_path)
    if not path.exists():
        return AuditVerdict.HARD_FAIL
    text = path.read_text()

    missing = [s for s in REQUIRED_SECTIONS if f"## {s}" not in text]
    if missing:
        return AuditVerdict.HARD_FAIL

    has_completion_time = "*完成时间" in text or "completion_time" in text or "UTC" in text
    if not has_completion_time:
        return AuditVerdict.REPAIRABLE

    return AuditVerdict.PASS


def run_verify(args) -> dict:
    from research.evidence import collect_evidence

    run_dir = Path(args.run_dir)
    evidence = collect_evidence(str(run_dir))

    claims_path = run_dir / "source-claims.tsv"
    claim_results = []
    if claims_path.exists():
        claim_results = check_claims(claims_path.read_text(), evidence)

    report_path = run_dir / "draft-report.md"
    if report_path.exists():
        verdict = audit_report(str(report_path))
    else:
        report_candidates = list(run_dir.glob("*report*.md"))
        if report_candidates:
            verdict = audit_report(str(report_candidates[0]))
        else:
            verdict = AuditVerdict.HARD_FAIL

    scraped = sum(1 for e in evidence if e.status == "scraped")
    search_only = sum(1 for e in evidence if e.status == "search-only")
    failed = sum(1 for e in evidence if e.status == "failed")
    match_count = sum(1 for c in claim_results if c.result == "match")

    has_repairable = verdict == AuditVerdict.REPAIRABLE
    has_fail = verdict == AuditVerdict.HARD_FAIL

    if args.allow_repairable and has_repairable:
        final_verdict = AuditVerdict.PASS
    elif has_fail:
        final_verdict = AuditVerdict.HARD_FAIL
    elif has_repairable:
        final_verdict = AuditVerdict.REPAIRABLE
    else:
        final_verdict = verdict

    result = {
        "evidence_urls": {
            "total": len(evidence),
            "scraped": scraped,
            "search_only": search_only,
            "failed": failed,
        },
        "claim_check": {
            "total": len(claim_results),
            "match": match_count,
            "match_pct": f"{match_count / len(claim_results) * 100:.0f}%" if claim_results else "N/A",
        },
        "report_structure": {
            "sections": "5/5" if verdict != AuditVerdict.HARD_FAIL else f"{5 - len([s for s in REQUIRED_SECTIONS if f'## {s}' not in Path(run_dir / 'draft-report.md').read_text()])}/5",
            "completion_time": "✓" if verdict != AuditVerdict.REPAIRABLE and verdict != AuditVerdict.HARD_FAIL else ("✗" if verdict == AuditVerdict.REPAIRABLE else "N/A"),
        },
        "verdict": final_verdict.value,
    }

    if not args.json:
        print(f"evidence-urls: {len(evidence)} collected, {scraped} scraped, {search_only} search-only, {failed} failed")
        if claim_results:
            print(f"claim-check: {match_count}/{len(claim_results)} match ({result['claim_check']['match_pct']})")
        print(f"report-structure: sections {result['report_structure']['sections']}, completion-time {result['report_structure']['completion_time']}")
        print(f"verdict: {final_verdict.value}")

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_verify.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/verify.py tests/test_verify.py
git commit -m "feat: verify module with claim checking and report structure audit"
```

---

### Task 7: Finalize (finalize.py)

**Files:**
- Create: `src/research/finalize.py`
- Create: `tests/test_finalize.py`

- [ ] **Step 1: Write the failing test**

`tests/test_finalize.py`:
```python
import json
import pytest
from pathlib import Path
from research.finalize import (
    parse_draft_report,
    classify_sources,
    assign_labels,
    linkify_report,
    determine_final_status,
    write_artifacts,
    DraftReport,
    EvidenceRow,
    LabeledRow,
)


class TestParseDraftReport:
    def test_basic_parse(self):
        text = (
            "## 结论\n\nSummary\n\n"
            "## 关键发现\n\nFinding\n\n"
            "## 证据与来源\n\n"
            "| 来源 | 类型 | 状态 |\n"
            "|------|------|------|\n"
            "| https://a.com | article | scraped |\n"
            "| https://b.com | news | search-only |\n\n"
            "## 置信度\n\nHigh\n\n"
            "## 未解决问题\n\nNone\n"
        )
        report = parse_draft_report(text)
        assert len(report.sections) == 5
        assert len(report.evidence_rows) == 2
        assert report.evidence_rows[0].url == "https://a.com"

    def test_no_evidence_table(self):
        text = "## 结论\n\nC\n\n## 关键发现\n\nK\n\n## 证据与来源\n\nNone\n\n## 置信度\n\nH\n\n## 未解决问题\n\nN\n"
        report = parse_draft_report(text)
        assert report.evidence_rows == []


class TestClassifySources:
    def test_all_admissible(self):
        from research.evidence import EvidenceItem
        evidence = [EvidenceItem(url="https://a.com", status="scraped")]
        rows = [EvidenceRow(url="https://a.com", source_type="article", status="scraped")]
        admissible, dropped = classify_sources(evidence, rows)
        assert len(admissible) == 1
        assert len(dropped) == 0

    def test_dropped_failed(self):
        from research.evidence import EvidenceItem
        evidence = [EvidenceItem(url="https://a.com", status="failed")]
        rows = [EvidenceRow(url="https://a.com", source_type="article", status="scraped")]
        admissible, dropped = classify_sources(evidence, rows)
        assert len(admissible) == 0
        assert len(dropped) == 1


class TestAssignLabels:
    def test_sequential_labels(self):
        rows = [
            LabeledRow(url="https://a.com", source_type="article", status="scraped", label=""),
            LabeledRow(url="https://b.com", source_type="news", status="search-only", label=""),
        ]
        labeled = assign_labels(rows)
        assert labeled[0].label == "S1"
        assert labeled[1].label == "S2"

    def test_empty_list(self):
        assert assign_labels([]) == []


class TestLinkifyReport:
    def test_basic_linkify(self):
        report = "See [S1] and [S2] for details."
        labeled = [
            LabeledRow(url="https://a.com", label="S1"),
            LabeledRow(url="https://b.com", label="S2"),
        ]
        result = linkify_report(report, labeled)
        assert "[S1](https://a.com)" in result
        assert "[S2](https://b.com)" in result

    def test_no_labels(self):
        report = "No sources."
        assert linkify_report(report, []) == "No sources."


class TestDetermineFinalStatus:
    def test_pass(self):
        assert determine_final_status(admissible=5, dropped=0, audit_verdict="pass") == "pass"

    def test_degraded(self):
        assert determine_final_status(admissible=5, dropped=2, audit_verdict="pass") == "degraded"

    def test_fatal_on_fail(self):
        assert determine_final_status(admissible=0, dropped=5, audit_verdict="pass") == "fatal"

    def test_fatal_on_audit_fail(self):
        assert determine_final_status(admissible=5, dropped=1, audit_verdict="hard_fail") == "fatal"


class TestWriteArtifacts:
    def test_writes_all_files(self, tmp_path):
        write_artifacts(
            run_dir=str(tmp_path),
            report="# Final\nContent",
            claims=[{"url": "https://a.com", "status": "scraped"}],
            audit={"verdict": "pass"},
            summary={"status": "pass"},
        )
        assert (tmp_path / "final-report.md").exists()
        assert (tmp_path / "source-claims.tsv").exists()
        assert (tmp_path / "source-audit.tsv").exists()
        assert (tmp_path / "finalize-summary.json").exists()

    def test_report_content(self, tmp_path):
        write_artifacts(
            run_dir=str(tmp_path),
            report="# Final\nContent",
            claims=[],
            audit={},
            summary={},
        )
        content = (tmp_path / "final-report.md").read_text()
        assert "# Final" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_finalize.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Write minimal implementation**

`src/finalize.py`:
```python
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone


@dataclass
class EvidenceRow:
    url: str
    source_type: str = ""
    status: str = ""


@dataclass
class DraftReport:
    sections: dict[str, str] = field(default_factory=dict)
    evidence_rows: list[EvidenceRow] = field(default_factory=list)


@dataclass
class LabeledRow:
    url: str
    source_type: str = ""
    status: str = ""
    label: str = ""


def parse_draft_report(text: str) -> DraftReport:
    sections: dict[str, str] = {}
    current_section = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    evidence_rows: list[EvidenceRow] = []
    evidence_section = sections.get("证据与来源", "")
    table_lines = [l for l in evidence_section.split("\n") if "|" in l and "---" not in l]
    for line in table_lines[1:]:
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 1:
            url = parts[0]
            source_type = parts[1] if len(parts) > 1 else ""
            status = parts[2] if len(parts) > 2 else ""
            evidence_rows.append(EvidenceRow(url=url, source_type=source_type, status=status))

    return DraftReport(sections=sections, evidence_rows=evidence_rows)


def classify_sources(evidence: list, rows: list[EvidenceRow]) -> tuple[list[LabeledRow], list[LabeledRow]]:
    evidence_map = {e.url: e for e in evidence}
    admissible: list[LabeledRow] = []
    dropped: list[LabeledRow] = []

    for row in rows:
        ev = evidence_map.get(row.url)
        status = ev.status if ev else "unknown"
        lr = LabeledRow(url=row.url, source_type=row.source_type, status=status)
        if ev and ev.status in ("scraped", "search-only"):
            admissible.append(lr)
        else:
            dropped.append(lr)

    return admissible, dropped


def assign_labels(rows: list[LabeledRow]) -> list[LabeledRow]:
    for i, row in enumerate(rows, start=1):
        row.label = f"S{i}"
    return rows


def linkify_report(report: str, labeled: list[LabeledRow]) -> str:
    label_map = {f"[{lr.label}]": f"[{lr.label}]({lr.url})" for lr in labeled if lr.label}
    result = report
    for old, new in label_map.items():
        result = result.replace(old, new)
    return result


def determine_final_status(admissible: list | int, dropped: list | int, audit_verdict: str) -> str:
    ad_count = len(admissible) if isinstance(admissible, list) else admissible
    dr_count = len(dropped) if isinstance(dropped, list) else dropped

    if audit_verdict in ("hard_fail",):
        return "fatal"
    if dr_count > ad_count:
        return "fatal"
    if dr_count > 0:
        return "degraded"
    return "pass"


def write_artifacts(run_dir: str, report: str, claims: list, audit: dict, summary: dict):
    base = Path(run_dir)
    base.mkdir(parents=True, exist_ok=True)

    (base / "final-report.md").write_text(report)

    claims_lines = ["url\tstatus"]
    for c in claims:
        claims_lines.append(f"{c.get('url', '')}\t{c.get('status', '')}")
    (base / "source-claims.tsv").write_text("\n".join(claims_lines))

    audit_lines = ["url\tlabel\tclaimed\tactual"]
    (base / "source-audit.tsv").write_text("\n".join(audit_lines))

    (base / "finalize-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))


def run_finalize(args) -> dict:
    from research.evidence import collect_evidence

    run_dir = Path(args.run_dir)

    if args.report_stdin:
        import sys
        draft_text = sys.stdin.read()
    elif args.report:
        draft_text = Path(args.report).read_text()
    else:
        draft_text = (run_dir / "draft-report.md").read_text()

    draft = parse_draft_report(draft_text)
    evidence = collect_evidence(str(run_dir))
    admissible, dropped = classify_sources(evidence, draft.evidence_rows)
    all_sources = assign_labels(admissible + dropped)

    report_text = draft_text
    if all_sources:
        report_text = linkify_report(report_text, all_sources)

    from research.verify import audit_report
    verdict = audit_report(str(run_dir / "draft-report.md")) if (run_dir / "draft-report.md").exists() else None
    audit_result = verdict.value if verdict else "unknown"

    final_status = determine_final_status(admissible, dropped, audit_result)

    output_path = args.output or str(run_dir / "final-report.md")
    Path(output_path).write_text(report_text)

    claims_data = [{"url": lr.url, "status": lr.status, "label": lr.label} for lr in all_sources]
    audit_data = {
        "verdict": audit_result,
        "admissible": len(admissible),
        "dropped": len(dropped),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    summary = {
        "status": final_status,
        "admissible": len(admissible),
        "dropped": len(dropped),
        "audit_verdict": audit_result,
        "report_path": str(Path(output_path).resolve()),
    }

    write_artifacts(
        run_dir=str(run_dir),
        report=report_text,
        claims=claims_data,
        audit=audit_data,
        summary=summary,
    )

    result = {
        "status": final_status,
        "report_path": str(Path(output_path).resolve()),
        "admissible": len(admissible),
        "dropped": len(dropped),
    }

    print(f"✔ final-report.md")
    print(f"✔ source-claims.tsv")
    print(f"✔ source-audit.tsv")
    print(f"✔ finalize-summary.json")

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_finalize.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/research/finalize.py tests/test_finalize.py
git commit -m "feat: finalize module with draft parsing, labeling, linkify, and artifact writing"
```

---

### Task 8: SKILL.md

**Files:**
- Create: `SKILL.md`

- [ ] **Step 1: Write SKILL.md**

`SKILL.md`:
```markdown
# Research CLI — AI Agent Skill

## 适用场景

当用户要求联网搜索、事实核验、信息汇总时。

## 轻量 vs 深度判定

- **deep**：时效性强 / 高风险 / 需多来源交叉验证
- **light**：简单事实确认、单来源摘要

## CLI 快速参考

```
research search <query> [<query2> ...]   搜索（多关键词并发）
research scrape <url> [<url2> ...]        抓取（多 URL 并发）
research verify --run-dir <path>          证据审计
research finalize --run-dir <path>        报告收口
```

详见 `research <cmd> -h`。

## 标准工作流

```
搜索 → Agent 出关键词计划 → CLI 并发搜索 → 筛选 URL
→ CLI 并发抓取 → Agent 写草稿 → CLI finalize 收口
```

## 抓取降级链路

直连 → `--browser` Puppeteer → Agent 端浏览器自动化工具（agent-browser / Playwright MCP 等）

## 报告结构

5 段标题：结论 / 关键发现 / 证据与来源 / 置信度 / 未解决问题

## 质量闸门

- FINAL_STATUS=pass：全部通过
- FINAL_STATUS=degraded：部分来源未采集，报告可用但标注降级
- FINAL_STATUS=fatal：关键缺陷，报告不可用
- 最低证据数：3 条
- 置信度标签：high / medium / low / unverifiable

## 多 Agent 协作模式（框架支持时启用）

### 并行研究方向调研
- 主 Agent 将研究问题拆解为 N 个独立子方向
- 每个子方向派发一个子 Agent，各自执行：关键词规划 → `research search` → URL 筛选 → `research scrape`
- 子 Agent 返回结构化研究笔记（含发现摘要 + 已收集证据 URL 列表）
- 主 Agent 汇总所有子方向结果，撰写综合草稿

### 独立多方验证
- 最终报告产出后，派发 2-3 个子 Agent 独立执行 `research verify --run-dir <path>`
- 每个子 Agent 各自做 claim 比对 + 结构审计
- 主 Agent 比对多份审计结果：一致则通过，不一致则标记争议点复查
- 避免单 Agent 的确认偏误

### 协作时序
```
主 Agent 拆解问题
  ├─ 子 Agent A: 方向 1 → search → scrape → 笔记
  ├─ 子 Agent B: 方向 2 → search → scrape → 笔记
  └─ 子 Agent C: 方向 3 → search → scrape → 笔记
主 Agent 汇总 → 写草稿 → finalize
  ├─ 子 Agent D: verify（独立）
  ├─ 子 Agent E: verify（独立）
  └─ 主 Agent: 比对审计 → 定稿
```

## 禁忌

- 不能凭记忆答时效性问题
- 搜索摘要 ≠ 正文证据（必须 scrape 获取全文）
- 转载 ≠ 独立来源（需找原始出处）
```

- [ ] **Step 2: Verify file exists**

Run: `head -3 SKILL.md`
Expected: First 3 lines of SKILL.md

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "docs: add SKILL.md for AI Agent research workflow"
```

---

### Task 9: Full integration test and final verification

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Verify CLI entry point**

Run: `python -m research.cli --help`
Expected: Shows usage with search/scrape/verify/finalize

- [ ] **Step 3: Commit final state**

```bash
git add -A
git commit -m "chore: finalize project with all modules and tests"
```
