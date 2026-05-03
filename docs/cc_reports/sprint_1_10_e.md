# Sprint 1.10-E:Validator 24 条全部实施 + meta 约束记录

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)§3.4
**Sprint 路径定位**:v1.4 §10.5 第五行 — 1 天工作量
**前置 sprint**:1.10-A/B/C(数据层)+ 1.10-D(master AI thesis-aware,Validator 6 stub 已加)
**后置 sprint**:1.10-F(AI 重试机制,接 Validator 8/9/11/21/22 的"重试 1 次"语义)

---

## Triggers / 决策记录

### 启动确认 4 个 D 用户拍板

- **D1 = a + 路径纠正**:**原地重写 `src/ai/validator.py`**(不新建 `src/decision/validator.py`),理由:避免 orchestrator import 改动副作用 + 与 1.10-D master_adjudicator 路径修正模式一致 + §X 满足
- **D2 = c**:Validator 12 evidence_ref 轻量校验(非空 list[str]),严校验留 1.10-L(已加 1.10-L checklist)
- **D3 = a**:Validator 13 字符串匹配(每条 evidence 含 input 中字段名/数值 token)
- **D4 = a**:Validator 21 只识别(写 `validator_21_soft_resistance: True`),重试机制留 1.10-F

### 节奏

完全放手模式(用户授权一次性跑完 5 commits)。

---

## 任务 1:Validator 现状调研 + DB schema 调研

### Validator 现状

| 项 | 现状(b25cfe6 前) | v1.4 期望 |
|---|---|---|
| `src/decision/validator.py` | **不存在**(用户指令 v1.4 §11.3 提到的路径错误) | 不新建,留 1.10-J 修文档 |
| **`src/ai/validator.py`** | **存在 300 行,v1.3 H1-H10 共 10 条**,被 orchestrator line 79/154 调用 | **原地重写为 v1.4 24 条**(D1=a) |
| `AdjudicatorValidator.validate()` 签名 | `(master_output, l1-5_output, current_state) → {validated_output, violations, passed}` | 新增 `validate_master_output(master_output, context, *, fuse_check) → (validated, activations)` |
| 旧 H1-H10 → 新 V1-V24 字段语义 | H 用 action/state/grade(14 档语义) | V 用 mode/thesis_assessment/new_thesis(thesis-aware 语义) |

**§X 删除**:旧 H1-H10 完整删除(不留双 Validator 体系)。

### DB schema 现状

`strategy_runs` 表(`src/data/storage/schema.sql:19-39`)无 `constraint_activations_json` 字段:
- 现有列:run_id / generated_at_utc / generated_at_bjt / reference_timestamp_utc / previous_run_id / action_state / stance / btc_price_usd / state_transitioned / run_trigger / run_mode / fallback_level / system_version / rules_version / strategy_flavor / observation_category / cold_start / ai_model_actual / full_state_json
- **本 sprint migration 011** 加 `constraint_activations_json TEXT`(JSON serialized)

### v1.4 §11.3 路径错误清单(待 1.10-J 修)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | **1.10-E**(本 sprint) |

---

## 任务 2-6 实施记录(commit-by-commit 实时填)

### Commit 1:报告骨架 + 调研 + 路径错误清单(本 commit)
- hash: 待 push 后填
- `docs/cc_reports/sprint_1_10_e.md`(本文件)

### Commit 2-5:待执行

---

## 部署四件事 / 测试记录(commit-by-commit 实时填)

待 commit 5 完成填。

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| `src/ai/validator.py` 旧 v1.3 H1-H10 实施(class AdjudicatorValidator 内部 H1-H10 方法 + ILLEGAL_TRANSITIONS 14 档常量) | `src/ai/validator.py:18-300` | D1=a + §X:旧 H1-H10 字段语义(action/state/grade/14 档)与新 V1-V24(mode/thesis-aware)不能共存 |
| `HOLDING_STATES` / `ILLEGAL_TRANSITIONS` 14 档常量 | `src/ai/validator.py:18-29` | 14 档枚举属 v1.4 §11.2 删除范围(代码层 prompt 已在 1.10-D 删) |

orchestrator.py line 154 调用 `self._validator.validate(...)` 改为 `validate_master_output(...)`(新接口,本 sprint commit 4 同步改)。

state_builder 写 strategy_runs 时同步写 constraint_activations_json(commit 4)。
