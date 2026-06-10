"""
OpenCLI backend for veritas-harness.

Routes search queries to high-quality information sites via opencli
(<site> <command>) adapters. Supports both PUBLIC (no browser needed)
and COOKIE/INTERCEPT/UI (requires Chrome + OpenCLI extension) strategies.

Auto-routing: when no --site is specified, queries are dispatched to a
curated set of sites based on category detection (tech, ai, china, academic, etc.).
"""

import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from research.backends.protocol import (
    ResearchBackend, SearchResult, ScrapeResult, BackendError,
)

# ── Site routing table ──────────────────────────────────────────────
# Maps site domain patterns → opencli site + search/read commands.
# "strategy" indicates whether browser is needed.

SITE_ROUTING: dict[str, dict] = {
    "news.ycombinator.com": {"site": "hackernews", "search": "search", "read": "read", "strategy": "public"},
    "arxiv.org":            {"site": "arxiv",       "search": "search", "read": "paper",  "strategy": "public"},
    "reddit.com":           {"site": "reddit",      "search": "search", "read": "read",   "strategy": "cookie"},
    "wikipedia.org":        {"site": "wikipedia",   "search": "search", "read": "summary","strategy": "public"},
    "36kr.com":             {"site": "36kr",        "search": "search", "read": "article", "strategy": "intercept"},
    "aibase.com":           {"site": "aibase",      "search": "news",   "read": None,     "strategy": "public"},
    "bbc.com":              {"site": "bbc",         "search": "news",   "read": None,     "strategy": "public"},
    "bloomberg.com":        {"site": "bloomberg",   "search": "news",   "read": None,     "strategy": "public"},
    "mp.weixin.qq.com":     {"site": "weixin",      "search": "search", "read": "download","strategy": "cookie"},
    "zhihu.com":            {"site": "zhihu",       "search": "search", "read": "answer-detail","strategy": "cookie"},
    "weibo.com":            {"site": "weibo",       "search": "search", "read": None,     "strategy": "cookie"},
    "stackoverflow.com":    {"site": "stackoverflow","search": "search","read": "read",   "strategy": "public"},
    "dev.to":               {"site": "devto",       "search": "search", "read": "read",   "strategy": "public"},
    "linux.do":             {"site": "linux-do",    "search": "search", "read": "topic-content","strategy": "cookie"},
    "v2ex.com":             {"site": "v2ex",        "search": "search", "read": "topic",  "strategy": "cookie"},
    "scholar.google.com":   {"site": "google-scholar","search": "search","read": None,    "strategy": "public"},
    "pubmed.ncbi.nlm.nih.gov": {"site": "pubmed",   "search": "search", "read": "article","strategy": "public"},
    "dblp.org":             {"site": "dblp",        "search": "search", "read": "paper",  "strategy": "public"},
    "twitter.com":          {"site": "twitter",     "search": "search", "read": "thread", "strategy": "ui"},
    "x.com":                {"site": "twitter",     "search": "search", "read": "thread", "strategy": "ui"},
    "producthunt.com":      {"site": "producthunt", "search": "browse", "read": None,     "strategy": "intercept"},
    "medium.com":           {"site": "medium",      "search": "search", "read": None,     "strategy": "cookie"},
    "openalex.org":         {"site": "openalex",    "search": "search", "read": "work",   "strategy": "public"},
    "bilibili.com":         {"site": "bilibili",    "search": "search", "read": None,     "strategy": "cookie"},
    "google.com":           {"site": "google",      "search": "search", "read": None,     "strategy": "public"},
    "duckduckgo.com":       {"site": "duckduckgo",  "search": "search", "read": None,     "strategy": "public"},
}


# ── Category → site routing ──────────────────────────────────────────
# When no --site is specified, the backend auto-routes to a curated set
# of sites based on keyword category detection.

CATEGORY_SITES: dict[str, list[str]] = {
    "ai":       ["hackernews", "reddit", "arxiv", "aibase", "36kr"],
    "tech":     ["hackernews", "reddit", "arxiv", "36kr", "devto"],
    "china":    ["weibo", "zhihu", "weixin", "36kr"],
    "academic": ["arxiv", "google-scholar", "pubmed", "dblp", "openalex"],
    "dev":      ["stackoverflow", "devto", "linux-do", "v2ex", "hackernews"],
    "general":  ["wikipedia", "hackernews", "reddit", "google", "duckduckgo"],
    "legal":    ["google", "wikipedia"],  # legal → primarily yuandian, opencli as supplement
    "news":     ["bbc", "bloomberg", "hackernews", "google"],
}

SITE_COMMANDS: dict[str, dict[str, str | None]] = {}
for _info in SITE_ROUTING.values():
    SITE_COMMANDS.setdefault(_info["site"], {
        "search": _info.get("search", "search"),
        "read": _info.get("read"),
    })

# Keywords for category detection
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "ai":       ["ai", "llm", "gpt", "claude", "模型", "人工智能", "machine learning",
                 "deep learning", "transformer", "token", "embedding", "fine-tun",
                 "rag", "prompt", "agent", "copilot", "openai", "anthropic"],
    "tech":     ["api", "sdk", "framework", "library", "protocol", "benchmark",
                 "cloud", "database", "infra", "kubernetes", "docker", "saas"],
    "china":    ["中国", "国内", "北京", "上海", "深圳", "政府", "政策", "法规",
                 "监管", "部委", "国务院", "证监会", "央行"],
    "academic": ["paper", "研究", "survey", "benchmark", "dataset", "baseline",
                 "state-of-the-art", "ablation", "experiment", "arxiv"],
    "dev":      ["code", "bug", "fix", "issue", "pr", "commit", "deploy", "ci/cd",
                 "javascript", "python", "rust", "go", "typescript", "react"],
    "legal":    ["法", "合同", "侵权", "诉讼", "仲裁", "判决", "案号", "法院",
                 "律师", "立法", "司法解释"],
    "news":     ["news", "breaking", "announce", "release", "launch", "update",
                 "最新", "发布", "宣布"],
}


def detect_category(query: str) -> str:
    """Detect the content category of a search query using keyword matching."""
    query_lower = query.lower()
    scores: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            scores[category] = score
    if not scores:
        return "general"
    return max(scores, key=scores.get)


def select_sites(query: str, category: str | None = None,
                 explicit_sites: list[str] | None = None,
                 public_only: bool = False) -> list[str]:
    """Select which opencli sites to search based on query and config."""
    if explicit_sites:
        return explicit_sites
    if category is None:
        category = detect_category(query)
    sites = CATEGORY_SITES.get(category, CATEGORY_SITES["general"])
    if public_only:
        # Filter to PUBLIC-strategy sites only (no browser needed)
        public_site_names: set[str] = set()
        for _domain, info in SITE_ROUTING.items():
            if info["strategy"] == "public":
                public_site_names.add(info["site"])
        sites = [s for s in sites if s in public_site_names]
    return sites


def match_site_routing(url: str) -> dict | None:
    """Find the opencli routing info for a given URL by domain matching."""
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return None
    # Exact match first
    if hostname in SITE_ROUTING:
        return SITE_ROUTING[hostname]
    # Subdomain match
    for domain, info in SITE_ROUTING.items():
        if hostname.endswith("." + domain) or hostname == domain.lstrip("www."):
            return info
    return None


def _run_opencli(args: list[str], timeout: int = 30) -> dict | list | str:
    """Run an opencli command and return parsed JSON or raw text."""
    cmd = ["opencli"] + args + ["-f", "json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise BackendError(f"opencli timed out after {timeout}s: {' '.join(cmd)}")
    except FileNotFoundError:
        raise BackendError(
            "opencli not found. Install with: npm install -g @jackwener/opencli"
        )

    # opencli outputs JSON then may append update notices
    stdout = result.stdout.strip()
    if not stdout and result.stderr:
        raise BackendError(f"opencli error: {result.stderr[:500]}")

    # Try to parse as JSON; handle trailing update notices
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        # Find the last ']' or '}' and try parsing up to there
        for end_char in [']', '}']:
            idx = stdout.rfind(end_char)
            if idx > 0:
                try:
                    return json.loads(stdout[:idx + 1])
                except json.JSONDecodeError:
                    continue
        # Return raw text if all parsing fails
        return stdout


class OpenCLIBackend(ResearchBackend):
    """Search backend that routes queries through opencli site adapters."""

    def __init__(self, sites: list[str] | None = None,
                 public_only: bool = False,
                 timeout: int = 30,
                 inter_command_delay: float = 3.0):
        self._configured_sites = sites  # None = auto-routing
        self._public_only = public_only
        self._timeout = timeout
        self._delay = inter_command_delay

    # ── health ───────────────────────────────────────────────────────
    def health(self) -> dict:
        """Check if opencli is installed and list available adapters."""
        try:
            result = subprocess.run(
                ["opencli", "--version"], capture_output=True, text=True, timeout=5,
            )
            version = result.stdout.strip() or result.stderr.strip()
        except FileNotFoundError:
            return {"status": "error", "backend": "opencli",
                    "configured": False, "error": "opencli not installed"}
        except Exception as e:
            return {"status": "error", "backend": "opencli",
                    "configured": False, "error": str(e)}

        # Count available public vs cookie sites
        try:
            raw = _run_opencli(["list"], timeout=10)
            adapters = raw if isinstance(raw, list) else []
            public_count = sum(1 for a in adapters
                              if isinstance(a, dict) and a.get("strategy") == "public")
        except Exception:
            adapters = []
            public_count = 0

        return {
            "status": "ok",
            "backend": "opencli",
            "configured": True,
            "version": version,
            "total_adapters": len(adapters),
            "public_adapters": public_count,
        }

    # ── search ───────────────────────────────────────────────────────
    def search(self, query: str, count: int = 10, **kwargs) -> list[SearchResult]:
        """
        Search across opencli-powered sites.

        Keyword args:
            site: Specific opencli site to search (e.g. 'hackernews')
            sites: List of opencli sites to search
            category: Content category for auto-routing
            public_only: Only use PUBLIC-strategy sites
        """
        explicit_site = kwargs.get("site")
        explicit_sites = kwargs.get("sites", self._configured_sites)

        if isinstance(explicit_sites, str):
            explicit_sites = [s.strip() for s in explicit_sites.split(",") if s.strip()]

        if explicit_site:
            sites_to_search = [explicit_site]
        else:
            category = kwargs.get("category")
            public_only = kwargs.get("public_only", self._public_only)
            sites_to_search = select_sites(query, category, explicit_sites, public_only)

        # Cap count per site
        per_site_count = max(3, count // max(1, len(sites_to_search)))

        all_results: list[SearchResult] = []
        last_search_time = 0.0

        # Search sites sequentially with rate limiting to respect opencli guidelines
        for site in sites_to_search:
            # Rate limiting: at least `_delay` seconds between commands
            elapsed = time.time() - last_search_time
            if elapsed < self._delay:
                time.sleep(self._delay - elapsed)

            try:
                results = self._search_site(site, query, per_site_count)
                all_results.extend(results)
                last_search_time = time.time()
            except BackendError as e:
                # Log but continue with other sites
                print(f"⚠ opencli/{site}: {e}", flush=True)
            except Exception as e:
                print(f"⚠ opencli/{site}: unexpected error: {e}", flush=True)

        # Deduplicate by URL
        seen: set[str] = set()
        deduped: list[SearchResult] = []
        for r in all_results:
            if r.url not in seen:
                seen.add(r.url)
                deduped.append(r)

        return deduped[:count]

    def _search_site(self, site: str, query: str, count: int) -> list[SearchResult]:
        """Search a single opencli site."""
        search_cmd = SITE_COMMANDS.get(site, {}).get("search") or "search"
        try:
            raw = _run_opencli([site, search_cmd, query, "--limit", str(count)],
                              timeout=self._timeout)
        except BackendError:
            raise
        except Exception as e:
            raise BackendError(f"opencli {site} search failed: {e}")

        return self._parse_search_results(site, raw)

    def _parse_search_results(self, site: str, data) -> list[SearchResult]:
        """Parse opencli search output into SearchResult objects."""
        results: list[SearchResult] = []

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("results", data.get("items", []))
        else:
            return results

        if not isinstance(items, list):
            return results

        for item in items:
            if not isinstance(item, dict):
                continue
            # Extract common fields across different opencli adapters
            title = (item.get("title") or item.get("name") or
                    item.get("headline") or "")
            url = (item.get("url") or item.get("link") or
                  item.get("href") or item.get("id", ""))
            snippet = (item.get("snippet") or item.get("description") or
                      item.get("summary") or item.get("content") or
                      item.get("text", ""))
            source = item.get("source", site)
            published = (item.get("published") or item.get("date") or
                        item.get("created_at") or item.get("time", ""))

            # Build synthetic snippets for sites that don't provide them
            if not snippet:
                if site == "hackernews":
                    parts = []
                    score = item.get("score")
                    if score is not None:
                        parts.append(f"{score} points")
                    author = item.get("author")
                    if author:
                        parts.append(f"by {author}")
                    comments = item.get("comments")
                    if comments is not None:
                        parts.append(f"{comments} comments")
                    snippet = ", ".join(parts) if parts else ""
                elif site == "reddit":
                    parts = []
                    score = item.get("score") or item.get("ups")
                    if score is not None:
                        parts.append(f"{score} upvotes")
                    author = item.get("author")
                    if author:
                        parts.append(f"by {author}")
                    subreddit = item.get("subreddit")
                    if subreddit:
                        parts.append(f"r/{subreddit}")
                    snippet = ", ".join(parts) if parts else ""
                elif site == "arxiv":
                    authors = item.get("authors") or item.get("author", "")
                    snippet = f"Authors: {authors}" if authors else ""

            if not title or not url:
                continue

            # Normalize URL: if it's just an ID, prepend site domain
            if not url.startswith("http"):
                domain_map = {
                    "hackernews": f"https://news.ycombinator.com/item?id={url}",
                    "arxiv": f"https://arxiv.org/abs/{url}",
                    "reddit": f"https://reddit.com{url}" if url.startswith("/") else url,
                    "linux-do": f"https://linux.do/t/{url}" if url.isdigit() else url,
                    "v2ex": f"https://v2ex.com/t/{url}" if url.isdigit() else url,
                }
                url = domain_map.get(site, url)

            results.append(SearchResult(
                title=str(title)[:200],
                url=str(url)[:500],
                snippet=str(snippet)[:1000],
                source=f"opencli/{site}",
                published=str(published) if published else None,
            ))

        return results

    # ── scrape ───────────────────────────────────────────────────────
    def scrape(self, url: str, **kwargs) -> ScrapeResult:
        """
        Scrape a URL using the appropriate opencli adapter.

        Detects the site from the URL domain and uses the site's read/download
        command to fetch full content.
        """
        routing = match_site_routing(url)
        if not routing or not routing.get("read"):
            # Fall back to generic web read
            return self._scrape_generic(url, **kwargs)

        site = routing["site"]
        cmd = routing["read"]

        try:
            raw = self._scrape_via_opencli(site, cmd, url, **kwargs)
            return self._parse_scrape_result(site, url, raw)
        except BackendError:
            raise
        except Exception as e:
            # Fall back to generic on failure
            try:
                return self._scrape_generic(url, **kwargs)
            except Exception:
                raise BackendError(f"opencli scrape failed for {url}: {e}")

    def _scrape_via_opencli(self, site: str, cmd: str, url: str, **kwargs) -> dict | str:
        """Execute an opencli read/download command for a URL."""
        # Site-specific argument handling
        if site == "hackernews":
            # Extract item ID from URL: https://news.ycombinator.com/item?id=12345
            from urllib.parse import parse_qs, urlparse as up
            parsed = up(url)
            item_id = parse_qs(parsed.query).get("id", [None])[0]
            if not item_id:
                raise BackendError(f"Cannot extract HN item ID from {url}")
            return _run_opencli([site, cmd, item_id], timeout=self._timeout)

        elif site == "arxiv":
            # Extract paper ID: https://arxiv.org/abs/2301.12345
            paper_id = url.rstrip("/").split("/")[-1]
            # Remove version suffix like v2
            paper_id = re.sub(r"v\d+$", "", paper_id)
            return _run_opencli([site, cmd, paper_id], timeout=self._timeout)

        elif site == "wikipedia":
            # Extract page title from URL
            from urllib.parse import unquote
            parsed = urlparse(url)
            path = parsed.path
            if "/wiki/" in path:
                title = unquote(path.split("/wiki/")[-1])
                return _run_opencli([site, cmd, title], timeout=self._timeout)
            raise BackendError(f"Cannot extract Wikipedia title from {url}")

        elif site == "weixin":
            return _run_opencli([site, cmd, "--url", url,
                                "--download-images=false"],
                              timeout=max(60, self._timeout))

        elif site == "reddit":
            # reddit read takes a post ID
            from urllib.parse import parse_qs, urlparse as up
            parsed = up(url)
            path = parsed.path
            # URL format: /r/subreddit/comments/post_id/title/
            parts = [p for p in path.split("/") if p]
            if "comments" in parts:
                idx = parts.index("comments")
                if idx + 1 < len(parts):
                    post_id = parts[idx + 1]
                    return _run_opencli([site, cmd, post_id], timeout=self._timeout)
            raise BackendError(f"Cannot extract Reddit post ID from {url}")

        elif site in ("twitter",):
            return _run_opencli([site, cmd, url], timeout=self._timeout)

        else:
            # Generic: many opencli read commands accept a URL or ID as positional arg
            return _run_opencli([site, cmd, url], timeout=self._timeout)

    def _scrape_generic(self, url: str, **kwargs) -> ScrapeResult:
        """Generic web scrape using opencli web read."""
        try:
            raw = _run_opencli(["web", "read", url], timeout=self._timeout)
        except BackendError:
            # web read requires cookie; fall back to direct fetch
            import requests
            try:
                resp = requests.get(url, timeout=self._timeout,
                                   headers={"User-Agent": "Veritas/0.1"})
                resp.raise_for_status()
                return ScrapeResult(
                    title="",
                    url=url,
                    markdown=resp.text[:50000],
                    text=resp.text[:50000],
                    page_type="html",
                    content_quality="partial",
                )
            except Exception as e:
                raise BackendError(f"Generic scrape failed for {url}: {e}")

        return self._parse_scrape_result("web", url, raw)

    def _parse_scrape_result(self, site: str, url: str,
                             data) -> ScrapeResult:
        """Parse opencli read output into ScrapeResult."""
        if isinstance(data, dict):
            title = (data.get("title") or data.get("name") or "")
            markdown = (data.get("content") or data.get("markdown") or
                       data.get("text") or data.get("body") or "")
            text = data.get("text") or markdown
            page_type = data.get("page_type", "article")
            content_quality = data.get("content_quality", "full")
            metadata = {k: v for k, v in data.items()
                       if k not in ("title", "content", "markdown", "text",
                                    "body", "page_type", "content_quality")}
        elif isinstance(data, list):
            # List output (e.g., HN comments): convert to markdown
            title = ""
            page_type = "discussion" if site == "hackernews" else "list"
            content_quality = "full"
            metadata = {}
            lines = []
            for item in data:
                if not isinstance(item, dict):
                    lines.append(str(item))
                    continue
                item_type = item.get("type", "")
                author = item.get("author", "")
                score = item.get("score", "")
                text = item.get("text", "")
                indent = "  " * (item_type.count("L") if item_type else 0)
                prefix = f"**{author}**" if author else ""
                if score:
                    prefix += f" ({score} pts)"
                if prefix:
                    prefix += ": "
                lines.append(f"{indent}{prefix}{text}")
            markdown = "\n\n".join(lines)
            text = markdown
        else:
            title = ""
            markdown = str(data)
            text = str(data)
            page_type = "unknown"
            content_quality = "full"
            metadata = {}

        return ScrapeResult(
            title=str(title)[:200],
            url=url,
            markdown=str(markdown)[:50000],
            text=str(text)[:50000],
            page_type=page_type,
            content_quality=content_quality,
            metadata=metadata,
        )
