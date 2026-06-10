import json
import pytest
from pathlib import Path
from research.regtrack import (
    RegtrackStore, IndustryGroup, TrackedRegulation, RegulationSnapshot,
    content_hash, add_industry, check_industry,
    RegulationChange, format_status, format_changes,
    _make_key,
)


class TestRegtrackStore:
    def test_load_empty_when_no_file(self, tmp_path):
        store = RegtrackStore.load(str(tmp_path / "nonexistent.json"))
        assert store.industries == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        p = tmp_path / "regtrack.json"
        store = RegtrackStore(industries={
            "测试": IndustryGroup(keywords=["测试"], added="2026-01-01", regulations=[
                TrackedRegulation(id="1", name="法A", status="现行有效",
                                  snapshot=RegulationSnapshot(
                                      content_hash="abc", content="...", taken_at="2026-01-01")),
            ]),
        })
        store.save(str(p))
        loaded = RegtrackStore.load(str(p))
        assert "测试" in loaded.industries
        assert loaded.industries["测试"].regulations[0].name == "法A"
        assert loaded.industries["测试"].regulations[0].snapshot.content_hash == "abc"

    def test_save_creates_parent_dir(self, tmp_path):
        p = tmp_path / "sub" / "regtrack.json"
        store = RegtrackStore()
        store.save(str(p))
        assert p.exists()


class TestContentHash:
    def test_consistent(self):
        assert content_hash("hello") == content_hash("hello")

    def test_different(self):
        assert content_hash("hello") != content_hash("world")

    def test_empty(self):
        h = content_hash("")
        assert isinstance(h, str) and len(h) == 64


class TestAddIndustry:
    def test_add_new_industry(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=l1", title="数据安全法"),
        ]
        mock_backend.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "数据安全法", "content": "全文...", "sxx": "现行有效"})
        )
        store = RegtrackStore()
        store = add_industry(store, ["数据安全"], mock_backend)
        assert "数据安全" in store.industries
        assert len(store.industries["数据安全"].regulations) == 1
        assert store.industries["数据安全"].regulations[0].name == "数据安全法"

    def test_add_industry_dedup(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=l1", title="法A"),
        ]
        mock_backend.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "法A", "content": "...", "sxx": "现行有效"})
        )
        store = RegtrackStore(industries={
            "测试": IndustryGroup(keywords=["测试"], added="2026-01-01", regulations=[
                TrackedRegulation(id="l1", name="法A", status="现行有效"),
            ]),
        })
        store = add_industry(store, ["测试"], mock_backend)
        assert len(store.industries["测试"].regulations) == 1

    def test_add_industry_skip_scrape_failure(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=l_fail", title="法X"),
        ]
        mock_backend.scrape.side_effect = Exception("API error")
        store = RegtrackStore()
        store = add_industry(store, ["测试"], mock_backend)
        assert len(store.industries["测试"].regulations) == 0


class TestCheckIndustry:
    def test_detect_new_law(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=l1", title="法A"),
            mocker.Mock(url="yuandian://law/detail?id=l2", title="法B"),
        ]

        def scrape_side_effect(url):
            rid = url.split("id=")[-1]
            data = {
                "l1": {"fgmc": "法A", "content": "旧内容", "sxx": "现行有效"},
                "l2": {"fgmc": "法B", "content": "新内容", "sxx": "现行有效"},
            }
            return mocker.Mock(markdown=json.dumps(data[rid]))
        mock_backend.scrape.side_effect = scrape_side_effect

        store = RegtrackStore(industries={
            "测试": IndustryGroup(keywords=["测试"], added="2026-01-01", regulations=[
                TrackedRegulation(id="l1", name="法A", status="现行有效",
                                  snapshot=RegulationSnapshot(
                                      content_hash=content_hash("旧内容"),
                                      content="旧内容", taken_at="2026-01-01")),
            ]),
        })
        store, changes = check_industry(store, _make_key("测试"), mock_backend)
        change_types = {c.change_type for c in changes}
        assert "new" in change_types
        assert "unchanged" in change_types
        assert len(store.industries["测试"].regulations) == 2

    def test_detect_content_change(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=l1", title="法A"),
        ]
        mock_backend.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "法A", "content": "新内容!!!", "sxx": "现行有效"})
        )
        store = RegtrackStore(industries={
            "测试": IndustryGroup(keywords=["测试"], added="2026-01-01", regulations=[
                TrackedRegulation(id="l1", name="法A", status="现行有效",
                                  snapshot=RegulationSnapshot(
                                      content_hash=content_hash("旧内容"),
                                      content="旧内容", taken_at="2026-01-01")),
            ]),
        })
        store, changes = check_industry(store, _make_key("测试"), mock_backend)
        assert any(c.change_type == "changed" for c in changes)
        changed = [c for c in changes if c.change_type == "changed"][0]
        assert "新内容" in changed.diff

    def test_detect_expired(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=l1", title="法A"),
        ]
        mock_backend.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "法A", "content": "内容", "sxx": "已失效"})
        )
        store = RegtrackStore(industries={
            "测试": IndustryGroup(keywords=["测试"], added="2026-01-01", regulations=[
                TrackedRegulation(id="l1", name="法A", status="现行有效",
                                  snapshot=RegulationSnapshot(
                                      content_hash=content_hash("内容"),
                                      content="内容", taken_at="2026-01-01")),
            ]),
        })
        store, changes = check_industry(store, _make_key("测试"), mock_backend)
        assert any(c.change_type == "expired" for c in changes)

    def test_no_change(self, mocker):
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=l1", title="法A"),
        ]
        mock_backend.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "法A", "content": "内容", "sxx": "现行有效"})
        )
        store = RegtrackStore(industries={
            "测试": IndustryGroup(keywords=["测试"], added="2026-01-01", regulations=[
                TrackedRegulation(id="l1", name="法A", status="现行有效",
                                  snapshot=RegulationSnapshot(
                                      content_hash=content_hash("内容"),
                                      content="内容", taken_at="2026-01-01")),
            ]),
        })
        store, changes = check_industry(store, _make_key("测试"), mock_backend)
        assert all(c.change_type == "unchanged" for c in changes)

    def test_check_nonexistent_industry(self, mocker):
        mock_backend = mocker.Mock()
        store = RegtrackStore()
        store, changes = check_industry(store, _make_key("不存在"), mock_backend)
        assert changes == []


class TestFormatting:
    def test_format_status(self):
        store = RegtrackStore(industries={
            "测试": IndustryGroup(keywords=["测试"], added="2026-01-01", regulations=[
                TrackedRegulation(id="1", name="法A", status="现行有效"),
                TrackedRegulation(id="2", name="法B", status="已失效"),
            ]),
        })
        out = format_status(store)
        assert "测试" in out
        assert "法A" in out
        assert "✓" in out
        assert "✗" in out

    def test_format_status_filter(self):
        store = RegtrackStore(industries={
            "A": IndustryGroup(keywords=["A"], added="", regulations=[
                TrackedRegulation(id="1", name="法1", status="现行有效"),
            ]),
            "B": IndustryGroup(keywords=["B"], added="", regulations=[
                TrackedRegulation(id="2", name="法2", status="现行有效"),
            ]),
        })
        out = format_status(store, keyword="A")
        assert "法1" in out
        assert "法2" not in out

    def test_format_changes(self):
        changes = [
            RegulationChange(id="1", name="法A", change_type="new"),
            RegulationChange(id="2", name="法B", change_type="expired", detail="已失效"),
            RegulationChange(id="3", name="法C", change_type="changed", diff="@@ -1 +1 @@\n-旧\n+新"),
            RegulationChange(id="4", name="法D", change_type="unchanged"),
        ]
        out = format_changes(changes)
        assert "新增" in out
        assert "已失效" in out
        assert "内容已变更" in out
        assert "正常" in out


class TestIndustryGroupMigration:
    def test_load_old_format(self, tmp_path):
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
        from research.regtrack import _make_key
        key = _make_key("餐饮", "广东")
        store = RegtrackStore(industries={
            key: IndustryGroup(
                keywords=["餐饮", "食品安全"],
                region="广东",
                added="2026-01-01",
            ),
        })
        p = tmp_path / "new.json"
        store.save(str(p))
        loaded = RegtrackStore.load(str(p))
        assert key in loaded.industries
        g = loaded.industries[key]
        assert g.keywords == ["餐饮", "食品安全"]
        assert g.region == "广东"

    def test_make_key(self):
        from research.regtrack import _make_key
        assert _make_key("餐饮") == "餐饮"
        assert _make_key("餐饮", "广东") == "餐饮@广东"


class TestRegtrackCliIntegration:
    def test_cmd_add_industry(self, mocker, tmp_path):
        from research.cli import cmd_regtrack

        class FakeArgs:
            action = "add"
            industry = "测试行业"
            keywords = None
            region = ""
            count = 50
            since = ""
            until = ""
            reg_id = None
            regtrack_file = str(tmp_path / "regtrack.json")
            json = False

        mock_backend_cls = mocker.patch("research.backends.yuandian.YuandianBackend")
        mock_backend_cls.return_value.search.return_value = [
            mocker.Mock(url="yuandian://law/detail?id=l1", title="测试法规"),
        ]
        mock_backend_cls.return_value.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "测试法规", "content": "全文", "sxx": "现行有效"})
        )
        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": "test-key"},
        })

        cmd_regtrack(FakeArgs())
        assert (tmp_path / "regtrack.json").exists()


class TestAddIndustryMultiKeyword:
    def test_add_with_two_keywords_dedup(self, mocker):
        """Multiple keywords searched, results deduped by ID."""
        import json
        from research.regtrack import add_industry, RegtrackStore, _make_key
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


class TestAddIndustryWithRegion:
    def test_add_with_region_creates_compound_key(self, mocker):
        import json
        from research.regtrack import add_industry, RegtrackStore, _make_key
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
        # Verify search was called with region param
        mock_backend.search.assert_called_once_with(
            "餐饮", count=50, legal_type="law", region="广东"
        )

    def test_add_with_region_and_without_region_are_separate(self, mocker):
        import json
        from research.regtrack import add_industry, RegtrackStore, _make_key
        def make_search(reg):
            def fn(*a, **kw):
                return [mocker.Mock(url=f"yuandian://law/detail?id={reg}_1", title=f"Reg{reg}")]
            return fn
        mock_backend = mocker.Mock()
        mock_backend.search.side_effect = [
            [mocker.Mock(url="yuandian://law/detail?id=n1", title="全国法")],
            [mocker.Mock(url="yuandian://law/detail?id=g1", title="广东法")],
        ]
        def scrape_all(url):
            rid = url.split("id=")[-1]
            data = {
                "n1": {"fgmc": "全国法", "content": "...", "sxx": "现行有效"},
                "g1": {"fgmc": "广东法", "content": "...", "sxx": "现行有效"},
            }
            return mocker.Mock(markdown=json.dumps(data[rid]))
        mock_backend.scrape.side_effect = scrape_all

        store = RegtrackStore()
        store = add_industry(store, ["餐饮"], mock_backend)  # 全国
        store = add_industry(store, ["餐饮"], mock_backend, region="广东")  # 广东
        assert _make_key("餐饮") in store.industries
        assert _make_key("餐饮", "广东") in store.industries


class TestCheckIndustrySince:
    def test_check_with_since_passes_fbrq_to_backend(self, mocker):
        import json
        from research.regtrack import (
            check_industry, RegtrackStore, IndustryGroup,
            _make_key,
        )
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
        mock_backend.search.assert_called_once_with(
            "餐饮", count=50, legal_type="law", region="", since="2026-03-01", until=""
        )

    def test_check_with_since_skips_phase2(self, mocker):
        import json
        from research.regtrack import (
            check_industry, RegtrackStore, IndustryGroup,
            TrackedRegulation, RegulationSnapshot, content_hash,
        )
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = []
        mock_backend.scrape.return_value = mocker.Mock(
            markdown=json.dumps({"fgmc": "法A", "content": "新内容", "sxx": "现行有效"})
        )
        store = RegtrackStore(industries={
            "餐饮": IndustryGroup(keywords=["餐饮"], added="2026-01-01", regulations=[
                TrackedRegulation(id="l1", name="法A", status="现行有效",
                                  snapshot=RegulationSnapshot(
                                      content_hash=content_hash("旧内容"),
                                      content="旧内容", taken_at="2026-01-01")),
            ]),
        })
        store, changes = check_industry(store, "餐饮", mock_backend, since="2026-03-01")
        # Phase 2 skipped — scrape should NOT be called
        assert mock_backend.scrape.call_count == 0


class TestCheckIndustryWithRegion:
    def test_check_with_region_uses_group_region(self, mocker):
        import json
        from research.regtrack import (
            check_industry, RegtrackStore, IndustryGroup,
            _make_key,
        )
        mock_backend = mocker.Mock()
        mock_backend.search.return_value = []
        key = _make_key("餐饮", "广东")
        store = RegtrackStore(industries={
            key: IndustryGroup(keywords=["餐饮"], region="广东", added="2026-01-01"),
        })
        store, changes = check_industry(store, key, mock_backend)
        mock_backend.search.assert_called_once_with(
            "餐饮", count=50, legal_type="law", region="广东", since="", until=""
        )


class TestFormatStatusRegion:
    def test_format_status_shows_compound_key(self):
        from research.regtrack import RegtrackStore, IndustryGroup, _make_key
        key = _make_key("餐饮", "广东")
        store = RegtrackStore(industries={
            key: IndustryGroup(keywords=["餐饮"], region="广东", added="2026-01-01", regulations=[]),
        })
        out = format_status(store)
        assert "餐饮@广东" in out


class TestRegtrackCliCheck:
    def test_cmd_check_with_region(self, mocker, tmp_path):
        from research.cli import cmd_regtrack
        from research.regtrack import RegtrackStore, IndustryGroup, _make_key

        key = _make_key("餐饮", "广东")
        store = RegtrackStore(industries={
            key: IndustryGroup(keywords=["餐饮"], region="广东", added="2026-01-01"),
        })
        store.save(str(tmp_path / "regtrack.json"))

        class FakeArgs:
            action = "check"
            industry = "餐饮"
            keywords = None
            region = "广东"
            count = 50
            since = ""
            until = ""
            reg_id = None
            regtrack_file = str(tmp_path / "regtrack.json")
            json = False

        mocker.patch("research.backends.yuandian.YuandianBackend")
        mock_be = __import__("research.backends.yuandian", fromlist=[""]).YuandianBackend
        mock_be.return_value.search.return_value = []
        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": "test-key"},
        })

        cmd_regtrack(FakeArgs())
        assert True  # no crash
