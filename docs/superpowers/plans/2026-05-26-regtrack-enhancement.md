# Regtrack Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-keyword, region-scoped monitoring, configurable count, and date-range filtering to `research regtrack`.

**Architecture:** Extend `IndustryGroup` data model (keywords list + region), pass `region/since/until` through `search()` → `_search_law()`, use `rh_fg_search` with `dy`/`fbrq_start`/`fbrq_end` when these params are set.

**Tech Stack:** Python 3.12, Yuandian API (`law_vector_search`, `rh_fg_search`), pytest + pytest-mock

---

### Task 1: Backend — `_search_law` region/since/until support

**Files:**
- Modify: `src/research/backends/yuandian.py:72-109`

- [ ] **Step 1: Write failing test for `_search_law` with region**

Read `tests/test_regtrack.py` to find the existing regtrack test file.

Add to `tests/test_backends.py` (create if not exists):

```python
import json
import pytest
from research.backends.yuandian import YuandianBackend


class TestSearchLawRegion:
    def test_search_law_passes_dy_when_region_set(self, mocker):
        be = YuandianBackend(api_key="test-key")
        mock_post = mocker.patch.object(be, "_post")
        mock_post.return_value = {
            "code": 200, "data": [
                {"id": "abc", "fgmc": "广东餐饮规定", "fbbm": "广东省人大",
                 "sxx": "现行有效", "dy": "广东", "fbrq": "2026-01-01"},
            ], "message": "ok", "status": "success",
        }
        results = be._search_law("餐饮", count=10, region="广东")
        # Verify _post was called with rh_fg_search and dy=广东
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "rh_fg_search"
        assert call_kwargs[1]["dy"] == "广东"
        assert len(results) == 1

    def test_search_law_passes_since_until(self, mocker):
        be = YuandianBackend(api_key="test-key")
        mock_post = mocker.patch.object(be, "_post")
        mock_post.return_value = {
            "code": 200, "data": [], "message": "ok", "status": "success",
        }
        be._search_law("餐饮", count=10, since="2026-03-01", until="2026-04-30")
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["fbrq_start"] == "2026-03-01"
        assert call_kwargs[1]["fbrq_end"] == "2026-04-30"

    def test_search_law_vector_when_no_region_or_since(self, mocker):
        be = YuandianBackend(api_key="test-key")
        mock_post = mocker.patch.object(be, "_post")
        mock_post.return_value = {
            "code": 201, "extra": {"fatiao": []}, "msg": "ok",
        }
        be._search_law("餐饮", count=10)
        call_args = mock_post.call_args
        assert call_args[0][0] == "law_vector_search"
        assert call_args[1]["return_num"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src /tmp/research-venv/bin/pytest tests/test_backends.py::TestSearchLawRegion -v
```
Expected: FAIL — `_search_law` doesn't accept `region`/`since`/`until` params yet.

- [ ] **Step 3: Implement `_search_law` with region/since/until**

```python
def _search_law(self, query: str, count: int = 50, region: str = "",
                since: str = "", until: str = "") -> list[SearchResult]:
    if region or since or until:
        body: dict[str, str | int] = {"keyword": query, "top_k": min(count, 50)}
        if region:
            body["dy"] = region
        if since:
            body["fbrq_start"] = since
        if until:
            body["fbrq_end"] = until
        data = self._post("rh_fg_search", body)
        records: list[dict] = data.get("data", []) or []
        if not isinstance(records, list):
            records = []
    else:
        try:
            data = self._post("law_vector_search", {"query": query, "return_num": count})
        except BackendError:
            data = self._post("rh_fg_search", {"keyword": query, "top_k": min(count, 50)})
        records = []
        extra = data.get("extra")
        if isinstance(extra, dict):
            records = extra.get("fatiao", []) or []
        if not records:
            d = data.get("data")
            if isinstance(d, dict):
                for key in ("records", "lst"):
                    recs = d.get(key)
                    if isinstance(recs, list):
                        records = recs
                        break
            elif isinstance(d, list):
                records = d
    results = []
    seen_fgids: set[str] = set()
    for item in (records or []):
        if not isinstance(item, dict):
            continue
        if region or since or until:
            # rh_fg_search results use "id" as fgid
            item_id = item.get("id", "")
            law_name = item.get("fgmc") or item.get("title") or ""
            clause = ""
        else:
            item_id = item.get("fgid") or item.get("id", "")
            law_name = item.get("fgtitle") or item.get("fgmc") or item.get("title") or ""
            if isinstance(law_name, list):
                law_name = law_name[0] if law_name else ""
            clause = item.get("ftnum") or item.get("num", "")
        if item_id in seen_fgids:
            continue
        seen_fgids.add(item_id)
        title = f"{law_name} {clause}".strip()
        if not title:
            continue
        results.append(SearchResult(
            title=title,
            url=f"yuandian://law/detail?id={item_id}",
            snippet=item.get("content") or "",
            source="元典法规",
            published=item.get("implementDate") or item.get("fbrq") or "",
        ))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src /tmp/research-venv/bin/pytest tests/test_backends.py::TestSearchLawRegion -v
```
Expected: PASS

- [ ] **Step 5: Also fix existing `pageSize` bug in fallback path**

The current fallback uses `"pageSize": count` but the API param is `top_k`. This is already fixed in Step 3 code above (using `"top_k": min(count, 50)`).

- [ ] **Step 6: Update `search()` to forward region/since/until**

Read `src/research/backends/yuandian.py:60-70` and update:

```python
def search(self, query: str, count: int = 10, **kwargs) -> list[SearchResult]:
    legal_type = kwargs.get("legal_type", "all")
    region = kwargs.get("region", "")
    since = kwargs.get("since", "")
    until = kwargs.get("until", "")
    results: list[SearchResult] = []
    half = max(1, count // 2) if legal_type == "all" else count

    if legal_type in ("law", "all"):
        results.extend(self._search_law(query, half, region=region, since=since, until=until))
    if legal_type in ("case", "all"):
        results.extend(self._search_case(query, half))
    return results[:count]
```

- [ ] **Step 7: Run all backend tests**

```bash
PYTHONPATH=src /tmp/research-venv/bin/pytest tests/ -v -k "yuandian or backend" 2>&1 | tail -20
```
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add src/research/backends/yuandian.py tests/test_backends.py
git commit -m "feat: add region/since/until params to Yuandian backend _search_law"
```


### Task 2: Data model — `IndustryGroup` keywords list + region

**Files:**
- Modify: `src/research/regtrack.py:31-61`

- [ ] **Step 1: Read current `IndustryGroup` and `RegtrackStore`**

Read `src/research/regtrack.py:31-61`.

- [ ] **Step 2: Update `IndustryGroup` dataclass**

```python
@dataclass
class IndustryGroup:
    keywords: list[str] = field(default_factory=list)
    added: str = ""
    last_checked: str = ""
    region: str = ""
    regulations: list = field(default_factory=list)
```

- [ ] **Step 3: Add `_make_key` helper**

```python
def _make_key(name: str, region: str = "") -> str:
    return name if not region else f"{name}@{region}"
```

- [ ] **Step 4: Update `RegtrackStore.load()` for backward compat**

```python
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
        # backward compat: old single keyword
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
```

- [ ] **Step 5: Update `RegtrackStore.save()`**

```python
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
```

- [ ] **Step 6: Commit**

```bash
git add src/research/regtrack.py
git commit -m "feat: IndustryGroup keywords list + region field with backward compat"
```


### Task 3: Add/Check industry — multi-keyword, region, count, since/until

**Files:**
- Modify: `src/research/regtrack.py:97-212`

- [ ] **Step 1: Read current `add_industry` and `check_industry`**

Read `src/research/regtrack.py:97-212`.

- [ ] **Step 2: Update `add_industry()`**

```python
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


def _extract_id(url: str) -> str:
    return url.split("id=")[-1] if "id=" in url else url
```

- [ ] **Step 3: Update `check_industry()`**

```python
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

    # Phase 2: check existing regulations (skip if since/until specified)
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
```

- [ ] **Step 4: Commit**

```bash
git add src/research/regtrack.py
git commit -m "feat: add/check industry with multi-keyword, region, count, since/until"
```


### Task 4: CLI — new parameters

**Files:**
- Modify: `src/research/cli.py:82-91,283-363`

- [ ] **Step 1: Update parser arguments**

```python
# regtrack
sp = subparsers.add_parser("regtrack", help="法规雷达 — 按行业监控法规变更")
sp.add_argument("action", choices=["add", "remove", "check", "status"],
                help="操作")
sp.add_argument("--industry", help="行业关键词（单关键词模式）")
sp.add_argument("--keywords", help="行业关键词列表，逗号分隔")
sp.add_argument("--region", default="", help="地区限定（如 广东、北京）")
sp.add_argument("--count", type=int, default=50, help="搜索结果数")
sp.add_argument("--since", default="", help="发布日期起始 YYYY-MM-DD")
sp.add_argument("--until", default="", help="发布日期截止 YYYY-MM-DD")
sp.add_argument("--id", dest="reg_id", help="法规 ID")
sp.add_argument("--regtrack-file", default=".research/regtrack.json",
                help="跟踪数据文件路径")
sp.add_argument("--json", action="store_true", help="JSON 输出")
sp.set_defaults(func=cmd_regtrack)
```

- [ ] **Step 2: Write failing test for CLI integration**

Add to `tests/test_regtrack.py`:

```python
class TestRegtrackCliParams:
    def test_check_with_region_and_since(self, mocker, tmp_path):
        from research.cli import cmd_regtrack

        class FakeArgs:
            action = "check"
            industry = "餐饮"
            keywords = None
            region = "广东"
            count = 100
            since = "2026-03"
            until = "2026-04"
            reg_id = None
            regtrack_file = str(tmp_path / "regtrack.json")
            json = False

        # Pre-create a store with 餐饮@广东
        from research.regtrack import RegtrackStore, IndustryGroup, _make_key
        store = RegtrackStore(industries={
            _make_key("餐饮", "广东"): IndustryGroup(
                keywords=["餐饮"], region="广东", added="2026-01-01",
            ),
        })
        store.save(str(tmp_path / "regtrack.json"))

        mocker.patch("research.backends.yuandian.YuandianBackend")
        mock_be = __import__("research.backends.yuandian", fromlist=[""]).YuandianBackend
        mock_be.return_value.search.return_value = []
        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": "test-key"},
        })

        # Should not raise
        cmd_regtrack(FakeArgs())
        assert True
```

- [ ] **Step 3: Run test to verify it fails**

```bash
PYTHONPATH=src /tmp/research-venv/bin/pytest tests/test_regtrack.py::TestRegtrackCliParams -v
```
Expected: FAIL

- [ ] **Step 4: Update `cmd_regtrack()`**

```python
def cmd_regtrack(args):
    from research.regtrack import (
        RegtrackStore, add_industry, check_industry,
        format_status, format_changes, _make_key,
    )
    from research.backends.yuandian import YuandianBackend
    from research.config import load_config
    cfg = load_config()
    api_key = cfg.get("api_keys", {}).get("yuandian_key", "")
    if not api_key:
        print("Error: YUANDIAN_API_KEY not configured")
        return
    backend = YuandianBackend(api_key=api_key)

    # Normalize date format: YYYY-MM → YYYY-MM-01 / YYYY-MM-DD
    def _norm_date(s: str, is_end: bool = False) -> str:
        if not s:
            return ""
        if len(s) == 7:  # YYYY-MM
            if is_end:
                import calendar
                y, m = int(s[:4]), int(s[5:7])
                last = calendar.monthrange(y, m)[1]
                return f"{s}-{last}"
            return f"{s}-01"
        return s

    since = _norm_date(args.since)
    until = _norm_date(args.until, is_end=True)

    # Resolve keywords
    if args.keywords and args.industry:
        print("Error: --keywords 和 --industry 不能同时使用")
        return
    keywords_str = args.keywords or args.industry or ""
    keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
    if not keywords:
        if args.action == "add":
            print("请指定 --keywords 或 --industry")
            return
        # check/status/remove may use stored keywords

    store = RegtrackStore.load(args.regtrack_file)

    if args.action == "add":
        if not keywords:
            print("请指定 --keywords 或 --industry")
            return
        store = add_industry(store, keywords, backend, region=args.region, count=args.count)
        store.save(args.regtrack_file)
        key = _make_key(keywords[0], args.region)
        n = len(store.industries[key].regulations)
        print(f"已注册行业「{key}」, 跟踪 {n} 部法规")
        return

    if args.action == "remove":
        if keywords:
            key = _make_key(keywords[0], args.region)
            if key in store.industries:
                del store.industries[key]
                store.save(args.regtrack_file)
                print(f"已移除行业「{key}」")
            else:
                print(f"行业「{key}」未注册")
        elif args.reg_id:
            removed = False
            for g in store.industries.values():
                before = len(g.regulations)
                g.regulations = [r for r in g.regulations if r.id != args.reg_id]
                if len(g.regulations) < before:
                    removed = True
            if removed:
                store.save(args.regtrack_file)
                print(f"已移除法规 ID: {args.reg_id}")
            else:
                print(f"未找到法规 ID: {args.reg_id}")
        else:
            print("请指定 --industry(--keywords) 或 --id")
        return

    if args.action == "check":
        if keywords:
            keys_to_check = [_make_key(keywords[0], args.region)]
        else:
            keys_to_check = list(store.industries.keys())
        all_changes = []
        for key in keys_to_check:
            if key not in store.industries:
                print(f"行业「{key}」未注册，请先 add")
                continue
            store, changes = check_industry(
                store, key, backend,
                count=args.count, since=since, until=until,
            )
            all_changes.extend(changes)
        store.save(args.regtrack_file)
        print(format_changes(all_changes))
        return

    if args.action == "status":
        key = _make_key(keywords[0], args.region) if keywords else None
        print(format_status(store, key))
        if args.json:
            import json
            print(json.dumps({
                name: {
                    "keywords": g.keywords,
                    "region": g.region,
                    "added": g.added,
                    "last_checked": g.last_checked,
                    "regulation_count": len(g.regulations),
                    "regulations": [
                        {"id": r.id, "name": r.name, "status": r.status}
                        for r in g.regulations
                    ],
                }
                for name, g in store.industries.items()
            }, ensure_ascii=False, indent=2))
        return
```

- [ ] **Step 5: Update `format_status()` to accept key instead of keyword**

```python
def format_status(store: RegtrackStore, key: str | None = None) -> str:
    lines = []
    for name, group in store.industries.items():
        if key and name != key:
            continue
        total = len(group.regulations)
        region_tag = f"@{group.region}" if group.region else ""
        lines.append(f"行业: {name} ({total} 部法规)  最后检查: {group.last_checked or '从未'}")
        for reg in group.regulations:
            status_icon = "✓" if reg.status == "现行有效" else "✗"
            lines.append(f"  {status_icon} {reg.name} — {reg.status}")
    return "\n".join(lines)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
PYTHONPATH=src /tmp/research-venv/bin/pytest tests/test_regtrack.py -v 2>&1 | tail -25
```
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/research/cli.py src/research/regtrack.py
git commit -m "feat: regtrack CLI --keywords/--region/--count/--since/--until"
```


### Task 5: Tests — full coverage

**Files:**
- Modify: `tests/test_regtrack.py`

- [ ] **Step 1: Add migration test**

```python
class TestIndustryGroupMigration:
    def test_load_old_format(self, tmp_path):
        """Old JSON with keyword: str loads as keywords=[keyword], region=''"""
        p = tmp_path / "old.json"
        p.write_text(json.dumps({
            "industries": {
                "餐饮": {
                    "keyword": "餐饮",
                    "added": "2026-01-01",
                    "regulations": [],
                }
            }
        }))
        store = RegtrackStore.load(str(p))
        assert "餐饮" in store.industries
        g = store.industries["餐饮"]
        assert g.keywords == ["餐饮"]
        assert g.region == ""

    def test_save_and_load_new_format(self, tmp_path):
        p = tmp_path / "new.json"
        store = RegtrackStore(industries={
            _make_key("餐饮", "广东"): IndustryGroup(
                keywords=["餐饮", "食品安全"],
                region="广东",
                added="2026-01-01",
            ),
        })
        store.save(str(p))
        loaded = RegtrackStore.load(str(p))
        key = _make_key("餐饮", "广东")
        assert key in loaded.industries
        g = loaded.industries[key]
        assert g.keywords == ["餐饮", "食品安全"]
        assert g.region == "广东"
```

- [ ] **Step 2: Add `_make_key` / `_extract_id` tests**

```python
class TestHelpers:
    def test_make_key_no_region(self):
        from research.regtrack import _make_key
        assert _make_key("餐饮") == "餐饮"
        assert _make_key("餐饮", "广东") == "餐饮@广东"

    def test_extract_id(self):
        from research.regtrack import _extract_id
        assert _extract_id("yuandian://law/detail?id=abc123") == "abc123"
        assert _extract_id("no-id") == "no-id"
```

- [ ] **Step 3: Add `add_industry` multi-keyword test**

```python
class TestAddIndustryMultiKeyword:
    def test_add_with_two_keywords_dedup(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.side_effect = [
            # First search for "餐饮"
            [mocker.Mock(url="yuandian://law/detail?id=l1", title="法A"),
             mocker.Mock(url="yuandian://law/detail?id=l2", title="法B")],
            # Second search for "食品安全"
            [mocker.Mock(url="yuandian://law/detail?id=l2", title="法B"),
             mocker.Mock(url="yuandian://law/detail?id=l3", title="法C")],
        ]
        def scrape_side(url):
            rid = url.split("id=")[-1]
            data = {
                "l1": {"fgmc": "法A", "content": "...", "sxx": "现行有效"},
                "l2": {"fgmc": "法B", "content": "...", "sxx": "现行有效"},
                "l3": {"fgmc": "法C", "content": "...", "sxx": "现行有效"},
            }
            return mocker.Mock(markdown=json.dumps(data[rid]))
        mock_backend.scrape.side_effect = scrape_side

        store = RegtrackStore()
        store = add_industry(store, ["餐饮", "食品安全"], mock_backend)
        key = _make_key("餐饮")
        assert key in store.industries
        assert len(store.industries[key].regulations) == 3  # l1, l2, l3 deduped
```

- [ ] **Step 4: Add region search test**

```python
class TestAddIndustryWithRegion:
    def test_add_with_region_passes_dy(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=g1", title="广东餐饮规定"),
        ]
        mock_backend.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "广东餐饮规定", "content": "...", "sxx": "现行有效"})
        )
        store = RegtrackStore()
        store = add_industry(store, ["餐饮"], mock_backend, region="广东")
        key = _make_key("餐饮", "广东")
        assert key in store.industries
        g = store.industries[key]
        assert g.region == "广东"
        assert len(g.regulations) == 1

        # Verify search was called with region=广东
        mock_backend.search.assert_called_once_with(
            "餐饮", count=50, legal_type="law", region="广东"
        )
```

- [ ] **Step 5: Add `check_industry` with since/until test**

```python
class TestCheckIndustrySince:
    def test_check_with_since_passes_fbrq(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=n1", title="新法规"),
        ]
        mock_backend.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "新法规", "content": "...", "sxx": "现行有效"})
        )
        store = RegtrackStore(industries={
            "餐饮": IndustryGroup(keywords=["餐饮"], added="2026-01-01"),
        })
        store, changes = check_industry(store, "餐饮", mock_backend, since="2026-03-01")
        assert any(c.change_type == "new" for c in changes)
        # Verify search was called with since
        mock_backend.search.assert_called_once_with(
            "餐饮", count=50, legal_type="law", region="", since="2026-03-01", until=""
        )
```

- [ ] **Step 6: Run all regtrack tests**

```bash
PYTHONPATH=src /tmp/research-venv/bin/pytest tests/test_regtrack.py -v
```
Expected: 20+ tests all pass

- [ ] **Step 7: Run full test suite**

```bash
PYTHONPATH=src /tmp/research-venv/bin/pytest tests/ -v 2>&1 | tail -10
```
Expected: 125+ tests all pass

- [ ] **Step 8: Commit**

```bash
git add tests/test_regtrack.py
git commit -m "test: regtrack multi-keyword, region, since/until tests"
```
