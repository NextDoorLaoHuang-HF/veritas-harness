"""Smoke tests for research.distribution module.

覆盖：4 条规则的触发/不触发边界、CASE_NO_RE 边界、is_body_chapter 主体章节判定。
"""

import pytest
from research.distribution import (
    check_evidence_distribution,
    format_distribution_report,
    parse_chapters,
    is_body_chapter,
    is_appendix_heading,
    CASE_NO_RE,
)


class TestCaseNoRegex:
    """CASE_NO_RE 边界测试 — 覆盖 3 种元典案号格式。"""

    def test_full_bracket_unicode(self):
        # （YYYY）全角括号（最常见）
        text = "参见（2024）陕1024民初1232号案"
        m = CASE_NO_RE.findall(text)
        assert m == ["（2024）陕1024民初1232号"]

    def test_full_bracket_ascii(self):
        # (YYYY) 半角括号
        text = "see (2024)京02民终3691号"
        m = CASE_NO_RE.findall(text)
        assert m == ["(2024)京02民终3691号"]

    def test_dot_format(self):
        # 2023.京0113民初20126号 简化案号
        text = "依据 2023.京0113民初20126号 判决"
        m = CASE_NO_RE.findall(text)
        assert m == ["2023.京0113民初20126号"]

    def test_no_match(self):
        # 普通文本无案号
        text = "这里没有任何案号，只是普通段落"
        m = CASE_NO_RE.findall(text)
        assert m == []

    def test_multiple_cases(self):
        text = "（2024）京02民终3691号 + (2025)宁04民终861号 + 2023.京0113民初20126号"
        m = CASE_NO_RE.findall(text)
        assert len(m) == 3


class TestIsBodyChapter:
    """is_body_chapter 主体章节判定。"""

    def test_level2_is_body(self):
        from research.distribution import ChapterStats
        ch = ChapterStats(heading="一、法律关系定性", level=2, start_line=1, end_line=10)
        assert is_body_chapter(ch) is True

    def test_appendix_excluded(self):
        from research.distribution import ChapterStats
        ch = ChapterStats(heading="附录 A：参考案例", level=2, start_line=1, end_line=10)
        assert is_body_chapter(ch) is False

    def test_metadata_excluded(self):
        from research.distribution import ChapterStats
        for kw in ["目录", "结论", "总结", "置信度", "参考文献", "完成时间"]:
            ch = ChapterStats(heading=kw, level=2, start_line=1, end_line=10)
            assert is_body_chapter(ch) is False, f"{kw} should be excluded"

    def test_level3_subchapter_excluded(self):
        # ### （一）xxx 是子章节，不独立算主体
        from research.distribution import ChapterStats
        ch = ChapterStats(heading="（一）认定要件", level=3, start_line=1, end_line=10)
        assert is_body_chapter(ch) is False

    def test_level3_case_label_is_body(self):
        # ### 案例一：xxx  是 case-research 的独立主体
        from research.distribution import ChapterStats
        ch = ChapterStats(heading="案例一：陈某案", level=3, start_line=1, end_line=10)
        assert is_body_chapter(ch) is True


class TestCheckEvidenceDistribution:
    """4 条规则触发/不触发边界。"""

    def test_no_chapters(self):
        r = check_evidence_distribution("# Title\n\nbody text without chapters")
        assert r["verdict"] == "ok"
        assert r["stats"]["total_chapters"] == 0

    def test_well_distributed_ok(self):
        # 4 章各 1 案号 → ok
        text = """# 测试报告

## 一、基础概念
参见（2024）京02民初1234号。

## 二、认定标准
参见（2024）京02民初1235号。

## 三、法律后果
参见（2024）京02民初1236号。

## 四、应对方案
参见（2024）京02民初1237号。
"""
        r = check_evidence_distribution(text)
        assert r["verdict"] == "ok"
        assert r["stats"]["body_chapters_with_case"] == 4
        assert r["stats"]["total_unique_cases"] == 4

    def test_appendix_style_hard_warning(self):
        # 20 案号全在附录 + body 全空 → hard_warning（规则 1 + 3 触发）
        body = "## 一、基础\n\n正文无案号\n\n" * 5
        appendix = "## 附录 A：参考案例\n\n"
        for i in range(20):
            appendix += f"| 案号（{2024}）京02民终{i:04d}号 | 案例 {i} |\n"
        text = body + appendix
        r = check_evidence_distribution(text)
        assert r["verdict"] == "hard_warning"
        assert r["stats"]["total_unique_cases"] == 20
        assert r["stats"]["appendix_ratio"] == 1.0  # 100% 案号在附录
        assert r["stats"]["body_chapters_with_case"] == 0
        # 5 个 body 章节（5 个 `## 一、基础`）都缺案号
        assert len(r["stats"]["body_chapters_without_case"]) == 5

    def test_empty_body_chapter_warning(self):
        # 5 章但 3 章无案号 → warning（规则 1）
        text = """## 一、有案号
参见（2024）京01民初1234号。

## 二、无案号
正文段落但没引用任何案号。

## 三、有案号
参见（2024）京01民初1235号。

## 四、无案号
正文段落。

## 五、无案号
正文段落。
"""
        r = check_evidence_distribution(text)
        assert r["verdict"] in ("warning", "hard_warning")
        assert r["stats"]["body_chapters_with_case"] == 2
        assert len(r["stats"]["body_chapters_without_case"]) == 3

    def test_dominant_chapter_warning(self):
        # 1 章节独占 60%+ → warning（规则 4）
        lines = ["## 一、 分散章"]
        # 4 章均衡 + 1 章大量
        for i in range(4):
            text_chap = f"\n\n## 章节{i}\n\n"
            for j in range(1):
                text_chap += f"参见（{2024}）京02民终{i:04d}{j:03d}号。\n"
            lines.append(text_chap)
        # 主导章节：10 个案号
        dominant = "\n\n## 主导章\n\n"
        for j in range(10):
            dominant += f"参见（{2024}）京02民终9999{j:03d}号。\n"
        text = "".join(lines) + dominant
        r = check_evidence_distribution(text)
        # 期望 4 章节各 1 + 主导章 10 = 总 14，主导章占 10/14 = 71% → warning
        assert r["verdict"] in ("warning", "hard_warning")
        assert any("过度集中" in w for w in r["warnings"])

    def test_case_research_exempts_rule2(self):
        # case-research 报告：5 案号全在尾部「研究依据」段 + 短开头
        # 通用模式会触发规则 2 hard_warning；case-research 模式豁免
        text = """## 一、检索问题

简短问题陈述。

## 二、初步结论

依据案例展开。

## 三、研究依据

参见（2024）京01民初1234号。
参见（2024）京01民初1235号。
参见（2024）京01民初1236号。
参见（2024）京01民初1237号。
参见（2024）京01民初1238号。
"""
        # general 模式：可能因 5/5 案号集中 → hard_warning
        r_general = check_evidence_distribution(text, report_type="general")
        # case-research 模式：豁免规则 2
        r_case = check_evidence_distribution(text, report_type="case-research")
        # case-research 的 verdict 应 ≤ general 的 severity
        sev = {"ok": 0, "warning": 1, "hard_warning": 2}
        assert sev[r_case["verdict"]] <= sev[r_general["verdict"]]


class TestFormatDistributionReport:
    """format_distribution_report 渲染测试（不抛异常即可）。"""

    def test_format_ok(self):
        text = "## 一、章\n\n参见（2024）京02民初1234号。"
        r = check_evidence_distribution(text)
        out = format_distribution_report(r)
        assert "evidence-distribution" in out
        assert "verdict=" not in out  # 不应有原始 dict
