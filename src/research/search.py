import json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from research.backends.protocol import SearchResult
from research.config import load_config

RUN_DIR_BASE = ".research/runs"


def build_run_dir(run_dir: str | None, topic: str = "research", base: str | None = None) -> Path:
    if run_dir:
        return Path(run_dir)
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic)[:40]
    path = Path(base or RUN_DIR_BASE) / f"{date_str}-{safe_topic}"
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


def _make_backend(args):
    """Instantiate the correct backend based on CLI args and config."""
    backend_name = getattr(args, "backend", "opencli")
    config = load_config()

    if backend_name == "yuandian":
        from research.backends.yuandian import YuandianBackend
        api_key = config.get("api_keys", {}).get("yuandian_key", "")
        if not api_key:
            print("⚠ Yuandian API key not configured (set via: research config set api_keys.yuandian_key <key>)")
            print("   Searching without API key may be rate-limited or fail.")
        return YuandianBackend(api_key=api_key)

    # Default: opencli
    from research.backends.opencli import OpenCLIBackend
    opencli_cfg = config.get("opencli", {})
    explicit_sites = getattr(args, "opencli_sites", None) or opencli_cfg.get("default_sites", "")
    public_only_arg = getattr(args, "opencli_public_only", None)
    public_only = opencli_cfg.get("public_only", False) if public_only_arg is None else public_only_arg
    timeout_arg = getattr(args, "opencli_timeout", None)
    timeout = opencli_cfg.get("timeout", 30) if timeout_arg is None else timeout_arg
    delay = opencli_cfg.get("inter_command_delay", 3.0)
    return OpenCLIBackend(
        sites=[s.strip() for s in explicit_sites.split(",") if s.strip()] if explicit_sites else None,
        public_only=public_only,
        timeout=timeout,
        inter_command_delay=delay,
    )


def _result_to_json(r: SearchResult) -> dict:
    return {
        "title": r.title,
        "url": r.url,
        "snippet": r.snippet,
        "source": r.source,
        "published": r.published,
    }


def _scrape_to_json(sr) -> dict:
    return {
        "url": sr.url,
        "status": 200,
        "title": sr.title,
        "markdown": sr.markdown,
        "text": sr.text,
        "pageType": sr.page_type,
        "contentQuality": sr.content_quality,
        "blockedReason": "",
    }


def _write_scrapes(run_dir: Path, backend, results: list[SearchResult]) -> list[dict]:
    scrape_index = []
    for i, r in enumerate(results, 1):
        try:
            result_data = _scrape_to_json(backend.scrape(r.url))
        except Exception as e:
            result_data = {
                "url": r.url,
                "status": 500,
                "title": "",
                "markdown": "",
                "text": "",
                "pageType": "error",
                "contentQuality": "empty",
                "blockedReason": str(e),
            }
        fname = f"scrape-{i}.json"
        (run_dir / fname).write_text(json.dumps(result_data, ensure_ascii=False, indent=2))
        scrape_index.append({"url": r.url, "file": fname})

    if scrape_index:
        (run_dir / "scrape-manifest.tsv").write_text("url\tfile\n" + "\n".join(
            f"{e['url']}\t{e['file']}" for e in scrape_index
        ))
    return scrape_index


def run_search(args) -> dict:
    config = load_config()
    backend = _make_backend(args)
    run_dir = build_run_dir(args.run_dir, args.query[0], config.get("run_dir", {}).get("base", RUN_DIR_BASE))

    legal_type = getattr(args, "legal_type", "all")
    backend_name = getattr(args, "backend", "opencli")
    limit = getattr(args, "limit", None) or config.get("search", {}).get("default_limit", 10)
    max_concurrent = config.get("search", {}).get("max_concurrent", 4)

    # Build search kwargs based on backend type
    search_kwargs = {}
    if backend_name == "opencli":
        opencli_sites = getattr(args, "opencli_sites", None)
        if opencli_sites:
            search_kwargs["sites"] = [s.strip() for s in opencli_sites.split(",") if s.strip()]
        public_only_arg = getattr(args, "opencli_public_only", None)
        if public_only_arg is not None:
            search_kwargs["public_only"] = public_only_arg
    else:
        search_kwargs["legal_type"] = legal_type
        search_kwargs["region"] = getattr(args, "region", "")
        search_kwargs["since"] = getattr(args, "since", "")
        search_kwargs["until"] = getattr(args, "until", "")

    all_results: list[SearchResult] = []
    results_by_query: dict[str, list[SearchResult]] = {}
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_map = {
            executor.submit(backend.search, q, limit, **search_kwargs): q
            for q in args.query
        }
        for future in as_completed(future_map):
            q = future_map[future]
            try:
                results = future.result()
                results_by_query[q] = dedup_results(results)
                all_results.extend(results)
            except Exception as e:
                results_by_query[q] = []
                print(f"Search failed for '{q}': {e}")

    all_results = dedup_results(all_results)

    run_dir.mkdir(parents=True, exist_ok=True)
    for i, q in enumerate(args.query):
        chunk = results_by_query.get(q, [])[:limit]
        out_path = run_dir / f"query-{i + 1}.json"
        out_path.write_text(json.dumps({
            "query": q,
            "count": len(chunk),
            "results": [_result_to_json(r) for r in chunk],
            "provider": backend.__class__.__name__.replace("Backend", ""),
        }, ensure_ascii=False, indent=2))

    scrape_index = []
    if getattr(args, "scrape", False) and all_results:
        scrape_index = _write_scrapes(run_dir, backend, all_results)

    backend_name = backend.__class__.__name__.replace("Backend", "")
    result = {
        "query": args.query,
        "count": len(all_results),
        "results": [_result_to_json(r) for r in all_results],
        "provider": backend_name,
        "run_dir": str(run_dir),
    }
    if scrape_index:
        result["scraped"] = scrape_index

    if args.json:
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(output)
        else:
            print(output)

    return result
