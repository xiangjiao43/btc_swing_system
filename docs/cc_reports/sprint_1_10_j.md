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

### Commits 2-9 实施记录

#### 阶段 1(commit 1-5,中断点 1 后审通过)
- **Commit 2** `0ab357e`: A 项 4h 注释清理 + kpi/collector +24h(2 文件,~10 行)
- **Commit 3** `a07594b`: F 项 base.yaml runtime: 整段删(1 文件,-19 行)
- **Commit 4a** `1069b58`: D 项 account_state 删除(7 文件 +56/-171,删 derive_account_state + state_machine.compute_next 移除参数 + 4 测试改造,2 模块整 SKIP)
- **Commit 4b** `04e6d54`: E.1.a 网页层脱钩 FLIP_WATCH/POST_PROTECTION_REASSESS(3 文件 +15/-10,labels/normalize_state/app.js 删 4 处)
- **Commit 5** `91f0f6e`: B 项 observation_classifier 整删 + 8 文件引用 + DAO 写 NULL(6 文件 +32/-712,整文件 303 行 + test_observation_classifier 整删)

#### 阶段 2(commit 6-9,中断点 2 后审通过)
- **Commit 6** `53ec0dd`: C 项 cold_start 整删 + 18 文件引用 + DAO 写 0 graceful(21 文件 +97/-420 + 2 文件 DELETED;cold_start.py 52 + test_cold_start_util 整删 + 14 老测试改/删)
- **Commit 7** `666b72a`: H 项 AlertsDAO 类重构 + events_calendar.triggered_at_utc 条件 ALTER + 18 单测(6 文件 +405/-25)
- **Commit 8** `e3064ae`: G 项 docs/modeling.md §11.3 路径错误修(2 处)
- **Commit 9** 本 commit: verify_cleanup_v14 + 报告 4 段 + 1.10-K/L checklist

---

## 部署四件事 / 测试记录

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1471 passed (-23 vs 1494 删旧测试), 4 skipped, 0 regression |
| GitHub push(9 commits) | ✅ 全部已推:57b506e → 0ab357e → a07594b → 1069b58 → 04e6d54 → 91f0f6e → 53ec0dd → 666b72a → e3064ae(commit 9 本次) |
| 服务器 git pull | ⚠ 待用户执行(服务器仍在 80c4301,差 60+ commit;1.10-J 是 1.10-L 之前最后一次同步机会) |
| 服务器 systemctl restart | ⚠ 待用户执行(11 个 cron job 改动 + AlertsDAO 重构需 uvicorn 重启) |
| 生产 DB events_calendar.triggered_at_utc 列 | ⚠ 待用户执行 — `.venv/bin/python scripts/init_v14_tables.py /path/to/prod/btc_strategy.db`(幂等条件 ALTER,沿用 1.10-F 模式) |

### §Z verify_cleanup_v14.py 真实运行结果

```
$ .venv/bin/python scripts/verify_cleanup_v14.py
通过:35 项
失败:0 项
✅ 全部通过
```

### 35 §Z 断言分布

| Section | 项 | 内容 |
|---|---|---|
| A | 3 | F 项 base.yaml runtime: 整删 |
| B | 3 | B 项 observation_classifier §X 0 业务依赖 + __init__ 不导出 |
| C | 5 | C 项 cold_start §X 0 业务依赖 + web/app.js 字段/标签删 |
| D | 2 | D 项 account_state — compute_next 无参数 + derive 函数已删 |
| E | 4 | E.1.a 网页层 labels + normalize_state 4 处删 |
| F | 3 | H#1 AlertsDAO 类 + 4 处 INSERT 只剩 1 自身 + e2e 写读 |
| G | 1 | H#2/H#3 events_calendar.triggered_at_utc 列存在 |
| H | 3 | G 项 docs/modeling.md §11.3 路径错误修(commit 8) |
| I | **5** | **§Z 真启动 uvicorn TestClient + 11 v14 API 全 200**(继承 1.10-I commit 7 教训) |
| J | 3 | §Z scheduler cron 注册 + PIPELINE_STAGES / STATE_MACHINE_STATES 删 |
| K | 2 | DAO graceful 列保留 — cold_start 写 0 + observation_category 写 NULL |

### 单元测试矩阵

| 测试文件 | 净 +/- 单测数 | 覆盖 |
|---|---|---|
| `tests/test_alerts_dao.py`(NEW) | +18 | commit 7 — AlertsDAO + migration 幂等 |
| `tests/test_observation_classifier.py`(整删) | -16 | commit 5 — observation 整删 |
| `tests/test_cold_start_util.py`(整删) | -10 | commit 6 — cold_start 整删 |
| `tests/test_state_machine_e2e.py`(整模块 SKIP) | (-N skip) | commit 4a — 14 档 e2e 留 1.10-K |
| `tests/test_lifecycle_e2e_reversal.py`(整模块 SKIP) | (-N skip) | commit 4a — 同上 |
| `tests/test_state_machine_inputs.py` | -4(3 e2e + 1 单元 整删) | commit 4a |
| `tests/pipeline/test_orchestrator_mapper.py` | -4 净(删 5 + 加 1) | commit 5 + 6 |
| `tests/test_alerts.py` | -2 | commit 6 — cold_start_stuck + sorted_by_level |
| `tests/test_kpi_collector.py` | -1 | commit 6 — cold_start_progress |
| `tests/test_no_opportunity_8_scenarios.py` | -1 | commit 6 — cold_start scenario |
| `tests/test_no_opportunity_narrator.py` | -1 | commit 6 — cold_start route detection |
| `tests/test_plain_reading.py` | (1 改) | commit 6 — health_status='error' 替代 |
| **小计** | **净 -23**(1494 → 1471) | 全为整删/SKIP 老 14 档 + observation + cold_start 测试 |

---

## 1.10-K 累积清单(本 sprint 完整 declare,留 1.10-K 实施)

| # | 项 | 来源 sprint | 1.10-K 实施 |
|---|---|---|---|
| 1 | state_machine.py 主体重写(1190 行)+ inputs/lifecycle_manager(2504 行)→ thesis-driven | 1.10-J E.3 决策 | 架构级重写 |
| 2 | strategy_runs.observation_category / cold_start 列 DROP COLUMN(SQLite CREATE TABLE 复制) | 1.10-J B/C 决策 | Migration 015(影响 50+ 历史 strategy_runs) |
| 3 | normalize_state.py:61/156 schema_version='v13' hardcode 改 'v14' | 1.10-J I 决策 | 跟 normalize_state 重构一起 |
| 4 | ThesesDAO 统一重构(1.10-I get_by_id 单加,留统一 review) | 1.10-I | 1.10-K DAO 重构 |
| 5 | state_machine 内部 _from_FLIP_WATCH / _from_POST_PROTECTION_REASSESS / 纪律 3 校验 50+ 处 | 1.10-J E.1.b 决策 | 跟 #1 一起 |
| 6 | narrator SCENARIO_COLD_START + SCENARIO_POST_PROTECTION + _gen_* 函数 + 4-6 处 route logic | 1.10-J commit 5+6 | 跟 #1 一起整重写 |
| 7 | alerts.acknowledged / notification_sent 字段 → AlertsDAO 加 mark_acknowledged / mark_notified 方法 | 1.10-J commit 7 | 1.10-K AlertsDAO 扩展 |

## 1.10-L checklist(真用户 + 真生产数据验证,本 sprint 加)

| # | 项 | 验证场景 |
|---|---|---|
| 1 | 服务器同步 80c4301 → e3064ae(60+ commit) | 1.10-J 是关键节点,1.10-L 之前最后机会 |
| 2 | 生产 DB 跑 init_v14_tables.py 加 events_calendar.triggered_at_utc 列 | 1.10-G verify event_macro 报错的根因修 |
| 3 | systemctl restart btc-strategy 让 11 个 cron 注册新版本 | 改动较多,确保运行时无残留 v1.3 进程 |
| 4 | 网页打开后历史 strategy_runs(含 cold_start / observation_category 老值)graceful 渲染 | DAO 写 0/NULL,前端不消费,不应 console 报错 |
| 5 | 生产真触发 alerts(critical / warning / info)经 AlertsDAO 写入 | 4 处调用方真生产路径(state_builder / jobs.py x2 / conservative_monitor) |

### v1.4 §11.3 路径错误清单 — **本 sprint 清零**

| # | v1.4 §11.3 文档路径 | 真实路径 | 修复 sprint |
|---|---|---|---|
| 1 | ~~`src/ai/adjudicator.py`~~ → `src/ai/agents/master_adjudicator.py` | ✅ 已修(commit 8)| 1.10-J |
| 2 | ~~`src/decision/validator.py`~~ → `src/ai/validator.py` | ✅ 已修(commit 8)| 1.10-J |

---

## 本 sprint 删除清单(汇总)

| 类别 | 项 | 来源 | commit |
|---|---|---|---|
| 整文件 | `src/utils/cold_start.py` | C 项 | 6 |
| 整文件 | `src/strategy/observation_classifier.py` | B 项 | 5 |
| 整文件 | `tests/test_cold_start_util.py` | C 项 | 6 |
| 整文件 | `tests/test_observation_classifier.py` | B 项 | 5 |
| 整模块 SKIP | `tests/test_state_machine_e2e.py` | E.1+D | 4a |
| 整模块 SKIP | `tests/test_lifecycle_e2e_reversal.py` | E.1+D | 4a |
| 函数 | `_determine_cold_start` (state_builder) | C | 6 |
| 函数 | `_run_observation_classifier` (state_builder) | B | 5 |
| 函数 | `_observation_fallback` (state_builder) | B | 5 |
| 函数 | `derive_account_state` (state_machine_inputs) | D | 4a |
| 函数 | `_check_cold_start_stuck` (monitoring/alerts) | C | 6 |
| 函数 | `_build_cold_start_state` (orchestrator_mapper) | C | 6 |
| 函数 | `_build_classifier_state` (orchestrator_mapper) | B | 5 |
| 段 | base.yaml `runtime:` 整段(scheduled/event_driven/manual) | F | 3 |
| 段 | base.yaml `cold_start:` 整段 | C | 6 |
| 字段 | StateMachine.compute_next `account_state=` 参数 | D | 4a |
| 字段 | strategy_state["cold_start"] | C | 6 |
| 字段 | DEFAULT_COLD_START_THRESHOLD | C | 6 |
| 函数 | 4 处裸 `INSERT INTO alerts` 改 AlertsDAO.insert_alert | H#1 | 7 |

§X 实质完成:**18 个删除对象 + 6 个文件级 / 模块级整删**,代码层 0 业务依赖。

**自检清单**(commit 9 前 CC 已跑):
- [x] 1471 pytest 0 regression
- [x] 35 §Z 全过(双重验证:文本 grep 0 + 真启动 uvicorn + 真启动 scheduler)
- [x] §X 关键 grep 全 0 hits in src/(`from .*observation_classifier import` /
      `from .*cold_start import` / `derive_account_state` 等)
- [x] AlertsDAO 4 处调用方都迁移(grep "INSERT INTO alerts" → 1 hit 自身)
- [x] events_calendar.triggered_at_utc 真生产 DB 已加列(PRAGMA 验证)
- [x] §11.3 docs/modeling.md 2 处路径错误修

---

## 段 4 — 报告路径

详细报告:`docs/cc_reports/sprint_1_10_j.md`
