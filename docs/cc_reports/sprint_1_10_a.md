# Sprint 1.10-A:虚拟账户 + 挂单 + thesis 三表数据层

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`,2132 行)
**Sprint 路径定位**:v1.4 §10.5 第一行 — DB 表 + DAO + 单测,2 天工作量
**前置 sprint**:无 / **后置 sprint**:1.10-B(虚拟账户 + 挂单引擎管理层)

---

## Triggers(偏离建模 / 决策点 / 用户补充)

- 用户 v2 指令(基于 b25cfe6)+ 3 项补充提醒:
  - A: base.yaml 字段名严格 `virtual_account.initial_capital` / `virtual_account.currency`
  - B: `theses.break_conditions` SQL 用 TEXT(JSON 字符串),DAO 写时 json.dumps
  - C: `virtual_orders.expires_at_utc` DAO 计算(读 `base.yaml::virtual_orders.default_expiry_days`)
- 节奏:每 commit push 后等用户"继续"再做下一个,**避免连发 6 commit 后发现路径错**
- migration 编号 `009`(不是用户初稿的 005,b25cfe6 v2 已确认)

---

## 任务 1:事实核查调研结果(不删,只标记)

按 §X 删除纪律,本 sprint 0 删除,只记录现状。下面所有"残留"都归 sprint 1.10-J 集中清理。

### 1.1 v1.2 残留 — 5 个废弃组合因子

**物理文件**:已删除 ✅(`src/composite/` 只剩 `__init__.py` / `_base.py` / `cycle_position.py` / `.gitkeep`)

**字符串引用残留**(50+ 处,主要在以下文件,不是代码调用,是字段名 / DB 列 / 注释):

| factor | 引用文件数 | 主要位置(非自身定义) |
|---|---|---|
| `truth_trend` | 5 | `src/pipeline/state_builder.py` / `src/kpi/metrics.py` / `src/strategy/factor_picker.py` 等 |
| `band_position` | 6 | `src/evidence/_anti_patterns.py` / `src/pipeline/state_builder.py` / `src/kpi/metrics.py` 等 |
| `crowding` | 16 | `src/evidence/_anti_patterns.py` / `src/evidence/pillars.py` / `src/pipeline/state_builder.py` 等 |
| `macro_headwind` | 12 | `src/evidence/_anti_patterns.py` / `src/pipeline/_orchestrator_mapper.py` / `src/pipeline/state_builder.py` 等 |
| `event_risk` | 13 | `src/pipeline/state_builder.py` / `src/evidence/pillars.py` / `src/ai/context_builder.py` 等 |

→ 1.10-J 任务:全 grep + 删字段名 / DB 列 / 注释,确认 0 处遗留。

### 1.2 `observation_classifier` / `observation_category`

**物理文件存在**:`src/strategy/observation_classifier.py`

**引用 7+ 文件**:`src/pipeline/_orchestrator_mapper.py` / `src/pipeline/state_builder.py` / `src/utils/cold_start.py` / `src/data/storage/schema.sql` / `src/data/storage/dao.py` / `src/strategy/__init__.py` / `src/strategy/observation_classifier.py`(自身)

→ 1.10-J 任务:整套删除(v1.4 §11.2 明确)。

### 1.3 `account_state` 真实账户假设

**5 文件引用**:
- `src/pipeline/state_builder.py`
- `src/ai/agents/l4_risk_analyst.py`
- `src/ai/agents/master_adjudicator.py`
- `src/strategy/state_machine_inputs.py`
- `src/strategy/state_machine.py`

→ 1.10-J 任务:删 `account_has_long` / `entry_zone_filled_confirmed_1h` 相关字段(v1.4 §11.2 明确)。

### 1.4 14 档老逻辑(POST_PROTECTION_REASSESS / FLIP_WATCH)

**11 文件引用**:
- `src/pipeline/state_builder.py`
- `src/ai/validator.py`
- `src/ai/agents/prompts/master_adjudicator.txt`(prompt 文件)
- `src/web_helpers/labels.py`
- `src/web_helpers/normalize_state.py`
- `src/strategy/state_machine_inputs.py`
- `src/strategy/state_machine.py`
- `src/strategy/no_opportunity_narrator.py`
- `src/strategy/lifecycle_manager.py`
- `src/strategy/observation_classifier.py`
- (自身文件)

→ 1.10-J 任务:按 v1.4 §4.1.5 14 档↔5 档映射表迁移代码,删旧 14 档枚举,DB 历史行不动(向后兼容)。

### 1.5 主策略 4h 旧逻辑(b25cfe6 v2 新增调研项)

**配置层**:
- `config/scheduler.yaml:11` 注释提"6 档:00:05/04:05/12:05/16:05/20:05 + 08:40"(v1.4 应改为 BJT 16:00 单档)
- `config/scheduler.yaml:26` 注释提"Sprint 2.6-A 老配置(pipeline_run interval 4h + ...)"
- `config/scheduler.yaml:113-127` `pipeline_run_regular` + `pipeline_run_8h_onchain` 2 个 cron entry
- `config/base.yaml:60` `cron_hours_utc: [0, 4, 8, 12, 16, 20]`(v1.4 §11.2 明确删:跟 scheduler.yaml 冲突段)

**代码层**:
- `src/scheduler/jobs.py:53` `def job_pipeline_run(...)`(主函数)
- `src/scheduler/jobs.py:128-146` `job_pipeline_run_regular` + `job_pipeline_run_8h_onchain` 2 个 wrapper(Sprint 2.7-C)
- `src/scheduler/jobs.py:5/94/105/125` 注释 / log 字符串提及 pipeline_run

**测试层**:
- `tests/test_scheduler_2_7_b_collectors.py`(疑似 4h fixture)
- `tests/test_scheduler.py`(同)

**保留不动**(v1.4 §11.2 末段明确):
- `position_health_check: interval: '4h'`(持仓期合法 4h 任务)
- `pipeline_run_8h_onchain` 是 8h 不是 4h(且已 disabled)

→ 1.10-J 任务:全项目 grep `'4h'` / `"4h"` / `每 4 小时` / `interval: 4h`,凡是涉及主策略触发节奏的引用都改/删,留 `position_health_check` 4h 不动。

### 1.6 L4 AI agent 当前状态(b25cfe6 v2 新增调研项)

**物理文件存在 ✅**:`src/ai/agents/l4_risk_analyst.py`(2493 字节,71 行,2026-05-01 创建)

**v1.4 §3.3.4 设计**:L4 是**规则 + AI 协作**(规则给 hard_invalidation_levels 候选 + position_cap_base,AI 选 + 微调 -10% 到 -20%)。

→ **L4 AI 是 v1.4 保留设计,无需清理**。本 sprint 0 改动。1.10-J 也不动。

---

## 任务 2-6 实施记录(commit-by-commit 实时填)

> 每个 commit 完成立即 push + 等用户"继续"再做下一个;每个 commit 在下面对应小节实时填具体改动。

### Commit 1:调研 + 报告骨架(本 commit)

- 写 `docs/cc_reports/sprint_1_10_a.md`(本文件)— 任务 1 全部 6 项调研结果 + 任务 2-6 骨架
- 0 代码改动 / 0 测试改动
- hash: 待 push 后填

### Commit 2:migration 009(待执行)

预计改动:
- 新建 `migrations/009_v14_virtual_account_thesis.sql`
  - `virtual_account`(§5.1.2,15 列 + 1 索引)
  - `virtual_orders`(§5.2.2,13 列 + 2 索引)
  - `theses`(§5.3.2,17 列 + 2 索引)
  - 严格按 v1.4 字段名 / 类型 / 约束,无自由发挥

### Commit 3:VirtualAccountDAO(待执行)

预计改动:
- `src/data/storage/dao.py` 新增 `class VirtualAccountDAO`(insert_snapshot / get_latest / get_history)
- `tests/test_virtual_account_dao.py`(in-memory SQLite + happy/edge)

### Commit 4:VirtualOrdersDAO + ThesesDAO(待执行)

预计改动:
- `src/data/storage/dao.py` 新增 `class VirtualOrdersDAO`(create_order / fill_order / cancel_order / get_pending / get_filled / mark_expired)+ `class ThesesDAO`(create / update_assessment / close / get_active / get_history)
- `tests/test_virtual_orders_dao.py` + `tests/test_theses_dao.py`
- 按用户补充 B/C:
  - `theses.break_conditions` DAO `json.dumps` 写入,`json.loads` 读出
  - `virtual_orders.expires_at_utc` DAO 内计算 `created_at + default_expiry_days * 86400`(读 base.yaml)

### Commit 5:init_v14_tables.py + base.yaml 配置(待执行)

预计改动:
- `scripts/init_v14_tables.py` 幂等初始化(读 base.yaml `virtual_account.initial_capital`,关联最新 strategy_run)
- `config/base.yaml` 新增段(按用户补充 A 字段名严格对齐):
  ```yaml
  virtual_account:
    initial_capital: 100000
    currency: "USDT"
  virtual_orders:
    default_expiry_days: 7
  ```

### Commit 6:verify_v14_tables.py + 报告收尾(待执行)

预计改动:
- `scripts/verify_v14_tables.py`(连真 DB,SQL 断言三表存在 + 索引 + virtual_account 行数 = 1 + initial_capital = 100000)
- 本报告 4 段总结填完

---

## 部署状态四件事清单(commit-by-commit 实时填)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | 待 commit 3/4 完成填 |
| GitHub push | 每 commit 完成立即 push,hash 见上 |
| 服务器 git pull | 1.10-A 不需要服务器部署(纯 DB schema + DAO + 脚本),用户 1.10-B 后再统一部署 |
| 服务器 systemctl restart | N/A 本 sprint |
| 端到端真实断言(§Z) | commit 6 verify_v14_tables.py + 用户 SSH 跑 |

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| (无) | — | §X 纪律:本 sprint 0 删除,任务 1 全部 6 项调研只标记位置,留给 1.10-J 统一清理 |

**本 sprint 无替代关系,无删除项**(纯新增 3 表 + DAO + 单测 + 脚本)。

## 测试记录(commit-by-commit 实时填)

待 commit 3/4 完成填。
