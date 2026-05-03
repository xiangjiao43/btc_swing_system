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

### Commit 1:报告骨架 + 调研 + 路径错误清单 ✅
- hash: `e4da46e`
- `docs/cc_reports/sprint_1_10_e.md`(本文件)

### Commit 2:migration 011 + Validator 1-12 + 34 单测 ✅
- hash: `0850bae`
- migration 011 + init_v14_tables.py 扩展(条件 ALTER strategy_runs.constraint_activations_json)
- src/ai/validator.py 新增 V1-V12 模块级函数
- tests/test_validator_v14_part1.py 34 单测全 pass

### Commit 3:Validator 13-23 + 32 单测 ✅
- hash: `de2aa66`
- src/ai/validator.py 新增 V13-V23 模块级函数
- helper:_objective_evidence_tokens_from_context(D3=a 字符串匹配)
- tests/test_validator_v14_part2.py 32 单测全 pass
- bug 修:V15 cap = 0.699(< 0.7 严格,避 round 边界)

### Commit 4:V24 meta + validate_master_output 入口 + 删 H1-H10 + orchestrator + DAO ✅
- hash: `9fd7143`
- 删 v1.3 AdjudicatorValidator class(263 行 H1-H10)+ HOLDING_STATES + ILLEGAL_TRANSITIONS
- 新增 V24 collect_meta_activations(28 字段 + 4 额外 meta)
- 新增 validate_master_output 入口(顺序应用 V1-V23 + V24 收尾)
- orchestrator 改 import + run_full_a 末尾(装配 validator_ctx 调 validate_master_output → 写 result["constraint_activations"])
- StrategyStateDAO.insert_state 加 constraint_activations_json 列写入
- schema.sql + 集成 12 单测
- 删 obsolete tests:tests/ai/test_validator.py(33 v1.3 H 测试)+ test_orchestrator.py 5 个 H 集成测试

### Commit 5:verify_validator_v14 + 报告 + 2 checklists(本 commit)
- hash: 待 push 后填
- scripts/verify_validator_v14.py(19 项 §Z 断言全 pass + DB 0 残留)
- 4 段总结 + 5 风险 + 2 checklists(1.10-F retry 必备 + 1.10-L V12 严校验)

---

## 部署四件事

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1174 passed, 1 skipped(从 1134 → 1200 → 1162 → 1174:加 78 v14 - 38 obsolete = 净 +40)|
| GitHub push(commit 1-5) | ✅ e4da46e / 0850bae / de2aa66 / 9fd7143 / 待填(commit 5) |
| 服务器 git pull | 待用户(1.10-E 数据 + 业务全, 可跟 1.10-F retry 一起部署) |
| 服务器 systemctl restart | 需要(validator import + DAO insert 改) |
| 端到端真实断言(§Z) | ✅ 19 项全 pass + DB 0 残留 |
| 1.10-L 端到端真 API checklist | 已写 1 项新增(V12 严校验)|

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
1174 passed, 1 skipped, 360 warnings in 7.98s
```

本 sprint 单测变化:
- 新增:test_validator_v14_part1.py(34) + part2.py(32) + integration.py(12) = 78
- 删除:tests/ai/test_validator.py(33,v1.3 H 测试) + test_orchestrator.py 5 个 H 集成 = 38
- 净增:+40 单测

## 段 2 用户验证脚本

```bash
cd ~/Projects/btc_swing_system

# 1. 部署 schema 改动(strategy_runs.constraint_activations_json 字段)
.venv/bin/python scripts/init_v14_tables.py

# 2. 端到端 §Z 验证(Validator 24 条 + V24 meta + DB 写入)
.venv/bin/python scripts/verify_validator_v14.py
# 期望:19/19 ✅ exit 0

# 3.(可选)pytest Validator 全套
.venv/bin/python -m pytest tests/test_validator_v14_part1.py \
    tests/test_validator_v14_part2.py \
    tests/test_validator_v14_integration.py -v
# 期望:78 单测全 pass

# 4. 1.10-A/B/C/D 验证仍跑(向后兼容)
.venv/bin/python scripts/verify_v14_tables.py            # 1.10-A
.venv/bin/python scripts/verify_orders_engine.py         # 1.10-B
.venv/bin/python scripts/verify_thesis_lifecycle.py      # 1.10-C
.venv/bin/python scripts/verify_master_thesis_aware.py   # 1.10-D
```

## 段 3 同类风险扫描

**1.10-D 5 项继承状态**:
- #1 D2 mock 不验证真 prompt 效果 ⚠ 留 1.10-L
- #2 prompt 无 few-shot ⚠ 留 1.10-L 实测后判断是否补
- #3 validate_mode 仅 V6 → 本 sprint **解决**(V1-V23 + V24 全实施,validate_mode stub 仍在 master_adjudicator 但已被 validate_master_output 取代,留 1.10-J 整理)
- #4 fallback 不触发 thesis_aware_fallback ⚠ 仍未解决,**留 1.10-F**(retry 机制 sprint 应在 BaseAgent.analyze 失败时调 thesis_aware_fallback)
- #5 prompt 行数大幅缩减风险 ⚠ 留 1.10-L 实测后回头加 few-shot

**1.10-E 新风险(5 项)**:
1. **V8/V9 客观性 / 距离判定启发式**:_is_objective_break / V9 价格类 ≤20% 用启发式正则,生产真 master AI 可能输边界值(如"BTC 跌破 60000" 当前 80000 → 25%)→ 触发 V9 但 master 可能本意是"远期 break"。1.10-L 真 API 验证后调阈值
2. **V10 confidence_score 范围 hardcode**:80-100/60-80/40-60 在 prompt + V10 都写死,grade-permission 表也分散在 prompt + V5。**单一 source 不一致风险**,1.10-J 提到 v1.4 §3.3.6 的常量提取
3. **V11 direction_lock 用关键词**:仅 narrative 含"反手做空"等关键词触发,master 用别的表达(如"建议平多入空")无法捕。**严校验留 1.10-L**
4. **V12 evidence_ref 轻量校验**(D2=c 决策):本 sprint 只验非空 list[str],严校验"每条 ref 真在 evidence_cards"留 1.10-L(已加 checklist)
5. **V13 字符串匹配 false positive 风险**:tokens 含 input 数值如 "100"(initial_capital),master 提到 "成功率 100%" 可能错误命中。短数字 token 应过滤(< 4 位)— 留 1.10-L 端到端实测后调

## 段 4 详细报告路径

`docs/cc_reports/sprint_1_10_e.md`(本文件)。

---

# 1.10-F 端到端 checklist(retry 机制必备项)

**1.10-F sprint 启动时,retry 机制必须实施以下 5 项**(对应 V8/V9/V11/V21 的 "重试 1 次" 语义 + V22 "连续 3 天失败")。

## 必实施 5 项

1. **V8 break_objectivity 重试**:`activations.validator_8_break_objectivity=True` → 触发 1 次重试(temperature 0.4 → 0.6,prompt 加"上次输出 break_conditions 含主观词,请重出"提示)。再失败 → fallback 不创建 thesis(silent_cooldown)。

2. **V9 break_distance 重试**:同 V8 模式,触发条件 `activations.validator_9_break_distance=True`。

3. **V11 direction_lock 重试**:`activations.validator_11_direction_lock=True` → 1 次重试(prompt 加"上次 narrative 含方向反转 hint,请重写")。再失败 → fallback `thesis_aware_fallback(has_active_thesis=True)` 保留旧 thesis。

4. **V21 soft_resistance 重试**:`activations.validator_21_soft_resistance=True` → 1 次重试(prompt 加"系统检测满足创建条件,请明确出 mode=new_thesis 或解释为何 silent")。再失败 → 标 fallback,**不强制创建**(避免规则错误关键决策)。

5. **V22 3day_fail → review_pending**:`activations.validator_22_3day_fail=True` → 调 `src/strategy/review_pending.enter_review_pending(reason="validator_22_3day_fail", related_thesis_id=active.thesis_id)`,推 critical 告警。

## retry 机制设计(1.10-F)

按 v1.4 §6.3.2:
- 指数退避:5 / 10 / 20 分钟(3 次重试)
- 短路依赖:某层失败,下层用上次成功结果继续
- 2 小时窗口:超过 2h 仍未恢复 → fallback Level 2,不调 AI

## 1.10-L 端到端真 API checklist 增量(D2=c 补充)

**1.10-D 已有 8 项 checklist**(mode 真生成 / mode 与 active_thesis 对齐 等)。**1.10-E 新增 1 项**:

9. **Validator 12 evidence_ref 真实性严校验上线**(D2=c 延后契约):
   - 真 API 生成 evidence_cards(card_id 列表)
   - master 输出 evidence_ref(应是 card_id)
   - V12 严校验 → 每条 ref 真在 evidence_cards 中,违规走覆盖(从 primary_drivers 删除)
   - 与 1.10-D Validator 6 严校验一脉相承,确保延后但不忘

## v1.4 §11.3 文档路径错误清单(待 1.10-J 修)

| # | v1.4 §11.3 文档路径 | 真实路径 | 发现 sprint |
|---|---|---|---|
| 1 | `src/ai/adjudicator.py` | `src/ai/agents/master_adjudicator.py` | 1.10-D |
| 2 | `src/decision/validator.py` | `src/ai/validator.py` | 1.10-E |

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| `src/ai/validator.py` 旧 v1.3 H1-H10 实施(class AdjudicatorValidator 内部 H1-H10 方法 + ILLEGAL_TRANSITIONS 14 档常量) | `src/ai/validator.py:18-300` | D1=a + §X:旧 H1-H10 字段语义(action/state/grade/14 档)与新 V1-V24(mode/thesis-aware)不能共存 |
| `HOLDING_STATES` / `ILLEGAL_TRANSITIONS` 14 档常量 | `src/ai/validator.py:18-29` | 14 档枚举属 v1.4 §11.2 删除范围(代码层 prompt 已在 1.10-D 删) |

orchestrator.py line 154 调用 `self._validator.validate(...)` 改为 `validate_master_output(...)`(新接口,本 sprint commit 4 同步改)。

state_builder 写 strategy_runs 时同步写 constraint_activations_json(commit 4)。
