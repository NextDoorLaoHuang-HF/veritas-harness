"""证据分布检查：每章≥1 案号 + 案号不全集中尾部 30%。

设计目标：机械化检测"附录式"反模式。
- 解析 markdown 章节（## 一、 / ## 1. / ### （一）/ 案例一）
- 统计每章的案号数量 + 案号位置
- 触发条件：
  1. 主体章节（## 一、~## N、）0 案号 → WARNING
  2. 总案号数 ≥5 但 70% 集中在尾部 30% 行 → WARNING "证据分布不均（疑似附录式）"
  3. "附录" 标题下案号 ≥ 总案号 50% → HARD warning "案号堆在附录"

警告级别：
- warning：仅提示，不影响 verdict
- hard：报告 verdict 降为 repairable（除非 --allow-repairable）

这些是结构启发式，**不替代人工审读**。报告中明确"误报可能"以便 Agent 复核。
"""

import re
from dataclasses import dataclass, field
from typing import Iterable


# 案号正则：宽匹配，含 4 位年份 + 法院代字 + 案号 + 号字
# 例：(2024)京02民终3691号 / （2024）京02民终3691号 / 2023.京0113民初20126号 / （2018）湘09行终70号
CASE_NO_RE = re.compile(
    r"[（(]\d{4}[）)][\s\S]{1,40}?[\dA-Za-z一-鿿]+号"
    r"|"
    r"\d{4}\.[\dA-Za-z一-鿿]+号",
    re.UNICODE,
)


@dataclass
class ChapterStats:
    heading: str
    level: int
    start_line: int
    end_line: int
    case_nos: list[str] = field(default_factory=list)

    def has_case(self) -> bool:
        return len(self.case_nos) > 0


def parse_chapters(text: str) -> list[ChapterStats]:
    """解析 markdown 主章节（## / ###）和子章节（#### 案例一 等）。

    返回 ChapterStats 列表，按出现顺序。
    """
    lines = text.splitlines()
    chapter_re_h2 = re.compile(r"^##\s+([^#].*)$")
    chapter_re_h3 = re.compile(r"^###\s+([^#].*)$")
    chapter_re_h4 = re.compile(r"^####\s+([^#].*)$")

    raw = []
    for i, line in enumerate(lines, 1):
        m = chapter_re_h2.match(line)
        if m:
            raw.append((i, 2, m.group(1).strip()))
            continue
        m = chapter_re_h3.match(line)
        if m:
            raw.append((i, 3, m.group(1).strip()))
            continue
        m = chapter_re_h4.match(line)
        if m:
            raw.append((i, 4, m.group(1).strip()))

    stats: list[ChapterStats] = []
    for idx, (line_no, level, heading) in enumerate(raw):
        end_line = raw[idx + 1][0] - 1 if idx + 1 < len(raw) else len(lines)
        stats.append(ChapterStats(
            heading=heading,
            level=level,
            start_line=line_no,
            end_line=end_line,
        ))

    # 给每个章节塞入其范围内的案号
    for ch in stats:
        section_text = "\n".join(lines[ch.start_line - 1: ch.end_line])
        ch.case_nos = list(set(CASE_NO_RE.findall(section_text)))

    return stats


def is_appendix_heading(heading: str) -> bool:
    """判断是否为附录标题（启发式）。"""
    h = heading.lower()
    if "附录" in h:
        return True
    if h.startswith("appendix"):
        return True
    if "参考案例（按" in h or "参考案例(" in h:
        return True
    if "判例汇总" in h or "案号汇总" in h:
        return True
    return False


def is_body_chapter(ch: ChapterStats) -> bool:
    """判断是否主体章节（应含案号）。排除元数据、目录、附录、声明。

    主体章节判断规则：
    - level=2（##）且非"附录/前言/结论/元数据"等 → 是主体章节
    - level=3（### "（一）（二）"子章节）→ **不独立算**主体章节（其案号归属上级 level=2）
    - level=4（####）→ 也不独立算

    例外：level=3 但标题不以"（一）（二）"开头（如"### 案例一：..."） → 算独立主体章节
    """
    h = ch.heading
    if is_appendix_heading(h):
        return False
    # 排除元数据/目录/总结/置信度/未解决/声明/尾注
    skip_kw = [
        "目录", "前言", "结论", "总结", "摘要", "abstract",
        "置信度", "未解决", "声明", "尾注", "metadata",
        "完成时间", "references", "参考文献", "元数据",
    ]
    if any(kw in h.lower() for kw in skip_kw):
        return False
    # level=2 是主章节（如 "## 一、xxx" / "## 1. xxx"）
    if ch.level == 2:
        return True
    # level=3 子章节 "### （一）..." "### （二）..." 不独立算
    if ch.level == 3 and re.match(r"^[（(]\s*[一二三四五六七八九十]+\s*[）)]", h):
        return False
    # 其他 level=3 算独立主体章节（如 "### 案例一：..."）
    return ch.level == 3


def check_evidence_distribution(text: str, report_type: str = "general") -> dict:
    """主入口：返回证据分布审计结果。

    report_type:
      - "general"（默认）：通用报告，4 规则全开
      - "case-research"：豁免规则 2（70% 尾部集中），因 case-research 报告结构
        天然把多个案号集中在「三、研究依据」段，触发误报。

    返回：
    {
        "verdict": "ok" | "warning" | "hard_warning",
        "warnings": [str, ...],
        "stats": {
            "total_chapters": N,
            "body_chapters": N,
            "body_chapters_with_case": N,
            "body_chapters_without_case": [...],
            "total_unique_cases": N,
            "appendix_cases": N,
            "appendix_ratio": 0.0-1.0,
            "tail_concentration": 0.0-1.0,  # 尾部 30% 占比
        },
    }
    """
    chapters = parse_chapters(text)
    if not chapters:
        return {
            "verdict": "ok",
            "warnings": [],
            "stats": {
                "total_chapters": 0,
                "body_chapters": 0,
                "body_chapters_with_case": 0,
                "body_chapters_without_case": [],
                "total_unique_cases": 0,
                "appendix_cases": 0,
                "appendix_ratio": 0.0,
                "tail_concentration": 0.0,
            },
        }

    body_chapters = [ch for ch in chapters if is_body_chapter(ch)]
    body_chapters_with_case = [ch for ch in body_chapters if ch.has_case()]
    body_chapters_without_case = [ch for ch in body_chapters if not ch.has_case()]

    all_case_nos: set[str] = set()
    appendix_case_nos: set[str] = set()
    for ch in chapters:
        for cn in ch.case_nos:
            all_case_nos.add(cn)
            if is_appendix_heading(ch.heading):
                appendix_case_nos.add(cn)

    total_lines = len(text.splitlines())
    tail_start = int(total_lines * 0.7)  # 尾部 30%
    tail_lines = text.splitlines()[tail_start:]
    tail_text = "\n".join(tail_lines)
    tail_case_nos = set(CASE_NO_RE.findall(tail_text))
    tail_concentration = (
        len(tail_case_nos & all_case_nos) / len(all_case_nos)
        if all_case_nos else 0.0
    )
    appendix_ratio = (
        len(appendix_case_nos) / len(all_case_nos)
        if all_case_nos else 0.0
    )

    warnings: list[str] = []
    verdict = "ok"

    # 规则 1：主体章节 0 案号（当主体章节数 ≥2 时）
    if len(body_chapters) >= 2 and body_chapters_without_case:
        names = [ch.heading for ch in body_chapters_without_case]
        warnings.append(
            f"⚠ 证据分布不均：{len(body_chapters_without_case)}/{len(body_chapters)} 个主体章节"
            f"无案号引用 — {names[:5]}{'...' if len(names) > 5 else ''}。"
            f"建议为这些章节补充 ≥1 个相关案号（见 draft 中的 '📌 证据分配点' 占位符）"
        )
        if verdict == "ok":
            verdict = "warning"

    # 规则 2：总案号数 ≥5 但 70% 集中在尾部 30%（疑似附录式）
    # case-research 报告结构天然尾部集中案号，豁免此规则
    if (
        report_type != "case-research"
        and len(all_case_nos) >= 5
        and tail_concentration >= 0.7
    ):
        warnings.append(
            f"⚠ 证据分布不均：{len(tail_case_nos & all_case_nos)}/{len(all_case_nos)} "
            f"({tail_concentration:.0%}) 案号集中在尾部 30%（{tail_start}-{total_lines} 行）— "
            f"疑似附录式。veritas 模板要求：案号按争点融入正文，禁止堆在文末附录"
        )
        verdict = "hard_warning"

    # 规则 3：附录中案号 ≥ 总案号 50%
    if all_case_nos and appendix_ratio >= 0.5:
        appendix_chs = [ch for ch in chapters if is_appendix_heading(ch.heading) and ch.has_case()]
        appendix_names = [ch.heading for ch in appendix_chs]
        warnings.append(
            f"⚠ 案号堆在附录：{len(appendix_case_nos)}/{len(all_case_nos)} "
            f"({appendix_ratio:.0%}) 案号出现在「{'、'.join(appendix_names[:3])}」等附录章节。"
            f"违反 SKILL.md「证据分配点」反附录式硬性要求。"
        )
        verdict = "hard_warning"

    # 规则 4：主体章节案号均分度（吉尼系数简易版）—— 当主体章节 ≥3 且单一章节占比 ≥60% 时告警
    if body_chapters_with_case and len(body_chapters_with_case) >= 3:
        case_counts = [len(ch.case_nos) for ch in body_chapters_with_case]
        max_count = max(case_counts)
        total_in_body = sum(case_counts)
        if total_in_body > 0 and max_count / total_in_body >= 0.6:
            dominant_ch = max(body_chapters_with_case, key=lambda c: len(c.case_nos))
            warnings.append(
                f"⚠ 证据过度集中：{len(case_counts)} 个主体章节中，「{dominant_ch.heading}」"
                f"独占 {max_count}/{total_in_body} ({max_count / total_in_body:.0%}) 案号。"
                f"建议将部分案号分到其他章节以平衡分布"
            )
            if verdict == "ok":
                verdict = "warning"

    return {
        "verdict": verdict,
        "warnings": warnings,
        "stats": {
            "total_chapters": len(chapters),
            "body_chapters": len(body_chapters),
            "body_chapters_with_case": len(body_chapters_with_case),
            "body_chapters_without_case": [ch.heading for ch in body_chapters_without_case],
            "total_unique_cases": len(all_case_nos),
            "appendix_cases": len(appendix_case_nos),
            "appendix_ratio": round(appendix_ratio, 2),
            "tail_concentration": round(tail_concentration, 2),
        },
    }


def format_distribution_report(result: dict) -> str:
    """供 CLI 打印用。"""
    lines = []
    verdict = result["verdict"]
    icon = {"ok": "✓", "warning": "⚠", "hard_warning": "🛑"}.get(verdict, "?")
    stats = result["stats"]

    lines.append(f"{icon} evidence-distribution: {verdict}")
    lines.append(
        f"  body-chapters: {stats['body_chapters_with_case']}/{stats['body_chapters']} "
        f"have case references, {stats['total_unique_cases']} unique cases total"
    )
    if stats["body_chapters_without_case"]:
        names = ", ".join(stats["body_chapters_without_case"][:5])
        lines.append(f"  chapters-without-case: {names}")
    if stats["tail_concentration"] >= 0.7:
        lines.append(
            f"  tail-concentration: {stats['tail_concentration']:.0%} "
            f"of cases in last 30% of lines (appendix-style)"
        )
    if stats["appendix_ratio"] >= 0.5:
        lines.append(
            f"  appendix-ratio: {stats['appendix_ratio']:.0%} of cases in appendix chapters"
        )
    for w in result["warnings"]:
        lines.append(f"  {w}")
    return "\n".join(lines)
