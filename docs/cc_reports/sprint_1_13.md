# Sprint 1.13 — State Machine(系统状态分类器)

## Triggers for Human Attention

1. **【重要】发现并保留了原 `config/state_machine.yaml`**。它实现的是**建模 §5 的交易生命周期 FSM**(FLAT / LONG_PLANNED / LONG_OPEN / LONG_HOLD / LONG_TRIM / LONG_EXIT / SHORT_* / FLIP_WATCH / PROTECTION / POST_PROTECTION_REASSESS,14 状态),语义和本 Sprint 要实现的"系统运行状态分类器"(cold_start / chaos_pause / active_long_execution / ...)**是两个不同的概念**——前者关心"这笔交易走到第几步",后者关心"系统此刻该处于什么运行状态"。我**把原文件改名为 `config/lifecycle_fsm.yaml` 保留**,在 `config/state_machine.yaml` 新建了本 Sprint 要求的 14 状态分类器。后续 Sprint 1.15 要做 StrategyModule(交易执行)时会用到 lifecycle_fsm.yaml。建议确认这两套状态并存是不是你想要的设计;如果希望合并/二选一,请指示。

2. **`post_execution_cooldown` 条件偏离了你的 spec YAML,但遵循了 spec 文本说明**。你的 YAML 里写:
   ```yaml
   post_execution_cooldown:
     enter_conditions:
       - previous_state_in: [active_long_execution, active_short_execution]
       - minutes_since_previous_transition_lt: 120
   ```
   但 `previous_state` 严格指"上一 tick 的状态",pipeline 按 tick 跑时这只会在紧挨着下一 tick 命中一次,之后 previous 就变成 `post_execution_cooldown` 自己,条件就不成立了——达不到"冷却 120 分钟"的语义。你紧接着的 spec 文本("D) post_execution_cooldown 特殊处理")又说"先从 DAO 读**最近一条 state=active_* 的记录**,计算距今分钟数",这才是 120 分钟冷却的正确语义。我按 spec 文本实现,即新增字段 `minutes_since_last_active_execution`(用 `StrategyStateDAO.get_latest_with_state_in(['active_long_execution', 'active_short_execution'])` 反查),YAML 里条件改为 `minutes_since_last_active_execution_lt: 120`。如果你想严格按 YAML 的"immediate previous"语义,我切换一行代码就行。

3. **StrategyState schema 依然不是 `schemas.yaml §4.8` 的完整版**。Sprint 1.12 里我说了"state_key / previous_state_key / transition_reason 等会在 1.13 加"——现在加的是 `state['state_machine']` 这个**子字典块**,字段名是 `current_state` / `previous_state` / `transition_reason` / `stable_in_state` / `state_entered_at_utc` / `minutes_since_previous_transition` / `transition_evidence`,**不是**把 state_key / previous_state_key 平铺到顶层。若 schemas.yaml 要求平铺,请告知我改字段布局。当前布局便于 AI/下游只读 `state.state_machine` 就拿到完整决策过程。

4. **`account_state` 还没接真实账户源**。`account_has_long_position` / `account_has_short_position` / `account_stop_triggered` 目前是从 `account_state_provider()` 取,后续 Sprint 实现 FastAPI 或本地 wallet 监控时再把真实 source 接上。现阶段 `run_pipeline_once.py` 跑时 account_state=None,所以 `long_protective_hold` / `short_protective_hold` / `stop_triggered` 都不会误触发。

5. **事件风险字段名 `event_risk_level` vs `band`**。EventRisk factor 实际输出 `band ∈ {low, medium, high}`,你的 spec 写的是 `event_risk_level`。我在抽取器里让 `event_risk_level` 优先读 `band`(`er.get("event_risk_level") or er.get("band")`),两个名字都能工作,因为 event_risk factor 本身没改。

---

## 本 Sprint 做了什么(3 句话)

1. 新增 `src/pipeline/state_machine.py` + `config/state_machine.yaml` 的 14-状态分类器:YAML 声明 `transition_priority` + 每状态 `enter_conditions`,Python 侧 DSL 支持 `_eq/_in/_gt/_gte/_lt/_lte` 六种操作符,字段抽取层兼容 Sprint 1.12 顶层 / `evidence_reports` 两种 shape,缺失字段保守 False。
2. StrategyStateBuilder 插入 `state_machine` stage(在 AI 之后、persist 之前),从 `StrategyStateDAO.get_latest_state` 读上一条记录作为 `previous_record`,把 `{previous_state, current_state, transition_reason, stable_in_state, state_entered_at_utc, minutes_since_previous_transition, transition_evidence}` 写进 `state['state_machine']`;stage 失败用 `_state_machine_fallback` 回退到 `neutral_observation`。
3. 新增 `StrategyStateDAO.get_latest_with_state_in(states)`(用 `json_extract($.state_machine.current_state)` 反查)+ `tests/test_state_machine.py` 20 用例,全绿 200 passed。连续两次 `run_pipeline_once.py` 验证 `previous_state` 正确串联。

---

## 提交信息

`Sprint 1.13: State Machine with 14-state FSM`

---

## 详细报告

### 1. 14 状态 + 优先级

| # | 状态 | 主要触发条件 | 设计语义 |
|---|---|---|---|
| 1 | `cold_start_warming_up` | `cold_start.warming_up=true` | 历史 < 42 轮 |
| 2 | `degraded_data_mode` | `stages_failed_count ≥ 3` | 多 collector 失败 |
| 3 | `stop_triggered` | `account.stop_triggered=true` | 账户止损上报 |
| 4 | `chaos_pause` | `L1.regime = chaos` | 混乱期暂停 |
| 5 | `macro_shock_pause` | `L5 strong_headwind + risk_off + correlation ≥ 0.7` | 宏观冲击 |
| 6 | `event_window_freeze` | `event_risk=high + ≤ 24h` | 事件窗口冻结 |
| 7 | `post_execution_cooldown` | `minutes_since_last_active_execution < 120` | 120 分钟冷却 |
| 8 | `active_long_execution` | `bullish + grade A/B + can_open/cautious_open/ambush_only + cap > 0.02` | 主动做多 |
| 9 | `active_short_execution` | 镜像做空 | 主动做空 |
| 10 | `long_protective_hold` | `account.long > 0 + perm ∈ {no_chase,hold_only,watch,protective}` | 多头保护持仓 |
| 11 | `short_protective_hold` | 镜像做空 | 空头保护持仓 |
| 12 | `disciplined_bull_watch` | `bullish + grade B/C + perm ∈ {hold_only, watch}` | 多头纪律观察 |
| 13 | `disciplined_bear_watch` | 镜像做空 | 空头纪律观察 |
| 14 | `neutral_observation` | 兜底(空 enter_conditions) | 中性观察 |

优先级 `transition_priority` 按上表顺序:**异常/降级/暂停类先判**,**active 类靠后**,`neutral_observation` 兜底。这样保证"chaos + bullish A 同时满足"时不会误进 active_long(实际走 chaos_pause)。

### 2. DSL 操作符

| 后缀 | 语义 | 例子 |
|---|---|---|
| `_eq` | 相等 | `cold_start_warming_up_eq: true` |
| `_in` | 值 ∈ 列表 | `l3_grade_in: [A, B]` |
| `_gt` / `_gte` | 数值 > / ≥ | `stages_failed_count_gte: 3` |
| `_lt` / `_lte` | 数值 < / ≤ | `event_hours_ahead_lte: 24` |
| 空 conditions 列表 | 永远 true(兜底) | `neutral_observation` 用 |

每条 `enter_conditions` 是 `list[dict]`,AND 语义。任一条件失败 → 该状态不进,继续往下一优先级试。

**缺失字段保守为 False**:例如 L2 output 缺失 → `l2_stance_eq: bullish` 直接 False,避免"空 L2 也误入 active"。

### 3. 字段抽取器(`_FIELD_EXTRACTORS`)

字段 → 抽取 lambda:

```python
"cold_start_warming_up":   s → state['cold_start']['warming_up']
"runs_completed":          s → state['cold_start']['runs_completed']
"l1_regime":               s → evidence.layer_1.regime | regime_primary
"volatility_regime":       s → evidence.layer_1.volatility_regime | volatility_level
"l2_stance":               s → evidence.layer_2.stance
"l3_grade":                s → evidence.layer_3.opportunity_grade | grade
"l3_execution_permission": s → evidence.layer_3.execution_permission
"l4_position_cap":         s → evidence.layer_4.position_cap
"l5_macro_headwind":       s → evidence.layer_5.macro_headwind_vs_btc
"l5_macro_environment":    s → evidence.layer_5.macro_environment
"btc_nasdaq_correlation":  s → float | float(layer_5.btc_nasdaq_correlation[.coefficient])
"event_risk_level":        s → composite.event_risk.event_risk_level | band
"event_hours_ahead":       s → min(e.hours_to for e ∈ contributing_events, e.hours_to ≥ 0)
"nearest_event_name":      s → argmin 同上 的 name | type
"stages_failed_count":     s → len(pipeline_meta.failures | meta.stages_failed)
"account_has_long_position":  a → a.long_position_size > 0
"account_has_short_position": a → a.short_position_size > 0
"account_stop_triggered":     a → a.stop_triggered
"previous_state":          (from previous_record.state.state_machine.current_state)
"minutes_since_previous_transition": (now - previous_record.run_timestamp_utc)
"minutes_since_last_active_execution": (now - DAO.get_latest_with_state_in(['active_long_execution','active_short_execution']).run_timestamp_utc)
```

字段抽取容错:内部 try/except,任何 lambda 报错 → 对应字段 = None → 条件评估 False(保守)。

**两种 state shape 都支持**:优先取 `state[key]`(顶层 shortcut),否则取 `state['evidence_reports'][key]`(Sprint 1.12 嵌套风格)。单测里用了两种 fixture 形状验证。

### 4. `state.state_machine` 块结构

```json
{
  "previous_state": "cold_start_warming_up | null",
  "current_state":  "<state_name>",
  "transition_reason": "冷启动中,已运行 3/42 轮",
  "transition_evidence": {
    "matched_conditions": [
      "cold_start_warming_up eq True (actual=True)"
    ],
    "evaluated_order": [
      "cold_start_warming_up"
    ],
    "state_entered": "cold_start_warming_up",
    "fields_snapshot": {
      "cold_start_warming_up": true,
      "runs_completed": 3,
      "l1_regime": "transition_up",
      ...  // 只留标量 + 短字符串
    }
  },
  "stable_in_state": true,
  "minutes_since_previous_transition": 1.5,
  "state_entered_at_utc": "2024-05-10T10:00:00Z"
}
```

`stable_in_state=true` 表示当前状态和 previous_state 相同(连续 tick 未跳)。`state_entered_at_utc` 在 stable 情况下沿用前一条记录的时间,transition 时刷为 `run_timestamp_utc`——这样下游可以算"已在此状态持续多久"。

### 5. 降级契约

| 情况 | 行为 |
|---|---|
| YAML 找不到 | StateMachine 构造失败 → StrategyStateBuilder `_state_machine` stage 异常 → 用 `_state_machine_fallback` 回退到 `neutral_observation`,写 FallbackLog level_1 |
| `determine_state` 内部异常 | 同上 |
| DAO `get_latest_with_state_in` 抛错(old SQLite 等) | `minutes_since_last_active_execution=None` → `post_execution_cooldown` 条件评估 False,不会误触发 |
| `account_state_provider` 抛错 | `account_state=None` → 所有 `account_*` 字段为默认值(False / 0)|
| 全部 state 都不匹配(理论上不可能,有 neutral_observation 兜底) | 额外兜底 return neutral_observation,`transition_reason='fallback: no state matched (config error)'` |

### 6. 集成:StrategyStateBuilder 15→16 stage

```diff
 cold_start_check                 ← 1.12
 cycle_position_last_stable_lookup
 composite.truth_trend
 composite.band_position
 composite.cycle_position
 composite.crowding
 composite.macro_headwind
 layer_1
 composite.event_risk
 layer_2
 layer_3
 layer_4
 layer_5
 ai_summary
+state_machine                    ← 1.13 新增
 persist_state
```

stage `state_machine` 读:
1. `StrategyStateDAO.get_latest_state(conn)` → previous_record(可能为 None)
2. `self._account_state_provider()` → account_state(可注入;默认 None)
3. `self.conn` 传给 `determine_state` 供 `_minutes_since_last_active` 反查

异常时记 `FallbackLog(level_1, triggered_by="pipeline.state_machine")`,`state_machine` 块仍用降级占位填入,pipeline 不中断。

### 7. 测试覆盖(20 cases,全 PASS)

**每状态典型触发**(12):
1. cold_start=True → `cold_start_warming_up`(模板 `{runs}/{threshold}` 填充验证)
2. 3 个 stage 失败 → `degraded_data_mode`
3. L1=chaos → `chaos_pause`
4. bullish + A + can_open + cap=0.12 → `active_long_execution` + 模板填 `Grade=A / 0.12 / can_open`
5. bearish + A + can_open → `active_short_execution`
6. bullish + C + watch → `disciplined_bull_watch`
7. neutral → `neutral_observation`
8. event=high + hours=12 → `event_window_freeze` + 模板填 FOMC/12h
9. risk_off + strong_headwind + corr=0.82 → `macro_shock_pause`
10. 30 min 前 active_long 记录 → `post_execution_cooldown`
11. 150 min 前 active_long → `active_long_execution`(冷却已过)
12. `account.stop_triggered=true` → `stop_triggered`

**优先级冲突**(2):
13. chaos + bullish A → `chaos_pause`(chaos 优先)
14. event_window + active 条件同时 → `event_window_freeze`

**集成 & 边界**(6):
15. 端到端:两次 `StrategyStateBuilder.run()` → 第二次 `previous_state == first.current_state`
16. `previous_record=None` → `previous_state=None` + `stable_in_state=False`
17. 顶层 shortcut shape(`state['layer_1']` 直接在顶层)也正常工作
18. `stable_in_state=True` 时 `state_entered_at_utc` 沿用旧时间 + `minutes_since_previous_transition` 正确计算
19. DSL `_eval_single` 单元测:gt/gte/lt/lte/eq/in 各取样
20. 完全空 state → 兜底进 `neutral_observation`

**全测试套件**:200 passed,0.87s(Sprint 1.12 的 180 + 本 Sprint 20)。

### 8. 脚本输出样例

```bash
$ uv run python scripts/run_pipeline_once.py
{
  "run_id": "47ec4182-...",
  "persisted": true,
  "summary": {
    ...
    "state_machine.previous": null,
    "state_machine.current": "cold_start_warming_up",
    "state_machine.transition_reason": "冷启动中,已运行 2/42 轮",
    "state_machine.stable_in_state": false,
  }
}

$ uv run python scripts/run_pipeline_once.py   # 第二次
{
  ...
  "state_machine.previous": "cold_start_warming_up",
  "state_machine.current":  "cold_start_warming_up",
  "state_machine.transition_reason": "冷启动中,已运行 3/42 轮",
  "state_machine.stable_in_state": true,
}
```

### 9. 留给后续 Sprint

- **Sprint 1.14**:Review Report 生成(lifecycle 结束触发)
- **Sprint 1.15**:StrategyModule(交易执行):这时启用 `config/lifecycle_fsm.yaml` 的 §5 lifecycle FSM,把系统状态(本 Sprint)与交易生命周期状态(保留的原 yaml)串接
- `account_state_provider` 接真实 wallet / 交易所 API
- 把 `schemas.yaml §4.8` 的完整 BtcStrategyState 字段(kpi_snapshot / observation_category 等)补齐(如果确有需要)
