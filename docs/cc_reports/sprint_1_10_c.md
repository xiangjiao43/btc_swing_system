# Sprint 1.10-C:thesis 生命周期 + 反手 3 档通道 + 14 天熔断 + 60 天上限

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)
**Sprint 路径定位**:v1.4 §10.5 第三行 — 2.5 天工作量
**前置 sprint**:1.10-A(三 DAO)+ 1.10-B(VirtualAccountManager + OrdersEngine)
**后置 sprint**:1.10-D(master AI thesis-aware)

---

## Triggers / 决策记录

### 启动确认 4 个 D 用户拍板

- **D1 = b**:新增 `fuse_events` 表(独立 schema,FuseMonitor 高频查询用)
- **D2 = a**:新增 `system_states` 表(review_pending 等持久状态)
- **D3 = a + 原子化补充**:`closed_at_utc` 用 last fill 的 `filled_at_utc`(物理准确);**fill 触发后立刻调 close_thesis,中间不持久化 phantom 状态**(OrdersEngine fill 后,调用方在同一调用栈内立刻调 ThesisManager.close_thesis)
- **D4 = b + 显式字段**:`theses.is_60d_capped INTEGER DEFAULT 0`(不复用 last_assessment_note,语义保留 AI 输出);60d-capped thesis 仍能被 OrdersEngine 触发挂单走自然平仓 → 通道 A

### 1.10-B 5 项风险对本 sprint 的影响

| 1.10-B 风险 | 对 1.10-C 的影响 | 本 sprint 处理 |
|---|---|---|
| #1 close 流程留 1.10-C | **必做** — `compute_snapshot` 1.10-B 只跳过 non-entry,本 sprint 扩展处理 close fills(stop_loss / take_profit 扣减 position + 算 realized_pnl) | commit 2 ThesisManager.close_thesis + 扩展 compute_snapshot |
| #2 不预 round float | **直接继承** — close 流程数学全程 float,SQLite REAL = 64-bit double | 本 sprint 编码自检 |
| #3 单进程假设 | **不解决**(1.10-J) | 注释明示 |
| #4 verify thesis_id 命名 | **本 sprint 兑现** | commit 6 用 prefix `verify_1_10_c_lifecycle_*` + pre/post cleanup |
| #5 get_klines 边界 | **不直接影响** — ThesisManager 接 fills list,不直接调 get_klines | docstring 写明 |

### 节奏

完全放手模式(用户授权一次性跑完 6 commits)。

---

## 任务范围(本 sprint 边界)

### 任务 1:ThesisManager(`src/strategy/thesis_manager.py`)
- `create_thesis(thesis_spec, run_id, now_utc)` — DB write theses + 对应 entry/sl/tp 挂单
- `advance_lifecycle(thesis_id, fills, prev_snapshot, current_btc_price, now_utc)` — 5 档迁移
- `close_thesis(thesis_id, reason, close_channel, closed_at_utc, fills_for_close, ...)` — 关闭 + cancel 残余挂单
- `check_60d_cap(thesis_id, now_utc)` + `mark_60d_capped(thesis_id)`
- 扩展 `compute_snapshot`(virtual_account.py)接受 close fills

### 任务 2:CooldownManager(`src/strategy/cooldown_manager.py`)
- `determine_close_channel(close_reason, l1_regime_change, l2_stance_change, l5_signals)` — A/B/C 4 条件分级
- `compute_cooldown_end(closed_at_utc, channel)` — A=72h / B=24h / C=0h
- `is_in_cooldown(now_utc, latest_closed_thesis)` — 判定 + 剩余时长

### 任务 3:FuseMonitor(`src/strategy/fuse_monitor.py`)— 含 DB 改动
- migration 010:`fuse_events` + `system_states` + `theses.is_60d_capped`
- `record_thesis_cycle(thesis_id, closed_at_utc)` / `record_channel_c_use(thesis_id, used_at_utc)`
- `check_14d_fuse(now_utc)` — Validator 18(双触发)
- `check_60d_cap(thesis_id, now_utc)` — Validator 19
- `check_consecutive_fuse()` — Validator 20

### 任务 4:review_pending(`src/strategy/review_pending.py`)
- `enter_review_pending(reason, related_thesis_id)` — system_states INSERT
- `exit_a()` / `exit_b(new_thesis_spec)` / `exit_c()` — 3 出口
- `is_in_review_pending()` 查询

### 任务 5:单元测试 — 4 个 test 文件,合计 38-48 单测

### 任务 6:`scripts/verify_thesis_lifecycle.py` — 端到端 §Z(15-20 SQL 断言)

---

## 实施记录(commit-by-commit 实时填)

### Commit 1:报告骨架(本 commit)
- hash: 待 push 后填
- `docs/cc_reports/sprint_1_10_c.md`(本文件)

### Commit 2:ThesisManager + 单测(待执行)
预计:`src/strategy/thesis_manager.py` + `src/strategy/virtual_account.py`(扩展 close fills)+ `tests/test_thesis_manager.py`
若超 200/300 行 → 拆 2a/2b

### Commit 3:CooldownManager + 单测(待执行)

### Commit 4:migration 010 + FuseMonitor + 单测(待执行)
schema 改动统一在此 commit,避免 migration 分散

### Commit 5:review_pending + 单测(待执行)

### Commit 6:verify 脚本 + 报告收尾(待执行)

---

## 部署四件事 / 测试记录(commit-by-commit 实时填)

待 commit 6 完成填。

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无) | — | §X 纪律:本 sprint 0 删除,任何旧代码清理留 1.10-J |

**本 sprint 无替代关系,无删除项**(纯新增 4 manager + 1 migration + 单测 + 验证)。
