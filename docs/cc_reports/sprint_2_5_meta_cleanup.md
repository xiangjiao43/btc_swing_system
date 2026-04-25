# Sprint 2.5-meta-cleanup — 撤销过时例外条款 + 人读层合规审计

**Date:** 2026-04-25
**Branch:** main
**Type:** docs / audit

---

## 任务 1:撤销过时例外条款

### 修改文件

| 文件 | 操作 | 说明 |
|---|---|---|
| `docs/modeling.md` §2.5 | 删 18 行 + 改 1 行 | 删"6 个组合因子双段(2.5-B 引入)⚠ 例外"行 + 整个"v1.3 待办"段;同位置改写为"6 个组合因子双段 → 规则化模板,❌ 否";末尾加引述 "Sprint 2.5-B 已确定走规则化模板路线,不构成原则例外" |
| `CLAUDE.md` | 删 3 行 | 移除"例外审计:Sprint 2.5-B …"段落 |

### 修改后状态

§2.5 末尾对照表 5 行,全部 ❌ 否(L1-L5 结论 / pillars / composition / 双段 / 综合 narrative)。综合 narrative 那行的"AI 是否参与人读版"列保留 ✅,因为综合裁决环节是原则 #5 明文允许的唯一 AI 出口。

---

## 任务 2:人读层 AI 介入审计

### 已扫描文件

| 路径 | 扫描方式 | 结果 |
|---|---|---|
| `src/composite/_base.py band_position.py crowding.py cycle_position.py event_risk.py macro_headwind.py truth_trend.py` | grep `import anthropic`、`from anthropic`、`from ..ai.`、`messages.create`、`claude`、`gpt`、`openai` | ✅ 0 命中 |
| `src/evidence/_anti_patterns.py _base.py layer1_regime.py layer2_direction.py layer3_opportunity.py layer4_risk.py layer5_macro.py pillars.py plain_reading.py` | 同上 | ✅ 0 命中 |
| `src/strategy/composite_composition.py factor_card_emitter.py observation_classifier.py` | 同上 | ✅ 0 命中 |
| `web/assets/app.js` | grep `ai_response`、`ai_verdict`、`adjudicator.`、`current_analysis`、`strategy_impact` | ⚠ 见下方违规项 |
| `web/index.html` | grep `ai_verdict`、`narrative`、`adjudicator`、`compositeCurrentAnalysis`、`compositeStrategyImpact`、`compositeMissingHint` | ⚠ 见下方违规项 |

### 是否发现 AI 混入

**结论:存在 1 项已知违规(Sprint 2.5-B 残留),其余 0 命中。**

### 违规项详情

| 违规位置 | 违规模式 | 来源 commit |
|---|---|---|
| `web/index.html:453` `x-text="compositeCurrentAnalysis(c.card_id)"` | Region 3 组合因子卡的"📊 当前态势"段渲染 `state.composite_factors[k].current_analysis`,该字段在 backend 由 AI 生成 | d8999c4 (Sprint 2.5-B) |
| `web/index.html:461` `x-text="compositeStrategyImpact(c.card_id)"` | Region 3 组合因子卡的"🎯 对策略影响"段渲染 `state.composite_factors[k].strategy_impact`,同上由 AI 生成 | d8999c4 |
| `web/assets/app.js:430-446` `compositeCurrentAnalysis()` / `compositeStrategyImpact()` / `compositeMissingHint()` | 前端 helper,只是把 AI 字段透传给 `x-text`,本身不调 AI 但消费 AI 字段 | d8999c4 |
| `src/ai/adjudicator.py` `_validate_composite_factors()`(系统 prompt 也含双段 50-70 字要求) | AI 输出 `composite_factors[]`,validator 接收并填进 adjudicator 输出 dict | d8999c4 |
| `src/pipeline/state_builder.py` `_merge_composite_analyses_into_state()` | 把 `adjudicator_result.composite_factors[]` 合并进 `state.composite_factors[k].current_analysis / strategy_impact`,完成 AI → 人读层注入 | d8999c4 |

### 违规模式归类

**模式:AI 综合裁决环节"附带"产出非裁决用文本,污染人读层数据流。**

具体路径:
```
Claude prompt(2.5-B 段落要求双段)
  → AI JSON output: composite_factors:[{key, current_analysis, strategy_impact}]
  → adjudicator.py validator 接收并兜底
  → state_builder.py merge 进 state.composite_factors[k]
  → 前端 helper 直接透传给 Region 3 卡片
  → 用户在"组合因子"区域读到的是 AI 文本,不是规则模板
```

### 合法对照(✅ 合规的 AI 出口)

| 位置 | 字段 | 是否合规 | 说明 |
|---|---|---|---|
| `web/index.html:268` "策略说明" | `state.ai_verdict.narrative` | ✅ 合规 | 在 Region 1 "AI 策略建议"区域,属于原则 #5 明文允许的"综合裁决"出口,且分区命名直接告诉用户这是 AI 文本 |

### 修复建议(本批次不修,只标记)

#### 选项 A:Sprint 2.5-B-rewrite — 规则化模板替换(推荐,与 §2.5 对齐)

1. 在 `src/strategy/composite_composition.py`(或新建 `composite_narrative.py`)为 6 个 composite 各写一个模板函数 `narrative_<key>(c, ctx) -> {current_analysis, strategy_impact}`
   - 输入:已 inject 完 composition / value_interpretation / affects_layer 的 composite dict
   - 逻辑:查阈值表(score → band 文案)+ 引用建模规则编号(L1./L2./...)+ 拼模板
   - 输出:同 schema 的两段中文
2. 在 `state_builder.py` 删除 `_merge_composite_analyses_into_state` 调用,改为新函数 `inject_composite_narrative(state)` 在 `inject_composite_composition` 之后调
3. `src/ai/adjudicator.py`:
   - `_SYSTEM_PROMPT` 删除整段"组合因子双段分析(Sprint 2.5-B)"
   - `_MAX_TOKENS` 2000 → 1000(回退)
   - 删除 `_validate_composite_factors` / `_build_composite_snapshot` / `_COMPOSITE_KEYS` / `_COMPOSITE_FALLBACK_TEXT`
   - `_extract_facts` 删除 `composite_snapshot` / `composite_factors_raw` 字段
   - `_validate_and_enforce_constraints` 删除 `composite_factors` 字段
   - `_build_rule_output` 删除 `composite_factors:[]` 默认值
4. 前端不改:`compositeCurrentAnalysis` / `compositeStrategyImpact` 继续读 `state.composite_factors[k].current_analysis / strategy_impact`,数据来源切换为模板生成
5. 测试:`tests/test_adjudicator.py::TestCompositeFactorsAnalyses` 删除或改为模板测试

#### 选项 B:保留 AI 但收编为"叙事辅助"

- 不推荐,与 §2.5 #3 直接冲突
- 若选 B,需在 §2.5 重新加入"AI 生成的人读版必须满足 X/Y/Z 条审计性约束"的例外条款 — 即恢复本次刚撤销的内容

### 工作量预估(选项 A)

- composite_narrative.py 6 个函数 + 各 1 个模板:~150 行
- state_builder 调整:~10 行
- adjudicator.py 删除:~80 行(净减)
- 测试改造:~50 行
- 合计:1 个 sprint 子任务即可,无后端架构变更

---

## 关键决策点

> 已知违规(Sprint 2.5-B 残留)按用户指令"本批次不修,只标记",未停下问。
> 未发现任何意外的、用户不知情的违规,无需停下决策。

---

## 不修复的明示

本 sprint(2.5-meta-cleanup)只做两件事:
1. 撤销过时例外条款(让文档反映用户最新决策)
2. 审计现有代码并标记违规(供下次 sprint 使用)

**没有修复 d8999c4 引入的 AI → 人读层注入路径。** 该修复留给 Sprint 2.5-B-rewrite。
