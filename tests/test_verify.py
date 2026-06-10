import json
import pytest
from research.verify import check_claims, audit_report, AuditVerdict, ClaimResult


def _long_general_report(source_url: str = "https://a.com", appendix_cases: bool = False) -> str:
    findings = "\n".join(
        f"- [S{(i % 3) + 1}]({source_url if i == 1 else f'https://example.com/{i}'}) "
        f"**发现{i}**：这是第 {i} 条关键发现，包含足够的事实描述、日期和影响说明。"
        for i in range(1, 36)
    )
    evidence_rows = "\n".join(
        f"| https://example.com/{i} | article | search-only | 摘要 |"
        for i in range(1, 36)
    )
    appendix = ""
    if appendix_cases:
        appendix = (
            "\n## 附录 A：参考案例\n\n"
            "（2024）京01民终1001号\n"
            "（2024）京01民终1002号\n"
            "（2024）京01民终1003号\n"
            "（2024）京01民终1004号\n"
            "（2024）京01民终1005号\n"
        )
    return (
        "## 结论\n\n"
        "**总体结论**：本报告用于测试质量门。\n\n"
        "## 关键发现\n\n"
        f"{findings}\n\n"
        "## 证据与来源\n\n"
        "| 来源 | 类型 | 状态 | 关键信息 |\n"
        "|------|------|------|----------|\n"
        f"| {source_url} | article | search-only | 摘要 |\n"
        f"{evidence_rows}\n\n"
        "## 置信度\n\n"
        "**high** — 来源覆盖充分，仍需人工复核。\n\n"
        "## 未解决问题\n\n"
        "- 暂无。\n"
        f"{appendix}\n"
        "*完成时间: 2026-05-24T12:00:00Z*"
    )


class TestCheckClaims:
    def test_all_match(self):
        claims_tsv = "url\tclaimed_status\nhttps://a.com\tscraped\nhttps://b.com\tsearch-only\n"
        evidence = [
            type("E", (), {"url": "https://a.com", "status": "scraped", "label": "S1", "date": "2026-01-01"}),
            type("E", (), {"url": "https://b.com", "status": "search-only", "label": "S2", "date": None}),
        ]
        results = check_claims(claims_tsv, evidence)
        assert all(r.result == "match" for r in results)
        assert len(results) == 2

    def test_mismatch(self):
        claims_tsv = "url\tclaimed_status\nhttps://a.com\tscraped\n"
        evidence = [
            type("E", (), {"url": "https://a.com", "status": "search-only", "label": "", "date": None}),
        ]
        results = check_claims(claims_tsv, evidence)
        assert results[0].result == "mismatch"

    def test_missing_claim(self):
        claims_tsv = "url\tclaimed_status\nhttps://a.com\tscraped\nhttps://b.com\tscraped\n"
        evidence = [
            type("E", (), {"url": "https://a.com", "status": "scraped", "label": "S1", "date": "2026-01-01"}),
        ]
        results = check_claims(claims_tsv, evidence)
        assert any(r.result == "missing" for r in results)


class TestAuditReport:
    def test_perfect_report(self, tmp_path):
        report = tmp_path / "report.md"
        report.write_text(
            "## 结论\n\nContent\n\n"
            "## 关键发现\n\nContent\n\n"
            "## 证据与来源\n\n[S1](https://a.com) source\n\n"
            "## 置信度\n\nHigh\n\n"
            "## 未解决问题\n\nNone\n\n"
            "*完成时间: 2026-05-24T12:00:00Z*"
        )
        verdict = audit_report(str(report))
        assert verdict == AuditVerdict.PASS

    def test_missing_sections(self, tmp_path):
        report = tmp_path / "report.md"
        report.write_text("## 结论\n\nContent\n\n## 关键发现\n\nContent\n")
        verdict = audit_report(str(report))
        assert verdict == AuditVerdict.HARD_FAIL

    def test_missing_completion_time(self, tmp_path):
        report = tmp_path / "report.md"
        report.write_text(
            "## 结论\n\nContent\n\n"
            "## 关键发现\n\nContent\n\n"
            "## 证据与来源\n\n[S1](url)\n\n"
            "## 置信度\n\nHigh\n\n"
            "## 未解决问题\n\nNone\n"
        )
        verdict = audit_report(str(report))
        assert verdict == AuditVerdict.REPAIRABLE


class TestRunVerify:
    def test_verify_integration(self, tmp_path, monkeypatch):
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [{"url": "https://a.com", "title": "A", "snippet": "s", "source": "a.com"}]
        }))
        (tmp_path / "source-claims.tsv").write_text(
            "url\tclaimed_status\nhttps://a.com\tsearch-only\n"
        )
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\nC\n\n## 关键发现\n\nK\n\n"
            "## 证据与来源\n\n[S1](https://a.com)\n\n"
            "## 置信度\n\nH\n\n## 未解决问题\n\nN\n\n"
            "*完成时间: 2026-05-24T12:00:00Z*"
        )

        class FakeArgs:
            run_dir = str(tmp_path)
            json = False
            allow_repairable = True
            fix_manifest = False

        from research.verify import run_verify
        result = run_verify(FakeArgs())
        assert "verdict" in result

    def test_verify_handles_hallucination_failure(self, tmp_path, mocker):
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [{"url": "https://a.com", "title": "A", "snippet": "s", "source": "a.com"}]
        }))
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\nC\n\n## 关键发现\n\nK\n\n"
            "## 证据与来源\n\n[S1](https://a.com)\n\n"
            "## 置信度\n\nH\n\n## 未解决问题\n\nN\n\n"
            "根据《民法典》第一千二百条规定...\n\n"
            "*完成时间: 2026-05-24T12:00:00Z*"
        )

        mocker.patch(
            "research.backends.yuandian.YuandianBackend.detect_hallucinations",
            side_effect=Exception("系统繁忙，请稍后重试"),
        )
        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": "test-key"},
        })

        class FakeArgs:
            run_dir = str(tmp_path)
            json = False
            allow_repairable = True
            fix_manifest = False

        from research.verify import run_verify
        result = run_verify(FakeArgs())
        assert result["verdict"] == "pass"
        assert result["legal_hallucination_check"]["checked"] is False
        assert "系统繁忙" in result["legal_hallucination_check"]["error"]

    def test_distribution_hard_warning_updates_json_verdict(self, tmp_path, mocker):
        mocker.patch("research.config.load_config", return_value={"api_keys": {"yuandian_key": ""}})
        (tmp_path / "draft-report.md").write_text(
            _long_general_report(source_url="https://a.com", appendix_cases=True)
        )
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [
                {"url": "https://a.com", "title": "A", "snippet": "s", "source": "a.com"},
                *[
                    {"url": f"https://example.com/{i}", "title": str(i), "snippet": "s", "source": "example.com"}
                    for i in range(1, 36)
                ],
            ]
        }))

        class FakeArgs:
            run_dir = str(tmp_path)
            type = "general"
            json = True
            allow_repairable = False
            fix_manifest = False

        from research.verify import run_verify
        result = run_verify(FakeArgs())
        assert result["evidence_distribution"]["verdict"] == "hard_warning"
        assert result["verdict"] == "repairable"

    def test_inline_s_reference_missing_source_is_repairable(self, tmp_path, mocker):
        mocker.patch("research.config.load_config", return_value={"api_keys": {"yuandian_key": ""}})
        (tmp_path / "draft-report.md").write_text(
            _long_general_report(source_url="https://missing.example")
        )
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [
                {"url": f"https://example.com/{i}", "title": str(i), "snippet": "s", "source": "example.com"}
                for i in range(1, 36)
            ]
        }))

        class FakeArgs:
            run_dir = str(tmp_path)
            type = "general"
            json = True
            allow_repairable = False
            fix_manifest = False

        from research.verify import run_verify
        result = run_verify(FakeArgs())
        assert result["source_alignment"]["missing"]
        assert result["verdict"] == "repairable"
