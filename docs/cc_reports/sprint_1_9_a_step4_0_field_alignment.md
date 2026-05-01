# Sprint 1.9-A Step 4.0 — 三方字段对齐调研

**日期:** 2026-05-01
**范围:** 调研 only,不动代码
**目的:** 对比 (a) 6 prompt 期望字段 / (b) ContextBuilder 已准备 / (c) 5 agent _build_user_prompt 当前传递,标出 gap

---

## 1. 三方对齐表

每行 = 1 个字段(组),3 列 + 状态标。

### L1 Regime

| 字段 | prompt v5 期望 | ContextBuilder 已准备 | agent 当前传递 | 状态 |
|---|---|---|---|---|
| chart_b64 | ✅ chart_l1_180d.png | (orchestrator 调 render_l1_chart) | ✅ orchestrator 注入 | ✅ |
| klines_1d_30d_close | ✅ array of 30 closes | ❌ 仅有 klines_1d full DataFrame | ❌(传 klines_1d_summary 简略 dict) | ❌ |
| computed_indicators | ✅ dict(adx/atr/ema/swing/price_position/current_close) | ✅ 全部已准备(Sprint 1.9-A.2,缺 price_position_in_90d_range) | ❌(传 indicators 旧名) | ⚠️ 部分缺 |
| previous_l1 | ✅ | ✅ 占位 None(1.9-A.4 解析 full_state_json 填) | ✅ 但来源是 None | ⚠️ |

### L2 Direction

| 字段 | prompt v2 期望 | ContextBuilder 已准备 | agent 当前传递 | 状态 |
|---|---|---|---|---|
| chart_b64 | ✅ chart_l2.png | (orchestrator 调 render_l2_chart) | ✅ orchestrator 注入 | ✅ |
| klines_1d_30d_close | ✅ | ❌ 同 L1 | ❌ | ❌ |
| computed_indicators | ✅ dict(EMA + swing + 4h EMA + LTH/STH + funding + exchange_flow + current_close) | ✅ 全部已准备 | ❌(传 derivatives_snapshot/onchain_structure_snapshot/price_structure 旧名) | ⚠️ |
| l1_output | ✅ | (orchestrator 注入 prior agent output) | ❌(传 previous_l1_output 错名) | ⚠️ |
| rule_cycle_position | ✅ {label, confidence, voting_details} | ❌ ContextBuilder 没调 CyclePositionFactor | ❌ | ❌ |
| previous_l2 | ✅ | ✅ 占位 None | ❌ | ⚠️ |

### L3 Opportunity

| 字段 | prompt v3 期望 | ContextBuilder 已准备 | agent 当前传递 | 状态 |
|---|---|---|---|---|
| l1_output | ✅ | (orchestrator 注入) | ✅ 但传 previous_l1 错名 | ⚠️ |
| l2_output | ✅ | (orchestrator 注入) | ✅ 但传 previous_l2 错名 | ⚠️ |
| risk_preview | ✅ {funding_z, oi_z, events_count_72h} 3 字段 | ✅ build_risk_preview 实现 | ❌(传 cycle_position_rule/funding_pressure/asopr/cdd 旧名,完全没传 risk_preview) | ⚠️ |
| anti_pattern_signals | ✅ 5 bool dict | ❌ ContextBuilder 没调 anti_pattern_signals.py | ❌ | ❌ |
| current_state | ✅ 14 档枚举 | ✅ 从 strategy_runs 读 | ❌ | ⚠️ |
| previous_l3 | ✅ | ✅ 占位 None | ❌ | ⚠️ |

### L4 Risk

| 字段 | prompt v2 期望 | ContextBuilder 已准备 | agent 当前传递 | 状态 |
|---|---|---|---|---|
| chart_b64 | ✅ chart_l4.png | (orchestrator 调 render_l4_chart) | ✅ orchestrator 注入 | ✅ |
| computed_indicators | ✅ dict(current_close + atr + ema + swing + funding + OI + exchange_flow + LTH + drawdown) | ✅ 全部已准备 | ❌(传 crowding_signals/current_price 旧名) | ⚠️ |
| l1_output | ✅ | (orchestrator 注入) | ✅ 但传 previous_l1 错名 | ⚠️ |
| l2_output | ✅ | (orchestrator 注入) | ✅ 但传 previous_l2 错名 | ⚠️ |
| l3_output | ✅ | (orchestrator 注入) | ✅ 但传 previous_l3 错名 | ⚠️ |
| current_state | ✅ | ✅ | ❌ | ⚠️ |
| previous_l4 | ✅ | ✅ 占位 None | ❌ | ⚠️ |

### L5 Macro

| 字段 | prompt v3 期望 | ContextBuilder 已准备 | agent 当前传递 | 状态 |
|---|---|---|---|---|
| computed_macro_indicators | ✅ dict(dxy/us10y/us2y/vix/nasdaq/m2/fed_balance/btc_dominance/etf_flow + 衍生指标) | ✅ 已准备(无 sp500,1.8.1 已删) | ❌(传 macro_factors 旧名) | ⚠️ |
| events_calendar_72h | ✅ list of 事件 | ✅ EventsCalendarDAO 取 72h | ❌(传 events_72h 错名) | ⚠️ |
| extreme_event_flags | ✅ 5 bool dict | ❌ ContextBuilder 没调 detect_extreme_events | ❌ | ❌ |
| previous_l5 | ✅ | ✅ 占位 None | ❌ | ⚠️ |

### Master Adjudicator

| 字段 | prompt v2 期望 | ContextBuilder 已准备 | agent 当前传递 | 状态 |
|---|---|---|---|---|
| l1_output ~ l5_output | ✅ 各层完整输出 | (orchestrator 注入 prior outputs) | ✅ | ✅ |
| current_state | ✅ 14 档 | ✅ | ❌(传 state_machine_current 错名) | ⚠️ |
| previous_strategy_run | ✅ {state, last_state_change_utc, ...} | ✅ StrategyStateDAO.get_latest_state | ❌(没传) | ⚠️ |
| _system_provided | ✅ {crowding_multiplier, event_multiplier, current_close} | (orchestrator._compute_* 算) | ❌(没 dump 到 prompt) | ⚠️ |
| hard_invalidation_levels (master 已可从 l4_output 拿) | (来自 l4_output) | (来自 l4_output) | ✅ 但 master 已可从 l4_output 拿,冗余 | ⚠️(冗余) |

---

## 2. ❌ 项汇总 — ContextBuilder 没准备 + prompt 期望

| # | 字段 | 期望 prompt | 实施路径 | 工作量 | 处置 |
|---|---|---|---|---|---|
| ❌1 | `klines_1d_30d_close` (last 30 closes array) | L1 + L2 | `klines_1d['close'].iloc[-30:].tolist()` | 1 行 | **补到 Step 4** |
| ❌2 | `price_position_in_90d_range`(0.0-1.0) | L1 | `(close - 90d_low) / (90d_high - 90d_low)` | 5 行 helper | **补到 Step 4** |
| ❌3 | `rule_cycle_position`({label, confidence, voting_details}) | L2 | 调 `CyclePositionFactor().compute(context)` | 5 行 wrapper | **补到 Step 4** |
| ❌4 | `anti_pattern_signals`(5 bool) | L3 | ContextBuilder 不能算(需 L1+L2 输出);**orchestrator 在 L3 之前调 `compute_anti_pattern_signals(l1, l2, ...)`** | orchestrator 改 5 行 | **补到 Step 4(在 orchestrator)** |
| ❌5 | `extreme_event_flags`(5 bool) | L5 | `detect_extreme_events(conn)` 已在 1.9-A.3,**ContextBuilder 调一次塞入 context** | 3 行 | **补到 Step 4** |

**总 ❌ 项:5 个,全部能在 Step 4 内补完,无需新数据源。**

⚠️ 项(命名漂移)= 几乎所有 5 agent 的 _build_user_prompt 字段名,Step 4 全部重命名 + 重对齐。

---

## 3. Step 4 实施清单(基于本调研)

按优先级:

A. **ContextBuilder 补 5 个 helper / wrapper**(`src/ai/context_builder.py`):
   1. `klines_1d_30d_close` 派生(在 build_full_context 末尾)
   2. `price_position_in_90d_range` 派生
   3. `rule_cycle_position` 调 CyclePositionFactor wrapper
   4. `extreme_event_flags` 调 detect_extreme_events wrapper

B. **Orchestrator 补 1 个 helper 调用**(`src/ai/orchestrator.py`):
   5. `_run_l3` 之前调 `compute_anti_pattern_signals(l1_out, l2_out, current_close, extreme_event_flags)` 注入 context

C. **5 agent _build_user_prompt 重对齐**(L1/L2/L3/L4/L5 + master):
   - 每个 agent 改 ~10 行,字段名对齐 prompt 期望(详见 §1 表的 ❌/⚠️)

D. **previous_l1-l5 解析**(用户 b 方案):
   - `src/ai/context_builder.py` 加 `parse_previous_layer_outputs(strategy_run_dict) -> dict[str, dict]`
   - 从 `strategy_runs.full_state_json` JSON 解析,取 `layers.l1` ~ `layers.l5`
   - `build_full_context` 调用,填入 previous_l1-l5(替代当前 None)

E. **测试**:
   - 每个 agent 加 1 个 _build_user_prompt 输出字段断言测试(5 个)
   - parse_previous_layer_outputs 加 4 个测试(正常解析 / 空 JSON / 缺 layers / 旧 schema)
   - ContextBuilder 集成测试加 1 个 — 端到端含 anti_pattern_signals + extreme_event_flags + previous_l*-l5

---

## 4. 总览

- ✅ 已对齐:4 项(chart_b64 + master 5 层输出注入)
- ⚠️ 命名漂移(改 agent 文件即可):约 25 处字段
- ❌ ContextBuilder/orchestrator 缺准备(需补 helper 调用):**5 项**(全部小改动,Step 4 内可完成)

**结论**:Step 4 可执行,无 blocker;无需补新数据源,无需问用户。
