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

### Commit 1:报告骨架 ✅
- hash: `ea77c48`
- `docs/cc_reports/sprint_1_10_b.md`(本文件)— 边界 / 决策 / 4 commit 计划

### Commit 2:VirtualAccountManager + 12 单测 ✅
- hash: `964214e`
- `src/strategy/virtual_account.py`(2 函数)
- `tests/test_virtual_account_manager.py`(12 单测全 pass)
- happy: cold_start / long entry / short entry / 多 fill 加权 / 加仓重算
- edge: 异常 direction 跳过 / non-entry 跳过 / 空 history / total_pct
- 收益率算法:closest_at_or_before(target) 找最近 ts ≤ target 的快照对比 latest

### Commit 3:OrdersEngine + 12 单测 ✅
- hash: `bd83fba`
- `src/strategy/orders_engine.py`(163 行,impl 略超 150 行预算 13 行,未拆;同 1.10-A commit 4 风格)
- `tests/test_orders_engine.py`(408 行,12 单测全 pass)
- 12 单测覆盖:多挂单全触发 / 边界等号 / 多 K 线序列 / 已 fill 不重触发 / 过期 / 空 K 线 / non-entry 跳过 / thesis 隔离 / 字典序 tie-break / prev_snapshot 加仓

### Commit 4:verify 脚本 + 1 处精度修 + 报告收尾(本 commit)
- hash: 待 push 后填
- `scripts/verify_orders_engine.py`(端到端 §Z,11 项 SQL 断言)
- **关键发现**:verify 脚本捕到 1 处 OrdersEngine 精度 bug — `round(filled_btc_amount, 8)` 让 compute_snapshot 反推 avg_price 时丢精度(20000 / 0.27027027 = 74000.000074 而非 74000)。**修**:OrdersEngine 不预 round,DAO 直接接全精度 float,SQLite REAL = 64-bit double 不丢精度
- 本报告 4 段总结填完

---

## 部署四件事

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1035 passed, 1 skipped(从 1011 + 24 本 sprint 新增) |
| GitHub push(commit 1-4) | ✅ ea77c48 / 964214e / bd83fba / 待填(commit 4) |
| 服务器 git pull | 待用户(1.10-B 是数据层,可跟 1.10-C 一起部署) |
| 服务器 systemctl restart | **不需要**(本 sprint 0 服务代码改动) |
| 端到端真实断言(§Z) | ✅ scripts/verify_orders_engine.py 本机真 DB 跑通 11/11 项 |
| 生产 DB 迁移 | N/A(本 sprint 0 schema 改动,1.10-A migration 009 已就位) |

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
1035 passed, 1 skipped, 360 warnings in 8.66s
```

本 sprint 新增 24 单测:
- `tests/test_virtual_account_manager.py`:12 单测
- `tests/test_orders_engine.py`:12 单测
全套 1011 → 1035。

## 段 2 用户验证脚本

```bash
cd ~/Projects/btc_swing_system  # Mac 本地或服务器路径

# 1. 跑端到端真实断言(§Z 纪律,会自创建测试数据 + 自清理)
.venv/bin/python scripts/verify_orders_engine.py
# 期望:11 项全 ✅,exit 0,DB 无残留

# 2.(可选)pytest 本 sprint 24 单测
.venv/bin/python -m pytest tests/test_virtual_account_manager.py \
    tests/test_orders_engine.py -v
# 期望:24 passed
```

服务器 DB 路径默认 `data/btc_strategy.db`(可 `scripts/verify_orders_engine.py /path/to/db` 指定)。

## 段 3 同类风险扫描

1. **`compute_snapshot` 不接受 close fills**(stop_loss/take_profit 平仓):本 sprint 只做 entry 加仓,close 流程留 1.10-C ThesisManager。1.10-C 时需要在 compute_snapshot 加新分支处理 close(扣减 long/short_position_usdt + 算 realized_pnl)。
2. **避免预 round float 导致后续派生丢精度**:1.10-B 调试时遇到 `round(filled_btc_amount, 8)` 让 avg_price 反推丢精度的 bug,已删除前置 round。**1.10-C 写 close 流程时同样不要预 round**(SQLite REAL = double precision)。
3. **OrdersEngine 不锁 conn**:并发 check 同一 thesis 可能 race(2 个 process 同时 fill 同一 order)。本 sprint 假设单进程串行(scheduler cron 主流程)。1.10-J cron 串行约束需明确写入 scheduler.yaml 注释。
4. **verify_orders_engine 用固定 thesis_id `verify_orders_engine_test_thesis`**:重复跑会先 cleanup 再 setup(pre-clean),不污染。但**生产 DB 真有同名 thesis 时会被误删**(极不可能,但理论风险)。
5. **`get_klines(start, end)` inclusive**:`last_check_utc` 边界 K 线可能重复触发(若上次没 fill 这次又被取出)。当前用 `WHERE status='pending'` 拦截重复 fill,**生产无破坏**,但语义上 `last_check_utc` 应理解为"≥ 此时间的 K 线"。1.10-C / 1.10-J cron 调度时调用方需稳定推进 last_check_utc。

## 段 4 详细报告路径

`docs/cc_reports/sprint_1_10_b.md`(本文件)。

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无) | — | §X 纪律:本 sprint 0 删除 |

**本 sprint 无替代关系,无删除项**(纯新增 2 模块 + 单测 + 验证脚本)。
