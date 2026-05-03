# Sprint 1.10-D:master AI thesis-aware 改造 + System Prompt 重写

**对齐文档**:`docs/modeling.md` v1.4(commit `b25cfe6`)§3.3.6
**Sprint 路径定位**:v1.4 §10.5 第四行 — 1.5 天工作量
**前置 sprint**:1.10-A(三 DAO)+ 1.10-B(VirtualAccount + Orders)+ 1.10-C(Thesis + Cooldown + Fuse + ReviewPending)
**后置 sprint**:1.10-E(Validator 24 条 + meta 约束记录)

---

## Triggers / 决策记录

### 启动确认 4 个 D 用户拍板

- **D1 = a**:新文件 `src/ai/master_input_builder.py`(独立模块,与 context_builder 关注点分离)
- **D2 = a**:完全 mock 不调真 master AI(留 1.10-L 端到端);**补充**:报告末尾必写 1.10-L checklist(延后但不忘契约)
- **D3 = a**:本 sprint 删干净 prompt 内 14 档枚举(§X + 同步耦合改造);**注意**:代码层 14 档(state_machine.py 等 11 文件)留 1.10-J
- **D4 = a**:轻量验证 mode 字段存在 + 枚举合法(留 1.10-E Validator 24 条统一覆盖其他)

### 关键路径纠正

- 用户指令"src/ai/adjudicator.py"实际**不存在** — 真实路径 `src/ai/agents/master_adjudicator.py`
- 1.10-J 时一并修 v1.4 §11.3 的路径错误
- 本 sprint 用真实路径:
  - `src/ai/agents/master_adjudicator.py`(98 行,继承 BaseAgent)
  - `src/ai/agents/prompts/master_adjudicator.txt`(577 行,v1.2/v1.3 框架)

### 节奏

完全放手模式(用户授权一次性跑完 5 commits)。

---

## 任务 1:master AI 现状调研

| 项 | 现状(b25cfe6 前) | v1.4 期望 |
|---|---|---|
| Master AI 类 | `src/ai/agents/master_adjudicator.py::MasterAdjudicator(BaseAgent)`(98 行) | 改造 `_build_user_prompt` 接 thesis-aware + `_fallback_output` 改 thesis-aware fallback |
| Prompt 文件 | `src/ai/agents/prompts/master_adjudicator.txt`(577 行,v1.2 框架,大量 14 档枚举:line 6/61/63/116/119/121/125/126/128 等) | 整体重写为 v1.4 §3.3.6 5 段 prompt + 删 14 档 |
| Orchestrator | `src/ai/orchestrator.py::AIOrchestrator` 有 `MasterAdjudicator` hook(line 32/75) | **不动**(留 1.10-F retry 改造) |
| Client | `src/ai/client.py::build_anthropic_client`(novaiapi 中转站,`claude-sonnet-4-5-20250929`,300s timeout) | **不动** |
| Context builder | `src/ai/context_builder.py` 算客观指标(EMA/ADX/ATR/funding/onchain),不读业务表 | **不动**;新增独立 `master_input_builder.py` 读业务表 + 装配 |
| L1-L5 agents | `src/ai/agents/l[1-5]_*.py` 全存在 | **不动**(本 sprint 只改 master) |
| Validator | `src/ai/validator.py::AdjudicatorValidator` 已有(orchestrator line 79) | **不动**;v1.4 24 条留 1.10-E 重写 |
| BTC_USE_ORCHESTRATOR | env flag,true 走 orchestrator | **不动** |

### v1.4 §3.3.6 关键澄清

- **C 级也允许创建 thesis**(grade ∈ {A,B,**C**}),但 execution_permission 强制 `ambush_only`(只允许埋伏单)
- **mode 字段三选一**:`evaluate_existing` / `new_thesis` / `silent_cooldown`
- **active_thesis 不为 null 时禁止出 new_thesis**(由 Validator 6 强制,本 sprint 留 1.10-E)

---

## 任务 2:master_input_builder(本 sprint 实施)

新文件 `src/ai/master_input_builder.py`:
- `build_master_input(conn, *, layer_outputs, current_btc_price, now_utc) -> dict`
- 装配 v1.4 §3.3.6 完整 input schema:
  - L1-5 outputs(由调用方传入,不查 DB)
  - active_thesis(ThesesDAO.get_active)
  - current_position(VirtualAccountDAO.get_latest 抽 long/short)
  - pending_orders(VirtualOrdersDAO.get_pending 当前 active thesis)
  - cooldown_state(CooldownManager.is_in_cooldown)
  - fuse_state(FuseMonitor.check_14d_fuse + 60d_cap_count + channel_c_uses)
  - last_5_assessments(ThesesDAO.get_history 取 last_assessment 字段)

## 任务 3:System Prompt 重写(本 sprint 实施)

完整搬 v1.4 §3.3.6 5 段 prompt:
- 你的身份(账户 + 持仓状态变量)
- 你必须做的(mode 三选一 + 各模式约束)
- 你绝对不能做的(5 条硬约束)
- 必须包含的输出元素(objective_evidence / counter / what_change)
- 关于"刚刚好"判断(3 条)

完整删除旧 14 档枚举段(line 116-128 的"四、14 档状态机"段 + line 134 起 5.1 FLAT 起始等所有迁移规则段)。新 prompt 用 thesis lifecycle 5 档(planned / opened / holding / trim / closed)+ mode 字段表达。

## 任务 4:master_adjudicator.py 改造 + fallback thesis-aware

- `_build_user_prompt(context)` 改造:接 master_input dict(含 active_thesis 等),序列化为 prompt
- `_fallback_output()` thesis-aware:
  - 有 active_thesis → mode=evaluate_existing + still_valid=mostly + reasoning="master AI 失败,fallback 保守评估"
  - 无 active_thesis → mode=silent_cooldown + silent_reason="master AI 失败,等下次重试"
- mode 字段轻量校验:解析后检查 mode in {evaluate_existing, new_thesis, silent_cooldown},否则 fallback

**v1.4 §6.4 fallback 真表对齐**(D2 mock 测试覆盖):
| 场景 | fallback |
|---|---|
| 有 active_thesis + master 失败 | 保留 thesis 不评估 |
| 无 active_thesis + master 失败 | silent |

## 任务 5:单元测试(本 sprint 实施)

- `tests/test_master_input_builder.py`(8-10 单测)
- `tests/test_master_adjudicator_v14.py`(10-15 单测,全 mock 不调真 API)

## 任务 6:集成验证脚本(轻量,本 sprint 实施)

`scripts/verify_master_thesis_aware.py`:
- 创建 1 active thesis + 持仓 + 挂单
- 调 build_master_input
- SQL + dict 断言:返回 dict 含 v1.4 §3.3.6 全部字段
- 自清理(prefix `verify_1_10_d_master_*`)
- **不调真 master AI**(D2 锁定)

---

## 实施记录(commit-by-commit 实时填)

### Commit 1:报告骨架 + 现状调研 ✅
- hash: `7c933c9`
- `docs/cc_reports/sprint_1_10_d.md`(本文件)+ master AI 现状调研一览表

### Commit 2:master_input_builder + 11 单测 ✅
- hash: `49c402f`
- `src/ai/master_input_builder.py`(D1=a 独立模块)+ `tests/test_master_input_builder.py`
- 7 字段装配:L1-5 + active_thesis + current_position + pending_orders + cooldown_state + fuse_state + last_5_assessments

### Commit 3:System Prompt 重写 ✅
- hash: `0e290de`
- `src/ai/agents/prompts/master_adjudicator.txt`:577 行 → 187 行(-67%)
- v1.4 §3.3.6 8 段(身份/必须/不能/输出元素/刚刚好/输入 schema/输出 schema/输出格式)
- 14 档枚举全删 grep 0 残留(D3=a)

### Commit 4:master_adjudicator 改造 + thesis-aware fallback + 20 单测 ✅
- hash: `1f0c0e8`
- `src/ai/agents/master_adjudicator.py`:_build_user_prompt 接 thesis-aware /
  _fallback_output 改 mode=silent_cooldown / 加 thesis_aware_fallback / validate_mode 静态方法 / VALID_MODES 常量
- 顺带修 2 个 v1.3 legacy 测试(随 v1.4 schema 迁移自然修)
- D4=a 轻量验证(mode 字段 + active_thesis 一致性,Validator 6 触发)

### Commit 5:verify_master_thesis_aware + 报告 + 1.10-L checklist(本 commit)
- hash: 待 push 后填
- `scripts/verify_master_thesis_aware.py`(端到端 §Z 32 项断言全 pass)
- D2=a 锁定:不调真 master AI(留 1.10-L)
- 报告末尾写入 1.10-L 端到端 checklist(D2 补充契约)

---

## 部署四件事

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1134 passed, 1 skipped(从 1103 + 31 本 sprint:11 + 20 + 0 prompt only) |
| GitHub push(commit 1-5) | ✅ 7c933c9 / 49c402f / 0e290de / 1f0c0e8 / 待填(commit 5) |
| 服务器 git pull | 待用户(1.10-D 是 master AI 改造,可跟 1.10-E Validator 24 一起部署) |
| 服务器 systemctl restart | 需要(prompt 文件改 + master 类改,但 BTC_USE_ORCHESTRATOR 决定是否真路径)|
| 端到端真实断言(§Z) | ✅ verify_master_thesis_aware.py 32/32 + DB 0 残留 |
| 1.10-L 端到端真 API 调用 | ❌ **本 sprint 不做**(D2=a 锁定,1.10-L checklist 写入本报告末尾) |

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
1134 passed, 1 skipped, 360 warnings in 8.64s
```

本 sprint 新增 31 单测:
- `tests/test_master_input_builder.py`:11
- `tests/test_master_adjudicator_v14.py`:20

全套 1103 → 1134(+31)。本 sprint 顺带 v1.4 schema 迁移修复 2 个 v1.3 legacy 测试(test_master_fallback_on_error / test_master_prompt_contains_v2_fields)。

## 段 2 用户验证脚本

```bash
cd ~/Projects/btc_swing_system

# 1. 端到端 §Z 验证(D2=a 不调真 AI,32 项全跑)
.venv/bin/python scripts/verify_master_thesis_aware.py

# 2.(可选)pytest 本 sprint 31 单测
.venv/bin/python -m pytest tests/test_master_input_builder.py \
    tests/test_master_adjudicator_v14.py -v

# 3. 1.10-A/B/C 端到端验证仍跑(向后兼容)
.venv/bin/python scripts/verify_v14_tables.py            # 1.10-A:14/14
.venv/bin/python scripts/verify_orders_engine.py         # 1.10-B:11/11
.venv/bin/python scripts/verify_thesis_lifecycle.py      # 1.10-C:34/34

# 4. prompt 改动 git diff(577 → 187 行,大幅精简)
git diff 7c933c9 1f0c0e8 -- src/ai/agents/prompts/master_adjudicator.txt | head -50
```

## 段 3 同类风险扫描

**1.10-B/C 风险继承状态**:
- 1.10-B #1 close 流程 ✅(1.10-C 已实施)
- 1.10-B #2 不预 round ✅(本 sprint 0 round)
- 1.10-B #3 单进程假设 ⚠ 仍未解决(留 1.10-J)
- 1.10-B #4 verify thesis_id 命名 ✅(本 sprint prefix `verify_1_10_d_master_*`)
- 1.10-C #1 走势 1/4 简化 ⚠ 留 1.10-D 的 master AI 综合判断 — **本 sprint 已开通 master AI thesis-aware**,但真 AI 调用留 1.10-L
- 1.10-C #2 opened_at_utc 推算 ⚠ 留 1.10-J(theses 加字段)
- 1.10-C #3 D3 closed_at_utc 信任 ⚠ 留 1.10-E Validator 7 校验
- 1.10-C #4 verify 自动 migration 的 schema 改动副作用 ✅(本 sprint verify 同样模式,已知)
- 1.10-C #5 exit_c 全删 14d_fuse audit log ⚠ 留 1.10-H weekly_review 快照保护

**1.10-D 新风险**:
1. **D2 mock 不验证真 prompt 效果**:本 sprint 全程 mock,无法验证 master AI 实际理解新 prompt 的"5 段"结构 / mode 字段 / C 级 ambush_only 约束。**1.10-L 必须真 API 验证**(checklist 见末尾)
2. **prompt 仅含 §3.3.6 静态描述,不含 few-shot 示例**:旧 v1.3 prompt 有 3 个示例(理想开仓 / PROTECTION / 持仓中观察),本 sprint 删干净。新 prompt 是否需要 v1.4 thesis-aware 示例待 1.10-L 实测后判断 — 若发现 master 理解 mode 不准,1.10-L 后回头加 few-shot
3. **validate_mode 仅检查 Validator 6**(active_thesis + new_thesis 冲突)。其他强制条件(C 级必须 ambush_only / break_conditions ≥ 3 / direction 一致)留 1.10-E
4. **fallback 不触发 thesis_aware_fallback**:本 sprint 实施 thesis_aware_fallback 静态方法,但**无调用方**(orchestrator 仍调老 _fallback_output)。1.10-F retry 机制 sprint 应在 BaseAgent.analyze 失败时调 thesis_aware_fallback(需读 has_active_thesis context)
5. **prompt 行数大幅缩减(577 → 187,-67%)**:可能丢失 v1.3 prompt 中重要细节(如 conflict_resolution 字段说明)。已通过 grep 确保 v1.4 §3.3.6 5 段 + I/O schema 全在,但**1.10-L 真 API 验证时若发现 master 输出缺关键字段,可能要加补**

## 段 4 详细报告路径

`docs/cc_reports/sprint_1_10_d.md`(本文件)。

---

# 1.10-L 端到端 checklist(D2=a 补充契约,延后但不忘)

**1.10-L sprint 启动时,真 API 调用必须验证以下 8 项**:

## 必验 8 项(真 master AI 调用)

1. **mode 字段真生成**:真 API 输出 JSON 含 `"mode"` 字段,值在 `{evaluate_existing, new_thesis, silent_cooldown}` 之一。**断言**:从 master output 解析 `result["mode"] in VALID_MODES`,否则 1.10-D 的 prompt §七、输出 schema 段不到位。

2. **mode 与 active_thesis 状态对齐**:
   - 输入 `active_thesis=None + cooldown_state.in_cooldown=False + L3 grade=A` → master 应输 `mode=new_thesis` + `new_thesis.direction` 完整
   - 输入 `active_thesis={...} + L3 grade=B` → master 应输 `mode=evaluate_existing` + `thesis_assessment.still_valid` 完整
   - 输入 `active_thesis=None + cooldown_state.in_cooldown=True` → master 应输 `mode=silent_cooldown` + `silent_reason`
   - **断言**:3 种场景跑真 AI,各看 mode 是否对齐;若 mismatch → 1.10-D 的 prompt §二、必须做的 段不到位

3. **thesis-aware 输入真传到 prompt**:验证 master AI 能在 narrative 中引用 active_thesis 字段(如 "thesis 创建 8 天前" / "持有 long 0.27 BTC")。**断言**:master output 的 narrative 含 `active_thesis.thesis_id` / `current_position.long_btc_amount` / `cooldown_state.in_cooldown` 等真实字段值的引用。

4. **objective_evidence 真填充**:master AI 真按 prompt §四、必须包含的输出元素 段填 objective_evidence(引用真实 input 字段值,如 "DXY 当前 105 < 108")。**断言**:`len(result.get("objective_evidence", [])) >= 1` 且每条含可解析数字 / 字段名。

5. **C 级 ambush_only 约束**:输入 `L3 grade=C` 创建新 thesis 场景,master 输出 `new_thesis.execution_permission == "ambush_only"`。**断言**:这是 v1.4 §3.3.6 §二、必须做的 #3 的硬约束 — 真 API 不遵守 → prompt 加强或 1.10-E Validator 5 拦截。

6. **break_conditions ≥ 3 条客观**:`mode=new_thesis` 时,`new_thesis.break_conditions` 长度 ≥ 3 且每条含数字 / 阈值(防主观)。**断言**:正则匹配 `\d+` 在每条 break_conditions 中(粗略客观性检查)。Validator 8 留 1.10-E 严格化。

7. **counter_arguments + what_would_change_mind 长度**:counter_arguments ≥ 1 / what_would_change_mind ≥ 3,对齐 prompt §四。**断言**:真 API 易遗漏这两个字段,直接 assert 长度。

8. **fallback 真触发(网络失败 / 模型超时)**:模拟 client 异常 → 验证 BaseAgent.analyze 返回 `_fallback_output` (status=degraded) 或调用方触发 `thesis_aware_fallback(has_active_thesis)`。**断言**:fallback 路径 mode=silent_cooldown 或 evaluate_existing(永不 new_thesis,§6.4 真表)。

## 1.10-L 必跑场景(集成测试)

- 场景 A:无 active_thesis + L3 grade=A + 无冷却 → 期望 mode=new_thesis,新 thesis 创建,挂单生成
- 场景 B:有 active_thesis(已开仓 7 天)+ L3 grade=B → 期望 mode=evaluate_existing,still_valid=mostly/fully
- 场景 C:active_thesis + 模拟 break 条件触发(DXY 真破 110)→ 期望 still_valid=invalidated + which_break_triggered 准确填
- 场景 D:无 active_thesis + cooldown_state.in_cooldown=True → 期望 mode=silent_cooldown
- 场景 E:无 active_thesis + L3 grade=C → 期望 mode=new_thesis + execution_permission=ambush_only

## 成本估算

每个真 master AI 调用 ~4000 tokens(input + output)× $0.003-$0.015 / 1k tokens(claude-sonnet-4-5 价位)= 约 ¥0.10-¥0.50/次。8 项 × 5 场景 = 40 次调用 ≈ ¥4-¥20。**1.10-L 实施时预算 ¥30 应对各场景 + 失败重试**。


## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| 14 档枚举 prompt 段(line 116-128 + 5.1+ 迁移规则) | `src/ai/agents/prompts/master_adjudicator.txt` | D3=a + §X:prompt 跟新 mode schema 不能共存,完整重写 |
| 14 档相关 prompt 字段(LONG_OPEN / SHORT_PLANNED / FLIP_WATCH / POST_PROTECTION_REASSESS 等枚举提及) | 同上 | 同上 |

prompt 旧版 git history 永远可恢复(`git show HEAD~N:src/ai/agents/prompts/master_adjudicator.txt`),不留 .v13.bak 副本(违反 §X)。

代码层 14 档枚举(state_machine.py / labels.py / normalize_state.py 等 11 文件)**留 1.10-J**,本 sprint 不动。
