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
        call = mock_post.call_args
        assert call[0][0] == "rh_fg_search"
        assert call[0][1]["dy"] == "广东"
        assert len(results) == 1

    def test_search_law_passes_since_until(self, mocker):
        be = YuandianBackend(api_key="test-key")
        mock_post = mocker.patch.object(be, "_post")
        mock_post.return_value = {
            "code": 200, "data": [], "message": "ok", "status": "success",
        }
        be._search_law("餐饮", count=10, since="2026-03-01", until="2026-04-30")
        call = mock_post.call_args
        assert call[0][1]["fbrq_start"] == "2026-03-01"
        assert call[0][1]["fbrq_end"] == "2026-04-30"

    def test_search_law_vector_when_no_region_or_since(self, mocker):
        be = YuandianBackend(api_key="test-key")
        mock_post = mocker.patch.object(be, "_post")
        mock_post.return_value = {
            "code": 201, "extra": {"fatiao": []}, "msg": "ok",
        }
        be._search_law("餐饮", count=10)
        call = mock_post.call_args
        assert call[0][0] == "law_vector_search"
        assert call[0][1]["return_num"] == 10

    def test_search_law_dedup_by_fgid(self, mocker):
        be = YuandianBackend(api_key="test-key")
        mock_post = mocker.patch.object(be, "_post")
        mock_post.return_value = {
            "code": 201, "extra": {"fatiao": [
                {"fgid": "fg-1", "id": "ft-1", "fgtitle": "食品安全法",
                 "num": "第一条", "content": "内容1"},
                {"fgid": "fg-1", "id": "ft-2", "fgtitle": "食品安全法",
                 "num": "第二条", "content": "内容2"},
            ]},
        }
        results = be._search_law("食品安全", count=10)
        assert len(results) == 1

    def test_search_law_forwards_region_from_search(self, mocker):
        be = YuandianBackend(api_key="test-key")
        mock_post = mocker.patch.object(be, "_post")
        mock_post.return_value = {
            "code": 200, "data": [], "message": "ok", "status": "success",
        }
        be.search("餐饮", legal_type="law", region="广东")
        call = mock_post.call_args
        assert call[0][1].get("dy") == "广东"

    def test_search_law_kwargs_top_k_used(self, mocker):
        be = YuandianBackend(api_key="test-key")
        mock_post = mocker.patch.object(be, "_post")
        mock_post.return_value = {
            "code": 200, "data": [], "message": "ok", "status": "success",
        }
        be._search_law("餐饮", count=10, region="广东")
        call = mock_post.call_args
        assert call[0][1].get("top_k") == 10
