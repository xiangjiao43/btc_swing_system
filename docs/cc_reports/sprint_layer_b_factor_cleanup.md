# Sprint Layer B 因子重构 — 删除 6 个大周期 / 噪音因子(全链路清理)

**日期**:2026-05-19
**目的**:Layer A 独立子系统上线后,Layer B 回归纯波段策略。删除已被 Layer A 覆盖
或对波段判断无贡献的因子,避免 Layer B 与 Layer A 双轨判断大周期。
**前置审计**:[sprint_layer_b_factor_reaudit.md](sprint_layer_b_factor_reaudit.md)

## 1. 删除清单(最终)

| 因子 | 原 Layer B 位置 | Layer A 是否仍用 | 网页卡片去留 |
|---|---|---|---|
| `rule_cycle_position`(9 档) | L2 long_cycle_context | 否(Layer A 用 6 阶段) | 删(emitter composite spec 整删) |
| `lth_supply_90d_pct_change` | L2 computed_indicators | **是**(onchain_packet) | **留**(linked_layer 改为 Layer A) |
| `sth_supply_90d_pct_change` | L2 computed_indicators | **是**(onchain_packet) | **留**(无独立 emitter card;raw `onchain_sth_supply` 卡保留) |
| `lth_realized_price` | L2 computed_indicators | **是**(onchain_packet) | **留**(_emit_onchain_reference 函数级注释) |
| `lth_supply_30d_pct_change` | L4 computed_indicators | 否(Layer A 用 90d) | 无 emitter card(本来就没有) |
| `global_m2_yoy_pct` | L5 computed_macro_indicators | 否(Layer A 不读 yoy) | 无 emitter card(无运行时源) |

## 2. 保留清单(关键)

| 因子 | 保留理由 |
|---|---|
| `sth_realized_price` | L2 波段背景(155 天滑窗 ≈ 短中线持有者成本) |
| `exchange_net_flow_30d_sum` | 30 天资金流,L2 stance 流动性维度 + L4 风险维度 |
| `funding_rate_*` 系列 | L2/L4 衍生品情绪核心 |
| `ema_*` / `swing_*` / `adx_*` / `atr_*` | L1/L2/L4 波段技术因子地基 |
| `dxy / vix / nasdaq / us10y / etf_flow / btc_dominance / events / extreme_event` | L5 必留 macro 因子 |
| 共 ★ 必留 37 个因子 + ◯ 倾向保留 6 个 | 详见 [sprint_layer_b_factor_reaudit.md](sprint_layer_b_factor_reaudit.md) |

## 3. 4 个 commit 概览

| Step | Commit | 改动文件 | diff 行 | 内容概要 |
|---|---|---|---:|---|
| Step 1 | [`77ba672`](../../commit/77ba672) | 5 | +52 / -96 | 5 个 prompt 重写(L1/L2/L3/L4/L5)+ 顺手清理 |
| Step 2 | [`fd011c6`](../../commit/fd011c6) | 24 | +89 / -621 | 代码层(context_builder + anti_pattern + 删 cycle_position.py + state_machine + 测试) |
| Step 3 | [`6297862`](../../commit/6297862) | 2 | +31 / -40 | 网页层(factor_card_emitter 删 cycle_position composite 卡 + linked_layer 标签) |
| Step 4 | (本 commit) | ~7-8 | ~+150 / -250 | §X carryover 清理(pillars/L3 prompt/config schemas + thresholds + data_catalog)+ modeling.md 3 处同步 + 本报告 |

## 4. §X 完整删除清单

### 4.1 代码 / 函数

| 对象 | 路径 | 删除原因 | git grep 证据(真实代码) |
|---|---|---|---|
| `CyclePositionFactor` 类 + `compute()` 方法 | `src/composite/cycle_position.py`(整删 423 行) | 9 档大周期判断,Layer A 6 阶段替代 | 残留只在 state_builder.py stub(允许) + 注释 |
| `is_against_long_cycle(l2_output)` 函数 | `src/ai/anti_pattern_signals.py` | 反模式 5 类 → 4 类,大周期一致性检查归 Layer A | 0(只剩 docstring 解释) |
| `_l2_downstream_hint(l2, cp)` 重写为不带 `cp` 参数 | `src/evidence/pillars.py` | 9 档 thresholds dict 删除 | 0 |
| `_pillars_l2` 中支柱三 long_cycle_context 整段 | `src/evidence/pillars.py:186-220` | L2 不再判大周期 → 支柱 3 改 2 | 0 |
| `compute_anti_pattern_signals` 返回 5 keys → 4 keys | `src/ai/anti_pattern_signals.py` | 同上 | 0 |

### 4.2 字段 / 数据结构

| 对象 | 路径 | 删除原因 |
|---|---|---|
| `rule_cycle_position` 注入 | `src/ai/context_builder.py:l2_ctx`(已删除字段 + 整段计算逻辑) | Layer A 6 阶段替代 |
| `lth_supply_90d_pct_change` 注入 | `src/ai/context_builder.py:computed_indicators` | Layer B 不消费(Layer A 同名字段独立计算) |
| `sth_supply_90d_pct_change` 注入 | 同上 | 同上 |
| `lth_realized_price` 注入(alias) | `src/ai/context_builder.py:computed_indicators` | 同上 |
| `lth_supply_30d_pct_change` 注入 | `src/ai/context_builder.py:computed_indicators` | L4 prompt 已删引用 |
| `long_cycle_context` L2 输出字段 | L2 prompt 输出 schema | Layer B 不再做大周期 |
| `_fw_cycle_mult` 实例字段 | `src/strategy/state_machine.py:193` | FLIP_WATCH 统一 base 时长 |
| `composite_factors.cycle_position` 读取 | `src/strategy/state_machine.py:983` | 同上 |
| `cycle_position` 在 state_machine fields dict | `src/strategy/state_machine.py:1033-1034` | 0 consumer |
| `rule_cycle_position` 写入 context_summary | `src/pipeline/_orchestrator_mapper.py:343` | Layer B 不再产 cycle 字段 |
| `rule_cycle_position` snapshot 注入 | `src/ai/agents/l2_direction_analyst.py:51` | L2 prompt 不再消费 |
| `rule_cycle_position` UI 显示 | `src/web_helpers/normalize_state.py:_l1_supporting_data` | L1 不显示长周期定位 |
| `long_cycle_context` UI 显示 | `src/web_helpers/normalize_state.py:_l2_supporting_data` | L2 不再输出 |
| `is_against_long_cycle` 标签 | `src/web_helpers/labels.py:183` | 反模式 4 类 |

### 4.3 因子卡片 / Web

| 对象 | 路径 | 删除原因 |
|---|---|---|
| `cycle_position` composite card spec | `src/strategy/factor_card_emitter.py:_composite_specs`(整条删除,6 → 5) | 9 档不再产生 |
| `cycle_position` category 映射 | `src/strategy/factor_card_emitter.py:_composite_category` | 同上 |
| `cycle_position` 在 `_composite_direction` 9 档 if-branch | `src/strategy/factor_card_emitter.py` | 同上 |
| `cycle_position` 在 `_composite_plain_reading` 9 档 labels block | `src/strategy/factor_card_emitter.py` | 同上 |
| aSOPR 卡 strategy_impact 中 "cycle_position" 提及 | `src/strategy/factor_card_emitter.py:1852` | 占位过期 |

### 4.4 Prompt

| 对象 | 路径 | 删除原因 |
|---|---|---|
| L2 §4 long_cycle_context 整段 + JSON schema 字段 | `src/ai/agents/prompts/l2_direction.txt` | L2 不再输出 |
| L2 stance 定义里"LTH 累积/派发"句 | 同上 | stance 改基于价格行为 + 衍生品 + 30d 流 |
| L2 输入 4 个 LTH/STH 字段 + rule_cycle_position | 同上 | 因子删除 |
| L2 Few-shot 两个示例改写 | 同上 | 用新 stance 定义 |
| L4 input lth_supply_30d_pct_change + Few-shot | `src/ai/agents/prompts/l4_risk.txt` | 因子删除 |
| L5 global_m2_yoy_pct input + Few-shot + completeness penalty | `src/ai/agents/prompts/l5_macro.txt` | 因子删除 |
| L5 §15 stale discipline "SP500" → "NASDAQ" | 同上 | 顺手清理(SP500 早已退役) |
| L3 input 描述 `long_cycle_context` 两行 | `src/ai/agents/prompts/l3_opportunity.txt:37,236` | L2 不再输出 |
| L3 §6 反模式 5 类 → 4 类 + against_long_cycle 删除 | 同上 | 反模式重编号 |
| L1 §九 重复编号 → §十三 | `src/ai/agents/prompts/l1_regime.txt` | 顺手清理 |
| L3 旧版本注释(Sprint 1.9-A.1) | `src/ai/agents/prompts/l3_opportunity.txt` | 顺手清理 |
| `weekly_review_analyst.txt:190` "5 类反模式" → "4 类" | | 同步 |
| `weekly_review_analyst.py:317` "5 类反模式" → "4 类" | | 同步 |
| `weekly_review_input_builder.py:535` "5 类反模式" → "4 类" | | 同步 |

### 4.5 配置(yaml)

| 对象 | 路径 | 删除原因 |
|---|---|---|
| `cycle_position_multipliers:` 块 | `config/state_machine.yaml:36` | FLIP_WATCH 用 base 时长 |
| `cycle_position_decision:` 整段(86 行,bands + voting + halving) | `config/thresholds.yaml:514+` | 0 consumer(原始 consumer composite/cycle_position.py 已删) |
| `dynamic_direction_thresholds:` 9 档块 | `config/thresholds.yaml:84-93` | L2 用统一 0.65/0.70 门槛 |
| `cycle_position_switch_delay_days: 7` | `config/thresholds.yaml:101` | 0 consumer |
| `cycle_position: [...]` 在 short_grade_rules 2 处 | `config/thresholds.yaml:143,153` | 9 档值已退役 |
| `long_cycle_context:` schema | `config/schemas.yaml:627-630` | L2 不再输出此字段 |
| `cycle_position_output:` schema 整段(25 行) | `config/schemas.yaml:892-916` | 0 consumer |
| `cycle_position:` enum(9 档) | `config/schemas.yaml:125-127` | 替代 enum 在 spot_cycle_stage_state.py(Layer A 6 阶段) |
| `serves: [..., cycle_position]` 3 处 | `config/data_catalog.yaml:257,266,275` | 已无 cycle_position derived factor |
| `- name: cycle_position` derived metric 整段(13 行) | `config/data_catalog.yaml:928-940` | 同上 |

### 4.6 测试

| 对象 | 路径 | 删除原因 |
|---|---|---|
| `test_against_long_cycle_*`(5 个测试函数 + import) | `tests/ai/test_anti_pattern_signals.py` | 函数已删 |
| `test_compute_anti_pattern_signals_returns_5_keys` → `_returns_4_keys` | 同上 | 4 类反模式 |
| `lth_supply_90d_pct_change / sth_supply_90d / lth_realized_price_current` 断言 | `tests/ai/test_context_builder_integration.py:203-204,206` | Layer B ctx 不再注入 |
| L2 ctx keys 集合移除 `rule_cycle_position` | 同上 | 字段已删 |
| `assert "rule_cycle_position" in prompt` → `not in` | `tests/ai/test_step4_field_alignment.py:64` | 删除验证 |
| 4 类 anti_pattern_signals fixture | 同上 | 同步 |
| `l2: {rule_cycle_position: ...}` fixture 清除 | `tests/ai/test_orchestrator.py:102` / `tests/pipeline/test_orchestrator_mapper.py:94` / `tests/pipeline/test_state_builder_orchestrator_branch.py:153,192` | 同步 |
| `assert "rule_cycle_position" in cs` → `not in cs` | `tests/pipeline/test_orchestrator_mapper.py:305` | 删除验证 |
| `cycle_position` 参数 + `composite_factors.cycle_position` 注入 | `tests/test_state_machine.py:46,80-83` | state_machine 不读 cycle_position |
| `long_cycle_context` fixture L2 | `tests/web_helpers/test_normalize_state.py:53` | L2 不再输出 |
| 4 类 anti_pattern_signals fixture | 同上:100 | 同步 |
| `long_cycle_context` fixture L2 | `tests/test_human_readable_style.py:83` | 同步 |
| `test_composite_cards_all_six` → `_all_five` + 6 → 5 composite 断言 | `tests/test_factor_card_emitter.py:44,87` | 5 个 composite |

## 5. 行为变化(用户应知)

### 5.1 FLIP_WATCH 冷却时长不再因大周期调整

**之前**:状态机从 `composite_factors.cycle_position` 读 9 档判断,做乘数调整:
- `late_bull / distribution / late_bear / accumulation` × 0.7(缩短)
- `mid_bull / mid_bear` × 1.3(拉长)
- 其他 × 1.0(base)

**现在**:FLIP_WATCH 冷却时长**统一为 base 时长 18-96h**(由反手通道档位决定),
不再因大周期阶段调整。详见 [docs/modeling.md §4.3.6](../modeling.md#436-flip_watch-冷却时长2026-05-19-更新)。

### 5.2 L3 反模式从 5 类降为 4 类

删除 `is_against_long_cycle`(stance vs cycle_position 反向)反模式。Layer B 反模式现在只关注:
1. `is_extending_late_phase` — L2 phase ∈ {late, exhausted}
2. `is_chasing_breakout_no_pullback` — 价格突破阻力后无回踩
3. `is_failing_at_resistance` — 价格在阻力反复测试失败
4. `is_after_extreme_event_no_reset` — 极端事件后未充分整理

L3 prompt §六硬约束 H4(反模式触发 → grade 降级)逻辑不变,只是触发面收窄一类。

### 5.3 L2 stance 定义重写

**之前**(摘要):
> bullish — K 线 HH+HL + 4h/1d 一致 + **LTH 累积**
> bearish — K 线 LH+LL + 4h/1d 一致 + **LTH 派发**

**现在**:
> bullish — K 线 HH+HL + 4h/1d 一致 + 衍生品健康(funding 不极端)+ 30d 链上净流出
>          + 可参考价格与 sth_realized_price 相对位置作为波段背景
> bearish — 镜像 bullish

stance_confidence_tier 计算从 4 维改 4 维,其中"长周期支持"换成"30 天链上资金流方向一致"。

### 5.4 L2 三支柱 → 二支柱

`evidence/pillars.py:_pillars_l2` 输出从 3 个支柱(结构序列 + 相对位置 + 长周期背景)
变为 2 个支柱(结构序列 + 相对位置)。`_l2_downstream_hint` 函数签名从 `(l2, cp)` 改为 `(l2)`,
用统一门槛(做多 0.65 / 做空 0.70)替代 9 档动态 thresholds dict。

### 5.5 网页 composite tier 卡片数 6 → 5

Factor card emitter 不再产 `composite_cycle_position` 卡。网页 composite tier
布局如果是固定 6 列 grid 可能留 1 空位,flex 自适应排版会自动重排(用户视觉确认后再决定是否调整)。

## 6. 保留的 3 个 Layer A 因子卡片在网页的位置

| 卡片 | 产生位置 | linked_layer | 注释 |
|---|---|---|---|
| `onchain_lth_supply_90d_change_{date}` | factor_card_emitter.py:780 | **Layer A**(本 sprint 改) | strategy_impact 中加 "used by Layer A onchain_packet" |
| `onchain_lth_realized_price_{date}` | `_emit_onchain_reference` 共享 ref 循环 | L2(未改) | 函数级注释说明 used by Layer A |
| `onchain_sth_realized_price_{date}` | 同上 | L2(未改) | L2 仍保留消费(波段背景) |

> 说明:`lth_realized_price` / `sth_realized_price` 卡仍在 `_emit_onchain_reference` 共享循环中,
> linked_layer="L2" 是历史标签。该循环还包含 `mvrv` / `realized_price` 等(非纯 Layer A)。
> 若用户希望严格按"Layer A 卡片应在 Layer A 区域",可在后续 sprint 把这 2 个卡拆出循环单独 emit。

## 7. 后续 backlog(不在本 sprint 范围)

### Backlog-1:state_builder.py 整体退役
- `src/pipeline/state_builder.py` 是 v1.2 retired path(scheduler 已 disabled)
- 包含的 5 个 v1.2 Factor stub(CyclePositionFactor / TruthTrendFactor / BandPositionFactor /
  CrowdingFactor / MacroHeadwindFactor)+ 5 个 Layer*Stub 当前对系统行为无影响
- 整体退役需要独立 sprint,先确认 `_assemble_context` 是否还有合法消费方(API + factor_cards_refresher)
- 建议触发时机:本 Layer B 重构生产稳定运行 2 周后

### Backlog-2:composite/_base.py 评估
- state_builder.py 退役后,composite 目录只剩 `_base.py` 抽象基类
- 评估是否还有继承方,无则整删 composite/ 目录

### Backlog-3:kpi/metrics.py PIPELINE_STAGES 中 cycle_position 相关 stage 清理
- 历史 strategy_runs 仍含 `"cycle_position_last_stable_lookup"` 和 `"composite.cycle_position"` stage 名
- 删了会让历史数据无法 KPI 化,需要数据迁移评估
- 与 Backlog-1 一起做

### Backlog-4:网页 composite tier 布局微调(可选)
- composite 一排从 6 个 → 5 个,如果是固定 6 列 grid 可能留 1 空位
- 用户使用时视觉确认后再决定是否调整

### Backlog-5:thresholds.yaml 中 layer_2_direction / layer_3_opportunity 整体退役
- 这两节剩余配置(stance_confidence_floor / ceiling / long_grade_rules / short_grade_rules /
  grade_a_floors 等)0 consumer
- 本 sprint 只做了 cycle_position 相关 key 的 surgical 清理
- 整体退役建议与 Backlog-1 同 sprint

### Backlog-6:realized_price 卡 linked_layer 重打 Layer A
- 当前 `lth_realized_price` / `sth_realized_price` 卡 linked_layer="L2",
  实际上数据被 Layer A 引用更多
- 建议把它们从 `_emit_onchain_reference` 循环拆出单独 emit,linked_layer 改为 "Layer A"

## 8. 测试结果

| Step | Pre-step pytest | Post-step pytest | 通过率变化 |
|---|---|---|---|
| Step 1(prompt only) | baseline | 1880 pass / 1 fail (pre-existing) | 无变化 |
| Step 2(code + delete cycle_position.py) | 1880 pass | 1876 pass / 1 fail (pre-existing) | -4(空表 4 测试随 schema 删除,1880→1876) |
| Step 3(web emitter) | 1876 pass | 1876 pass / 1 fail (pre-existing) | 无变化 |
| Step 4(carryover + modeling) | 1876 pass | **1876 pass / 1 fail (pre-existing) / 1 skip** | 无变化 |

预存失败:`tests/test_jobs_fetch_attempts_integration.py::test_collect_klines_1h_kline_succeeds_derivatives_fail`
— 与 Layer B 因子重构**完全无关**(K 线 collector / derivatives error handling 问题),
git stash 干净状态下也失败。

## 9. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | ❌ 待用户审完 4 个 commit 后执行 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(本次无 schema 变更,DB 表结构不动) |

## 10. 部署后验证建议

push + restart 之后,建议用户:
1. 看下一次 11:35 BJT Layer B pipeline 运行日志,确认 AI 调用无异常
2. 看网页"原始数据因子"区,确认:
   - 3 个保留卡片仍在(lth_supply_90d_change / lth_realized_price / sth_realized_price)
   - 3 个删除卡片消失(composite_cycle_position;另 2 个本来就没有 emitter card)
3. 看 L3 反模式输出,确认 4 类反模式工作正常(JSON 输出中无 `is_against_long_cycle` key)
4. 看 FLIP_WATCH 状态(如有),确认冷却时长是 base 时长(18-96h)而非乘数后
5. 看 L2 stance / phase 输出质量,密切观察前 7 天是否有显著质量下降

## 11. 风险提示

**主要风险**:L2 stance 定义重写

- L2 stance 定义重写后,AI 在前几天可能会有判断偏移
- 建议密切观察 thesis 创建情况(频率 / 方向 / confidence_score 分布)
- 如果 7 天内发现 L2 stance 质量显著下降,**回滚选项**:`git revert 77ba672`(Step 1)
  即可恢复 L2 prompt 旧定义
- 其他 Step 不需要回滚(数据采集和 DB 不动,回滚 Step 1 后 Layer B 会继续工作但 stance 用旧定义,
  rule_cycle_position 字段仍为 None — AI 会在 long_cycle_context 输出处给保守 fallback)

**次要风险**:state_builder.py retired path 中 CyclePositionFactor stub

- state_builder.py:622 仍调用 `CyclePositionFactor().compute(context)` — 已 stub 成
  `_RetiredV12Module`,运行时抛 NotImplementedError → `_run_stage` 捕获 → degraded fallback
- 与其他 4 个 v1.2 retired Factor 一致,scheduler 已 disabled,生产端不触发
- 整体退役见 Backlog-1

**架构风险**:网页"Layer A 区域 vs Layer B 区域"无严格分离

- 当前 `layerAFactorCardSpecs()` 是 Layer A 显式 specs 列表,但保留的 3 个卡片
  通过 Layer B emitter 产生 + linked_layer 标签自动归类
- 用户可能看到"Layer A 标签的卡片在 Layer B 区域出现"或反之
- 不影响 AI 决策,仅 UI 视觉一致性问题。见 Backlog-6

## 12. 与上次审计(2026-05-17)的差异

| 维度 | 上次审计 | 本次执行 |
|---|---|---|
| 结论 | Backlog 归档,不动手 | 4 commit 全链路清理 |
| 前提 | L2 stance 定义不动 | L2 stance 可改 |
| 判断标准 | "保留所有,提 A/B/C 路径让用户选" | "波段判断价值" 单一标准 |
| 实际删除 | 0 | 6 个因子全链路 + 7 个 yaml block + 5 个测试 + 2 个 Python 函数 + 1 个 Python 文件 |

## 13. modeling.md 同步修改 3 处

| 位置 | 改动 |
|---|---|
| [§3.2.5 CyclePosition 计算](../modeling.md) | 顶部加"⚠️ 历史设计 — 已于 2026-05-19 退役"标注,正文保留作历史参考 |
| [§3.3.2 L2 AI 方向结构分析师](../modeling.md) | 末尾加 2026-05-19 更新说明:CyclePosition 输入移除 + long_cycle_context 字段删除 + 反模式 4 类 |
| [§4.3.6 FLIP_WATCH 冷却时长(新增节)](../modeling.md) | 新增整节说明:cycle_position 乘数删除,统一 base 时长 + 设计权衡 + 未来恢复路径 |

---

**报告完**。
