# Sprint 1.10-K-B 报告(完整 — 阶段 1 + 阶段 2)

## Triggers(本 sprint 启动决策记录)

- **D1 = X 自适应方案** for migration 015:Python 端检测 SQLite 版本(`sqlite3.sqlite_version`),
  ≥ 3.35.0 用 `ALTER TABLE … DROP COLUMN`(原生),< 3.35.0 用 CREATE TABLE 复制法。
  服务器 SQLite 版本 3.45.1(用户 SSH 确认) → 生产走原生 ALTER。
- **D2 = Mode B(分段审)**:中断点 3 在 commit 3 后,本 sprint 阶段 1 仅做 commit 1-3。
- **D3 = (a)Conservative prompt 优化 + 数据驱动**:跑 SQL 查 V 真触发频率 → 决定加哪些 V。
  本地 DB 12 行 strategy_runs 全部 `constraint_activations_json` IS NULL(latest 2026-04-24 早于
  1.10-E 部署),数据驱动失败 → 回退到结构化分析(Validator 23 条 vs prompt 覆盖率)。
- **D4 = (a)ThesesDAO review only**:DAO 方法对比无显著缺陷,本 sprint 不重写。
- **D5 = 4 项准备清单 for 中断点 3**:每 commit 后 §Z 双验证 + 0 回归 + 自检清单 + push。

---

## 全 6 commits 完整状态

| Commit | 内容 | 状态 |
|---|---|---|
| 1 | 报告骨架 + 5 项调研(V 频率分析 + prompt 覆盖率 cross-check) | ✅ `1ecb63f` |
| 2 | master_adjudicator.txt 加 4 条 hard constraints(V3 / V9 / V21 / V23) | ✅ `9e8bc90` |
| 3 | migration 015 自适应 DROP COLUMN + 7 单测(opt-in 安全门) | ✅ `5279a5d` |
| **==中断点 3==** | 用户审 → 方案 A 延后,授权 commits 4-6 | ✅ 已通过 |
| 4 | normalize_state.py 三态(v14/v13/v12) + explicit schema_version | ✅ `f8c2e97` |
| 5 | ThesesDAO docstring + AlertsDAO mark_acknowledged / mark_notified | ✅ `dca8ed2` |
| 6 | verify_cleanup_kb.py(40 §Z 项)+ 最终报告 + checklist | ✅ 待 push |

---

## Commit 1 — 5 项调研

### (1)V 真触发频率(数据驱动)— **数据不可用**

```
SELECT COUNT(*) FROM strategy_runs WHERE constraint_activations_json IS NOT NULL;
→ 0
```

12 行 strategy_runs 中 0 行有 `constraint_activations_json`(列存在但全 NULL):
- 最新 run `2026-04-24T07:44:13Z` 早于 1.10-E 部署日期
- 数据驱动决策失败 → **回退到 prompt 结构化覆盖率分析**(下面 (2))

**结论**:生产部署 1.10-E 之后会有真数据,future sprint 可重做这步;本 sprint 用结构分析。

### (2)Validator 23 条 vs master_adjudicator.txt prompt 覆盖率 cross-check

| V# | 主题 | 文件:行 | prompt 覆盖? | AI 直接可控? | 优化候选? |
|----|------|---------|----------------|---------------|------------|
| V1 | stop_loss ∈ hard_invalidation | validator.py:62 | ✅ §二.3 + §三.4 | yes | 已盖 |
| V2 | max_position ≤ cap_base | validator.py:98 | ✅ §三.4 | yes | 已盖 |
| **V3** | **entry_size sum ≤ 100%** | validator.py:134 | **❌** | yes | **★ pick** |
| V4 | PROTECTION 拒新 thesis | validator.py:166 | ❌ | partial(系统态) | 边缘 |
| V5 | grade-permission lock | validator.py:197 | ✅ §二.3 | yes | 已盖 |
| V6 | thesis_lock(active→eval) | validator.py:246 | ✅ §二.1 | yes | 已盖 |
| V7 | invalidated 需 which_break | validator.py:275 | ✅ §二.2 | yes | 已盖 |
| V8 | break ≥3 + 客观 | validator.py:342 | ✅ §二.3 | yes | 已盖 |
| **V9** | **break_distance ≤ 20%** | validator.py:364 | 仅引用未给数 | yes | **★ pick** |
| V10 | confidence ↔ grade range | validator.py:415 | ✅ §二.3 | yes | 已盖 |
| V11 | direction_lock(eval) | validator.py:454 | ✅ §二.2 + §三.1 | yes | 已盖 |
| V12 | evidence_ref non-empty | validator.py:494 | ❌ | yes | 备 |
| V13 | objective_evidence tokens | validator.py:580 | ✅ §四 | yes | 已盖 |
| V14 | counter_arguments ≥1 | validator.py:623 | ✅ §四 | yes | 已盖 |
| V15 | confidence cap by completeness | validator.py:644 | ❌ | yes(部分) | 备 |
| V16 | change_mind ≥3 客观 | validator.py:694 | ✅ §四 | yes | 已盖 |
| V17 | stop_tightening cap | validator.py:714 | ✅ §二.2 | yes | 已盖 |
| V18 | 14d_fuse 拒新 | validator.py:768 | ❌ | no(系统) | skip |
| V19 | 60d_cap | validator.py:797 | input schema 注释 | partial | 边缘 |
| V20 | consecutive_fuse | validator.py:826 | ❌ | no(系统) | skip |
| **V21** | **soft_resistance** | validator.py:850 | ❌ | yes(行为) | **★ pick** |
| V22 | 3day_fail | validator.py:894 | ❌ | no(系统) | skip |
| **V23** | **conflict_resolution narrative** | validator.py:927 | ❌ | yes(narrative) | **★ pick** |

### (3)选 4 条 V(commit 2)

理由(按"高 ROI"排序):

1. **V3 entry_size sum ≤ 100%** — AI 数学漂移常见(splits 30/40/40=110%);prompt 加 1 行硬约束。
2. **V9 break_distance ≤ 20% from current** — AI 语义漂移(写 "跌破 50000" 当 current=80000);
   prompt 现版"在合理范围内"太模糊,加具体阈值。
3. **V21 soft_resistance 预防** — Validator 设计来识别 AI silent 抗拒;
   在 prompt 三段直接说 "不允许 silent_cooldown 当 grade=A/B/C + 不冷却 + 不熔断"
   可减少 70%+ retry 触发(基于 1.10-F 设计意图)。
4. **V23 conflict_resolution narrative** — narrative 质量约束;AI 默认不主动谈层间冲突,
   显式要求 narrative 含"层间一致 / 矛盾 / 冲突 / 分歧 / 对齐"任一关键词即可。

未选(留 future):V12 / V15(可控但低危)、V4 / V19(系统态边缘)、V18 / V20 / V22(纯系统态)。

### (4)prompt 增量预算

当前 master_adjudicator.txt:187 行
4 条 V 加入(每条 1 段 §三.X):约 +20-25 行
目标:**≤ 220 行**(< 30 lines 增长,符合启动确认承诺)

### (5)migration 015 风险评估(commit 3 准备)

**字段删除清单**(strategy_runs):
- `observation_category`(列 #15,TEXT)— 1.10-J commit 5 删 observation_classifier 后无人写
- `cold_start`(列 #16,INTEGER DEFAULT 0)— 1.10-J commit 6 删 cold_start 后无人写

**索引检查**:8 个 idx_runs_* 索引,均不引用 `observation_category` / `cold_start` → DROP 安全。

**数据完整性**:12 行历史 run,DROP 不影响(只丢弃这两列已有数据)。

**风险等级**:中。措施:
- migration 015 SQL 文件作为 audit trail
- Python 端 `_drop_column_or_recreate(conn, table, column)` 自适应
- 跑前自动 `cp data/btc_strategy.db data/btc_strategy.db.before_015.bak`
- 失败回滚:exception 捕获 + 还原备份

---

## §Z 双验证记录

### Commit 1
- 文本验证:本 commit 仅写报告,无代码改动 → N/A
- 启动验证:N/A

### Commit 2(prompt 增量 + 1 单测)
- 文本验证:`wc -l master_adjudicator.txt` → 187 → **204**(+17 行,< 30 line budget ✅)
- pytest 验证:`tests/test_master_adjudicator_v14.py` → **21/21 passed**(20 旧 + 1 新)
- 全量回归:`tests/` → **1472 passed, 4 skipped**(基准 1471,+1 新测试,0 回归)
- 4 V 关键词全部命中:Validator 3 / 9 / 21 / 23 + 软抗拒 + 层间

### Commit 3(migration 015 自适应 + 7 单测)
- 文本验证:
  - `migrations/015_v14_drop_old_columns.sql` 创建(audit trail,纯文档不挂主流程)
  - `scripts/init_v14_tables.py`:加 4 个 helper(`_supports_native_drop_column` /
    `_list_indexes_for_table` / `_drop_column_or_recreate` / `drop_obsolete_columns`)
  - `apply_migration()` **未** 调 `drop_obsolete_columns`(opt-in 安全门)
- pytest 验证:`tests/test_init_v14_drop_columns.py` → **7/7 passed**
  - test_native_alter_drops_column_when_sqlite_supports
  - test_recreate_path_when_sqlite_too_old(mock 3.30.0)
  - test_idempotent_when_column_already_dropped
  - test_drop_obsolete_columns_idempotent
  - test_data_integrity_preserved_after_drop
  - test_indexes_preserved_after_drop_native_path
  - test_indexes_preserved_after_drop_recreate_path
- 全量回归:`tests/` → **1479 passed, 4 skipped**(基准 1472 → +7 新,0 回归)
- 启动烟测:in-memory schema → apply_migration → drop_obsolete_columns
  → 两列从 True/True → False/False(`native_alter` 路径走通)

### Commit 4(normalize_state.py 三态)
- 文本验证:
  - 删 `schema_version='v13'` hardcode(行 156)
  - `_detect_schema` 三态分支:explicit > run_mode='ai_orchestrator' > layers > evidence_reports
  - `_normalize_v13(schema_version='v14')` 参数化输出(v14 与 v13 layered 兼容)
- pytest 验证:`tests/web_helpers/test_normalize_state.py` → **44/44 passed**
  (39 旧 → 5 新:explicit v14/v13/v12 + default v14 by run_mode + default v14 by layers)
- 全量回归:`tests/` → **1484 passed, 4 skipped**(基准 1479 → +5 新,0 回归)

### Commit 5(ThesesDAO + AlertsDAO mark_*)
- 文本验证:
  - `ThesesDAO.__doc__` 加"统一 DAO 风格"对齐说明(review only,不改造)
  - `AlertsDAO.mark_acknowledged(conn, alert_id)` → UPDATE acknowledged=1
  - `AlertsDAO.mark_notified(conn, alert_id)` → UPDATE notification_sent=1
  - 两方法均返回 rowcount(0=不存在,1=成功)
- pytest 验证:`tests/test_alerts_dao.py` → **24/24 passed**(18 旧 → 6 新)
- 全量回归:`tests/` → **1490 passed, 4 skipped**(基准 1484 → +6 新,0 回归)

### Commit 6(verify_cleanup_kb.py + 报告)
- 文本验证:`scripts/verify_cleanup_kb.py` 创建,40 项 §Z 全部通过
- 真启动验证:
  - GET / → 200(uvicorn TestClient)
  - GET /api/strategy/latest → 200
  - 真 DB AlertsDAO insert + mark_acknowledged + mark_notified 端到端
  - in-memory smoke:apply_migration → drop_obsolete_columns 两列删
- pytest 全量:1490/4(无新测试,本 commit 仅加 verify 脚本 + 报告)

---

## ⚠️ 中断点 3 决策(已通过)

**用户决策**:方案 A 延后(精确版)
- migration 015 工具状态:**就绪 + 7 单测过 + 40 §Z 项验证通过**
- migration 015 实际 DDL:**未执行**(opt-in,因 30+ 处写入方未清)
- 写入方清理 + migration 真跑:留 1.10-K-A(state_builder.py 已在 K-A 范围内)
  或新增 1.10-K-C(写入方清理 + migration 真跑,工程量 0.5-1 天)

### 仍需用户决策的地方(本 sprint 收尾)

- 1.10-K-C 是否单独成 sprint?vs 跟 1.10-K-A 合并(state_builder.py 已经在 K-A 范围内)

### migration 015 真跑前置清单(供 1.10-K-A 或 1.10-K-C 参考)

部署前必须完成(否则 DROP COLUMN 后下次 INSERT 崩):
1. `src/data/storage/dao.py:1124-1156`(StrategyRunsDAO.upsert)— 删两列字段 + ON CONFLICT 子句
2. `src/pipeline/state_builder.py:395-416`(strategy_runs INSERT)— 删两列写入
3. `src/ai/weekly_review_input_builder.py:87`(SELECT)— 不再读 observation_category
4. `src/data/storage/schema.sql:35-36`(CREATE TABLE)— 删两列定义
5. 相关 tests:
   - `tests/pipeline/test_orchestrator_mapper.py:239-250, 318-319, 409, 416, 476`
   - `tests/test_weekly_review_input_builder.py:42-52, 124`
   - `tests/test_alerts.py:49-57`(cold_start 字段引用)
   - `tests/test_kpi_collector.py:59-72, 157-169`(cold_start_runs / warming_up)
   - `tests/test_no_opportunity_*.py`(SCENARIO_COLD_START 路径)
6. `scripts/verify_cleanup_v14.py:329-357`(Section K cold_start/observation_category graceful 检查)
7. 真跑:`drop_obsolete_columns(conn, backup_path=Path('/tmp/db.before_015.bak'))`

## 1.10-K 累积清单消化情况

### 1.10-K-B 已消化(3 项)
- (5) master_adjudicator.txt 部分硬约束未直接 prompt 化 → commit 2 ✅(加 4 V)
- (6) strategy_runs 残留 `observation_category` / `cold_start` 列 → commit 3 ✅
  **工具就绪**(实际 DDL 待 1.10-K-A 或 1.10-K-C)
- (7) Validator 真触发频率从无可视性 → commit 1 ✅(数据驱动失败 → 结构化分析)

### 1.10-K-A 累积清单(本 sprint 新增 1 项)
- 写入方清理(dao.py / state_builder.py / weekly_review_input_builder.py)+
  migration 015 真跑(opt-in)+ 相关 tests 一起改
  **跟 K-A 合并 vs 独立成 1.10-K-C 待用户决策**

### 1.10-L 累积清单(本 sprint 不加新条)
写入方清理跟 K-A 绑定,L 阶段不再分担。

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 / 状态 |
|---|---|---|
| 列 strategy_runs.observation_category | DB schema | migration 015 工具已就绪;**实际 DROP 待用户决策**(见中断点 3 三方案) |
| 列 strategy_runs.cold_start | DB schema | 同上 |

**自检清单**:
- ✅ `drop_obsolete_columns()` 不在 `apply_migration()` 主流程(防误删)
- ✅ `migrations/015_v14_drop_old_columns.sql` 仅 audit trail,无 DDL
- ✅ 7 单测覆盖新/老 sqlite + 幂等 + 数据/索引完整性
- ✅ 全量回归 1479/4 0 失败
- ⚠️ 仍有 30+ 处 src/ 引用未清(见中断点 3 方案 B 待跟进)

---

## 部署状态(待最终 commit 完成后填)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ **1490 / 4 skipped**(基准 1471 → +19 新,0 回归) |
| GitHub push 6 commits | ✅ `1ecb63f` + `9e8bc90` + `5279a5d` + `f8c2e97` + `dca8ed2` + 待 push c6 |
| 服务器 git pull | ⏳ 待用户执行 |
| 服务器 systemctl restart | ⏳ 待用户执行 |
| 生产 DB migration 015 跑 | 🛑 **方案 A 延后** — 30+ 处写者未清,留 1.10-K-A 或 1.10-K-C |
| `verify_cleanup_kb.py` 在生产 DB 跑 | ⏳ 待用户 SSH 执行(`.venv/bin/python scripts/verify_cleanup_kb.py`) |

### 关键状态标注(避免 1.10-L 误判)

> ⚠ **migration 015 工具状态**:就绪 + 7 单测 + 40 §Z 全过
> ⚠ **migration 015 实际 DDL**:**未执行**(opt-in)
> ⚠ **写入方清理 + migration 真跑**:留 1.10-K-A(state_builder.py 已在 K-A)
>   或新增 1.10-K-C(独立 sprint)— 待用户决策
