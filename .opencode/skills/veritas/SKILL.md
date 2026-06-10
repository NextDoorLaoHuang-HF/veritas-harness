---
name: veritas
description: "当用户要求联网/法律研究、事实核验、证据审计报告、法条/案号校验、法规雷达或 veritas-harness 流水线时使用；指导 search/scrape、draft-report.md、verify/finalize、yuandian/opencli、inject-cases、regtrack 与常见 fatal 陷阱。"
version: 1.1.0
author: Veritas Harness maintainers
license: MIT
compatibility: opencode
---

# Research CLI — AI Agent Skill

## 适用场景

当用户要求联网搜索、事实核验、信息汇总时。

## 轻量 vs 深度判定

- **deep**：时效性强 / 高风险 / 需多来源交叉验证
- **light**：简单事实确认、单来源摘要

## 流水线概览

```
┌────────────────────────────────────────────┐
│ Agent 自有工具 (websearch / webfetch)       │ ← 优先，零部署
│ 或 CLI 命令 (veritas search / scrape)      │ ← opencli 多站点搜索 + yuandian:// 详情
├────────────────────────────────────────────┤
│ Agent 写草稿 (draft-report.md)              │
├────────────────────────────────────────────┤
│ veritas verify --run-dir <path>            │ ← 核心价值：证据审计
│ veritas finalize --run-dir <path>          │ ← 核心价值：报告收口
└────────────────────────────────────────────┘
```

## 标准工作流

```
Agent 出关键词计划 → websearch 搜 → webfetch 抓 →
写入 run-dir 结构化数据 → Agent 写草稿 → verify → finalize
```

## 失败分支速查（必须按条件处理）

| 触发条件 | 一线修复 | 仍失败兜底 |
|---|---|---|
| 搜索结果不足 3 条 | 拆关键词、换同义词、补 opencli/yuandian 第二后端 | 明确标注 `confidence=low`，不要强行写高置信结论 |
| opencli 站点失败或需要浏览器态 | 换 `--opencli-public-only` 或指定 PUBLIC 站点 | 回退到 Agent 自有 websearch/webfetch，写入同一 run-dir |
| yuandian 返回 401 | 先按限流处理：暂停 60-120s，避免连续重试 | 若 5 次内稳定 401，再检查 API base、`X-API-Key` 与 `~/.config/research-cli/config.toml` |
| `verify` 输出 repairable | 按 warning 修草稿后重跑 `verify` | 无法修复时在交付中明确降级原因，不能声称 FINAL_STATUS=pass |
| `finalize` 输出 fatal | 停止交付，修复 dropped 来源、S# 映射或结构硬伤 | 重新跑 `verify` + `finalize`；仍 fatal 则报告不可用 |
| 法条/案号无法核验 | 改写为“未能核验/示意”，降低置信度 | 不得把未核验案号、条文号写成真实权威引用 |
| CWD 是公开仓库或同步目录 | 立刻显式指定安全 `--run-dir` | 已生成 `.research/` 时检查是否含敏感材料，必要时移出仓库 |

**原则**：失败必须显式处理；不得静默跳过 `verify/finalize`，也不得把 degraded/fatal 包装成通过。

## 证据分配（反附录式硬性要求）

> ⚠ **本章节是质量门之一。**违反者 `veritas verify` 会把 verdict 降为 `repairable`。

**核心禁令**：
- ❌ **禁止**将所有案号堆在文末"附录 A：参考案例"或"案例汇总表"中
- ❌ **禁止**用"汇总表/速查表"代替正文中的案号融入（汇总表是辅助，**不是**主战场）
- ❌ **禁止**主体章节正文段落不挂案号，全靠"另见附录"指代

**正面要求**：
- ✅ 每个主体章节（`##` 级别）正文段落必须融入 ≥1 个相关案号
- ✅ 案号应**直接挂在论理句中**，而非单独成行罗列
- ✅ 案号推荐采用 `（YYYY）XX民XX号` 全角括号格式 + 法院论理一句话总结

**标准工作流（升级版）**：
```
1. 关键词计划 → websearch 搜 → webfetch 抓 → 写入 run-dir
2. 【新】veritas inject-cases --run-dir <path> --type <type>
   → 生成 case-allocation.md：每章推荐 2-3 个最相关案号
3. Agent 拿到 case-allocation.md → 手工挑选 + 改写为论理段
4. Agent 写草稿（draft-report.md）：在每章末尾的"📌 证据分配点"占位符填入
5. veritas verify → 检查"证据分布"硬性指标
6. veritas finalize → 报告收口
```

**为什么是"推荐"而非"自动注入"**：
- 关键词级初筛是机械化的（CLI 能做）
- 语义级"哪个 case 配哪个论理段"是 LLM 任务（Agent 做）
- LLM 拿到 case-allocation.md 后**手工挑选 + 改写为论理段**，**不是**直接复制字符串
- 这样保留 Agent 对案例筛选的最终控制权

**例：正确 vs 错误**：

```markdown
❌ 错误：附录式（案号全在文末）

## 三、法律后果

责任比例问题需要综合考量……（正文无案号）

## 附录 A：参考案例

| 案号 | 案由 |
|------|------|
| （2019）粤03民终24213号 | 冒名入职工亡 |
| （2021）湘0224民初1235号 | 提供劳务受害 |


✅ 正确：融合式（案号融入论理段）

## 三、法律后果

**责任比例**：参考（2019）粤03民终24213号案，**冒名入职员工因工亡**的，
**法院认定其主观上存在明显过错，应承担主要责任**；参考（2021）湘0224民初1235号案，
**用工单位在选任监督上有过错的承担次要责任**。两案裁判尺度基本一致。
```

**veritas verify 自动检查的指标**：
1. 主体章节 0 案号 → warning
2. 70%+ 案号集中在尾部 30% 行 → **hard warning**（疑似附录式）
3. 附录中案号 ≥ 总案号 50% → **hard warning**（案号堆在附录）
4. 单一主体章节独占 60%+ 案号 → warning（疑似"伪融合"汇总表替代正文）

verdict 影响：
- `verdict=ok` → 全部 OK
- `verdict=warning` → 仅警告，不影响最终结论
- `verdict=hard_warning` → 报告降为 `repairable`，需手工修复后重跑

## CLI 快速参考

```
veritas verify --run-dir <path>          证据审计（含证据分布检查）
veritas finalize --run-dir <path>        报告收口
veritas inject-cases --run-dir <path>    反附录式案例分配（生成 case-allocation.md）
veritas search <query> [<query2> ...]    搜索（默认 opencli，零部署）
    --backend opencli (默认)               opencli 多站点适配器
    --backend yuandian                     元典法律数据库
veritas scrape <url> [<url2> ...]        抓取（普通 URL 走 opencli，yuandian:// 走元典直连）
veritas template --type <type> --topic <topic>  生成草稿模板（含证据分配点占位符）
veritas legal verify-citations --run-dir <path>  法律引用幻觉校验
```

详见 `veritas <cmd> -h`。

## 报告类型与质量标准

Veritas 支持 4 种报告类型，每种类型有独立的结构要求和质量阈值。**所有类型的质量基准对标"专业法律研究样板"——即专业法律研究报告的实务标准。**

### 类型选择指南

| 信号 | 推荐类型 |
|------|----------|
| 多角度深度分析，需对比数据/费用表/制度框架 | `deep-research`（专题研究） |
| 面向实务操作，需步骤指引/强调标记/应对方案 | `practical-guide`（实务指引） |
| 检索裁判案例，需案号/法院论理/判决主文 | `case-research`（检索报告） |
| 一般性研究，无特定格式要求 | `general`（通用研究） |

### deep-research（专题研究）质量标准

**结构要求**：
- 元数据头（`> 来源：...`）
- 编号主章节（`## 1.`, `## 2.`）
- 子章节（`### （一）`）
- 三级标题（`#### 1、`）
- 📊 对比摘要表（开篇）
- 📋 数据明细表（每节至少1个）
- **加粗**关键结论
- ①②③脚注

**质量阈值**：
- ≥80行
- ≥6处**加粗**标注
- ≥2个数据表格
- 必须有脚注
- 必须有强调标记（实务结论/核心提示）

### practical-guide（实务指引）质量标准

**结构要求**：
- 元数据头
- 中文编号章节（`## 一、`, `## 二、`）
- 痛点引入段（1-3句场景描述）
- 认定要件（1. 2. 3.）
- 法律后果（含具体金额区间）
- **划重点！**强调标记
- 操作步骤（`### 1.`, `### 2.`, `### 3.`, `### 4.`）
- 双线策略（和解层面 / 应诉层面）
- 尾注行（`*本文档为...*`）

**质量阈值**：
- ≥60行
- ≥6处**加粗**标注
- 必须有强调标记（划重点/核心提示）

### case-research（检索报告）质量标准

**结构要求**：
- 三段式：检索问题 → 初步结论 → 研究依据
- 案例概要表（四列：序号/概要/具体内容/案号）
- 🔴🟡🟢裁判倾向标记
- 每个案例须包含：
  - **案号**：完整案号，如 `(2024)京02民终3691号`
  - **诉请**：原告诉讼请求（1-4项）
  - **论理**：法院认定，**加粗**关键推理
  - **判决主文**：逐项列出
- 案例间 `---` 分隔线

**质量阈值**：
- ≥80行
- ≥4处**加粗**标注
- ≥1个表格（案例概要表）
- ≥2个有效案号
- 必须有🔴🟡标记

### general（通用研究）质量标准

**结构要求**：
- 5段式：结论 / 关键发现 / 证据与来源 / 置信度 / 未解决问题
- S#标签与引用链接
- 关键发现每项2-4句（含数据、日期、影响范围）
- 结论2-3段
- 置信度须含理由

**质量阈值**：
- ≥40行
- ≥4处**加粗**标注

## 草稿模板生成

```
veritas template --type deep-research --topic "跨境商事争议解决路径" --run-dir .research/runs/2026-05-31-cross-border
veritas template --type practical-guide --topic "字体侵权" --run-dir .research/runs/2026-05-31-font
veritas template --type case-research --topic "提前撤租违约金" --run-dir .research/runs/2026-05-31-lease
```

模板包含完整的结构骨架和内容指引（方括号占位），Agent 填充实际内容后即可走 verify/finalize 管线。

## 法律研究（元典开放平台）

当 `YUANDIAN_API_KEY` 配置后，支持通过元典开放平台进行法律研究：

### 法规案例搜索

```
# 基础搜索（语义检索）
veritas search --backend yuandian --type law "食品安全法 惩罚性赔偿"
veritas search --backend yuandian --type case "股东知情权 纠纷"
veritas search --backend yuandian --type all "知识产权 侵权"

# 按月/按地区检索（关键词匹配，支持日期+地区过滤）
veritas search --backend yuandian --type law --region 北京 \
  --since 2026-05-01 --until 2026-05-31 "餐饮"
```

- `--type law`：搜索法律法规（语义检索 + 关键词检索双模式自动降级）
- `--type case`：搜索裁判案例 / 权威案例
- `--type all`：同时搜索法规和案例，结果合并
- `--region`：地区过滤（如 `北京`、`广东`，传后自动切换为关键词匹配模式）
- `--since` / `--until`：发布日期范围（`YYYY-MM-DD`，传后自动切换为关键词匹配模式）

### 法律引用幻觉校验

```
veritas legal verify-citations --run-dir .research/runs/<date>-<topic>
veritas legal verify-citations --text "根据《民法典》第一千二百条..."
veritas legal verify-citations --file draft.md
```

自动抽取文本中的法规/法条和案号，与权威来源比对语义一致性、核验时效性，输出：

```
检测到 3 条法规引用, 1 条案例引用
⚠ 发现 1 个潜在问题:
  [法规] 《民法典》：语义比对不一致
```

### 配合 verify/finalize 管线

> **无需全量 scrape**。`search` 返回的 `snippet` 已包含匹配到的**条文原文**（100-400 字），足够 Agent 写草稿。`scrape` 调用 `rh_fg_detail` 返回的是**整部法规全文 + 元数据**的 JSON dump（6000+ 字），适合做深度分析但非必须。只对草稿中实际引用（`[S#]`）的法条/案例做 scrape，未 scrape 的记作 `search-only`，不影响 verify 判决。

```
veritas search --backend yuandian --type law "..."        # 搜索（写入 query-*.json）
veritas search --backend yuandian --type case "..."        # 搜索案例
veritas scrape "yuandian://law/detail?id=xxx"              # （可选）仅抓取草稿引用的关键法条详情
veritas scrape "yuandian://case/detail?type=ptal&id=yyy"   # （可选）仅抓取草稿引用的关键案例详情
→ Agent 写草稿（引用 URL 来自 yuandian://... 或 websearch 结果）
veritas verify --run-dir <path>                            # 证据审计
veritas legal verify-citations --run-dir <path>            # 法律引用校验
veritas finalize --run-dir <path>                          # 报告收口
```

### 元典按月/按地区检索法规（rh_fg_search）

> ⚠️ **语义检索 vs 关键词检索**：传了 `--region` 或 `--since/--until` 后，搜索从语义检索（`law_vector_search`）自动切换为关键词匹配（`rh_fg_search`）。这意味着多词查询（如 `"餐饮 食品安全"`）可能匹配不到，建议拆为单关键词分别搜索。

**CLI 用法**：

```bash
# 按月对比北京餐饮法规变化
veritas search --backend yuandian --type law \
  --region 北京 --since 2026-05-01 --until 2026-05-31 "餐饮"

veritas search --backend yuandian --type law \
  --region 北京 --since 2026-04-01 --until 2026-04-30 "餐饮"

# 不传 --region 则搜全国
veritas search --backend yuandian --type law \
  --since 2026-05-01 --until 2026-06-05 "食品安全"
```

**curl 备用**（如需编程调用）：

```bash
KEY=$(grep yuandian_key ~/.config/research-cli/config.toml | sed 's/.*= *"\(.*\)"/\1/')
curl -s -X POST "<YUANDIAN_API_ENDPOINT>/open/rh_fg_search" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"keyword":"餐饮","top_k":15,"dy":"北京","fbrq_start":"2026-05-01","fbrq_end":"2026-06-05"}'
```

**参数说明**：
- `--region`：地区过滤（如 `北京`、`广东`，不传则全国）
- `--since` / `--until`：发布日期范围（YYYY-MM-DD）
- 底层 API 参数：`keyword`（关键词）、`top_k`（返回数量，`--limit` 映射）、`dy`（地区）、`fbrq_start`/`fbrq_end`（日期）

**⚠️ 限流提醒**：`rh_fg_search` 和 `law_vector_search` 共享同一限流配额（5min/~8次）。建议统一用 CLI 调用，避免混用 CLI 和 curl 导致配额碎片化。

### 元典后端：关键陷阱（实战踩坑，2026-06 实测）

**API base（最常见的错误源）**

真实端点：`<YUANDIAN_API_ENDPOINT>`。**不是** `https://open.chineselaw.com`。
错误地址会返回 HTML/JSON 错配，401 报"key 无效"是**伪装**——实际是路由不通或鉴权头错位。

**鉴权**：仅 `X-API-Key` 一个 header，**不要**带 `Authorization: Bearer`（元典不识别，会返 401）。

**限流策略（核心，5min/IP≈8 次后会触发）**

5 分钟 / IP 大约 8 次请求后，**返回 401 伪装"key 无效"**。这是限流，不是 key 失效。

```python
# ✅ 正确的限流-aware 调用模式
import time

QUERIES = ["q1", "q2", ...]  # 8-10 个查询
for i, q in enumerate(QUERIES):
    if i > 0 and i % 5 == 0:
        time.sleep(60)  # 每 5 个查询 sleep 60s
    else:
        time.sleep(3)   # 查询间 sleep 3s
    result = search_yuandian(q)
```

**实战预算**：
- 5 个查询：`3s × 4 + 60s ≈ 72s`（安全）
- 10 个查询：`3s × 4 + 60s + 3s × 4 + 60s ≈ 144s`（安全）
- 看到连续 401：**立即 sleep 60-120s**，**不要**循环重试（会一直 401）
- 用 `--type all` 一次合并 `law + case` 搜索，**减少 50% 请求数**

**CLI 不会自动重试**：`veritas search` 失败只 echo 错误，不会 sleep 重试。Agent 需自己包装 retry loop 或在批量调用时手动 sleep。

### CWD 污染陷阱（必读，避免污染 git 仓/客户目录）

`veritas search` / `scrape` / `template` **默认在 CWD 下创建** `.research/runs/<date>-<topic>/`。

**危险场景**：
- CWD 是 git 仓 → `.research/` 已被 `.gitignore` 保护，**不会污染 git**，但磁盘污染 + 同步目录会 leak
- CWD 是云同步目录（iCloud / OneDrive / Dropbox）→ 触发同步，**可能把 API key/客户原文同步到云**
- CWD 是公开开源仓（veritas-harness 本身）→ 仓内出现 `.research/runs/` 目录，即使 git ignore 也**破坏开发环境干净原则**

**正确做法**：在敏感目录运行 CLI 时，**显式指定 `--run-dir` 指向安全位置**：

```bash
# ✅ 显式指定，避开 CWD 污染
veritas search --backend yuandian --type law "..." \
  --run-dir ~/.hermes/scratch/2026-06-02-研究主题

# ❌ 默认行为（在 CWD 下建 .research/runs/）
veritas search --backend yuandian --type law "..."
```

**研究产物归宿建议**：

| 场景 | 推荐 `--run-dir` 位置 |
|------|---------------------|
| 客户委托研究（保密） | `~/Clients/<客户名>/research/<date>-<主题>/` 或 `~/.hermes/scratch/private/` |
| 团队共享研究 | `~/workspace/team-research/<date>-<主题>/` |
| 一次性自查 | `~/.hermes/scratch/<date>-<主题>/` |
| 公开仓库（含 .gitignore） | **100% 不放**，即使 .gitignore 保护也不放 |
| 已存在的客户目录（带原素材） | 直接用原目录的子文件夹 |

**自检命令**：

```bash
# 跑 CLI 前先确认 CWD 是哪、是否 git 仓
pwd && git rev-parse --is-inside-work-tree 2>/dev/null || echo "NOT-GIT-REPO"
```

## 搜索与抓取

**Agent 自有 `websearch` / `webfetch` 即可搜索和抓取。** CLI 的 `search` 默认使用 opencli 后端（零部署），法律检索可显式切换 `--backend yuandian`；`scrape` 对普通 URL 使用 opencli，对 `yuandian://` URL 自动使用元典直连。

### 方式一：Agent 自有工具

用 `websearch` 搜索，`webfetch` 抓取，然后将结果写入 run-dir。run-dir 结构如下：

```
.research/runs/<日期>-<主题>/
  ├── query-1.json        搜索原始结果
  ├── query-2.json        第二个关键词的结果（可选）
  └── scrape-manifest.tsv 抓取清单 + 每页的 markdown
```

**query-*.json 格式**（每条结果一个条目）：

```json
{
  "query": "2026年3月 餐饮 新规",
  "count": 2,
  "results": [
    {
      "title": "标题",
      "url": "https://example.com/article",
      "snippet": "摘要文字",
      "source": "example.com",
      "published": "2026-03-15"
    }
  ],
  "provider": "websearch"
}
```

**scrape-manifest.tsv 格式**（tab 分隔，首行是表头）：

```
url	file
https://example.com/article	scrape-1.json
```

对应的 `scrape-1.json` 内容：

```json
{
  "url": "https://example.com/article",
  "status": 200,
  "title": "页面标题",
  "markdown": "抓取到的正文 markdown",
  "text": "纯文本版本",
  "pageType": "article",
  "contentQuality": "full"
}
```

### 方式二：OpenCLI 后端（推荐，零部署）

当本地已安装 [opencli](https://github.com/jackwener/opencli)（`npm install -g @jackwener/opencli`），可直接通过 opencli 适配器搜索高质量信息站点。**这是 veritas 的默认后端，无需额外部署。**

#### 搜索

```bash
# 指定站点搜索
veritas search --backend opencli --opencli-sites hackernews,duckduckgo "AI agent" --limit 5

# 自动路由（根据查询内容选择合适站点）
veritas search --backend opencli "AI alignment research" --limit 10

# 仅用 PUBLIC 策略站点（无需浏览器/Chrome 扩展）
veritas search --backend opencli --opencli-public-only "python async patterns" --limit 10

# JSON 输出
veritas search --backend opencli --json --opencli-sites hackernews,arxiv,duckduckgo "Rust async" --limit 5
```

#### 抓取

```bash
# 用 opencli 抓取 URL 内容（自动识别站点，使用对应适配器）
veritas scrape --backend opencli "https://news.ycombinator.com/item?id=42691946"

# 元典详情 URL 自动走 YuandianBackend 直连，不经过 opencli
veritas scrape "yuandian://law/detail?id=xxx"

# 批量抓取
veritas scrape --backend opencli "https://arxiv.org/abs/2301.12345" "https://news.ycombinator.com/item?id=12345"
```

#### 支持的站点

| 类别 | 站点 (opencli site) | 策略 | 搜索 | 抓取 |
|------|-------------------|------|:----:|:----:|
| **科技/AI** | hackernews | PUBLIC | ✅ | ✅ |
| | arxiv | PUBLIC | ✅ | ✅ |
| | aibase | PUBLIC | ✅ | — |
| | 36kr | INTERCEPT | ✅ | ✅ |
| | reddit | COOKIE | ✅ | ✅ |
| **开发** | stackoverflow | PUBLIC | ✅ | ✅ |
| | devto | PUBLIC | ✅ | ✅ |
| | linux-do | COOKIE | ✅ | ✅ |
| | v2ex | COOKIE | ✅ | ✅ |
| **通用搜索** | duckduckgo | PUBLIC | ✅ | — |
| | google | PUBLIC | ✅ | — |
| | wikipedia | PUBLIC | ✅ | ✅ |
| **学术** | google-scholar | PUBLIC | ✅ | — |
| | pubmed | PUBLIC | ✅ | ✅ |
| | dblp | PUBLIC | ✅ | ✅ |
| | openalex | PUBLIC | ✅ | ✅ |
| **中文** | zhihu | COOKIE | ✅ | ✅ |
| | weixin | COOKIE | ✅ | ✅ |
| | weibo | COOKIE | ✅ | — |
| **新闻** | bbc | PUBLIC | ✅ | — |
| | bloomberg | PUBLIC | ✅ | — |

> **策略说明**：PUBLIC = 无需浏览器即可使用；COOKIE/INTERCEPT/UI = 需要 Chrome + OpenCLI 扩展。

#### 自动路由规则

当不指定 `--opencli-sites` 时，后端根据查询内容自动选择站点：

| 查询类别 | 检测关键词 | 默认站点 |
|----------|----------|---------|
| AI | ai, llm, gpt, 模型, agent, copilot... | hackernews, reddit, arxiv, aibase, 36kr |
| 技术 | api, sdk, framework, kubernetes, docker... | hackernews, reddit, arxiv, 36kr, devto |
| 中文 | 中国, 政府, 政策, 法规, 监管... | weibo, zhihu, weixin, 36kr |
| 学术 | paper, research, survey, benchmark... | arxiv, google-scholar, pubmed, dblp, openalex |
| 开发 | code, bug, fix, python, rust... | stackoverflow, devto, linux-do, v2ex, hackernews |
| 法律 | 法, 合同, 侵权, 诉讼... | google, wikipedia（配合 yuandian） |
| 通用 | （默认） | wikipedia, hackernews, reddit, google, duckduckgo |

#### 配置

```toml
# ~/.config/research-cli/config.toml
[opencli]
public_only = false        # 仅用 PUBLIC 策略站点
timeout = 30               # 单次命令超时（秒）
inter_command_delay = 3.0  # 命令间隔（秒，遵守风控）
default_sites = ""         # 逗号分隔默认站点，空=自动路由
```

环境变量：
- `OPENCLI_TIMEOUT` — 超时
- `OPENCLI_PUBLIC_ONLY` — 仅 PUBLIC 站点
- `OPENCLI_DEFAULT_SITES` — 默认站点

#### 风控注意事项

opencli 后端内置了命令间延迟（默认 3 秒），但高频调用仍需遵守：
- COOKIE 策略站点：同一站点连续 ≤10 次后休息 ≥5 分钟
- 搜索 --limit 建议 10~20，不超过 50
- 遇到错误不要空车重试，等待 30 分钟后重试

> **与 yuandian 的组合**：法律研究建议用 `--backend yuandian` 搜索法规案例，`--backend opencli` 搜索新闻/学术补充材料。两者 run-dir 可合并后走 verify/finalize 管线。

## 抓取降级链路

opencli 站点适配器 → opencli `web read` → requests 直连 fallback → Agent 端 webfetch/浏览器工具手工补采。

## S# 标签与引用链接

`finalize` 支持两种 `[S#]` 引用标注方式：

### 方式一：内联 URL（推荐）

在草稿中直接写 `[S1](https://example.com)`，`finalize` 保持内联 URL 不变，不覆盖。

```
## 关键发现
- [S1](https://moa.gov.cn/...) **GB 2763-2026 农残国标**...
- [S2](https://foodmate.net/...) **调制肉制品规范**...
```

### 方式二：裸引用 + 自动分配

写 `[S1]` 不带 URL，`finalize` 按"证据与来源"表格顺序分配链接。

**关键规则**：证据表的 URL 顺序必须与 S# 引用顺序一致。不一致时 `finalize` 会打印 ⚠ 警告。

```
## 关键发现
- [S1] 发现一        ← 对应证据表第 1 行
- [S2] 发现二        ← 对应证据表第 2 行

## 证据与来源
| 来源 | ... |           ← 第 1 行 → S1，第 2 行 → S2
| https://a.com | ... |
| https://b.com | ... |
```

### 自动注入

`finalize` 会自动在"证据与来源"表格中插入 `| 标签 |` 列，标注每条证据对应的 S#。

> ⚠️ **标签列陷阱（关键，踩坑率最高）**：草稿中的证据表**绝对不能**包含 `| 标签 |` 列。`finalize` 解析时将第一个数据列视为 URL——如果你在草稿中写了标签列，`**S1**` 会被当作 URL 解析，导致全部证据 → `unknown` → claim-check 0% → FINAL_STATUS=fatal。**正确做法**：草稿证据表只写 `| 来源 | 类型 | 状态 |`（3列，不要标签列、不要关键信息列），让 finalize 自己注入标签列。

### 最佳实践

1. **始终用内联 URL**：`[S1](url)` 精确映射。裸引用 `[S1]` 依赖证据表顺序，脆弱易断——不建议使用。
2. **关键发现每个条目写 2-4 句**：陈述事实 + 关键数据 + 影响
3. **结论写 2-3 段**：总体判断 + 重点变化 + 对经营者的影响（或改为对经营者的行动建议）
4. **置信度必须给出理由**：来源覆盖面、交叉验证情况
5. **关键推理和结论必须加粗**：帮助读者快速定位核心信息
6. **数据表必须加脚注**：说明口径、不含项、计算方式
7. **实务指引必须有"划重点"**：读者引导标记不可省略
8. **general 类型报告末尾必须有 `*完成时间: YYYY-MM-DDTHH:MM:SSZ*`**，缺此标记会被 verify/finalize 标记为 repairable，并使 FINAL_STATUS 降为 degraded

## 质量闸门

## 🔴 交付前 STOP 检查点

交付前逐项确认；任一不满足，不得把报告称为“最终版”或 `pass`：

1. `draft-report.md` 中的关键事实均有 `[S#](url)` 或可追溯来源；general 类型证据表仍是 3 列（来源/类型/状态），没有预填标签列。
2. 法律报告中的法条精确到“第 X 条”，案号为完整格式；无法核验的引用已降级标注，未冒充真实。
3. 已运行 `veritas verify --run-dir <path> --type <type>`，且没有未处理的 hard warning / repairable 项。
4. 已运行 `veritas finalize --run-dir <path> --type <type>`；若 `FINAL_STATUS` 不是 `pass`，交付时必须明示 degraded/fatal 原因。
5. 研究产物位于安全 `--run-dir`，没有把客户材料、API key 或临时 `.research/` 泄露到公开仓/同步目录。

- FINAL_STATUS=pass：质量阈值、结构要求、证据采集与引用核对均通过
- FINAL_STATUS=degraded：存在 repairable 质量缺口、部分来源未采集，或报告引用可追溯性不足；报告可用但必须标注降级
- FINAL_STATUS=fatal：存在 hard_fail，或 dropped 来源数量超过 admissible 来源数量，报告不可用
- 最低证据数：3 条
- 置信度标签：high / medium / low / unverifiable

### 质量阈值自动检查

`verify` 和 `finalize` 会自动检查以下质量维度，不达标时输出 ⚠ 警告：

| 维度 | general | deep-research | practical-guide | case-research |
|------|:---:|:---:|:---:|:---:|
| 最小行数 | 40 | 80 | 60 | 80 |
| 最少加粗 | 4处 | 6处 | 6处 | 4处 |
| 最少表格 | 0 | 2 | 0 | 1 |
| 脚注 | — | 必须 | — | — |
| 强调标记 | — | 必须 | 必须 | — |
| 🔴🟡标记 | — | — | — | 必须 |
| [S#](url)引用 | ≥3处 | ≥3处 | — | — |
| 《XX法》第X条 | — | ≥1处精确 | ≥3处精确 | ≥1处精确 |
| 案号引用 | — | — | — | ≥2个 |

**引用说明**：
- **[S#](url)引用**：内联来源URL标注，finalize 自动注入标签列。格式：`[S1](https://...)`
- **《XX法》第X条**：精确到条文号的法条引用。仅写《XX法》不写第X条会被标记"法条引用精度不足"
- **案号引用**：完整案号格式，如 `(2024)京02民终3691号`
- **引用不足影响判决**：引用缺口会导致 verdict 从 pass 降为 repairable（practical-guide 和 case-research 的法条/案号引用是硬性要求）

## 多 Agent 协作模式（框架支持时启用）

### 并行研究方向调研
- 主 Agent 将研究问题拆解为 N 个独立子方向
- 每个子方向派发一个子 Agent，各自执行：关键词规划 → websearch → webfetch → 结构化笔记
- 子 Agent 返回结构化研究笔记（含发现摘要 + 已收集证据 URL 列表），写入独立 run-dir
- 主 Agent 汇总所有子方向结果，撰写综合草稿

### 独立多方验证
- 最终报告产出后，派发 2-3 个子 Agent 独立执行 `veritas verify --run-dir <path>`
- 每个子 Agent 各自做 claim 比对 + 结构审计
- 主 Agent 比对多份审计结果：一致则通过，不一致则标记争议点复查
- 避免单 Agent 的确认偏误

### 协作时序
```
主 Agent 拆解问题
  ├─ 子 Agent A: 方向 1 → websearch → webfetch → 笔记
  ├─ 子 Agent B: 方向 2 → websearch → webfetch → 笔记
  └─ 子 Agent C: 方向 3 → websearch → webfetch → 笔记
主 Agent 汇总 → 写草稿 → finalize
  ├─ 子 Agent D: verify（独立）
  ├─ 子 Agent E: verify（独立）
  └─ 主 Agent: 比对审计 → 定稿
```

## 法规雷达（regtrack）

> ⚠️ **重要限制**：regtrack 依赖**预注册的法规追踪数据**。`regtrack add` 注册的是空的 tracking profile，并非实时拉取法规。`regtrack check` 只能查到已入库的法规变更——首次使用时库为空，返回空结果。**因此对首次研究任务（如"最近北京餐饮有什么新法规"），regtrack 无效**，应直接用 `search --backend yuandian` 或 `search --backend opencli`。regtrack 的正确用途是：先用 search 做完首次研究并登记关键法规后，后续用 regtrack 做**持续变更监控**。

当用户要求监控特定行业/地区的法规变更时使用。

### 触发场景

- "最近餐饮行业有什么新法规？" → **用 search，非 regtrack**
- "北京地区 3-4 月有什么法规变化？" → **用 search**（或用 rh_fg_search curl 直调实现按月检索）
- "帮我跟踪一下数据安全相关的法规" → 先用 search 做首次研究，后续用 regtrack 做持续监控

### 工作流

```
# 首次研究：用 search（非 regtrack）
veritas search --backend yuandian --type law "餐饮 食品安全 北京" --limit 10

# 持续监控：先注册，再定期 check
veritas regtrack add --industry 餐饮 --keywords 食品安全,食品经营 --region 北京 --count 50
veritas regtrack check --industry 餐饮 --region 北京 --since 2026-03 --until 2026-04
veritas regtrack status --industry 餐饮 --region 北京
```

### 分析深度要求

进行 regtrack 分析时，必须做到以下检查：

1. **多参数试探**：不要只试一组参数。先用 `--count 50`，再试 `--count 100` 看是否有遗漏。
2. **多关键词**：不要只用一个关键词。用 `--keywords 餐饮,食品安全,食品经营许可,反食品浪费` 多角度挖掘。
3. **结果分类**：对输出结果做分类：
   - 🏛️ **法律法规**：人大/国务院/部委发布的正式法规
   - 📋 **通知公告**：地方商务局、市监局等发布的行政通知
   - 📊 **报告**：年度报告、工作报告（通常不是法规）
4. **交叉验证**：对关键结果搜索补充信息确认其重要性。
5. **完整性说明**：报告中必须说明参数选择和可能的遗漏。
6. **无 region 时**：默认搜中央级法规（全国性法律）。

### 输出格式要求

```
## 搜索策略
- 关键词: 餐饮, 食品安全
- 地区: 北京
- 时间段: 2026-03 ~ 2026-04
- 结果数: 50

## 发现
### 新增法规（3条）
🏛️ 法规名称 — 发布部门 — 发布日期

### 行政通知（5条）  
📋 通知名称 — 发布部门 — 发布日期

### 报告/其他（2条）
📊 报告名称 — 发布部门 — 发布日期

## 完整性评估
- 搜索覆盖度: 高/中/低
- 可能遗漏: [说明]
```

### 自检标准

regtrack 分析不适合走 verify/finalize 管线（证据来源不同、报告结构不同），代之以以下自检清单。**如果 Agent 框架支持派发子代理，建议派独立子代理执行自检**，避免主 Agent 的确认偏误。

| # | 标准 | 含义 |
|---|------|------|
| 1 | **参数覆盖** | 至少试了 2 个 count + 2 个以上关键词组合，说明最终选择 |
| 2 | **分类准确** | 每条结果明确归入 🏛️法规 / 📋通知 / 📊报告，边界清晰 |
| 3 | **区分层级** | 市级 vs 区级分开列，标注发布部门 |
| 4 | **误报过滤** | 排除明显不相关结果，说明排除理由 |
| 5 | **置信度声明** | high/medium/low + 理由 |
| 6 | **遗漏说明** | 主动说明数据源限制和可能漏了什么 |
| 7 | **证据可回溯** | 每条发现能对应到 regtrack 数据条目 |

### 文件落地

分析结果必须写入 `.research/runs/<日期>-<主题>/draft-report.md`，按输出格式要求中的模板，以便追溯和审计。

## 中文法律案例搜索策略

需要查找真实案号时，**搜索引擎选择比搜索词更关键**。按以下优先级使用：

| 优先级 | 引擎 | 适用性 | 注意事项 |
|:---:|------|--------|----------|
| 1 | **360搜索** (so.com) | ✅ 中文法律内容索引好，无验证码 | 首选。对"客观情况重大变化"等法律术语不分词 |
| 2 | 浏览器直接访问 | ✅ 搜狐/澎湃/华律网/金柚网等转载文章 | 文章通常包含案号+裁判要旨+案情 |
| 3 | Bing 国内版 | ⚠️ 中文法律术语分词质量差 | "客观情况重大变化"会被拆成"客观"+"情况" |
| 4 | 百度 | ❌ 浏览器直接访问触发验证码 | 需 curl 或绕过 |
| 5 | Bing/Google 国际版 | ❌ 不索引中国法律网站 | 中文法律内容几乎搜不到 |
| 6 | 裁判文书网/北大法宝/无讼 | ❌ 需登录注册 | 不适合 Agent 快速查询 |

### 搜索技巧

1. **搜法律实务文章，而非裁判文书网**——搜狐/澎湃/华律网/金柚网等转载的案例文章更容易搜到，且包含案号、裁判要旨和案情摘要
2. **用当事人姓名+法院+关键词**精确搜索——如"邱丽红 参天公司 客观情况重大变化 案号"
3. **引号精确匹配**——360搜索支持 `"` 引号精确匹配，如 `"竞业限制" "违约金" "案号" "民终"`
4. **从搜索摘要直接提取案号**——360搜索摘要中常直接显示案号，无需点进文章
5. **交叉验证**——案号需在至少2个独立来源中出现才视为已验证

### 已验证案号

参见 `references/verified-case-numbers.md`，避免重复搜索。

## 陷阱与调试

### Python 版本与 CLI shebang不一致

`pip install -e .` 安装的 `veritas` CLI 脚本 shebang 可能指向 venv Python（如 `~/.hermes/hermes-agent/venv/bin/python`），而非 pyproject.toml 要求的 ≥3.11 Python。症状：CLI 输出与直接 Python 调用结果不一致（旧代码缓存）。

**验证方法**：`head -1 $(which veritas)` 检查 shebang，对比 `/opt/homebrew/bin/python3.13 -m research.cli` 的输出。

**修复**：始终用 `python3.13 -m research.cli verify/finalize` 替代 `veritas` 命令，或在正确 Python 下 `pip install -e .`。

### `_count_lines()` 计算非空行

`_count_lines()` 只计非空行（`line.strip()` 非空），`wc -l` 计总行数。写示例草稿时两者差异可达 40-50 行。**用 `python3.13 -c "from research.finalize import _count_lines; print(_count_lines(open('file').read()))"` 精确检查**，不要依赖 `wc -l`。

### general 类型证据表不能预填标签列

general 模板的证据表必须是**3列**（来源/类型/状态）。不能包含标签列、也不能包含"关键信息"等额外列。`finalize` 的 `parse_draft_report` 会将第一列当 URL 解析——若第一列是标签文字，所有证据被标记 `unknown` → dropped > admissible → fatal。标签列由 finalize 自动注入。

### general 类型必须有完成时间标记

报告最后一行必须是 `*完成时间: YYYY-MM-DDTHH:MM:SSZ*`（如 `*完成时间: 2026-06-05T10:30:00Z*`）。缺少此标记会被 verify/finalize 标记为 repairable，并使 FINAL_STATUS 降为 degraded。

### 法条条文号验证要点

1. **劳动合同法**（2012修正）条文号稳定，第四十条第三项、第二十三条、第二十四条、第四十六条、第四十八条、第八十七条等均可直接引用
2. **民事诉讼法**2023年9月修正（2024年1月施行）后，涉外编条文号全面重新编排。旧条文号（如第265/280/282条）已失效，新条文号需逐条查证——**不确定时写"依据《民事诉讼法》涉外编相关规定"而非使用旧条文号**
3. **《反不正当竞争法》**2019修正后新增第32条（举证责任转移）和第17条第4款（惩罚性赔偿），条文号准确
4. **所有法条引用前须在 flk.npc.gov.cn 核实**——模型对条文号的记忆不可靠
5. **已验证条文号速查**：参见 `references/verified-law-articles.md`，避免重复查证
6. **已验证案号速查**：参见 `references/verified-case-numbers.md`，避免重复搜索

### S# 引用 URL 须指向真实来源

`[S1](https://www.example.com/...)` 占位符 URL 不应出现在正式草稿中。S# 引用的 URL 须指向：
- 政府网站（flk.npc.gov.cn、gov.cn、sz.gov.cn 等）
- 国际组织网站（newyorkconvention1958.org 等）
- 权威法律数据库
- 已抓取的原文页面

若 URL 尚未获取，用裸引用 `[S1]` 而非填入假 URL。

### 引用不足影响判决（不仅是警告）

引用缺口（法条/案号/S#）会导致 verdict 从 pass 降为 repairable。这不是可忽略的警告——practical-guide 缺3处法条引用、case-research 缺2个案号，都会阻止 FINAL_STATUS=pass。

## 禁忌

- **绝对禁止编造案号、法条条文号、裁判文书内容**——这是 veritas 最核心的红线。一个审引用的工具自己造引用，比没有引用更危险。
  - 案号必须来自真实裁判文书（可在 wenshu.court.gov.cn 或 pkulaw.com 检索验证）
  - 法条条文号必须经过核实（来源：flk.npc.gov.cn 国家法律法规数据库）
  - 若无法验证案号/条文号的真实性：标注"（示意）"并在置信度声明中明确说明，绝不能冒充真实
  - 若对民诉法等2023修正后的条文号不确定，写"依据《XX法》涉外编相关规定"而非编造条文号
- 不能凭记忆答时效性问题
- 搜索摘要 ≠ 正文证据（必须 scrape 获取全文）
- 转载 ≠ 独立来源（需找原始出处）
