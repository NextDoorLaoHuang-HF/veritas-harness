"""Smoke tests for research.inject module.

覆盖：CASE_NO_RE 边界、extract_cases_from_run 三来源、allocate_cases 排序、parse_user_section_keywords、自定义关键词覆盖。
"""

import json
import pytest
from pathlib import Path

from research.inject import (
    CASE_NO_RE,
    extract_cases_from_run,
    score_case_against_section,
    allocate_cases,
    parse_user_section_keywords,
    DEFAULT_KEYWORDS,
)


class TestCaseNoRegex:
    """CASE_NO_RE 边界 — 与 distribution.py 的版本同源。"""

    def test_full_bracket_unicode(self):
        text = "（2024）陕1024民初1232号"
        m = CASE_NO_RE.findall(text)
        assert m == ["（2024）陕1024民初1232号"]

    def test_full_bracket_ascii(self):
        text = "(2024)京02民终3691号"
        m = CASE_NO_RE.findall(text)
        assert m == ["(2024)京02民终3691号"]

    def test_dot_format(self):
        text = "2023.京0113民初20126号"
        m = CASE_NO_RE.findall(text)
        assert m == ["2023.京0113民初20126号"]

    def test_no_match(self):
        text = "没有任何案号的普通段落"
        assert CASE_NO_RE.findall(text) == []


class TestExtractCasesFromRun:
    """extract_cases_from_run 三来源测试（query-*.json / scrape-*.json / scrape-manifest.tsv）。"""

    def test_empty_run_dir(self, tmp_path):
        cases = extract_cases_from_run(tmp_path)
        assert cases == []

    def test_query_json_case_in_snippet(self, tmp_path):
        # query-*.json 的 snippet 含案号
        (tmp_path / "query-1.json").write_text(json.dumps({
            "results": [
                {
                    "title": "冒名入职工伤案例",
                    "url": "https://example.com",
                    "snippet": "参见（2024）陕1024民初1232号案，认定事实劳动关系成立",
                }
            ]
        }))
        cases = extract_cases_from_run(tmp_path)
        assert len(cases) == 1
        assert cases[0]["case_no"] == "（2024）陕1024民初1232号"
        assert cases[0]["title"] == "冒名入职工伤案例"

    def test_scrape_json_dedup(self, tmp_path):
        # 2 个 scrape 文件含相同案号 → 去重为 1
        for i in range(2):
            (tmp_path / f"scrape-{i}.json").write_text(json.dumps([
                {
                    "case_no": "（2024）京02民终3691号",
                    "title": f"案 {i}",
                    "content": "工伤认定内容",
                    "url": f"https://example.com/{i}",
                }
            ]))
        cases = extract_cases_from_run(tmp_path)
        assert len(cases) == 1
        assert cases[0]["case_no"] == "（2024）京02民终3691号"

    def test_scrape_json_dot_format(self, tmp_path):
        # 点格式案号也能从标准 scrape-*.json 的 text/markdown 中识别
        (tmp_path / "scrape-1.json").write_text(json.dumps({
            "title": "简化案号",
            "markdown": "本案 2023.京0113民初20126号 涉及",
            "url": "https://example.com",
        }))
        cases = extract_cases_from_run(tmp_path)
        assert len(cases) == 1
        assert cases[0]["case_no"] == "2023.京0113民初20126号"

    def test_legacy_scrape_yuandian_name_still_supported(self, tmp_path):
        (tmp_path / "scrape-yuandian-1.json").write_text(json.dumps([
            {
                "case_no": "（2024）沪01民终1234号",
                "title": "旧命名兼容",
                "content": "旧 scrape-yuandian 文件仍可读取",
                "url": "https://example.com/legacy",
            }
        ]))
        cases = extract_cases_from_run(tmp_path)
        assert len(cases) == 1
        assert cases[0]["case_no"] == "（2024）沪01民终1234号"


class TestScoreCaseAgainstSection:
    """score_case_against_section 关键词命中数。"""

    def test_hit_count(self):
        case = {
            "title": "工伤认定案件",
            "content": "劳动者在工作时间因工受伤，认定为工伤",
        }
        score, hits = score_case_against_section(case, ["工伤", "认定", "无关词"])
        assert score == 2
        assert "工伤" in hits and "认定" in hits
        assert "无关词" not in hits

    def test_no_hit(self):
        case = {"title": "无关案件", "content": "完全无关"}
        score, hits = score_case_against_section(case, ["工伤", "认定"])
        assert score == 0
        assert hits == []


class TestAllocateCases:
    """allocate_cases 排序 + top_n 限制。"""

    def test_returns_top_n(self):
        cases = [
            {"case_no": f"（2024）京02民终{i:04d}号",
             "title": "工伤认定案例", "content": "工伤 认定 责任 赔偿"}
            for i in range(10)
        ]
        section_map = {
            "1": ("工伤认定", ["工伤", "认定"]),
        }
        result = allocate_cases(cases, section_map, top_n=3)
        assert len(result) == 1
        assert result[0]["section_id"] == "1"
        assert len(result[0]["recommendations"]) == 3

    def test_filters_zero_score(self):
        cases = [
            {"case_no": "（2024）京01民初1234号", "title": "无关", "content": "完全无关内容"},
        ]
        section_map = {"1": ("工伤", ["工伤"])}
        result = allocate_cases(cases, section_map, top_n=3)
        assert result[0]["recommendations"] == []
        assert result[0]["total_candidates"] == 0


class TestParseUserSectionKeywords:
    """parse_user_section_keywords 自定义关键词解析。"""

    def test_basic_parse(self):
        spec = "一、:工伤,认定;二、:赔偿,责任"
        result = parse_user_section_keywords(spec)
        assert result == {"一、": ["工伤", "认定"], "二、": ["赔偿", "责任"]}

    def test_with_spaces(self):
        spec = " 一、 : 工伤 , 认定 ; 二、 : 赔偿 "
        result = parse_user_section_keywords(spec)
        assert result == {"一、": ["工伤", "认定"], "二、": ["赔偿"]}

    def test_empty(self):
        assert parse_user_section_keywords("") == {}
        assert parse_user_section_keywords(None or "") == {}

    def test_malformed_chunks_skipped(self):
        # 没冒号的 chunk 跳过
        spec = "一、:工伤,认定;bad_chunk;二、:赔偿"
        result = parse_user_section_keywords(spec)
        assert result == {"一、": ["工伤", "认定"], "二、": ["赔偿"]}


class TestDefaultKeywords:
    """DEFAULT_KEYWORDS 内置主题词表存在性。"""

    def test_practical_guide_has_4_sections(self):
        assert len(DEFAULT_KEYWORDS["practical-guide"]) == 4
        # 一、二、三、四 必在
        for k in ["一、", "二、", "三、", "四、"]:
            assert k in DEFAULT_KEYWORDS["practical-guide"]

    def test_deep_research_has_3_subsections(self):
        assert len(DEFAULT_KEYWORDS["deep-research"]) == 3
        for k in ["1.1", "1.2", "1.3"]:
            assert k in DEFAULT_KEYWORDS["deep-research"]
