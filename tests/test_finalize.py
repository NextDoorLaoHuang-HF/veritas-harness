import json
import pytest
from pathlib import Path
from research.finalize import (
    parse_draft_report,
    classify_sources,
    assign_labels,
    linkify_report,
    inject_labels_into_evidence_table,
    validate_s_alignment,
    determine_final_status,
    write_artifacts,
    run_finalize,
    DraftReport,
    EvidenceRow,
    LabeledRow,
)


class TestParseDraftReport:
    def test_basic_parse(self):
        text = (
            "## 结论\n\nSummary\n\n"
            "## 关键发现\n\nFinding\n\n"
            "## 证据与来源\n\n"
            "| 来源 | 类型 | 状态 |\n"
            "|------|------|------|\n"
            "| https://a.com | article | scraped |\n"
            "| https://b.com | news | search-only |\n\n"
            "## 置信度\n\nHigh\n\n"
            "## 未解决问题\n\nNone\n"
        )
        report = parse_draft_report(text)
        assert len(report.sections) == 5
        assert len(report.evidence_rows) == 2
        assert report.evidence_rows[0].url == "https://a.com"

    def test_no_evidence_table(self):
        text = "## 结论\n\nC\n\n## 关键发现\n\nK\n\n## 证据与来源\n\nNone\n\n## 置信度\n\nH\n\n## 未解决问题\n\nN\n"
        report = parse_draft_report(text)
        assert report.evidence_rows == []


class TestClassifySources:
    def test_all_admissible(self):
        from research.evidence import EvidenceItem
        evidence = [EvidenceItem(url="https://a.com", status="scraped")]
        rows = [EvidenceRow(url="https://a.com", source_type="article", status="scraped")]
        admissible, dropped = classify_sources(evidence, rows)
        assert len(admissible) == 1
        assert len(dropped) == 0

    def test_dropped_failed(self):
        from research.evidence import EvidenceItem
        evidence = [EvidenceItem(url="https://a.com", status="failed")]
        rows = [EvidenceRow(url="https://a.com", source_type="article", status="scraped")]
        admissible, dropped = classify_sources(evidence, rows)
        assert len(admissible) == 0
        assert len(dropped) == 1


class TestAssignLabels:
    def test_sequential_labels(self):
        rows = [
            LabeledRow(url="https://a.com", source_type="article", status="scraped", label=""),
            LabeledRow(url="https://b.com", source_type="news", status="search-only", label=""),
        ]
        labeled = assign_labels(rows)
        assert labeled[0].label == "S1"
        assert labeled[1].label == "S2"

    def test_empty_list(self):
        assert assign_labels([]) == []


class TestLinkifyReport:
    def test_basic_linkify(self):
        report = "See [S1] and [S2] for details."
        labeled = [
            LabeledRow(url="https://a.com", label="S1"),
            LabeledRow(url="https://b.com", label="S2"),
        ]
        result = linkify_report(report, labeled)
        assert "[S1](https://a.com)" in result
        assert "[S2](https://b.com)" in result

    def test_no_labels(self):
        report = "No sources."
        assert linkify_report(report, []) == "No sources."

    def test_preserves_inline_urls(self):
        report = "See [S1](https://original.com) for details."
        labeled = [
            LabeledRow(url="https://evidence.com", label="S1"),
        ]
        result = linkify_report(report, labeled)
        assert result == "See [S1](https://original.com) for details."

    def test_mixed_bare_and_inline(self):
        report = "[S1](https://inline.com) and [S2] are both linked."
        labeled = [
            LabeledRow(url="https://e1.com", label="S1"),
            LabeledRow(url="https://e2.com", label="S2"),
        ]
        result = linkify_report(report, labeled)
        assert "[S1](https://inline.com)" in result
        assert "[S2](https://e2.com)" in result


class TestInjectLabelsIntoEvidenceTable:
    def test_injects_label_column(self):
        report = (
            "## 证据与来源\n\n"
            "| 来源 | 类型 | 状态 |\n"
            "|------|------|------|\n"
            "| https://a.com | article | scraped |\n"
        )
        labeled = [LabeledRow(url="https://a.com", label="S1")]
        result = inject_labels_into_evidence_table(report, labeled)
        assert "| 标签 |" in result
        assert "| --- |" in result
        assert "**S1**" in result

    def test_multiple_rows(self):
        report = (
            "## 证据与来源\n\n"
            "| 来源 | 类型 | 状态 |\n"
            "|------|------|------|\n"
            "| https://a.com | article | scraped |\n"
            "| https://b.com | news | search-only |\n"
        )
        labeled = [
            LabeledRow(url="https://a.com", label="S1"),
            LabeledRow(url="https://b.com", label="S2"),
        ]
        result = inject_labels_into_evidence_table(report, labeled)
        assert "**S1**" in result
        assert "**S2**" in result

    def test_no_label_map(self):
        report = "## 证据与来源\n\n| 来源 |\n|------|\n| https://a.com |\n"
        result = inject_labels_into_evidence_table(report, [])
        assert result == report

    def test_replaces_correctly(self):
        report = (
            "## 证据与来源\n\n"
            "| 来源 | 类型 |\n"
            "|------|------|\n"
            "| https://a.com | x |\n"
            "| https://b.com | y |\n"
        )
        labeled = [LabeledRow(url="https://b.com", label="S2")]
        result = inject_labels_into_evidence_table(report, labeled)
        lines = result.strip().split("\n")
        # Header has label col
        assert "| 标签 |" in lines[2]
        # First row has empty label cell
        assert lines[4].startswith("| | https://a.com")
        # Second row has S2 label
        assert "**S2**" in lines[5]


class TestValidateSAlignment:
    def test_no_warnings_for_inline(self):
        report = (
            "## 关键发现\n\n"
            "- [S1](https://a.com) finding\n"
            "- [S2](https://b.com) finding\n\n"
            "## 证据与来源\n\n"
            "| 来源 |\n"
            "|------|\n"
            "| https://a.com |\n"
            "| https://b.com |\n"
        )
        assert validate_s_alignment(report) == []

    def test_no_warnings_for_aligned_bare(self):
        report = (
            "## 关键发现\n\n"
            "- [S1] finding\n"
            "- [S2] finding\n\n"
            "## 证据与来源\n\n"
            "| 来源 |\n"
            "|------|\n"
            "| https://a.com |\n"
            "| https://b.com |\n"
        )
        assert validate_s_alignment(report) == []

    def test_mismatch_emits_warning(self):
        report = (
            "## 关键发现\n\n"
            "- [S1] finding\n"
            "- [S3] finding\n\n"
            "## 证据与来源\n\n"
            "| 来源 |\n"
            "|------|\n"
            "| https://a.com |\n"
            "| https://b.com |\n"
        )
        warnings = validate_s_alignment(report)
        assert len(warnings) >= 1
        assert "S#顺序警告" in warnings[0]

    def test_no_findings_section(self):
        report = "## 结论\n\nNothing\n"
        assert validate_s_alignment(report) == []

    def test_no_bare_refs_with_inline_present(self):
        report = (
            "## 关键发现\n\n"
            "- [S1](https://a.com) finding\n\n"
            "## 证据与来源\n\n"
            "| 来源 |\n"
            "|------|\n"
            "| https://b.com |\n"
        )
        assert validate_s_alignment(report) == []


class TestDetermineFinalStatus:
    def test_pass(self):
        assert determine_final_status(admissible=5, dropped=0, audit_verdict="pass") == "pass"

    def test_degraded(self):
        assert determine_final_status(admissible=5, dropped=2, audit_verdict="pass") == "degraded"

    def test_fatal_on_fail(self):
        assert determine_final_status(admissible=0, dropped=5, audit_verdict="pass") == "fatal"

    def test_fatal_on_audit_fail(self):
        assert determine_final_status(admissible=5, dropped=1, audit_verdict="hard_fail") == "fatal"

    def test_degraded_on_repairable_audit(self):
        assert determine_final_status(admissible=5, dropped=0, audit_verdict="repairable") == "degraded"


class TestWriteArtifacts:
    def test_writes_all_files(self, tmp_path):
        write_artifacts(
            run_dir=str(tmp_path),
            report="# Final\nContent",
            claims=[{"url": "https://a.com", "label": "S1", "status": "scraped", "claimed_status": "正常"}],
            audit={"verdict": "pass"},
            summary={"status": "pass"},
        )
        assert (tmp_path / "final-report.md").exists()
        assert (tmp_path / "source-claims.tsv").exists()
        assert (tmp_path / "source-audit.tsv").exists()
        assert (tmp_path / "finalize-summary.json").exists()

        audit_content = (tmp_path / "source-audit.tsv").read_text().strip()
        lines = audit_content.split("\n")
        assert len(lines) == 2
        assert lines[0] == "url\tlabel\tclaimed\tactual"
        assert lines[1] == "https://a.com\tS1\t正常\tscraped"

    def test_audit_tsv_shows_claimed_vs_actual(self, tmp_path):
        write_artifacts(
            run_dir=str(tmp_path),
            report="# Final\nContent",
            claims=[{"url": "https://b.com", "label": "S2", "status": "search-only", "claimed_status": "正常"}],
            audit={},
            summary={},
        )
        content = (tmp_path / "source-audit.tsv").read_text().strip()
        lines = content.split("\n")
        assert lines[0] == "url\tlabel\tclaimed\tactual"
        assert lines[1] == "https://b.com\tS2\t正常\tsearch-only"

    def test_audit_tsv_empty_claims_only_header(self, tmp_path):
        write_artifacts(
            run_dir=str(tmp_path),
            report="# Final\nContent",
            claims=[],
            audit={},
            summary={},
        )
        content = (tmp_path / "source-audit.tsv").read_text().strip()
        assert content == "url\tlabel\tclaimed\tactual"

    def test_report_content(self, tmp_path):
        write_artifacts(
            run_dir=str(tmp_path),
            report="# Final\nContent",
            claims=[],
            audit={},
            summary={},
        )
        content = (tmp_path / "final-report.md").read_text()
        assert "# Final" in content


class TestRunFinalize:
    def test_persisted_summary_uses_portable_report_path(self, tmp_path):
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\n**结论一**：测试结论。\n\n"
            "## 关键发现\n\n"
            "- [S1](https://a.com) **发现一**：测试内容。\n"
            "- [S2](https://b.com) **发现二**：测试内容。\n"
            "- [S3](https://c.com) **发现三**：测试内容。\n\n"
            "## 证据与来源\n\n"
            "| 来源 | 类型 | 状态 |\n"
            "|------|------|------|\n"
            "| https://a.com | article | search-only |\n"
            "| https://b.com | article | search-only |\n"
            "| https://c.com | article | search-only |\n\n"
            "## 置信度\n\n**high** — **测试**。\n\n"
            "## 未解决问题\n\n无。\n\n"
            "*完成时间: 2026-05-24T12:00:00Z*"
        )
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [
                {"url": "https://a.com", "title": "A", "snippet": "s", "source": "a.com"},
                {"url": "https://b.com", "title": "B", "snippet": "s", "source": "b.com"},
                {"url": "https://c.com", "title": "C", "snippet": "s", "source": "c.com"},
            ]
        }))

        class FakeArgs:
            run_dir = str(tmp_path)
            type = "general"
            report_stdin = False
            report = None
            output = None
            summary = None

        run_finalize(FakeArgs())
        summary = json.loads((tmp_path / "finalize-summary.json").read_text())
        assert summary["report_path"] == "final-report.md"
        assert not Path(summary["report_path"]).is_absolute()

    def test_summary_option_writes_custom_summary(self, tmp_path):
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\nC\n\n"
            "## 关键发现\n\n- [S1](https://a.com) **发现**：内容。\n\n"
            "## 证据与来源\n\n"
            "| 来源 | 类型 | 状态 |\n"
            "|------|------|------|\n"
            "| https://a.com | article | search-only |\n\n"
            "## 置信度\n\n**high** — 理由。\n\n"
            "## 未解决问题\n\n无。\n\n"
            "*完成时间: 2026-05-24T12:00:00Z*"
        )
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [{"url": "https://a.com", "title": "A", "snippet": "s", "source": "a.com"}]
        }))

        class FakeArgs:
            run_dir = str(tmp_path)
            type = "general"
            report_stdin = False
            report = None
            output = None
            summary = str(tmp_path / "custom-summary.json")

        result = run_finalize(FakeArgs())
        assert Path(FakeArgs.summary).exists()
        assert result["summary_path"] == str(Path(FakeArgs.summary).resolve())

    def test_general_repairable_type_validation_degrades_status(self, tmp_path):
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\nC\n\n"
            "## 关键发现\n\nK\n\n"
            "## 证据与来源\n\n"
            "| 来源 | 类型 | 状态 |\n"
            "|------|------|------|\n"
            "| https://a.com | article | search-only |\n\n"
            "## 置信度\n\nH\n\n"
            "## 未解决问题\n\nN\n\n"
            "*完成时间: 2026-05-24T12:00:00Z*"
        )
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [{"url": "https://a.com", "title": "A", "snippet": "s", "source": "a.com"}]
        }))

        class FakeArgs:
            run_dir = str(tmp_path)
            type = "general"
            report_stdin = False
            report = None
            output = None
            summary = None

        result = run_finalize(FakeArgs())
        assert result["type_verdict"] == "repairable"
        assert result["status"] == "degraded"

    def test_case_research_without_evidence_cannot_pass(self, tmp_path):
        lines = [
            "> 来源：公开测试材料",
            "## 一、检索问题",
            "竞业限制违约金是否会被法院酌减？",
            "## 二、初步结论",
            "1. 🔴 **若违约金明显高于损失，法院通常会依据《民法典》第五百八十五条酌减。**",
            "2. 🟡 **若用人单位能证明实际损失，法院可能全额支持。**",
            "## 三、研究依据",
            "| 序号 | 概要 | 具体内容 | 案号 |",
            "|------|------|---------|------|",
            "| 1 | 🔴 酌减 | 法院综合薪酬、补偿和损失酌减。 | （2024）京01民终1234号 |",
            "| 2 | 🟡 支持 | 用人单位证明损失后获支持。 | （2024）沪01民终5678号 |",
            "---",
            "### 案例一：测试科技公司诉赵某竞业限制纠纷",
            "**法院认为**：应依据《民法典》第五百八十五条审查违约金与损失是否相当。",
            "案号：（2024）京01民终1234号",
            "---",
            "### 案例二：测试咨询公司诉钱某竞业限制纠纷",
            "**法院认为**：用人单位已证明客户流失损失，违约金可获支持。",
            "案号：（2024）沪01民终5678号",
        ]
        for i in range(70):
            lines.append(f"补充分析{i}：**裁判要点**围绕《民法典》第五百八十五条和损失证明展开。")
        (tmp_path / "draft-report.md").write_text("\n".join(lines))

        class FakeArgs:
            run_dir = str(tmp_path)
            type = "case-research"
            report_stdin = False
            report = None
            output = None
            summary = None

        result = run_finalize(FakeArgs())
        summary = json.loads((tmp_path / "finalize-summary.json").read_text())
        assert result["type_verdict"] == "pass"
        assert result["status"] == "degraded"
        assert summary["status"] == "degraded"
