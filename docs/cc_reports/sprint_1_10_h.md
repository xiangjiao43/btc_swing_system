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

### Commits 2-6:待执行

---

## 部署四件事 / 测试记录(commit 6 末尾填)

待 commit 6 完成。

## 本 sprint 删除清单(commit 6 末尾汇总)

本 sprint 是**纯新增**(weekly_review_analyst + ConservativeMonitor + 1 新表),
仅 1 项替换:
- 1.10-G `job_position_health_check` stub → commit 5 真 AI 接通(算修改不算删除)

§X 删除留 1.10-J(alerts 裸 INSERT → AlertsDAO 类重构)。
