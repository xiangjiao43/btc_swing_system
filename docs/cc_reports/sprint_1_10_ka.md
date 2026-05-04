# Sprint 1.10-K-A 报告(进行中 — 阶段 1)

**最大架构级 sprint**:写入方清理 + migration 015 真跑 + state_machine 主体重写
+ FLIP_WATCH/POST_PROTECTION_REASSESS 主体逻辑删 + narrator 重写 + 9 测试改造。

工程量预估 4-5 天,14 commits,4 中断点(模式 B 分段审)。

## Triggers(本 sprint 启动决策记录)

### P0 决策(用户拍板,2026-05-04)

#### P0 #1 = 方案 C(混合)— 14 档枚举字符串保留 + thesis dict 镜像
- **保留**:14 档枚举字符串(LONG_OPEN/HOLD/etc.)在 compute_next 输出 +
  state_builder summary + _orchestrator_mapper / web/assets/app.js 不强制改
- **删除**(本 sprint):
  - `_from_FLIP_WATCH` 整函数(state_machine.py:791-856,~66 行)
  - `_from_POST_PROTECTION_REASSESS` 整函数(state_machine.py:877-899,~23 行)
  - `_calc_flip_watch_bounds` 整函数(state_machine.py:304-334)
  - `_PPR_ALLOWED_TARGETS` 常量(state_machine.py:72)
  - `_on_enter_effects` PROTECTION/PPR/FLIP_WATCH 三个分支(state_machine.py:413-426 + 405-412)
  - `_verify_disciplines` PPR→PLANNED / PPR→PROTECTION 拒绝分支(state_machine.py:944-956)
    → 改 review_pending 路由
  - `state_machine_inputs._flip_watch_bounds_state` (521-542)
  - `state_machine_inputs._prev_cycle_side` (545-569)
- **新增**(向后兼容):compute_next 输出 schema 加
  ```python
  {
      previous_state: 'LONG_PLANNED', current_state: 'LONG_OPEN',  # 14 档保留
      thesis: {direction: 'long', lifecycle_stage: 'opened', status: 'active'},  # 新增
      system_state: 'normal' | 'PROTECTION' | 'review_pending',  # 新增
      ...
  }
  ```
- **测试改造范围**:~20 个(test_state_machine.py 43 个里 ~10,test_state_machine_inputs.py
  26 个里 ~6,SKIP 2 文件 unskip + 重写,narrator 测试 ~4)

#### P0 #2 = lifecycle_manager → ThesesDAO 接通**不含**,留 1.10-L
- K-A 不动 lifecycle_manager.compute_post_sm 写 theses 表逻辑
- 1.10-L checklist 加:lifecycle_manager 关闭流程接通 ThesesDAO.create
  (closed thesis 写 theses 表)
- 工程量预估 0.5 天,留 1.10-L

### P1 决策

#### P1 #1 = **方案 A 不动索引**(用户 2026-05-04 重决策)
- **背景**:CC 启动确认报告 §4.10 写 "本地 4 vs schema.sql 7 索引",事实错(`PRAGMA index_list | wc -l` 误读 header)
- **真相**:本地 + 生产都已 7 个 idx_runs_* 索引齐全(action_state / ai_model /
  flavor / reference / rules_version / time / trigger),与 schema.sql 完全匹配
- **决策**:commit 2 **不动索引**,不加 IF NOT EXISTS 防御层(无意义代码)
- **migration 015 真跑标准**:本地 7 → 7,生产 7 → 7(commit 4 验证统一)
- **verify_cleanup_ka.py**(commit 13)加 §Z 断言:索引数 = 7

#### P1 #2 = 索引差异自捕事实更正
- 1.10-K-A 启动调研报告里若有"本地 4 索引"措辞,以本决策为准修订
- 教训:统计性命令(`wc -l` / `COUNT`)输出含 header 时易误读,后续优先用
  `SELECT name FROM sqlite_master ORDER BY name` 直查名字而非数

### 数据驱动评估
- 服务器 strategy_runs 136 行(用户 SSH 确认)+ **0 行 constraint_activations_json 非 NULL**
- 1.10-E V24 meta 字段仍未真触发(冷启动期间 V1-V23 大多 silent)
- **本 sprint 不依赖数据驱动**,verify 不强求 V 触发数据

---

## 14 commit 计划 + 4 中断点(模式 B 分段审)

| # | 内容 | 影响文件 | 中断点 |
|---|---|---|---|
| **阶段 1:写入方清理 + migration**| | | |
| 1 | 启动 + 报告骨架 + 接受 P0/P1 决策 | 1 | ✅ `9d26b73` |
| 2 | dao.py + schema.sql + state_builder + orchestrator_mapper + weekly_review + 4 测试 fixture(scope 扩展)| 9 | ✅ `ee46335` |
| 3 | 残留 §X 注释压缩 + §Z 三重验证(中断点 4 准备)| 3 | ✅ `4b3f8bf` |
| **==中断点 4:写入方清理完成,1490+ 测试 0 regression==**| | | ✅ 已通过 |
| 4 | migration 015 本地真跑(备份 + DROP + 21→19 / 12→12 / 7→7 + verify K 段更新)| 3 | ✅ 待 push |
| **==中断点 5:migration 015 真跑后,本地 + 生产 21→19 列==**| | | 🛑 |
| **阶段 2:state_machine 重写**| | | |
| 5 | _from_FLIP_WATCH 整删 + _calc_flip_watch_bounds 删 + _on_enter_effects FLIP_WATCH 分支删 + state_machine_inputs._flip_watch_bounds_state + _prev_cycle_side 删 | 2 | — |
| 6 | _from_POST_PROTECTION_REASSESS 整删 + _PPR_ALLOWED_TARGETS 删 + _on_enter_effects PPR 分支删 + _verify_disciplines PPR 拒绝分支改 review_pending 路由 | 1 | — |
| 7 | compute_next 输出 schema 加 thesis dict + system_state 字段(方案 C 关键)+ 上游 _orchestrator_mapper 加镜像 | ~3 | — |
| **==中断点 6:commit 7 完成,thesis dict + system_state 输出验证==**| | | 🛑 |
| **阶段 3:测试改造 + narrator + verify**| | | |
| 8 | test_state_machine.py 43 测试改造(删 FLIP_WATCH / PPR transition assertion)| 1 | — |
| 9 | test_state_machine_inputs.py 26 测试改造 + test_lifecycle_manager.py 19 review | 2 | — |
| 10 | test_state_machine_e2e.py UNSKIP + thesis-driven e2e 重写 + test_lifecycle_e2e_reversal.py UNSKIP + 反向重写 | 2 | — |
| 11 | test_no_opportunity_narrator.py 14 + test_no_opportunity_8_scenarios.py 8 改造 | 2 | — |
| 12 | narrator.py 重写(_gen_cold_start 整删 / SCENARIO_POST_PROTECTION 改 review_pending)+ test_orchestrator_mapper.py 36 review | 3 | — |
| **==中断点 7:commit 12 完成,准备 verify==**| | | 🛑 |
| 13 | scripts/verify_cleanup_ka.py(50+ §Z 含真触发 strategy_run e2e)| 1 | — |
| 14 | 最终报告 + 1.10-K-A 累积清单结清 + 1.10-L checklist | 1 | — |

**4 个中断点**:写入方完成(c3 后)/ migration 真跑(c4 后)/ state_machine 重写(c7 后)/ verify 准备(c12 后)。

**绝对不做**(本批次 commit 1):commit 2-14 全部。

---

## 7 项启动确认调研归档

### 1. v1.4 文档阅读

✅ §3.3.1-3.3.9(9 个 AI 职责)+ §4.1.1-4.1.5(状态空间 + **§4.1.5 14↔5 映射表逐行**)
+ §4.2.1-4.2.9(9 条 transition)+ §4.3.1-4.3.5(反手 3 档 + 14 天熔断 + 3 纪律)
+ §5.3.1-5.3.7(thesis 表 + 失效 + weakened + review_pending 三出口)+ §11.2/§11.3/§11.4。

### 2. SSH 调研结果(本地 grep,生产需用户 SSH 验证)

#### 2.1 state_machine.py 函数职责图(1194 行,31 entity)
- 14 transition 处理函数,**2 个整删**(_from_FLIP_WATCH 791-856 / _from_POST_PROTECTION_REASSESS 877-899)
- 模块常量 6 个,**1 个整删**(_PPR_ALLOWED_TARGETS 72)
- _on_enter_effects 8 状态分支,**3 个删**(PROTECTION 413-420 / PPR 421-426 / FLIP_WATCH 405-412)
- _verify_disciplines 4 段,**2 段改 review_pending 路由**(944-949 PPR→PROTECTION / 951-956 PPR→PLANNED)
- _build_field_snapshot 154 行,**部分清理**(post_protection_next_target / FLIP_WATCH duration 字段)

#### 2.2 state_machine_inputs.py 615 行(23 函数)
- public_entry: build_state_machine_fields (53-216) + apply_inputs_to_strategy_state (219-272)
- **2 函数整删**(_flip_watch_bounds_state 521-542 / _prev_cycle_side 545-569)
- 14 档常量保留(_LONG_STATES / _SHORT_STATES / _HOLDING_STATES,方案 C 关键)

#### 2.3 lifecycle_manager.py 700 行(22 函数)
- 本 sprint **不重写**(留 1.10-L 接 ThesesDAO)
- 14 档 STATES 集合保留(_PLANNED_STATES / _OPEN_STATES / etc.)

### 3. 14 档 ↔ thesis 5 档映射执行计划(方案 C)

| 14 档 | thesis dict 镜像 | system_state |
|---|---|---|
| FLAT | `thesis: None` | `'normal'` |
| LONG_PLANNED | `{direction:'long', lifecycle_stage:'planned', status:'active'}` | `'normal'` |
| LONG_OPEN | `{direction:'long', lifecycle_stage:'opened', status:'active'}` | `'normal'` |
| LONG_HOLD | `{direction:'long', lifecycle_stage:'holding', status:'active'}` | `'normal'` |
| LONG_TRIM | `{direction:'long', lifecycle_stage:'trim', status:'active'}` | `'normal'` |
| LONG_EXIT | `{direction:'long', lifecycle_stage:'closed', status:'closed_profit'/'closed_loss'}` | `'normal'` |
| SHORT_* | mirror | `'normal'` |
| FLIP_WATCH | `thesis: None`(冷却态由 thesis.closed_at 推导) | `'normal'` |
| PROTECTION | `thesis: None`(active thesis 已 closed_protection) | `'PROTECTION'` |
| POST_PROTECTION_REASSESS | `thesis: None` | `'review_pending'` |

实施位置:`StateMachine._build_result` (243-298) 加构造逻辑。

### 4. migration 015 真跑前置 7 项执行步骤

- 4.1 备份本地 + 服务器 DB(commit 4 前)
- 4.2-4.7 写入方清理(commit 2-3,33 处)
- 4.8 调 drop_obsolete_columns(commit 4)
- 4.9 验证 21 → 19 列(commit 4)
- 4.10 验证 12 → 12 行 + 7 → 7 索引(commit 4)
- 4.11 全量 pytest 0 regression + verify_cleanup_v14 / kb 全过(commit 4 后)
- 4.12 错误回滚机制(若失败 mv backup → revert)

### 5. commit 拆分 + 4 中断点(见上面 14 commit 计划)

### 6. 数据驱动评估
- 本地 12 行 / 0 V 数据;服务器 136 行 / 0 V 数据(用户 SSH 确认)
- 不依赖,本 sprint verify 不强求

### 7. 字段歧义 / v1.4 偏离风险
- P0 #1 / P0 #2 / P1 #1 全已用户拍板(见 Triggers)

---

## 33 处写入方清理详细行号(commit 2-3 实施清单)

### Commit 2(dao.py + schema.sql + dao 相关测试)

| 文件 | 行号 | 内容 | 改动 |
|---|---|---|---|
| `src/data/storage/schema.sql` | 17 | 注释提及两列 | 删 |
| `src/data/storage/schema.sql` | 35 | `observation_category TEXT,` | 删 |
| `src/data/storage/schema.sql` | 36 | `cold_start INTEGER DEFAULT 0,` | 删 |
| `src/data/storage/dao.py` | 1124 | `observation = state.get("observation") or {}` | 删 |
| `src/data/storage/dao.py` | 1139 | `observation_category = observation.get(...)` | 删 |
| `src/data/storage/dao.py` | 1140 | `cold_start_flag = 0` | 删 |
| `src/data/storage/dao.py` | 1162-1163 | INSERT 列名 `observation_category, cold_start,` | 改(删两列名 + 调整 VALUES `?` 数 + params)|
| `src/data/storage/dao.py` | 1178-1179 | ON CONFLICT 子句 `observation_category = excluded..., cold_start = excluded...,` | 删 |
| `src/data/storage/dao.py` | 1193-1194 | params `observation_category, cold_start_flag,` | 删 |
| `src/data/storage/dao.py` | 1226 | 注释提及 cold_start 判定 | 改(删 cold_start 提及)|
| **dao 相关测试** | | | |
| `tests/test_weekly_review_input_builder.py` | 42, 47, 52 | INSERT 含 observation_category | 改 / 删 |
| `tests/pipeline/test_orchestrator_mapper.py` | 239-242, 247-250 | observation_category / cold_start always_zero 测试 | 改(测试列已不存在)|

### Commit 3(state_builder + _orchestrator_mapper + weekly_review + 19 测试)

| 文件 | 行号 | 内容 | 改动 |
|---|---|---|---|
| `src/pipeline/state_builder.py` | 13 | docstring 提及 cold_start | 改(措辞精简)|
| `src/pipeline/state_builder.py` | 205-206 | 注释 cold_start_check stage | 删 |
| `src/pipeline/state_builder.py` | 395-396 | INSERT 列名 `observation_category, cold_start,` | 删 |
| `src/pipeline/state_builder.py` | 415-416 | params `mapped["observation_category"], mapped["cold_start"],` | 删 |
| `src/pipeline/state_builder.py` | 506-508 | 注释 cold_start_check stage | 删 |
| `src/pipeline/state_builder.py` | 613 | 注释 observation_category | 删 |
| `src/pipeline/state_builder.py` | 909-910 | 注释 _determine_cold_start | 删 |
| `src/pipeline/state_builder.py` | 943-944 | 注释 cold_start 字段已删 | 删 |
| `src/pipeline/_orchestrator_mapper.py` | 12-16, 56 | 注释 | 改(精简,K-A 完成)|
| `src/pipeline/_orchestrator_mapper.py` | 120-126 | observation_category / cold_start_int = None / 0 | 删 |
| `src/pipeline/_orchestrator_mapper.py` | 150-151 | mapped 字段 | 删 |
| `src/pipeline/_orchestrator_mapper.py` | 181-186, 234 | 注释 _build_cold_start_state / cold_start key | 删 |
| `src/ai/weekly_review_input_builder.py` | 87 | SELECT 含 observation_category | 删 |
| **19 测试** | | | |
| `tests/test_kpi_collector.py` | 59-72, 157-169 | cold_start_runs / cold_start_warming_up 测试参数 | 改(去掉 cold_start_warming_up case 或改 health_status='error')|
| `tests/test_alerts.py` | 49-57, 188-189 | cold_start_runs 参数 + 已删测试注释 | 改 / 清理 |
| `tests/test_no_opportunity_narrator.py` | 34, 38, 42, 45, 49-51, 94-96 | cold_start_warming_up 路由测试 | 改(commit 11-12 narrator 重写一并)|
| `tests/test_no_opportunity_8_scenarios.py` | 69-71, 229 | SCENARIO_COLD_START 测试 | 改(commit 11) |
| `tests/test_human_readable_style.py` | 261-263 | cold_start scenario 参数 | 改 |
| `tests/test_review_generator.py` | 55 | "cold_start": {...} 字段 | 删 |
| `tests/test_virtual_account_manager.py` | 13 | test_cold_start_no_prev_no_fills | 改(测试名重命名,语义保留)|
| `tests/test_web_modules_1_2_3.py` | 80 | cold_start_placeholder 测试 | 改 |
| `tests/test_web_schema_gate.py` | 181 | observation_category fixture | 删 |
| `tests/test_narrative_human_quality.py` | 49 | cold_start_warming_up=False 字段 | 删 |
| `tests/test_plain_reading.py` | 61, 109 | health_status="cold_start_warming_up" | 改(已 1.10-J 改 'error',删剩余引用)|

**总计**:**33 处主代码 + ~15 处测试**,符合用户预期 30+。

---

## §Z 双验证记录

### Commit 1
- 文本验证:本 commit 仅写报告 + 决策记录,无代码改动 → N/A
- 启动验证:N/A

### Commit 2(scope 调整 — 见下面备注)
**实际 scope**(超出原计划"dao.py + schema.sql + dao 测试"):
- `src/data/storage/schema.sql`:删 line 17 注释 + line 35-36 字段定义(3 处)
- `src/data/storage/dao.py:StrategyStateDAO.insert_state`:删 9 处(observation/cold_start 提取 + INSERT 列名 + ON CONFLICT 子句 + params + 注释)
- `src/pipeline/_orchestrator_mapper.py`:删 mapped["observation_category"] / ["cold_start"](2 处 + 8 行注释)
- `src/pipeline/state_builder.py:_v13_path INSERT`:删 INSERT 列名 + params(4 处)
- `src/ai/weekly_review_input_builder.py:_aggregate_strategy_runs`:删 SELECT 含 observation_category(1 处)
- `tests/test_init_v14_drop_columns.py`:_make_conn_with_schema 加 ALTER ADD COLUMN 还原老 schema(模拟 1.10-K-A commit 2 之前生产 DB,验证 DROP 仍可工作)
- `tests/test_weekly_review_input_builder.py:_seed_strategy_run`:删 INSERT observation_category 引用(1 处)
- `tests/pipeline/test_orchestrator_mapper.py`:test_col_16/17 改为"字段不在 mapped" + test_returns_all_19 → 17(3 测试改造)

**为什么 scope 比原计划大**:schema.sql 改动**强制**触发所有 reader/writer 同步改 — 不改的话 in-memory DB 测试会全失败 25 个。这是"production code coupling",不是"test 改造适配"。原计划 commit 2(dao.py only)/ commit 3(其他 writer)的拆分在物理上不可分割。

**§Z 文本验证**:`grep observation_category|cold_start src/data/storage/dao.py src/data/storage/schema.sql src/pipeline/_orchestrator_mapper.py src/pipeline/state_builder.py src/ai/weekly_review_input_builder.py` → 0 hits in INSERT/SELECT/CREATE TABLE 语句(只剩注释引用,详见 §X 注释格式遵循)

**§Z 启动烟测**:in-memory schema → strategy_runs 19 列 → StrategyStateDAO.insert_state rowcount=1 → _aggregate_strategy_runs 返回正确 dict ✅

**全量回归**:`tests/` → **1490 passed, 4 skipped, 0 failed**(基准 1490 → 0 净增,3 测试改造 + 写入方清理后维持)

**commit 3 重新定义**:测试 fixtures 中 cold_start_warming_up / SCENARIO_COLD_START 等纯叙事场景测试残留(~10 测试),不影响生产代码 INSERT/SELECT。本来在 commit 3 计划里的 19 测试改造,大部分已在 commit 2 内顺手完成。commit 3 改为收尾测试残留 + 必要文档。

### Commit 4(migration 015 本地真跑)
**实际执行**:
1. 备份双份:
   - `data/btc_strategy.db.before_015.bak`(固定名,符合用户清单)
   - `data/btc_strategy.db.before_015_20260504_150642.bak`(时间戳归档)
2. 调 `drop_obsolete_columns(conn, backup_path=...)` → 返回
   `{'strategy_runs.observation_category': 'native_alter', 'strategy_runs.cold_start': 'native_alter'}`
3. 验证(对照启动确认验证标准):
   - **列数 21 → 19** ✅(SQLite 3.50.4 走原生 ALTER TABLE … DROP COLUMN)
   - **行数 12 → 12** ✅(零数据丢失)
   - **索引 7 → 7** ✅(idx_runs_action_state / ai_model / flavor / reference / rules_version / time / trigger 全保留)
   - 19 列详情:run_id / generated_at_utc / generated_at_bjt / reference_timestamp_utc /
     previous_run_id / action_state / stance / btc_price_usd / state_transitioned /
     run_trigger / run_mode / fallback_level / system_version / rules_version /
     strategy_flavor / ai_model_actual / full_state_json / constraint_activations_json /
     retry_log_json
4. **K 段 graceful 验证更新**(用户指令 "verify_cleanup_v14 K 段如果因 migration 015 跑通而需要更新,在本 commit 一并更新"):
   - `scripts/verify_cleanup_v14.py:325-365`:K 段从"DAO graceful 写 0/NULL"
     改为"DAO 不再写 cold_start / observation_category 列 + PRAGMA 验证两列已删 + 列数 = 19"
   - `scripts/verify_cleanup_kb.py:164-189`:Section B 烟测从"apply_migration 后两列仍在(opt-in 安全门)"
     改为"K-A 后 schema.sql 不再含两列 → apply_migration 后两列从未存在;模拟老 schema(手动
     ALTER ADD)→ drop_obsolete_columns 仍可工作"

**§Z 三重验证(commit 4)**:
- ✅ **真跑** drop_obsolete_columns 在生产形态本地 DB(非 in-memory)→ 21→19 / 12→12 / 7→7
- ✅ 全量回归:`tests/` → **1490 passed, 4 skipped, 0 failed**(K-A 阶段 1 4 commit 累计基准维持)
- ✅ `verify_cleanup_v14.py` → **37/37 §Z**(K 段 4 项更新后全过)
- ✅ `verify_cleanup_kb.py` → **40/40 §Z**(B 段烟测 5 项更新后全过)

**备份文件**:
- `data/btc_strategy.db.before_015.bak`(2026-05-04 15:06)
- `data/btc_strategy.db.before_015_20260504_150642.bak`(同上,时间戳归档)
- 失败回滚:`mv data/btc_strategy.db.before_015.bak data/btc_strategy.db`(用户可执行)

### Commit 3(残留 §X 注释压缩 + 中断点 4 §Z 三重验证)
**实际 scope**(scope 比 commit 2 小,因 commit 2 已吸收大部分测试改造):

注释压缩(从"1.10-J 留 1.10-K 删列"老状态 → "1.10-K-A commit 2 + 4 已删"新状态):
- `src/pipeline/_orchestrator_mapper.py:12-16`(2 处 docstring)
- `src/pipeline/state_builder.py:13`(1 处 docstring)

**未触动的注释**(memory 教训:§X 解释性注释保留):
- state_builder.py:205-206 / 505-507 / 612 / 908-909 / 942-943 — 含"_determine_cold_start 整删 / cold_start_check stage 已删"是真历史 §X 痕迹,删了未来读代码的人会困惑
- _orchestrator_mapper.py:174-175 / 179 / 227 — 同上
- dao.py:1125 — 本 commit 新写,保留

**未触动的 cold_start_warming_up 测试场景**(per K-A 原计划,改造留 commit 11-12 narrator 重写):
- tests/test_kpi_collector.py:59-72,157-169
- tests/test_alerts.py:49-57
- tests/test_no_opportunity_narrator.py(SCENARIO_COLD_START / SCENARIO_POST_PROTECTION 重写)
- tests/test_no_opportunity_8_scenarios.py
- tests/test_human_readable_style.py / test_review_generator.py / test_virtual_account_manager.py / test_web_modules_1_2_3.py / test_web_schema_gate.py / test_narrative_human_quality.py / test_plain_reading.py
- 这些是 narrator 叙事场景测试,不直接 INSERT/SELECT 已删的列,本 sprint 阶段 3 重写

**§Z 三重验证(中断点 4 准备)**:
- ✅ uvicorn TestClient + GET / → 200 + body 含 'BTC'
- ✅ GET /api/strategy/latest → 200
- ✅ scheduler 启动 → BackgroundScheduler + 10 cron jobs registered
- ✅ _JOB_FUNCTIONS 注册数:14
- ✅ schema.sql in-memory 验证:strategy_runs **19 列**(原 21 - observation_category - cold_start)+ **7 索引**(action_state / ai_model / flavor / reference / rules_version / time / trigger 全)
- ✅ 全量回归:**1490 passed, 4 skipped, 0 failed**(基准维持)

---

## 1.10-K-A 累积清单(本 sprint 内消化 + 待 1.10-L)

### 本 sprint 内消化(K-A)
- (1) 写入方清理 30+ 处 → commit 2-3
- (2) migration 015 真跑 → commit 4
- (3) state_machine 主体重写 → commit 5-7(方案 C)
- (4) FLIP_WATCH / POST_PROTECTION_REASSESS 主体逻辑删 → commit 5-6
- (5) narrator 重写 → commit 11-12
- (6) 9 测试改造 → commit 8-12

### 留 1.10-L(本 sprint 不做)
- (7) lifecycle_manager → ThesesDAO 接通(closed thesis 写 theses 表)— 0.5 天
- (8) 14 档枚举字符串去除(方案 C 当下保留,1.10-L 决定是否进一步清理)
- (9) _orchestrator_mapper.py / state_builder summary / web/assets/app.js 14 档 label 升级(方案 C 渐进迁移)
- (10) master_adjudicator prompt V12 / V15 / V19 等中等可控 V 加入(数据驱动)

---

## 部署状态(待 commit 14 完成后填)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ⏳ 待 |
| GitHub push commits | ⏳ 待(本 sprint 14 commit)|
| 服务器 git pull | ⏳ 待用户执行 |
| 服务器 systemctl restart | ⏳ 待用户执行 |
| 生产 DB migration 015 跑 | ⏳ 待用户执行(commit 4 完成 + 中断点 5 通过后)|
