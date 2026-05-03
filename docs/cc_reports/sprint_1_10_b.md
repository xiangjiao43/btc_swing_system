# Sprint 1.10-B:虚拟账户管理 + 挂单引擎 + 触发判定

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)
**Sprint 路径定位**:v1.4 §10.5 第二行 — 2 天工作量
**前置 sprint**:1.10-A(三 DAO 已就绪)/ **后置**:1.10-C(thesis lifecycle + 反手通道 + 14 天熔断 + 60 天上限)

---

## Triggers / 决策记录

- 启动确认 D1 = **C** 修正版(用户拍板,推翻 CC 推荐):
  - OrdersEngine 不直接 insert virtual_account
  - `check_and_fill_orders` 返回 `{filled_orders, expired_orders, skipped_orders, computed_snapshot_for_account}`
  - 上层(verify 脚本 / 1.10-C/D 的 master_run)负责 `VirtualAccountDAO.insert_snapshot`
  - **关注点分离**:OrdersEngine 只管挂单触发判定 + 计算快照,virtual_account 写入由上层协调
- 启动确认 D2 = **a**(CC 推荐被接受):
  - OrdersEngine 内部过滤 `order_type='entry'`
  - `mark_expired` 仍兜底所有 order_type
  - 代码注释明确:"stop_loss / take_profit 触发判定留 1.10-C ThesisManager 处理"
- 节奏:**完全放手**模式(用户授权一次性跑完 4 commits)

---

## 任务范围(本 sprint 边界)

### 任务 1:VirtualAccountManager(`src/strategy/virtual_account.py`)

职责(v1.4 §5.1.5):
- 浮盈浮亏计算(unrealized_pnl)
- equity 派生(total_equity)
- 收益率计算(日 / 周 / 月 / 年 / 至今)
- **不调用 DAO 写入**(D1=C:由上层协调)

接口:
- `compute_snapshot(prev_snapshot, current_btc_price, fills_since_last, initial_capital, snapshot_at_utc, snapshot_id, run_id) -> dict`
  返回 16 字段 dict 可直接 `**kwargs` 传 `VirtualAccountDAO.insert_snapshot`
- `compute_returns_history(snapshots: list[dict]) -> dict`
  返回 `{daily_pct, weekly_pct, monthly_pct, yearly_pct, total_pct}`

**严格不做**:不生成挂单(留 1.10-D)/ 不推 thesis lifecycle(留 1.10-C)/ 不调度 cron(留 1.10-J)

### 任务 2:OrdersEngine(`src/strategy/orders_engine.py`)

职责(v1.4 §5.2.3-§5.2.5):
- 取上次检查至今 1H K 线
- pending entry 挂单做 `low ≤ price ≤ high` 穿过判定
- 触发的挂单 → `VirtualOrdersDAO.fill_order`
- 过期挂单 → `mark_expired`(兜底所有 order_type)
- 算 computed_snapshot(via VirtualAccountManager,不写入)

接口:
```python
check_and_fill_orders(
    conn, thesis_id, last_check_utc, now_utc,
    current_btc_price, initial_capital,
) -> {filled_orders, expired_orders, skipped_orders, computed_snapshot_for_account}
```

**3 条硬约束**(§5.2.4 + §5.2.5):
1. 入场价 = 挂单价(`filled_price = order.price`,不是 K 线 close / high / low)
2. 同 1H 多挂单全触发(low ≤ price ≤ high 任一满足都触发)
3. BTC 数量 = `size_usdt / filled_price`

**触发顺序**:K 线 ASC(早 K 线先)+ 同 1H 内 order_id 字典序(确定性 tie-break)

**严格不做**:thesis lifecycle 推进 / master AI 调用 / stop_loss-take_profit 触发(全留后续 sprint)

### 任务 3:单元测试

- `tests/test_virtual_account_manager.py`(8-10 单测)
- `tests/test_orders_engine.py`(10-12 单测)
- in-memory SQLite,不污染真实 DB

### 任务 4:集成验证脚本

`scripts/verify_orders_engine.py`(端到端 §Z):
- 创建测试 thesis + 3 entry 挂单(74000 / 70000 / 66000)
- 模拟 1H K 线 high=78000, low=73000 → 仅 74000 穿过
- 调 OrdersEngine.check_and_fill_orders
- SQL 断言 + insert computed_snapshot + 验证字段
- 清理:删测试 thesis / orders / 多余快照

---

## 实施记录(commit-by-commit 实时填)

### Commit 1:报告骨架(本 commit)
- hash: 待 push 后填
- `docs/cc_reports/sprint_1_10_b.md`(本文件)— 边界 / 决策 / 4 commit 计划

### Commit 2:VirtualAccountManager + 单测(待执行)
预计:`src/strategy/virtual_account.py` + `tests/test_virtual_account_manager.py`

### Commit 3:OrdersEngine + 单测(待执行)
预计:`src/strategy/orders_engine.py` + `tests/test_orders_engine.py`
若超 150/250 行 → 拆 3a / 3b

### Commit 4:verify 脚本 + 报告收尾(待执行)
预计:`scripts/verify_orders_engine.py` + 本报告 4 段总结

---

## 部署四件事 / 测试记录(commit-by-commit 实时填)

待 commit 4 完成填。

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无) | — | §X 纪律:本 sprint 0 删除 |

**本 sprint 无替代关系,无删除项**(纯新增 2 模块 + 单测 + 验证脚本)。
