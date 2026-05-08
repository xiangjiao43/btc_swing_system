# Sprint B — 网页诚实显示 + 顺手修副作用 bug

**日期**:2026-05-08
**类型**:数据真实性透明化系列(A→B→C→D)第二步
**Commit**:`34175b1`(feat(web): Sprint B — 数据源诚实显示 + 修 collect_onchain
多余 enqueue 副作用)

## 背景

Sprint A 把 `fetch_attempts` 表 + 共用底座做完后,网页"数据源"那栏仍读老的
`/api/system/health-detail` 的 `data_sources` 字段 — 它来自
`SELECT MAX(inserted_at_utc) FROM <metric_table>`,被 `derived_mvrv` 这种
"上游 fail 但本地仍写行"的副作用骗过,即使 Glassnode 13 fetcher 全 403
仍显示绿点 "ok"。

Sprint B 把网页改成读 fetch_attempts 真实状态,并顺手修 collect_onchain
触发多余 pipeline_run 的副作用 bug(同一根因)。

## 改动清单

| 路径 | 行 | 类型 | 说明 |
|---|---|---|---|
| `src/api/routes/data_sources.py` | +144 | 新建 | `GET /api/data_sources/freshness` 路由 |
| `src/api/models.py` | +17 | 修改 | `DataSourceFreshness` 响应模型 |
| `src/api/app.py` | +3 | 修改 | 注册新路由 `data_sources_routes.router` |
| `src/scheduler/jobs.py` | +9/-6 | 修改 | `collect_onchain` enqueue 条件改 `gn_first_exc is None and glassnode_rows > 0` |
| `web/assets/app.js` | +60/-22 | 修改 | 新 state `dataSourcesFreshness` + 6 个 helper(状态颜色 / 中文徽章 class / staleHint / tooltip)|
| `web/index.html` | +25/-12 | 修改 | 数据源那栏 template 全替换 |
| `tests/test_api_data_sources_freshness.py` | +258 | 新建 | 9 个 e2e 测试 |
| `tests/test_jobs_fetch_attempts_integration.py` | +55 | 修改 | +2 个反退化测试(enqueue 不调 vs 调) |

合计:8 文件,+583 / -39 行。

## 设计决策

### 1. 4 个固定 source label

`_EXPECTED_SOURCES` 在 `data_sources.py` 里写死 4 行(顺序就是网页显示顺序):
- binance_kline → "Binance K 线"
- coinglass_derivatives → "CoinGlass 衍生品"
- glassnode_onchain → "Glassnode 链上"
- fred_macro → "FRED 宏观"

**生产 DB 当前只有前 3 个 source** 有行(因为 Sprint A 部署时刻是 BJT 15:47,
今天的 collect_macro 06:00 已过、明天 06:00 才会写第一行 fetch_attempts);
fred_macro 行返回 status=no_data。

### 2. failure 时 last_success_at 回填

如果 latest attempt 是 failure,API 自动 SELECT 该 source 最近一条 success
attempt 的 `attempted_at_utc`,前端用来显示"沿用 X 月 X 日数据"。
从未成功过则返回 null,前端显示"从未成功过"。

### 3. 5 桶 failure_reason 中文徽章

| failure_reason | 中文徽章 | 颜色样式 |
|---|---|---|
| quota_exceeded | 配额用尽 | 红底白字(rose-500) |
| network_error | 网络错误 | 黄底深字(amber) |
| api_error | API 错误 | 黄底深字 |
| parse_error | 数据格式错误 | 黄底深字 |
| unknown | 未知错误 | 灰底深字 |

按用户原 spec 的颜色映射:quota 用红(配额耗尽是硬阻塞,与全 fail 同等
级);其他 4 桶用黄(可能是临时问题)。

### 4. 网页双层信息架构

每行包含:
1. **第一行(主信息)**:🟢/🔴 圆点 + `display_name` + 中文失败徽章 + `minutes_ago`
2. **第二行(灰字小字,只 failure 显示)**:`沿用 X 月 X 日数据`

完整错误信息(error_message + duration_ms + rows_upserted + BJT 时间)
通过 `<li :title>` 给鼠标 hover tooltip。这样普通用户看一眼就明白
"绿/红 + 多久前 + 失败原因",hover 才看完整堆栈。

### 5. collect_onchain enqueue 副作用 bug

**老逻辑**(jobs.py 第 837):
```python
# Sprint 2.7-D
if total > 0:
    _enqueue_pipeline_run("event_onchain")
```
其中 `total` = Glassnode 入库行数 + derived_mvrv 派生行数。今天 Glassnode 全
403 → 0 行,但 `compute_and_save_derived_mvrv` 用昨天 realized_price 算出
748 行 lth_mvrv/sth_mvrv → `total > 0` → enqueue → v1.3 orchestrator 跑
失败 stack trace(根因记录于 `glassnode_frequency_audit.md`)。

**新逻辑**:
```python
gn_success = (gn_first_exc is None) and (glassnode_rows > 0)
if gn_success:
    _enqueue_pipeline_run("event_onchain")
```
`gn_first_exc` 是 Sprint A 已经在 body 内 track 的字段,`glassnode_rows`
是新加的(只计 Glassnode 一手 fetcher 的入库行数,不含派生)。语义:
- 13 fetcher 全成功 + 入库 > 0 → enqueue ✅
- 任一 fetcher fail → 不 enqueue(即使 derived 写了行)
- 全成功但全空响应(rows=0) → 不 enqueue(没新数据)

### 6. /api/system/health-detail 老 data_sources 字段保留

Sprint B 不动 `_query_data_source_freshness` 和 `HealthDetailResponse.data_sources`,
理由:它仍喂 `_aggregate_overall()` 算顶栏徽章 `selfCheckBadgeLabel`(全部正常
✅ / ⚠️ 部分降级 / ❌ 数据中断)。这层逻辑也 broken(Glassnode 全 fail 时
仍报 "全部正常"),但 Sprint C 数据健康判定时一并改更合理 — Sprint B 严格
只换"数据源"那栏。

## 关键 diff 节选

### `data_sources.py` 核心查询

```python
def _row_for_source(conn, source, display_name, now):
    latest = conn.execute(
        "SELECT attempted_at_utc, status, failure_reason, error_message, "
        "       rows_upserted, duration_ms FROM fetch_attempts "
        "WHERE source = ? ORDER BY attempted_at_utc DESC, id DESC LIMIT 1",
        (source,),
    ).fetchone()
    if latest is None:
        return DataSourceFreshness(source=source, display_name=display_name, status="no_data")
    # ... 取 status, failure_reason_label
    if status == "success":
        last_success_at_utc = last_attempt_at_utc
    else:
        succ = conn.execute(
            "SELECT attempted_at_utc FROM fetch_attempts "
            "WHERE source = ? AND status = 'success' "
            "ORDER BY attempted_at_utc DESC, id DESC LIMIT 1",
            (source,),
        ).fetchone()
        last_success_at_utc = succ["attempted_at_utc"] if succ else None
    return DataSourceFreshness(...)
```

### jobs.py 副作用 bug 修法

```diff
-        # Sprint 2.7-D:onchain 抓完立即 enqueue 一次 pipeline_run
-        if total > 0:
+        # Sprint B fix:只有 Glassnode bucket 真 success 才 enqueue;上游 fail 时
+        # derived_mvrv 写若干行不算"新数据"。
+        gn_success = (gn_first_exc is None) and (glassnode_rows > 0)
+        if gn_success:
             _enqueue_pipeline_run("event_onchain")
         return {
             "by_collector": {
-                "glassnode": total - sum(derived_stats.values()),
+                "glassnode": glassnode_rows,
                 "derived_mvrv": sum(derived_stats.values()),
             },
             "total_upserted": total,
-            "events_triggered": ["event_onchain"] if total > 0 else [],
+            "events_triggered": ["event_onchain"] if gn_success else [],
```

### 网页"数据源"那栏

```diff
-        <ul class="space-y-1">
-          <template x-for="src in (systemHealth?.data_sources || [])"
-                    :key="src.name">
-            <li class="flex items-center gap-2 leading-snug"
-                :title="(src.captured_at_bjt || '无数据') + ' · ' + src.expected_cadence">
-              <span :class="sourceStatusGlyphClass(src.status)" x-text="sourceStatusGlyph(src.status)"></span>
-              <span :class="sourceTextClass(src.status)" x-text="src.name"></span>
-              <span :class="sourceTextClass(src.status)" x-text="sourceAgeLabel(src)"></span>
+        <ul class="space-y-1">
+          <template x-for="src in (dataSourcesFreshness || [])"
+                    :key="src.source">
+            <li class="leading-snug" :title="sourceTooltip(src)">
+              <div class="flex items-center gap-2">
+                <span :class="sourceStatusGlyphClass(src.status)" x-text="sourceStatusGlyph(src.status)"></span>
+                <span class="flex-1 flex items-center gap-1.5"
+                      :class="sourceTextClass(src.status)">
+                  <span x-text="src.display_name"></span>
+                  <span x-show="src.status === 'failure' && src.failure_reason_label"
+                        :class="sourceReasonBadgeClass(src.failure_reason)"
+                        x-text="src.failure_reason_label"></span>
+                </span>
+                <span :class="sourceTextClass(src.status)" x-text="sourceAgeLabel(src)"></span>
+              </div>
+              <div x-show="src.status === 'failure'"
+                   class="ml-6 text-[10px] text-slate-400"
+                   x-text="sourceStaleHint(src)"></div>
             </li>
           </template>
         </ul>
```

## 验收记录

### A. API 直接 curl(已在生产服务器运行)

```
$ ssh ubuntu@124.222.89.86 "curl -s http://127.0.0.1:8000/api/data_sources/freshness | python3 -m json.tool"
[
  {
    "source": "binance_kline",
    "display_name": "Binance K 线",
    "status": "success",
    "last_attempt_at_utc": "2026-05-08T08:00:05.270438Z",
    "last_attempt_at_bjt": "2026-05-08 16:00:05",
    "minutes_ago": 19,
    "rows_upserted": 24, "duration_ms": 5243,
    ...
  },
  {
    "source": "coinglass_derivatives",
    "display_name": "CoinGlass 衍生品",
    "status": "success", "minutes_ago": 19,
    "rows_upserted": 35, "duration_ms": 3065, ...
  },
  {
    "source": "glassnode_onchain",
    "display_name": "Glassnode 链上",
    "status": "failure",
    "minutes_ago": 19,
    "failure_reason": "quota_exceeded",
    "failure_reason_label": "配额用尽",
    "error_message": "HTTP 403 (non-retry) on /v1/metrics/market/mvrv_z_score: ... 您的 glassnode 周期内配额已用尽",
    "rows_upserted": 0, "duration_ms": 8296,
    "last_success_at_utc": null
  },
  {
    "source": "fred_macro",
    "display_name": "FRED 宏观",
    "status": "no_data",
    "last_attempt_at_utc": null, ...
  }
]
```

字段全齐,中文徽章正确,glassnode 显示 quota_exceeded + 配额用尽 + 完整 error。

### B. pytest

新加 11 个测试(9 API e2e + 2 反退化)+ 之前所有测试全过:
```
1576 passed, 1 skipped, 0 failed
```
对比 Sprint B-prep:1565 passed → 1576 passed(+11)。

### C. 副作用 bug 反退化测试

```python
def test_collect_onchain_all_fail_does_not_enqueue_pipeline_run(...):
    """13 个 fetcher 全 403 → derived_mvrv 仍可能本地写 5+5 行,
    但 Sprint B 修后 _enqueue_pipeline_run 不应被调用。"""
    enqueue.assert_not_called()  # ← Sprint A 之前会失败
```

加上正向 case 验证 `assert_called_once_with("event_onchain")` 在真 success
时仍触发,确保没把 retry 链一起改坏。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1576 passed, 1 skipped, 0 failed |
| GitHub push(commit hash:34175b1)| ✅ 已 push origin/main |
| 服务器 git pull | ✅ Fast-forward 0bb042b..34175b1 |
| 服务器 systemctl restart | ✅ `is-active = active`,curl `/api/data_sources/freshness` 返回正确 4 行 |
| 生产 DB 迁移 / 清污 | N/A(本 sprint 无 schema 改动)|

## 段 3 同类风险扫描

### 1. /api/data_sources/freshness 路径冲突?

`grep -rn 'data_sources' src/api/routes/ web/` 显示 0 个 prefix 冲突;
路由文件 `data_sources.py` 用 prefix=`/data_sources` 与现存 `data` prefix
(`/api/data/summary`)是不同路径。pytest e2e 直接 200 OK,生产 curl 也 200。

### 2. 中文 display_name 是否覆盖所有真实 source?

生产 DB `SELECT DISTINCT source FROM fetch_attempts`:`binance_kline /
coinglass_derivatives / glassnode_onchain` 三行(fred_macro 因 collect_macro
在服务重启后还没 fire 而暂无行)。

`_EXPECTED_SOURCES` 写死 4 个,与 jobs.py `_record_fetch_attempt` 调用点
1:1 对齐,没有"额外的第 5 源"。如果未来 Sprint C 加新 collector(如
binance_spot_price 之类),需要同步加进 `_EXPECTED_SOURCES` 和
`_FAILURE_REASON_LABELS`。

### 3. 副作用 bug 修法误伤?

正向反退化测试 `test_collect_onchain_real_success_does_enqueue_pipeline_run`
确认:13 fetcher 全成功 + 入库 > 0 时 `_enqueue_pipeline_run` 仍被调用一次。
未误伤正常 success 路径。

### 4. 网页 mock fallback 旧 stub 4 行?

`grep -rn '数据源\|data_sources' web/` 只在 `index.html` line 322-345
那一段 + `app.js` 改过的 helper 区命中,**没有别处 hardcoded 的 4 行 stub**。
`v1.4.2` 时期的占位符全部走 `placeholder-dash` class,不在数据源那栏。

### 5. /api/system/health-detail 老逻辑

未动 `_query_data_source_freshness` + `HealthDetailResponse.data_sources` +
`_aggregate_overall()`。顶栏徽章(`selfCheckBadgeLabel`)仍走老路径。
**留 Sprint C 数据健康判定时一并改**。

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 老 `sourceStatusGlyph` `sourceStatusGlyphClass` `sourceTextClass` `sourceAgeLabel` 4 个 helper | web/assets/app.js | API 形状变了:从 `status ∈ {ok/warn/critical/no_data}` 变成 `{success/failure/no_data}`,4 行字段也变(`age_minutes` → `minutes_ago` 等)。**全部重写,不留兼容**。 |
| 老 `<template x-for="src in (systemHealth?.data_sources || [])">` 块 | web/index.html:325-339 | 替换成新 template,读 `dataSourcesFreshness`,数据源那栏完整重写。 |

`git grep 'systemHealth?.data_sources\|systemHealth\.data_sources'` 在 web/
和 src/ 里 0 命中(老字段在 health-detail 响应里仍存在,但前端没有任何
代码再读它 — 留待 Sprint C 一并清理 server-side 字段)。

## 未覆盖 / 留给 C/D

按用户「不在范围」明示,本 sprint 不做以下:

1. **Cron 配置改动**(Sprint C):quota-aware retry / 多档 cron 收敛 / 配额日重置
   时间识别。
2. **AI prompt 加 fetch_attempts 摘要**(Sprint D):让 AI 知道哪个数据源
   stale,在 trade_plan 时 down-weight。
3. **派生指标 stale 连锁**(Sprint C):`compute_and_save_derived_mvrv` 在
   Glassnode 上游 fail 时仍写行,导致 strategy_runs 状态被骗;Sprint C
   重新规划。
4. **`data_fetch_log` 老表 DROP**(Sprint D 收尾):本 sprint 仍 0 读 0 写,
   保留待 D 结束时一并清理。
5. **顶栏 `overall_status` 徽章用 fetch_attempts**(Sprint C):当前仍读老
   `_aggregate_overall(layers, sources)`,Glassnode 全 fail 时还是显示"全部
   正常 ✅"。

## 用户验证

服务器已重启,API 已 live。建议刷新浏览器 http://124.222.89.86 查
"数据源"那栏:

- 🟢 Binance K 线 19 分钟前
- 🟢 CoinGlass 衍生品 19 分钟前
- 🔴 Glassnode 链上 [配额用尽 红徽章] 19 分钟前抓取失败 / 沿用 (从未成功过 — 因为 fetch_attempts 表新加,在它出现前的成功历史不在记录里)
- ⚪ FRED 宏观 尚未抓取

`fred_macro` 行明早 06:00 BJT collect_macro cron 跑过后会变成 success。
`glassnode_onchain` "从未成功过"是 Sprint A 表新加的纪录窗口效应,等明天
配额 reset 后会被首个真 success 覆盖。
