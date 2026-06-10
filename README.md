# Veritas / 征实

**质量保障管线，让 AI 研究报告可审计、可追溯、可靠。**

```
veritas verify --run-dir .research/runs/<date>-<topic>     # 证据审计
veritas finalize --run-dir .research/runs/<date>-<topic>    # 报告收口
veritas template --type deep-research --topic "餐企出海"     # 生成草稿模板
veritas regtrack check --industry 餐饮 --region 北京         # 法规雷达
```

## 问题

AI 代写研究/法律报告最大的问题不是"写不出"——写得出，甚至写得漂亮——而是**质量不稳定**：

- 法条/案号可能是 AI 编的
- 引用的网页可能跟声称的内容不一致
- 报告结构可能不完整
- 没有可审计的源证据

Veritas 不替 Agent 写报告。它做的是在 Agent 写完后，**按证据维度核查质量**，给出一份可用的审计结论。

## 报告类型分型

Veritas 支持四种报告类型，每种有专属模板、验证规则和管线：

| `--type` | 报告类型 | 结构特征 | 管线 |
|-----------|---------|---------|------|
| `general` | 通用研究 | 5段式 + S# 标签 | verify → finalize 完整管线 |
| `deep-research` | 专题研究 | 编号章节 + 数据表格 + 对比分析 | verify → finalize 完整管线 |
| `practical-guide` | 实务指引 | 中文编号 + 步骤化 + 划重点 | verify → finalize（类型验证，不做 S# 标签） |
| `case-research` | 检索报告 | 三段式 + 案例概要表 + 案号 | verify → finalize（类型验证，不做 S# 标签） |

**类型选择逻辑**：含"比较/分析/费用"→ `deep-research`；含"要点/指引/如何应对"→ `practical-guide`；含"检索/案例/案号"→ `case-research`；其他 → `general`。

## 设计思路

### 三层质量保障

```
Agent 写草稿 ──→ verify ──→ finalize
                    │              │
             结构审计           S# 标签注入
             证据完整性         证据表格式化
             类型感知验证       类型感知收口
```

**第一层：结构规范**

verify 按报告类型检查必需章节——通用研究检查 5 段式；专题研究检查编号章节和元数据头；实务指引检查中文编号和划重点；检索报告检查三段式和案例概要表。不达标判 repairable 或 hard_fail。

**第二层：证据追溯**

通用研究和专题研究：每条 `[S#](url)` 引用必须对应 run-dir 证据集中的源 URL。verify 会区分 scraped、search-only 和 failed，finalize 自动在证据表注入 S# 标签。

实务指引和检索报告：不使用 S# 标签体系，用法条号和案号替代；仍可走 verify/finalize 做类型验证和最终状态判定。

**第三层：引用验真（法律专用）**

自动抽取引用的法条/案号，通过元典开放平台做语义比对，识别 AI 编造或不一致的引用。不影响 verify 判决，但输出专门的风险报告。

### 核心原则

- **证据先于结论** — 先采集源材料再写草稿，而不是先写再找来源
- **search-only ≠ scraped** — 只有搜索摘要（未抓取全文）的证据标记为 search-only，明确降级
- **类型感知** — 不同报告类型有不同质量标准，不做一刀切
- **不干扰 Agent 写作** — verify/finalize 只审核结构，不改动内容
- **独立验证** — 有框架支持时，派独立子代理执行自检，避免主 Agent 确认偏误

## 实例

以下示例用于展示 veritas 管线产物结构；示例状态来自仓库内随附证据快照，开源复用时请以自己的 run-dir 重新验证：

| 实例 | 课题 | 类型 | 审计结果 | 产物 |
|------|------|------|----------|------|
| 检索报告 | AI替岗"客观情况重大变化"的司法认定 | `case-research` | `pass` | [`examples/01-ai-replaces-worker/`](examples/01-ai-replaces-worker/) |
| 专题研究 | 深圳打造人工智能先锋城市：政策全景与合规要点 | `deep-research` | `pass` | [`examples/02-shenzhen-ai-regulations/`](examples/02-shenzhen-ai-regulations/) |
| 通用研究 | 2025—2026年动力电池回收：新规、执行与行业困境 | `general` | `pass` | [`examples/03-battery-recycling/`](examples/03-battery-recycling/) |
| 专题研究 | 跨境商事争议解决路径比较：仲裁与诉讼 | `deep-research` | `degraded`（演示快照，无证据文件） | [`examples/04-cross-border-dispute/`](examples/04-cross-border-dispute/) |
| 实务指引 | 商业秘密侵权全流程法律要点 | `practical-guide` | `degraded`（演示快照，无证据文件） | [`examples/05-confidential-info-guide/`](examples/05-confidential-info-guide/) |
| 检索报告 | 竞业限制违约金的裁判尺度 | `case-research` | `degraded`（演示快照，无证据文件） | [`examples/06-noncompete-cases/`](examples/06-noncompete-cases/) |

每个 run 目录包含管线产物：`draft-report.md`（草稿）、`final-report.md`（收口报告）、`finalize-summary.json`（审计摘要）、`source-audit.tsv`（证据核对表）。含搜索结果的示例还包含 `query-*.json`（搜索结果）和 `scrape-*.json`（源采集结果）；未随附证据快照的示例明确标记为 `degraded`，只用于展示报告结构。

---

## 快速上手

### 1. 生成草稿模板

```bash
# 专题研究：含编号章节 + 数据表格 + 对比分析
veritas template --type deep-research --topic "餐企出海马来西亚争议解决与法律适用"

# 实务指引：中文编号 + 步骤化 + 划重点
veritas template --type practical-guide --topic "字体侵权全流程法律要点"

# 检索报告：三段式 + 案例概要表 + 案号
veritas template --type case-research --topic "提前撤租押金与违约金"

# 写入 run-dir
veritas template --type deep-research --topic "..." --run-dir .research/runs/2026-05-31-my-topic
```

生成模板包含元数据头占位、必需分节骨架、质量标准提示，Agent 按模板填充即可通过类型验证。

### 2. 搜索与抓取

```bash
# 法律搜索（元典开放平台）
veritas search --backend yuandian --type law "食品安全法 惩罚性赔偿"
veritas search --backend yuandian --type case "股东知情权 纠纷"

# 通用网页搜索
veritas search "2026年 餐饮 新规" --limit 5

# 抓取详情
veritas scrape "yuandian://law/detail?id=xxx"
veritas scrape "https://example.com/article"
```

### 3. Agent 写草稿（按模板）

Agent 按生成的模板填充内容，使用 `[S1](url)` 内联引用（通用研究/专题研究），或法条号/案号（实务指引/检索报告）。

### 4. 验证与收口

```bash
# 通用研究 / 专题研究：完整管线
veritas verify --run-dir .research/runs/2026-05-31-my-topic --type general
veritas finalize --run-dir .research/runs/2026-05-31-my-topic --type general

# 专题研究
veritas verify --run-dir .research/runs/2026-05-31-my-topic --type deep-research
veritas finalize --run-dir .research/runs/2026-05-31-my-topic --type deep-research

# 实务指引：类型验证 + 法律引用校验
veritas verify --run-dir .research/runs/2026-05-31-my-topic --type practical-guide
veritas finalize --run-dir .research/runs/2026-05-31-my-topic --type practical-guide
veritas legal verify-citations --run-dir .research/runs/2026-05-31-my-topic

# 检索报告：类型感知验证
veritas verify --run-dir .research/runs/2026-05-31-my-topic --type case-research
veritas finalize --run-dir .research/runs/2026-05-31-my-topic --type case-research
```

---

## 优势

| | 直接用 AI Agent | 用 Veritas |
|------|---|---|
| **引用可追溯** | 靠 Agent 自觉写 URL | verify 强制每条引用必须有源 URL |
| **幻觉检测** | 无，完全相信模型 | 法律引用自动比对权威来源 |
| **报告结构** | 取决于 prompt 质量 | 类型感知验证，4 种类型各有质量标准 |
| **证据完整性** | 看不到哪些源没抓到 | evidence-urls: 10 collected, 8 scraped, 2 failed |
| **法规监控** | 手动搜索 | regtrack 自动跟踪行业/地区法规变化 |
| **模板驱动** | 从零写起 | template 一键生成类型专属骨架 |
| **多方验证** | 无 | SKILL.md 规定了独立子代理自检模式 |

## 命令

| 命令 | 用途 |
|------|------|
| `veritas search` | 搜索（通用或法律数据库） |
| `veritas scrape` | 抓取 URL（含 yuandian:// 协议） |
| `veritas template --type TYPE --topic TOPIC` | 生成类型专属草稿模板 |
| `veritas verify [--type TYPE]` | 证据完整性审计 + 法律引用校验（自动） |
| `veritas legal verify-citations` | 法律引用幻觉校验（独立运行） |
| `veritas finalize [--type TYPE]` | 报告收口（类型验证；S# 标签按类型注入） |
| `veritas regtrack add/check/status` | 法规雷达监控 |
| `veritas config` | API Key 管理 |

## 搜索后端

| 后端 | 用途 | 需配置 |
|------|------|--------|
| `opencli`（默认） | 通用网页/站点适配器搜索 | 本地安装 `opencli` |
| `yuandian` | 法律法规/案例检索 | `YUANDIAN_API_KEY` |

## S# 引用系统

通用研究和专题研究用内联 URL 精确引用：

```markdown
- [S1](https://flk.npc.gov.cn/...) **《工伤保险条例》第14条**：详情...
- [S2](yuandian://case/detail?type=ptal&id=xxx) **指导案例**：详情...
```

`veritas finalize` 自动注入 S# 标签到证据表，校验引用顺序一致性。

**实务指引和检索报告不使用 S# 标签**，finalize 会跳过 S# 标签注入，用法条号（如"《民法典》第五百八十五条"）和案号（如"(2024)京02民终3691号"）做类型验证。

## 类型专属质量标准

Veritas 的验证器会自动检查以下质量维度，不达标时输出 ⚠ 警告。这些阈值对标专业法律研究报告的实务标准：

| 维度 | general | deep-research | practical-guide | case-research |
|------|:---:|:---:|:---:|:---:|
| 最小行数 | 40 | 80 | 60 | 80 |
| 最少加粗标注 | 4处 | 6处 | 6处 | 4处 |
| 最少表格 | 0 | 2 | 0 | 1 |
| 脚注（①②③） | — | 必须 | — | — |
| 强调标记 | — | 必须 | 必须 | — |
| 🔴🟡裁判标记 | — | — | — | 必须 |
| [S#](url)引用 | ≥3处 | ≥3处 | — | — |
| 《XX法》第X条 | — | ≥1处精确 | ≥3处精确 | ≥1处精确 |
| 案号引用 | — | — | — | ≥2个 |

> **引用说明**：[S#](url) 是内联来源URL标注（finalize 自动注入标签列）；《XX法》第X条 须精确到条文号；案号须完整格式如 `(2024)京02民终3691号`。引用不足会导致 verdict 从 pass 降为 repairable。

### 专题研究（deep-research）

| # | 标准 |
|---|------|
| 1 | 分节编号：主章节 1. 2.，子章节（一）（二），三级 1、2、 |
| 2 | 数据表格：涉及金额/费率/对比必须用表格，标注单位 |
| 3 | 对比分析：多方案须有汇总表或雷达图 + 一句话关键发现 |
| 4 | 具体金额：精确到个位，不模糊 |
| 5 | 法律依据：引用法条号 |
| 6 | 实务结论：每段末尾**加粗**实务结论句 |
| 7 | 元数据头：来源/作者/日期 |

### 实务指引（practical-guide）

| # | 标准 |
|---|------|
| 1 | 中文编号：一、二、三、四 + 步骤 1. 2. 3. |
| 2 | 递进逻辑：前提 → 标准 → 后果 → 应对 |
| 3 | 痛点引入：开头面向读者痛点 |
| 4 | 金额/阈值：必须给具体数字 |
| 5 | 划重点：关键处用 **划重点！** |
| 6 | 双线方案：和解与应诉并列 |
| 7 | 可操作性：每步可执行 |
| 8 | 尾注：文末标注来源类型 |

### 检索报告（case-research）

| # | 标准 |
|---|------|
| 1 | 三段式：检索问题 → 初步结论 → 研究依据 |
| 2 | 结论先行：初步结论在案例详情前，每条含数据 |
| 3 | 案例概要表：四列（序号/概要/具体内容/案号） |
| 4 | 案号完整：如 (2024)京02民终3691号 |
| 5 | 推理加粗：法院核心推理 **加粗** |
| 6 | 金额精确：精确到元/分 |
| 7 | 原文保留：法院说理保留原文 |
| 8 | 对比提炼：初步结论做跨案例对比 |
| 9 | 案例分隔：--- 分隔 |

## 法规雷达

```bash
veritas regtrack add --industry 餐饮 --keywords 餐饮,食品安全,反食品浪费 --region 北京
veritas regtrack check --industry 餐饮 --region 北京 --since 2026-03 --until 2026-04
veritas regtrack status --industry 餐饮 --region 北京
```

支持多关键词并发、地区过滤、时间范围、可配置结果数。`--keywords` 同时兼容逗号分隔和空格分隔。

## 安装

```bash
pip install -e .
```

### Agent Skill 安装

Skill 文件位于本仓库 `.opencode/skills/veritas/`，定义了 Agent 工作流、质量阈值、搜索策略和陷阱。

**Hermes Agent：**

```bash
# 方式一：symlink（推荐，改动双向同步）
ln -s $(pwd)/.opencode/skills/veritas ~/.hermes/skills/research/veritas

# 方式二：hermes skills install
hermes skills install .opencode/skills/veritas/SKILL.md --name veritas
```

**OpenCode / 其他 Agent：**

将 `.opencode/skills/veritas/SKILL.md` 复制到对应 Agent 的 skill 目录即可。SKILL.md 内的 `compatibility: opencode` 标记表示兼容 OpenCode skill 格式。

## 配置

```bash
veritas config init
veritas config set api_keys.yuandian_key <key>
```

## SKILL

详细工作流、质量阈值、搜索策略与 Agent 协作模式参见 [`.opencode/skills/veritas/SKILL.md`](.opencode/skills/veritas/SKILL.md)。
