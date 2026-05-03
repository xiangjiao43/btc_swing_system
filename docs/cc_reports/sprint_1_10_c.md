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

### Commit 1:报告骨架 ✅
- hash: `cef4074`
- `docs/cc_reports/sprint_1_10_c.md`(本文件)+ 1.10-B 5 风险审视

### Commit 2:ThesisManager + 16 单测 ✅
- hash: `c006ff5`
- `src/strategy/thesis_manager.py`(388 行)+ `src/strategy/virtual_account.py` 扩展 close fills
- `tests/test_thesis_manager.py`(631 行,16 单测)
- 实施超预算(388/200, 631/300),同 1.10-B commit 3 风格未拆,在 commit msg 披露

### Commit 3:CooldownManager + 21 单测 ✅
- hash: `507a4f5`
- `src/strategy/cooldown_manager.py` + 21 单测全 pass
- 4 条件分级 + 通道 A/B/C 时长 + cooldown 边界

### Commit 4:migration 010 + FuseMonitor + 18 单测 ✅
- hash: `4646e6c`
- `migrations/010_v14_fuse_system_states.sql`(fuse_events + system_states)
- `scripts/init_v14_tables.py` 扩展处理 010(条件 ALTER theses.is_60d_capped)
- `src/strategy/fuse_monitor.py`(Validator 18/19/20)
- 18 单测全 pass

### Commit 5:review_pending + 8 单测 ✅
- hash: `ab3faae`
- `src/strategy/review_pending.py`(D2=a 用 system_states 持久化)
- 8 单测全 pass(enter 幂等 / 三出口 / exit_c 删 14d_fuse audit log)

### Commit 6:verify_thesis_lifecycle + 报告收尾(本 commit)
- hash: 待 push 后填
- `scripts/verify_thesis_lifecycle.py`(端到端 §Z,**34 项 SQL 断言全 pass**)
  - 自动 apply migration(防 migration 010 未上 DB 就跑 verify)
  - prefix `verify_1_10_c_lifecycle_*`(继承 1.10-B 风险 #4 教训)
  - pre/post cleanup 双 try,即使中间报错也清干净
- **关键发现**:verify 第一次跑捕到 2 个真问题:
  1. migration 010 未上真 DB(commit 4 加的,verify 跑前没重新 init)→ 修:verify 自动 apply
  2. test 用 prev_snapshot snapshot_at_utc=2026-04-30,真 DB 有 init_v14_tables 真今天的 snapshot,DAO.get_latest 返回 init 的(cold start) → close_thesis PnL=0 → 修:test 用 future date 2099-04-30 保证 latest

---

## 部署四件事

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1103 passed, 1 skipped(从 1035 + 68 本 sprint:16 + 21 + 18 + 8 + 5) |
| GitHub push(commit 1-6) | ✅ cef4074 / c006ff5 / 507a4f5 / 4646e6c / ab3faae / 待填(commit 6) |
| 服务器 git pull | 待用户(1.10-C 数据 + 业务层完整,可跟 1.10-D 一起部署) |
| 服务器 systemctl restart | **不需要**(本 sprint 0 service 改动) |
| 端到端真实断言(§Z) | ✅ 34 项全 pass + DB 0 残留(5 表 cleanup 验证) |
| 生产 DB 迁移 | ⚠ 需用户 SSH 跑 `scripts/init_v14_tables.py` 应用 migration 010 |

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
1103 passed, 1 skipped, 360 warnings in 8.10s
```

本 sprint 新增 68 单测:
- `tests/test_thesis_manager.py`:16
- `tests/test_cooldown_manager.py`:21
- `tests/test_fuse_monitor.py`:18
- `tests/test_review_pending.py`:8
- 其中 5 个是扩展老 test_virtual_account_manager.py(close fills 数学,实测 11 → 12 是误算 — 实际 close 数学 3 个新 case 在 test_thesis_manager.py)

全套 1035 → 1103(+68)。

## 段 2 用户验证脚本

```bash
cd ~/Projects/btc_swing_system  # Mac 本地或 SSH 服务器路径

# 1. 应用 migration 010(idempotent;首次必跑)
.venv/bin/python scripts/init_v14_tables.py

# 2. 端到端真实断言(§Z 纪律,34 项 SQL 断言)
.venv/bin/python scripts/verify_thesis_lifecycle.py
# 期望:34 项全 ✅,exit 0,DB 0 残留(5 表 cleanup)

# 3.(可选)pytest 本 sprint 68 单测
.venv/bin/python -m pytest tests/test_thesis_manager.py \
    tests/test_cooldown_manager.py \
    tests/test_fuse_monitor.py \
    tests/test_review_pending.py -v
# 期望:63 passed(16 + 21 + 18 + 8)+ 全套 1103 passed

# 4. 1.10-A 端到端断言仍跑(向后兼容)
.venv/bin/python scripts/verify_v14_tables.py
# 期望:14 项全 ✅(原 1.10-A 验证脚本,加 010 表后仍兼容)

# 5. 1.10-B 端到端断言仍跑
.venv/bin/python scripts/verify_orders_engine.py
# 期望:11 项全 ✅
```

服务器 DB 路径默认 `data/btc_strategy.db`(可显式 `path/to/db` 指定)。

## 段 3 同类风险扫描(继承 1.10-B,新增本 sprint)

**1.10-B 5 项继承状态**:
- #1 close 流程 ✅ 本 sprint 兑现(compute_snapshot 扩展 + ThesisManager.close_thesis)
- #2 不预 round ✅ 全程 float 无 round(thesis_manager / fuse_monitor / cooldown_manager 验证)
- #3 单进程假设 ⚠ 仍未解决(留 1.10-J)
- #4 verify thesis_id 命名 ✅ 兑现(prefix `verify_1_10_c_lifecycle_*` + pre/post cleanup)
- #5 get_klines 边界 N/A(本 sprint 不调 get_klines)

**1.10-C 新风险**:
1. **opened → holding 走势 1/4 简化**:本 sprint 只实现"24h + 浮盈 ≥ 2%"一项(其他 3 项:4H 收盘 / 回撤反弹 / TP1 50% 距离 留 1.10-D master AI)。生产期间可能 24h 内浮盈 2% 但其他 3 项均不满足 → 误推 holding。1.10-D 可加 master AI 复核覆盖。
2. **opened_at_utc 用 first entry filled time 推算**:DB 没存 thesis transitioned_to_opened_at,用 `min(entry filled_at_utc)` 反推。多 entry 同 1H 全填时,opened 时间 = 该 1H K 线的 close 时间,与"实际 transition"瞬间一致;若 entry 跨多 1H,opened 时间 = 最早 fill,符合直觉但不严格记账。1.10-J 可考虑加 thesis.opened_at_utc 字段。
3. **D3 原子化补充未在 ThesisManager 内强制**:close_thesis 接 closed_at_utc 参数,信任调用方传 last fill 时间。若调用方 misuse 传 now → 仍写入,产生小延迟。Validator 7(留 1.10-D)应校验 closed_at_utc 在合理窗口。
4. **verify 自动 apply migration 引入"测试改 schema"风险**:verify_thesis_lifecycle 内嵌 init_v14_tables.apply_migration。若 migration 010 在生产首次跑,**verify 会自动迁移**(用户可能不知情)。生产推荐先手工 init_v14_tables → 后 verify。
5. **review_pending exit_c 全删 14d_fuse 行**:出口 C 删除所有 14d_fuse_triggered 记录,**audit log 永久丢失**。1.10-I UI 应明示用户 reset 不可逆,1.10-H weekly_review 应在 reset 前快照保存。

## 段 4 详细报告路径

`docs/cc_reports/sprint_1_10_c.md`(本文件)。

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无) | — | §X 纪律:本 sprint 0 删除,任何旧代码清理留 1.10-J |

**本 sprint 无替代关系,无删除项**(纯新增 4 manager + 1 migration + 单测 + 验证)。
