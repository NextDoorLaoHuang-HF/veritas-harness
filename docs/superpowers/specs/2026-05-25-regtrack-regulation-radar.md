# Regulation Tracking (regtrack) — 法规雷达

## 动机

企业法务/合规团队需要按行业监控法规变动：新规出台、现有法规修订、法规废止。手动跟踪各立法机关网站不可持续。

## 设计原则

1. **按行业聚合** — 一次 keyword 搜索注册整个行业相关法规，而非逐条手动添加
2. **触发式检测** — Agent 手动执行 `regtrack check`，无需常驻进程或 cron
3. **增量发现** — 每次 check 自动发现行业内的新法规
4. **内容级 diff** — 不仅提示"变了"，还展示具体修改了什么

## 数据模型

存储文件：`.research/regtrack.json`

```json
{
  "industries": {
    "数据安全": {
      "keyword": "数据安全",
      "added": "2026-05-25T12:00:00",
      "last_checked": "2026-05-25T12:00:00",
      "regulations": [
        {
          "id": "4d2a64f343ccc59066bf0adf84ec5e0e",
          "name": "数据安全法",
          "status": "现行有效",
          "snapshot": {
            "content_hash": "sha256:e3b0c44...",
            "content": "全文快照...",
            "taken_at": "2026-05-25T12:00:00"
          }
        }
      ]
    }
  }
}
```

- `snapshot.content_hash` — content 全文的 SHA256，快速比对
- `snapshot.content` — 缓存全文，用于生成 diff
- `status` — 上次确认时的 sxx 值

## CLI 命令

```
research regtrack add --industry "数据安全"    # 搜索 + 注册整个行业
research regtrack add --id <id>               # 按 ID 注册单条法规
research regtrack remove --id <id>            # 移除单条
research regtrack remove --industry "数据安全" # 移除整个行业
research regtrack check                       # 检测全部行业
research regtrack check --industry "数据安全"  # 检测指定行业
research regtrack status                      # 展示状态
research regtrack status --json               # JSON 输出
```

### `add --industry` 流程

1. 调用 `YuandianBackend.search(keyword, legal_type="law")` 搜索法规
2. 对每条结果：若 `id` 尚未在跟踪列表中 → 调用 `rh_fg_detail` 取全文 → 计算 hash → 存入 snapshot
3. 写入 `.research/regtrack.json`

### `check` 流程

对每个行业（或指定行业）：

1. **发现新法**：重新 `search(keyword)`，对比跟踪列表。未跟踪的 → 标记 `[新增]`，自动加入
2. **检测变更**：遍历已跟踪法规，调用 `rh_fg_detail`：
   - `content` hash 不同 → 用 `difflib.unified_diff` 计算差异 → 标记 `[变更]`
   - `sxx` 从现行有效变为其他 → 标记 `[失效]`
   - 无变化 → 标记 `[正常]`
3. 更新缓存（新 hash + 新 content）

### `status` 输出

```
行业: 数据安全 (5 部法规)
  ✓ 数据安全法                          — 正常
  ✗ 数据安全管理办法(试行)              — 已失效
  ! 网络数据分类分级要求                — 内容已变更 (2026-05-20)
    @@ -120,5 +120,7 @@
    - 三级数据应当...
    + 三级数据应当经安全评估后...
  + 数据跨境安全评估办法 (2026-05-20)   — 新增
```

## 文件清单

### 新增
- `src/research/regtrack.py` — 核心数据层 + CLI 逻辑
- `tests/test_regtrack.py` — 单元测试 + 集成测试

### 修改
- `src/research/cli.py` — 添加 `regtrack` 子解析器

### 不变
- `backends/yuandian.py` — 复用现有接口
- `verify.py`, `finalize.py`, `hallucination.py` — 不变
- 所有现有测试不变

## 测试计划

| 测试 | 类型 | 方法 |
|------|------|------|
| `test_add_industry_new` | 单元 | mock search + detail，验证写入 regtrack.json |
| `test_add_industry_duplicate` | 单元 | 重复注册同一行业，验证幂等 |
| `test_check_new_law` | 单元 | search 返回新结果，验证标记新增 |
| `test_check_content_changed` | 单元 | detail 返回不同 content，验证标记变更 + diff |
| `test_check_law_expired` | 单元 | detail 返回 sxx=已失效，验证标记失效 |
| `test_check_no_change` | 单元 | 内容无变化，验证标记正常 |
| `test_status_output` | 集成 | 模拟 regtrack.json，验证 status 格式 |
| `test_remove_by_id` | 单元 | 移除后文件不含该法规 |
| `test_remove_industry` | 单元 | 移除后文件不含该行业 |
| `test_cli_regtrack_commands` | 集成 | mock 后端，验证 CLI 入口路由正确 |

## 不变部分

- 后端协议不变，`YuandianBackend` 不修改
- 不添加新的 CLI 顶层命令，`regtrack` 是 `research` 的子命令
- 不引入新依赖（difflib 是标准库）
