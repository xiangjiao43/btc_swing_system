# Sprint 1.5b 报告:Observation Classifier + Adjudicator 对齐 14 档 + position_cap / permission 合成

## Triggers(偏离建模 / 自主决策)

1. **Sprint 1.10 的 `grade_to_base_cap` + `per_trade_decay` 多因素衰减**从 Layer4 删除。按建模 §4.5.5 只保留"基础 70% × 4 个乘数"的单一串行合成链。`scale_in_plans`(按 grade 分层加仓)保留,因为是 §7.10 的独立机制,不冲突。
2. **`hard_invalidation_levels`(§4.5.4)v1 实现**:直接把 `stop_loss_reference` 升格为单条 hard_invalidation_level(priority=1,confirmation_timeframe="4H",basis=stop 的 atr/swing/combined 方法)。Sprint 1.5c+ 再接更精细的结构性失效位。
3. **`overall_risk_level`(§4.5.7)本 Sprint 自己派生**:从 volatility_regime + crowding_score + event_risk_score + macro_headwind_score 4 个信号各自评档,取最严。建模没明确计算公式,本分档方案写进 `_derive_overall_risk_level`。
4. **Adjudicator 的 `state_machine_hint` / `state_machine_output` 上下文传递**:L4 计算 permission 的 A 级缓冲需要知道当前 state_machine 是否为 PROTECTION。但 L4 在 state_machine 之前跑,此时 state_machine 还未算。v1 方案:L4 读 `context.state_machine_hint` / `context.state_machine_output`,实际运行时通常为 None,走非 PROTECTION 分支。Sprint 1.5c+ 若需要 PROTECTION 感知,需反转顺序或引入早期状态判定。
5. **`observation_category` 流水线位置**:建模 §4.7.1 说"L3 之后、AI 裁决之前"。我放在 L5 之后、AI summary 之前(即四层证据全部就位)。因为 `observation_category` 的 disciplined 判定依赖 L4 `overall_risk_level` 和 L5 `macro_stance`,放 L3 之后就读不到。不影响纪律条款(只读)。
6. **`state.lifecycle` 维持 pending_lifecycle_manager 占位**(来自 Sprint 1.5a),Sprint 1.5b 不动它。

## Task 执行结果

### Task B1:Observation Classifier(§4.7)

- 新建 [src/strategy/observation_classifier.py](src/strategy/observation_classifier.py),`classify()` 函数产出 `ObservationResult`
- 四档:`disciplined` / `watchful` / `possibly_suppressed` / `cold_start_warming_up`
- disciplined 7 条硬触发(任一)、watchful 4 条同时满足、possibly_suppressed 6 条同时满足 + streak ≥ 42 次运行
- 告警级别:`warning`(streak ≥ 84)/ `critical`(streak ≥ 180)
- **纪律条款字段 `discipline_note` 每次输出**,明确"只读、不进决策路径"
- StrategyStateBuilder 新增 `observation_classifier` stage(L5 之后,AI summary 之前);`state.observation` 持久化到 strategy_state_history
- 单测 [tests/test_observation_classifier.py](tests/test_observation_classifier.py) 18 case 全绿

### Task B2:Adjudicator 对齐 14 档(§6.5)

旧状态名 → 新 14 档映射:

| 旧名 | 新处理 |
|---|---|
| `chaos_pause` | 拆散:`l1_regime=chaos` → A 级缓冲例外 → permission 强制 watch |
| `active_long_execution` | 不再是状态,由 L2.stance + L3.grade + L3.permission 自然决定 |
| `active_short_execution` | 同上(对称) |
| `cold_start_warming_up` | 从状态变为 `cold_start.warming_up=true` 直接检查 |
| `disciplined_*_watch` | 不再是状态,由 observation_classifier 反映 |
| `event_window_freeze` | 不再是状态,通过 L4.event_risk_score / L5 事件反映 |
| `degraded_data_mode` | `pipeline_meta.fallback_level ≥ 2` 检查 |
| `macro_shock_pause` | `l5.extreme_event_detected=true` |
| `stop_triggered` | 暂未使用(account_state 自己会在 Sprint 2+ 暴露) |

新 `_check_hard_constraints` 优先级:

1. L5 extreme_event OR state=PROTECTION → `pause`
2. cold_start.warming_up → `watch`
3. fallback_level ∈ {level_2, level_3, ≥2} → `watch`
4. state=POST_PROTECTION_REASSESS → `hold`
5. L3.execution_permission = watch → `watch`
6. L3.execution_permission = protective → `reduce_*`/`close_*`/`hold`
7. L3.execution_permission = hold_only → `hold`
8. L4.position_cap = 0 → `watch`

`_should_call_ai` 状态白名单:{FLAT, LONG_PLANNED, LONG_OPEN, LONG_HOLD, LONG_TRIM, SHORT_PLANNED, SHORT_OPEN, SHORT_HOLD, SHORT_TRIM, FLIP_WATCH}。

`_allowed_actions_for_facts` 每档状态对应一组合法 action(FLAT 允许 open_*,*_OPEN 允许 hold/scale_in/reduce/close,FLIP_WATCH 只允许 hold/watch 等)。

[tests/test_adjudicator.py](tests/test_adjudicator.py) 重写,19 case 覆盖全部 8 条硬约束路径 + AI 路径 + 规则兜底。

### Task B3:cycle_position 字段路径确认

- 验证 [src/composite/cycle_position.py:188](src/composite/cycle_position.py:188) 实际输出嵌套键名是 `cycle_position`(不是 `band`)
- 检查 [src/strategy/state_machine.py](src/strategy/state_machine.py) 的字段读取:`cp.get("cycle_position") or cp.get("band")` 已正确兼容两种形态
- 在 [tests/test_state_machine.py](tests/test_state_machine.py) 新增 test_41 / test_42 锁定字段链路:
  - test_41:生产路径(`cycle_position="late_bear"` + `volatility=extreme`)→ 乘积 0.7 × 1.3 = 0.91 → eff_min ≈ 16.4h,eff_max ≈ 87.4h
  - test_42:legacy `band` 字段回退也能读到
- **结论:Sprint 1.5a 当时已经写对了,本 Sprint 只是补回归测试**

### Task B4 + B5:position_cap + execution_permission 合成(合并 commit)

[src/evidence/layer4_risk.py](src/evidence/layer4_risk.py) 整体重写。Layer4 现在的输出:

| 字段 | 含义 | 建模条款 |
|---|---|---|
| `overall_risk_level` | low/moderate/elevated/high/critical | §4.5.7 |
| `position_cap` | 0.0-1.0,最终账户级 cap | §4.5.5 |
| `position_cap_composition` | 5 步审计 + floor_gate 标记 | §4.5.5 |
| `execution_permission` | 归并 + A 级缓冲 + 例外 之后的最终值 | §4.5.6 |
| `permission_composition` | 四条建议 + merged + buffer + override 审计 | §4.5.6 |
| `hard_invalidation_levels` | 单元素 list,由 stop_loss 升格(v1) | §4.5.4 |
| `risk_permission` | L3 ∩ L4 取更严(向后兼容 Sprint 1.10 调用方) | - |
| `stop_loss_reference` / `risk_reward_ratio` / `rr_pass_level` / `scale_in_plan` | Sprint 1.10 逻辑保留 | §7.10 |

5 步合成链:

```
base 70%
  × overall_risk_level mult {low:1.0, moderate:0.9, elevated:0.7, high:0.5, critical:0.3}
  × crowding_score mult   {0-3:1.0, 4-5:0.85, 6+:0.7}
  × macro_headwind mult   {≥-1:1.0, -2~-4:0.85, ≤-5:0.7}
  × event_risk mult       {<4:1.0, 4-7:0.85, ≥8:0.7}
  → floor_gate(permission ∈ {can_open, cautious_open, ambush_only} 且 overall ≠ critical)→ max(.., 15%)
```

Permission 归并:每因子 (overall_risk / crowding / event_risk / macro_headwind) 各产出一个建议 → 取最严 → A 级缓冲抬升(grade=A + regime 稳定 trend_up/down + stable/slightly_shifting)→ 四例外覆盖(PROTECTION / extreme / critical / chaos)。

[tests/test_layer4_risk.py](tests/test_layer4_risk.py) 重写,22 case:
- 5 case 测 5 步合成(含建模 audit example 42.5-28% / floor_gate / critical 不 floor)
- 4 case 测 overall_risk_level 各档
- 8 case 测 permission 归并 + A 级缓冲 + 四例外
- 2 case 测 hard_invalidation_levels
- 3 case 测 schema

### Task B6:单测 + 验收

- `uv run pytest tests/ -v`:**299 passed / 1 skipped**(含本 Sprint 新增 18 observation + 改版 19 adjudicator + 改版 22 layer4 + 2 cycle_position 回归 = 新增/修改约 60 条)
- `uv run python scripts/run_pipeline_once.py --dry-run`:端到端成功
  - `state.observation = {observation_category: "disciplined", reason: "l1_regime=transition_up; l2_stance=neutral", discipline_note: "...只读..."}`
  - `state.evidence_reports.layer_4.position_cap_composition = {base: 70, after_l4_risk: 70, after_l4_crowding: 70, after_l5_macro: 70, after_l4_event: 70, final: 70}`
  - `state.evidence_reports.layer_4.permission_composition = {suggestions: {...}, merged_before_buffer: "can_open", final_permission: "can_open"}`
  - `state.evidence_reports.layer_4.overall_risk_level = "low"`
  - `state.evidence_reports.layer_4.hard_invalidation_levels = []`(L2 stance neutral)
  - 硬约束:cold_start → adjudicator.action="watch"(rationale:"硬约束:冷启动未完成,暂不参与开仓。")
- 连跑两次持久化:`state_machine.previous=FLAT, current=FLAT` 稳定;observation 字段稳定

### Commits

1. `02c1d6f` — Sprint 1.5b-1: Observation Classifier per modeling §4.7
2. `e0e6cdd` — Sprint 1.5b-2: Adjudicator hard constraints aligned to 14-state machine
3. `c369ce1` — Sprint 1.5b-3: confirm cycle_position.* field path for FLIP_WATCH cooldown
4. `e00b4ae` — Sprint 1.5b-4/5: position_cap 5-step + permission merging per modeling §4.5
5. (本 commit) — Sprint 1.5b-6: tests and verification report

## 简短三段汇报

**结果**:Sprint 1.5b 完成。新建 `src/strategy/observation_classifier.py`(§4.7 四档分类器 + 只读纪律条款);Adjudicator `_check_hard_constraints` / `_allowed_actions_for_facts` / `_should_call_ai` 全部对齐建模 14 档 + §6.5 硬约束链;Layer4 `position_cap` / `execution_permission` / `overall_risk_level` / `hard_invalidation_levels` 按 §4.5.5-§4.5.7 重做(Sprint 1.10 的多因素衰减作废);cycle_position 字段链路确认 + 加回归测试;全仓库 299 pass / 1 skipped;pipeline 端到端跑通,state 输出含 observation + position_cap_composition + permission_composition 审计字段。

**自主决策**:
- `overall_risk_level` 建模没给计算公式,本 Sprint 用"vol/crowding/event/macro 各自评档取最严"的规则层派生;
- `hard_invalidation_levels` v1 先由 stop_loss_reference 单条升格,Sprint 1.5c+ 再加结构性失效位;
- observation_classifier 落在 L5 之后而非 L3 之后(L3 之后读不到 L4.overall_risk_level / L5.macro_stance,disciplined 判定会残废);
- Layer4 的 A 级缓冲需要知道 `state_machine_hint`,但 state_machine 在其后跑,所以 v1 只能走 extreme/critical/chaos 三例外,PROTECTION 例外留空(实际由 adjudicator 硬约束前置拦截)。

**待关注**:
1. **Layer4 读 state_machine 的顺序问题**:建模 §4.5.6 的"PROTECTION 态不走 A 级缓冲"需要 Layer4 知道当前 state,但 state_machine 在 L4 之后算。Sprint 1.5c 需要决定:要么让 state_machine 先跑产出 current_state 传给 L4,要么让 Adjudicator 的 PROTECTION 硬约束前置拦截(目前是后者)。
2. **`cold_start_warming_up` 的冷启动标签**:当前 observation 和 adjudicator 都独立检查 `cold_start.warming_up`;两者逻辑一致但重复判断。Sprint 1.5c 可以考虑合并。
3. **`possibly_suppressed` streak 依赖历史 `state.observation.suppressed_base_satisfied` 字段**,当前只有 Sprint 1.5b 之后的运行才会写入,所以 warning/critical 告警需要 14 天 / 30 天实际运行才能触发。测试已用 mock records 验证逻辑正确。
4. **StrategyStateBuilder 的 stage 顺序**仍是 L1-L5 → observation → ai_summary → adjudicator → state_machine。如果 Sprint 1.5c 要让 Layer4 感知 state_machine,必须反转或拆分 state_machine 为"预判"+"正式计算"两阶段。
