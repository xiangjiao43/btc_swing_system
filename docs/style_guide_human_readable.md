# 人读输出层风格指南(Sprint 2.7-readability)

本文是后续所有"人读字符串"重写的唯一标准。任何新增的展示字段、报告 narrative、
评论、tooltip 都按本指南执行。

## 1. 适用范围

本指南适用于"展示给最终用户(策略所有者)看"的字符串字段,即:

- `src/strategy/composite_composition.py` 的 `_xxx_narrative` 函数(6 个)
- `src/evidence/plain_reading.py` 的 `plain_reading_lN` 函数(5 个)
- `src/evidence/pillars.py` 的 `_pillars_lN` 返回的 `interpretation` / `core_question` /
  `downstream_hint` / `matched_rule` / `upgrade_conditions` 等字符串字段
- `src/strategy/factor_card_emitter.py` 的每张 card 的 `plain_interpretation` /
  `strategy_impact`

不适用:
- 函数 docstring(给开发者看,可保留专业术语)
- 日志(`logger.info(...)`)
- Pytest 错误信息
- DB schema / 字段名

## 2. 必须保留的币圈通用术语清单

这些术语用户已经懂或愿意学,直接用英文 + 必要时首次出现加中文注解:

✅ **链上**:MVRV / NUPL / LTH(长期持有者) / SOPR / aSOPR / Reserve Risk / Puell Multiple / 实现价格(Realized Price)
✅ **技术**:ADX / ATR / MA-20 / MA-60 / MA-120 / MA-200
✅ **衍生品**:OI(未平仓合约) / Funding(资金费率) / 多空比 / 清算 / 基差(basis) / Put/Call
✅ **宏观**:DXY(美元指数) / US10Y(10 年期美债收益率) / VIX(恐慌指数) / 纳指 / 标普 500 / 黄金
✅ **事件**:FOMC / CPI / NFP
✅ **K 线**:1H / 4H / 1D / 1W

注:首次出现可加中文括号(例:`OI(未平仓合约)`),同一段后续再出现直接用英文。

## 3. 绝对禁止的系统内部术语

以下系统字段名 / 枚举值 / 章节引用 **不得**出现在用户可见字符串里:

❌ **状态字段名**:`stance` / `stance_confidence` / `regime` / `phase` / `cycle_position`
❌ **机会层字段**:`grade` / `opportunity_grade` / `execution_permission` / `permission`
❌ **风险字段**:`position_cap` / `fallback_level` / `extreme_event_detected`
❌ **建模章节引用**:`§3.8.4` / `§4.4.2` / `§4.5.5` 等
❌ **系统路径**:`L4.crowding_multiplier` / `L5.macro_headwind_score` / `L2.动态门槛表` 等
❌ **合约英文术语**:`trade_plan` / `stop_loss` / `take_profit` → 必须翻译
❌ **执行许可英文枚举**:`ambush_only` / `cautious_open` / `can_open` / `no_chase` /
   `hold_only` / `protective` → 必须翻译
❌ **周期英文枚举**:`early_bull` / `mid_bull` / `late_bull` / `distribution` /
   `accumulation` / `early_bear` / `mid_bear` / `late_bear` / `unclear` → 必须翻译
❌ **市场状态英文枚举**:`chaos` / `transition_up` / `transition_down` /
   `trend_up` / `trend_down` → 必须翻译

## 4. 翻译速查表(完整)

### 方向(stance)
| 英文 | 中文 |
|---|---|
| `stance=bullish` | "倾向看多" / "偏多结构" |
| `stance=bearish` | "倾向看空" / "偏空结构" |
| `stance=neutral` | "方向不明" / "多空难辨" |

### 市场状态(regime)
| 英文 | 中文 |
|---|---|
| `regime=trend_up` | "上升趋势确立" |
| `regime=trend_down` | "下跌趋势确立" |
| `regime=transition_up` | "趋势在转向多头但还没站稳" |
| `regime=transition_down` | "趋势在转向空头但还没站稳" |
| `regime=range_high` | "高位震荡" |
| `regime=range_mid` | "中位震荡" |
| `regime=range_low` | "低位震荡" |
| `regime=chaos` | "市场失序" |

### 波段阶段(phase)
| 英文 | 中文 |
|---|---|
| `phase=early` | "趋势初段" |
| `phase=mid` | "趋势中段" |
| `phase=late` | "趋势末段" |
| `phase=exhausted` | "衰竭期" |
| `phase=unclear` / `n_a` | "波段位置不明" |

### 长周期位置(cycle_position)
| 英文 | 中文 |
|---|---|
| `cycle_position=accumulation` | "底部累积期" |
| `cycle_position=early_bull` | "牛市早期" |
| `cycle_position=mid_bull` | "牛市中段" |
| `cycle_position=late_bull` | "牛市晚期" |
| `cycle_position=distribution` | "顶部派发期" |
| `cycle_position=early_bear` | "熊市早期" |
| `cycle_position=mid_bear` | "熊市中段" |
| `cycle_position=late_bear` | "熊市晚期" |
| `cycle_position=unclear` | "周期位置不明朗" |

### 机会等级(grade)
| 英文 | 中文 |
|---|---|
| `grade=A` | "高等级机会"(信心高) |
| `grade=B` | "中等级机会"(信心中) |
| `grade=C` | "低等级参考机会"(信心低) |
| `grade=none` | "暂无符合条件的机会" |

### 执行许可(permission)
| 英文 | 中文 |
|---|---|
| `permission=can_open` | "可以开仓" |
| `permission=cautious_open` | "谨慎开仓" |
| `permission=ambush_only` | "只允许埋伏单" |
| `permission=no_chase` | "不追单" |
| `permission=hold_only` | "仅持仓不开新" |
| `permission=watch` | "仅观察,不开仓" |
| `permission=protective` | "保护性减仓" |

### 字段术语
| 英文 | 中文 |
|---|---|
| `position_cap` | "建议仓位上限" |
| `stop_loss` | "止损价" |
| `take_profit` | "止盈位" |
| `trade_plan` | "交易计划" |
| `stance_confidence ≥ 0.55` | "做多信心要超过 55%" |
| `stance_confidence ≥ 0.75` | "做空信心要超过 75%" |
| `position_cap × 0.7` | "仓位上限收紧到 70%" |
| `position_cap × 0.85` | "仓位上限轻度下调(× 85%)" |

## 5. 4 段固定字段格式(原始因子卡专用)

每张原始因子卡的 `plain_interpretation` + `strategy_impact` 必须组合呈现 4 段:

```
{数值}                                    ← current_value 字段已经显示
📍 这个指标在测什么: {1-2 句, 用户能懂}     ← 放 strategy_impact 字段
📊 当前怎么解读: {对当前数值的解读 + 档位}  ← 放 plain_interpretation 第 1 段
🔍 历史阈值参考: {3-4 个关键阈值的语言}    ← 放 plain_interpretation 第 2 段
```

**实施细节**:
- `strategy_impact` 字段:1 行,以 `📍 ` 开头
- `plain_interpretation` 字段:2 段,以 `📊 ` 开头,中间换行,后接 `🔍 `
- 多段用 `\n` 分隔(前端 `<p style="white-space: pre-wrap">` 渲染成多行)

## 6. 样例对比

### 6.1 组合因子卡 — 长周期位置

❌ 原:
```
"MVRV-Z=0.83、NUPL=0.31、距 ATH -32.1%、判档 early_bull。"
```
✅ 新:
```
"MVRV-Z 0.83 偏低,链上估值还在价值区。NUPL 0.31 说明市场整体在盈利但远未过热。"
"距历史高点还有 32% 空间。三个特征叠加,BTC 处在牛市早期。"
```

❌ 原:
```
"对应建模 §3.8.4 牛市早期(做多最佳窗口);驱动 L2.动态门槛表 上调多头阈值或下调空头阈值。当前 L2.stance=neutral。"
```
✅ 新:
```
"牛市早期是做多最佳窗口。但开仓前还要看其他证据:现在方向不明,系统保持观望。等方向明确,系统就会考虑做多。"
```

### 6.2 五层证据链 L3

❌ 原:`"stance=neutral 不满足任何档; regime=transition_up,过渡/混乱期 A/B 门槛不开"`
✅ 新:`"方向不明,趋势刚开始转向多头但还没站稳,目前不满足任何机会档位。"`

❌ 原:`"stance_confidence ≥ 多头门槛 0.55(牛市早期)或空头门槛 0.75"`
✅ 新:`"做多信心达到 55% 以上(牛市早期门槛),或做空信心达到 75%"`

❌ 原:`"grade=none → AI 强制 watch,不给交易计划"`
✅ 新:`"暂无符合条件的机会,系统强制观望,不下交易计划。证据真不够。"`

### 6.3 原始因子卡 — 资金费率

❌ 原:
- `plain_interpretation`: `"资金费率深度为负,空头拥挤,反向挤压潜在"`
- `strategy_impact`: `"Crowding 主因子,>0.03% 且连续 3 次 → +2 分"`

✅ 新:
- `plain_interpretation`:
  ```
  📊 当前怎么解读: -0.49% 轻微偏空,空头略付多头,情绪温和偏空,拥挤度低。
  🔍 历史阈值参考: > 0.03% 连续 3 次为多头过度拥挤(警告);-0.01% ~ 0.01% 为正常区间;< -0.05% 为空头过度拥挤(反弹信号)。
  ```
- `strategy_impact`: `"📍 这个指标在测什么: 永续合约多空双方互付的费率。正值=多头付空头,负值=空头付多头。极端值反映市场情绪和拥挤度。"`

## 7. 自检流程(写完任何展示字符串后必跑)

1. 对照 §3 的禁止术语列表 grep 当前输出
2. 对照 §4 的翻译表确认枚举值已翻译
3. 对照 §5 的 4 段格式确认原始因子卡结构
4. 跑 `pytest tests/test_human_readable_style.py`,0 fail 才能 commit

## 8. 历史 commit 引用

- Sprint 2.7 之前(commit `e0ac4a0` 及更早)产出的展示字符串 **未遵循本指南**
  — 那是历史包袱,本 sprint 系列重写
- 本指南成立于 commit `<this commit>`,后续所有展示字符串改动以此为准
