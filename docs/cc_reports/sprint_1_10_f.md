# Sprint 1.10-F:AI 重试机制(指数退避 + 短路依赖 + 2h 窗口)

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)§6.3 + §6.4 + §3.4.7
**Sprint 路径定位**:v1.4 §10.5 第六行 — 2 天工作量
**前置 sprint**:1.10-A/B/C/D/E 全部完成

---

## Triggers / 决策记录

### 启动确认 4 个 D 用户拍板

- **D1 = b**:新增 `strategy_runs.retry_log_json TEXT`(migration 012)
- **D2 = a + 滑动 72h**:V22 用 `SELECT WHERE generated_at_utc >= now - 72h AND retry_log_json LIKE '%master_fail%'` 计数 ≥ 3
- **D3 = b**:V21 强化 prompt 追加 hint(`_v21_retry_hint` 字段拼入 master prompt)
- **D4 = a**:L5 失败硬编码 macro fallback(risk_neutral / headwind_score=0 / extreme_event=False / cap_macro=1.0 / status=degraded_l5_failed_macro_fallback)

### 关键洞察:两层重试架构

- **BaseAgent.analyze 现有 2-attempt 重试**(temperature 0.2/0.4,即时):**保留**,作为低级 API 重试(网络抖动 / 临时 parse 错)
- **v1.4 §6.3 是 orchestrator 层失败重试**:整层/整次 run 失败 → 等 5/10/20 分钟,2h 窗口,**跨 cron tick 调度**(异步重试)
- **Validator 触发的同步重试**(V8/V9/V11/V21):orchestrator 在同一 run 内立刻调 master.analyze 1 次 with hint,不等 cron

两机制并存:
| 机制 | 触发 | 时机 | 实施位置 |
|---|---|---|---|
| BaseAgent 即时重试 | API 网络抖动 / parse 错 | 即时 | BaseAgent._call_ai_with_retry |
| **同步重试**(Validator) | V8/V9/V11/V21 触发 | 同一 run 内 | commit 5 orchestrator hook |
| **异步重试**(整层) | L1-L5 整层失败 | 等下次 cron(5/10/20 分钟外触发) | commit 4 orchestrator + RetryPolicy |

### 节奏

完全放手模式(用户授权一次性跑完 6 commits)。

---

## 任务 1:现状调研

### 调研结果

| 项 | 现状 | v1.4 期望 |
|---|---|---|
| **BaseAgent._call_ai_with_retry** | 2-attempt 即时(temp 0.2/0.4) | **保留**,作为 API 低级重试 |
| **orchestrator._run_lX** | try/except → `_fallback_output()` 即时,无上层重试无短路 | 加 RetryPolicy + CircuitBreaker wrapper |
| **thesis_aware_fallback 调用方** | **0 处**(1.10-D 加了静态方法,本 sprint 接通) | _run_master 失败时调 thesis_aware_fallback(has_active_thesis) |
| `config/base.yaml::ai_retry` | **不存在** | 本 commit 加 `intervals_minutes: [5,10,20]` + `max_attempts_per_layer: 3` + `total_window_hours: 2` |
| `strategy_runs.retry_log_json` | **不存在** | commit 4 migration 012 加 |
| 6 agent 调用顺序 | L1 → L2 → L5 → L3 → L4 → master(L5 在 L3/4 之前) | 不变(本 sprint 只加 retry/短路 wrapper) |

### v1.4 §11.3 路径错误清单(继承 1.10-D/E,1.10-J 修)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |

---

## 任务 2-7 实施记录(commit-by-commit 实时填)

### Commit 1:报告骨架 + 调研 + base.yaml::ai_retry(本 commit)
- hash: 待 push 后填
- `docs/cc_reports/sprint_1_10_f.md`(本文件)
- `config/base.yaml` 新增 `ai_retry` 段(D1-D4 配置常量)

### Commit 2:RetryPolicy + 19 单测
- hash: `2d294fa`
- `src/ai/retry_policy.py` — `compute_backoff_seconds(attempt)` 返回 300/600/1200,`is_within_window(start, now)` 2h 边界,`classify_failure(exc)` 5 类
- `tests/test_retry_policy.py` — 19 单测全过

### Commit 3:CircuitBreaker + 18 单测
- hash: `d7f57af`
- `src/ai/circuit_breaker.py` — `_SHORTCUT_RULES` 短路依赖图(L1→[l2,l3,master],L5→[]),`should_master_run`,`apply_macro_fallback()` 硬编码 D4=a 字段
- `tests/test_circuit_breaker.py` — 18 单测全过

### Commit 4:migration 012 + orchestrator 改造 + Master fallback 接通 + 9 单测
- hash: `800a831`
- `migrations/012_v14_retry_log.sql` — audit trail SQL,实际 ALTER 在 Python 侧
- `scripts/init_v14_tables.py` — 加 `_MIGRATION_012` + 条件 ALTER `strategy_runs.retry_log_json`(SQLite 不支持 ADD COLUMN IF NOT EXISTS,沿用 1.10-E 套路)
- `src/data/storage/schema.sql` — 加 `retry_log_json TEXT` 字段
- `src/data/storage/dao.py` — `StrategyStateDAO.insert_state` 写入 `state["retry_log"]` → `retry_log_json`(无字段时 NULL)
- `src/ai/orchestrator.py`:
  - 删 commit 3 遗留的 `master_adjudicator` 重复 import
  - `_run_l5` 失败 → `CircuitBreaker.apply_macro_fallback()` 替换 l5 输出 + retry_log["macro_fallback_applied"]=True
  - `_run_master` 失败 → 接通 1.10-D `MasterAdjudicator.thesis_aware_fallback(has_active_thesis=...)` + retry_log["thesis_aware_fallback_applied"]=True
- `tests/ai/test_orchestrator_retry.py` — 9 单测覆盖 L5 fallback / Master fallback (有/无 thesis) / DAO 写入 / happy path

### Commit 5:V8/V9/V11/V21/V22 retry 集成 + V22 SQL 滑动 72h + 15 单测
- hash: `c665909`
- `src/ai/validator.py`:
  - V8/V9/V11/V21 触发时增加 `validator_<n>_needs_retry=True` 标记
  - V21 增加 `validator_21_retry_hint` 文本(D3=b)
  - V22 升级:优先 `context["master_failures_in_72h"]`(orchestrator 注入),fallback 老字段 `master_consecutive_failures`
  - 新 helper `count_master_failures_in_window(conn, window_hours, now_utc)`(D2=a)
  - `collect_meta_activations` 聚合 needs_retry 决策 + retry_hints,剥离 per-V 临时键不重复持久化
  - `_DEFAULT_ACTIVATIONS_V24` 新增 4 个 retry meta 字段(28→32)
- `src/ai/orchestrator.py`:
  - `run_full_a` 末尾增加 validator-triggered retry 钩子:`needs_retry=True` + master 第 1 次成功 → 同 context + `_v21_retry_hint` 重新调用 master 1 次,第 2 次校验通过则采纳
  - `validator_ctx` 新增 `master_failures_in_72h` 字段(caller 装入)
- `tests/ai/test_validator_v14_retry.py` — 15 单测
- `tests/test_validator_v14_integration.py` — 28 字段断言更新为 32(显式列出原 28 项防回归)
- `tests/ai/test_orchestrator_retry.py` — `_ok_master` 修复 V8 误触

### Commit 6:verify_retry_mechanism.py(30 §Z 断言) + 报告 + 1.10-G/L checklists
- hash: 本 commit
- `scripts/verify_retry_mechanism.py` — 8 段共 30 项 §Z 断言(RetryPolicy + CircuitBreaker + macro fallback + V8/V21 needs_retry + V22 SQL + retry_log 端到端 + Orchestrator e2e + meta_activations 聚合)
- §Z 真捕真修(连续第 4 次):验证发现 `collect_meta_activations` 把 per-V `_needs_retry`/`_retry_hint` 临时键泄漏到最终 activations(34 != 32),修法是在 collect 末尾 pop 掉,只保留聚合后的 `validator_needs_retry` + `validator_retry_hints`
- `scripts/verify_validator_v14.py` — 28→32 字段断言更新

---

## 部署四件事 / 测试记录

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1235 passed (+25 vs 1.10-E), 1 skipped, 0 regression |
| GitHub push(commit hash) | ✅ commits 1-5 已推:c665909 / 800a831 / d7f57af / 2d294fa / 33cc22b;commit 6 本次 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB migration 012 | 待用户执行 — `.venv/bin/python scripts/init_v14_tables.py /path/to/prod/btc_strategy.db`(幂等,已初始化则只 ALTER 加 retry_log_json) |

### §Z verify 真实运行结果

```
$ .venv/bin/python scripts/verify_retry_mechanism.py
通过:30 项
失败:0 项
✅ 全部通过
```

### 单元测试矩阵

| 测试文件 | 单测数 | 覆盖 |
|---|---|---|
| `tests/test_retry_policy.py` | 19 | commit 2 RetryPolicy |
| `tests/test_circuit_breaker.py` | 18 | commit 3 CircuitBreaker |
| `tests/ai/test_orchestrator_retry.py` | 9 | commit 4 L5 fallback + Master fallback + DAO retry_log |
| `tests/ai/test_validator_v14_retry.py` | 15 | commit 5 V8/9/11/21/22 needs_retry + V22 SQL + orchestrator post-validate retry |
| **小计** | **61** | 1.10-F 全覆盖 |

---

## 未覆盖 / 留 1.10-G/L 处理

### 1.10-G 留处理(事件触发)

- **现状**:本 sprint 实现的"异步重试"靠 cron 自然 tick 触发(每 5/10/20 分钟外有下次 cron run 时尝试)。`RetryPolicy.compute_backoff_seconds` 仅返回延迟时间,**未实际调用 sleep / asyncio**(留 1.10-G 真接入 jobs.py 时做)
- **需 1.10-G 做**:在 `src/scheduler/jobs.py` 接入异步 retry queue:层失败 → 写 `pending_retries` 表 → 下个 cron tick 检查表 → 跑窗口内的 retry
- **本 sprint 已铺好的 framework**:RetryPolicy 计算延迟 + CircuitBreaker 短路图 + retry_log_json 持久化结构

### 1.10-L 留处理(真 API + 端到端)

- 当前所有 6 AI 调用在测试中都是 mock,真 API 行为(网络抖动 / parse 错 / token 限流)未覆盖。1.10-L 接 jobs.py 后用真 anthropic SDK 跑 1 周观察实际触发率
- V21/V22 检测在真 master AI 上的"软抗拒识别准确率"需真观察样本评估
- V21 retry hint 加入 master prompt 后第 2 次输出**质量改进**待真 AI 验证(本 sprint 只验证 hook 走通)
- V8/V9/V11 触发率与 master AI 实际输出风格的契合度(过严会浪费 token)

### v1.4 §11.3 路径错误清单(继承)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |
| 3 | (无新增) | — | — |

留 1.10-J 统一修文档。

---

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无 v1.3 老 fallback 代码) | — | 本 sprint 纯新增 framework |
| `master_adjudicator` 重复 import(commit 3 遗留) | `src/ai/orchestrator.py:38` | commit 3 加 CircuitBreaker import 时混入,commit 4 清理 |
| `validator_<n>_needs_retry` / `validator_21_retry_hint` per-V 临时键持久化 | 在 `collect_meta_activations` 末尾 pop | §Z verify 发现泄漏到 constraint_activations_json,修复 |

**自检清单**(commit 6 前 CC 已跑):
- [x] `git grep` 新增函数 `count_master_failures_in_window` / `apply_macro_fallback` / `thesis_aware_fallback` 调用方齐全
- [x] `tests/` 中无重复 / 死测试
- [x] `config/base.yaml::ai_retry` 段已被 RetryPolicy 消费(`tests/test_retry_policy.py`)
- [x] 1235 pytest 0 regression
- [x] 30 §Z 全过

---

## 段 4 — 报告路径

详细报告:`docs/cc_reports/sprint_1_10_f.md`
