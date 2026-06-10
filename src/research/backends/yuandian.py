import json
from dataclasses import dataclass
from research.backends.protocol import (
    ResearchBackend, SearchResult, ScrapeResult, BackendError,
)
from research.config import load_config

# 元典开放平台 API 后端
# API_BASE 可通过配置文件 [api_endpoints] yuandian 覆盖。
# 未提供时使用公开端点 https://open.chineselaw.com/open
def _get_api_base() -> str:
    cfg = load_config()
    override = cfg.get("api_endpoints", {}).get("yuandian", "")
    if override:
        return override.rstrip("/")
    return "https://open.chineselaw.com/open"

API_BASE = _get_api_base()


class YuandianBackend(ResearchBackend):
    def __init__(self, api_key: str | None = None):
        if not api_key:
            cfg = load_config()
            api_key = cfg.get("api_keys", {}).get("yuandian_key", "")
        self.api_key = api_key or ""
        self._session = None
        self._headers = {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _post(self, route: str, body: dict) -> dict:
        import requests as req
        try:
            resp = req.post(
                f"{API_BASE}/{route}",
                headers=self._headers,
                json=body,
                timeout=90,
            )
        except req.RequestException as e:
            raise BackendError(f"Yuandian API error: {e}")
        if resp.status_code != 200:
            raise BackendError(f"Yuandian API HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if not isinstance(data, dict):
            raise BackendError(f"Yuandian API returned non-object: {type(data).__name__}")
        code = data.get("code")
        if code is not None and code not in (200, 201, 0):
            raise BackendError(f"Yuandian API biz error: {data.get('message', 'unknown')}")
        return data

    def _get(self, route: str, params: dict | None = None) -> dict:
        import requests as req
        try:
            resp = req.get(
                f"{API_BASE}/{route}",
                headers=self._headers,
                params=params,
                timeout=30,
            )
        except req.RequestException as e:
            raise BackendError(f"Yuandian API error: {e}")
        if resp.status_code != 200:
            raise BackendError(f"Yuandian API HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

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
            use_fgid = False
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
            use_fgid = True

        seen: set[str] = set()
        results = []
        for item in (records or []):
            if not isinstance(item, dict):
                continue
            if use_fgid:
                item_id = item.get("fgid") or item.get("id", "")
                law_name = item.get("fgtitle") or item.get("fgmc") or item.get("title") or ""
                if isinstance(law_name, list):
                    law_name = law_name[0] if law_name else ""
                clause = item.get("ftnum") or item.get("num", "")
            else:
                item_id = item.get("id", "")
                law_name = item.get("fgmc") or item.get("title") or ""
                clause = ""
            if item_id in seen:
                continue
            seen.add(item_id)
            title = f"{law_name} {clause}".strip()
            if not title:
                title = item.get("title", "") or ""
            results.append(SearchResult(
                title=title,
                url=f"yuandian://law/detail?id={item_id}",
                snippet=item.get("content") or "",
                source="元典法规",
                published=item.get("implementDate") or item.get("fbrq") or "",
            ))
        return results

    def _search_case(self, query: str, count: int) -> list[SearchResult]:
        try:
            data = self._post("case_vector_search", {"query": query, "top_k": count})
        except BackendError:
            data = self._post("rh_ptal_search", {"keyword": query, "pageSize": count})
        records: list[dict] = []
        extra = data.get("extra")
        if isinstance(extra, dict):
            for key in ("wenshu", "fatiao"):
                recs = extra.get(key)
                if isinstance(recs, list):
                    records = recs
                    break
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
        for item in (records or []):
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("ajmc") or item.get("ah", "") or ""
            case_id = item.get("scid") or item.get("id", "")
            results.append(SearchResult(
                title=title,
                url=f"yuandian://case/detail?type=ptal&id={case_id}",
                snippet=item.get("content") or item.get("wenshuContent", "") or item.get("aiSummary", "") or "",
                source="元典案例",
                published=item.get("judgmentDate") or item.get("cpfjRq"),
            ))
        return results

    def scrape(self, url_or_id: str, **kwargs) -> ScrapeResult:
        if url_or_id.startswith("yuandian://law/detail"):
            import urllib.parse
            params = urllib.parse.parse_qs(url_or_id.split("?")[1])
            fid = params.get("id", [""])[0]
            data = self._post("rh_fg_detail", {"id": fid})
        elif url_or_id.startswith("yuandian://case/detail"):
            import urllib.parse
            params = urllib.parse.parse_qs(url_or_id.split("?")[1])
            ctype = params.get("type", ["ptal"])[0]
            cid = params.get("id", [""])[0]
            data = self._get("rh_case_details", {"type": ctype, "id": cid})
        else:
            raise BackendError(f"Unsupported yuandian URL: {url_or_id}")

        raw = data.get("data", data)
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        title = raw.get("fgmc") or raw.get("name") or raw.get("title") or ""
        markdown = json.dumps(raw, ensure_ascii=False, indent=2)
        return ScrapeResult(
            title=title,
            url=url_or_id,
            markdown=markdown,
            text=markdown,
            page_type="legal",
            content_quality="full",
        )

    def health(self) -> dict:
        return {
            "status": "ok" if self.api_key else "no_api_key",
            "backend": "yuandian",
            "configured": bool(self.api_key),
        }

    def detect_hallucinations(self, text: str) -> dict:
        """Call hall_detect API to check legal citations in text."""
        import time
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                data = self._post("hall_detect", {"text": text})
                return data
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        raise last_error
