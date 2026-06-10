# 法律引用校验自动嵌入 verify 流程

## 动机

法律用户在使用 `research verify` 验证证据后，需要额外运行 `research legal verify-citations` 来检测法律引用幻觉。两者的前置条件（运行目录、草稿文件）完全重叠，且法律用户每次都需要手动执行两个命令。

将法律引用校验自动嵌入 `verify` 流程，满足条件时静默追加校验结果，用户可以一次命令完成完整审计。

## 设计

### 核心原则

1. **不增加非法律用户的认知负担** — 未配置 `YUANDIAN_API_KEY` 或草稿不含法律引用时，行为完全不变
2. **不阻塞主流程** — `legal_hallucination_check` 结果仅作为信息输出，不影响 verdict
3. **保留独立入口** — `research legal verify-citations` 仍然可用，支持 `--text`/`--file` 手动指定

## 架构

### 新增文件: `src/research/hallucination.py`

```
src/research/hallucination.py
```

两个公开函数：

#### `detect_legal_references(text: str) -> bool`

检测文本中是否包含法律引用特征：

| 模式 | 正则 | 示例 |
|------|------|------|
| 法规名称 | `《[^》]+》` | 《民法典》 |
| 法条引用 | `第\s*\d+\s*条` | 第1200条 |
| 案号 | `（\d{4}）[^》]+?\d+号` | （2019）苏0206民初3374号 |

返回 `True` 当任意模式匹配。

#### `run_legal_check(run_dir: Path, api_key: str) -> dict | None`

流程：

1. 读取 `run_dir / "draft-report.md"`
2. 调用 `detect_legal_references(text)` — 若无法律引用，返回 `None`
3. 实例化 `YuandianBackend(api_key=api_key)`
4. 调用 `backend.detect_hallucinations(text)` — 获取 `hall_detect` API 原始结果
5. 解析 `regulations` 和 `cases`，筛选出问题项
6. 返回结构化 dict：

```python
{
    "checked": True,
    "total_regulations": 3,
    "total_cases": 1,
    "issues": [
        {
            "type": "法规",
            "name": "民法典",
            "clause": "第一千二百条",
            "conclusion": "语义比对不一致",
            "detail": "...",
        },
    ],
}
```

### 修改文件: `src/research/verify.py`

在 `run_verify()` 函数末尾，返回 result 之前追加：

```python
from research.config import load_config
from research.hallucination import run_legal_check

cfg = load_config()
api_key = cfg.get("api_keys", {}).get("yuandian_key", "")
if api_key:
    legal_result = run_legal_check(run_dir, api_key)
    if legal_result is not None:
        result["legal_hallucination_check"] = legal_result
        if not args.json and legal_result.get("issues"):
            print(f"legal-hallucination: {len(legal_result['issues'])} issues found")
```

关键点：
- `run_legal_check` 返回 `None` 表示无需执行（无法律引用），此时 result 中不添加该字段
- `legal_hallucination_check` 始终包含 `"checked": True`（曾尝试检测）
- verdict 计算逻辑不变

### 输出示例

```json
{
    "evidence_urls": {"total": 10, ...},
    "claim_check": {"total": 5, "match": 3, "match_pct": "60%"},
    "report_structure": {"sections": "5/5", "completion_time": "✓"},
    "legal_hallucination_check": {
        "checked": true,
        "total_regulations": 3,
        "total_cases": 1,
        "issues": [...]
    },
    "verdict": "pass"
}
```

命令行输出：

```
evidence-urls: 10 collected, 8 scraped, 2 search-only, 0 failed
claim-check: 3/5 match (60%)
report-structure: sections 5/5, completion-time ✓
legal-hallucination: 2 issues found
verdict: pass
```

## 测试

### 新增文件: `tests/test_hallucination.py`

| 测试 | 内容 |
|------|------|
| `test_detect_legal_references_law_name` | 《民法典》→ True |
| `test_detect_legal_references_clause` | 第1200条 → True |
| `test_detect_legal_references_case_number` | 案号 → True |
| `test_detect_legal_references_non_legal` | 普通文本 → False |
| `test_detect_legal_references_empty` | 空字符串 → False |
| `test_run_legal_check_no_legal_refs` | 无法律引用 → None |
| `test_run_legal_check_with_issues` | 有引用且有 API 结果 → 返回 issues |
| `test_run_legal_check_no_issues` | 有引用但 API 返回无问题 → 返回空 issues |
| `test_run_legal_check_missing_draft` | 草稿不存在 → 返回 None |
| `test_verify_hallucination_integration` | verify 端到端集成测试，mock YuandianBackend |

## 文件清单

### 新增
- `src/research/hallucination.py`
- `tests/test_hallucination.py`

### 修改
- `src/research/verify.py`

## 不变部分

- `cli.py` 的 `cmd_legal()` — `research legal verify-citations` 行为不变
- `backends/yuandian.py` — 不修改
- `evidence.py`, `finalize.py`, `search.py`, `scrape.py` — 不修改
- verdict 计算逻辑 — 不修改
