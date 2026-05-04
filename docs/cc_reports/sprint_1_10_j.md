# Sprint 1.10-J:配置文件统一 + 旧逻辑大清理

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)§11.2 + §11.3 +
§10.5 1.10-J 行
**Sprint 路径定位**:v1.4 §10.5 第十行 — 1.5 天工作量
**前置 sprint**:1.10-A → 1.10-I 全部完成(HEAD 在 75d3725)

---

## Triggers / 决策记录

### 启动确认 5 项 + E.3 关键决策 用户拍板

- **5 项启动确认全接受**:9 项 grep 调研结果 + 处理表格 + 9 commit 拆分 +
  中断点 1(commit 5 后)+ 模式 B 分段审
- **E.3 决策:留 1.10-K**(state_machine 主体 1190 行重写是架构级改造,
  非清理范畴;1.10-J 只删 POST_PROTECTION_REASSESS / FLIP_WATCH 引用 +
  account_state)
- **§X 删除策略(B/C 列)**:DB 列保留 + DAO 写 NULL + 代码层 0 引用 =
  §X 实质完成。Migration 删列(strategy_runs.observation_category /
  strategy_runs.cold_start)留 1.10-K(影响 50+ 历史 strategy_runs)
- **normalize_state.py:61/156** schema_version="v13" hardcode 留 1.10-K
  (跟 normalize_state 重构一起)

### 节奏

模式 B 分段审:阶段 1 跑 commit 1-5,中断点 1 等用户审 +
浏览器 / scheduler 真启动验证(继承 1.10-I 教训:文本匹配抓不到
JS 运行时错误)。阶段 2 commit 6-9 等用户授权。

---

## 9 项调研详细记录

### A — 4h interval / cron_hours_utc / event_driven 残留

| 项 | 文件:行 | 状态 | 处理 |
|---|---|---|---|
| 主策略 `pipeline_run: interval: '4h'` | scheduler.yaml | **已删**(1.9-B 改 cron) | — |
| `cron_hours_utc` | config/base.yaml | 1.10-G 已删,grep 0 in src/ | — |
| `runtime.event_driven.throttle` | config/base.yaml | 1.10-G 已删,grep 0 in src/ | — |
| `position_health_check: interval: '4h'` | scheduler.yaml:158 | **保留**(v1.4 明确合法) | — |
| `data_catalog.yaml interval: 4h` | config 2 处 | **保留**(K 线时间框架) | — |
| `factor_cards_refresher.py:3` 注释"每 4h" | 文档过时 | commit 2 改注释 |
| `kpi/collector.py:223` 注释 + `next_expected = +4h` | 真逻辑 | commit 2 改 +24h |

### B — observation_classifier(整删 + 14 文件引用)

- `src/strategy/observation_classifier.py`(303 行,整删)
- 引用 14 文件:8 src/ + 6 tests/
- ⚠ schema.sql `observation_category TEXT` 列**保留**(SQLite DROP COLUMN
  风险大,留 1.10-K),DAO 写 NULL = §X 实质完成

### C — cold_start(整删 + 33 文件引用)

- `src/utils/cold_start.py`(52 行,整删)
- 31 src/test 文件 + 2 config 引用
- web/assets/app.js 区分:line 571 注释 "cold-start placeholder" 保留(commit 7 加,描述 1.10-I UI 占位符);其他 cold_start 字段 / cold_start_warming_up / cold_start_tick 删
- ⚠ schema.sql `cold_start INTEGER DEFAULT 0` 列保留(同 B 决策)
- 预计 6-8 个老测试整删 / 改造

### D — account_state(5 src + 4 tests)

- `src/strategy/state_machine_inputs.py:273` `derive_account_state` 整删
- `src/strategy/state_machine.py` `account_state` 参数(line 158/182)+
  `account_has_long/short` 字段(line 737/764/1108)
- `src/ai/agents/l4_risk_analyst.py` 注释引用
- `src/pipeline/state_builder.py` 传 account_state 给 state_machine.compute_next
- 4 tests:test_state_machine_inputs / test_state_machine / test_state_machine_e2e /
  test_lifecycle_e2e_reversal — 大改造

### E — 14 档代码层(分级处理)

| 子项 | 文件 | 决策 |
|---|---|---|
| E.1 `POST_PROTECTION_REASSESS` / `FLIP_WATCH` 引用(17+ 文件) | 多处 | commit 4 删 |
| E.2 14 档枚举字符串(LONG_OPEN / HOLD / TRIM / SHORT_*)| 25+ 文件 | **保留** — v1.4 §5.1 thesis lifecycle 仍用 |
| E.3 `state_machine.py` 1190 行整重写 | 2504 行 3 文件 | **留 1.10-K** — 架构级改造,非清理范畴 |

### F — base.yaml runtime 段

- 1.10-G 已删 cron_hours_utc + throttle(0 真消费)
- 残留 `runtime: {scheduled, event_driven.types, manual}` declare-only
- commit 3 整段删除(0 src 消费)

### G — §11.3 路径错误同步

- 行 1980 `src/ai/adjudicator.py` → `src/ai/agents/master_adjudicator.py`
- 行 1982 `src/decision/validator.py` → `src/ai/validator.py`
- commit 8 修(本阶段 1 不动)

### H — 累积清单 4 项

| # | 项 | 决策 |
|---|---|---|
| 1 | AlertsDAO 重构(裸 INSERT 4 处) | commit 7 修 |
| 2 | events_calendar.triggered_at_utc migration 路径 | commit 7 修(生产 DB 真缺此列,init_v14_tables 加条件 ALTER) |
| 3 | 1.10-G verify event_macro 报错 | #2 修后自动解决 |
| 4 | ThesesDAO.get_by_id review | 本 sprint 不动,稳定 |

### I — schema_version='v13' 其他写死

- `web/assets/app.js` commit 7 已修
- `src/web_helpers/normalize_state.py:61/156` hardcode 输出 v13(本 sprint 不动,留 1.10-K)
- 测试 test_normalize_state.py 假设 v13(留 1.10-K)

---

## 1.10-J 累积清单 declare(本 sprint 不动)

| # | 留 1.10-K 项 | 来源 |
|---|---|---|
| 1 | state_machine 主体重写(E.3,2504 行 3 文件) | 1.10-J 决策 |
| 2 | strategy_runs.observation_category / cold_start 列 DROP | 1.10-J B/C 决策 |
| 3 | normalize_state.py 输出 schema_version='v14'(对齐后端) | 1.10-J I 决策 |
| 4 | ThesesDAO 统一重构 | 1.10-I |

### v1.4 §11.3 路径错误清单(commit 8 修后清零)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |

---

## 任务 1-9 实施记录(commit-by-commit 实时填)

### Commit 1:启动 + 报告骨架 + 9 项调研记录 + 1.10-J 累积清单 declare(本 commit)
- hash: 待 push 后填
- `docs/cc_reports/sprint_1_10_j.md`(本文件)

### Commits 2-9:阶段 1(2-5)+ 阶段 2(6-9)分两批

阶段 1(本次 commit 1-5):commit 1 / 2 (A) / 3 (F) / 4 (E.1+D) / 5 (B)
阶段 2(用户审后 commit 6-9):6 (C cold_start) / 7 (H AlertsDAO + migration) / 8 (G docs) / 9 (verify + 报告)

---

## 部署四件事 / 测试记录(commit 9 末尾填)

待 commit 9 完成。

## 本 sprint 删除清单(commit 9 末尾汇总)

详见上方 9 项调研。**§X 实质完成 = 代码层 0 残留 + DB 列保留 NULL**(B/C 项)。
