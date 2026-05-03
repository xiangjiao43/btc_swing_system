# Sprint 1.10-G:事件触发 + 硬失效位 cron + RetryPolicy 异步调度

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)§3.3.8 + §6.2.3 + §10.4.1 + §10.4.3
**Sprint 路径定位**:v1.4 §10.5 第七行 — 2 天工作量
**前置 sprint**:1.10-A → 1.10-F 全部完成(HEAD 在 cba1ee6)

---

## Triggers / 决策记录

### 启动确认 4 个 D 用户拍板

- **D1 = b**:baseline_price 取上次任一 `strategy_runs.btc_price_usd`(改造 2.7-D 现有 24h 滚动)。
  对齐 v1.4 §6.2.3 节流"距上次主 AI 介入 < 30min 跳过"暗示的决策窗口语义。
  用户已知是行为变化,接受;1.10-L 真 API 验证暴露问题(若有)。
- **D2 = b**:`event_throttle` 表加 `event_class` 字段(`event_price` / `event_invalidation`),两类独立计数。
  关键安全论证:event_invalidation 是规则平仓保护资金,不能被 event_price 节流挡住,否则 thesis 击穿了但等 2h 才平仓 = 灾难。
- **D3 = a**:APScheduler one-shot 扩展现有 `_enqueue_pipeline_run` 加 `attempt` 参数。
  失败时 `delay_sec = RetryPolicy.compute_backoff_seconds(attempt)` → `is_within_window` → 自调度 / 否则放弃 + critical 告警。
- **D4 = b1**:HardInvalidationMonitor 调 `ThesisManager.close_thesis(reason="stop_loss_filled", close_channel="A")` 复用现有 reason,
  retry_log_json 标记 `event_invalidation_triggered=True` 区分场景。不新增 reason,不改 `_REASON_TO_OUTCOME` 表。

### 节奏

完全放手模式(用户授权一次性跑完 6 commits;commit 5 若超 500 行自动拆 5a/5b)。

---

## §X 删除 / 替换清单(commit 1 declare,commits 2-5 实施)

| # | 删除 / 替换对象 | 路径 | 实施 commit | 验证方式 |
|---|---|---|---|---|
| 1 | `_PRICE_CHANGE_THRESHOLD = 0.03` 单一硬编码 | `src/scheduler/event_listener.py:35` | commit 5 | 改读 `base.yaml::event_trigger`,EventTrigger 双轨决定 |
| 2 | `_check_event_invalidation` 触发后只 enqueue pipeline_run | `src/scheduler/event_listener.py:108` | commit 5 | 改 1h 独立 cron(scheduler.yaml::hard_invalidation_monitor)直接调 HardInvalidationMonitor 规则平仓 |
| 3 | `runtime.scheduled.cron_hours_utc: [0,4,8,12,16,20]` | `config/base.yaml` | **commit 1 ✅** | scheduler.yaml::pipeline_run_regular 是真权威源(v1.4 §10.4.2 明确删除) |
| 4 | `runtime.event_driven.throttle` 段 | `config/base.yaml` | **commit 1 ✅** | 迁移到 `event_trigger` 段(单一配置源) |

**0 引用核查**(commit 1 前已验证):
- `git grep "cron_hours_utc"` → 0 hit(无 consumer)
- `git grep "runtime.event_driven\|runtime.scheduled"` → 0 hit(全 declare-only)
- `git grep "_PRICE_CHANGE_THRESHOLD"` → 1 hit(自身定义,commit 5 替换)

---

## 调研 — 现状对照

### 已存在(Sprint 2.7-D 实施)

| 项 | 文件:行 | v1.4 兼容性 |
|---|---|---|
| `event_listener._check_event_invalidation` | `src/scheduler/event_listener.py:108` | ⚠ 触发后只 enqueue pipeline_run,§6.2.3 期望规则平仓(commit 5 改) |
| `event_listener._check_event_price` | `src/scheduler/event_listener.py:192` | ⚠ 单一 ±3% + 24h 滚动 baseline,期望双轨 + 上次 run baseline(commit 5 改) |
| `event_throttle` 表 + `_is_throttled` / `_record_trigger` | `src/scheduler/event_listener.py:67/88` | ⚠ 表无 event_class 字段(D2=b 加列) |
| scheduler.yaml::event_listener 60s | `config/scheduler.yaml` | ✅ 保留,作为 event_price 主入口 |
| `OrdersEngine.check_and_fill_orders` | `src/strategy/orders_engine.py:37` | ✅ HardInvalidationMonitor 可直调 |
| `ThesisManager.close_thesis(reason, close_channel, ...)` | `src/strategy/thesis_manager.py:305` | ✅ D4=b1 复用 stop_loss_filled reason |
| `CooldownManager._REASON_TO_DEFAULT_CHANNEL["stop_loss_filled"] = "A"` | `src/strategy/cooldown_manager.py:36` | ✅ D4=b1 一致 |

### v1.4 期望但缺失

- ❌ EventTrigger 双轨判定器(commit 2 新建)
- ❌ HardInvalidationMonitor 规则平仓(commit 3 新建)
- ❌ EmergencySimplifiedA AI agent(commit 4 新建)
- ❌ scheduler.yaml::hard_invalidation_monitor 1h cron + position_health_check 4h cron(commit 5 加)
- ❌ RetryPolicy 真异步接通(commit 5 接 _enqueue_pipeline_run)
- ❌ `orchestrator.run_event_a` 入口(commit 5 加)
- ❌ `event_throttle` 表 `event_class` 字段(commit 2/3 视谁先用)

### v1.4 §11.3 路径错误清单(继承 1.10-D/E/F,1.10-J 修)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |
| 3 | (本 sprint 无新增) | — | — |

---

## 任务 1-7 实施记录(commit-by-commit 实时填)

### Commit 1:报告骨架 + 调研 + base.yaml event_trigger 段 + §X 清单 declare(本 commit)
- hash: 待 push 后填
- `docs/cc_reports/sprint_1_10_g.md`(本文件)
- `config/base.yaml`:
  - 加 `event_trigger` 段(price_pct_flat 0.05 / price_pct_holding 0.03 / event_cooldown_seconds 7200 / skip_if_recent_scheduled_seconds 1800)
  - 删 `runtime.scheduled.cron_hours_utc` + `cron_timezone`(§X #3)
  - 删 `runtime.event_driven.throttle` 整段(§X #4,迁到 event_trigger)
  - 注释明确指明 scheduler.yaml 是真权威源

### Commits 2-6:待执行

---

## 部署四件事 / 测试记录(commit 6 末尾填)

待 commit 6 完成。

## 本 sprint 删除清单(commit 6 末尾汇总)

见上方 §X 清单,commit-by-commit 实施情况待 commit 6 汇总。
