# Sprint 1.5a 报告:状态机对齐建模 §5(14 档 + FLIP_WATCH 冷却 + PROTECTION)

## Triggers(偏离建模 / 自主决策)

1. **StrategyStateBuilder 内 Adjudicator 顺序前移到 State Machine 之前**
   - 建模未显式规定顺序,但旧代码是 SM→Adjudicator(Adjudicator 读 sm.current_state)。
   - 新 14 档状态机很多迁移条件(trade_plan、thesis_still_valid 等)由 Adjudicator 产出,所以把 State Machine 放在 Adjudicator 之后更符合建模 §5.2。
   - Adjudicator 里对 state_machine_current 的旧名称读取暂时失效(会回落到保守规则路径)——这一致性问题留给 Sprint 1.5b 的 adjudicator 对齐。
2. **state_machine.yaml 大幅瘦身为"只存阈值/乘数"**,迁移条件逻辑全部放到 Python(§5.2 的组合条件如"时间 ≥ 24h 且走势至少满足一项"YAML DSL 表达力不够)。
3. **on_enter 副作用 v1 只写 on_enter_effects 字段**,不真正写 lifecycle 表;实际 lifecycle 管理留给 Sprint 1.5b 的 `lifecycle_manager`(state.lifecycle 现为 `{current_lifecycle: "pending_lifecycle_manager"}` 占位)。
4. **旧 StateMachine 和 LifecycleFSM 一次性全部删除**,不做"兼容旧状态名"。读到历史库里的旧名(如 `active_long_execution`)一律归零到 `FLAT` 重新开始。

## Task 执行结果

### Task A:搬家 + 命名对齐

- 新建 [src/strategy/](src/strategy/)、[src/strategy/__init__.py](src/strategy/__init__.py)、[src/strategy/state_machine.py](src/strategy/state_machine.py)
- 删除 `src/pipeline/state_machine.py`、`src/pipeline/lifecycle_fsm.py`、`config/lifecycle_fsm.yaml`
- 重写 [config/state_machine.yaml](config/state_machine.yaml)(只存阈值/乘数/持续时间等参数)
- [src/pipeline/state_builder.py](src/pipeline/state_builder.py) 改调 `src.strategy.state_machine.StateMachine`;移除 `lifecycle_fsm` stage;`state.lifecycle` 暂填占位

### Task B:14 档状态迁移规则

[src/strategy/state_machine.py](src/strategy/state_machine.py) 按 §5.2 实现逐 source 分派 `_from_<STATE>`:

| 源 → 目标 | 条件语义 | 实现位置 |
|---|---|---|
| FLAT → LONG_PLANNED | 全部 8 项满足 | `_from_FLAT` |
| FLAT → SHORT_PLANNED | 镜像,`stance_confidence ≥ short_min` | `_from_FLAT` |
| *_PLANNED → *_OPEN | `entry_zone_filled_confirmed_1h = true` | `_from_*_PLANNED` |
| LONG_OPEN → LONG_HOLD | `(hours_since_open ≥ 24 ∧ 走势任一)` ∨ `tp1_distance ≥ 50%` | `_from_LONG_OPEN` |
| LONG_OPEN → LONG_EXIT | 5 条任一触发 | `_from_LONG_OPEN` |
| LONG_HOLD → LONG_TRIM | 5 条任一触发(tp_target / ai_phase=late / regime 转换 / thesis 弱化 / 宏观恶化) | `_from_LONG_HOLD` |
| LONG_TRIM 后续 | 三选一:current_trim_completed→LONG_HOLD、next_trim→LONG_TRIM、final→LONG_EXIT | `_from_LONG_TRIM` |
| LONG_EXIT → FLIP_WATCH / FLAT | 仓位已平 + L2 偏空 + L1 下行 → FLIP_WATCH;否则 FLAT | `_from_LONG_EXIT` |
| FLIP_WATCH → SHORT_PLANNED / LONG_PLANNED / FLAT | effective_min/max 校验 + 反向论点失效 + Grade A/B | `_from_FLIP_WATCH` |
| 任何 → PROTECTION | `l5.extreme_event_detected` / `fallback_level ≥ 3` / `macro_events.protection_trigger` | `compute_next` 前置检查 |
| PROTECTION → POST_PROTECTION_REASSESS | 事件结束 + 数据健康 + 无新极端风险 | `_from_PROTECTION` |
| POST_PROTECTION_REASSESS | 强制 ≥4h + 白名单 {LONG/SHORT_HOLD, LONG/SHORT_EXIT, FLAT, FLIP_WATCH} | `_from_POST_PROTECTION_REASSESS` |

SHORT 侧完整对称实现。

### Task C:FLIP_WATCH 动态冷却(§5.3)

`_calc_flip_watch_bounds` 在 LONG/SHORT_EXIT → FLIP_WATCH 迁移时计算并写入 `state.state_machine.flip_watch_bounds`:

- 基础 min=18h / max=96h
- cycle_position × {late_bull/distribution/late_bear/accumulation: 0.7, mid_bull/mid_bear: 1.3}
- volatility_regime × {extreme: 1.3, low: 0.8}
- `effective_min = max(8, 18 × 乘数累乘)`;`effective_max = min(168, 96 × 乘数累乘)`
- 进入时锁定,周期内不变(后续 tick 从 previous_record.state_machine.flip_watch_bounds 读)

单测 `test_24_flip_watch_multipliers_late_bull_low_vol` 验证 0.56 乘积 → min≈10.08h,max≈53.76h。

### Task D:状态进入副作用(§5.5)

`_on_enter_effects` 写入 `state.state_machine.on_enter_effects`,v1 只记动作列表:

- FLAT:`archive_current_lifecycle / reset_position_cap / clear_all_pending_orders / log_transition`
- *_PLANNED:`create_lifecycle_draft / record_origin_thesis / set_planned_expiry / push_notification`
- *_OPEN:`lifecycle_pending_to_active / record_origin_time / enable_open_phase_protection / push_notification`
- *_HOLD:`disable_open_phase_protection / enable_standard_monitoring / init_max_favorable_pct / init_max_adverse_pct`
- *_TRIM:`record_position_adjustment / stage_partial_trimmed / update_remaining_stops_and_tps`
- *_EXIT:`record_position_adjustment / prepare_lifecycle_archive / record_exit_reason`
- FLIP_WATCH:`archive_previous_lifecycle / record_flip_watch_start_time / lock_flip_watch_effective_bounds / reset_position` + flip_watch_bounds
- PROTECTION:`record_protection_entry_time_and_reason / freeze_new_openings / ai_handles_residual_positions / push_urgent_notification / require_manual_confirmation`
- POST_PROTECTION_REASSESS:`record_reassess_entry_time / preserve_lifecycle_no_archive / force_execution_permission_hold_only`

所有副作用标注 `lifecycle_delegate: "pending_lifecycle_manager"`,为 Sprint 1.5b 接入做准备。

### Task E:三条核心纪律(§5.4)

`_verify_disciplines` 在 `_build_result` 出口统一拦截,违反抛 `DisciplineViolation`:

1. **HOLD 不能直跳反向 PLANNED**:白名单阻止 `LONG_HOLD → SHORT_PLANNED` / `SHORT_HOLD → LONG_PLANNED`
2. **FLIP_WATCH 冷却强制**:`_from_FLIP_WATCH` 内部 `hours_in < effective_min` 永不产出迁移路径;1H 信号因此无法单独触发方向切换
3. **PROTECTION 唯一出口经 POST_PROTECTION_REASSESS**:拦截 PROTECTION→其他;POST_PROTECTION_REASSESS→PROTECTION;POST_PROTECTION_REASSESS→任何 PLANNED

### Task F:单测

[tests/test_state_machine.py](tests/test_state_machine.py) 共 **41 case**(Task F 最低要求 20),全部通过。

分布:
- FLAT 分支 8 case(正/负面)
- *_PLANNED / *_OPEN / *_HOLD / *_TRIM / *_EXIT 覆盖 16 case
- FLIP_WATCH 动态冷却 4 case(含乘数精确验证)
- PROTECTION / POST_PROTECTION_REASSESS 6 case
- 纪律违反 3 case
- 对称空头 4 case

### Task G:清理旧代码

| 删除 | 状态 |
|---|---|
| `src/pipeline/state_machine.py` | ✓ |
| `src/pipeline/lifecycle_fsm.py` | ✓ |
| `config/state_machine.yaml`(旧) | ✓(已替换为新版) |
| `config/lifecycle_fsm.yaml` | ✓ |
| `tests/test_state_machine.py`(旧 20 case) | ✓(已替换为新 41 case) |
| `tests/test_lifecycle_fsm.py` | ✓ |
| `src/pipeline/__init__.py` 里的 `StateMachine / LifecycleFSM` 导出 | ✓ |

`state.lifecycle` 字段保留,当前值 `{"current_lifecycle": "pending_lifecycle_manager", "managed_by": "sprint_1_5b_pending"}`。

### Task H:验收

- `uv run pytest tests/ -v` 全绿:**274 passed, 1 skipped**(旧版约 269,移除 37 条旧测试 + 新增 41 条 + 1 个 whitelist 冒烟 = 274,符合"约 260+")
- `uv run python scripts/run_pipeline_once.py --dry-run`:`state_machine.current = "FLAT"`,是建模 14 档之一 ✓
- 连跑两次(`--dry-run` 一次 + 持久化一次 + 再持久化一次):第二次持久化看到 `previous_state="FLAT", current_state="FLAT"`,说明 DAO→previous_record→新 SM 链路工作正常 ✓

### Task I:Commits

按任务分组提交(Task A/B/C/D/E 因单模块改动合并为一次 commit):

- `Sprint 1.5a-1..4: new 14-state machine per modeling §5`
- `Sprint 1.5a-5: state machine tests (40+ cases)`

## 简短三段汇报

**结果**:14 档状态机按建模 §5.1-§5.5 完整实现并落到 `src/strategy/state_machine.py`,旧的两套混乱 FSM(`src/pipeline/state_machine.py` + `src/pipeline/lifecycle_fsm.py`)及其配置与测试一并清除;FLIP_WATCH 动态冷却、三条核心纪律、§5.5 on_enter 副作用、对称空头全部到位;41 个单测全部通过,全仓库 274 pass;pipeline 脚本输出的 `state_machine.current` 是建模 14 档之一。

**自主决策**:把 Adjudicator 在 pipeline 里提前到 State Machine 之前(因为建模 §5.2 的很多迁移条件依赖 Adjudicator 产出);Adjudicator 里 `active_long_execution` 等旧状态名的硬约束分支会暂时命不中,新 14 档状态不会触发 AI 调用,这一致性修复留给 Sprint 1.5b 的 adjudicator 对齐;`state.lifecycle` 改为 `pending_lifecycle_manager` 占位,真实 lifecycle 表写入留给 Sprint 1.5b。

**待关注**:
1. Adjudicator 目前读 `state_machine_current` 时识别的还是旧名(chaos_pause / active_long_execution / cold_start_warming_up / ...),新 14 档状态落地后,Adjudicator 不会路由到 AI 路径,所有裁决退化到规则兜底;Sprint 1.5b 必须同步改 adjudicator 的 hard-constraint 判断与 allowed_actions 白名单。
2. `test_kpi_collector` / `test_review_generator` / `test_alerts` / `test_api_routes` 的 fixture 里还用旧状态名(`active_long_execution`、`neutral_observation` 等)测分布聚合,这些测试自带 fixture,不会破产;但旧状态名实际不会在生产库里再产生新记录,Sprint 1.5b 考虑是否同步更新为新 14 档名字。
3. State Machine 的 `cycle_position` 字段只在 LONG/SHORT_EXIT → FLIP_WATCH 时用于乘数计算,当前 `composite_factors.cycle_position.cycle_position` 字段在真实运行可能为 None——会走默认 mult=1.0,还需 Sprint 1.5b 把真实字段通路对齐。
