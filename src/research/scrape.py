import json
from pathlib import Path
from datetime import datetime
from research.backends.yuandian import YuandianBackend
from research.backends.opencli import OpenCLIBackend
from research.config import load_config

RUN_DIR_BASE = ".research/runs"


def _ensure_run_dir(run_dir: str | None, base: str | None = None) -> Path:
    if run_dir:
        path = Path(run_dir)
    else:
        date_str = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        path = Path(base or RUN_DIR_BASE) / f"scrape-{date_str}"
        print(f"Run directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scrape_yuandian(url: str, backend: YuandianBackend) -> dict:
    sr = backend.scrape(url)
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


def _scrape_opencli(url: str, backend: OpenCLIBackend) -> dict:
    sr = backend.scrape(url)
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


def run_scrape(args) -> dict:
    config = load_config()
    urls = args.url
    yuandian_urls = [u for u in urls if u.startswith("yuandian://")]
    non_yd_urls = [u for u in urls if not u.startswith("yuandian://")]

    run_dir = _ensure_run_dir(args.run_dir, config.get("run_dir", {}).get("base", RUN_DIR_BASE))
    results = {}
    scrape_index = []
    file_idx = 0

    if yuandian_urls:
        yd = YuandianBackend()
        for url in yuandian_urls:
            try:
                result_data = _scrape_yuandian(url, yd)
            except Exception as e:
                result_data = {
                    "url": url, "status": 500, "title": "", "markdown": "",
                    "text": "", "pageType": "error", "contentQuality": "empty",
                    "blockedReason": str(e),
                }
            results[url] = result_data
            file_idx += 1
            fname = f"scrape-{file_idx}.json"
            (run_dir / fname).write_text(json.dumps(result_data, ensure_ascii=False, indent=2))
            scrape_index.append({"url": url, "file": fname})

    if non_yd_urls:
        backend = OpenCLIBackend(
            timeout=getattr(args, "timeout", None) or config.get("opencli", {}).get("timeout", 30),
        )
        for url in non_yd_urls:
            try:
                result_data = _scrape_opencli(url, backend)
            except Exception as e:
                result_data = {
                    "url": url, "status": 500, "title": "", "markdown": "",
                    "text": "", "pageType": "error", "contentQuality": "empty",
                    "blockedReason": str(e),
                }
            results[url] = result_data
            file_idx += 1
            fname = f"scrape-{file_idx}.json"
            (run_dir / fname).write_text(json.dumps(result_data, ensure_ascii=False, indent=2))
            scrape_index.append({"url": url, "file": fname})

    manifest_path = run_dir / "scrape-manifest.tsv"
    manifest_path.write_text("url\tfile\n" + "\n".join(
        f"{e['url']}\t{e['file']}" for e in scrape_index
    ))

    result = results.get(urls[0], {"url": urls[0], "status": 200})
    if len(urls) > 1:
        result = {
            "count": len(results),
            "results": [results[url] for url in urls if url in results],
            "manifest": str(manifest_path),
        }

    if args.json:
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if getattr(args, "output", None):
            Path(args.output).write_text(output)
        else:
            print(output)

    return result
