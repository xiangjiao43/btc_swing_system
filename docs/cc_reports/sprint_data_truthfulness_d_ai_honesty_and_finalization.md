# Sprint D — AI 诚实约束 + Sprint B-fix 文案根治 + 收尾清理

**日期**:2026-05-08
**类型**:数据真实性透明化系列(A→B→C→D)收官
**Commit**:`935e20d`(feat(data-truthfulness): Sprint D — AI 诚实约束 + B-fix
文案根治 + 收尾清理)

## 背景

A→B→C 完成"数据透明化底座 + 网页诚实显示 + Glassnode 重试 + 派生 stale 守卫
+ 顶栏徽章修复"。Sprint D 收官:
- API fallback 让网页文案不再「从未成功过」/「尚未抓取」(B-fix 合并)
- state_builder 写入 4 源 freshness 摘要,下游消费
- AI master_adjudicator prompt 注入 freshness + system prompt 加纪律
- 显示侧 evidence_layers stale 守卫
- 全套清理:DROP data_fetch_log 老表

架构妥协:用户拍板 Sprint D Item 4 走 (A) 显示侧覆盖,(B) 5 个 sub-agent
prompt 注入留 Sprint E backlog。

## 改动清单

| 路径 | 类型 | 说明 |
|---|---|---|
| `src/data/freshness.py` | **新建 +296** | 共用 freshness 模块:fetch_attempts 优先 + 数据表 MAX(inserted_at_utc) fallback;`SourceFreshness` dataclass + `compute_all_freshness` + `stale_summary_for_layer` + `LAYER_SOURCE_DEPS` |
| `migrations/017_drop_data_fetch_log.sql` | 新建 +9 | DROP 老 data_fetch_log 表 |
| `src/api/routes/data_sources.py` | 重写 -94/+34 | 内部实现搬到共用模块,只负责 API 层 BJT 格式化 |
| `src/api/routes/system.py` | +47 | `_apply_layer_stale_overrides`(显示侧覆盖)+ `_query_fetch_attempts_failures` 接 freshness 模块 |
| `src/pipeline/state_builder.py` | +20 | `_build_data_freshness_block` → state.full_state_json["data_freshness"] |
| `src/ai/master_input_builder.py` | +16 | `_build_data_freshness_summary` 注入 master input |
| `src/ai/agents/master_adjudicator.py` | +52 | `_format_freshness_block` 渲染 [数据新鲜度] 段 |
| `src/ai/agents/prompts/master_adjudicator.txt` | +20 | 第九节「过期数据纪律」 |
| `src/ai/validator.py` | +50 | `validator_stale_disclosure`(VStale) + 加入 pipeline + retry 聚合 |
| `web/assets/app.js` | +14/-7 | `sourceAgeLabel` / `sourceStaleHint` 支持 fallback;新加 `_humanAgeFromBjt` |
| `web/index.html` | +1/-1 | 「沿用」副标题在 failure / no_data 都显示 |
| `src/data/storage/schema.sql` | -10/+5 | 删 data_fetch_log CREATE 块 |
| `src/data/storage/dao.py` | -6/+4 | 删 DataFetchLogDAO 注释 |
| `tests/test_sprint_d_freshness_and_stale.py` | **新建 +444** | 17 个端到端测试 |
| `tests/test_health_detail_endpoint.py` | +24 | 适配 Sprint D 显示侧 stale 守卫(test_evidence_layers_all_healthy seed 4 源 fresh) |
| `tests/test_sprint_c_derived_stale_and_overall.py` | +6/-13 | 适配 Sprint D 中 _query_fetch_attempts_failures 也算 is_stale |
| `tests/test_validator_v14_integration.py` | +6/-3 | 28→33 字段计数(Sprint D 加 1 个持久化字段) |

合计 +1161 / -158 行。

## 设计决策

### 1. 共用 freshness 模块

避免 4 处(API / state_builder / system display / AI prompt)各自查 fetch_attempts,
集中到 `src/data/freshness.py` 单源真相:

```python
@dataclass(frozen=True)
class SourceFreshness:
    source: str
    display_name: str
    status: str                         # success / failure / no_data
    last_attempt_at_utc: str | None
    last_success_at_utc: str | None
    minutes_since_last_attempt: int | None
    hours_since_last_success: float | None
    is_stale: bool
    failure_reason: str | None
    failure_reason_label: str | None    # 中文徽章
    error_message: str | None
    rows_upserted: int | None
    duration_ms: int | None
    last_success_source: str | None     # 'fetch_attempts' / 'data_table'
```

### 2. fallback 用 inserted_at_utc 而非 captured_at_utc

CoinGlass 衍生品和 Glassnode 链上数据 captured_at_utc 是 daily bar 日期(凌晨
0 点),inserted_at_utc 是实际写入时间。如果用 captured 当 fallback,健康日
也会显示「沿用 X 月 X 日」(因为日级 bar 自然滞后 24-48h)。改用 inserted 反
映"何时抓取到",更准。

### 3. 4 源 stale 阈值

| source | 阈值 | 理由 |
|---|---|---|
| binance_kline | 3h | K 线 1h cron,容忍 3 倍 |
| coinglass_derivatives | 3h | 同上(随 collect_klines_1h 一起跑) |
| glassnode_onchain | 48h | 沿用 Sprint C 派生指标守卫常量 |
| fred_macro | 72h | 日级 + 周末 FRED 不更新 |

### 4. master prompt freshness 块格式

`MasterAdjudicator._format_freshness_block` 渲染:
```
===== [数据新鲜度] Sprint D Item 3 =====
  🟢 Binance K 线:0.5 小时前成功
  🟢 CoinGlass 衍生品:0.5 小时前成功
  ⚠️ Glassnode 链上:已过期 72.5 小时(配额用尽),沿用 2026-05-05 数据
  🟢 FRED 宏观:8.0 小时前成功
🛑 纪律(system prompt §过期数据):任一源 is_stale=true 时,narrative
**必须**明确写"X 数据已过期 N 小时,本判断可信度相应降级",且不得给 high
置信度结论;违反则 validator 拒绝,走 fallback。
```

任一 ⚠️ → 加纪律语句;全 🟢 → 只列状态。

### 5. master_adjudicator.txt 第九节(prompt 纪律)

新加段「九、过期数据纪律(Sprint D Item 3)」明确 3 条要求:
1. narrative 含「过期」/「沿用」/「stale」关键词 + 中文源名 + 小时数
2. confidence_score ≤ 0.6
3. break_conditions 至少一条「等数据恢复」回退条件

例外:`mode=evaluate_existing` 仍需点名 stale 源 + 降一档 still_valid。

### 6. validator_stale_disclosure(VStale)

`silent_cooldown` mode 不强制(本来就最保守);其他 mode 检查 narrative
关键词。失败 → notes + `validator_stale_disclosure_needs_retry` →
`validator_needs_retry=True` → orchestrator 同 run 重试 1 次(走现有 V8/V9/V11/V21
retry 路径)。

### 7. 显示侧 evidence_layers stale 覆盖(Item 4 选项 A)

`LAYER_SOURCE_DEPS` 静态映射:
- L1 = (binance_kline,)
- L2 = (binance_kline, glassnode_onchain)
- L3 = ()  # 衍生自 L1+L2,不直接依赖 source
- L4 = (coinglass_derivatives, glassnode_onchain)
- L5 = (fred_macro,)

`_apply_layer_stale_overrides` 在 `_query_evidence_layers_health` 末尾跑:
某层依赖源 stale → `health = "degraded"`(if was healthy);
`missing_reasons` 追加「依赖的 X 数据已过期 N 小时」。

AI 内部 confidence_tier **不动** —— 只覆盖 API 输出的显示字段。这避免硬覆盖
AI 输出值的高风险动作(B 选项留 Sprint E)。

### 8. fetch_attempts → data_freshness → AI prompt 全链路验证

```
fetch_attempts (Sprint A)
    ↓
src/data/freshness.py compute_all_freshness  ← 单源真相
    ↓
四处消费:
    1. /api/data_sources/freshness               (网页"数据源"那栏 + 沿用 X 月 X 日)
    2. state_builder.full_state_json["data_freshness"]  (持久化,审计可查)
    3. master_input_builder.data_freshness_summary       (AI prompt 注入)
    4. system.py _apply_layer_stale_overrides            (evidence_layers 显示侧)
```

## 验收记录

### A. 生产 API fallback 工作(curl 真实输出)

```
glassnode_onchain:
  status=failure
  failure_reason_label="配额用尽"
  last_success_at_bjt="2026-05-06 14:00:31"   ← Sprint D 之前是 null
  error_message="HTTP 403 (non-retry) ... 配额已用尽"

fred_macro:
  status=no_data
  last_success_at_bjt="2026-05-08 08:00:11"   ← 今早 macro_metrics fred 写入
                                                Sprint D 之前是 null,网页显示
                                                「尚未抓取」
```

### D. 显示侧 evidence_layers stale 覆盖(curl 真实输出)

```
L1 市场状态层:    healthy
L2 方向结构层:    degraded   missing_reasons=["依赖的 Glassnode 链上 数据已过期 51.4 小时"]
L3 机会执行层:    healthy
L4 风险失效层:    degraded   missing_reasons=["依赖的 Glassnode 链上 数据已过期 51.4 小时"]
L5 背景事件层:    healthy
overall_status:   critical
```

L2 / L4 health 从 healthy 被覆盖成 degraded ✅;L1 / L5 不依赖 glassnode → 不动 ✅。

### E. data_fetch_log 已 DROP

```
$ ssh ubuntu@... "sqlite3 data/btc_strategy.db '.schema data_fetch_log'"
(无输出 = 表已删除)
```

### F. 本地 + 服务器 pytest

本地:`1599 passed, 1 skipped, 0 failed`(Sprint C 后 1582 → 1599,+17 新测)。

### G. 服务器 git pull + migration + restart

```
$ ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && \
   git pull --ff-only && \
   sqlite3 data/btc_strategy.db < migrations/017_drop_data_fetch_log.sql && \
   sudo systemctl restart btc-strategy.service"
Updating 17482c3..935e20d (Fast-forward)
active
```

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1599 passed, 1 skipped, 0 failed |
| GitHub push(commit hash:935e20d) | ✅ 已 push origin/main |
| 服务器 git pull | ✅ Fast-forward 17482c3..935e20d |
| 服务器 systemctl restart | ✅ active(API curl + DB schema 已验证) |
| 生产 DB 迁移(applied 017) | ✅ data_fetch_log dropped |

## 段 3 同类风险扫描

### 1. state_builder._evaluate_freshness 老 hard gate vs 新 data_freshness 块冲突?

**不冲突**。

老 `_evaluate_freshness`(state_builder.py:1387):是 pre-flight gate,失败 →
sleep 5 min retry → 仍失败 → 写 `degraded_stages`。这是 retry 行为路径。

新 `data_freshness` 块(state_builder.py:_build_data_freshness_block):只往
state 持久化字段写入信息,不做 retry。

两者数据源不同:老 gate 读 `metric_inserted_at`(由 _query_metric_inserted_at
查每张表的 MAX),新块走共用 freshness 模块(fetch_attempts 优先 + 数据表
MAX fallback)。可以并存,语义互补。

### 2. AI prompt 单测 fixture 兼容?

`tests/` 内对 `MasterAdjudicator._build_user_prompt` 的现有测试不存在传 stale
freshness 的场景;新增的 `test_master_adjudicator_prompt_renders_stale_warning`
+ `test_master_adjudicator_prompt_skips_block_when_no_freshness` 双向覆盖。
其他现存 master prompt 测试只关心 mode/snapshot,不读 [数据新鲜度] 段,
向后兼容。

### 3. selfCheckBadge 前端兼容?

`web/assets/app.js:selfCheckBadgeClass` 读 `systemHealth.overall_status`,
Sprint C 已修该字段为 critical/partial_degraded/all_healthy 三态;
Sprint D 没改返回结构,只把 fetch_attempts 接入聚合,前端无需改。
F 步骤 production curl 显示 overall_status=critical → 顶栏徽章应是「❌ 数据
中断」红色。**用户刷新网页应能直接看到顶栏变红 + 数据源栏 Glassnode 红 +
L2/L4 evidence_layers 红**。

### 4. 显示侧覆盖会让某些层永远 degraded?

是的:在 Glassnode 长期 fail 时,L2 / L4 网页显示永远 degraded。这是设计意
图(网页诚实)。AI 内部不动,所以 master 仍能在 narrative 里说"L2 数据
stale 但其他 L 健康,所以..."给降级建议。

如果未来 Glassnode 永久退役,Sprint E 时 LAYER_SOURCE_DEPS 可去掉
glassnode_onchain 依赖,L2/L4 health 不再被该源拖累。

### 5. 4 源 stale 阈值 vs 已有 _PREFLIGHT_THRESHOLDS_SEC

`state_builder._PREFLIGHT_THRESHOLDS_SEC` 阈值与 freshness.py 阈值不同
(老 gate 按 group "klines / derivatives / onchain / macro" 分,我的
按 source 分)。两套阈值各自 OK:
- _PREFLIGHT 是 retry gate,严格(短阈值,鼓励重试)
- freshness STALE 是显示 + AI prompt 阈值,宽松(长阈值,鼓励容忍)

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| `data_fetch_log` 表 | 生产 DB | Sprint 2.6-J 已废弃,Sprint A fetch_attempts 完整替代,11+ 天无写入,0 处读 |
| `CREATE TABLE data_fetch_log` SQL 块 | src/data/storage/schema.sql | 同上,新 schema 不再有此表 |
| `DataFetchLogDAO` 注释段 | src/data/storage/dao.py | 同上 |
| `_FAILURE_REASON_LABELS` / `_EXPECTED_SOURCES` / `_to_bjt_str` / `_minutes_ago` / `_row_for_source` 私有函数 | src/api/routes/data_sources.py | 全部搬到共用 `src/data/freshness.py`,API 层只剩 BJT 格式化 + dataclass → response model 转换 |

`git grep 'DataFetchLogDAO\|data_fetch_log'` 在 src/ + tests/ 0 命中(除注释)。
`git grep '_FAILURE_REASON_LABELS' src/` 只在共用 freshness 模块 1 处。

## Sprint E backlog

留下来的工作记在 `docs/cc_reports/sprint_e_backlog.md`(同 commit 写入)。

## 用户验证

按你给的脚本 A-G 全部通过:

```bash
# A:网页 API
curl -s http://127.0.0.1:8000/api/data_sources/freshness  # ✅ 4 行,fallback 工作

# D:evidence_layers stale 覆盖
curl -s http://127.0.0.1:8000/api/system/health-detail    # ✅ L2/L4 degraded

# E:data_fetch_log 已删
sqlite3 ... ".schema data_fetch_log"                      # ✅ 无输出
```

明早 BJT 8:35 后 Glassnode quota 重置,主档 1 行 success,
web display "Glassnode 链上 🟢 X 分钟前",L2/L4 自动恢复 healthy。
**FRED 06:00 BJT cron 会写一行 fetch_attempts success → 网页显示「X 小时前」
取代「沿用 X 月 X 日」**(取决于 fetch_attempts vs data_table fallback,
fetch_attempts 优先)。

如果你触发一次 pipeline_run(curl POST /api/system/run-now),strategy_runs
表里的 ai_input_prompt 应能看到 [数据新鲜度] ⚠️ Glassnode 链上... 段;
AI narrative 应明确提到"过期"/"沿用"/"stale"关键词;否则 validator
`validator_stale_disclosure_missing=true` 触发 needs_retry。
