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

### Commit 1:报告骨架 + 现状调研(本 commit)
- hash: 待 push 后填
- `docs/cc_reports/sprint_1_10_d.md`(本文件)

### Commit 2-5:待执行

---

## 部署四件事 / 测试记录(commit-by-commit 实时填)

待 commit 5 完成填。

## 本 sprint 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| 14 档枚举 prompt 段(line 116-128 + 5.1+ 迁移规则) | `src/ai/agents/prompts/master_adjudicator.txt` | D3=a + §X:prompt 跟新 mode schema 不能共存,完整重写 |
| 14 档相关 prompt 字段(LONG_OPEN / SHORT_PLANNED / FLIP_WATCH / POST_PROTECTION_REASSESS 等枚举提及) | 同上 | 同上 |

prompt 旧版 git history 永远可恢复(`git show HEAD~N:src/ai/agents/prompts/master_adjudicator.txt`),不留 .v13.bak 副本(违反 §X)。

代码层 14 档枚举(state_machine.py / labels.py / normalize_state.py 等 11 文件)**留 1.10-J**,本 sprint 不动。
