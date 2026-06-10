"""Inject-cases: 从 run-dir 抽取的 case 按主题词分配到报告章节。

设计目标：消除"附录式"报告——所有案号按争点融入正文。
- 读 query-*.json / scrape-*.json / scrape-manifest.tsv，抽取 case
- 按章节关键词表（type-specific 默认 + 用户自定义）打分
- 输出 case-allocation.md：每章推荐 2-3 个最相关 case
- 不直接修改 draft.md（避免 Agent 失去对案例筛选的最终控制权）

为什么是"推荐"而非"注入"：
- LLM/Agent 才能做语义级"哪个 case 配哪个段落"的判断
- CLI 只能做关键词级初筛
- Agent 拿到 case-allocation.md 后手工挑选 + 改写为论理段

主题词表设计：每个 type 一组默认关键词；用户可 --section-keywords 覆盖。
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# ====== 默认主题词 → 章节 映射 ======
# 格式：{ "章节编号": ("章节标题", [关键词]) }

DEFAULT_KEYWORDS: dict[str, dict[str, tuple[str, list[str]]]] = {
    "practical-guide": {
        "一、": ("核心前提/基础概念", [
            "劳动", "劳务", "用工", "关系", "身份", "冒名", "假冒", "虚构",
            "合同", "有效", "无效", "成立", "主体", "用工主体",
        ]),
        "二、": ("认定标准/核心要件", [
            "工伤", "认定", "工亡", "事故", "上下班", "工作时间", "工作原因",
            "工作时间", "工作场所", "履职", "因工", "三工", "视同", "举证",
        ]),
        "三、": ("法律后果/责任承担", [
            "责任", "赔偿", "损害", "承担", "比例", "过错", "主要", "次要",
            "基金", "保险", "工伤保险", "雇主责任", "雇主", "分担",
            "判决", "确认", "认定",
        ]),
        "四、": ("应对方案/操作步骤", [
            "追偿", "追偿权", "代位", "求偿", "风险", "防范", "合规",
            "操作", "程序", "申报", "时限", "诉讼", "仲裁", "起诉",
            "审查", "核实", "风险",
        ]),
    },
    "deep-research": {
        "1.1": ("子章节（一）研究维度", [
            "制度", "框架", "体系", "管辖", "原则", "适用", "范围",
        ]),
        "1.2": ("子章节（一）执行/费用维度", [
            "费用", "成本", "执行", "明细", "效率",
        ]),
        "1.3": ("子章节（二）替代/特殊路径", [
            "替代", "特殊", "跨境", "例外", "但书",
        ]),
    },
    "case-research": {
        # case-research 不做"按章节分配"——它本身就是案例集合
        # 仅做"按争点分组"：去重 + 提取争点
        "_default": ("全部案例", []),
    },
}


# ====== 案号正则 ======
# 统一与 distribution.py 的 CASE_NO_RE 同源：
# - (YYYY)XX民XX号 / （YYYY）XX民XX号  全/半角括号
# - YYYY.XXXX号  简化案号
CASE_NO_RE = re.compile(
    r"[（(]\d{4}[）)][\s\S]{1,40}?[\dA-Za-z一-鿿]+号"
    r"|"
    r"\d{4}\.[\dA-Za-z一-鿿]+号",
    re.UNICODE,
)


def extract_cases_from_run(run_dir: Path) -> list[dict[str, Any]]:
    """从 run-dir 下的 query-*.json / scrape-*.json / scrape-manifest.tsv 抽取所有 case。

    标准化字段：case_no, title, url, content, source
    """
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()

    for json_path in sorted(run_dir.glob("query-*.json")):
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict) or "results" not in data:
            continue
        for r in data["results"]:
            if not isinstance(r, dict):
                continue
            # query-* 来自 websearch，案号通常在 title/snippet 中
            blob = f"{r.get('title','')}\n{r.get('snippet','')}"
            for m in CASE_NO_RE.finditer(blob):
                cn = m.group(0).strip()
                key = cn
                if key in seen:
                    continue
                seen.add(key)
                cases.append({
                    "case_no": cn,
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("snippet", ""),
                    "content": r.get("snippet", ""),
                    "source": json_path.name,
                })

    for json_path in sorted(run_dir.rglob("scrape-*.json")):
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and isinstance(data.get("data"), list):
            items = data.get("data", [])
        elif isinstance(data, dict):
            items = [data]
        else:
            items = []
        if not isinstance(items, list):
            continue
        for r in items:
            if not isinstance(r, dict):
                continue
            cn = (r.get("case_no") or "").strip()
            if not cn:
                # 尝试从 content 提取
                blob = "\n".join(str(r.get(k, "")) for k in ("title", "content", "markdown", "text"))
                m = CASE_NO_RE.search(blob)
                if m:
                    cn = m.group(0).strip()
            if not cn:
                continue
            content = r.get("content") or r.get("markdown") or r.get("text") or ""
            key = cn
            if key in seen:
                # 已有 → 合并内容（保留更长的 content）
                for existing in cases:
                    if existing["case_no"] == cn and len(content) > len(existing.get("content","")):
                        existing["content"] = content
                        existing["url"] = existing["url"] or r.get("url", "")
                        existing["title"] = existing["title"] or r.get("title", "")
                continue
            seen.add(key)
            cases.append({
                "case_no": cn,
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
                "content": content,
                "source": json_path.name,
            })

    # 也支持 scrape-manifest.tsv 引用的 scrape-*.json（web 抓取的 case 文章）
    manifest = run_dir / "scrape-manifest.tsv"
    if manifest.exists():
        for line in manifest.read_text().splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            url, file_rel = parts[0], parts[1]
            scrape_path = run_dir / file_rel
            if not scrape_path.exists():
                continue
            try:
                data = json.loads(scrape_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            blob = json.dumps(data, ensure_ascii=False)
            for m in CASE_NO_RE.finditer(blob):
                cn = m.group(0).strip()
                if cn in seen:
                    continue
                seen.add(cn)
                cases.append({
                    "case_no": cn,
                    "title": data.get("title", "") if isinstance(data, dict) else "",
                    "url": url,
                    "snippet": (data.get("text", "") or "")[:200] if isinstance(data, dict) else "",
                    "content": data.get("text", "") if isinstance(data, dict) else "",
                    "source": file_rel,
                })

    return cases


def score_case_against_section(case: dict[str, Any], keywords: list[str]) -> tuple[int, list[str]]:
    """对单个 case 统计章节关键词命中数 + 命中的关键词列表。"""
    text = f"{case.get('title','')}\n{case.get('content','')}"
    hits = [k for k in keywords if k in text]
    return len(hits), hits


def allocate_cases(
    cases: list[dict[str, Any]],
    section_map: dict[str, tuple[str, list[str]]],
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """对每章返回 top_n 个最相关 case + 命中关键词。"""
    allocations = []
    for section_id, (section_title, keywords) in section_map.items():
        scored = []
        for case in cases:
            score, hits = score_case_against_section(case, keywords)
            if score > 0:
                scored.append((score, hits, case))
        scored.sort(key=lambda x: (-x[0], x[2]["case_no"]))  # score 降序，案号字典序
        recommendations = []
        for score, hits, case in scored[:top_n]:
            recommendations.append({
                "case_no": case["case_no"],
                "title": case.get("title", "")[:80],
                "score": score,
                "hits": hits,
                "url": case.get("url", ""),
                "content_preview": case.get("content", "")[:200],
            })
        allocations.append({
            "section_id": section_id,
            "section_title": section_title,
            "keywords": keywords,
            "recommendations": recommendations,
            "total_candidates": len(scored),
        })
    return allocations


def parse_user_section_keywords(spec: str) -> dict[str, list[str]]:
    """解析用户 --section-keywords 字符串。

    格式："章1:词1,词2;章2:词3,词4"
    """
    if not spec:
        return {}
    result = {}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        sec_id, kw_str = chunk.split(":", 1)
        kws = [k.strip() for k in kw_str.split(",") if k.strip()]
        if kws:
            result[sec_id.strip()] = kws
    return result


def render_allocation_md(allocations: list[dict[str, Any]], topic: str, total_cases: int) -> str:
    """渲染 case-allocation.md 推荐表。"""
    lines = [
        f"# 案例分配建议 — {topic}",
        "",
        f"> 来源：自动从 run-dir 抽取 **{total_cases}** 个案号，按章节关键词打分推荐",
        f"> 提示：本文件**仅供参考**，由 Agent 最终筛选并融入正文（详见 SKILL.md「证据分配点」章节）",
        "",
        "## 总览",
        "",
        "| 章节 | 主题 | 候选数 | 推荐 |",
        "|------|------|------|------|",
    ]
    for a in allocations:
        rec_str = " · ".join(r["case_no"] for r in a["recommendations"]) or "（无匹配）"
        lines.append(f"| {a['section_id']} | {a['section_title']} | {a['total_candidates']} | {rec_str} |")
    lines.append("")

    for a in allocations:
        lines.append(f"## {a['section_id']} {a['section_title']}")
        lines.append("")
        lines.append(f"**关键词**：{', '.join(a['keywords'])}")
        lines.append("")
        if not a["recommendations"]:
            lines.append("> ⚠ 无候选案例。可选方案：")
            lines.append("> 1. 调整该章节关键词，重跑 `inject-cases`")
            lines.append("> 2. 用 `veritas search --backend yuandian --type case` 补充案例")
            lines.append("> 3. 省略该章节的证据分配点（参考 templates 中『无相关案例时省略』规则）")
        else:
            lines.append("| 排序 | 案号 | 命中关键词 | 标题（截断） | 链接 |")
            lines.append("|:---:|------|----------|------------|------|")
            for i, rec in enumerate(a["recommendations"], 1):
                hits_str = "、".join(rec["hits"])
                lines.append(
                    f"| {i} | `{rec['case_no']}` | {hits_str} | "
                    f"{rec['title']} | {rec['url'] or '—'} |"
                )
            lines.append("")
            lines.append("**候选内容预览**（用于快速判断相关性）：")
            lines.append("")
            for rec in a["recommendations"]:
                lines.append(f"- **{rec['case_no']}**：{rec['content_preview']}…")
            lines.append("")

    lines.extend([
        "---",
        "",
        "## 使用方法",
        "",
        "1. **打开 draft-report.md**，定位到 `📌 证据分配点 N` 占位符",
        "2. 根据本章 `推荐` 列挑选 2-3 个最相关案号",
        "3. **改写为论理段**而非仅插入案号字符串——例如：",
        "",
        "   ```markdown",
        "   > 参见（YYYY）XX民XX号案：法院认为……[一句话核心规则]……。",
        "   ```",
        "",
        "4. **禁止**直接复制 case-allocation.md 到 draft.md；这是建议表，不是注入脚本",
        "5. **最终质量门**：`veritas verify --run-dir <path>` 会检查每章是否有 ≥1 案号、案号是否全在尾部 30%",
    ])
    return "\n".join(lines) + "\n"


def cmd_inject_cases(args) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"Error: --run-dir {run_dir} is not a directory")
        return 1

    cases = extract_cases_from_run(run_dir)
    if not cases:
        print(f"⚠ No cases found in {run_dir}")
        print("  Check: query-*.json / scrape-*.json / scrape-manifest.tsv")
        return 1

    # 决定 section_map
    report_type = getattr(args, "type", None) or "practical-guide"
    section_map_raw = DEFAULT_KEYWORDS.get(report_type, DEFAULT_KEYWORDS["practical-guide"])

    # 用户自定义关键词可覆盖
    user_kw = parse_user_section_keywords(getattr(args, "section_keywords", "") or "")
    if user_kw:
        section_map = {}
        for sec_id, (default_title, default_kws) in section_map_raw.items():
            if sec_id in user_kw:
                section_map[sec_id] = (default_title, user_kw[sec_id])
            else:
                section_map[sec_id] = (default_title, default_kws)
    else:
        section_map = {k: (t, list(kws)) for k, (t, kws) in section_map_raw.items()}

    allocations = allocate_cases(cases, section_map, top_n=args.top_n)

    # 输出
    out_path = Path(args.output) if args.output else run_dir / "case-allocation.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    md = render_allocation_md(allocations, args.topic or run_dir.name, len(cases))
    out_path.write_text(md)

    # 摘要
    print(f"✔ Analyzed {len(cases)} cases from {run_dir}")
    for a in allocations:
        n = len(a["recommendations"])
        marker = "✓" if n > 0 else "⚠"
        print(f"  {marker} {a['section_id']} {a['section_title']}: {a['total_candidates']} 候选 → 推荐 {n}")
    print(f"✔ Wrote {out_path}")

    if not args.json:
        print()
        print("下一步：")
        print(f"  1. 打开 {out_path} 查看每章推荐案号")
        print(f"  2. 手工挑选 + 改写为论理段，填入 draft-report.md 的证据分配点")
        print(f"  3. 运行 `veritas verify --run-dir {run_dir}` 检查证据分布")
    else:
        import json
        print(json.dumps({
            "total_cases": len(cases),
            "allocations": [
                {
                    "section_id": a["section_id"],
                    "section_title": a["section_title"],
                    "total_candidates": a["total_candidates"],
                    "recommendations": a["recommendations"],
                }
                for a in allocations
            ],
        }, ensure_ascii=False, indent=2))
    return 0
