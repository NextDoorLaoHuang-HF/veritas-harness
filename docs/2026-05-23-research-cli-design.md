# Research CLI — 设计文档

> 独立的 CLI 工具 + AI Skill，封装严谨的联网研究流程。
> 核心差异化：证据审计与引用验证流水线，搜索/抓取为 commodity 能力。

## 1. 仓库结构

```
/root/research-cli/
├── pyproject.toml                # CLI 入口：research = "research.cli:main"
├── SKILL.md                     # AI Agent 学习手册
├── README.md
├── src/
│   └── research/
│       ├── __init__.py
│       ├── cli.py               # 原子命令：search/scrape/verify/finalize
│       ├── config.py            # 配置加载（环境变量 + config.toml）
│       ├── evidence.py          # 证据收集（被 verify + finalize 共用）
│       ├── backends/
│       │   ├── __init__.py
│       │   ├── protocol.py      # ResearchBackend 抽象接口（预留扩展）
│       │   └── reader_selfhost.py  # reader-selfhost HTTP 后端
│       ├── search.py            # 搜索编排（多关键词并发）
│       ├── scrape.py            # 抓取编排（多 URL 并发）
│       ├── verify.py            # 证据审计：claim 比对 + 结构审计
│       └── finalize.py          # 报告收口（← finalize_firecrawl_report）
├── tests/
│   ├── test_search.py
│   ├── test_scrape.py
│   ├── test_evidence.py
│   ├── test_verify.py
│   ├── test_finalize.py
│   └── test_backend_reader_selfhost.py
└── config.toml.example
```

**继承关系**：
- `evidence.py` = `source_audit_gate.py` 的 `collect_evidence()`，提取为独立函数，被 verify + finalize 共用
- `verify.py` = `source_audit_gate.py` 的 `audit_report()` + `summarize_audit()` + `check_claims()`
- `finalize.py` = `finalize_firecrawl_report.py` 的草稿解析 + 证据表提取 + `[S#]` 标签分配 + URL 链接化 + FINAL_STATUS 判定 + 4 工件产出
- `search.py` / `scrape.py` / `backends/` = 新写（替换现有 reader_firecrawl.py 的 commodity 部分）
- `cli.py` = 新写（argparse）

**不包含**：
- Firecrawl 后端（未来按需添加）
- `research run` 交互命令
- OpenClaw 插件 infrastructure（hook、sandbox、dispatch）
- 飞书文档发布
- 自有浏览器交互能力（登录墙等复杂场景由 Agent 平台工具兜底）

## 2. 后端抽象层

### ResearchBackend 接口

```python
@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str          # 域名
    published: str | None  # ISO 8601 日期

@dataclass
class ScrapeResult:
    title: str
    url: str              # 重定向后的最终 URL
    markdown: str
    text: str
    page_type: str        # article|document_page|login_page|list_page|...
    content_quality: str  # full|partial|empty
    metadata: dict        # 引擎、缓存状态等

class ResearchBackend(ABC):
    def search(self, query: str, count: int = 10, **kwargs) -> list[SearchResult]: ...
    def scrape(self, url: str, **kwargs) -> ScrapeResult: ...
    def health(self) -> dict: ...
```

### reader-selfhost 实现

- `search` → `GET /search?q=<query>&count=N&format=json`（可选 `&site=<domain>` 限定来源）
- `scrape` → `GET /read?url=<URL>&format=json`
- `health` → `GET /health`

参数映射：
- `x-engine=browser` 请求头 → 浏览器渲染模式
- `x-timeout` 请求头 → 超时控制
- `site` 参数 → 传递给后端 API，后端不支持时在客户端侧按 domain 过滤（降级）
- 响应以 `format=json` 解析，结果归一化为 `SearchResult`/`ScrapeResult`

### 配置

三层优先级（高 → 低）：

1. 环境变量
   - `READER_API_URL`（默认 `http://localhost:3099`）
   - `READER_API_KEY`
   - `READER_TIMEOUT_SECONDS`（默认 30）
2. `$XDG_CONFIG_HOME/research-cli/config.toml`（默认 `~/.config/research-cli/config.toml`）
3. 内置默认值

```toml
[backend]
url = "http://localhost:3099"
api_key = ""

[search]
default_limit = 10
max_concurrent = 4

[scrape]
max_concurrent = 4
cache_ttl_ms = 3600000

[run_dir]
base = ".research/runs"
```

## 3. CLI 接口

### 命令总览

```
research search <query> [<query2> ...]  [options]
research scrape   <url> [<url2> ...]    [options]
research verify   --run-dir <path>      [options]
research finalize --run-dir <path>      [options]
```

每个命令支持 `-h/--help`、`--json`。默认输出 human-readable。

### research search

```
research search "餐饮新规 2026" "食品安全 政策 2026" --limit 10 --json
```

行为：
- 接收 1 个或多个关键词
- **并发**搜索所有关键词
- 跨关键词去重（相同 URL 只保留一个）
- 附带 `--scrape` 时对每个结果正文做浅抓取
- 结果写入 `RUN_DIR/query-N.json`（JSON 格式，Firecrawl 兼容结构）
- `--run-dir` 指定输出目录，不传时自动生成 `.research/runs/<日期>-<topic>/` 并打印路径

输出（human-readable）：
```
搜索完成：[3 个关键词 × 10 条 = 30 个结果，去重后 22 个唯一来源]
1. [title](url) — source
2. ...
```

输出（`--json`）：
```json
{
  "query": ["餐饮新规 2026", "食品安全 政策 2026"],
  "count": 22,
  "results": [{ "title": "...", "url": "...", "snippet": "...", "source": "..." }],
  "provider": "reader-selfhost"
}
```

参数：
| 参数 | 说明 |
|------|------|
| `query ...` | 1 个或多个查询词 |
| `--run-dir <path>` | 研究运行目录（不传则自动生成） |
| `--limit N` | 每个关键词的结果数（默认 10） |
| `--scrape` | 搜索结果附带正文浅抓取 |
| `--json` | 结构化输出 |
| `-o` / `--output` | 指定输出文件路径 |
| `--site <domain>` | 限定来源域名 |

### research scrape

```
research scrape "https://example.com/article1" "https://example.com/article2" --json
```

行为：
- 接收 1 个或多个 URL
- 并发抓取（`max_concurrent` 控制）
- `--run-dir` 指定输出目录，不传时自动生成并打印路径
- 写入 `RUN_DIR/scrape-{n}.json`

输出（`--json`）：
```json
{
  "url": "https://example.com/article1",
  "status": 200,
  "title": "...",
  "markdown": "...",
  "pageType": "article",
  "contentQuality": "full",
  "blockedReason": ""
}
```

参数：
| 参数 | 说明 |
|------|------|
| `url ...` | 1 个或多个 URL |
| `--run-dir <path>` | 研究运行目录（不传则自动生成） |
| `--format <type>` | markdown（默认）/ html / text |
| `--browser` | 强制浏览器渲染 |
| `--wait-for <ms>` | 渲染等待时间 |
| `--timeout <s>` | 单次超时 |
| `--json` | 结构化输出 |
| `-o` | 指定输出文件 |

### research verify

```
research verify --run-dir .research/runs/2026-05-23-topic
```

行为：
1. `evidence.collect_evidence(run_dir)` — 扫描 RUN_DIR 所有工件（search JSON、scrape 结果、manifest）
2. `check_claims()` — 对比 claims 表中的声明状态 vs 实际采集状态
3. 检查最终报告结构：5 段标题、UTC 完成时间、来源角色行、证据表 URL 一致性
4. 输出审计报告

输出：
```
evidence-urls: 15 collected, 8 scraped, 4 search-only, 3 failed
claim-check: 12/12 match (100%)
report-structure: 5 sections ✓, completion-time ✓, source-labels ✓, FINAL_STATUS=pass
verdict: pass
```

参数：
| 参数 | 说明 |
|------|------|
| `--run-dir <path>` | 研究运行目录（必填） |
| `--json` | 结构化输出 |
| `--allow-repairable` | 可修复问题不报 fatal |
| `--fix-manifest` | 自动补全 manifest |

### research finalize

```
research finalize --run-dir .research/runs/2026-05-23-topic --report-stdin <<'EOF'
...草稿正文...
EOF
```

行为（← finalize_firecrawl_report.py）：
1. 解析草稿 → 提取证据表
2. 调用 `evidence.collect_evidence()` 收集 RUN_DIR 证据
3. backfill manifest（自动匹配孤立抓取文件）
4. 修复 URL（重定向、小差异）
5. 来源分类：admissible / dropped
6. 分配 [S1]、[S2]... 标签
7. 链接化：`[S1]` → `[S1](url)`
8. 确定 FINAL_STATUS
9. 写 4 个工件

产出：
```
✔ final-report.md
✔ source-claims.tsv
✔ source-audit.tsv
✔ finalize-summary.json
FINAL_STATUS=pass
REPORT=/abs/path/final-report.md
```

参数：
| 参数 | 说明 |
|------|------|
| `--run-dir <path>` | 研究运行目录（必填） |
| `--report <file>` | 草稿文件路径 |
| `--report-stdin` | 从 stdin 读取草稿 |
| `--output <md>` | 最终报告路径 |
| `--summary <json>` | summary 输出路径 |

## 4. RUN_DIR 结构

每个研究任务一个独立目录：

```
.research/runs/2026-05-23-topic-name/
├── query-1.json              # 第 1 个关键词搜索结果
├── query-2.json              # 第 2 个关键词搜索结果
├── scrape-manifest.tsv        # 抓取记录（url  / 文件名）
├── scrape-1.json              # 第 1 个 URL 抓取结果
├── scrape-2.json              # 第 2 个 URL 抓取结果
├── draft-report.md            # Agent 草稿（输入）
├── final-report.md            # 最终报告（收口输出）
├── source-claims.tsv          # 来源声明表
├── source-audit.tsv           # 审计结果
└── finalize-summary.json      # 收口摘要
```

## 5. 核心流水线：evidence → verify + finalize

### evidence（公共模块）

来源自 `source_audit_gate.py` 的 `collect_evidence()`，被 verify 和 finalize 共同调用：

```python
def collect_evidence(run_dir: str) -> list[EvidenceItem]:
    """扫描 RUN_DIR 收集所有实际证据"""
    # 从 search JSON 提取 search-only 来源
    # 从 scrape manifest + scrape JSON 提取 scraped 来源
    # 检查失败/空页/反爬状态
    # 返回 [{url, status, label, date}, ...]
```

### verify

来源自 `source_audit_gate.py`，核心函数：

```python
def check_claims(claims_tsv: str, evidence: list[EvidenceItem]) -> list[ClaimResult]:
    """对比声明 vs 实际"""
    # 每个 claim：claimed_status vs actual_status
    # 输出：match / mismatch (overclaimed) / missing
```

```python
def audit_report(report_path: str) -> AuditVerdict:
    """结构审计"""
    # 5 sections present?
    # completion_time UTC?
    # source role lines match evidence?
    # confidence URLs match claims?
    # return pass / repairable / hard_fail
```

### finalize

来源自 `finalize_firecrawl_report.py`，核心函数：

```python
def parse_draft_report(text: str) -> DraftReport:
    """解析草稿 → sections + evidence rows"""
    # split by ## headers
    # extract 证据与来源 section → parse evidence rows
```

```python
def classify_sources(evidence, claims):
    """分类为 admissible / dropped"""
    # scraped + search-only → admissible
    # failed + missing → dropped
```

```python
def assign_labels(rows: list[EvidenceRow]) -> list[LabeledRow]:
    """分配 [S1], [S2]... 标签"""
```

```python
def linkify_report(report: str, labels: list[LabeledRow]) -> str:
    """[S1] → [S1](url)"""
```

```python
def determine_final_status(admissible, dropped, audit_verdict) -> str:
    """pass / degraded / fatal"""
```

```python
def write_artifacts(run_dir, report, claims, audit, summary):
    """写 4 个工件文件"""
```

## 6. 抓取降级兜底链

```
research scrape <url>                     → reader-selfhost 直连 fetch
  ↓ 空内容 / 反爬 / JS 渲染失败
research scrape <url> --browser           → reader-selfhost Puppeteer 渲染
  ↓ 仍失败（登录墙 / 复杂验证码）
Agent 用 `agent-browser` 工具定点操作     → 如 open / click / fill 等
```

CLI 不实现自有浏览器交互。Puppeteer 负责「一键渲染提取」，Agent 平台的浏览器工具负责「一步步交互探索」。两者职责分离。

## 7. SKILL.md 结构

Agent 读这份 skill 后应该知道：

1. **适用场景**：当用户要求联网搜索、事实核验、信息汇总时
2. **轻量 vs 深度判定**：时效/风险/多来源 → deep，否则 light
3. **CLI 快速参考**：search / scrape / verify / finalize 用法
4. **标准工作流**：

```
搜索 → Agent 出关键词计划 → CLI 并发搜索 → 筛选 URL
→ CLI 并发抓取 → Agent 写草稿 → CLI finalize 收口
```

5. **抓取降级链路**：直连 → `--browser` Puppeteer → Agent 端浏览器自动化工具（agent-browser / Playwright MCP 等）
6. **报告结构**：5 段标题（结论/关键发现/证据与来源/置信度/未解决问题）
7. **质量闸门**：FINAL_STATUS 含义、证据最低数、置信度标签
8. **多 Agent 协作模式（框架支持时启用）**：

### 并行研究方向调研
- 主 Agent 将研究问题拆解为 N 个独立子方向
- 每个子方向派发一个子 Agent，各自执行：关键词规划 → `research search` → URL 筛选 → `research scrape`
- 子 Agent 返回结构化研究笔记（含发现摘要 + 已收集证据 URL 列表）
- 主 Agent 汇总所有子方向结果，撰写综合草稿

### 独立多方验证
- 最终报告产出后，派发 2-3 个子 Agent 独立执行 `research verify --run-dir <path>`
- 每个子 Agent 各自做 claim 比对 + 结构审计
- 主 Agent 比对多份审计结果：一致则通过，不一致则标记争议点复查
- 避免单 Agent 的确认偏误

### 协作时序
```
主 Agent 拆解问题
  ├─ 子 Agent A: 方向 1 → search → scrape → 笔记
  ├─ 子 Agent B: 方向 2 → search → scrape → 笔记
  └─ 子 Agent C: 方向 3 → search → scrape → 笔记
主 Agent 汇总 → 写草稿 → finalize
  ├─ 子 Agent D: verify（独立）
  ├─ 子 Agent E: verify（独立）
  └─ 主 Agent: 比对审计 → 定稿
```

9. **禁忌**：不能凭记忆答时效问题、搜索摘要 ≠ 正文证据、转载 ≠ 独立来源

## 8. 配置规范

`config.toml` 完整示例：

```toml
[backend]
url = "http://localhost:3099"
api_key = ""

[search]
default_limit = 10
max_concurrent = 4
cache_ttl_ms = 300000

[scrape]
max_concurrent = 4
cache_ttl_ms = 3600000

[run_dir]
base = ".research/runs"

[finalize]
require_completion_time = true
min_evidence_urls = 3
min_evidence_dates = 0
```

## 9. 测试策略

| 模块 | 测试内容 |
|------|---------|
| `test_search.py` | 搜索编排、多关键词并发、去重、结果解析 |
| `test_scrape.py` | 并发控制、格式处理、超时、错误恢复 |
| `test_evidence.py` | 证据收集（search/scanner 扫描、manifest 匹配、状态判定） |
| `test_verify.py` | claim 比对、结构审计（5 段/时间/来源行） |
| `test_finalize.py` | 草稿解析、证据表提取、S# 分配、链接化、FINAL_STATUS 判定、4 工件产出 |
| `test_backend_reader_selfhost.py` | search/scrape 响应解析、健康检查、错误处理 |

## 10. 实现顺序

1. 项目骨架：`pyproject.toml`、`src/cli.py`、`src/config.py`
2. `backends/protocol.py` + `backends/reader_selfhost.py`
3. `search.py` + `scrape.py`
4. `evidence.py`（从 source_audit_gate 提取 collect_evidence）
5. `verify.py`（从 source_audit_gate 提取 audit_report + check_claims）
6. `finalize.py`（移植 finalize_firecrawl_report 核心）
7. `SKILL.md`
8. 测试
