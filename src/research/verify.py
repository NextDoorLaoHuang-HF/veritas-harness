from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re


class AuditVerdict(Enum):
    PASS = "pass"
    REPAIRABLE = "repairable"
    HARD_FAIL = "hard_fail"


@dataclass
class ClaimResult:
    url: str
    claimed_status: str
    actual_status: str | None
    result: str  # match | mismatch | missing


def check_claims(claims_tsv: str, evidence: list) -> list[ClaimResult]:
    lines = claims_tsv.strip().split("\n")
    if len(lines) < 2:
        return []
    results = []
    evidence_map = {e.url: e for e in evidence}
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        url, claimed = parts[0], parts[1]
        actual = evidence_map.get(url)
        if actual is None:
            results.append(ClaimResult(url=url, claimed_status=claimed, actual_status=None, result="missing"))
        elif actual.status == claimed:
            results.append(ClaimResult(url=url, claimed_status=claimed, actual_status=actual.status, result="match"))
        else:
            results.append(ClaimResult(url=url, claimed_status=claimed, actual_status=actual.status, result="mismatch"))
    return results


REQUIRED_SECTIONS = ["结论", "关键发现", "证据与来源", "置信度", "未解决问题"]


def _enum_from_type_verdict(verdict: str) -> AuditVerdict:
    if verdict == "pass":
        return AuditVerdict.PASS
    if verdict == "repairable":
        return AuditVerdict.REPAIRABLE
    return AuditVerdict.HARD_FAIL


def check_s_reference_alignment(report_text: str, evidence: list) -> dict:
    """Check inline [S#](url) references against collected evidence URLs."""
    evidence_map = {e.url: e for e in evidence}
    refs = []
    for label, url in re.findall(r'\[(S\d+)\]\(([^)]+)\)', report_text):
        if not label.startswith("S"):
            continue
        refs.append({"label": label, "url": url})

    matched = []
    missing = []
    failed = []
    for ref in refs:
        item = evidence_map.get(ref["url"])
        if item is None:
            missing.append(ref)
        elif item.status == "failed":
            failed.append({**ref, "status": item.status})
        else:
            matched.append({**ref, "status": item.status})

    warnings = []
    if missing:
        examples = ", ".join(f"{r['label']}={r['url']}" for r in missing[:3])
        warnings.append(f"S#引用未采集：{len(missing)} 个内联来源不在 query/scrape 证据集中（{examples}）")
    if failed:
        examples = ", ".join(f"{r['label']}={r['url']}" for r in failed[:3])
        warnings.append(f"S#引用采集失败：{len(failed)} 个内联来源状态为 failed（{examples}）")

    return {
        "total_inline_refs": len(refs),
        "matched": len(matched),
        "missing": missing,
        "failed": failed,
        "warnings": warnings,
    }


def _structure_summary(report_text: str, report_type: str, verdict: AuditVerdict) -> dict:
    if not report_text:
        return {"sections": "incomplete", "completion_time": "N/A"}
    if report_type == "general":
        missing = [s for s in REQUIRED_SECTIONS if f"## {s}" not in report_text]
        completion = "*完成时间" in report_text or "completion_time" in report_text or "UTC" in report_text
        return {
            "sections": f"{len(REQUIRED_SECTIONS) - len(missing)}/{len(REQUIRED_SECTIONS)}" if missing else "5/5",
            "completion_time": "✓" if completion else "✗",
        }
    return {
        "sections": "type-aware" if verdict != AuditVerdict.HARD_FAIL else "incomplete",
        "completion_time": "type-aware",
    }


def audit_report(report_path: str, report_type: str = "general") -> AuditVerdict:
    """Audit a draft report for structural completeness.

    For 'general' type, checks the standard 5-section structure.
    For other types, delegates to type-specific validation in finalize module.
    """
    path = Path(report_path)
    if not path.exists():
        return AuditVerdict.HARD_FAIL
    text = path.read_text()

    if report_type == "general":
        missing = [s for s in REQUIRED_SECTIONS if f"## {s}" not in text]
        if missing:
            return AuditVerdict.HARD_FAIL

        has_completion_time = "*完成时间" in text or "completion_time" in text or "UTC" in text
        if not has_completion_time:
            return AuditVerdict.REPAIRABLE

        return AuditVerdict.PASS
    else:
        # Use type-specific validation from finalize module
        from research.finalize import validate_report_by_type
        verdict, _warnings = validate_report_by_type(text, report_type)
        if verdict == "pass":
            return AuditVerdict.PASS
        elif verdict == "repairable":
            return AuditVerdict.REPAIRABLE
        else:
            return AuditVerdict.HARD_FAIL


def run_verify(args) -> dict:
    from research.evidence import collect_evidence
    from research.hallucination import run_legal_check
    from research.config import load_config
    from research.finalize import validate_report_by_type

    run_dir = Path(args.run_dir)
    report_type = getattr(args, "type", "general") or "general"

    evidence = collect_evidence(str(run_dir))

    claims_path = run_dir / "source-claims.tsv"
    claim_results = []
    if claims_path.exists():
        claim_results = check_claims(claims_path.read_text(), evidence)

    report_path = run_dir / "draft-report.md"
    report_text = ""
    if report_path.exists():
        report_text = report_path.read_text()
    else:
        report_candidates = list(run_dir.glob("*report*.md"))
        if report_candidates:
            report_path = report_candidates[0]
            report_text = report_path.read_text()

    if report_text:
        type_verdict, type_warnings = validate_report_by_type(report_text, report_type)
        verdict = _enum_from_type_verdict(type_verdict)
    else:
        type_verdict, type_warnings = "hard_fail", ["缺少 draft-report.md 或 *report*.md"]
        verdict = AuditVerdict.HARD_FAIL

    scraped = sum(1 for e in evidence if e.status == "scraped")
    search_only = sum(1 for e in evidence if e.status == "search-only")
    failed = sum(1 for e in evidence if e.status == "failed")
    match_count = sum(1 for c in claim_results if c.result == "match")

    final_verdict = verdict

    result = {
        "report_type": report_type,
        "evidence_urls": {
            "total": len(evidence),
            "scraped": scraped,
            "search_only": search_only,
            "failed": failed,
        },
        "claim_check": {
            "total": len(claim_results),
            "match": match_count,
            "match_pct": f"{match_count / len(claim_results) * 100:.0f}%" if claim_results else "N/A",
        },
        "report_structure": _structure_summary(report_text, report_type, verdict),
        "verdict": final_verdict.value,
    }

    result["type_validation"] = {
        "verdict": type_verdict,
        "warnings": type_warnings,
    }

    # Inline S# URL references must point at evidence collected in the run dir.
    if report_type in ("general", "deep-research") and report_text:
        s_alignment = check_s_reference_alignment(report_text, evidence)
        result["source_alignment"] = s_alignment
        if (s_alignment["missing"] or s_alignment["failed"]) and final_verdict == AuditVerdict.PASS:
            final_verdict = AuditVerdict.REPAIRABLE

    # Evidence distribution check (反附录式启发式)
    from research.distribution import check_evidence_distribution, format_distribution_report
    if report_text:
        dist_result = check_evidence_distribution(report_text, report_type=report_type)
        result["evidence_distribution"] = dist_result
        if dist_result["verdict"] == "hard_warning":
            # 反附录式硬性违规：报告 verdict 降为 repairable
            if final_verdict == AuditVerdict.PASS:
                final_verdict = AuditVerdict.REPAIRABLE
        if not args.json:
            print(format_distribution_report(dist_result))

    if args.allow_repairable and final_verdict == AuditVerdict.REPAIRABLE:
        final_verdict = AuditVerdict.PASS
    result["verdict"] = final_verdict.value

    if not args.json:
        print(f"report-type: {report_type}")
        print(f"evidence-urls: {len(evidence)} collected, {scraped} scraped, {search_only} search-only, {failed} failed")
        if claim_results:
            print(f"claim-check: {match_count}/{len(claim_results)} match ({result['claim_check']['match_pct']})")
        print(f"report-structure: sections {result['report_structure']['sections']}, completion-time {result['report_structure']['completion_time']}")
        print(f"verdict: {final_verdict.value}")
        tv = result["type_validation"]
        print(f"type-validation: {tv['verdict']}")
        for w in tv.get("warnings", []):
            print(f"  ⚠ {w}")
        for w in result.get("source_alignment", {}).get("warnings", []):
            print(f"  ⚠ {w}")

    # legal hallucination check (optional, does not affect verdict)
    cfg = load_config()
    api_key = cfg.get("api_keys", {}).get("yuandian_key", "")
    if api_key:
        try:
            legal_result = run_legal_check(run_dir, api_key)
            if legal_result is not None:
                result["legal_hallucination_check"] = legal_result
                if not args.json and legal_result.get("issues"):
                    print(f"legal-hallucination: {len(legal_result['issues'])} issues found")
        except Exception as e:
            if not args.json:
                print(f"legal-hallucination: ⚠ 检测不可用 ({e})")
            result["legal_hallucination_check"] = {"checked": False, "error": str(e)}

    return result
