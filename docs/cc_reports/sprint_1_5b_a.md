# Sprint 1.5b-A — 触发字段填充器(state_machine 输入侧)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,32 个新测试 + 713/713 全量回归过

---

## 一、问题与决策

**Bug**:建模 §5.2 14 状态机迁移逻辑已在 `state_machine.py` 完整实施,但
迁移条件依赖 `trade_plan / lifecycle / layer_2 / layer_4` 子字段(如
`entry_zone_filled_confirmed_1h`、`floating_pnl_pct`、
`hard_invalidation_breached`),而 `state_builder` 这些字段全 False / None,
导致状态机即使条件成立也卡在 FLAT。

**用户决策**:
- 本 sprint 1.5b-A 只做"输入填充器",**不重写 state_machine.py 的迁移逻辑**(§X)
- v1 lifecycle 还是占位,某些字段(浮盈、累计减仓比例)用简化推断,
  等 1.5b-B lifecycle_manager 接通后改进

---

## 二、改动

### 2.1 新建 `src/strategy/state_machine_inputs.py`

三个公开入口:

```python
build_state_machine_fields(
    *, prev_state, prev_strategy_state, current_strategy_state,
    context, lifecycle=None, now_utc=None,
) -> dict[str, Any]                  # 纯函数:计算 24 字段 flat dict

apply_inputs_to_strategy_state(
    strategy_state, fields,
) -> dict[str, Any]                  # mutate state:写到 trade_plan / lifecycle /
                                     # evidence_reports.layer_2/4 各路径

derive_account_state(fields) -> dict # 从 fields 推 {long_position_size, short_position_size}
                                     # 喂给 state_machine.compute_next 的 account_state= 参数
```

**字段计算**(24 字段,key 完全对齐 state_machine.py `_build_field_snapshot` 期望):

| 字段 | 实施逻辑 |
|---|---|
| `entry_zone_filled_confirmed_1h` | 仅 *_PLANNED:1H 收盘价进入 trade_plan.entry_zones 任一区间 |
| `hours_since_open` | 仅持仓:`now - lifecycle.origin_time_utc`;占位返回 0.0 |
| `floating_pnl_pct` | 仅持仓:`(last_1h_close - avg_entry) / avg_entry * 100`;占位返回 None |
| `hard_invalidation_breached` | 仅持仓:4H 收盘对比 `layer_4.hard_invalidation_levels` priority=1 价位 |
| `stop_loss_hit` | 仅持仓:1H 收盘对比 `trade_plan.stop_loss` |
| `l2_stance` / `l2_stance_confidence` | 直接读 `evidence_reports.layer_2` |
| `l2_stance_flipped` | 持仓期 prev L2.stance(同向) → curr L2.stance(反向) |
| `l2_bullish_early_signal` / `l2_bearish_early_signal` | L2.stance + confidence > 0.4 |
| `l4_new_critical_risk` | prev L4 != "critical" 且 curr == "critical" |
| `thesis_still_valid` | adjudicator.thesis_still_valid 或 thesis_assessment.thesis_still_valid;默认 "fully_valid" |
| `account_has_long` / `account_has_short` | 按 prev_state side 推断;*_EXIT + 48h → 视为已平仓 |
| `positions_flat` | 上面两个都 False |
| `next_trim_triggered` | *_HOLD/*_TRIM:trade_plan.take_profit_plan 找下一个未触发档,1D high/low 是否触达 |
| `current_trim_completed` | 仅 *_TRIM:hours_since_open >= 24h(v1 简化,1.5b-B 改读累计平仓比例) |
| `flip_watch_min_hours_passed` / `_max_hours_exceeded` | 仅 FLIP_WATCH:hours_in_flip_watch 对比 effective_min/max bounds |
| `long_thesis_invalidated` / `short_thesis_invalidated` | side + thesis_still_valid == "invalidated" |
| `prev_cycle_side` | FLIP_WATCH/POST_PROTECTION_REASSESS 从 prev lifecycle 取;否则按 prev_state 推 |
| `tp_target_hit` | 1.5b-A 阶段保留 False,1.5b-B 接通 lifecycle 后再启 |

### 2.2 wiring `src/pipeline/state_builder.py::_run_state_machine`

调 `compute_next` 之前先:
1. 解析 `prev_state_str` 从 DAO 最新 row 的 `state.state_machine.current_state`
2. `build_state_machine_fields(...)` 算 fields
3. `apply_inputs_to_strategy_state(state, fields)` 写到对应路径
4. `derive_account_state(fields)` 推 account_state
5. compute_next 读到的 strategy_state 已经被填好,内部 `_build_field_snapshot` 拿到真实数据

外部 `account_state_provider` 优先级最高,无 provider 时用 fields 推断。
任何字段计算异常都被 try/except 兜住,降级到原行为(空 dict),不让 pipeline crash。

新增 `_run_state_machine` 接 `context` 参数;调用站 `_run_stage` lambda 传入 context。

### 2.3 测试

`tests/test_state_machine_inputs.py`(30 测试):
- 字段单测(每个字段都覆盖 true / false / 占位 / 边界)
- `apply_inputs_to_strategy_state` 路径正确性
- `derive_account_state` 长/短/空
- **关键反退化**:`test_state_machine_no_longer_stuck_at_flat_when_fields_filled`
  + `test_state_machine_long_open_to_long_hold_after_24h_3pct_pnl`
  + `test_state_machine_long_hold_to_long_trim_when_tp_hit`
  这 3 个用真 `StateMachine.compute_next` 跑端到端迁移

`tests/test_state_machine_e2e.py`(2 测试):
- `test_full_progression_flat_to_long_trim`:4 步推进
  FLAT → LONG_PLANNED → LONG_OPEN → LONG_HOLD → LONG_TRIM,每步真跑
  build_state_machine_fields + apply + state_machine.compute_next,prev_state
  从上一步的 result 拿
- `test_state_machine_stuck_at_flat_without_fields_filler`:不调填充器 → trade_plan
  空 → state_machine 永远卡 LONG_PLANNED(显式记录老 bug 行为)

---

## 三、测试结果

| 范围 | 结果 |
|---|---|
| `tests/test_state_machine_inputs.py` | 30/30 pass |
| `tests/test_state_machine_e2e.py` | 2/2 pass |
| `tests/test_state_machine.py`(原回归) | 43/43 pass(无破坏) |
| `tests/test_state_builder.py`(原回归) | 15/15 pass |
| 全量 `pytest tests/` | **713 passed, 1 skipped, 4.65s** |

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 手动触发一次 pipeline,看 state_machine fields 是否真的有数据
.venv/bin/python -c "
from src.pipeline import StrategyStateBuilder
from src.data.storage.connection import get_connection
conn = get_connection()
b = StrategyStateBuilder(conn)
r = b.run(run_trigger='manual')
print('current_state:', r.state['state_machine']['current_state'])
print('matched:', r.state['state_machine'].get('matched_conditions'))
print('fields(部分):',
      'entry_zone_filled_confirmed_1h=',
      r.state.get('trade_plan',{}).get('entry_zone_filled_confirmed_1h'),
      'hours_since_open=',
      r.state.get('lifecycle',{}).get('hours_since_open'),
      'l2_stance_flipped=',
      r.state.get('evidence_reports',{}).get('layer_2',{}).get('stance_flipped'),
)
"
# 预期:current_state 仍可能是 FLAT(取决于 evidence 当下条件),但 fields 应该
# 是真实计算后的值(不是 None / False)。如果 stance=neutral / regime=range,
# state_machine 还是会留 FLAT,那是 evidence 层的问题不是填充器
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除 / 不重复)
- 不重写 state_machine.py 的迁移逻辑(只新增 inputs 模块)
- 不修改 state_machine.py 的 fields 字段名(向后兼容)
- 不重复 `_build_field_snapshot`:它仍是 state_machine 内部组装 fields 的入口,
  我的填充器只把"原本应该有但没有"的子字段写到正确路径,然后让
  `_build_field_snapshot` 自动捡到

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 30 个字段单测都用真 pandas DataFrame klines + 真 lifecycle dict
- 3 个集成测试 + 1 个 e2e 推进都用真 `StateMachine.compute_next`,断言
  `result["current_state"]` 实际迁移结果
- 反退化 guard:`test_state_machine_stuck_at_flat_without_fields_filler` 显式
  记录"不调填充器 → 卡 PLANNED"的老 bug,防止后续误删填充器

### 同类风险扫描
1. **`prev_state` 来自 DAO 最新 row** — 新部署 DB 空时 `previous_record=None`,
   `prev_state_str=None`,填充器返回 prev_state=None → side=None → 大多数字段
   走"非持仓"分支返回 False / 0.0 / None。state_machine 看到这些值会按"FLAT"
   分支跑,符合冷启动语义
2. **`lifecycle` 全占位** — 1.5b-A 阶段 average_entry_price / origin_time_utc 都
   None,`floating_pnl_pct` 返回 None / `hours_since_open` 返回 0.0,state_machine
   LONG_OPEN → LONG_HOLD 的 24h 条件天然不满足,留给 1.5b-B 接通
3. **`tp_target_hit` 保留 False** — state_machine LONG_HOLD → LONG_TRIM 不会自动
   触发,等 1.5b-B 接通 lifecycle.position_adjustments 后再启
4. **生产 stance=neutral 时 state_machine 仍是 FLAT** — 这是 evidence 层(L1/L2)
   的判断,不是填充器问题。填充器仍然正确填充了 stance=neutral / regime=range
   等 fields,state_machine 收到后按规则不迁移
5. **填充器自身异常** — `_run_state_machine` 用 try/except 兜住,失败时降级到
   "fields=空 dict",pipeline 仍能跑完(只是 state_machine 仍卡 FLAT,等同
   1.5b-A 之前的行为)

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/strategy/state_machine_inputs.py` | 新模块,3 公开入口 + 私有计算函数 |
| `src/pipeline/state_builder.py` | `_run_state_machine` 调填充器 + 透传 context |
| `tests/test_state_machine_inputs.py` | 30 字段单测 + 集成 |
| `tests/test_state_machine_e2e.py` | 2 e2e 多步推进 |
| 本报告 | |

---

## 七、未覆盖项 / 1.5b-B 接通项

- `lifecycle_manager` 本体(产生 origin_time_utc / average_entry_price /
  position_adjustments / current_trim_fraction_completed) — Sprint 1.5b-B
- `tp_target_hit` 接通(读 lifecycle.tp_history)— Sprint 1.5b-B
- `current_trim_completed` 改读累计平仓比例 — Sprint 1.5b-B
- `crossed_first_4h_close_no_reverse` / `survived_pullback_rebound_cycle` — 这两
  字段需要 lifecycle 跟踪开仓后第一个 4H 收盘行为,1.5b-B 接通
- 用户主观干预接入(§11.3)— v1 不做
