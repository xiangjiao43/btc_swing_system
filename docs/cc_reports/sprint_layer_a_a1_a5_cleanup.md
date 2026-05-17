# Sprint Layer A A1-A5 死代码清理

## Triggers

- 用户三轮调查后确认:Layer A 每日 10:00 实际运行路径是 `layer_a_spot_runner.py → run_layer_a_spot_only → LayerACycleAdjudicator`(单一裁决),旧 A1-A5 五层 agent 类一次也不会被调到。
- 任务范围:7 项删除 + 1 项 scheduler 描述更新。CC 按要求只执行"已确认无人调用的死代码"清理。
- **重要偏离**:任务列表中的第 3 项(删除 `normalize_a1..a5`)与第 4 项(删除 `build_a1_cycle_stage_context`)经核查发现两者均为**活跃代码**,不是死代码。CC 在不修改任何被显式标注"不要动"的代码(承袭逻辑)的前提下,无法安全删除它们 —— 因此 SKIP 这两项,在下方"未覆盖项"段详细说明,等待用户决策是否进入下一阶段重构。

## 实际改动文件列表

| 文件 | 改动 |
|---|---|
| [src/ai/agents/spot_cycle_agents.py](../../src/ai/agents/spot_cycle_agents.py) | 删除 A1-A5 五个类(原 36-137 行)、删除 `_prompt_payload` 辅助函数(已无引用)、删除对 `build_a1_cycle_stage_context` 与 `normalize_a1..a5` 的 import;保留 `LayerACycleAdjudicator` 及其依赖的 `_compact_prompt_payload` |
| [src/ai/agents/prompts/a1_spot_cycle.txt](../../src/ai/agents/prompts/) | 删除文件 |
| [src/ai/agents/prompts/a2_onchain_macro.txt](../../src/ai/agents/prompts/) | 删除文件 |
| [src/ai/agents/prompts/a3_spot_opportunity.txt](../../src/ai/agents/prompts/) | 删除文件 |
| [src/ai/agents/prompts/a4_spot_risk.txt](../../src/ai/agents/prompts/) | 删除文件 |
| [src/ai/agents/prompts/a5_spot_adjudicator.txt](../../src/ai/agents/prompts/) | 删除文件 |
| [src/ai/agents/__init__.py](../../src/ai/agents/__init__.py) | 从 import 与 `__all__` 中移除 5 个旧类名;保留 `LayerACycleAdjudicator` |
| [src/ai/orchestrator.py](../../src/ai/orchestrator.py) | 从 `from .agents import (...)` 移除 A1-A5 五个类;从 `self._agents` dict 移除 `"a1"..."a5"` 五行注册 |
| [config/scheduler.yaml](../../config/scheduler.yaml) | 第 126 行 description 由 `"只跑 A1-A5 + Spot Validator..."` 改为 `"Layer A 单一大周期裁决:四个数据包 + 一次 AI 调用 + Spot Validator + latest Layer A 持久化"` |

测试文件**未做任何改动**。理由:`grep -lE "from.*import.*A[1-5]SpotCycle…|normalize_a[1-5]"` 在整个 `tests/` 下命中 0 处。原报告里列出的 7 个测试文件之所以出现 `a1_cycle_stage` / `a5_spot_adjudicator` 等字串,是因为它们断言**输出 dict 的 key**,而不是 import 被删除的符号。这些 key 由 `normalize_layer_a_output` 通过仍保留的 `normalize_a1..a5` 函数合成,所以测试不受影响。

## 关键 diff 摘要

### src/ai/agents/spot_cycle_agents.py(由 186 行 → 69 行)

完全重写。新文件只保留 `LayerACycleAdjudicator` 类及其唯一依赖的辅助函数 `_compact_prompt_payload`。`_prompt_payload` 因仅被 A2/A3/A4/A5 使用,随同类一并删除。

### src/ai/agents/__init__.py(48 行 → 36 行)

```diff
-from .spot_cycle_agents import (
-    A1SpotCycleAnalyst,
-    A2OnchainMacroAnalyst,
-    A3SpotOpportunityAnalyst,
-    A4SpotRiskAnalyst,
-    A5SpotAdjudicator,
-    LayerACycleAdjudicator,
-)
+from .spot_cycle_agents import LayerACycleAdjudicator

 __all__ = [
     ...
-    "A1SpotCycleAnalyst",
-    "A2OnchainMacroAnalyst",
-    "A3SpotOpportunityAnalyst",
-    "A4SpotRiskAnalyst",
-    "A5SpotAdjudicator",
     "LayerACycleAdjudicator",
 ]
```

### src/ai/orchestrator.py

```diff
 from .agents import (
-    A1SpotCycleAnalyst,
-    A2OnchainMacroAnalyst,
-    A3SpotOpportunityAnalyst,
-    A4SpotRiskAnalyst,
-    A5SpotAdjudicator,
     LayerACycleAdjudicator,
     ...
 )
 ...
                 "master": MasterAdjudicator(client=anthropic_client),
-                "a1": A1SpotCycleAnalyst(client=anthropic_client),
-                "a2": A2OnchainMacroAnalyst(client=anthropic_client),
-                "a3": A3SpotOpportunityAnalyst(client=anthropic_client),
-                "a4": A4SpotRiskAnalyst(client=anthropic_client),
-                "a5": A5SpotAdjudicator(client=anthropic_client),
                 "layer_a_cycle": LayerACycleAdjudicator(client=anthropic_client),
```

### config/scheduler.yaml

```diff
-    description: 'Layer A 大周期现货策略(10:00 BJT 每日 1 档;只跑 A1-A5 + Spot Validator + latest Layer A 持久化)'
+    description: 'Layer A 大周期现货策略(10:00 BJT 每日 1 档;Layer A 单一大周期裁决:四个数据包 + 一次 AI 调用 + Spot Validator + latest Layer A 持久化)'
```

## 设计决策 / 偏离记录

### 偏离 #1:SKIP 删除 `normalize_a1..a5` 函数

**指令**:第 3 项要求删除 `src/ai/spot_strategy_normalizer.py` 中的 `normalize_a1..a5` 函数定义及其"文件内对它们的调用",并保留 `normalize_layer_a_output` 不动。

**事实**:`normalize_layer_a_output` 在 [519-525 行](../../src/ai/spot_strategy_normalizer.py#L519-L525) 直接调用这 5 个函数,把 `cycle_adjudicator` 输出"反向合成"成 `a1_cycle_stage`、`a2_onchain_macro`、`a3_spot_opportunity`、`a4_spot_risk`、`a5_spot_adjudicator` 五个段。这五个段最终落到 DB 的 `latest_layer_a_spot_strategy.layer_a` JSON 里。

**冲突**:
- 删 `normalize_a1..a5` → 必须同步删除/重构 `normalize_layer_a_output` 的合成逻辑 → 违反"保留 normalize_layer_a_output, 不要动"
- 不删调用 → 函数仍是活的,无法删除函数本身
- 而且 `normalize_layer_a_output` 后续 [539-599 行](../../src/ai/spot_strategy_normalizer.py#L539-L599) 的状态机/保守动作逻辑也读写 `out["a1_cycle_stage"]` / `out["a4_spot_risk"]` / `out["a5_spot_adjudicator"]` —— 这部分如果一并删,需要把所有逻辑改读 `cycle_adjudicator` 子段,工作量是 50+ 行的结构性重构,**不是删除**

**用户已明确"不要动"的承袭逻辑**(`spot_cycle_stage_state.py:122-131`、`spot_cycle_context_builder.py:364-373`、`layer_a_spot_runner.py:98-110`)也读 `previous["a1_cycle_stage"]` 与 `previous["a5_spot_adjudicator"]`,这些段一旦从 normalize 输出移除,新写入的 DB 行就不再有这些 key,承袭读取会全部返回空 dict —— 即使读路径代码本身没动,功能也会软性退化。

**CC 决策**:本次纯删除任务不动 `normalize_a1..a5` 与 `normalize_layer_a_output`。等用户决策下一步:
- (A) 接受现状:`normalize_a1..a5` 作为 `normalize_layer_a_output` 的内部 compat 合成器保留,不算死代码
- (B) 进入结构性重构:重写 `normalize_layer_a_output`,只产 `cycle_adjudicator` 段,删除 a1/a2/a3/a4/a5 合成 + 状态机后处理改读 `cycle_adjudicator`,**并同时拆除承袭读路径**(因为没数据可读了)+ 调整 7 个测试文件中 ~100 行涉及 `out["aN_xxx"]["..."]` 的断言

### 偏离 #2:SKIP 删除 `build_a1_cycle_stage_context`

**指令**:第 4 项要求删除 `src/ai/spot_cycle_context_builder.py` 中的 `build_a1_cycle_stage_context` 函数。

**事实**:`build_layer_a_cycle_adjudicator_context`(新单裁决器的 context 入口,**当前线上活跃**)在 [613 行](../../src/ai/spot_cycle_context_builder.py#L613) 调用 `build_a1_cycle_stage_context({"spot_cycle_context": spot_ctx})`,然后从其返回的 `cycle_evidence_summary` 提取各 packet 的指标。换言之,新单裁决器复用了旧 A1 的 evidence 组装函数。

**冲突**:删 `build_a1_cycle_stage_context` 会直接打断每日 10:00 的 Layer A 运行。

**CC 决策**:不删。如果用户希望去掉这个名字(它确实带有 "A1" 字样,语义已不匹配),建议的下一步是**重命名 + 内联**:把 `build_a1_cycle_stage_context` 重命名为 `_build_cycle_evidence_summary`(或类似中性名),让 `build_layer_a_cycle_adjudicator_context` 继续调用。这是重构,不是删除。

### 决策 #3:`_prompt_payload` 辅助函数随类一并删

`_prompt_payload` 原本只被 A2/A3/A4/A5 使用(A1 与 LayerACycleAdjudicator 都用 `_compact_prompt_payload`)。A2-A5 类删除后,`_prompt_payload` 没有调用者,符合 CLAUDE.md §X.6 "Helper / 内部函数级别也要删"。已删除。

## 验收记录

### 1. import smoke test

```
python -c "import src.ai.orchestrator; import src.ai.agents; \
  import src.pipeline.layer_a_spot_runner; \
  import src.ai.spot_cycle_context_builder; \
  import src.ai.spot_strategy_normalizer; print('imports OK')"
→ imports OK
```

### 2. Layer A 专项测试(7 个文件)

```
pytest tests/test_layer_a_spot_normalize.py \
       tests/test_layer_a_spot_validator.py \
       tests/test_layer_a_standalone_schedule.py \
       tests/test_layer_a_spot_context_builder.py \
       tests/test_layer_a_orchestrator_integration.py \
       tests/pipeline/test_orchestrator_mapper.py \
       tests/web_helpers/test_normalize_state.py
→ 132 passed, 12 warnings
```

### 3. 全量 pytest

```
1875 passed, 1 failed, 1 skipped, 672 warnings in 46.94s
```

**唯一失败用例**:`tests/test_jobs_fetch_attempts_integration.py::test_collect_klines_1h_kline_succeeds_derivatives_fail`

- 失败断言:`rows_dv[0]["failure_reason"] == "api_error"`,实际值 `'provider_error'`
- 根因:commit `16cad4f`("Audit Glassnode quota failure root cause", 2026-05-15)将 `src/data/collectors/_classify_failure.py` 的失败分类由 `api_error` 改为 `provider_error`,但**未同步更新本测试**
- 与本次 Layer A 清理**完全无关** —— 涉及衍生品采集错误归类,不动任何 Layer A 代码也会失败
- 不在本 sprint 修复范围

### 4. 自检 git grep

```
git grep "A1SpotCycleAnalyst|A2OnchainMacroAnalyst|...|A5SpotAdjudicator" 
  -- src/ tests/ config/  →  0 hits
git grep "a1_spot_cycle.txt|...|a5_spot_adjudicator.txt"
  -- src/ tests/ config/  →  0 hits
```

被删类与被删 prompt 文件名在仓库工作树(src/tests/config 范围内)0 残留。
注:`docs/` 与 `_review_bundle*/` 历史报告中仍有这些字符串,属于工件归档,按 CLAUDE.md §X.7 自检清单仅排除注释/sprint 报告,不计入残留。

## 未覆盖项 / 风险提示

1. **`normalize_a1..a5` + `build_a1_cycle_stage_context` 未删** —— 上面"偏离 #1/#2"已说明。需要用户决策是否进入结构性重构 sprint。
2. **承袭逻辑未动** —— 按用户指令保留。一旦未来接受偏离 #1 的 (B) 方案,承袭逻辑要一起拆除。
3. **`observation_category`、`run_full_a`、`config/state_machine.yaml`** —— 按指令本 sprint 不处理。
4. **`emergency_simplified_a.txt`** —— 按指令本 sprint 不处理。`EmergencySimplifiedA` 类与其 prompt 仍存在,`orchestrator.py` 中 `_agents["emergency_simplified_a"]` 注册保留。

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 类 `A1SpotCycleAnalyst` | `src/ai/agents/spot_cycle_agents.py` | v1.4 重构后由 `LayerACycleAdjudicator` 替代,运行时 0 调用 |
| 类 `A2OnchainMacroAnalyst` | `src/ai/agents/spot_cycle_agents.py` | 同上 |
| 类 `A3SpotOpportunityAnalyst` | `src/ai/agents/spot_cycle_agents.py` | 同上 |
| 类 `A4SpotRiskAnalyst` | `src/ai/agents/spot_cycle_agents.py` | 同上 |
| 类 `A5SpotAdjudicator` | `src/ai/agents/spot_cycle_agents.py` | 同上 |
| 函数 `_prompt_payload` | `src/ai/agents/spot_cycle_agents.py` | 仅被 A2/A3/A4/A5 使用,5 个类删除后无调用者 |
| 文件 `a1_spot_cycle.txt` | `src/ai/agents/prompts/` | 对应已删 A1 类的 prompt 文件 |
| 文件 `a2_onchain_macro.txt` | `src/ai/agents/prompts/` | 对应已删 A2 类的 prompt 文件 |
| 文件 `a3_spot_opportunity.txt` | `src/ai/agents/prompts/` | 对应已删 A3 类的 prompt 文件 |
| 文件 `a4_spot_risk.txt` | `src/ai/agents/prompts/` | 对应已删 A4 类的 prompt 文件 |
| 文件 `a5_spot_adjudicator.txt` | `src/ai/agents/prompts/` | 对应已删 A5 类的 prompt 文件 |
| `__all__` / import 条目 ×5 | `src/ai/agents/__init__.py` | 5 个类已删 |
| `from .agents import (A1..A5)` | `src/ai/orchestrator.py` | 5 个类已删 |
| `self._agents["a1".."a5"]` 5 行注册 | `src/ai/orchestrator.py` | 5 个类已删 |

自检:
- [x] `git grep "A[1-5]SpotCycleAnalyst|A[1-5]OnchainMacroAnalyst|...|A5SpotAdjudicator"` 在 `src/ tests/ config/` 0 行
- [x] `tests/` 无 import 残留(已 grep,0 命中)
- [x] config 中无引用 5 个旧 prompt 文件名(0 命中)
- [x] `git grep "a[1-5]_(spot_cycle|onchain_macro|spot_opportunity|spot_risk|spot_adjudicator)\.txt"` 在 `src/ tests/ config/` 0 行

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(1875 通过 / 1 失败<sup>*</sup> / 1 skipped) |
| GitHub push(commit hash:_pending_) | ❌ 待用户授权 |
| 服务器 git pull | ❌ 待用户授权 |
| 服务器 systemctl restart | ❌ 待用户授权 |
| 生产 DB 迁移 / 清污 | N/A(本次无 schema 变更) |

<sup>*</sup>唯一失败用例是上游 commit `16cad4f` 遗留的不一致(`api_error` → `provider_error`),与本 sprint 无关。
