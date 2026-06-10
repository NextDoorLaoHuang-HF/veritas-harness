# Legal Hallucination Check Auto-Embed into Verify

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically run legal citation hallucination check during `research verify` when `YUANDIAN_API_KEY` is configured and the draft contains legal references.

**Architecture:** Add `hallucination.py` with legal reference detection heuristics and `hall_detect` API wrapper; modify `verify.py` to call it conditionally without affecting verdict.

**Tech Stack:** Python, regex, requests (via existing YuandianBackend), pytest.

---

### Task 1: Create `hallucination.py` with prototype detection

**Files:**
- Create: `src/research/hallucination.py`
- Test: (test file in Task 2)

- [ ] **Step 1: Write `detect_legal_references()`**

```python
import re
from pathlib import Path


LEGAL_PATTERNS = [
    re.compile(r'《[^》]+》'),           # 《民法典》
    re.compile(r'第\s*\d+\s*条'),       # 第1200条
    re.compile(r'（\d{4}）[^》]+?\d+号'),  # （2019）苏0206民初3374号
]


def detect_legal_references(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in LEGAL_PATTERNS)
```

- [ ] **Step 2: Write `run_legal_check()` with `YuandianBackend` integration**

```python
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
        if conclusion and "一致" not in conclusion and "无法" not in conclusion:
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
```

---

### Task 2: Write tests for `hallucination.py`

**Files:**
- Create: `tests/test_hallucination.py`
- Depends: `src/research/hallucination.py` (Task 1)

- [ ] **Step 1: Write test file with 10 tests**

```python
import json
import pytest
from pathlib import Path
from research.hallucination import detect_legal_references, run_legal_check


class TestDetectLegalReferences:
    def test_law_name(self):
        assert detect_legal_references("根据《民法典》相关规定") is True

    def test_clause(self):
        assert detect_legal_references("依照第一千二百条处理") is True

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
        assert result["total_cases"] == 0
        assert len(result["issues"]) == 1
        assert result["issues"][0]["conclusion"] == "语义比对不一致"

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
```

- [ ] **Step 2: Run tests and confirm they pass**

Run: `PYTHONPATH=src /tmp/research-venv/bin/pytest tests/test_hallucination.py -v`

Expected: 9/9 passed

- [ ] **Step 3: Commit**

```bash
git add src/research/hallucination.py tests/test_hallucination.py
git commit -m "feat: add legal reference detection and run_legal_check utility"
```

---

### Task 3: Integrate legal check into `verify.py`

**Files:**
- Modify: `src/research/verify.py`

- [ ] **Step 1: Add integration code at end of `run_verify()` before return**

Find the `result = {` block (around line 101) and the final `return result` (line 127). Insert legal check code between the human-readable output block and the return:

```python
    # legal hallucination check (optional, does not affect verdict)
    cfg = load_config()
    api_key = cfg.get("api_keys", {}).get("yuandian_key", "")
    if api_key:
        legal_result = run_legal_check(run_dir, api_key)
        if legal_result is not None:
            result["legal_hallucination_check"] = legal_result
            if not args.json and legal_result.get("issues"):
                print(f"legal-hallucination: {len(legal_result['issues'])} issues found")

    return result
```

And add the import at the top:

```python
from research.hallucination import run_legal_check
from research.config import load_config
```

- [ ] **Step 2: Run existing verify tests to confirm no regression**

Run: `PYTHONPATH=src /tmp/research-venv/bin/pytest tests/test_verify.py -v`

Expected: all existing tests pass

- [ ] **Step 3: Add integration test for verify + hallucination check**

Add to `tests/test_hallucination.py`:

```python
class TestVerifyIntegration:
    def test_verify_with_legal_check(self, tmp_path, mocker):
        from research.verify import run_verify

        # Simulate a run directory
        (tmp_path / "query-test.json").write_text(json.dumps({
            "results": [{"url": "http://example.com", "title": "test"}]
        }))
        (tmp_path / "scrape-manifest.tsv").write_text("url\tfile")
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\n## 关键发现\n\n## 证据与来源\n\n## 置信度\n\n## 未解决问题\n\n"
            "根据《民法典》第一千二百条规定...\n\n*完成时间: 2026-01-01 UTC*"
        )
        (tmp_path / "source-claims.tsv").write_text("url\tstatus\nhttp://example.com\t200")

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

        class FakeArgs:
            run_dir = str(tmp_path)
            json = False
            allow_repairable = False

        result = run_verify(FakeArgs())
        assert "legal_hallucination_check" in result
        assert result["legal_hallucination_check"]["checked"] is True
        assert result["verdict"] == "pass"

    def test_verify_without_legal_key(self, tmp_path, mocker):
        from research.verify import run_verify

        (tmp_path / "query-test.json").write_text(json.dumps({
            "results": [{"url": "http://example.com", "title": "test"}]
        }))
        (tmp_path / "scrape-manifest.tsv").write_text("url\tfile")
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\n## 关键发现\n\n## 证据与来源\n\n## 置信度\n\n## 未解决问题\n\n"
            "*完成时间: 2026-01-01 UTC*"
        )
        (tmp_path / "source-claims.tsv").write_text("url\tstatus\nhttp://example.com\t200")

        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": ""},
        })

        class FakeArgs:
            run_dir = str(tmp_path)
            json = False
            allow_repairable = False

        result = run_verify(FakeArgs())
        assert "legal_hallucination_check" not in result
        assert result["verdict"] == "pass"

    def test_verify_no_legal_refs(self, tmp_path, mocker):
        from research.verify import run_verify

        (tmp_path / "query-test.json").write_text(json.dumps({
            "results": [{"url": "http://example.com", "title": "test"}]
        }))
        (tmp_path / "scrape-manifest.tsv").write_text("url\tfile")
        (tmp_path / "draft-report.md").write_text(
            "## 结论\n\n## 关键发现\n\n## 证据与来源\n\n## 置信度\n\n## 未解决问题\n\n"
            "普通文本内容，没有法律引用\n\n*完成时间: 2026-01-01 UTC*"
        )
        (tmp_path / "source-claims.tsv").write_text("url\tstatus\nhttp://example.com\t200")

        mocker.patch("research.config.load_config", return_value={
            "api_keys": {"yuandian_key": "test-key"},
        })

        class FakeArgs:
            run_dir = str(tmp_path)
            json = False
            allow_repairable = False

        result = run_verify(FakeArgs())
        # No legal refs → run_legal_check returns None → no key in result
        assert "legal_hallucination_check" not in result
        assert result["verdict"] == "pass"
```

- [ ] **Step 4: Run all tests**

Run: `PYTHONPATH=src /tmp/research-venv/bin/pytest tests/ -v`

Expected: all 87+12 = 99 tests pass

- [ ] **Step 5: Commit**

```bash
git add src/research/verify.py tests/test_hallucination.py
git commit -m "feat: embed legal hallucination check into verify command"
```

---

### Self-Review Checklist

1. **Spec coverage:**
   - `detect_legal_references(text)` — Task 1 Step 1 ✓
   - `run_legal_check(run_dir, api_key)` — Task 1 Step 2 ✓
   - verify.py integration — Task 3 Step 1 ✓
   - 3 legal patterns (law name, clause, case number) — Task 1 Step 1 ✓
   - No effect on verdict — Task 3 Step 1 (code before return, no verdict mutation) ✓
   - Only runs with api_key + legal refs — Test `test_verify_without_legal_key` + `test_verify_no_legal_refs` ✓
   - `legal verify-citations` unchanged — no modifications to cli.py ✓
   - Non-legal text skipped by `detect_legal_references` — Task 2 `test_non_legal` ✓
   - `None` return when no legal refs — Task 1 Step 2 (early return None) ✓
   - Human-readable print when issues found — Task 3 Step 1 ✓

2. **No placeholders** — all code is complete, no TBD/TODO.

3. **Type consistency** — all function signatures, dict keys, and return types match across tasks. `None` for skip, `dict` with `checked`, `total_regulations`, `total_cases`, `issues` keys for result.
