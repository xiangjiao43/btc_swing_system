# Sprint 1.14 报告:AI Adjudicator + Lifecycle FSM

## 目标回顾

- Task A:`src/ai/adjudicator.py` — 硬约束前置 + AI 主裁决
- Task B:`src/pipeline/lifecycle_fsm.py` + `config/lifecycle_fsm.yaml`
- 集成:`StrategyStateBuilder` 新增 `adjudicator` / `lifecycle_fsm` 两个 stage
- 验收:`uv run pytest tests/ -v` 全绿(≥224);`scripts/run_pipeline_once.py --dry-run` 跑通

## Task A:AI Adjudicator

### 硬约束前置(不调 AI,节省成本)

| 触发 | 强制 action |
|---|---|
| State Machine ∈ {chaos_pause, event_window_freeze, degraded_data_mode, macro_shock_pause, stop_triggered} | `pause` |
| State Machine = cold_start_warming_up | `watch` |
| L3.execution_permission = watch | `watch` |
| L3.execution_permission = protective + 有多仓 | `reduce_long` |
| L3.execution_permission = protective + 有空仓 | `reduce_short` |
| L3.execution_permission = protective + 无仓 | `hold` |
| L3.execution_permission = hold_only | `hold` |
| L4.position_cap ≤ 0 | `watch` |

检查顺序:State Machine 异常档 → cold_start → L3 权限 → L4 cap。

### AI 调用门槛(同时满足)

- `L3.grade ∈ {A, B, C}`
- `L3.execution_permission ∈ {can_open, cautious_open, ambush_only, no_chase}`
- `State Machine ∈ {active_long_execution, active_short_execution, disciplined_bull_watch, disciplined_bear_watch}`

不满足 → 直接返回 `watch`,不调 AI。

### AI 路径参数

- `temperature=0.2`,`max_tokens=600`
- JSON 解析失败一次重试(temp=0.0)→ 仍失败 → 回退 `watch`,`status=degraded_structured`
- AI action 违反硬约束 → override 到最接近允许项,notes 追加 `ai_action_overridden_by_constraints`

### 输出契约

```
{action, direction, confidence, rationale, constraints:{
  max_position_size, stop_loss_reference, event_risk_warning,
  execution_permission_binding,
}, evidence_gaps, model_used, tokens_in, tokens_out, latency_ms,
   status, notes}
```

### 单测:`tests/test_adjudicator.py`(14 case 全过)

硬约束 6 / AI 路径 6 / 规则兜底 1 / 字段形状 1。

## Task B:Lifecycle FSM

### 14 状态集

- FLAT
- LONG 侧 6:LONG_PLANNED / LONG_OPEN / LONG_SCALING / LONG_REDUCING / LONG_CLOSED
- SHORT 侧 5:SHORT_PLANNED / SHORT_OPEN / SHORT_SCALING / SHORT_REDUCING / SHORT_CLOSED
- 事件终止 3:STOP_TRIGGERED / COOLDOWN / FLAT_AFTER_STOP

`config/lifecycle_fsm.yaml` 采用声明式 transitions 表 + auto_after_minutes 实现,
`src/pipeline/lifecycle_fsm.py` 单函数 `compute_next` 完成推进。

### 评估顺序

1. `_auto_after_minutes` 已到期 → 走 `_auto_target`(auto_timeout)
2. action 在表中 → 显式目标
3. 否则走 `_default`
4. 无 `_default` 且仅 auto(如 LONG_CLOSED)→ 保持(no_op)

### 方向冲突保护

持 LONG_* + `open_short|scale_in_short` → 保持原状态 + `conflict_detected=true`,
反之亦然。

### 单测:`tests/test_lifecycle_fsm.py`(16 case 全过)

### 集成到 StrategyStateBuilder

新 stage 顺序:

```
composite → L1-L5 → ai_summary
→ state_machine   (adjudicator 需要读 state_machine.current_state)
→ adjudicator
→ lifecycle_fsm
→ persist_state
```

`state` 新增两个顶层字段:

- `state["adjudicator"] = {...}`
- `state["lifecycle"] = {previous_lifecycle, current_lifecycle,
   transition_triggered_by, transition_rule, minutes_since_previous,
   conflict_detected, state_entered_at_utc}`

`StrategyStateDAO.get_latest_state(...)` 供 lifecycle FSM 读上次的
`lifecycle.current_lifecycle` 和 `state_entered_at_utc`。无历史 → 默认 FLAT 起步。

## 验收

- 全量测试:230 passed, 1 skipped(Sprint 1.13 基线 200 + 新增 30)
- Pipeline 一次:`uv run python scripts/run_pipeline_once.py --dry-run` 成功跑完,
  `adjudicator.action=watch`(硬约束:冷启动),`lifecycle.current=FLAT`。

## 下一步(Sprint 1.15)

- FastAPI routes(health / strategy / pipeline / history / fallback_log)
- APScheduler 定时任务(pipeline 每 4 小时;data_collection / cleanup 留骨架)
