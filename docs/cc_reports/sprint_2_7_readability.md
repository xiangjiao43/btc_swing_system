# Sprint 2.7-readability — 4 文件人读输出层重写为人话

**Date:** 2026-04-25
**Branch:** main
**Type:** refactor / display strings only(不动业务逻辑)

---

## 一、4 个独立 commit

| commit | 文件 | 摘要 |
|---|---|---|
| `b2934a8` | `docs/style_guide_human_readable.md`(新建,202 行) | 风格指南:适用范围 / 术语清单 / 翻译表 / 4 段格式 / 样例对比 / 自检流程 |
| `c94b2d5` | `src/evidence/pillars.py`(±100 行) | `_l1/l2_downstream_hint` + `_pillars_l3` rule_trace + L4 拥挤度/事件窗口 + L5 downstream_hint 全部翻译;新加 `_REGIME_HUMAN / _STANCE_HUMAN / _PHASE_HUMAN / _PERM_HUMAN / _GRADE_HUMAN` 5 张翻译表 |
| `8cfb186` | `src/strategy/composite_composition.py` 6 个 narrator(±60 行) + 旧测试更新 | 6 个 narrator 的 `current_analysis` + `strategy_impact` 全部去机器味,内联翻译表;旧 `TestStrategyImpactCitation`(断言 §X.Y 引用)改成 `TestStrategyImpactHumanReadable`(断言"§"和"L*."不出现) |
| `7496e7a` | `src/evidence/plain_reading.py` + `src/strategy/factor_card_emitter.py` + `tests/test_human_readable_style.py`(新建,210 行) + `tests/test_plain_reading.py`(4 处断言更新) | 5 层 plain_reading 翻译;factor_card_emitter 45+ 张卡的 `plain_interpretation` + `strategy_impact` 全部按 4 段格式重写(📍 / 📊 / 🔍);新加守门员测试扫所有展示字段无禁止术语 |

---

## 二、关键改造原则

### 2.1 严格保留(从未触碰)

- 函数签名、参数名、return 字段名(`matched_rule` / `upgrade_conditions` /
  `current_analysis` / `strategy_impact` / `plain_interpretation` 等 key 名前端在用)
- if/elif/else 分支条件
- 所有阈值数字(>= 6 / < -5 / 0.55 / 0.75 等)
- 计算逻辑、累加、归一化、percentile 算法
- 任何字典的 key
- state 中所有业务字段(stance / regime / phase / grade / permission / position_cap
  这些 key 不动,值不动 — 只改"展示给人看的字符串")
- `_make_card` 调用的非展示参数(card_id / category / tier / impact_direction /
  impact_weight / linked_layer / source / value_unit / current_value 等)
- 所有 `_safe_float / _percentile_180d / _impact_direction_from_value / _composite_direction`
  等工具函数

### 2.2 严格禁止(对照风格指南 §3)

```
❌ stance / regime / phase / cycle_position(英文枚举值)
❌ grade / opportunity_grade / execution_permission / permission
❌ position_cap / fallback_level / extreme_event_detected
❌ §3.8.4 / §4.4.2 等章节引用
❌ L4.crowding_multiplier / L5.macro_headwind_score 等系统字段路径
❌ trade_plan / stop_loss / take_profit(改成"交易计划"/"止损价"/"止盈位")
❌ ambush_only / cautious_open / can_open / hold_only / protective(必须翻译)
❌ early_bull / mid_bull / distribution / accumulation 等英文枚举(必须翻译)
❌ chaos / transition_up / transition_down(必须翻译)
```

### 2.3 4 段格式(原始因子卡专用)

```
{数值}                                       ← current_value 字段
📍 这个指标在测什么: {1-2 句}                ← strategy_impact
📊 当前怎么解读: {对当前数值的解读 + 档位}   ← plain_interpretation 第 1 段
🔍 历史阈值参考: {3-4 个关键阈值的语言}      ← plain_interpretation 第 2 段
```

实施:`plain_interpretation` 内含 `📊` 和 `🔍` 两段用 `\n` 分隔。

---

## 三、改造的卡列表(commit 4 范围)

### 3.1 组合因子卡(6 张)

`src/strategy/factor_card_emitter.py::_emit_composite_cards` 的 `_composite_specs`
+ `_composite_plain_reading`:
- truth_trend / band_position / cycle_position / crowding / macro_headwind / event_risk

### 3.2 链上 primary(6 张)

MVRV-Z / NUPL / LTH 90d Change / Exchange Net Flow 7d / 距 ATH 跌幅 / Reserve Risk

### 3.3 衍生品 primary(4 张)

资金费率当前 / 资金费率 30 日分位 / OI 24h 变化 / 大户多空比

### 3.4 技术指标 primary(3 张)

ADX-14(1D) / ATR 180 日分位 / 多周期方向一致性

### 3.5 宏观 primary(2 张)

DXY 20 日变化 / VIX

### 3.6 链上 reference(7 张)

MVRV / Realized Price / LTH Realized Price / STH Realized Price / SOPR / aSOPR / Puell Multiple

### 3.7 衍生品 reference(6 张)

资金费率 7 日均 / 资金费率 Z 90d / OI 当前 / 24h 清算 / LSR 24h 变化 / 全交易所资金费率

### 3.8 技术指标 reference(4 张)

MA 20/60/120/200(包括数据不足占位)

### 3.9 宏观 reference(4 张)

US10Y 30 日变化 / 纳指 20 日变化 / BTC-纳指 60 日相关性 / BTC-黄金 60 日相关性

### 3.10 事件 reference(3 张)

下次 FOMC / 下次 CPI / 下次 NFP

**总计 45 张 = 6 组合 + 21 primary + 18 reference**(含 4 张 MA 占位)

---

## 四、自动化保护

### `tests/test_human_readable_style.py`(210 行)

4 个测试类,每个跑一次注入函数后扫所有展示字段:

| 测试类 | 覆盖模块 | 扫描字段 |
|---|---|---|
| `TestPillarsNoMachineTerms` | `inject_pillars` | core_question / downstream_hint / completeness_warning / pillars[].interpretation / rule_trace.matched_rule / rule_trace.upgrade_conditions[] |
| `TestCompositeNarrativesNoMachineTerms` | `inject_composite_composition` | composite_factors[k] 的 current_analysis / strategy_impact / value_interpretation / rule_description / affects_layer |
| `TestPlainReadingNoMachineTerms` | `inject_plain_readings` | layer_*.plain_reading |
| `TestFactorCardsNoMachineTerms` | `emit_factor_cards` | 每张 card 的 plain_interpretation / strategy_impact |

禁止模式清单(对照风格指南 §3):

```python
FORBIDDEN_PATTERNS = [
    r'\bstance\s*=\s*\w+',
    r'\bregime\s*=\s*\w+',
    r'\bphase\s*=\s*\w+',
    r'§\d+\.\d+',                                  # §X.Y
    r'\bL\d\.\w+_\w+',                              # L4.crowding_multiplier
    r'\bambush_only\b', r'\bcautious_open\b',
    r'\bcan_open\b', r'\bno_chase\b', r'\bhold_only\b',
    r'\btrade_plan\b',
    r'\btransition_up\b', r'\btransition_down\b',
    r'\bearly_bull\b', r'\bmid_bull\b', r'\blate_bull\b',
    r'\bearly_bear\b', r'\bmid_bear\b', r'\blate_bear\b',
]
```

任何未来的 commit 重新引入禁止术语,本测试会立即在 CI 阻止。

---

## 五、pytest 验收

```
$ .venv/bin/python -m pytest tests/ -q
395 passed, 1 skipped, 84 warnings in 1.89s
```

新增:
- `tests/test_human_readable_style.py`:4 个 case
- `tests/test_composite_narrative.py::TestStrategyImpactHumanReadable`:6 个 case(替换旧 §X.Y 断言)

更新:
- `tests/test_plain_reading.py`:4 处断言改为新文案("末段" / "高等级机会" / "中等级机会" / "低等级参考机会" / "优先级 1")

---

## 六、设计决策

### 6.1 翻译表内联 vs 集中
选择**内联**(每个文件自带局部翻译表):
- 不引入新 import
- 函数自包含,容易追踪
- 重复定义(如 stance 翻译表)的代价小,各自上下文略有差异(口语 vs 简短标签)

### 6.2 4 段格式 vs 新增字段
按用户原指令的"折中实施":
- `strategy_impact` 容纳 `📍 这个指标在测什么`(指标本质)
- `plain_interpretation` 容纳 `📊 当前怎么解读`(数值解读)+ `🔍 历史阈值参考`(阈值表)
- 两段用 `\n` 分隔,前端 `<p style="white-space: pre-wrap">` 渲染成多行

未新增字段,前端零改动。

### 6.3 fallback 文案保留
`_FALLBACK_TEXT = "基础数据暂未就绪,无法生成态势分析"` 已经是人话,保留。

### 6.4 旧测试是否调整
- `test_plain_reading.py`:测试断言更新到新文案(4 处)
- `test_composite_narrative.py::TestStrategyImpactCitation`:删除整个类(旧的 §X.Y 断言),换成 `TestStrategyImpactHumanReadable` 反向断言"§ 和 L*. 不出现"

---

## 七、部署 + 验证

```
$ git push  # 4 commits: b2934a8, c94b2d5, 8cfb186, 7496e7a
$ ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && git pull && sudo systemctl restart btc-strategy && .venv/bin/python scripts/run_pipeline_once.py'
active
pipeline.failure_count: 0
```

部署后用浏览器 / curl 抽查:
- composite_factors[*] 6 张卡:`current_analysis` / `strategy_impact` 中文人话,无 §X.Y / L*. / stance=*
- evidence_reports.layer_3.rule_trace.matched_rule:中文人话
- evidence_reports.layer_3.rule_trace.upgrade_conditions[]:中文人话
- factor_cards 抽查 5 张:`plain_interpretation` 含 `📊` + `🔍` 双段,`strategy_impact` 含 `📍` 解释

---

## 八、未覆盖项 / 风险

1. **`_l5_downstream_hint`(行 ~440)**:之前没有,本 sprint 新加的中文版还有改进空间(过于书面化),后续可继续打磨
2. **L1 `vol_label` / `stability_label` 等部分简短英文枚举(`actively_shifting` 等)**:在 plain_reading_l1 中通过翻译表已映射,但如果未来新增枚举值,需要补
3. **factor_cards 中"📍 这个指标在测什么"段**:目前的指标解释偏教学性,有些用户可能希望更短;可在用户反馈后调整
4. **风格指南执行靠测试 + 自律**:守门员测试只覆盖文档里列出的禁止模式,如果未来新加禁止术语忘了同步加 pattern,会漏检 — 需在更新 CLAUDE.md「报告写作纪律」时同步
5. **指标颜色 / emoji 统一**:目前 📍 / 📊 / 🔍 是约定,如果前端改 CSS / 不渲染 emoji,字符仍是好的回退
