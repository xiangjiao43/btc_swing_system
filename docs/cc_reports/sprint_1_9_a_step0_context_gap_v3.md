# Sprint 1.9-A Step 0 v3 — 严格 v1.3 哲学的 context gap

**报告日期:** 2026-05-01
**版本:** v3(替代 v2;v2 错列了 `key_levels_rule_estimate` / `crowding_signals` 为待补)
**Sprint 范围:** 调研 only,不修代码

---

## 0. v1.3 铁律(本调研依据)

1. 给 AI **图 + 客观数值**,不给规则结论标签
2. 系统精确计算(EMA/ADX/ATR/Swing/相关系数),不让 AI 算
3. AI 综合判断,不依赖单一阈值
4. fewshot 给 input 数据 + 图描述 → JSON,不给"参考信号"

---

## 1. 字段分类原则

| 类型 | 含义 | 示例 |
|---|---|---|
| **A** | 客观数值/结构识别(铁律 2) | EMA/ADX/ATR 数值、swing 数组、60d corr、funding z-score |
| **B** | v1.3 §3.3 显式定义系统给 AI 的预览/触发信号 | anti_pattern_signals(§3.3.3)、extreme_event_flags(§3.3.5) |
| **C** | 状态机 / 历史读取(规则范围,DAO 调用) | current_state / previous_l*/previous_strategy_run |
| **D** | orchestrator 内部规则映射(§3.1 第 5 条) | crowding_multiplier / event_multiplier |

---

## 2. 字段 gap 表(每行 = 字段或字段组,4 列)

| # | 字段 | 类型 | 实施路径(已有 / helper / DAO / orch 内部) | 工作量 |
|---|---|---|---|---|
| 1 | `klines_1d`(全 DataFrame,180d 用于 chart + summary) | A | 已有(state_builder 提供) | 0 |
| 2 | `klines_4h`(全 DataFrame,30d 用于 L2 chart) | A | 已有(state_builder 提供) | 0 |
| 3 | EMA-20/50/200(1d series + current,L1+L2+L4 chart) | A | 新 helper `compute_emas(klines_1d)` in `src/ai/context_builder.py` | ~30 行 |
| 4 | EMA-20/50(4h series + current,L2 chart) | A | 同上,扩展 `compute_emas(klines_4h)` | ~10 行 |
| 5 | ADX-14(1d series + current + 5d_avg,L1) | A | 新 helper `compute_adx_14(klines_1d)` | ~30 行 |
| 6 | ATR-14(1d series + current,L4 chart) | A | 新 helper `compute_atr_14(klines_1d)` | ~20 行 |
| 7 | ATR 180d 分位序列(L1 chart 副图) | A | 新 helper `compute_atr_180d_percentile(klines_1d)` | ~20 行 |
| 8 | Swing 5/3 高低点数组(L1+L2,既给 chart 又给数值) | A | 新 helper `detect_swing_points(klines_1d, lookback=180)`(zigzag 算法) | ~80 行 |
| 9 | EMA-20 30d slope(L1) | A | 简单 numpy 计算,放 `compute_emas` 旁 | ~5 行 |
| 10 | LTH/STH supply 90d/30d pct change + realized price(L2+L4) | A | 新 helper `compute_lth_sth_changes(onchain_dict)` | ~40 行 |
| 11 | exchange_net_flow 30d(sum + max_outflow + series for L4 chart) | A | 新 helper `compute_exchange_flow_30d(onchain_dict)` | ~30 行 |
| 12 | funding_rate 现值 + 90d z-score + 30d max + series for L4 chart | A | 新 helper `compute_funding_features(derivatives_dict)` | ~40 行 |
| 13 | open_interest 现值 + 90d z-score + series for L4 chart | A | 同 #12,合并 | ~20 行 |
| 14 | max_drawdown 60d % (L4) | A | 新 helper `compute_max_drawdown_60d(klines_1d)` | ~10 行 |
| 15 | `current_close`(master + L4) | A | klines_1d.iloc[-1].close,放 helper | 5 行 |
| 16 | `computed_indicators`(L1+L2+L3+L4 共用 dict,合成 #3-#15 + 部分 #10-#13) | A | 新 `build_computed_indicators(...)` 聚合上面 helpers | ~30 行 |
| 17 | macro 现值 + 30d/90d 变化 + 历史窗口(dxy/us10y/us2y/vix/nasdaq/m2/fed_balance/btc_dominance/etf_flow_30d/etf_flow_7d/yield curve) | A | 新 helper `compute_macro_features(macro_dict)` | ~80 行 |
| 18 | `computed_macro_indicators`(L5 用 dict,封装 #17 字段) | A | 同 #17 输出 | 0 |
| 19 | BTC-NASDAQ 60d 相关系数(L5 可选) | A | 新 helper `compute_btc_macro_corr_60d(klines_1d, macro_dict)` | ~20 行 |
| 20 | `events_calendar_72h`(L5 必)+ `events_count_72h`(L3 可) | A/B | EventsCalendarDAO.get_upcoming_within_hours(72) — 已有 (state_builder 现取 48h,扩 72h) | 5 行 |
| 21 | `risk_preview`(L3,**仅 3 字段**:funding_rate_z_score, open_interest_z_score, events_count_72h) | A | 派生 dict,从 #12+#13+#20 摘字段 | ~10 行 |
| 22 | `extreme_event_flags`(L5,5 类 bool:geopolitical/banking/regulatory/flash_crash/stablecoin_depeg) | B | 新 evidence module `src/ai/extreme_event_detector.py`(实现 5 个独立检测器);可先静态 false hardcode + 1.10 接数据源 | ~150 行 |
| 23 | `anti_pattern_signals`(L3,5 类 bool,§3.3.3) | B | 复用部分 `src/evidence/_anti_patterns.py` 逻辑(那几个函数已实现 4 类),补第 5 类 + 包成 dict | ~80 行 |
| 24 | `rule_cycle_position`(L2,9 档 + confidence) | B | 已有 `CyclePositionFactor().compute(context)` | 5 行 |
| 25 | `current_state`(14 档) | C | DAO:`StrategyStateDAO.get_latest()['action_state']`(已有) | 5 行 |
| 26 | `previous_l1` / `previous_l2` / `previous_l3` / `previous_l4` / `previous_l5` | C | **新 DAO**:`AIOutputsDAO`(新表 `ai_layer_outputs`,字段:run_id / layer_name / output_json / created_at);或挂在 strategy_runs.full_state_json 子结构里 | ~120 行(含 schema 迁移 + DAO 单测) |
| 27 | `previous_strategy_run`(master) | C | DAO:`StrategyStateDAO.get_latest()`(已有) | 5 行 |
| 28 | `_system_provided.crowding_multiplier` | D | 已有 `AIOrchestrator._compute_crowding_multiplier(l4_out)` | 0 |
| 29 | `_system_provided.event_multiplier` | D | 已有 `AIOrchestrator._compute_event_multiplier(events_72h)` | 0 |
| 30 | `_system_provided.current_close` | D | 同 #15 引用 | 0 |

---

## 3. PROMPT 偏离 v1.3(必须改 prompt,不补 helper)

### 3.1 L3 prompt v2 — `risk_preview` 含 2 个规则结论标签

文件:`src/ai/agents/prompts/l3_opportunity.txt`

| 行号 | 字段 | 偏离原因 | 处置 |
|---|---|---|---|
| 40 | `crowding_level: "moderate"` | L4 AI 综合判断输出,L3 跑在 L4 之前拿不到;给"moderate"是规则结论标签,违反铁律 1 | **删字段**(L3 prompt v3 改) |
| 44 | `event_risk_active: false` | 同上,bool 标签是规则结论 | **删字段** |
| 43 | `macro_warning_count: 0` | "warning" 来自 L5,L3 跑在 L5 之前;且 macro warning 是 L5 综合判断结果 | **删字段,改用客观 events_count_72h** |
| 41 | `funding_rate_z_score: 0.85` | 客观 z-score,合规 | 保留 |
| 42 | `open_interest_z_score: 0.42` | 同上 | 保留 |

修订建议(L3 prompt v3):
```yaml
"risk_preview": {
  "funding_rate_z_score_90d": 0.85,
  "open_interest_z_score_90d": 0.42,
  "events_count_72h": 1                    # 替代 macro_warning_count,纯客观计数
}
```

### 3.2 其他 prompt 复审结果

- L1 / L2 / L4 / L5 / master prompt v3 通读,**未发现规则结论标签字段**。
  全部是客观数值 + 已被 v1.3 §3.3 显式定义的 B 类字段(extreme_event_flags / anti_pattern_signals / rule_cycle_position)。
- master prompt §7 提到 `_system_provided.crowding_multiplier` / `event_multiplier`,这些是 D 类(orchestrator 规则映射,§3.1 第 5 条),合规。

---

## 4. Agent 代码 drift(独立于 context gap,需一并修)

每个 `_build_user_prompt` 用的 context key 名都是 1.8 骨架阶段的旧名,
**与 v5 prompt 期望的输入字段名不一致**。1.9-A 实施时必须同步重构。

| Agent | _build_user_prompt 当前 key | v5 prompt 期望 key |
|---|---|---|
| L1 | `klines_1d_summary` / `klines_4h_summary` / `indicators` | `klines_1d_30d_close` / `computed_indicators` |
| L2 | `derivatives_snapshot` / `onchain_structure_snapshot` / `price_structure` | `computed_indicators` / `l1_output` / `rule_cycle_position` |
| L3 | `asopr` / `cdd` / `cycle_position_rule` / `funding_pressure` | `l1_output` / `l2_output` / `risk_preview` / `anti_pattern_signals` / `current_state` |
| L4 | `crowding_signals` / `current_price` | `computed_indicators` / `l1_output` / `l2_output` / `l3_output` / `current_state` |
| L5 | `macro_factors` / `events_72h` | `computed_macro_indicators` / `events_calendar_72h` / `extreme_event_flags` |
| master | 已 OK(state_machine_current / allowed_transitions / hard_invalidation_levels 等) | 但还需 dump `_system_provided` 子 dict |

修复:1.9-A 在 Step 1 一并重构 6 个 agent 的 `_build_user_prompt` 与 v5
prompt 字段名对齐(纯重命名 + 删过时字段,无算法变化)。

---

## 5. 总览

- **类型 A(客观数值/计算 helper)**:18 项字段(#1-#19),**约 600 行新代码**
- **类型 B(预览/触发 — v1.3 §3.3 显式定义)**:3 项(events / extreme_event_flags / anti_pattern_signals)+ rule_cycle_position 复用,**约 240 行**
- **类型 C(状态机 / 历史 DAO)**:3 项(current_state / previous_strategy_run / previous_l*),**约 130 行(含 schema)**
- **类型 D(orchestrator 内部映射)**:3 项,**0 行(已实现)**

**Prompt 偏离需改**:
- L3 prompt risk_preview 块 3 字段:删 crowding_level / event_risk_active /
  macro_warning_count;新增 events_count_72h

**Agent 代码 drift 需修**:
- L1 / L2 / L3 / L4 / L5 五个 `_build_user_prompt` 需重命名 + 重对齐字段
  (~200 行重构 + 单测覆盖)

---

## 6. Sprint 1.9-A 实施建议(依赖顺序)

1. **Step 1 — Prompt 修偏离 + Agent code drift 修**
   - L3 prompt v3:risk_preview 3 字段改写
   - 6 个 _build_user_prompt 重对齐 v5 prompt 字段名
   - tests/ai/ 同步更新

2. **Step 2 — 类 A 计算 helpers**(无业务依赖,可并行写单测)
   - 新模块 `src/ai/context_builder.py`
   - ~600 行 helper + 单测覆盖
   - 不接入 state_builder

3. **Step 3 — 类 B 预览/触发**
   - 复用 `_anti_patterns.py` → 包成 `anti_pattern_signals` 函数
   - 新 `extreme_event_detector.py`(5 类 bool;先 hardcode false + 1.10 接数据源)

4. **Step 4 — 类 C DAO + schema 迁移**
   - 新表 `ai_layer_outputs`(run_id / layer_name / output_json / created_at)
   - 新 `AIOutputsDAO`
   - schema migration + 单测

5. **Step 5 — 集成 state_builder.run() → AIOrchestrator**(1.9-B 范围)
   - state_builder 整体重写 / 替换为 orchestrator 调用
   - 重启 cron(scheduler.yaml `pipeline_run` enabled: true)
   - 清理 _RetiredV12Module stub

总工作量估算:**1.9-A ≈ 1100 行新代码 + 200 行重构 + 大量单测**(分 4 个 sub-sprint 完成)。
