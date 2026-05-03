# Sprint 1.10-H:weekly_review_analyst + S3 过度保守 + position_health_check 真 AI

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)§3.3.9 + §8.1 + §8.2 + §8.4
**Sprint 路径定位**:v1.4 §10.5 第八行 — 1.5 天工作量
**前置 sprint**:1.10-A → 1.10-G 全部完成(HEAD 在 00d30e1)

---

## Triggers / 决策记录

### 启动确认 4 个 D 用户拍板

- **D1 = a**:新增 `weekly_reviews` 表(migration 014)+ alerts 表写一行通知。
  PK = week_start_utc(YYYY-MM-DD 周一 UTC),UPSERT 幂等;output_json 存 4 段完整 JSON;
  critical_count 由 adjustment_recommendations.priority='high' 计数。
- **D2 = a**:复用 EmergencySimplifiedA + ctx 加 trigger 字段区分('event_price' /
  'health_check')。改动 < 30 行,节约工程。prompt 加一段"若 trigger=health_check,
  跳过价格异动判断,只评估 thesis 仍 valid + 风险因子是否升级"。
- **D3 = a**:S3 过度保守监控集成到 `job_pipeline_run` 入口(builder.run() 之前)。
  规则计算 < 1ms,跟主 run 同步;告警立即体现在 16:05 BJT 网页(1.10-I)。
- **D4 = b2**:新增 `EXIT_D = "exit_d_thesis_resumed"`(语义清晰,周复盘 AI 后续能区分
  exit_b 用户续期 vs exit_d 过度保守自然恢复)。

### 节奏

完全放手模式(用户授权一次性跑完 6 commits;commit 5 < 500 行预测,不拆)。

---

## 调研 — 现状对照

### 已存在(1.10-A → G 实施)

| 项 | 文件:行 | 状态 |
|---|---|---|
| `EmergencySimplifiedA` agent | `src/ai/agents/emergency_simplified_a.py` | ✅ commit 5 加 trigger 字段复用 |
| `job_position_health_check` stub | `src/scheduler/jobs.py:988` | ⚠ 1.10-G stub,本 sprint commit 5 接通真 AI |
| `alerts` 表 schema(7 字段)| `src/data/storage/schema.sql:108` | ✅ 复用,无新 DAO 类(裸 INSERT 沿用 state_builder.py:1351 模式,留 1.10-J 重构) |
| `system_states` + review_pending 模块 | `src/strategy/review_pending.py` | ✅ commit 4 加 `EXIT_D` enum + `exit_d_thesis_resumed` 函数 |
| `strategy_runs.constraint_activations_json` | migration 011(1.10-E) | ✅ commit 2 input_builder 聚合 23 条 V 激活率 |
| `strategy_runs.retry_log_json` | migration 012(1.10-F) | ✅ commit 2 input_builder 聚合 fallback 历史 |
| `theses` 表 + `created_at_utc` | 1.10-A | ✅ commit 2/4 直查 |
| `virtual_account` 7 天 snapshots | 1.10-A | ✅ commit 2 算 weekly_pnl_pct / max_drawdown_pct |

### v1.4 期望但缺失(本 sprint 新建)

- ❌ `weekly_reviews` 表(commit 1 migration 014)
- ❌ `WeeklyReviewAnalyst` agent + system prompt(commit 3 新建)
- ❌ `weekly_review_input_builder`(commit 2 新建)
- ❌ `ConservativeMonitor` S3(commit 4 新建)
- ❌ `scheduler.yaml::weekly_review` cron(commit 5 加)
- ❌ `jobs.py::job_weekly_review` + `job_position_health_check` 真 AI 接通(commit 5)
- ❌ `EmergencySimplifiedA` 加 trigger 字段(commit 5,~30 行)

### v1.4 §11.3 路径错误清单(继承 1.10-D/E,本 sprint 无新增)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |

---

## 任务 1-8 实施记录(commit-by-commit 实时填)

### Commit 1:报告骨架 + migration 014 weekly_reviews 表(本 commit)
- hash: 待 push 后填
- `migrations/014_v14_weekly_reviews.sql`(NEW):CREATE TABLE IF NOT EXISTS + index
- `scripts/init_v14_tables.py`:加 `_MIGRATION_014` + executescript(全新表幂等)
- `src/data/storage/schema.sql`:加 weekly_reviews 表(测试用)
- `docs/cc_reports/sprint_1_10_h.md`(本文件)

### Commit 2:weekly_review_input_builder + 15 单测
- hash: `80012d2`
- `src/ai/weekly_review_input_builder.py`(NEW):
  - `VALIDATOR_KEYS` 常量 23 条 + `assert len==23`
  - 7 个聚合函数:strategy_runs / theses / virtual_orders / retry_log /
    virtual_account / fuse_and_states / constraint_activations
  - `build_weekly_review_input(conn, now_utc, window_days=7)` 入口
  - 算 weekly_pnl_pct + max_drawdown_pct(7 天 va snapshots)
- `tests/test_weekly_review_input_builder.py`(15 单测,含 23 V 完整性 + 冷启动 +
  双向 PnL + drawdown 跌至 -6.67%)

### Commit 3:WeeklyReviewAnalyst agent + system prompt + 14 单测
- hash: `39a0e99`
- `src/ai/agents/weekly_review_analyst.py`(NEW):
  - `class WeeklyReviewAnalyst(BaseAgent)`,继承 BaseAgent 全套机制
  - `_fallback_output` 返完整 4 段 + 23 V(每条 evaluation='AI 失败'),自带 1 条 high
    priority 触发 critical 告警
  - `normalize_output` 漏 V 自动补 + notes 标记
  - `count_critical_recommendations` 计 priority='high' 条数(D1=a alerts severity)
- `src/ai/agents/prompts/weekly_review_analyst.txt`(NEW):
  - 6 段 system prompt,完整列出 23 V 在 schema 内
  - v1.4 §3.4.9 末段评估规则:>5/7 太严 / 0/7 太松 / 1-3/7 适中
- `tests/test_weekly_review_analyst.py`(14 单测,prompt 含 23 V key + normalize 漏补 +
  count_critical 边界)

### Commit 4:ConservativeMonitor + EXIT_D + alerts 集成 + 16 单测
- hash: `6b3a926`
- `src/strategy/conservative_monitor.py`(NEW):
  - 阈值 30/60 天 + ALERT_TYPE='overly_conservative'
  - `check_recent_thesis_count` 冷启动安全(无 thesis → severity='none')
  - `check_and_alert` 主入口(写 alerts + critical 进 review_pending)
  - 24h 内同 severity 幂等不双写
  - 裸 INSERT 写 alerts(留 1.10-J AlertsDAO 重构)
- `src/strategy/review_pending.py`(D4=b2):
  - 加 `EXIT_D = "exit_d_thesis_resumed"` 常量
  - `exit_d_thesis_resumed` 函数:**只**对 reason='overly_conservative' 生效
- `tests/test_conservative_monitor.py`(16 单测,含等号边界 30d/60d + EXIT_D 拒绝其他 reason)

### Commit 5:scheduler + position_health_check 真 AI + EmergencySimplifiedA trigger 字段 + 23 单测
- hash: `ef12aa6`
- `config/scheduler.yaml` 加 `weekly_review` cron(周日 22:00 BJT)
- `src/ai/agents/emergency_simplified_a.py`(D2=a):
  - `_build_user_prompt` 加 `trigger 类型:{trigger}`(默认 'event_price' 向后兼容)
  - prompt 文件加 health_check 特别说明
- `src/scheduler/jobs.py`:
  - `job_pipeline_run` 顶部加 `ConservativeMonitor.check_and_alert`(D3=a)
  - `job_pipeline_run` 末尾加 EXIT_D 联动(D4=b2:thesis 创建 → exit_d)
  - `job_position_health_check` 改造(stub → 真 AI):取 baseline + current 调
    `EmergencySimplifiedA(trigger='health_check')`,写 alerts(severity 由 action 决定)
  - 新 `job_weekly_review`:input_builder + analyst + UPSERT weekly_reviews +
    `count_critical_recommendations` → alerts critical
  - `_state_from_thesis` helper 推导 14 档
- `tests/test_jobs_weekly_review_and_health_check.py`(23 单测)
- `tests/test_jobs_retry.py` adapter:position_health_check stub → skipped_no_price_data
- `tests/test_scheduler_2_7_a_cron.py` adapter:10→11 entries / expected_9→10

### Commit 6:verify_weekly_review.py(42 §Z)+ 报告 + checklists(本 commit)
- hash: 待 push 后填
- `scripts/verify_weekly_review.py` — 7 段共 42 项 §Z 真实断言:
  - A. weekly_reviews 表 + migration 014(4)
  - B. VALIDATOR_KEYS 23 条 + input_builder 7 类聚合(5)
  - C. WeeklyReviewAnalyst fallback + normalize + count_critical(8)
  - D. ConservativeMonitor + EXIT_D 完整流程(10)
  - E. scheduler weekly_review cron 注册(6)
  - F. job_weekly_review 端到端(mock AI + 真 DB UPSERT + alerts)(5)
  - G. EmergencySimplifiedA trigger 字段(D2=a)(4)

§Z 真捕真修(连续第 5 次,继承 1.10-D/E/F.commit3/F.commit6/G):
- **本 sprint catch**:section D 末段 `EXIT_D 拒绝 60d_cap` 测试创建的 stale
  system_states 行未被 cleanup 删(原 cleanup 只删 reason='overly_conservative')
  → 第 2 次 verify 时 enter_review_pending 检测到 60d_cap active → 'was_already_active'
  → review_pending_entered=False
- **修法**:cleanup 改为 `DELETE FROM system_states WHERE entered_at_utc LIKE '2099-%'`
  (清所有 2099- 测试用未来日期行,无论 reason)

---

## 部署四件事 / 测试记录

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1393 passed (+68 vs 1.10-G), 1 skipped, 0 regression |
| GitHub push(commit hash) | ✅ commits 1-5 已推:ef12aa6 / 6b3a926 / 39a0e99 / 80012d2 / 2a86465;commit 6 本次 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行(weekly_review cron 需 scheduler 重启注册) |
| 生产 DB migration 014 | 待用户执行 — `.venv/bin/python scripts/init_v14_tables.py /path/to/prod/btc_strategy.db`(全新表 IF NOT EXISTS 幂等) |

### §Z verify 真实运行结果

```
$ .venv/bin/python scripts/verify_weekly_review.py
通过:42 项
失败:0 项
✅ 全部通过
```

### 单元测试矩阵

| 测试文件 | 单测数 | 覆盖 |
|---|---|---|
| `tests/test_weekly_review_input_builder.py` | 15 | commit 2 — 7 类聚合 + 23 V + PnL/drawdown |
| `tests/test_weekly_review_analyst.py` | 14 | commit 3 — 4 段 JSON + 23 V normalize + count_critical |
| `tests/test_conservative_monitor.py` | 16 | commit 4 — S3 30d/60d 边界 + EXIT_D D4=b2 |
| `tests/test_jobs_weekly_review_and_health_check.py` | 23 | commit 5 — health_check 真 AI + weekly_review job + UPSERT |
| `tests/test_jobs_retry.py`(adapter) | (1 改) | position_health_check stub → 真 AI 行为 |
| `tests/test_scheduler_2_7_a_cron.py`(adapter) | (3 改) | 10→11 entries |
| **小计** | **68 + 4 改** | 1.10-H 全覆盖 |

---

## 未覆盖 / 留 1.10-I/J/L 处理

### 1.10-I 留处理(网页改造)

- `weekly_reviews` 表已有数据(每周日 22:00 自动写),网页 1.10-I 实施"周复盘"卡:
  - `SELECT * FROM weekly_reviews ORDER BY week_start_utc DESC LIMIT 12`(过去 12 周)
  - 4 段 JSON 结构化展示:performance_summary / system_health_diagnosis /
    strategy_quality / hard_constraint_activation_review(23 V 评估表)/
    adjustment_recommendations(critical 高亮红色)
- `alerts` 表 alert_type='overly_conservative' / 'weekly_review_critical_recommendation' /
  'position_health_check' → 网页 toast 推送 / 红色横幅
- `system_states` 显示 review_pending 横幅(reason='overly_conservative')+ 显式说明
  "新 thesis 创建后自动退出(D4=b2 EXIT_D)"

### 1.10-J 留处理(老代码清理)

| # | 老代码 | 路径 | 替代方案 / 理由 |
|---|---|---|---|
| 1 | alerts 裸 INSERT(无 DAO 类) | `src/strategy/conservative_monitor.py`(本 sprint)+ `src/scheduler/jobs.py`(本 sprint)+ `src/pipeline/state_builder.py:1351`(2.7-A) | 1.10-J 重构 AlertsDAO 类(insert_alert / get_recent / mark_acknowledged)|
| 2 | 1.10-G verify 遗留 `event_macro` 报 `no such column: triggered_at_utc` | `events_calendar.triggered_at_utc` 列只在 `migrate_2_7_d.py` 加,不在 init_v14_tables 路径 | 1.10-J 一并迁移到主 schema.sql |

### 1.10-L 留处理(真 API + 端到端)

- WeeklyReviewAnalyst 全 mock,真 anthropic API 调用未验证:
  - 真 master AI 在 5000 token input + 3000 token output 下 latency / cost / 输出质量待实测
  - 23 V evaluation 文本是否真满足"过严/适中/过松/未触发"分类标准
  - adjustment_recommendations 真 priority 分布(high 比例不超 1-2 条/周?)
- position_health_check trigger='health_check' 加 prompt 段后,真 AI 是否真区分两类场景
  (vs trigger='event_price')
- ConservativeMonitor 30/60 天阈值在真生产长期运行下的合理性(可能太宽 / 太严)

### v1.4 §11.3 路径错误清单(继承 1.10-D/E,本 sprint 无新增)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |

---

## 本 sprint 删除清单

| # | 删除 / 替换对象 | 路径 | 状态 |
|---|---|---|---|
| 1 | 1.10-G `job_position_health_check` stub 行为(无 active → 直接返 / 有 active → 仅 logger.info) | `src/scheduler/jobs.py:988` | commit 5 替换为真 AI 调用(算修改) |

**本 sprint 实质删除:0 项**(纯新增 framework 为主)。
§X 老代码清理留 1.10-J(alerts 裸 INSERT 2 处 + events_calendar.triggered_at_utc migration 路径)。

**自检清单**(commit 6 前 CC 已跑):
- [x] 1393 pytest 0 regression
- [x] 42 §Z 全过(catch + 修 cleanup bug)
- [x] git grep `weekly_review_analyst` 调用方齐(commit 5 jobs.py 接通)
- [x] git grep `EXIT_D` 调用方齐(commit 5 jobs.py post-thesis 接通)
- [x] git grep `ConservativeMonitor` 调用方齐(commit 5 job_pipeline_run 顶部接通)

---

## 段 4 — 报告路径

详细报告:`docs/cc_reports/sprint_1_10_h.md`
