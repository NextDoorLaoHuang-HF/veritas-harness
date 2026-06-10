import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone


# ── Report type definitions ──────────────────────────────────────────

REPORT_TYPES = ("general", "deep-research", "practical-guide", "case-research")

# Type-specific required sections
REQUIRED_SECTIONS_BY_TYPE = {
    "general": ["结论", "关键发现", "证据与来源", "置信度", "未解决问题"],
    "deep-research": [],  # checked by numbered sections instead
    "practical-guide": [],  # checked by Chinese-numbered sections
    "case-research": ["检索问题", "初步结论", "研究依据"],
}

# Type-specific validation functions return (verdict, warnings)
# verdict: "pass" | "repairable" | "hard_fail"


@dataclass
class EvidenceRow:
    url: str
    source_type: str = ""
    status: str = ""


@dataclass
class DraftReport:
    sections: dict[str, str] = field(default_factory=dict)
    evidence_rows: list[EvidenceRow] = field(default_factory=list)


@dataclass
class LabeledRow:
    url: str
    source_type: str = ""
    status: str = ""
    label: str = ""
    claimed_status: str = ""


def parse_draft_report(text: str) -> DraftReport:
    sections: dict[str, str] = {}
    current_section = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    evidence_rows: list[EvidenceRow] = []
    evidence_section = sections.get("证据与来源", "")
    table_lines = [l for l in evidence_section.split("\n") if "|" in l and "---" not in l]
    for line in table_lines[1:]:
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 1:
            url = parts[0]
            source_type = parts[1] if len(parts) > 1 else ""
            status = parts[2] if len(parts) > 2 else ""
            evidence_rows.append(EvidenceRow(url=url, source_type=source_type, status=status))

    return DraftReport(sections=sections, evidence_rows=evidence_rows)


def classify_sources(evidence: list, rows: list[EvidenceRow]) -> tuple[list[LabeledRow], list[LabeledRow]]:
    evidence_map = {e.url: e for e in evidence}
    admissible: list[LabeledRow] = []
    dropped: list[LabeledRow] = []

    for row in rows:
        ev = evidence_map.get(row.url)
        status = ev.status if ev else "unknown"
        lr = LabeledRow(url=row.url, source_type=row.source_type, status=status, claimed_status=row.status)
        if ev and ev.status in ("scraped", "search-only"):
            admissible.append(lr)
        else:
            dropped.append(lr)

    return admissible, dropped


def assign_labels(rows: list[LabeledRow]) -> list[LabeledRow]:
    for i, row in enumerate(rows, start=1):
        row.label = f"S{i}"
    return rows


def linkify_report(report: str, labeled: list[LabeledRow]) -> str:
    label_map = {lr.label: lr.url for lr in labeled if lr.label}

    def replace_bare(m: re.Match) -> str:
        label = m.group(1)
        url = label_map.get(label, "")
        if url:
            return f"[{label}]({url})"
        return m.group(0)

    return re.sub(r'\[(S\d+)\](?!\()', replace_bare, report)


def inject_labels_into_evidence_table(report: str, labeled: list[LabeledRow]) -> str:
    label_map = {lr.url: lr.label for lr in labeled if lr.label if lr.label}
    if not label_map:
        return report

    lines = report.split("\n")
    result = []
    in_table = False
    sep_seen = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## 证据与来源"):
            in_table = True
            sep_seen = False
            result.append(line)
            continue

        if in_table:
            if stripped.startswith("## "):
                in_table = False
                result.append(line)
                continue

            if not stripped.startswith("|"):
                result.append(line)
                continue

            if not sep_seen and "---" not in stripped:
                result.append("| 标签 |" + line[1:])
                continue

            if "---" in stripped:
                sep_seen = True
                result.append("| --- |" + line[1:])
                continue

            if sep_seen:
                cells = [c.strip() for c in line.split("|")]
                if len(cells) >= 2:
                    url = cells[1]
                    label = label_map.get(url, "")
                    if label:
                        result.append(f"| **{label}** |" + line[1:])
                    else:
                        result.append(f"| |" + line[1:])
                    continue

            result.append(line)
        else:
            result.append(line)

    return "\n".join(result)


def validate_s_alignment(report: str) -> list[str]:
    lines = report.split("\n")
    in_findings = False
    bare_refs: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## 关键发现"):
            in_findings = True
            continue
        if in_findings:
            if stripped.startswith("## "):
                in_findings = False
                continue
            refs = re.findall(r'\[(S\d+)\](?!\()', stripped)
            bare_refs.extend(refs)

    if not bare_refs:
        return []

    if re.search(r'\[S\d+\]\(https?://', report):
        return []

    draft = parse_draft_report(report)
    table_urls = [row.url for row in draft.evidence_rows]
    if not table_urls:
        return []

    warnings = []
    for i, s_ref in enumerate(bare_refs):
        if i < len(table_urls):
            expected = i + 1
            actual = int(s_ref[1:])
            if actual != expected:
                warnings.append(
                    f"S#顺序警告: 关键发现中第{i+1}个引用为[{s_ref}], "
                    f"按证据表顺序应为[S{expected}]。"
                    f"如需精确映射请使用 [S{actual}](url) 内联语法"
                )
    return warnings


# ── Type-specific validators ──────────────────────────────────────────

def _has_metadata_header(text: str) -> bool:
    """Check for metadata-style metadata header: > 来源：..."""
    return bool(re.search(r'>\s*来源[：:]', text))


def _has_numbered_sections(text: str) -> bool:
    """Check for ## 1. or ## 2. numbered sections (deep-research style)."""
    return bool(re.search(r'^##\s+\d+[.、]', text, re.MULTILINE))


def _has_chinese_numbered_sections(text: str) -> bool:
    """Check for ## 一、 or ## 二、 Chinese-numbered sections (practical-guide style)."""
    return bool(re.search(r'^##\s+[一二三四五六七八九十]+、', text, re.MULTILINE))


def _has_case_table(text: str) -> bool:
    """Check for case summary table with 4 columns (case-research style)."""
    # Look for a table header containing 序号 and 概要 and 案号
    return bool(re.search(r'序号.*概要.*案号', text))


def _count_case_numbers(text: str) -> int:
    """Count valid case numbers like (2024)京02民终3691号 or 2023.京0113民初20126号."""
    pattern = r'[（(]\s*\d{4}\s*[）)].+?号|\d{4}[.．].+?号'
    return len(re.findall(pattern, text))


def _count_bold_passages(text: str) -> int:
    """Count **bold** passages in the text."""
    return len(re.findall(r'\*\*[^*]+\*\*', text))


def _count_tables(text: str) -> int:
    """Count markdown tables (blocks with | header | and | --- | separator)."""
    lines = text.split("\n")
    count = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if next_stripped.startswith("|") and "---" in next_stripped:
                count += 1
    return count


def _count_lines(text: str) -> int:
    """Count non-empty lines."""
    return sum(1 for line in text.split("\n") if line.strip())


def _has_footnotes(text: str) -> bool:
    """Check for footnote markers like ① ② ③ or [1] [2]."""
    return bool(re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]|\[\d+\]', text))


def _has_emphasis_markers(text: str) -> bool:
    """Check for emphasis markers like 划重点, 关键, 核心提示, 实务结论."""
    return bool(re.search(r'划重点|核心提示|实务结论|终极|避坑', text))


def _count_law_citations(text: str) -> int:
    """Count law citations like 《XX法》第X条 or 《XX条例》第X条."""
    return len(re.findall(r'《[^》]+》第?[一二三四五六七八九十百千\d]+条', text))


def _count_law_references(text: str) -> int:
    """Count any law references including bare 《XX法》 without article numbers."""
    return len(re.findall(r'《[^》]+》', text))


def _count_s_references(text: str) -> int:
    """Count [S1], [S2] etc. references (with or without URLs)."""
    return len(re.findall(r'\[S\d+\]', text))


def _count_inline_url_refs(text: str) -> int:
    """Count [S1](url) inline URL references."""
    return len(re.findall(r'\[S\d+\]\(https?://\S+\)', text))


# ── Quality thresholds per report type ────────────────────────────────

QUALITY_THRESHOLDS = {
    "general": {
        "min_lines": 40,
        "min_bold": 4,
        "min_tables": 0,
        "require_footnotes": False,
        "require_emphasis": False,
        # Citation requirements
        "min_s_refs": 3,       # [S1](url) style
        "min_law_refs": 0,     # 《XX法》 style
        "min_case_nums": 0,    # (2024)京02民终3691号
    },
    "deep-research": {
        "min_lines": 80,
        "min_bold": 6,
        "min_tables": 2,
        "require_footnotes": True,
        "require_emphasis": True,
        # Citation requirements
        "min_s_refs": 3,
        "min_law_refs": 1,
        "min_case_nums": 0,
    },
    "practical-guide": {
        "min_lines": 60,
        "min_bold": 6,
        "min_tables": 0,
        "require_footnotes": False,
        "require_emphasis": True,
        # Citation requirements — 法条引用是核心
        "min_s_refs": 0,
        "min_law_refs": 3,
        "min_case_nums": 0,
    },
    "case-research": {
        "min_lines": 80,
        "min_bold": 4,
        "min_tables": 1,  # case summary table
        "require_footnotes": False,
        "require_emphasis": False,
        # Citation requirements — 案号+法条缺一不可
        "min_s_refs": 0,
        "min_law_refs": 1,
        "min_case_nums": 2,
    },
}


def _check_quality_thresholds(text: str, report_type: str) -> list[str]:
    """Check quality thresholds for the given report type.
    
    Returns a list of warnings for thresholds not met.
    These are informational and may not affect the final verdict directly,
    but they signal where the report falls short of the published quality benchmark.
    """
    warnings = []
    thresholds = QUALITY_THRESHOLDS.get(report_type, QUALITY_THRESHOLDS["general"])
    
    line_count = _count_lines(text)
    if line_count < thresholds["min_lines"]:
        warnings.append(
            f"内容深度不足：当前 {line_count} 行，"
            f"建议 ≥{thresholds['min_lines']} 行（专业研究质量标准）"
        )
    
    bold_count = _count_bold_passages(text)
    if bold_count < thresholds["min_bold"]:
        warnings.append(
            f"加粗标注不足：当前 {bold_count} 处，"
            f"建议 ≥{thresholds['min_bold']} 处（关键推理和结论须**加粗**标注）"
        )
    
    table_count = _count_tables(text)
    if table_count < thresholds["min_tables"]:
        warnings.append(
            f"数据表不足：当前 {table_count} 个表格，"
            f"建议 ≥{thresholds['min_tables']} 个（费用表/对比表/条件表等）"
        )
    
    if thresholds["require_footnotes"] and not _has_footnotes(text):
        warnings.append("缺少脚注标注（①②③），专题研究应对数据表和关键引用加脚注")
    
    if thresholds["require_emphasis"] and not _has_emphasis_markers(text):
        warnings.append("缺少强调标记（划重点/实务结论/核心提示），读者引导不足")
    
    # ── Citation requirements ──
    s_ref_count = _count_s_references(text)
    min_s = thresholds.get("min_s_refs", 0)
    if min_s > 0 and s_ref_count < min_s:
        inline_count = _count_inline_url_refs(text)
        if inline_count > 0:
            # Has inline refs but count low
            warnings.append(
                f"S#引用不足：当前 {s_ref_count} 处 [S#] 引用，"
                f"建议 ≥{min_s} 处（每个关键发现须有来源引用）"
            )
        else:
            # No S# refs at all
            warnings.append(
                f"缺少[S#](url)引用标注：当前 0 处，"
                f"建议 ≥{min_s} 处（每个关键发现须有来源URL引用，如 [S1](https://...)）"
            )
    
    law_ref_count = _count_law_references(text)
    law_cite_count = _count_law_citations(text)
    min_law = thresholds.get("min_law_refs", 0)
    if min_law > 0 and law_ref_count < min_law:
        warnings.append(
            f"法条引用不足：当前 {law_ref_count} 处《XX法》引用"
            f"（其中 {law_cite_count} 处精确到第X条），"
            f"建议 ≥{min_law} 处（每个法律判断须引用具体法条）"
        )
    elif min_law > 0 and law_cite_count < law_ref_count // 2:
        warnings.append(
            f"法条引用精度不足：{law_ref_count} 处《XX法》引用中"
            f"仅 {law_cite_count} 处精确到第X条，建议补充具体条文号"
        )
    
    case_num_count = _count_case_numbers(text)
    min_cases = thresholds.get("min_case_nums", 0)
    if min_cases > 0 and case_num_count < min_cases:
        warnings.append(
            f"案号引用不足：当前 {case_num_count} 个案号，"
            f"建议 ≥{min_cases} 个（每个案例须有完整案号，如 (2024)京02民终3691号）"
        )
    
    return warnings


def validate_deep_research(text: str) -> tuple[str, list[str]]:
    """Validate deep-research type report."""
    warnings = []

    if not _has_metadata_header(text):
        warnings.append("缺少元数据头（> 来源：...）")

    if not _has_numbered_sections(text):
        warnings.append("缺少编号章节（## 1. / ## 2.），专题研究应使用编号分节")

    # Check for comparison summary (📊 or radar chart description)
    if re.search(r'📊|雷达图|对比', text) and not re.search(r'关键发现', text):
        warnings.append("有对比内容但缺少关键发现总结句")

    # Quality thresholds
    quality_warnings = _check_quality_thresholds(text, "deep-research")
    warnings.extend(quality_warnings)

    # Determine verdict — citation gaps are structural, not cosmetic
    citation_gap = any(w for w in warnings if "S#引用不足" in w or "缺少[S#]" in w or "法条引用不足" in w)
    depth_gap = any(w for w in warnings if "深度不足" in w)
    structure_gap = not _has_numbered_sections(text) or not _has_metadata_header(text)
    
    if structure_gap and depth_gap:
        verdict = "hard_fail"
    elif structure_gap or depth_gap or citation_gap:
        verdict = "repairable"
    else:
        verdict = "pass"
    if not _has_numbered_sections(text) and not _has_metadata_header(text):
        verdict = "hard_fail"

    return verdict, warnings


def validate_practical_guide(text: str) -> tuple[str, list[str]]:
    """Validate practical-guide type report."""
    warnings = []

    if not _has_metadata_header(text):
        warnings.append("缺少元数据头")

    if not _has_chinese_numbered_sections(text):
        warnings.append("缺少中文编号章节（## 一、/ ## 二、），实务指引应使用中文编号")

    # Check for action steps (### 1. or 1. 2. 3.)
    if not re.search(r'###\s+\d+[.、]|^\d+[.、]\s+', text, re.MULTILINE):
        warnings.append("缺少步骤编号（### 1. / 1. 2. 3.），实务指引应有操作步骤")

    # Check for emphasis markers
    if '划重点' not in text and '关键' not in text:
        warnings.append("缺少**划重点**或等价强调标记")

    # Check for tail note
    if not re.search(r'\*本文档为', text):
        warnings.append("缺少尾注行（*本文档为...*）")

    # Quality thresholds
    quality_warnings = _check_quality_thresholds(text, "practical-guide")
    warnings.extend(quality_warnings)

    # Determine verdict — citation gaps are structural
    citation_gap = any(w for w in warnings if "法条引用不足" in w)
    depth_gap = any(w for w in warnings if "深度不足" in w)
    structure_gap = not _has_chinese_numbered_sections(text)
    
    if structure_gap:
        verdict = "hard_fail"
    elif structure_gap or depth_gap or citation_gap:
        verdict = "repairable"
    else:
        verdict = "pass"
    if not _has_chinese_numbered_sections(text):
        verdict = "hard_fail"

    return verdict, warnings


def validate_case_research(text: str) -> tuple[str, list[str]]:
    """Validate case-research type report."""
    warnings = []

    # Check three-part structure
    has_question = "检索问题" in text or re.search(r'##\s*一[、.]?\s*检索问题', text)
    has_conclusion = "初步结论" in text or re.search(r'##\s*二[、.]?\s*初步结论', text)
    has_evidence = "研究依据" in text or re.search(r'##\s*三[、.]?\s*研究依据', text)

    if not has_question:
        warnings.append("缺少'检索问题'章节")
    if not has_conclusion:
        warnings.append("缺少'初步结论'章节")
    if not has_evidence:
        warnings.append("缺少'研究依据'章节")

    if not (has_question and has_conclusion and has_evidence):
        return "hard_fail", warnings

    # Check case summary table
    if not _has_case_table(text):
        warnings.append("缺少案例概要表（四列：序号/概要/具体内容/案号）")

    # Check case numbers
    case_count = _count_case_numbers(text)
    if case_count == 0:
        warnings.append("未检测到有效案号")
    elif case_count < 2:
        warnings.append(f"仅检测到 {case_count} 个案号，检索报告应有多个案例")

    # Check bold key reasoning
    bold_count = _count_bold_passages(text)
    if bold_count < 2:
        warnings.append("关键推理缺少**加粗**标注")

    # Check case separators
    sep_count = text.count("\n---\n")
    if case_count > 1 and sep_count < case_count - 1:
        warnings.append("案例之间缺少 --- 分隔线")

    # Check for 🔴/🟡 markers in case summary table
    if not re.search(r'[🔴🟡🟢]', text):
        warnings.append("案例概要表缺少🔴🟡标记，应标注裁判倾向")

    # Quality thresholds
    quality_warnings = _check_quality_thresholds(text, "case-research")
    warnings.extend(quality_warnings)

    # Determine verdict — citation gaps (案号/法条) are structural
    citation_gap = any(w for w in warnings if "案号引用不足" in w or "法条引用不足" in w)
    depth_gap = any(w for w in warnings if "深度不足" in w)
    structure_gap = not (has_question and has_conclusion and has_evidence)
    
    if structure_gap:
        verdict = "hard_fail"
    elif citation_gap or depth_gap:
        verdict = "repairable"
    else:
        verdict = "pass"
    return verdict, warnings


def validate_report_by_type(text: str, report_type: str) -> tuple[str, list[str]]:
    """Validate report text against type-specific rules.

    Returns (verdict, warnings) where verdict is "pass"/"repairable"/"hard_fail".
    """
    if report_type == "deep-research":
        return validate_deep_research(text)
    elif report_type == "practical-guide":
        return validate_practical_guide(text)
    elif report_type == "case-research":
        return validate_case_research(text)
    else:
        # General: use original 5-section check
        missing = [s for s in REQUIRED_SECTIONS_BY_TYPE["general"] if f"## {s}" not in text]
        if missing:
            return "hard_fail", [f"缺少必需章节: {', '.join(missing)}"]
        has_completion_time = "*完成时间" in text or "completion_time" in text or "UTC" in text
        if not has_completion_time:
            return "repairable", ["缺少完成时间标记"]
        
        # Quality thresholds for general
        quality_warnings = _check_quality_thresholds(text, "general")
        citation_gap = any(w for w in quality_warnings if "S#引用不足" in w or "缺少[S#]" in w)
        depth_gap = any(w for w in quality_warnings if "深度不足" in w)
        if citation_gap or depth_gap:
            verdict = "repairable"
        else:
            verdict = "pass"
        return verdict, quality_warnings


def determine_final_status(admissible: list | int, dropped: list | int, audit_verdict: str) -> str:
    ad_count = len(admissible) if isinstance(admissible, list) else admissible
    dr_count = len(dropped) if isinstance(dropped, list) else dropped

    if audit_verdict in ("hard_fail",):
        return "fatal"
    if audit_verdict in ("repairable",):
        return "degraded"
    if dr_count > ad_count:
        return "fatal"
    if dr_count > 0:
        return "degraded"
    return "pass"


def _portable_path(path: Path, base: Path) -> str:
    """Return a persisted path that does not expose machine-specific absolute paths."""
    resolved_path = path.resolve()
    resolved_base = base.resolve()
    try:
        return str(resolved_path.relative_to(resolved_base))
    except ValueError:
        return os.path.relpath(resolved_path, resolved_base)


def _status_from_type_verdict(verdict: str) -> str:
    if verdict == "pass":
        return "pass"
    if verdict == "repairable":
        return "degraded"
    return "fatal"


def _degrade_without_evidence(status: str, evidence: list, report_type: str) -> str:
    """A report cannot be a clean pass if no collected evidence exists.

    Type validators check report shape and citation syntax; they cannot prove the
    cited materials were actually collected. This guard prevents example/demo
    reports from being persisted as pass without query/scrape evidence files.
    """
    if status == "pass" and not evidence:
        return "degraded"
    return status


def write_artifacts(run_dir: str, report: str, claims: list, audit: dict, summary: dict):
    base = Path(run_dir)
    base.mkdir(parents=True, exist_ok=True)

    (base / "final-report.md").write_text(report)

    claims_lines = ["url\tstatus"]
    for c in claims:
        claims_lines.append(f"{c.get('url', '')}\t{c.get('status', '')}")
    (base / "source-claims.tsv").write_text("\n".join(claims_lines))

    audit_lines = ["url\tlabel\tclaimed\tactual"]
    for c in claims:
        audit_lines.append(f"{c.get('url', '')}\t{c.get('label', '')}\t{c.get('claimed_status', '')}\t{c.get('status', '')}")
    (base / "source-audit.tsv").write_text("\n".join(audit_lines))

    (base / "finalize-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))


def run_finalize(args) -> dict:
    from research.evidence import collect_evidence

    run_dir = Path(args.run_dir)
    report_type = getattr(args, "type", "general") or "general"

    if args.report_stdin:
        import sys
        draft_text = sys.stdin.read()
    elif args.report:
        draft_text = Path(args.report).read_text()
    else:
        draft_text = (run_dir / "draft-report.md").read_text()

    # Type-specific validation
    type_verdict, type_warnings = validate_report_by_type(draft_text, report_type)
    for w in type_warnings:
        print(f"⚠ [{report_type}] {w}")

    # For practical-guide and case-research, skip S# label processing
    skip_s_labels = report_type in ("practical-guide", "case-research")

    if skip_s_labels:
        report_text = draft_text
    else:
        draft = parse_draft_report(draft_text)
        evidence = collect_evidence(str(run_dir))
        admissible, dropped = classify_sources(evidence, draft.evidence_rows)
        all_sources = assign_labels(admissible + dropped)

        warnings = validate_s_alignment(draft_text)
        for w in warnings:
            print(f"⚠ {w}")

        report_text = draft_text
        if all_sources:
            report_text = linkify_report(report_text, all_sources)
            report_text = inject_labels_into_evidence_table(report_text, all_sources)

    # Type-specific validation is the primary audit for all report types.
    audit_result = type_verdict

    evidence = collect_evidence(str(run_dir))
    if skip_s_labels:
        # For types that skip S# labels, use type validation plus evidence presence.
        final_status = _status_from_type_verdict(type_verdict)
        final_status = _degrade_without_evidence(final_status, evidence, report_type)
    else:
        draft = parse_draft_report(draft_text)
        admissible, dropped = classify_sources(evidence, draft.evidence_rows)
        final_status = determine_final_status(admissible, dropped, audit_result)
        final_status = _degrade_without_evidence(final_status, evidence, report_type)

    output_path = args.output or str(run_dir / "final-report.md")
    Path(output_path).write_text(report_text)

    claims_data = []
    if not skip_s_labels:
        draft_obj = parse_draft_report(draft_text)
        admissible, dropped = classify_sources(evidence, draft_obj.evidence_rows)
        all_sources = assign_labels(admissible + dropped)
        claims_data = [{"url": lr.url, "status": lr.status, "label": lr.label, "claimed_status": lr.claimed_status} for lr in all_sources]

    audit_data = {
        "verdict": audit_result,
        "type_verdict": type_verdict,
        "type_warnings": type_warnings,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    summary = {
        "status": final_status,
        "report_type": report_type,
        "type_verdict": type_verdict,
        "audit_verdict": audit_result,
        "evidence_count": len(evidence),
        "report_path": _portable_path(Path(output_path), run_dir),
    }
    summary_path = args.summary or str(run_dir / "finalize-summary.json")

    write_artifacts(
        run_dir=str(run_dir),
        report=report_text,
        claims=claims_data,
        audit=audit_data,
        summary=summary,
    )
    if args.summary:
        Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
        Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    result = {
        "status": final_status,
        "report_path": str(Path(output_path).resolve()),
        "summary_path": str(Path(summary_path).resolve()),
        "type_verdict": type_verdict,
    }

    print(f"✔ final-report.md (type={report_type}, status={final_status})")
    print(f"✔ source-claims.tsv")
    print(f"✔ source-audit.tsv")
    print(f"✔ {Path(summary_path).name}")

    return result
