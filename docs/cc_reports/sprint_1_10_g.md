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

### Commit 2:EventTrigger 双轨 + migration 013 + 40 单测
- hash: `b123e2d`
- `migrations/013_v14_event_throttle_class.sql` audit trail
- `scripts/init_v14_tables.py` 加 `_MIGRATION_013` + 条件 ALTER `event_throttle.event_class`
- `src/data/storage/schema.sql` 加 `event_class TEXT`(NULL 兼容老数据)
- `src/strategy/event_trigger.py`(NEW):
  - `EventTriggerConfig` dataclass + `from_dict` 读 base.yaml
  - `is_holding_state(state)` 14 档持仓判定(LONG/SHORT_OPEN/HOLD/TRIM)
  - `EventTrigger.should_trigger_event_price()` 纯 stateless 双轨判定
  - `record_event` / `get_last_event_at` / `get_last_main_run_at` /
    `get_baseline_price`(D1=b 从 strategy_runs 读 btc_price_usd)
- `tests/test_event_trigger.py`(40 单测)

### Commit 3:HardInvalidationMonitor 规则平仓 + 13 单测
- hash: `186915a`
- `src/strategy/hard_invalidation_monitor.py`(NEW):
  - `check_active_theses(conn, current_btc_price, now_utc)` 击穿判定
  - `execute_invalidation(...)` 调 `VirtualOrdersDAO.fill_order` +
    `thesis_manager.close_thesis(reason="stop_loss_filled", channel="A")`(D4=b1)
  - `retry_log_marker` 5 字段(event_invalidation_triggered=True 等)
  - `get_latest_btc_price(conn)` 1h K 线 helper
- 设计纪律:**不调 AI**(monkeypatch build_anthropic_client 抛异常验证)
- `tests/test_hard_invalidation_monitor.py`(13 单测,含 §6.2.3 硬约束验证)

### Commit 4:EmergencySimplifiedA agent + system prompt + 22 单测
- hash: `fe9ad10`
- `src/ai/agents/emergency_simplified_a.py`(NEW):
  - `class EmergencySimplifiedA(BaseAgent)` 继承 BaseAgent(prompt 加载 + AI 调用 + JSON 解析 + fallback)
  - `VALID_ACTIONS` = ("maintain", "emergency_exit", "tighten_stop", "wait_next_full")
  - `_fallback_output`: 失败时 maintain(最安全,等下次完整 run)
  - `normalize_output`: 非法 action 改 maintain + notes 标记
- `src/ai/agents/prompts/emergency_simplified_a.txt`(NEW)5-6 段 system prompt
- `tests/test_emergency_simplified_a.py`(22 单测,全 mock)

### Commit 5a:scheduler.yaml + 2 新 cron + RetryPolicy 异步接通 + 12 单测
- hash: `3d7c288`
- `config/scheduler.yaml`:加 `hard_invalidation_monitor` 1h + `position_health_check` 4h
- `src/scheduler/jobs.py`:
  - `_enqueue_pipeline_run` 加 `attempt` + `retry_start_utc` 参数
  - 新 `job_pipeline_run_with_retry` wrapper(D3=a 接通 RetryPolicy)
  - 新 `job_hard_invalidation_monitor`(无 AI,§6.2.3 硬约束)
  - 新 `job_position_health_check` stub(本 sprint 不调 AI;真 AI 留 1.10-H)
  - `_JOB_FUNCTIONS` 注册 3 entry
- `tests/test_jobs_retry.py`(NEW,12 单测)
- `tests/test_scheduler_2_7_a_cron.py`(adapter):8→10 entries / expected_7→expected_9 / interval_jobs 集合扩展

### Commit 5b:orchestrator.run_event_a + event_listener §X 改造 + 23 单测
- hash: `29f863d`
- `src/ai/orchestrator.py`:
  - 加 `EmergencySimplifiedA` 到 self._agents
  - 新 `run_event_a()` 入口走单 AI(不跑完整 6 AI)
- `src/scheduler/event_listener.py`(§X 大改造,3 类 → 2 类):
  - 删 `_check_event_invalidation`(移到 1h cron)
  - 删 `_is_throttled` / `_record_trigger`(替代 EventTrigger.{record,get_last})
  - 删 `_PRICE_CHANGE_THRESHOLD = 0.03` 单一硬编码 / `_PRICE_RECENT_RUN_THROTTLE_SEC` /
    `_THROTTLE_DEFAULT_SEC`(读 base.yaml::event_trigger 双轨配置)
  - 新 `_check_event_price` 用 EventTrigger:baseline 改 strategy_runs.btc_price_usd /
    双轨阈值(_get_current_state 决定 5%/3%)/ EventTrigger 内置节流
- `tests/test_event_listener.py` 完全重写(16 单测)
- `tests/ai/test_orchestrator_event_a.py`(NEW,7 单测)

### Commit 6:verify_event_trigger.py(36 §Z)+ 报告 + checklists(本 commit)
- hash: 待 push 后填
- `scripts/verify_event_trigger.py` — 7 段共 36 项 §Z 真实断言:
  - A. base.yaml event_trigger 配置 + §X #3/#4 已删验证(6)
  - B. EventTrigger 双轨判定(5)
  - C. event_throttle 双类独立 + migration 013(3)
  - D. HardInvalidationMonitor 规则平仓 + D4=b1 标记(9)
  - E. EmergencySimplifiedA + orchestrator.run_event_a(4)
  - F. scheduler 2 新 cron + RetryPolicy 异步接通(7)
  - G. check_and_trigger_events §X 改造 3→2 类(2)

---

## 部署四件事 / 测试记录

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1325 passed (+90 vs 1.10-F), 1 skipped, 0 regression |
| GitHub push(commit hash) | ✅ commits 1-5b 已推:29f863d / 3d7c288 / fe9ad10 / 186915a / b123e2d / 820fb66;commit 6 本次 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行(2 个新 cron 需 scheduler 重启注册) |
| 生产 DB migration 013 | 待用户执行 — `.venv/bin/python scripts/init_v14_tables.py /path/to/prod/btc_strategy.db`(幂等,只 ALTER 加 event_throttle.event_class 列) |

### §Z verify 真实运行结果

```
$ .venv/bin/python scripts/verify_event_trigger.py
通过:36 项
失败:0 项
✅ 全部通过
```

### 单元测试矩阵

| 测试文件 | 单测数 | 覆盖 |
|---|---|---|
| `tests/test_event_trigger.py` | 40 | commit 2 EventTrigger 双轨 + 节流 + DB helpers |
| `tests/test_hard_invalidation_monitor.py` | 13 | commit 3 规则平仓 + retry_log_marker + 不调 AI 验证 |
| `tests/test_emergency_simplified_a.py` | 22 | commit 4 简化 A + 4 取值 + fallback + normalize |
| `tests/test_jobs_retry.py` | 12 | commit 5a RetryPolicy 异步 + 2 新 cron job |
| `tests/test_event_listener.py`(重写) | 16 | commit 5b §X 改造后双轨 + macro |
| `tests/ai/test_orchestrator_event_a.py` | 7 | commit 5b run_event_a 入口 |
| `tests/test_scheduler_2_7_a_cron.py`(adapter) | (4 改) | commit 5a 8→10 entries / expected_7→9 |
| **小计** | **110** + 4 改 | 1.10-G 全覆盖 |

---

## 未覆盖 / 留 1.10-H/L 处理

### 1.10-H 留处理(Weekly Review AI + position_health_check 真 AI)

- `position_health_check` 4h cron 本 sprint 是 stub(无 thesis 直接返;有 thesis 仅 log)
- 1.10-H 实施 weekly_review_analyst(每周日 22:00 BJT,§3.3.9)+ position_health_check 真 AI 调用
- 当前已铺好 framework:scheduler.yaml::position_health_check 已注册,jobs.py::job_position_health_check stub 待替换

### 1.10-L 留处理(真 API 验证)

- 6 + 1 AI 全部 mock 测试,真 API 行为(网络抖动 / parse 错 / token 限流)未覆盖
- EmergencySimplifiedA system prompt 真实输出质量待真 master AI 验证(reasoning 长度 / immediate_action 选取准确率)
- D1=b 改造的 baseline 行为(从 24h 滚动 → 上次 strategy_run)在真生产数据下的事件触发频率需 1 周观测
- D2=b event_class 字段当前为 declare-only(SQL 不查),未来如分 event_price_flat / event_price_holding 可基于此分类聚合

### 1.10-J 留处理(v1.4 §11.3 路径错误清单)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |
| 3 | (本 sprint 无新增) | — | — |

---

## 本 sprint 删除清单

| # | 删除对象 | 路径 / 位置 | 删除原因 / 验证 |
|---|---|---|---|
| 1 | `_PRICE_CHANGE_THRESHOLD = 0.03` 单一硬编码 | `src/scheduler/event_listener.py`(原 line 35) | commit 5b 删,改读 `base.yaml::event_trigger` 双轨;`git grep _PRICE_CHANGE_THRESHOLD` → 0 |
| 2 | `_check_event_invalidation` 整段函数 | `src/scheduler/event_listener.py`(原 line 108) | commit 5b 删,迁到 1h cron `HardInvalidationMonitor`;`git grep _check_event_invalidation` → 0 |
| 3 | `_is_throttled` / `_record_trigger` helper | `src/scheduler/event_listener.py`(原 line 67/88) | commit 5b 删,替代 `EventTrigger.{record_event, get_last_event_at}`;src/ 内 `git grep _is_throttled` → 0 |
| 4 | `_THROTTLE_DEFAULT_SEC` / `_PRICE_RECENT_RUN_THROTTLE_SEC` 硬编码常量 | `src/scheduler/event_listener.py`(原 line 34/36) | commit 5b 删,读 base.yaml::event_trigger |
| 5 | `runtime.scheduled.cron_hours_utc: [0,4,8,12,16,20]` | `config/base.yaml`(§X #3) | commit 1 删(v1.4 §10.4.2 明确;0 引用核查后) |
| 6 | `runtime.scheduled.cron_timezone` | `config/base.yaml`(§X #3) | commit 1 删(scheduler.yaml::timezone 是真源) |
| 7 | `runtime.event_driven.throttle` 段 | `config/base.yaml`(§X #4) | commit 1 删,迁到 `event_trigger` 段(单一配置源) |
| 8 | 老 `_check_event_invalidation` / `_is_throttled` / `_record_trigger` 测试(8 条) | `tests/test_event_listener.py` | commit 5b 删,覆盖在 `tests/test_hard_invalidation_monitor.py` + `tests/test_event_trigger.py` |

**自检清单**(commit 6 前 CC 已跑):
- [x] `git grep _PRICE_CHANGE_THRESHOLD` → 0
- [x] `git grep _check_event_invalidation` → 0(除 sprint 报告)
- [x] `git grep _is_throttled / _record_trigger`(在 src/)→ 0
- [x] `git grep cron_hours_utc` → 0(除 sprint 报告 / scheduler.yaml 注释)
- [x] `git grep "runtime.event_driven.throttle"` → 0
- [x] `tests/test_event_listener.py` 完全重写,无残留老 import
- [x] 1325 pytest 0 regression
- [x] 36 §Z 全过

---

## 段 4 — 报告路径

详细报告:`docs/cc_reports/sprint_1_10_g.md`
