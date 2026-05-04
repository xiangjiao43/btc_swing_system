# Sprint 1.10-K-B 报告(进行中 — 阶段 1)

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

## 阶段 1 计划(commits 1-3,Mode B 中断点 3)

| Commit | 内容 | 状态 |
|---|---|---|
| 1 | 报告骨架 + 5 项调研(V 频率分析 + prompt 覆盖率 cross-check) | ✅ `1ecb63f` |
| 2 | 任务 1+2:master_adjudicator.txt 加 4 条 hard constraints(V3 / V9 / V21 / V23) | ✅ 进行中 push |
| 3 | 任务 3:migration 015 自适应 DROP COLUMN + 单测 | 待 |
| **==中断点 3==** | 用户审 → 授权才进 commit 4-6 | — |

**绝对不做**(本批次):commits 4-6(normalize_state v14 detect / ThesesDAO 微调 / AlertsDAO mark_*)。

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

## 1.10-K 累积清单(本 sprint 内消化的 7 项,1.10-K-A 已消化 4,1.10-K-B 消化 3)

详见 `docs/cc_reports/sprint_1_10_ka.md` 的 1.10-K 累积清单。本 sprint 拟消化:
- (5) master_adjudicator.txt 部分硬约束未直接 prompt 化 → commit 2
- (6) strategy_runs 残留 `observation_category` / `cold_start` 列 → commit 3
- (7) Validator 真触发频率从无可视性 → commit 1 调研 + 文档化

## 本 sprint 删除清单(待 commit 3 完成后填)

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 列 strategy_runs.observation_category | DB schema | 1.10-J commit 5 后无人写,通过 migration 015 清理 |
| 列 strategy_runs.cold_start | DB schema | 1.10-J commit 6 后无人写,通过 migration 015 清理 |

---

## 部署状态(待最终 commit 完成后填)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ⏳ 待 commit 3 后 |
| GitHub push(commit hash) | ⏳ 待 |
| 服务器 git pull | ⏳ 待用户执行 |
| 服务器 systemctl restart | ⏳ 待用户执行 |
| 生产 DB migration 015 跑 | ⏳ 待用户执行(自动备份) |
