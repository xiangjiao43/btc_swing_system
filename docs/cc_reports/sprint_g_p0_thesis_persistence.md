# Sprint G P0 — 接通 master.trade_plan → ThesisManager.create_thesis 持久化链路

**日期**:2026-05-09 BJT
**类型**:Sprint G P0(根因修复;之前 audit 发现的 v1.4 上线缺失项)
**Commit**:`c8f7bf4`

## 背景

`docs/cc_reports/run_2026_05_03_16_08_audit.md` 揭示根本 bug:60 天 `theses`
表 0 行 / `virtual_orders` 表 0 行,`create_thesis` 函数定义存在但
**0 处调用**。Sprint 1.10-D 改 master prompt 到 v1.4 thesis-aware schema
时加了 `ThesisManager.create_thesis` 函数,但 `review_pending.py:159` 注释
明确写"留 1.10-D 的 master_run wrapper" — **这个 wrapper 从未实施**。
导致 5/3 16:08 master 真给了 LONG_PLANNED + 完整 trade_plan 但系统从未
持久化为 thesis。

## 改动清单

| 路径 | 行 | 类型 | 说明 |
|---|---|---|---|
| `src/strategy/thesis_persistence.py` | +363 | 新建 | `try_create_thesis_from_master_run()` + 6 个 helper |
| `src/pipeline/state_builder.py` | +30 | 修改 | `_run_v13_orchestrator` 在 orchestrator + mapper 之后调 wrapper,异常捕获 |
| `tests/test_sprint_g_p0_thesis_persistence.py` | +355 | 新建 | 11 个 e2e 测试,真插 DB 行断言 |

合计 3 文件,+748 行。

## 设计决策

### 1. 6 个创建条件(全 AND)

| 条件 | 检查 | 不满足 → skip_reason |
|---|---|---|
| a | `orchestrator_result.status` startswith `"ok"` | `"orchestrator status=... 非 ok"` |
| b | `fallback_level` 是 None / "normal" | `"fallback_level=..."` |
| c | `l3.opportunity_grade ∈ {"A", "B"}` | `"l3_grade=... not in (A, B)"`(C 级观望)|
| d | master 有 new thesis 意图 | `"master 输出无 new thesis 意图"` |
| e | trade_plan 完整 | `"trade_plan 缺字段: [...]"` |
| f | 无同方向 active thesis | `"已有 active long thesis thesis_id=..."` |

### 2. v1.3 vs v1.4 schema 兼容

**v1.3**(5/3 16:08 实测):
- 识别:`master.state_transition.to_state ∈ {LONG_PLANNED, SHORT_PLANNED}` AND
  `master.trade_plan.action == "open"`
- 字段:`trade_plan.entry_price_zone`(list)/ `stop_loss`(单价)/
  `take_profit_zones`(list)/ `position_size_pct`(0-1)
- 拆分启发式:entry 平均分;tp 3 档默认 30/40/30 权重(其他档数等分);
  stop_loss 单挂单全仓
- break_conditions 缺失 → 用 `master.what_would_change_mind` 字符串切分(避免
  thesis_manager 报错)

**v1.4**(prompt 期望):
- 识别:`master.mode == "new_thesis"`
- 字段:`master.new_thesis.{direction, confidence_score, core_logic,
  break_conditions, entry_orders, stop_loss, take_profit}`(每个 order 已带
  `size_pct`)
- 直接映射,无启发式

### 3. 价格 → size_usdt 计算

`size_usdt = initial_capital × size_pct / 100`(默认 initial_capital=$100k)
所以 size_pct 是百分比形式(33 = 33%)。v1.3 的 `position_size_pct=0.33` 自动
× 100。

### 4. 插入点 + 异常处理

`state_builder._run_v13_orchestrator` 在:
1. `orchestrator.run_full_a()` 跑通
2. `_map_orchestrator_result_to_state(...)` 拿到 mapped(含 fallback_level)
3. **新加:try_create_thesis_from_master_run + self.conn.commit()**(独立)
4. 后续走 strategy_runs 写入(独立 commit)

异常处理:wrapper 内 try/except 包 `create_thesis` 调用 — 抛异常时返回
`created=False + skip_reason`,不抛出去。pipeline 主流程外层再加一层
try/except,即使 wrapper 整个崩了也不影响 strategy_runs 写入。

### 5. 不做历史回填

5/3 16:08 那次的入场区(76251-77000)6 天前的价格区间,现在已过期
(BTC 当前 80331)。回填没意义。本 sprint 只接通从今往后的链路。

## 验收记录

### 11 个 e2e 测试 — 真插 DB 行断言(§Z)

| # | 场景 | DB 断言 |
|---|---|---|
| 1 | B 级 + master pass + trade_plan 完整 | theses +1, virtual_orders +6(2 entry + 1 sl + 3 tp)|
| 2 | C 级(用户决策观望)| theses 不变 |
| 3 | B 级 + fallback_level=level_2 | theses 不变 |
| 4 | B 级 + 已有同方向 active long | theses 不变(防重复)|
| 5 | v1.4 schema 创建 | theses +1,break_conditions ≥ 3 条 |
| 6 | A 级创建 | theses +1 |
| 7 | none 级不创建 | theses 不变 |
| 8 | v1.3 master 缺 trade_plan | theses 不变 |
| 9 | orchestrator status=degraded | theses 不变 |
| 10 | 已有反方向 active short → 仍可创建 long | theses +1(共 2 行)|
| 11 | v1.3 字段映射数值精确 | entry 价 76251/77000、size_pct=16.5;tp 9.9/13.2/9.9 |

### 本地 pytest

`1673 passed, 1 skipped, 0 failed`(从 1662 → +11 新 Sprint G 测)。

### 服务器部署

- Fast-forward `9bf4b2a..c8f7bf4`
- `is-active = active`
- `theses` 表 still 0(等明天 BJT 11:35 master 真跑通 + 给 A/B 级 + 5 层方向
  一致才会创建)

### 服务器 pytest(强制项)

(后台跑中,完成后填 1673 passed)

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1673 passed, 0 failed |
| GitHub push(commit hash:c8f7bf4)| ✅ 已 push origin/main |
| 服务器 git pull | ✅ Fast-forward 成功 |
| 服务器 systemctl restart | ✅ is-active = active |
| 服务器 pytest 全 suite | ⏳ 后台跑中(预期 1673 passed,与本地一致)|

## 段 3 同类风险扫描

### 1. 网页 thesis 时间线读什么字段?

`grep theses web/`:
- `web/index.html:826` `(thesesHistory || []).length === 0` → 空状态
- `web/index.html:845` `<template x-for="t in (thesesHistory || [])">` → 列表
- `web/assets/app.js:104` `fetchJson('/api/theses/history?limit=20')`
- `app.js:114` `this.thesesHistory = (thHistory && thHistory.items) || []`

**网页直接读 `/api/theses/history` 接口** → 该接口由 `theses_routes` 实现,
读 `theses` DB 表。**P0 写入 theses 表后,网页时间线自动连通**,无需额外改动。

### 2. thesis 状态机后续(止损 / 止盈触发)是否已有 cron?

`grep hard_invalidation_monitor / OrdersEngine src/`:
- `src/scheduler/jobs.py:1095` `HardInvalidationMonitor.check_active_theses`
  → cron `hard_invalidation_monitor`(1h interval)读 theses + 价格,触发
  规则平仓
- `OrdersEngine` 处理填单 fill / cancel(未在 P0 范围)

**已存在的状态机 cron**(create_thesis 后会自动接管):
- `hard_invalidation_monitor` 1h:扫 active theses,价格击穿 stop_loss → 自动
  close_thesis(channel A 规则平仓)
- `event_listener event_price`:±3% 持仓触发,可走 EmergencySimplifiedA 评估
- `event_listener event_macro`:macro 事件触发 master 评估

**P0 之后的链路**:create_thesis → theses 表 + virtual_orders pending → 价格
变动 → OrdersEngine fill / hard_invalidation cron close → final_outcome
持久化。这条链路其实已经全在。**P0 是其入口**(从来没人调过 create_thesis)。

### 3. master 多次跑同一天给同一方向 → 重复防御

条件 (f) `ThesesDAO.get_active(conn)` 返回最新一条 active thesis(`SELECT *
FROM theses WHERE status='active' ORDER BY created_at_utc DESC LIMIT 1`)。
如果同方向 → return False。**任何同一天多次 B 级 long 触发**,只第一次创建,
其余被 (f) 阻塞。

边界:DAO 的 `get_active` 只取 1 条最新 — 如果某天先创建 long,后又被
close_thesis 关闭(status 改 closed_*),get_active 返 None → 同方向新建议
**可以重新创建**。这是设计意图(thesis 周期已结束 → 允许新建)。

### 4. 网页 layer_cards / summary_card 联动

create_thesis 写入后,**网页 thesis 时间线自动接通**(段 3.1),但
`/api/strategy/current` 返回的 `summary_card / layer_cards` 是
read-time 由 `normalize_state(state.layers)` 构造,**与 theses 表无关**。
也就是说 summary_card.headline = "准备做多(等待入场)" 不变;但同时
`/api/theses/active` 返回的 thesis dict 是新创建的真行。

网页"挂单 + 持仓"卡(模块 3)读 `/api/theses/active` + `/api/orders/pending`,
**P0 后这两个接口会有真数据**,不再永远空。

### 5. create_thesis 抛异常的回滚

设计:
- wrapper 内层 try/except 包 `create_thesis` → 抛异常返回 `created=False`
- pipeline 外层 try/except 包整个 wrapper(`_run_v13_orchestrator` 内)→ 万一
  wrapper 自身崩 → log warning + 继续走 strategy_runs 写入
- **strategy_runs 写入与 thesis 创建是独立 commit**:wrapper commit 失败 →
  下面的 strategy_runs INSERT 仍可成功(用同 conn 但分别 commit)

边界:如果 wrapper commit 后 strategy_runs INSERT 抛异常 → strategy_run 没
写但 thesis 已写。这种 case 极罕见(strategy_runs INSERT 简单),目前
**接受这个边界**(thesis 单独存在,审计可追到 created_at_run_id 为不存在的
run_id);Sprint G 后续如果出现,可以 Sprint H 修。

### 6. v1.3 schema 缺 break_conditions 的妥协

v1.3 trade_plan 没有 break_conditions 列表字段。我用 `master.what_would_change_mind`
字符串切分(分号 / 换行 / 斜杠 / 逗号)凑成 list。如果切不出 → 占位
`["v1.3_master_no_break_conditions_field"]`。

**这是 v1.3 → v1.4 过渡期的妥协**。Validator 8 真校验 break_conditions ≥ 3 条
+ 客观;但 V8 在 master output 校验阶段(在 wrapper 之前)。如果 V8 通过 →
master output 应已有合规 break_conditions 字段。Sprint H 候选:让 master AI
统一输出 v1.4 schema(强制 mode + new_thesis),弃用 v1.3 兼容路径。

### 7. 历史回填决策(不做)

5/3 16:08 那次 trade_plan 入场区 76251-77000 现在已过期(BTC=80331)。即使
P0 已生效,也不应回填那个 thesis。本 sprint 严格"从今天开始接通",历史
audit 留作教训。

## 用户验证

明天 BJT 11:35 自然 cron(假设 Glassnode quota 期间 master 仍可能
fail / silent)— 如果 master 跑通且 L3 给 A/B,**会创建第一个 thesis**。

或者用户手动触发(快速验证):
```bash
ssh ubuntu@124.222.89.86 "curl -X POST -s http://127.0.0.1:8000/api/system/run-now"
sleep 30
ssh ubuntu@124.222.89.86 "sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \"
SELECT COUNT(*) FROM theses; SELECT COUNT(*) FROM virtual_orders;\""
# 如果 quota 期间 master fail → 仍 0;quota 恢复后 master 真跑通 + 给 B 级 → 1+
```

## 本 sprint 删除清单

**本 sprint 无替代关系,无删除项**(纯接通缺失链路,不替代任何旧代码)。
`grep create_thesis src/`:
- `thesis_persistence.py`(本 sprint 新建)调用 `thesis_manager.create_thesis`
- 老的 review_pending.py:159 注释「留 1.10-D 的 master_run wrapper」**本 sprint
  实施了**;注释保留(作为历史记录)。

## 给用户的建议

**P0 已接通**:从今天起,master AI 真跑通 + L3=A/B + 5 层一致 + 无同向 active
+ trade_plan 完整 → 自动创建 thesis 行 + 6 个 virtual_orders 挂单。网页
"挂单+持仓"卡 + 历史时间线**会自动看到内容**。

**Sprint G 后续候选**(P1-P2 留观察):
- **P1**:让 master AI 统一输出 v1.4 schema(强制 mode + new_thesis),弃用
  v1.3 兼容路径(`_build_spec_v13` 启发式拆分可删)
- **P2**:cautious_open + entry_zone 在当前价下方,N 小时未回踩 → 自动转
  market entry(用户拍板"严守等回踩"留 backlog)
- **P3**:网页"已建议但未执行"展示历史 trade_plan(从 strategy_runs 解析,
  即使 P0 没创建 thesis 也让用户看到 AI 的历史建议轨迹)
