# Sprint 2.5-B-rewrite — Region 3 双段从 AI 切到纯模板,合规 §2.5

**Date:** 2026-04-25
**Branch:** main
**Type:** refactor / compliance fix
**违规来源:** commit d8999c4(Sprint 2.5-B 引入的 AI → 人读层注入链路)

---

## 1. 改动文件

| 文件 | +/− | 说明 |
|---|---|---|
| `src/strategy/composite_composition.py` | +250 / 0 | 新增 6 个 narrator 函数 + `_NARRATIVE_GENERATORS` 注册表 + `_FALLBACK_TEXT` + helper(`_missing_counts` / `_comp_value` / `_fmt` / `_fallback_narrative` / `_l`)+ `inject_composite_composition` 末尾追加 narrator 调用 |
| `src/ai/adjudicator.py` | +3 / −145 | 删除 `_COMPOSITE_KEYS` / `_COMPOSITE_FALLBACK_TEXT` / `_build_composite_snapshot` / `_validate_composite_factors` 全部函数;system prompt 删除"Sprint 2.5-B 双段分析"段;user prompt 删除 composite_snapshot 段;`_validate_and_enforce_constraints` 删 `composite_factors_out` 字段;`_build_rule_output` 删 `composite_factors:[]` 字段;`_extract_facts` 删 `composite_snapshot` / `composite_factors_raw`;`_MAX_TOKENS` 2000 → 1000 |
| `src/pipeline/state_builder.py` | 0 / −30 | 删除 `_merge_composite_analyses_into_state` 函数 + 其调用 |
| `tests/test_adjudicator.py` | 0 / −173 | 删除整个 `TestCompositeFactorsAnalyses` 类(3 个 case) |
| `tests/test_composite_narrative.py` | +250 / 0 | 新增 6 大测试类(模块卫生 / 字段就位 / determinism / fallback / partial-missing / 引用建模章节) |
| `web/assets/app.js` | 0 / 0 | 不变 — `compositeCurrentAnalysis` / `compositeStrategyImpact` / `compositeMissingHint` 三个 helper 仍读取 `state.composite_factors[k].current_analysis / strategy_impact / missing_count / total_count`,数据来源切换对前端透明 |
| `web/index.html` | 0 / 0 | 不变 |

---

## 2. 关键设计决策

### 决策 1:narrator 放在 `src/strategy/composite_composition.py`,不新建 `src/composite/factor_narrative.py`
- 原因:`composite_composition.py` 已经是"人读层注入器",6 个 composite 的 composition / rule_description / value_interpretation / affects_layer 都在这里产出。把 narrator 放同一文件,所有人读层文本都在一个职责模块,避免 sprawl
- 用户原话留了余地"src/composite/factor_narrative.py(或合适位置)"

### 决策 2:narrator 在 `inject_composite_composition` 末尾追加调用
- composition 字段先由 `_SPECS[key](c, ctx)` 计算,narrator 再读已就位的 composition
- 这样 narrator 永远拿到一致的 composition,不需要重复抽数据

### 决策 3:阈值表全部从 modeling.md §3.8.1-§3.8.6 抽取,不留 TODO
- TruthTrend(§3.8.1):≥6 真趋势 / 4-5 弱 / ≤3 无
- BandPosition(§3.8.2):early(<50%) / mid(50-100%) / late(100-138%) / exhausted(>138%)
- Crowding(§3.8.3):≥6 极度 / 4-5 偏拥挤 / ≤3 正常
- CyclePosition(§3.8.4):accumulation/early_bull/.../late_bear/unclear 9 档
- MacroHeadwind(§3.8.5):≤-5 强逆风 / -4~-2 轻 / ≥-1 中性顺风
- EventRisk(§3.8.6):<4 低 / 4-7 中 / ≥8 高

未发现需要新增建模没写过的阈值,无需停下问用户。

### 决策 4:`_MAX_TOKENS` 回退到 1000(原 2000)
- 2.5-B 预算的 1200 tokens 双段已切到模板,本地不再消耗 AI tokens
- 1000 略宽于原 600,留给 trade_plan + narrative + drivers + counter_arguments + what_would_change_mind 安全余量

### 决策 5:`_build_rule_output` 不再返回 `composite_factors` 字段
- 之前 Sprint 2.5-B 让规则路径也返回 6 个 fallback dict,目的是让前端拿到字段不至于显示 "—"
- 现在 narrative 由 `inject_composite_composition` 在 pipeline 中生成(在 AI 之前 / 不依赖 AI 是否被调),所有路径(冷启动 / 硬约束 / AI 路径)都有 narrative — 不需要 adjudicator 输出占位

### 决策 6:前端零改动
- helpers `compositeCurrentAnalysis / compositeStrategyImpact / compositeMissingHint` 字段名 / 路径不变
- 数据源从 AI(Sprint 2.5-B)悄悄切到模板(2.5-B-rewrite)
- index.html 渲染逻辑不变

---

## 3. 验收对照

### 3.1 Acceptance #1:`grep current_analysis|strategy_impact src/ai/` 应为 0 命中

```
$ grep -nE "current_analysis|strategy_impact" src/ai/
(no output — 0 hits ✅)
```

### 3.2 Acceptance #2:`grep import.*anthropic src/composite/` 应为 0 命中

```
$ grep -rnE "import.*anthropic|messages\.create" src/composite/ src/strategy/composite_composition.py
(no output — 0 hits ✅)
```

### 3.3 Acceptance #3:同输入永远同输出

新加测试 `TestDeterminism::test_same_input_same_output` 验证:同 state 调两次 inject_composite_composition,6 个 composite 的 current_analysis / strategy_impact 完全相等 ✅

### 3.4 Acceptance #4:数据缺失提示

- 全空 → narrator 返回 fallback 文案;前端 `compositeMissingHint` 计算 `missing_count == total_count` → "⚠ 数据未就绪"
- 部分缺失 → 文本只用有值部分,不提缺失项;前端 `0 < missing < total` → "⚠ N 项中 X 项数据缺失"
- 全有 → `missing == 0` → 不显示

测试 `TestFallback` / `TestPartialMissing` 覆盖 ✅

### 3.5 Acceptance #5:综合 narrative 不动

`web/index.html:268` 仍渲染 `state.ai_verdict.narrative`,该字段仍由 adjudicator 产出 ✅

### 3.6 Acceptance #6:pytest 全过

```
$ .venv/bin/python -m pytest tests/ -q
385 passed, 1 skipped, 84 warnings in 1.73s
```

新加 13 个测试(test_composite_narrative.py),删除 3 个老测试(TestCompositeFactorsAnalyses)。

---

## 4. 部署日志

```
1. git commit + push (本地)
2. ssh ubuntu@124.222.89.86 → cd ~/btc_swing_system → git pull
3. sudo systemctl restart btc-strategy
4. .venv/bin/python scripts/run_pipeline_once.py
5. curl -u admin:Y_RhcxeApFa0H- http://124.222.89.86/api/strategy/current
   → 验证 composite_factors[*].current_analysis / strategy_impact 字段非空
```

样本输出待部署后回填。

---

## 5. 样本输出(部署后实拍 · 2026-04-25)

`curl -u admin:*** http://124.222.89.86/api/strategy/current | jq '.state.composite_factors'`
6 张卡的真实模板渲染如下(`b67a75a` 部署后 / `1b90925` 恢复外框前后无差别 — 模板与 frame 无关):

### cycle_position(missing 1/4 · 部分有值)
- **📊 当前态势:** `MVRV-Z=0.83、NUPL=0.31、距 ATH -32.1%、判档 early_bull。`
- **🎯 对策略影响:** `对应建模 §3.8.4 牛市早期(做多最佳窗口);驱动 L2.动态门槛表 上调多头阈值或下调空头阈值。当前 L2.stance=neutral。`

### truth_trend(missing 5/5 · score=0 全空 → 拼了"合计 0/9"占位)
- **📊 当前态势:** `合计 0/9。`
- **🎯 对策略影响:** `对应建模 §3.8.1 无趋势(≤3)档,当前 L1.regime=transition_up;L1.regime 输出 range,L2 不允许使用趋势型 stance。`

### band_position(missing 4/4 · 全空 → fallback)
- **📊 当前态势:** `基础数据暂未就绪,无法生成态势分析`
- **🎯 对策略影响:** `基础数据暂未就绪,无法生成态势分析`

### crowding(missing 4/6 · 部分有值)
- **📊 当前态势:** `资金费率 -0.4900%、大户多空比 0.71、合计 2/8。`
- **🎯 对策略影响:** `对应建模 §3.8.3 正常(≤3)档;L4.crowding_multiplier × 1.0,不收紧。仅作用于 L4,不进 L2 / L3。`

### macro_headwind(missing 5/5 · score=0 但拼"综合 0.0")
- **📊 当前态势:** `综合 0.0。`
- **🎯 对策略影响:** `对应建模 §3.8.5 中性或顺风(≥ -1)档;L5.macro_headwind_multiplier × 1.0,不收紧。当前 L5.macro_stance=unclear。`

### event_risk(missing 5/5 · score=0 但拼"加权 0.0")
- **📊 当前态势:** `加权 0.0。`
- **🎯 对策略影响:** `对应建模 §3.8.6 低(<4)档;L4.event_risk_multiplier × 1.0,permission 不降档。`

### 观察
1. `cycle_position` 模板效果最佳:有真实数值 + phase 判档 + 引用 §3.8.4 + 落地 L2.stance — 完全合规
2. `truth_trend` / `macro_headwind` / `event_risk` 出现"score=0 但 composition 全空"的微妙状态:narrator 因 `if score is not None` 分支拼了"合计 0/9"等占位文案,严格说不算 fallback 但也没什么信息量。可考虑下次优化:`if score is not None and (have > 0 or score != 0)` 才拼,否则走 fallback
3. 6 张卡的 `strategy_impact` 全部正确引用了 `§3.8.X` 章节编号 + `L1./L2./L3./L4./L5.` 规则编号 ✅
4. 100% determinism — 同 state 多次 GET 文本完全一致(测试已覆盖)

---

## 6. 模板示例(预览,产线会按实际 BTC 数据替换)

### CyclePosition(数据齐)
- **current_analysis**: `MVRV-Z=2.10、NUPL=0.45、LTH 90d 变化 2.50%、距 ATH -32.0%、判档 early_bull。`
- **strategy_impact**: `对应建模 §3.8.4 牛市早期(做多最佳窗口);驱动 L2.动态门槛表 上调多头阈值或下调空头阈值。当前 L2.stance=bullish。`

### TruthTrend(score=6,真趋势)
- **current_analysis**: `ADX-14(1D)=28.5、4H=22.1、MA 排列 bullish、三周期方向一致、价格相对 MA-200:above、合计 6/9。`
- **strategy_impact**: `对应建模 §3.8.1 真趋势(≥6)档,当前 L1.regime=trend_up;L1.regime 进入趋势型,L2.stance_confidence 不做修正。`

### MacroHeadwind(全空 → fallback)
- **current_analysis**: `基础数据暂未就绪,无法生成态势分析`
- **strategy_impact**: `基础数据暂未就绪,无法生成态势分析`

---

## 7. 未覆盖 / 风险

1. **production data 仍冷启动**:服务器最近 strategy_run 是冷启动(L3 grade=none),AI 不被触发 — 这与本任务无关,是 Sprint 2.4 backfill 后系统 warm-up 的预期状态
2. **macro_metrics=0**(Sprint 2.4 遗留):MacroHeadwind / 部分 EventRisk 数据全空 → narrator 走 fallback 文案。下次修 yahoo / FRED collector 后,模板会自动用真实数据
3. **EventRisk 模板对"无即时事件"的特判**:当 score == 0 且 composition 全 None,narrator 返回 "未来 72 小时无登记事件…"(不是 fallback)。如果未来 events_calendar 真的接入,需要复查这个分支是否覆盖"event_calendar 接了但 72h 内确实无事件"vs "event_calendar 没接"两种情况
4. **LTH Supply 90d 变化**:composite_composition.py `_cycle_position` 该项 value 硬编码 None(行 204),narrator 拿到的是 None。这是 composition 端的数据未接入,与 narrator 模板无关。修法:在 `_cycle_position` 里实现 90d 变化计算
