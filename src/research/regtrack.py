import hashlib
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path


REGRACK_FILE = Path(".research/regtrack.json")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_key(name: str, region: str = "") -> str:
    return name if not region else f"{name}@{region}"


@dataclass
class RegulationSnapshot:
    content_hash: str
    content: str
    taken_at: str


@dataclass
class TrackedRegulation:
    id: str
    name: str
    status: str
    snapshot: RegulationSnapshot | None = None


@dataclass
class IndustryGroup:
    keywords: list[str] = field(default_factory=list)
    added: str = ""
    last_checked: str = ""
    region: str = ""
    regulations: list = field(default_factory=list)


@dataclass
class RegtrackStore:
    industries: dict[str, IndustryGroup] = field(default_factory=dict)

    @staticmethod
    def load(path: str | Path | None = None) -> "RegtrackStore":
        p = Path(path) if path else REGRACK_FILE
        if not p.exists():
            return RegtrackStore()
        raw = json.loads(p.read_text())
        industries = {}
        for name, g in raw.get("industries", {}).items():
            regs = [TrackedRegulation(**r) for r in g.get("regulations", [])]
            for r in regs:
                if r.snapshot:
                    r.snapshot = RegulationSnapshot(**r.snapshot)
            old_kw = g.get("keyword", "")
            keywords = g.get("keywords", [old_kw] if old_kw else [])
            industries[name] = IndustryGroup(
                keywords=keywords,
                added=g.get("added", ""),
                last_checked=g.get("last_checked", ""),
                region=g.get("region", ""),
                regulations=regs,
            )
        return RegtrackStore(industries=industries)

    def save(self, path: str | Path | None = None) -> None:
        p = Path(path) if path else REGRACK_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            "industries": {
                name: {
                    "keywords": g.keywords,
                    "added": g.added,
                    "last_checked": g.last_checked,
                    "region": g.region,
                    "regulations": [
                        {**asdict(r), "snapshot": asdict(r.snapshot) if r.snapshot else None}
                        for r in g.regulations
                    ],
                }
                for name, g in self.industries.items()
            }
        }
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=2))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_id(url: str) -> str:
    return url.split("id=")[-1] if "id=" in url else url


def _fetch_detail(backend, rid: str) -> dict | None:
    try:
        result = backend.scrape(f"yuandian://law/detail?id={rid}")
        import json as _json
        raw = _json.loads(result.markdown)
        return raw
    except Exception:
        return None


def add_industry(
    store: RegtrackStore,
    keywords: list[str],
    backend: "YuandianBackend",
    region: str = "",
    count: int = 50,
) -> RegtrackStore:
    name = keywords[0]
    key = _make_key(name, region)
    if key not in store.industries:
        store.industries[key] = IndustryGroup(
            keywords=keywords,
            added=_now(),
            region=region,
        )
    group = store.industries[key]
    existing_ids = {r.id for r in group.regulations}
    for kw in keywords:
        results = backend.search(kw, count=count, legal_type="law", region=region)
        for r in results:
            rid = _extract_id(r.url)
            if rid and rid not in existing_ids:
                detail = _fetch_detail(backend, rid)
                if detail:
                    group.regulations.append(TrackedRegulation(
                        id=rid,
                        name=detail.get("fgmc", r.title),
                        status=detail.get("sxx", "现行有效"),
                        snapshot=RegulationSnapshot(
                            content_hash=content_hash(detail.get("content", "")),
                            content=detail.get("content", ""),
                            taken_at=_now(),
                        ),
                    ))
                    existing_ids.add(rid)
    group.last_checked = _now()
    return store


@dataclass
class RegulationChange:
    id: str
    name: str
    change_type: str  # new | changed | expired | unchanged
    diff: str = ""
    detail: str = ""


def check_industry(
    store: RegtrackStore,
    key: str,
    backend: "YuandianBackend",
    count: int = 50,
    since: str = "",
    until: str = "",
) -> tuple[RegtrackStore, list[RegulationChange]]:
    group = store.industries.get(key)
    if not group:
        return store, []

    changes: list[RegulationChange] = []
    existing = {r.id: r for r in group.regulations}

    # Phase 1: discover new laws
    seen_ids: set[str] = set()
    for kw in group.keywords:
        results = backend.search(kw, count=count, legal_type="law",
                                 region=group.region, since=since, until=until)
        for r in results:
            rid = _extract_id(r.url)
            if not rid or rid in seen_ids:
                continue
            seen_ids.add(rid)
            if rid not in existing:
                detail = _fetch_detail(backend, rid)
                if detail:
                    group.regulations.append(TrackedRegulation(
                        id=rid,
                        name=detail.get("fgmc", r.title),
                        status=detail.get("sxx", "现行有效"),
                        snapshot=RegulationSnapshot(
                            content_hash=content_hash(detail.get("content", "")),
                            content=detail.get("content", ""),
                            taken_at=_now(),
                        ),
                    ))
                    changes.append(RegulationChange(
                        id=rid, name=detail.get("fgmc", r.title),
                        change_type="new",
                    ))

    # Phase 2: check existing (skip if date-filtering)
    if not since and not until:
        for reg in group.regulations:
            detail = _fetch_detail(backend, reg.id)
            if not detail:
                continue
            new_status = detail.get("sxx", "现行有效")
            new_content = detail.get("content", "")
            new_hash = content_hash(new_content)

            if new_status != "现行有效" and reg.status == "现行有效":
                changes.append(RegulationChange(
                    id=reg.id, name=reg.name,
                    change_type="expired", detail=f"状态: {new_status}",
                ))
            elif reg.snapshot and new_hash != reg.snapshot.content_hash:
                diff_text = _compute_diff(reg.snapshot.content, new_content, reg.name)
                changes.append(RegulationChange(
                    id=reg.id, name=reg.name,
                    change_type="changed",
                    diff=diff_text,
                ))
            else:
                changes.append(RegulationChange(
                    id=reg.id, name=reg.name,
                    change_type="unchanged",
                ))

            reg.status = new_status
            reg.snapshot = RegulationSnapshot(
                content_hash=new_hash,
                content=new_content,
                taken_at=_now(),
            )

    group.last_checked = _now()
    return store, changes


def _compute_diff(old: str, new: str, name: str) -> str:
    lines = list(unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"{name} (旧)",
        tofile=f"{name} (新)",
        lineterm="",
    ))
    return "".join(lines[:100])


def format_status(store: RegtrackStore, keyword: str | None = None) -> str:
    lines = []
    for name, group in store.industries.items():
        if keyword and name != keyword:
            continue
        total = len(group.regulations)
        lines.append(f"行业: {name} ({total} 部法规)")
        for reg in group.regulations:
            status_icon = "✓" if reg.status == "现行有效" else "✗"
            lines.append(f"  {status_icon} {reg.name} — {reg.status}")
    return "\n".join(lines)


def format_changes(changes: list[RegulationChange]) -> str:
    lines = []
    for c in changes:
        if c.change_type == "new":
            lines.append(f"  + {c.name} — 新增")
        elif c.change_type == "expired":
            lines.append(f"  ✗ {c.name} — {c.detail or '已失效'}")
        elif c.change_type == "changed":
            lines.append(f"  ! {c.name} — 内容已变更")
            if c.diff:
                for dline in c.diff.split("\n"):
                    lines.append(f"    {dline}")
        else:
            lines.append(f"  ✓ {c.name} — 正常")
    return "\n".join(lines)
