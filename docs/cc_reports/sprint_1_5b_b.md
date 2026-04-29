# Sprint 1.5b-B — lifecycle_manager 本体

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,19 个新测试 + 732/732 全量回归过

---

## 一、问题与决策

**Bug**:Sprint 1.5b-A 完成后,state_machine 14 状态机已能用真实输入正常迁移,
但 `state_builder.py` 仍写死占位 `state["lifecycle"] = {"current_lifecycle":
"pending_lifecycle_manager", "managed_by": "sprint_1_5b_pending"}`。
意味着系统不知道入场价、持仓时长、浮盈、TP 哪档触发了。

**用户决策**:实施 lifecycle_manager 本体,采用**两阶段**架构,
同时把 1.5b-A 留的 lifecycle 依赖 TODO 字段(`floating_pnl_pct` /
`hours_since_open` / `tp_target_hit` / `current_trim_completed`)接通。

---

## 二、改动

### 2.1 新建 `src/strategy/lifecycle_manager.py`

`class LifecycleManager` 两个公开入口:

```python
def compute_pre_sm(*, prev_state, prev_lifecycle, strategy_state, context, now_utc) -> dict | None
def compute_post_sm(*, prev_state, current_state, lifecycle, strategy_state, context,
                    run_id, now_utc) -> dict | None
```

**`compute_pre_sm`**(在 state_machine 之前跑):
- 仅当 `prev_lifecycle.status in {pending_open, active}` 时更新
- 计算 `hours_held`(now - origin_time_utc)
- 计算 `current_floating_pnl_pct`(基于最新 1H close + average_entry_price + direction)
- 维护 `max_favorable_pct`(单调增)/ `max_adverse_pct`(单调减)
- TP hit 检测:扫 `trade_plan.take_profit_plan`,1D high/low 命中且未在 `tp_history` 的
  追加新条目,设 `tp_target_hit_this_run=True/False`
- 推断 `open_phase_*` 4 个 bool 锁(min_time / pnl_confirmed / structure / pullback_survived)
- 同步 `crossed_first_4h_close_no_reverse` / `survived_pullback_rebound_cycle`
  别名(state_machine.py 已读这两个字段)
- v1 简化的 `current_trim_completed`:进入 *_TRIM 后 24h + 有 trim 记录

**`compute_post_sm`**(在 state_machine 之后跑):
- `FLAT → *_PLANNED`:创建 `pending_open` 草稿,`origin_thesis` 截 adjudicator.narrative
  前 500 字符(不可变)
- `*_PLANNED → *_OPEN`:激活,计算 `average_entry_price` = entry_zones[0] 中点,
  `position_adjustments` 追加 `open` 记录(100% 入场)
- `*_OPEN → *_HOLD`:`stage="holding"` 锁定 4 个 open_phase bool
- `*_HOLD → *_TRIM`:`stage="partial_trimmed"`,追加 `trim` 记录(size_pct 从下一档 TP 读)
- `*_TRIM → *_HOLD`:`stage="holding"`,reset `current_trim_completed`
- `*_(HOLD/TRIM/OPEN) → *_EXIT`:`stage="preparing_exit"`,追加 `exit` 记录
- `*_EXIT → FLAT/FLIP_WATCH`:归档(`status="closed"`,`exit_time_utc=now`,
  `realized_pnl_pct = current_floating_pnl_pct`,`final_outcome_type` 推断)
- `PROTECTION` / `POST_PROTECTION_REASSESS`:保留 lc,`protection_active` 标记/复位
- `*_PLANNED → FLAT`:草稿丢弃返回 None

**`final_outcome_type` v1 4 类**:
- `A_perfect`(realized ≥ 5%)
- `B_good_suboptimal`(1% ~ 5%)
- `F_wrong_but_stopped`(-3% ~ 1%)
- `G_wrong_late_stop`(< -3%)

建模 §8.3 完整 10+ 类留 v1.x 复盘工具细化。

### 2.2 wiring `src/pipeline/state_builder.py`

- `__init__` 新增 `self._lifecycle_manager = LifecycleManager()`
- 替换占位代码块为两阶段 stage:
  ```
  Stage: lifecycle_pre_sm  ← state_machine_inputs 在 state_machine 内部读
  Stage: state_machine
  Stage: lifecycle_post_sm ← 状态过渡副作用
  ```
- 新 `_read_previous_lifecycle()`:DAO 读最新 row 的 `state.lifecycle`,
  legacy 占位(`managed_by="sprint_1_5b_pending"`)视为无 lc
- 删除原 `state["lifecycle"] = {"current_lifecycle": "pending_lifecycle_manager", ...}`(§X)

### 2.3 接通 1.5b-A 留的 TODO

`src/strategy/state_machine_inputs.py::build_state_machine_fields` 改为优先读
LifecycleManager 写入的字段:

| state_machine 字段 | 优先源 | fallback |
|---|---|---|
| `hours_since_open` | `lifecycle.hours_held` | `_hours_since_open(lifecycle, now)` 自算 |
| `floating_pnl_pct` | `lifecycle.current_floating_pnl_pct` | `_floating_pnl_pct(...)` 自算 |
| `tp_target_hit` | `lifecycle.tp_target_hit_this_run` | False |
| `next_trim_triggered` | 同上(TP hit 真实命中即设) | klines 自检 |
| `current_trim_completed` | `lifecycle.current_trim_completed` | `hours_since_open >= 24` 自算 |

---

## 三、测试

`tests/test_lifecycle_manager.py`(19 测试):

| 类别 | 测试 |
|---|---|
| pre_sm 无活跃 lc | None / closed → None |
| pre_sm 度量更新 | 24h hold + +3% PnL + max_favorable/max_adverse 单调 |
| pre_sm TP hit | 1D high 触达 → tp_history 追加 + tp_target_hit_this_run=True |
| pre_sm TP 不重复 | 已 history 的 tp_id → 不重复追加 |
| post_sm 创建草稿 | FLAT → LONG_PLANNED:status=pending_open,origin_thesis 截 narrative |
| post_sm 激活 | LONG_PLANNED → LONG_OPEN:avg_entry=区间中点,position_adjustments 追加 open |
| post_sm 各过渡 | OPEN → HOLD / HOLD → TRIM(追加 trim 记录)/ EXIT → FLAT(归档)|
| post_sm outcome | A/B/F/G 4 类边界 |
| post_sm 草稿丢弃 | LONG_PLANNED → FLAT → None |
| post_sm 保护期 | PROTECTION → protection_active=True / POST_PROTECTION_REASSESS → stage=reassess |
| **集成** | `test_state_builder_replaces_placeholder_with_real_lifecycle`:真跑 builder.run + 真 SQLite,断言 DB 持久化的 lifecycle 不再含 `managed_by="sprint_1_5b_pending"` |
| **集成** | `test_state_machine_inputs_reads_lifecycle_pnl`:LifecycleManager.pre_sm 写的 PnL → state_machine_inputs 读到 |

**回归**:全量 `pytest tests/` = **732 passed, 1 skipped, 4.56s**(713 + 19 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 跑一次 pipeline 看 lifecycle 不再是占位
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(
    'SELECT full_state_json FROM strategy_runs '
    'ORDER BY reference_timestamp_utc DESC LIMIT 1'
).fetchone()
state = json.loads(row[0])
life = state.get('lifecycle')
sm = state.get('state_machine', {}).get('current_state')
print('state_machine.current_state:', sm)
print('lifecycle keys:', list(life.keys()) if isinstance(life, dict) else life)
print('lifecycle.status:', (life or {}).get('status'))
"
# 预期:
# - state_machine.current_state: FLAT(stable / 当前 stance=neutral)
# - lifecycle keys: []  (FLAT 期空 dict,不再含 managed_by/pending_lifecycle_manager)
# - 若已进 PLANNED+,会有完整 dict(status / direction / origin_thesis 等)
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除)
- `state_builder.py` 占位代码块 `{"current_lifecycle": "pending_lifecycle_manager",
  "managed_by": "sprint_1_5b_pending"}` 已完整删除,不允许新旧并存
- 1.5b-A 留的 TODO 字段(`hours_since_open` / `floating_pnl_pct` / `tp_target_hit` /
  `current_trim_completed`)全部接通真实 lifecycle 数据(优先级);自算 fallback 仅
  在 lifecycle 缺字段时用,不并存
- `_read_previous_lifecycle` 把 legacy 占位识别为"无 lc",生产升级时不会被旧数据干扰

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 19 个测试全部用真 pandas DataFrame klines + 真 strategy_state dict
- 集成测试 `test_state_builder_replaces_placeholder_with_real_lifecycle` 真跑
  `StrategyStateBuilder.run()`,真 SQLite + 真 schema + 真 persist,断言
  `full_state_json.lifecycle` 不再含 `managed_by` 字段
- TP hit 测试用真实 take_profit_plan list + 1D OHLC DataFrame

### 同类风险扫描
1. **冷启动 prev_lifecycle=None** — `compute_pre_sm` 返回 None,`state["lifecycle"]={}`,
   build_state_machine_fields 走 fallback 路径,行为等同 1.5b-A
2. **生产升级时遇到 legacy 占位 lc** — `_read_previous_lifecycle` 判 `managed_by` 后
   返回 None,LifecycleManager 视为无活跃 lc 重新走流程
3. **`average_entry_price` 取 entry_zones[0] 中点** — 加仓 / 多档 entry 留 v1.x 改进。
   v1 假定一次性入场,position_adjustments[0].size=100%
4. **`tp_history` 重复检测靠 tp_id** — 用户 trade_plan 没显式给 tp_id 时回退
   `f"tp{idx+1}"`(idx 是 list 位置),稳定性 OK
5. **`final_outcome_type` 简化 4 类** — 用户复盘只能看到这 4 类粒度,建模 §8.3
   的 10+ 类(C/D/E/H/I/J/X)需要更细的 trim_history / structure_log 数据,留
   v1.x 复盘工具细化
6. **lifecycles 表落库** — 本 sprint 只写 `strategy_runs.full_state_json.lifecycle`;
   `/api/lifecycle/*` 改造留 1.5b-C(归档查询时再启用)

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/strategy/lifecycle_manager.py` | 新模块,`LifecycleManager` class + 两阶段入口 |
| `src/pipeline/state_builder.py` | __init__ 实例化 + 两阶段 stage + `_read_previous_lifecycle` + 删占位 |
| `src/strategy/state_machine_inputs.py` | 优先读 lifecycle 写入的字段(hours_held / current_floating_pnl_pct / tp_target_hit_this_run / current_trim_completed) |
| `tests/test_lifecycle_manager.py` | 新文件 19 测试 |

---

## 七、未覆盖项 / 后续 sprint 接入

- **lifecycles 表归档查询 API**(`/api/lifecycle/history`) — Sprint 1.5b-C
- **加仓加权 average_entry_price** — v1.x(目前一次性入场)
- **`final_outcome_type` 完整 10+ 类** — v1.x 复盘工具
- **structure_log / pullback_log** 用于 `crossed_first_4h_close_no_reverse` /
  `survived_pullback_rebound_cycle` 的精确判断 — v1.x(目前用 v1 简化:
  hours_held >= 4 / max_adverse <= -1% + max_favorable >= 2%)
- **用户主观干预 v1.3 接入(§11.3)**
