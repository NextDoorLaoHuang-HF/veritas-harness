# Regtrack 增强：多关键词、Region 限定、可配结果数

## 概述

为 `research regtrack` 命令增加多关键词搜索、地区限定监控和可配结果数量，使餐饮等法规密集行业的监控更精准。

## 数据模型变更

### `IndustryGroup`

```python
@dataclass
class IndustryGroup:
    keywords: list[str]    # 旧: keyword: str → 自动迁移为 [keyword]
    region: str = ""        # 空=中央级；具体值如 "广东""北京""上海"
    added: str
    last_checked: str = ""
    regulations: list = field(default_factory=list)
```

### 唯一标识

内部 key = `{name}@{region}`（region 为空时等于 `{name}`，兼容旧数据）。

- `--keywords 餐饮,食品安全` → name = `餐饮`, key = `餐饮`
- `--keywords 餐饮,食品安全 --region 广东` → key = `餐饮@广东`
- `--keywords 餐饮 --region 北京` → key = `餐饮@北京`

### 迁移

旧 `regtrack.json` 中 `IndustryGroup.keyword` 为字符串，加载时自动转为 `[keyword]`，`region=""`。

## 搜索策略

| 场景 | API | 参数 | 说明 |
|------|-----|------|------|
| 无 `--region` 无 `--since/--until` | `law_vector_search` | `query=keyword, return_num=count` | 当前行为不变，结果均为中央级 |
| 有 `--region` 无 `--since/--until` | `rh_fg_search` | `keyword=keyword, dy=region, top_k=min(count, 50)` | 仅返回该地区特有法规 |
| 有 `--since/--until` | `rh_fg_search` | `keyword=keyword, dy=region(可选), fbrq_start/fbrq_end, top_k=min(count, 50)` | 按发布日期范围过滤 |

- `--since/--until` 强制走 `rh_fg_search`（因为 `law_vector_search` 不支持日期过滤）
- 多个 keyword 各自搜索，按 `fgid`/`id` 去重合并
- 不混搜 region（有 region 时不额外搜中央法规）

### 后端变更：`_search_law`

```python
def _search_law(self, query: str, count: int = 50, region: str = "",
                since: str = "", until: str = "") -> list[SearchResult]:
    if region or since or until:
        body = {"keyword": query, "top_k": min(count, 50)}
        if region:
            body["dy"] = region
        if since:
            body["fbrq_start"] = since
        if until:
            body["fbrq_end"] = until
        data = self._post("rh_fg_search", body)
        # 解析 data 列表（当前 fallback 路径已有此逻辑）
    else:
        data = self._post("law_vector_search", {"query": query, "return_num": count})
        # 解析 extra.fatiao（当前主路径逻辑不变）
```

## CLI 接口

```
research regtrack add --keywords 餐饮,食品安全 --region 广东 --count 100
research regtrack check --industry 餐饮 --region 广东 --count 100 --since 2026-03 --until 2026-04
research regtrack status --industry 餐饮 --region 广东
research regtrack remove --industry 餐饮 --region 广东
```

- `--keywords`：逗号分隔（**新**）
- `--industry`：保留为单关键词别名，相当于 `--keywords X`
- `--region`：可选，地区名（**新**）
- `--count`：可选，结果数，默认 50（**新**）
- `--since`：可选，发布日期起始，格式 `YYYY-MM-DD` 或 `YYYY-MM`（**新**，仅 check）
- `--until`：可选，发布日期截止，格式同上（**新**，仅 check）

## 输出格式

```
行业: 餐饮@广东 (12 部法规)  最后检查: 2026-05-26
  ✓ 广东省食品安全条例 — 现行有效
  ✓ 广东省餐饮服务食品安全监督管理办法 — 现行有效

行业: 餐饮 (8 部法规)  最后检查: 2026-05-25
  ✓ 中华人民共和国食品安全法 — 现行有效
```

- JSON 输出增加 `region` 和 `keywords` 字段

## 改动文件

| 文件 | 改动 |
|------|------|
| `src/research/regtrack.py` | `IndustryGroup` 字段变更；`add/check` 签名扩展；`format_status` region 显示；旧数据迁移 |
| `src/research/backends/yuandian.py` | `_search_law` 增加 `region` 参数；`search()` 透传 kwargs |
| `src/research/cli.py` | `--keywords`, `--region`, `--count` 参数；`cmd_regtrack` 逻辑适配 |
| `tests/test_regtrack.py` | 新增 region 搜索测试、多关键词测试、count 参数测试、旧数据兼容测试 |

## 边界情况

- `--keywords` 和 `--industry` 同时传：报错提示二选一
- 旧 `regtrack.json` 自动兼容：`keyword` 字符串 → 加载为 `keywords=[keyword]`
- `rh_fg_search` 的 `top_k` 上限 50，`--count 200` 时仍只返回最多 50 条
- `region` 值非法（非 API 支持的 `dy` 值）：由 API 返回空结果，不做额外校验
- `check` 时只对 `keywords` 在本地区搜索，不跨越地区
- `--since/--until` 仅对 `check` 生效，`add` 忽略；格式为 `YYYY-MM-DD` 或 `YYYY-MM`（自动补全为当月首日/末日）
- `--since/--until` 强制使用 `rh_fg_search`，此时结果来自关键词匹配而非语义检索
