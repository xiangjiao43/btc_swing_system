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

### Commit 2-6:待执行

---

## 部署四件事 / 测试记录(commit-by-commit 实时填)

待 commit 6 完成填。

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无明确 v1.3 老 fallback 代码 — 本身没有上层重试机制) | — | 本 sprint 是新增 framework,§X 删除清理实际为 0(orchestrator 改 _fallback_output → thesis_aware_fallback 是替换不是删除) |

**本 sprint 删除清单**:**0 项**(纯新增)。
