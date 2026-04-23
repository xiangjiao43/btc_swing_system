# Sprint 1.12 — StrategyStateBuilder + Pipeline 协调层

> Scope 收窄版(State Machine 已推迟到 Sprint 1.13):
> 只做 builder + 编排 + 持久化 + 运行脚本。

## Triggers for Human Attention

1. **冷启动阈值源**。`_determine_cold_start` 读 `config/base.yaml → cold_start.warming_up_runs`(现值 42),**没有**新增 `thresholds.yaml → cold_start_min_samples`。用户最初 spec 写的是"cold_start_min_samples(默认 30)",但 base.yaml 早就有 42 的官方来源,为避免双源分裂,我复用了 base.yaml。如果你想把阈值搬到 `thresholds.yaml`,告诉我,我会挪过去并保留向后兼容。

2. **EventRisk 的执行位置**。EventRisk 需要 L1 输出的 `is_volatility_extreme`,但它形式上属于"组合因子"。我把它单独挪到了 **L1 之后**运行(其他 5 个 composite 在 L1 之前),这和建模 §3.8 的原本"6 因子统一在 evidence 前"略有偏差。其他 Layer 继续按 L1 → L2 → L3 → L4 → L5 顺序运行,composite_factors 最终包含全部 6 个 factor。用户的 spec 明确列出了 "composite.event_risk (post-L1)" stage 名,所以是按预期方案实现;只是想显式提醒架构决策点。

3. **`state` schema 是 Sprint 1.12 版**,**不是** `schemas.yaml §4.8` 的完整 BtcStrategyState。当前 state 只含:identity / cold_start / evidence_reports / composite_factors / context_summary / pipeline_meta。缺的是 State Machine 相关字段(state_key / previous_state_key / transition_reason 等),这些会在 Sprint 1.13 加入。下游(review_reports 等)读 state 时要注意。

4. **FallbackLog 只发 level_1**。pipeline 单阶段异常全部登记为 `level_1`;现在没有任何"自动升级到 level_2"的逻辑(base.yaml `fallback.level_1.auto_upgrade_to_l2_consecutive` 需要后续 scheduler 模块实现)。连续失败 5 次的监控告警不在本 sprint 内。

5. **`scripts/run_pipeline_once.py --dry-run` 实跑下 AI stage 报 `ImportError: Using SOCKS proxy, but 'socksio' package is not installed`**(环境 httpx 配 SOCKS 但缺依赖)。这是用户本地代理配置问题,不是 pipeline bug;但 pipeline 完整地降级了(`ai_status=degraded_error`, `persisted=True if not --dry-run`),其他 14 个 stage 全部通过。如果要清掉这个 warning,要么 `pip install httpx[socks]`,要么 `unset` proxy 环境变量。

---

## 本 Sprint 做了什么(3 句话)

1. 新增 `src/pipeline/state_builder.py`(440 行)和 `src/pipeline/__init__.py`,封装 **5 composite → L1 → event_risk → L2 → L3 → L4 → L5 → AI → persist** 的 15-stage 编排,任一 stage 异常都不抛、只记 `FallbackLog(level_1)` + `pipeline_meta.failures`。
2. 扩展 5 个 DAO 方法给 pipeline 用:`BTCKlinesDAO.get_recent_as_df` / `_MetricLongTableDAO.get_distinct_metric_names` / `get_all_metrics` / `EventsCalendarDAO.get_upcoming_within_hours` / `StrategyStateDAO.get_count` / `StrategyStateDAO.get_latest_non_unclear_cycle` / `FallbackLogDAO.log_stage_error`;`CyclePositionFactor` 升级为优先读 pipeline 预注入的 `context['cycle_position_last_stable']`。
3. 新增 `scripts/run_pipeline_once.py`(CLI:`--dry-run`/`--trigger`/`--json`)+ `tests/test_state_builder.py`(15 用例)。

---

## 提交信息

`Sprint 1.12: StrategyStateBuilder with full pipeline orchestration`

---

## 详细报告

### 1. 架构决策

#### 1.1 执行顺序(EventRisk 挪后)

```
Stage  1: cold_start_check            (读 base.yaml + StrategyStateDAO.get_count)
Stage  2: cycle_position_last_stable  (预查 StrategyStateDAO → 注入 context)
Stage  3: composite.truth_trend
Stage  4: composite.band_position
Stage  5: composite.cycle_position    (消费 stage 2 注入值)
Stage  6: composite.crowding
Stage  7: composite.macro_headwind    (输出 correlation_amplified)
Stage  8: layer_1                     (消费前 5 composite)
Stage  9: composite.event_risk        (消费 L1.volatility_regime + MH.correlation_amplified)
Stage 10: layer_2
Stage 11: layer_3
Stage 12: layer_4
Stage 13: layer_5
Stage 14: ai_summary                  (消费 L1-L5 输出)
Stage 15: persist_state               (写 strategy_state_history)
```

EventRisk 的 context 需求是**可解析的**:
- `context['is_volatility_extreme']` ← `L1.volatility_regime == "extreme"`
- `context['btc_nasdaq_correlated']` ← `macro_headwind.correlation_amplified`

如果把 EventRisk 放在 L1 之前,这两个量只能从原始数据里再算一次,属于**重复劳动**。把它挪到 L1 之后使用 L1 的成品,符合"单一数据源"原则。

#### 1.2 降级契约

| 层 | 出错时的 fallback | 是否抛 | `pipeline_meta.failures` | FallbackLog |
|---|---|---|---|---|
| Composite 单个失败 | `_factor_degraded(name)`:`{health_status: error, notes}` | ✘ | ✔ | level_1 |
| Layer 单个失败 | `_layer_error_report`:完整字段的 error report | ✘ | ✔ | level_1 |
| AI caller raise | 默认 dict `{status: degraded_error}` | ✘ | ✔ | level_1 |
| AI 返回 `degraded_*` | state 透传 status,额外记一条 FallbackLog | N/A | ✘ | level_1 |
| `persist_state` 异常 | `persisted=False`,但 state 已返回 | ✘ | ✔ | level_1 |

**不抛异常**这点对下游 scheduler(Sprint 1.14+)很重要:scheduler 只需要看 `BuildResult.persisted / failures` 就能决定下一步。

#### 1.3 `BuildResult` 字段

```python
@dataclass
class BuildResult:
    run_id: str
    run_timestamp_utc: str
    state: dict                    # 可直接 json.dumps
    failures: list[dict]           # [{stage, error_type, error_message}]
    degraded_stages: list[str]     # 去重后的失败/降级 stage 名
    ai_status: str                 # success / degraded_timeout / degraded_error
    persisted: bool
    duration_ms: int
```

### 2. DAO 扩展

| 新增方法 | 用途 |
|---|---|
| `BTCKlinesDAO.get_recent_as_df(conn, tf, limit)` | 取最近 N 根 K 线,返回 `pd.DataFrame` with DatetimeIndex |
| `_MetricLongTableDAO.get_distinct_metric_names(conn)` | 查某长表里出现过的全部 metric 名 |
| `_MetricLongTableDAO.get_all_metrics(conn, lookback_days)` | 返回 `{metric_name → pd.Series}`,lookback 180d |
| `EventsCalendarDAO.get_upcoming_within_hours(conn, hours, now_utc)` | 事件窗口 + 附加 `hours_to` 字段 |
| `StrategyStateDAO.get_count(conn)` | cold_start 判定 |
| `StrategyStateDAO.get_latest_non_unclear_cycle(conn)` | 查 `json_extract($.composite_factors.cycle_position.band)` 最近非 unclear 的 band |
| `FallbackLogDAO.log_stage_error(conn, ts, stage, error, fallback_applied)` | pipeline stage 异常的便捷封装 |

`get_latest_non_unclear_cycle` 的 SQL 用 `json_extract` 直接在 SQLite 侧过滤,**不读 state_json 再解析**,避免扫全表:

```sql
SELECT json_extract(state_json, '$.composite_factors.cycle_position.band') AS band
FROM strategy_state_history
WHERE json_extract(state_json, '$.composite_factors.cycle_position.band') IS NOT NULL
  AND json_extract(state_json, '$.composite_factors.cycle_position.band') != 'unclear'
ORDER BY run_timestamp_utc DESC LIMIT 1
```

SQLite 3.38+ 原生支持 `json_extract`;遇到不支持的老版本会 `OperationalError`,方法兜底返回 `None`。

### 3. State 结构(Sprint 1.12 版)

```json
{
  "run_id": "uuid",
  "reference_timestamp_utc": "ISO8601",
  "generated_at_utc": "ISO8601",
  "run_trigger": "scheduled | manual | event_*",
  "rules_version": "v1.2.0",
  "ai_model_actual": "mock-model | claude-sonnet-4-5-... | null",

  "cold_start": {
    "warming_up": bool,
    "runs_completed": int,
    "threshold": 42,
    "days_elapsed": int | null,
    "reason": "..."
  },

  "evidence_reports": {
    "layer_1": {...EvidenceReport...},
    "layer_2": {...},
    "layer_3": {...},
    "layer_4": {...},
    "layer_5": {...}
  },

  "composite_factors": {
    "truth_trend":    {...},
    "band_position":  {...},
    "cycle_position": {...},
    "crowding":       {...},
    "macro_headwind": {...},
    "event_risk":     {...}
  },

  "context_summary": {
    "summary_text":  "3 段中文 | null",
    "status":        "success | degraded_timeout | degraded_error",
    "tokens_in":     int,
    "tokens_out":    int,
    "latency_ms":    int,
    "error":         "... | null"
  },

  "pipeline_meta": {
    "failures":         [{stage, error_type, error_message}, ...],
    "degraded_stages":  [str, ...],
    "stages_total":     15,
    "stages_succeeded": int
  }
}
```

**未包含的字段**(Sprint 1.13 State Machine 会补):
- `state_key / previous_state_key / transition_reason / transition_rule_triggered`
- `state_duration_seconds / state_entered_at_utc`
- `kpi_snapshot / observation_category`

### 4. 测试覆盖(15 cases,全 PASS)

| # | Class / Method | 用意 |
|---|---|---|
| 1 | `TestHappyPath` | 所有 stage 成功 + state 结构 + 持久化 |
| 2 | `TestColdStart::warming_up` | DB 空 → warming_up=True + L1 health_status 降级 |
| 3 | `TestColdStart::passed` | 42 条历史 state → warming_up=False |
| 4 | `TestLastStableInjected` | 上次 `cycle_position.band=late_bear` 正确注入 factor |
| 5 | `TestStageFailure` | `TruthTrendFactor.compute` 抛 → failures + FallbackLog + 其他 stage 继续 |
| 6 | `TestAIDegradedLogged` | AI 返回 degraded → context_summary 透传 + FallbackLog |
| 7 | `TestAICallerRaises` | AI caller 抛 → default dict + ai_summary degraded |
| 8 | `TestDryRun` | `persist=False` → 不写 strategy_state_history |
| 9 | `TestPersistenceRoundTrip` | state_json 反解析等价 |
| 10 | `TestEventRiskAfterL1` | Fake L1 → volatility_regime=extreme → vol bonus 应用 |
| 11 | `TestRunWithoutConn` | `StrategyStateBuilder(conn=None).run()` 抛 ValueError |
| 12 | `TestBuildWithoutDB` | `build(ctx, persist=False)` 空 ctx 也能跑(走 insufficient) |
| 13 | `TestFallbackLogDetailsShape` | `log_stage_error` 写入 details 可反解析 |
| 14 | `TestLatestNonUnclearQuery::empty` | 空表 → None |
| 15 | `TestLatestNonUnclearQuery::skips_unclear` | unclear 被跳过,返回上一条 late_bear |

**全测试套件**:180 passed,0 failed,0.77s。

### 5. 运行脚本

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV
# 持久化一次(完整 pipeline):
uv run python scripts/run_pipeline_once.py
# 不写库、只看结构:
uv run python scripts/run_pipeline_once.py --dry-run
# 打印完整 state JSON:
uv run python scripts/run_pipeline_once.py --dry-run --json
# 覆盖触发源:
uv run python scripts/run_pipeline_once.py --trigger event_fomc_pre
```

退出码:
- `0`:完全成功(persisted=True,failures=[],degraded_stages=[])
- `1`:有 fallback / degraded,但 state 已写库
- `2`:未写库(persist_state 阶段异常 / dry-run)

### 6. 未完成 / 留给后续 Sprint

- **Sprint 1.13**:State Machine(14 状态、转换规则、kpi_snapshot 累积)
- **Sprint 1.14**:Review Report 生成(lifecycle 结束触发)
- **Sprint 1.15+**:scheduler(调 `run()` 按 `base.yaml → daily_runs` 频率)+ 监控 /告警

### 7. 非 OPS 环境要验证

- [x] 所有 pytest 通过(180/180)
- [x] `run_pipeline_once.py --dry-run` 能跑到尾(尽管 AI 因本地 SOCKS proxy 失败,也正常 degrade)
- [ ] 生产跑一次 `run_pipeline_once.py`(不加 --dry-run)验证:
  - `strategy_state_history` 新增 1 行
  - `fallback_log` 只在确有阶段降级时写
  - `run_metadata` 有 started → completed 记录
  - `summary_text` 非空(AI 侧本地 proxy 问题修复后)
