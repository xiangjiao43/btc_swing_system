# Sprint 1.9-A Step 0 调研 — orchestrator context 构造完整度

**报告日期:** 2026-05-01
**Sprint 范围:** 调研 only — 不修代码,核实 `AIOrchestrator.run_full_a(context)` 期望的 context 字段 vs `state_builder._assemble_context` 实际提供的字段
**前置:** Sprint 1.8.1.2(commit d39cd8f)

---

## 1. 三处源对比

### 1.1 state_builder._assemble_context 实际返回(`src/pipeline/state_builder.py:751-801`)

```python
return {
    "reference_timestamp_utc": now_utc or _utc_now_iso(),
    "klines_1h": klines_1h,
    "klines_4h": klines_4h,
    "klines_1d": klines_1d,
    "klines_1w": klines_1w,
    "derivatives": derivatives,            # 注:不是 derivatives_snapshot
    "onchain": onchain,                    # 注:不是 onchain_structure
    "macro": macro,                        # 注:不是 macro_indicators
    "events_upcoming_48h": events,         # 注:48h 不是 72h
    "next_events_by_type": next_events_by_type,
    "single_factors": _build_single_factors(onchain),
    "metric_inserted_at": metric_inserted_at,
}
```

**共 10 个 key**(其中 4 个有命名差异)。

### 1.2 Orchestrator 各 agent 从 context 读取的字段(`src/ai/orchestrator.py:205-432`)

| Agent | context 字段 |
|---|---|
| L1 | `klines_1d`, `klines_4h`, `ema_20_1d`, `ema_50_1d`, `ema_200_1d`, `adx_14_1d`, `atr_180d_pct_1d`, `swing_points_1d`, `computed_indicators`, `previous_l1` |
| L2 | `klines_1d`, `klines_4h`, `ema_20_1d`, `ema_50_1d`, `ema_20_4h`, `ema_50_4h`, `swing_points_1d`, `key_levels_rule_estimate`, `derivatives_snapshot`, `onchain_structure`, `computed_indicators`, `rule_cycle_position`, `previous_l2` |
| L3 | `computed_indicators` (含 asopr_value/cdd_value/funding_pressure), `rule_cycle_position`, `risk_preview`, `anti_pattern_signals`, `current_state`, `previous_l3` |
| L4 | `klines_1d`, `ema_50_1d`, `ema_200_1d`, `atr_14_1d`, `funding_rate_series`, `open_interest_series`, `exchange_net_flow_series`, `current_close`, `crowding_signals`, `account_state`, `previous_l4` |
| L5 | `macro_indicators`, `events_calendar_72h`, `extreme_event_flags`, `btc_macro_corr_60d`, `previous_l5` |
| master | `current_state`, `previous_strategy_run`, `current_close`, `allowed_transitions`, `account_state`(L1-L5 输出来自上游 stage,不算 context) |

---

## 2. Gap 表(每行 = agent + 缺的字段列表)

| Agent | state_builder 已有 | 缺(state_builder 需新增) | 命名差异(易修) |
|---|---|---|---|
| **L1** | `klines_1d` ✅, `klines_4h` ✅ | `computed_indicators`(汇总 EMA/ADX/ATR/Swing 数值)、`ema_20_1d`/`ema_50_1d`/`ema_200_1d`、`adx_14_1d`、`atr_180d_pct_1d`、`swing_points_1d`、`previous_l1` | — |
| **L2** | `klines_1d` ✅, `klines_4h` ✅ | `ema_20_1d`/`ema_50_1d`/`ema_20_4h`/`ema_50_4h`、`swing_points_1d`、`key_levels_rule_estimate`、`computed_indicators`、`rule_cycle_position`、`previous_l2` | `derivatives` → `derivatives_snapshot`;`onchain` → `onchain_structure` |
| **L3** | — | `computed_indicators`(含 asopr_value/cdd_value/funding_pressure)、`rule_cycle_position`、`risk_preview`、`anti_pattern_signals`、`current_state`、`previous_l3` | — |
| **L4** | `klines_1d` ✅ | `ema_50_1d`/`ema_200_1d`、`atr_14_1d`、`funding_rate_series`、`open_interest_series`、`exchange_net_flow_series`、`current_close`、`crowding_signals`、`account_state`、`previous_l4` | — |
| **L5** | — | `extreme_event_flags`、`btc_macro_corr_60d`、`previous_l5` | `macro` → `macro_indicators`;`events_upcoming_48h`(48h)→ `events_calendar_72h`(72h) |
| **master** | — | `current_state`、`previous_strategy_run`、`current_close`、`allowed_transitions`、`account_state` | — |

---

## 3. 缺口性质分类(给 1.9-A Step 1 的实施分类参考)

### 3.1 类 X — 命名差异(只需重命名 / alias,改 1-2 行)

| 旧名 | 新名 | 影响 agent |
|---|---|---|
| `derivatives` | `derivatives_snapshot` | L2 |
| `onchain` | `onchain_structure` | L2 |
| `macro` | `macro_indicators` | L5 |
| `events_upcoming_48h` (48h) | `events_calendar_72h` (72h) | L5 |

### 3.2 类 Y — 已有原料但需计算(需新 helper)

| 待算字段 | 来源 | 用法 |
|---|---|---|
| `computed_indicators`(EMA-20/50/200/ADX-14/ATR-14/ATR-180d% 等数值) | klines_1d / klines_4h | L1+L2+L3+L4 都用 |
| `ema_20_1d` / `ema_50_1d` / `ema_200_1d` / `adx_14_1d` / `atr_14_1d` / `atr_180d_pct_1d`(独立 series) | klines_1d | chart_renderer 输入 |
| `ema_20_4h` / `ema_50_4h`(独立 series) | klines_4h | chart_renderer 输入 |
| `swing_points_1d` | klines_1d(swing 算法) | L1+L2 chart |
| `key_levels_rule_estimate`(nearest/major support/resistance) | klines_1d + EMA + swing | L2 chart 横线 |
| `funding_rate_series` / `open_interest_series` / `exchange_net_flow_series` | derivatives + onchain pivot | L4 chart 副图 |
| `current_close` | klines_1d 最后一根 | master + L4 |
| `btc_macro_corr_60d` | klines_1d × macro 计算 | L5 |
| `rule_cycle_position` | CyclePositionFactor.compute() | L2+L3 |

### 3.3 类 Z — 需要新数据源 / 状态机层(需 dao + 业务逻辑)

| 字段 | 来源 |
|---|---|
| `previous_l1` / `previous_l2` / `previous_l3` / `previous_l4` / `previous_l5` / `previous_strategy_run` | 新 DAO:`AIOutputsDAO.get_latest_layer_output(layer)` 或现有 StrategyStateDAO 扩展 |
| `current_state`(14 档状态机) | 状态机模块(目前 StrategyStateDAO 已写 `action_state` 字段,可借) |
| `allowed_transitions`(从 current_state 算合法迁移集) | 状态机迁移规则模块(建模 §5.1)|
| `account_state` | 账户跟踪模块(建模 §7,可能未实现) |
| `risk_preview`(L3 用) | L4 输出预跑或 L3 内部估算 |
| `anti_pattern_signals`(L3 用) | 反模式检测器(部分逻辑在 evidence/_anti_patterns.py) |
| `crowding_signals`(L4 用) | derivatives funding/OI z-score 等汇总 |
| `extreme_event_flags`(L5 用) | 5 个 bool flag(地缘/银行/监管/闪崩/脱锚)— 数据源待定 |

---

## 4. 总览

- **类 X(命名修)**:4 项,**1.9-A Step 1 内可直接做完**
- **类 Y(计算 helper)**:9 项,**1.9-A Step 2 实施(≈ 中等工作量)**
- **类 Z(新数据 / 状态机)**:8 项,**1.9-A Step 3-4 实施(需要新 DAO + 状态机)**

**结论**:`AIOrchestrator.run_full_a(context)` 当前**绝对不能**直接被
state_builder 调用 — 几乎所有字段都缺或命名错。Sprint 1.9-A 需要
实质性 context 构造层重写。

`run_pipeline_once.py` → 当前 state_builder 只能跑出 v1.2 stub fallback
(degraded,`_RetiredV12Module.compute()` 抛 NotImplementedError),
不能驱动 6 AI 中任何一个真跑。

---

## 5. Sprint 1.9-A Step 1+ 建议

1. **Step 1**:类 X 命名修(4 项,~30 行 diff)
2. **Step 2**:类 Y 计算 helper(9 项,~300 行新代码 + 单测)
3. **Step 3**:类 Z previous_l*(6 项,新 DAO + 单测)
4. **Step 4**:类 Z 状态机 / account_state / risk_preview / anti_pattern / crowding / extreme_event(8 项,这些是建模 §5/§6/§7 大头)

`state_builder.run()` 主体重写到 1.9-B 再做(切到 AIOrchestrator);1.9-A
只补 context 构造能力。
