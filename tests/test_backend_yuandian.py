import pytest
from research.backends.yuandian import YuandianBackend
from research.backends.protocol import BackendError


class TestYuandianBackendInit:
    def test_default_no_key(self, mocker):
        mocker.patch("research.backends.yuandian.load_config", return_value={
            "api_keys": {"yuandian_key": ""},
        })
        backend = YuandianBackend(api_key="")
        assert backend.api_key == ""
        h = backend.health()
        assert h["configured"] is False

    def test_with_key(self):
        backend = YuandianBackend(api_key="test-key")
        assert backend.api_key == "test-key"


class TestYuandianBackendHealth:
    def test_health_no_key(self, mocker):
        mocker.patch("research.backends.yuandian.load_config", return_value={
            "api_keys": {"yuandian_key": ""},
        })
        backend = YuandianBackend(api_key="")
        h = backend.health()
        assert h["status"] == "no_api_key"
        assert h["configured"] is False

    def test_health_with_key(self):
        backend = YuandianBackend(api_key="test-key")
        h = backend.health()
        assert h["status"] == "ok"
        assert h["configured"] is True


class TestYuandianBackendSearchMocked:
    def test_search_law_returns_results(self, mocker):
        mock_post = mocker.patch("requests.post")
        mock_post.return_value.status_code = 200
        # Real law_vector_search: code 201, extra.fatiao with fgtitle/num
        mock_post.return_value.json.return_value = {
            "code": 201,
            "extra": {
                "fatiao": [
                    {
                        "fgtitle": "《中华人民共和国食品安全法》",
                        "num": "第一百条",
                        "content": "食品安全法第一百条内容",
                        "id": "law-001",
                    }
                ]
            },
        }
        backend = YuandianBackend(api_key="test-key")
        results = backend.search("食品安全", legal_type="law")
        assert len(results) >= 1
        assert "食品安全" in results[0].title
        assert results[0].source == "元典法规"

    def test_search_case_returns_results(self, mocker):
        mock_post = mocker.patch("requests.post")
        mock_post.return_value.status_code = 200
        # Real case_vector_search: code 201, extra.wenshu
        mock_post.return_value.json.return_value = {
            "code": 201,
            "extra": {
                "wenshu": [
                    {
                        "title": "某某公司与某某某股东知情权纠纷案",
                        "ah": "(2024)京01民终1234号",
                        "id": "case-001",
                        "content": "股东知情权纠纷一审判决...",
                        "judgmentDate": "2024-01-15",
                    }
                ]
            },
        }
        backend = YuandianBackend(api_key="test-key")
        results = backend.search("股东知情权", legal_type="case")
        assert len(results) >= 1
        assert "股东知情权" in results[0].title
        assert results[0].source == "元典案例"

    def test_search_all_merges_results(self, mocker):
        mock_post = mocker.patch("requests.post")
        mock_post.return_value.status_code = 200
        # Real: law_vector_search (code 201) + case_vector_search (code 201)
        mock_post.return_value.json.side_effect = [
            {"code": 201, "extra": {"fatiao": [
                {"fgtitle": "《民法典》", "num": "第一千条", "content": "...", "id": "l1"}
            ]}},
            {"code": 201, "extra": {"wenshu": [
                {"title": "案例一", "ah": "(2024)京01民终1号", "id": "c1", "content": "..."}
            ]}},
        ]
        backend = YuandianBackend(api_key="test-key")
        results = backend.search("test", legal_type="all")
        assert len(results) == 2

    def test_search_law_fallback_lst_format(self, mocker):
        """rh_fg_search may return data.lst (dict with records/lst key)."""
        mock_post = mocker.patch("requests.post")
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.side_effect = [
            {"code": 500, "message": "error"},
            {"code": 200, "data": {
                "total": 1, "lst": [
                    {"fgmc": "《民法典》", "ftnum": "第一条", "content": "...", "id": "l1"}
                ]
            }},
        ]
        backend = YuandianBackend(api_key="test-key")
        results = backend.search("test", legal_type="law")
        assert len(results) >= 1

    def test_search_case_fallback_lst_format(self, mocker):
        """rh_ptal_search returns data.lst (dict with lst key)."""
        mock_post = mocker.patch("requests.post")
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.side_effect = [
            {"code": 500, "message": "error"},
            {"code": 200, "data": {
                "total": 1, "lst": [
                    {"title": "某某纠纷案", "ah": "(2024)京01民终1号", "id": "c1", "content": "..."}
                ]
            }},
        ]
        backend = YuandianBackend(api_key="test-key")
        results = backend.search("test", legal_type="case")
        assert len(results) >= 1

    def test_search_graceful_fallback(self, mocker):
        mock_post = mocker.patch("requests.post")
        # First call (law_vector_search) fails, fallback rh_fg_search returns flat data list
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.side_effect = [
            {"code": 500, "message": "error"},
            {"code": 200, "data": [
                {"fgmc": "《民法典》", "ftnum": "第一条", "content": "...", "id": "l1"}
            ]},
        ]
        backend = YuandianBackend(api_key="test-key")
        results = backend.search("test", legal_type="law")
        assert len(results) >= 1


class TestYuandianBackendScrapeMocked:
    def test_scrape_law_detail(self, mocker):
        mock_post = mocker.patch("requests.post")
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "code": 200,
            "data": {"name": "《中华人民共和国民法典》", "content": "民法典全文..."},
        }
        backend = YuandianBackend(api_key="test-key")
        result = backend.scrape("yuandian://law/detail?id=law-001")
        assert "民法典" in result.title

    def test_scrape_case_detail(self, mocker):
        mock_get = mocker.patch("requests.get")
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "data": [{"name": "某某案", "content": "..."}],
        }
        backend = YuandianBackend(api_key="test-key")
        result = backend.scrape("yuandian://case/detail?type=ptal&id=case-001")
        assert "某某案" in result.title

    def test_scrape_unsupported_url(self):
        backend = YuandianBackend(api_key="test-key")
        with pytest.raises(BackendError):
            backend.scrape("https://example.com")


class TestYuandianBackendHallDetectMocked:
    def test_detect_hallucinations(self, mocker):
        mock_post = mocker.patch("requests.post")
        mock_post.return_value.status_code = 200
        # Real hall_detect response shape (no top-level code field)
        mock_post.return_value.json.return_value = {
            "regulations": [
                {
                    "name": "《民法典》",
                    "clause": "第一千二百条",
                    "conclusion": "不一致",
                    "detail": "侧A表述的是一般侵权责任构成要件...",
                    "semantic_compare": {
                        "结论": "不一致",
                        "说明": "侧A表述的是一般侵权责任构成要件...",
                    },
                }
            ],
            "cases": [],
            "highlighted_text": "<span>...</span>",
            "chat_model": "gpt-4o",
            "request_id": "req-001",
        }
        backend = YuandianBackend(api_key="test-key")
        result = backend.detect_hallucinations("根据《民法典》第一千二百条...")
        assert len(result["regulations"]) == 1
        assert result["regulations"][0]["name"] == "《民法典》"
        assert result["regulations"][0]["semantic_compare"]["结论"] == "不一致"
