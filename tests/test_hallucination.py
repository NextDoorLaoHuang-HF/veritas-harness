import json
import pytest
from pathlib import Path
from research.hallucination import detect_legal_references, run_legal_check


# Convenience class to simulate argparse args
class _FakeArgs:
    def __init__(self, run_dir, json=False, allow_repairable=False):
        self.run_dir = run_dir
        self.json = json
        self.allow_repairable = allow_repairable


def _write_general_verify_fixture(tmp_path: Path, extra_text: str = ""):
    urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    (tmp_path / "query-test.json").write_text(json.dumps({
        "results": [
            {"url": url, "title": f"source {i}", "snippet": "s"}
            for i, url in enumerate(urls, 1)
        ]
    }))
    (tmp_path / "scrape-manifest.tsv").write_text("url\tfile\n")
    (tmp_path / "source-claims.tsv").write_text(
        "\n".join(["url\tstatus", *[f"{url}\tsearch-only" for url in urls]])
    )

    findings = "\n".join(
        f"- [S{(i % 3) + 1}]({urls[i % 3]}) **关键发现{i}**："
        f"这是用于集成测试的第 {i} 项事实描述，包含背景、影响和复核口径。"
        for i in range(1, 38)
    )
    evidence_rows = "\n".join(
        f"| {url} | article | search-only | 复核来源 |"
        for url in urls
    )
    extra = f"\n\n{extra_text}" if extra_text else ""
    (tmp_path / "draft-report.md").write_text(
        "## 结论\n\n"
        "**总体结论**：该样本用于验证法律幻觉检查与质量门的集成行为。\n\n"
        "## 关键发现\n\n"
        f"{findings}{extra}\n\n"
        "## 证据与来源\n\n"
        "| 来源 | 类型 | 状态 | 关键信息 |\n"
        "|------|------|------|----------|\n"
        f"{evidence_rows}\n\n"
        "## 置信度\n\n"
        "**high** — 来源覆盖充分，引用均可追溯到 run-dir 证据集。\n\n"
        "## 未解决问题\n\n"
        "- 暂无。\n\n"
        "*完成时间: 2026-01-01T00:00:00Z*"
    )


class TestDetectLegalReferences:
    def test_law_name(self):
        assert detect_legal_references("根据《民法典》相关规定") is True

    def test_clause(self):
        assert detect_legal_references("依照第1200条处理") is True

    def test_case_number(self):
        assert detect_legal_references("参见（2019）苏0206民初3374号判决") is True

    def test_non_legal(self):
        assert detect_legal_references("今天天气很好，适合写代码") is False

    def test_empty(self):
        assert detect_legal_references("") is False

    def test_none(self):
        assert detect_legal_references(None) is False  # type: ignore


class TestRunLegalCheck:
    def test_no_legal_refs(self, tmp_path):
        draft = tmp_path / "draft-report.md"
        draft.write_text("这是普通报告，没有法律引用")
        result = run_legal_check(tmp_path, api_key="test-key")
        assert result is None

    def test_missing_draft(self, tmp_path):
        result = run_legal_check(tmp_path, api_key="test-key")
        assert result is None

    def test_with_issues_inconsistent(self, tmp_path, mocker):
        draft = tmp_path / "draft-report.md"
        draft.write_text("根据《民法典》第一千二百条的规定...")

        mock_detect = mocker.patch(
            "research.backends.yuandian.YuandianBackend.detect_hallucinations"
        )
        mock_detect.return_value = {
            "regulations": [
                {
                    "name": "民法典",
                    "clause": "第一千二百条",
                    "semantic_compare": {
                        "结论": "语义比对不一致",
                        "说明": "原文内容与权威来源不符",
                    },
                }
            ],
            "cases": [],
        }

        result = run_legal_check(tmp_path, api_key="test-key")
        assert result is not None
        assert result["checked"] is True
        assert result["total_regulations"] == 1
        assert len(result["issues"]) == 1
        assert result["issues"][0]["conclusion"] == "语义比对不一致"

    def test_with_issues(self, tmp_path, mocker):
        draft = tmp_path / "draft-report.md"
        draft.write_text("根据《民法典》第一千二百条的规定...")

        mock_detect = mocker.patch(
            "research.backends.yuandian.YuandianBackend.detect_hallucinations"
        )
        mock_detect.return_value = {
            "regulations": [
                {
                    "name": "民法典",
                    "clause": "第一千二百条",
                    "semantic_compare": {
                        "结论": "法规内容不匹配",
                        "说明": "原文内容与权威来源不符",
                    },
                }
            ],
            "cases": [],
        }

        result = run_legal_check(tmp_path, api_key="test-key")
        assert result is not None
        assert result["checked"] is True
        assert result["total_regulations"] == 1
        assert result["total_cases"] == 0
        assert len(result["issues"]) == 1
        assert result["issues"][0]["conclusion"] == "法规内容不匹配"

    def test_no_issues(self, tmp_path, mocker):
        draft = tmp_path / "draft-report.md"
        draft.write_text("根据《民法典》第一千二百条的规定...")

        mock_detect = mocker.patch(
            "research.backends.yuandian.YuandianBackend.detect_hallucinations"
        )
        mock_detect.return_value = {
            "regulations": [
                {
                    "name": "民法典",
                    "clause": "第一千二百条",
                    "semantic_compare": {
                        "结论": "语义比对一致",
                        "说明": "",
                    },
                }
            ],
            "cases": [],
        }

        result = run_legal_check(tmp_path, api_key="test-key")
        assert result is not None
        assert result["issues"] == []

    def test_retry_on_transient_failure(self, tmp_path, mocker):
        draft = tmp_path / "draft-report.md"
        draft.write_text("根据《民法典》第一千二百条...")
        from research.backends.yuandian import YuandianBackend

        call_count = [0]
        def _post_side_effect(route, body):
            call_count[0] += 1
            if call_count[0] < 3:
                from research.backends.protocol import BackendError
                raise BackendError("系统繁忙，请稍后重试")
            return {"regulations": [], "cases": []}

        mocker.patch.object(YuandianBackend, "_post", side_effect=_post_side_effect)
        result = run_legal_check(tmp_path, api_key="test-key")
        assert result is not None
        assert result["checked"] is True
        assert call_count[0] == 3

    def test_retry_exhausted(self, tmp_path, mocker):
        draft = tmp_path / "draft-report.md"
        draft.write_text("根据《民法典》第一千二百条...")
        from research.backends.yuandian import YuandianBackend

        mocker.patch.object(YuandianBackend, "_post",
                            side_effect=Exception("系统繁忙，请稍后重试"))
        with pytest.raises(Exception, match="系统繁忙"):
            run_legal_check(tmp_path, api_key="test-key")


class TestVerifyIntegration:
    def test_verify_with_legal_check(self, tmp_path, mocker):
        from research.verify import run_verify

        _write_general_verify_fixture(tmp_path, "根据《民法典》第一千二百条规定。")

        mocker.patch(
            "research.backends.yuandian.YuandianBackend.detect_hallucinations",
            return_value={
                "regulations": [
                    {"name": "民法典", "clause": "第一千二百条",
                     "semantic_compare": {"结论": "语义比对一致", "说明": ""}}
                ],
                "cases": [],
            },
        )
        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": "test-key"},
        })

        result = run_verify(_FakeArgs(str(tmp_path)))
        assert "legal_hallucination_check" in result
        assert result["legal_hallucination_check"]["checked"] is True
        assert result["verdict"] == "pass"

    def test_verify_without_legal_key(self, tmp_path, mocker):
        from research.verify import run_verify

        _write_general_verify_fixture(tmp_path)

        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": ""},
        })

        result = run_verify(_FakeArgs(str(tmp_path)))
        assert "legal_hallucination_check" not in result
        assert result["verdict"] == "pass"

    def test_verify_no_legal_refs(self, tmp_path, mocker):
        from research.verify import run_verify

        _write_general_verify_fixture(tmp_path, "普通文本内容，没有专门引用。")

        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": "test-key"},
        })

        result = run_verify(_FakeArgs(str(tmp_path)))
        assert "legal_hallucination_check" not in result
        assert result["verdict"] == "pass"
