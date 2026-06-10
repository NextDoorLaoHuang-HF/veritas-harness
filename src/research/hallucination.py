import re
from pathlib import Path


LEGAL_PATTERNS = [
    re.compile(r'《[^》]+》'),           # 《民法典》
    re.compile(r'第\s*\d+\s*条'),       # 第1200条
    re.compile(r'（\d{4}）[^》]+?\d+号'),  # （2019）苏0206民初3374号
]


# Known non-issue conclusions from hall_detect API
HALL_DETECT_OK = {"语义比对一致", "语义比对无法确定"}


def detect_legal_references(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in LEGAL_PATTERNS)


def run_legal_check(run_dir: Path, api_key: str) -> dict | None:
    draft = run_dir / "draft-report.md"
    if not draft.exists():
        return None
    text = draft.read_text()
    if not detect_legal_references(text):
        return None

    from research.backends.yuandian import YuandianBackend
    backend = YuandianBackend(api_key=api_key)
    result = backend.detect_hallucinations(text)

    regs = result.get("regulations", [])
    cases = result.get("cases", [])

    issues = []
    for r in regs:
        sc = r.get("semantic_compare", {})
        conclusion = sc.get("结论", "")
        if conclusion and conclusion not in HALL_DETECT_OK:
            issues.append({
                "type": "法规",
                "name": r.get("name", ""),
                "clause": r.get("clause", ""),
                "conclusion": conclusion,
                "detail": sc.get("说明", ""),
            })
    for c in cases:
        if c.get("case_number") and not c.get("think_tank_content"):
            issues.append({
                "type": "案例",
                "case_number": c.get("case_number", ""),
                "conclusion": "未命中权威来源",
                "detail": "案号未能匹配权威案例库",
            })

    return {
        "checked": True,
        "total_regulations": len(regs),
        "total_cases": len(cases),
        "issues": issues,
    }
