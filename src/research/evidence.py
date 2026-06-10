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
