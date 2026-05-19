# Sprint Layer B 因子重新审计(波段判断价值视角)

**日期**:2026-05-19
**审计性质**:纯调查,无代码 / 配置 / 数据变更
**前置审计**:[sprint_layer_b_factor_audit.md](sprint_layer_b_factor_audit.md)(2026-05-17,backlog 归档,结论已过期)
**触发**:用户重新定位 Layer B 职责 — "只负责波段方向 / 入场 / 止损 / 仓位",大周期判断归 Layer A;上次审计前提"L2 stance 当前定义不动"已被推翻。

---

## 1. 审计范围与判断标准

### 1.1 范围

5 个 Layer B prompt + 1 个 ctx_builder:
- [src/ai/agents/prompts/l1_regime.txt](../../src/ai/agents/prompts/l1_regime.txt)
- [src/ai/agents/prompts/l2_direction.txt](../../src/ai/agents/prompts/l2_direction.txt)
- [src/ai/agents/prompts/l3_opportunity.txt](../../src/ai/agents/prompts/l3_opportunity.txt)
- [src/ai/agents/prompts/l4_risk.txt](../../src/ai/agents/prompts/l4_risk.txt)
- [src/ai/agents/prompts/l5_macro.txt](../../src/ai/agents/prompts/l5_macro.txt)
- [src/ai/context_builder.py](../../src/ai/context_builder.py)(887 行,18 个 helper)
- 派生:[src/ai/anti_pattern_signals.py](../../src/ai/anti_pattern_signals.py)
- 重叠对照:[src/ai/agents/prompts/layer_a_cycle_adjudicator.txt](../../src/ai/agents/prompts/layer_a_cycle_adjudicator.txt) + [src/ai/spot_cycle_context_builder.py](../../src/ai/spot_cycle_context_builder.py)

### 1.2 唯一判断标准 — 波段判断价值

判断"删 / 留"的依据**只有一条**:这个因子对 Layer B 下面 4 件事的贡献:
1. 波段方向(未来几周到几月 BTC 偏多还是偏空)
2. 入场时机(回踩等仓位 / 突破追入 / 等待)
3. 止损位(`hard_invalidation_levels` 候选)
4. 仓位大小(`position_cap_multiplier` 微调)

**严格不作为判断标准**:
- 时间尺度(90d 链上因子如果对波段有不可替代贡献,留;7d K 线因子如果在制造误判,删)
- 与 Layer A 的字段名重叠(语义独立的重叠允许保留)
- "看起来像长周期" / "看起来像短周期"

### 1.3 与上次审计的根本分歧

| 维度 | 上次审计(2026-05-17) | 本次审计(2026-05-19) |
|---|---|---|
| 前提 | L2 stance 定义不动(LTH 累积/派发 是硬绑定) | L2 stance 定义可改 |
| 判断标准 | "看起来是大周期就标 ⚠️" | "对波段判断的真实贡献" |
| 结论 | 全保留 + 提出 3 条路径(A/B/C)让用户选 | 给出具体 4 档分类 + 9 个具体改动 |
| 立场 | 中立陈述 | 明确推荐 |

---

## 2. 各层因子全清单

### 2.1 L1(regime / 市场状态)— 12 个因子

数据装配点:[context_builder.py:767-771 `l1_ctx`](../../src/ai/context_builder.py#L767-L771)

| # | 因子 | 数据源 | 时间尺度 | Prompt 角色 | 问题 A:服务什么决策 | 问题 B:删了影响 |
|---|---|---|---|---|---|---|
| 1 | `klines_1d_30d_close` | K 线 1d | 30d | 给 AI 看完整 30 天收盘序列 | 波段方向 + 大周期位置 | **严重负面**:K 线序列是 regime 判断地基 |
| 2 | `current_close` | K 线 1d | 即时 | 现价 | 全部 4 件事 | **严重负面**:无现价 = 系统无法运作 |
| 3 | `ema_20_current` | K 线 1d 派生 | 1d × 20 | 短期趋势线 | 波段方向 + 入场时机 | **严重负面**:EMA-20 是波段方向核心 |
| 4 | `ema_50_current` | K 线 1d 派生 | 1d × 50 | 中期趋势线 | 波段方向 + 止损位 | **严重负面**:EMA-50 是波段中期支撑 + 常作止损 |
| 5 | `ema_200_current` | K 线 1d 派生 | 1d × 200 | 长期趋势线 | 背景参考(价格在长期均线上方/下方) | 中等负面:对波段判断有补充价值,知道你在长期均线上方更敢做多 |
| 6 | `ema_20_slope_30d` | K 线 1d 派生 | 30d | EMA-20 斜率(趋势加速度) | 入场时机 | 中等负面:斜率反映"趋势在加速还是减速" |
| 7 | `adx_14_1d_current` | K 线 1d 派生 | 14d | 趋势强度 | 波段方向(分 trend / range / chaos) | **严重负面**:ADX 是 regime 9 档分档关键 |
| 8 | `adx_14_1d_5d_avg` | K 线 1d 派生 | 5d 滚动 | ADX 平滑 | 同上 | 中等负面:防 ADX 单日跳动误判 |
| 9 | `atr_14_1d_current` | K 线 1d 派生 | 14d | 波动率绝对值 | 止损位 + 仓位 | **严重负面**:ATR 决定止损距离 + 仓位削减 |
| 10 | `atr_180d_percentile` | K 线 1d 派生 | 180d 分位 | volatility 4 档(low/normal/elevated/extreme)的唯一客观档位 | 仓位大小 | **严重负面**:volatility 档位直接决定 position_cap 削减 |
| 11 | `price_position_in_90d_range` | K 线 1d 派生 | 90d | 价格在 90 天区间相对位置 | 入场时机(中位 vs 极值)| 中等负面:量化"现在贵还是便宜" |
| 12 | `swing_5_recent` | K 线 1d 派生(zigzag depth=5)| 序列 | 最近 5 个 swing 高低点 | 入场时机 + 止损位 | **严重负面**:swing low 是止损候选,swing 序列是 HH/HL 判断依据 |

**L1 总评**:**100% 波段技术因子**,无长周期 / 无 Layer A 重叠。所有因子都直接服务于波段判断。

### 2.2 L2(direction / 方向 + phase + key_levels + long_cycle_context)— 新增 12 个

数据装配点:[context_builder.py:772-778 `l2_ctx`](../../src/ai/context_builder.py#L772-L778) + orchestrator 注入 `l1_output`

**L2 同 L1 的因子**(全部继承,继续 ★ 必留):
- 全套 EMA / ADX / ATR / swing(L1 列表 #3-#12)

**L2 新增因子**:

| # | 因子 | 数据源 | 时间尺度 | Prompt 角色 | 问题 A | 问题 B |
|---|---|---|---|---|---|---|
| 13 | `ema_20_4h_current` | K 线 4h 派生 | 4h × 20 | 4h 趋势对齐 | 波段方向(多周期一致性) | **严重负面**:4h 与 1d 一致 = stance high tier |
| 14 | `ema_50_4h_current` | K 线 4h 派生 | 4h × 50 | 同上 | 同上 | 中等负面 |
| 15 | `swing_high_3_recent` | K 线 1d 派生 | 序列 | 最近 3 个高点(判 HH 序列) | 波段方向 + 止损位 | **严重负面**:HH/LH 判定依据 |
| 16 | `swing_low_3_recent` | K 线 1d 派生 | 序列 | 最近 3 个低点(判 HL 序列) | 同上 | **严重负面**:HL/LL 判定依据 |
| 17 | `funding_rate_current` | 衍生品 1d | 当日 | 衍生品多空情绪 | 波段方向 + 入场时机 | **严重负面**:funding 极端是反手最早信号 |
| 18 | `funding_rate_z_score_90d` | 衍生品派生 | 90d Z 分 | 拥挤度 | 同上 | **严重负面**:Z 分给出"是否拥挤"的客观档位 |
| 19 | `lth_supply_90d_pct_change` | 链上派生 | 90d %change | L2 stance 定义中"LTH 累积/派发" | **大周期** — 长持有者行为 | 中等正面:LTH 90d %change 通常 ±1-3% 缓变,几乎不对波段方向给出"现在该做多/做空"的清晰信号;但 stance 定义把它当做硬锚定 → 强迫 L2 在 LTH 和 K 线冲突时纠结 |
| 20 | `sth_supply_90d_pct_change` | 链上派生 | 90d %change | 同上(STH 派发对应) | **大周期** | 中等正面:同 #19 |
| 21 | `exchange_net_flow_30d_sum` | 链上派生 | 30d sum | L2 stance 链上锚点 | 波段背景(中期资金流向)| 中等负面:30 天净流是"波段级流动性背景"(几周方向),有真实贡献 |
| 22 | `lth_realized_price` | 链上 | 即时(累积值)| L2 stance "价格 vs 长期成本" | **大周期** — 长期持有者成本基础 | 中等正面:LTH realized price 与波段方向关系微弱;它告诉你长期成本基础但波段判断更需要的是 EMA / swing 关系 |
| 23 | `sth_realized_price` | 链上 | 即时(累积值)| L2 stance "价格 vs 短期成本" | 中长周期 — 短期持有者成本基础 | 中性:STH realized price 比 LTH 更贴近波段(155 天滑窗),但 Layer A 已用 |
| 24 | `rule_cycle_position` | 派生(MVRV-Z + NUPL + LTH-90d + ATH-drawdown)| 慢变 | L2 输出 `long_cycle_context.ai_assessment` | **完全是 Layer A 的职责** | 中等正面:L2 当前用它做"长周期判断 → 喂给 anti_pattern_signals.is_against_long_cycle";Layer A 6 阶段更精确,这个 9 档独立判断与 Layer A 不一致风险大 |

### 2.3 L3(opportunity / 机会)— 无原始因子

数据装配点:[context_builder.py:779-784 `l3_ctx`](../../src/ai/context_builder.py#L779-L784) + orchestrator 注入

L3 不读 raw factor,只读:
- `risk_preview`(3 客观字段:funding_z + oi_z + events_count_72h)
- `current_state`(14 档 strategy_state)
- `anti_pattern_signals`(5 bool,由 [anti_pattern_signals.py](../../src/ai/anti_pattern_signals.py) 产)
- `previous_l3`
- orchestrator 注入的 `l1_output / l2_output`

**派生因子分析**:`anti_pattern_signals.is_against_long_cycle`(行 41-69):
- 读 `l2_output.long_cycle_context.ai_assessment` + `ai_alternative` 与 9 档 cycle_position 比对
- **直接依赖 L2 的 cycle 判断 → 直接依赖 `rule_cycle_position`**
- 如果 L2 删 `rule_cycle_position`,这个 anti_pattern 也跟着改(改读 Layer A 6 阶段)或删除

### 2.4 L4(risk / 风险失效)— 新增 6 个

数据装配点:[context_builder.py:785-790 `l4_ctx`](../../src/ai/context_builder.py#L785-L790) + orchestrator 注入 `l1_output / l2_output / l3_output`

**L4 同 L1/L2 的因子**(全部继承):current_close, ema_50, ema_200, swing_5, atr_14, funding_rate_current, funding_rate_z_score_90d

**L4 新增因子**:

| # | 因子 | 数据源 | 时间尺度 | Prompt 角色 | 问题 A | 问题 B |
|---|---|---|---|---|---|---|
| 25 | `funding_rate_30d_max` | 衍生品派生 | 30d max | 30 天 funding 极值 | 拥挤度风险 | 中等负面:防 z-score 失真(z 计算用 90d,但极值更敏感)|
| 26 | `open_interest_current` | 衍生品 | 即时 | 杠杆水平 | 拥挤度 + 仓位 | **严重负面**:OI 是杠杆度量,L4 crowding 必需 |
| 27 | `open_interest_z_score_90d` | 衍生品派生 | 90d Z 分 | OI 拥挤档位 | 同上 | **严重负面**:Z 分给客观档位 |
| 28 | `exchange_net_flow_30d_max_outflow` | 链上派生 | 30d min | 单日最大流出极值 | 流动性风险 | 中等负面:极值反映恐慌或异常 |
| 29 | `lth_supply_30d_pct_change` | 链上派生 | 30d %change | "LTH 派发开始"风险信号 | **大周期延后信号** | 中性偏正面:LTH 派发是缓变信号,30d %change 通常对 L4 波段风险评估贡献微弱;真要爆发风险通常 funding/OI 先给出更早信号 |
| 30 | `max_drawdown_60d_pct` | K 线 1d 派生 | 60d 滚动 | 最近回撤幅度 | 仓位削减 | 中等负面:量化"波段刚被打的多狠" |

### 2.5 L5(macro / 宏观)— 21 个独立因子

数据装配点:[context_builder.py:791-796 `l5_ctx`](../../src/ai/context_builder.py#L791-L796)

L5 input 显式**不含 L1-L4 输出**(prompt 第二节),纯宏观独立判断。

| # | 因子 | 数据源 | 时间尺度 | Prompt 角色 | 问题 A | 问题 B |
|---|---|---|---|---|---|---|
| 31 | `dxy_current` | FRED | 即时 | 美元强度 | 波段方向(美元强 = BTC 压制)| **严重负面** |
| 32 | `dxy_30d_change_pct` | FRED 派生 | 30d | 美元动量 | 同上 | **严重负面** |
| 33 | `dxy_90d_change_pct` | FRED 派生 | 90d | 美元中期动量 | 背景参考 | 中等负面 |
| 34 | `us10y_yield_current` | FRED | 即时 | 长债收益率 | 流动性环境 | **严重负面** |
| 35 | `us10y_30d_change_bps` | FRED 派生 | 30d bps | 长债动量 | 同上 | **严重负面** |
| 36 | `us2y_yield_current` | FRED | 即时 | 短债收益率 | 同上 | 中等负面 |
| 37 | `yield_curve_2_10_spread_bps` | FRED 派生 | 即时 | 收益率曲线倒挂 | 衰退预警 | 中等负面 |
| 38 | `vix_current` | FRED | 即时 | 风险情绪 | 波段方向 + extreme_event 触发 | **严重负面**(VIX > 35 强制 extreme_event)|
| 39 | `vix_30d_avg` | FRED 派生 | 30d | VIX 基线 | 同上 | 中等负面 |
| 40 | `vix_90d_max` | FRED 派生 | 90d max | VIX 历史极值 | 同上 | 中等负面 |
| 41 | `nasdaq_current` | FRED | 即时 | 风险资产联动 | 波段方向 | **严重负面**(BTC vs Nasdaq 60d 相关 ~0.5-0.7)|
| 42 | `nasdaq_30d_change_pct` | FRED 派生 | 30d | Nasdaq 动量 | 同上 | **严重负面** |
| 43 | `nasdaq_90d_change_pct` | FRED 派生 | 90d | 中期动量 | 背景参考 | 中等负面 |
| 44 | `global_m2_yoy_pct` | FRED | yoy(12 月)| 全球流动性 | **长周期背景** | 中性:M2 yoy 变化以季度计,对几周到几月波段判断影响极小;作为长期 macro stance 仍合理 |
| 45 | `fed_balance_sheet_30d_change_pct` | FRED 派生 | 30d | 美联储缩表/扩表 | 流动性环境 | 中等负面 |
| 46 | `btc_dominance_current` | CoinGlass | 即时 | BTC 占比 | 波段方向(altcoin 资金轮动)| 中等负面 |
| 47 | `btc_dominance_30d_change_pct` | CoinGlass 派生 | 30d | dominance 动量 | 同上 | 中等负面 |
| 48 | `etf_flow_30d_sum_usd` | CoinGlass | 30d sum | BTC ETF 资金流 | 波段方向 + macro stance | **严重负面**(ETF 流是 macro stance 核心信号)|
| 49 | `etf_flow_7d_sum_usd` | CoinGlass | 7d sum | 短期 ETF 加速度 | 同上 | **严重负面** |
| 50 | `events_calendar_72h`(数组)| events_calendar 表 | 72h | FOMC / CPI / NFP 等 | 入场时机(避险)| **严重负面** |
| 51 | `extreme_event_flags`(5 bool:geopolitical / banking / regulatory / flash_crash / stablecoin_depeg)| `detect_extreme_events()` | 即时 | extreme_event 触发 PROTECTION | 仓位削减(强制保护)| **严重负面**(硬约束)|

---

## 3. 四档分类清单

> 重要:**时间尺度不是分类依据**。LTH 90d %change(大周期)归 ◑ 倾向删除,是因为它对波段判断贡献微弱;EMA-200 / global_m2_yoy(长周期)归 ★ 必留或 ◯ 倾向保留,是因为它们对波段判断有清晰背景贡献。

### 3.1 ★ 必留(删了波段判断会更不准)— 共 37 个

**L1(全 12 个)**:
ema_20_current, ema_50_current, ema_200_current(背景), ema_20_slope_30d, adx_14_1d_current, adx_14_1d_5d_avg, atr_14_1d_current, atr_180d_percentile, swing_5_recent, price_position_in_90d_range, current_close, klines_1d_30d_close

**L2 新增 6 个**:
ema_20_4h_current, ema_50_4h_current, swing_high_3_recent, swing_low_3_recent, funding_rate_current, funding_rate_z_score_90d

**L4 新增 4 个**:
funding_rate_30d_max, open_interest_current, open_interest_z_score_90d, exchange_net_flow_30d_max_outflow

**L5 必留 15 个**:
dxy_current, dxy_30d_change_pct, us10y_yield_current, us10y_30d_change_bps, vix_current, vix_30d_avg, vix_90d_max, nasdaq_current, nasdaq_30d_change_pct, fed_balance_sheet_30d_change_pct, etf_flow_30d_sum_usd, etf_flow_7d_sum_usd, events_calendar_72h, extreme_event_flags(5 个 bool 视为 1 项)

### 3.2 ◯ 倾向保留(有不可替代背景价值,但 prompt 用途需明确化)— 共 6 个

- **L2:`exchange_net_flow_30d_sum`** — 30 天净流是中期波段流动性背景(几周方向),保留但 prompt 重新定位
- **L4:`max_drawdown_60d_pct`** — 量化波段刚承受的回撤,影响 position_cap 微调
- **L5:`dxy_90d_change_pct`** — 90 天美元动量,中期 macro 背景
- **L5:`us2y_yield_current` + `yield_curve_2_10_spread_bps`** — 短端利率 + 曲线形态,衰退预警背景
- **L5:`nasdaq_90d_change_pct`** — Nasdaq 中期动量,作为相关性背景
- **L5:`btc_dominance_current / _30d_change_pct`** — alt 资金轮动,中期波段背景
- **L5:`global_m2_yoy_pct`** — 长期流动性环境(M2 yoy 变化以季度计,对波段直接影响小,但作为 macro stance 长期锚点合理)

### 3.3 ◑ 倾向删除(删了无害或更聚焦)— 共 5 个

- **L2:`lth_supply_90d_pct_change`**
- **L2:`sth_supply_90d_pct_change`**
- **L2:`lth_realized_price`**
- **L2:`sth_realized_price`**
- **L4:`lth_supply_30d_pct_change`**

### 3.4 ✗ 必删(在制造误判或与 Layer A 完全重复)— 共 1 项(+ 派生 1)

- **L2:`rule_cycle_position`**(label + confidence + voting_details)
- **派生:`anti_pattern_signals.is_against_long_cycle`** — 改为读 Layer A `cycle_adjudicator.official_stage_recommendation`,或随上面同删

---

## 4. 删除影响评估(◑ 倾向删除 + ✗ 必删,逐项)

### 4.1 ✗ 必删:L2 `rule_cycle_position`

**当前位置**:
- 装配:[context_builder.py:775 `l2_ctx["rule_cycle_position"]`](../../src/ai/context_builder.py#L775)
- 来源:[composite/cycle_position.py `CyclePositionFactor`](../../src/composite/cycle_position.py)(输入:MVRV-Z + NUPL + LTH 90d + ATH drawdown 投票)
- 引用:L2 prompt 第八节(long_cycle_context),要求 AI 给 `agree / disagree / neutral` + `ai_alternative`(9 档之一)
- 下游消费:[anti_pattern_signals.py:41-69 `is_against_long_cycle`](../../src/ai/anti_pattern_signals.py#L41-L69)

**删除好处**:
- **避免双轨重复**:Layer A 已经用 6 阶段做了大周期判断,Layer B 再用 9 档 `rule_cycle_position` 独立判断,两个体系语义不一致(`accumulation` / `early_bull` 等 9 档 vs `bear_bottom` / `recovery` 等 6 阶段),用户看到两个 cycle 标签可能困惑
- **避免 L2 AI 纠结**:当 K 线显示 HH+HL(bullish)但 `rule_cycle_position=late_bull`(应警惕),L2 AI 需要在"波段方向"和"长周期警告"间纠结 — 这恰好是 Layer A 的职责,Layer B 不应承担
- **明确职责边界**:Layer B 只需要知道"我的 stance 是否与 Layer A 阶段一致" → 直接读 Layer A 输出即可
- **简化 anti_pattern**:`is_against_long_cycle` 改读 Layer A 阶段名(`bear_decline` / `top_distribution` → 看空,`bear_bottom` / `recovery` / `bull_main` → 看多),逻辑更清晰

**删除代价**:
- **L2 失去独立 cycle fallback**:Layer A 跑失败时,L2 不再有"我自己算的 cycle"作为兜底 — 但 Layer A 是独立 pipeline,失败时应该走 PROTECTION,而不是让 L2 用 9 档兜底(那只会引入第三种状态)
- **某些 edge case 下 L2 stance 失去链上验证**:例如 K 线看多 + Layer A 在 `bear_decline` → L2 当前会标 `is_against_long_cycle=True`,删除后这个矛盾仍能由 Layer A 阶段判定捕获,不损失信息
- **历史回测断点**:`composite/cycle_position.py` 可以保留为 historic / fallback(用户决定是否真删函数本身)

**Layer A 已有的处理**:
- Layer A 6 阶段 `bear_bottom / recovery / bull_main / bull_late / top_distribution / bear_decline` 完整覆盖大周期
- Layer A 输出已通过 `latest_layer_a_spot_strategy` 表持久化,被 `api/routes/strategy.py:_overlay_latest_layer_a_spot_strategy` 注入网页响应
- **结论**:Layer B 重复读取无必要,信息已经在 Layer A 那里更精准

**L2 stance 定义改写建议**:
- 当前(prompt 第四节):
  > bullish — ... 4h 与 1d 方向一致看多,**长持有者(LTH)持仓在累积**
  > bearish — ... 4h 与 1d 方向一致看空,**LTH 持仓在派发**
- 改为:
  > bullish — ... 4h 与 1d 方向一致看多,**[长期资金动向锚点删除]**
  > bearish — ... 4h 与 1d 方向一致看空

**下游影响**:
- `anti_pattern_signals.is_against_long_cycle` — 改读 Layer A 输出(具体改法见 §6)
- master_adjudicator prompt — 当前未引用 long_cycle_context(只引用 l2_output 整体),无需改
- validator — 当前 Validator 23(narrative 必须含层间一致性)不依赖 cycle 字段,无需改
- web 模块 — 若 emitter 产生 `rule_cycle_position` 卡片(参见上次审计 §3),应删除该卡

---

### 4.2 ◑ 倾向删除:L2 `lth_supply_90d_pct_change`

**当前位置**:
- 装配:[context_builder.py:769](../../src/ai/context_builder.py#L769)(通过 `compute_lth_sth_changes`)
- 引用:L2 prompt 第四节 stance 定义(LTH 累积/派发),Few-shot 示例 1 第 286 行

**删除好处**:
- LTH 90d %change **是个缓变信号**:LTH 持仓量是约 700w+ 个 BTC 的统计值,90 天 %change 通常落在 ±1-3% 区间,极少给出"波段方向"信号
- 波段方向(几周到几月)主要由 **K 线结构 + 多周期 EMA 一致性 + funding 情绪**决定 — LTH 90d %change 的"波段方向贡献"接近 0
- 删除后 L2 prompt 不再需要回答"LTH 在累积还是派发" → 减少 AI 推理负担
- Layer A 已经用全套 LTH 指标(`lth_supply` / `lth_net_position_change` / `lth_sopr` 等)做大周期判断

**删除代价**:
- L2 stance 定义需配套改写(把"LTH 累积/派发"句删除)
- 用户网页上若有 LTH 90d %change 因子卡(来自 emitter),需调整说明
- 当 LTH 90d %change 极端值(±5% 以上,罕见)时,L2 会失去这个"长期资金大动作"的预警 — 但 Layer A 阶段一旦变更会通过 `is_against_long_cycle` anti_pattern 间接反映

**波段场景反例**(理论上可能损失):
- K 线刚出现 HH+HL(bullish 早期)+ LTH 90d -3.5%(大量派发)→ L2 当前会降 stance_confidence_tier;删除后 L2 不知道这事,可能错给 high tier
- **但这种情况下 Layer A 阶段会判 `bull_late` / `top_distribution`,Layer B 通过新的 anti_pattern(从 Layer A 阶段比对)仍能捕获 → 信息不丢**

**Layer A 已有的处理**:Layer A onchain_packet 显式包含 `lth_supply` + `lth_net_position_change`,且 Layer A prompt 第三节明确把"LTH 派发"作为 `bull_late` / `top_distribution` 的核心特征。

**L2 stance 定义需改写**:见 §4.1 已经合并改写。

---

### 4.3 ◑ 倾向删除:L2 `sth_supply_90d_pct_change`

**当前位置 + 引用**:同 `lth_supply_90d_pct_change`(L2 prompt 第四节 Few-shot 示例 1)

**删除好处**:STH(短期持有者,持仓 < 155 天)% 90d change 与 LTH 是镜像;LTH 90d %change 已被删除,STH 同因。

**删除代价**:同 4.2,信息冗余,Layer A 已覆盖。

---

### 4.4 ◑ 倾向删除:L2 `lth_realized_price`

**当前位置**:
- 装配:[context_builder.py:701](../../src/ai/context_builder.py#L701)
- 引用:L2 prompt 第四节(stance "价格 vs 长期成本")+ 第七节 `key_levels.major_support` 候选

**删除好处**:
- LTH realized price 是**整个长持有者群体的平均成本**(可能 30,000-50,000 美元,远低于现价),它告诉你"长期资金还在水下/水上"
- 对波段判断(未来几周方向)**几乎无信息价值** — 它变化以季度计算,波段层面是常量
- L2 prompt 第七节让 AI 把 lth_realized_price 作为 `major_support` 候选 — 但**这个用法不准确**:LTH realized price 在牛市中段往往离现价很远(差 30%+),不是真正的"支撑"
- 真正的 major_support 应该是 EMA-200 / 主要 swing low / 200w MA 等近距离结构位

**删除代价**:
- L2 失去一个 `major_support` 候选 — 但 EMA-200 / 200w MA(后者来自 Layer A 数据)是更准确的长期支撑
- Layer A onchain_packet 已显式包含 lth_realized_price + sth_realized_price + realized_price 三件套,用户能在 Layer A 的因子展示里看到

**Layer A 已有的处理**:[spot_cycle_context_builder.py:441-443](../../src/ai/spot_cycle_context_builder.py#L441-L443),三个 realized_price 都已在 onchain_packet 输出。

---

### 4.5 ◑ 倾向删除:L2 `sth_realized_price`

**当前位置 + 引用**:同 `lth_realized_price`

**特殊性**:STH realized price 比 LTH 更贴近波段(短期持有者成本基础 = 最近 155 天进场者的平均成本),理论上当 BTC 跌破 STH realized price 时 = 短线持有者全员浮亏 = 中期下行确认。

**评估**:
- 这个信号**在中长期波段判断里有微弱价值**,但波段层判断更直接的信号是 EMA-50 / EMA-200 跌破
- Layer A 已用 STH realized price,如果用户希望网页保留这个因子展示,Layer A 已经满足
- 删除后 Layer B prompt 减负;保留则继续冗余

**判断**:**◑ 倾向删除**,但争议性最大 — 这是 §8 决策点之一。

---

### 4.6 ◑ 倾向删除:L4 `lth_supply_30d_pct_change`

**当前位置**:
- 装配:[context_builder.py:699](../../src/ai/context_builder.py#L699)
- 引用:L4 prompt 第二节 input 描述,Few-shot 示例 1 第 263 行(用作"链上 LTH 派发开始"风险信号)

**删除好处**:
- 30d %change 比 90d 更敏感,但 LTH 派发对**波段层风险评估**(L4 的核心任务)价值有限:
  - L4 关注未来几天到几周的风险,LTH 30d 派发是缓变信号
  - 真要爆发风险时,funding/OI 极端值会更早给出信号(funding z-score、OI 拥挤等)
  - LTH 30d %change 在 L4 prompt Few-shot 出现 1 次,且并非决定性证据
- Layer A 已用同源数据做大周期判断,L4 重复读取无必要

**删除代价**:
- L4 失去"链上风险维度"中的 1 条 LTH 派发信号 — 但 L4 的链上风险主要由 `exchange_net_flow_30d_sum` + `_max_outflow` 承载,这两个是更直接的"流动性风险"指标
- 边缘情况:LTH 在 30 天内大量派发(罕见,通常对应 top distribution)而衍生品没反应 — 但这种情况 Layer A 阶段已经报警

**判断**:删

---

## 5. 保留理由 + 用途明确化建议(◯ 倾向保留)

### 5.1 L2 `exchange_net_flow_30d_sum` — ◯ 倾向保留

**当前用途**(L2 prompt 第四节):L2 stance 提示("链上资金流动")

**为什么不能删**:
- 30 天净流是真实的"波段背景"信号 — 几周到几月时间尺度的资金流向
- **波段场景举例**:连续 30 天净流出 8500 BTC = 中期资金正在从交易所(投机)转向冷钱包(持有)= 中期看多背景;反之净流入 5000 BTC = 资金回流交易所准备抛售 = 中期看空背景
- 这个信号对波段方向(未来 1-3 月)有真实贡献,且 K 线 + EMA + funding 都不能直接替代
- L4 也读这个因子做"流动性风险"(不同语义,见 §6)

**当前 prompt 用途描述**:Few-shot 示例 1 第 287 行 "LTH 持仓 90d +1.63% 累积,STH 持仓 -0.85% 派发,长期资金信任度高" — 这句把 exchange_net_flow 和 LTH 混在一起说"长期资金"

**建议改写**:
- 把 exchange_net_flow_30d 从"L2 stance 链上锚点"重新定位为"**30 天波段流动性背景**"
- prompt 第四节里把它的角色从"stance 定义的链上验证"改为"波段背景参考"
- 删除 LTH/STH 字段后(§4.2-4.5),exchange_net_flow_30d 成为 L2 唯一保留的链上因子,定位更清晰

### 5.2 L4 `max_drawdown_60d_pct` — ◯ 倾向保留

**当前用途**:[l4_risk.txt:52](../../src/ai/agents/prompts/l4_risk.txt#L52) input + 第七节 risk_breakdown 的"structure_risk" 隐含输入

**为什么不能删**:
- 60 天滚动峰值的回撤是真实的"波段刚被打的多狠"量化
- **波段场景举例**:60 天最大回撤 -22.5% → 即使现在反弹,L4 也应认定 structure_risk 偏高(刚遭遇大跌后市场结构受损);60 天最大回撤 -8.2% → 是正常 trend_up 中的健康回调
- 直接影响 position_cap_multiplier(回撤大时削仓更多)

**Layer A 重叠?**:Layer A 用"距 ATH 回撤" — 看全历史最高点,不同语义(Layer A 是周期级别"现在便宜多少",L4 是波段级别"刚被打的多狠")

**建议**:保留,prompt 用途已明确,无需改写。

### 5.3 L5 `dxy_90d_change_pct` / `nasdaq_90d_change_pct` — ◯ 倾向保留

**当前用途**:L5 prompt 第二节 input(没有 Few-shot 单独引用)

**为什么不能删**:
- 90 天动量提供中期 macro 背景(对比 30d 的短期动量)
- **波段场景举例**:DXY 30d +0.5%(短期持平)但 90d +6%(中期持续强势)→ macro stance 应为 headwind(短期看似平稳但中期压制还在)
- 单独看 30d 容易被短期反弹带偏

**建议**:保留,prompt 第二节 input 描述已含,无需改写。

### 5.4 L5 `us2y_yield_current` + `yield_curve_2_10_spread_bps` — ◯ 倾向保留

**当前用途**:L5 prompt 第二节 input

**为什么不能删**:
- 收益率曲线倒挂(2y > 10y → spread 负)是**衰退预警**信号
- **波段场景举例**:spread -30bps + VIX 18.5(温和)→ 市场尚未对衰退定价,但已是 macro 警告;若 spread 转正同时 VIX 跳到 35+ → 衰退恐慌兑现 = extreme_event
- 对波段方向有真实贡献,且无替代

**建议**:保留,prompt 已含,无需改写。

### 5.5 L5 `btc_dominance_current` / `btc_dominance_30d_change_pct` — ◯ 倾向保留

**当前用途**:L5 prompt 第七节 macro_warnings 中 `crypto_specific` 类别的输入

**为什么不能删**:
- dominance 反映 BTC vs altcoin 资金轮动 — 中期波段背景
- **波段场景举例**:dominance 从 55% → 60% + ETF 流入 → 资金正在从 alt 撤回 BTC = BTC 相对强势波段
- 与 ETF flow 一起构成 "crypto_specific" 维度,对 macro stance 判断有补充

**建议**:保留,prompt 已含。

### 5.6 L5 `global_m2_yoy_pct` — ◯ 倾向保留(争议项)

**当前用途**:L5 prompt 第二节 input + Few-shot 示例 1 narrative 引用

**为什么倾向保留**:
- M2 yoy 反映全球流动性环境(扩张 / 收缩)
- 对波段直接影响小(yoy 变化以季度计),但作为 macro stance "支持 / 逆风" 的**长期背景锚**仍合理
- 如果删除 L5 失去"流动性"维度的核心因子(fed_balance_sheet 是补充信号,不是替代)

**潜在删除理由**:M2 yoy 在几周内通常变化 < 0.5%,L5 已经用 fed_balance_sheet_30d 做"中期流动性",M2 在某种意义是冗余

**判断**:保留,但承认这是争议项 — 见 §8 决策点

---

## 6. 与 Layer A 的因子重叠图谱

> Layer A([spot_cycle_context_builder.py](../../src/ai/spot_cycle_context_builder.py))读取 onchain 25+ / price structure 6+ / macro flow 8+ 因子。

| 类别 | Layer B(当前)| Layer A(当前)| 重叠程度 | 本次审计建议 |
|---|---|---|---|---|
| **LTH 行为** | L2: lth_supply_90d_pct_change, lth_realized_price | onchain_packet: lth_supply, lth_net_position_change, lth_sopr, lth_realized_price | **完全重叠** | 删 L2 侧 |
| **STH 行为** | L2: sth_supply_90d_pct_change, sth_realized_price | onchain_packet: sth_supply, sth_sopr, sth_realized_price | **完全重叠** | 删 L2 侧 |
| **大周期判断** | L2: rule_cycle_position (9 档) | cycle_adjudicator: 6 阶段(bear_bottom / recovery / bull_main / bull_late / top_distribution / bear_decline) | **职责重叠 + 语义不一致** | 删 L2 侧;Layer B 改读 Layer A 阶段 |
| **链上估值** | (Layer B 不直接读 MVRV / NUPL,但通过 rule_cycle_position 间接读)| onchain_packet: mvrv, mvrv_z_score, nupl, rhodl_ratio, reserve_risk, puell_multiple | **间接重叠** | 随 rule_cycle_position 删 |
| **交易所流(链上)** | L2: exchange_net_flow_30d_sum;L4: 同 + _max_outflow | macro_flow_packet: exchange_net_flow | 语义独立(波段背景 vs 周期资金流)| 保留两边 |
| **DXY / VIX / Yields / Nasdaq / M2** | L5: 全套(current + 30d + 90d 动量) | macro_flow_packet: 同套(月级别变化) | 语义独立(短中期 macro stance vs 周期估值环境)| 保留两边 |
| **ETF flow** | L5: etf_flow_30d_sum_usd + _7d_sum_usd | macro_flow_packet: etf_flow | 语义独立(L5 看 30d/7d 动量,Layer A 看趋势)| 保留两边 |
| **价格结构** | L1-L4: EMA-20/50/200 + ATR + ADX + swing + 90d range position | price_structure_packet: 200w MA + 距 ATH + 周/月线结构 + 主要支撑阻力 | **互补,几乎不重叠**(波段技术因子 vs 长期结构) | 保留两边 |
| **衍生品(funding / OI)** | L2 + L4: funding 全套 + OI 全套 | **Layer A 显式不读衍生品**(prompt 第二节明文) | 0 重叠 | Layer B 独占 |
| **极端事件** | L5: extreme_event_flags (5 bool) | (Layer A 不消费极端事件)| 0 重叠 | Layer B 独占 |

**重叠总计**:5 个 L2 因子 + 1 个 L4 因子(共 6 个)和 Layer A 重叠;其余 ~45 个因子是 Layer B 独占 / 语义独立。

---

## 7. 与上次审计结论的最大冲突

上次审计([sprint_layer_b_factor_audit.md](sprint_layer_b_factor_audit.md))结论是**"全保留,Backlog 归档"**。本次审计基于新前提("L2 stance 定义可改 + 判断标准 = 波段判断价值")推翻该结论。

### 冲突 1:`rule_cycle_position`

| 上次 | 本次 |
|---|---|
| "存疑,3 条路径让用户选(A/B/C)" | **✗ 必删**,理由具体:Layer A 6 阶段 + 9 档双轨重复,Layer B 完全可以读 Layer A 输出 |

**差异原因**:上次假设"全保留为零风险路径",但用户现在明确"波段判断价值"是唯一标准。`rule_cycle_position` 对波段方向 / 入场 / 止损 / 仓位的具体贡献接近 0(它只参与一个 anti_pattern 信号),而完全可被 Layer A 阶段替代 → 删除不损失波段判断质量,反而消除双轨语义冲突。

### 冲突 2:`lth_supply_90d_pct_change` + `sth_supply_90d_pct_change`

| 上次 | 本次 |
|---|---|
| "保留 — L2 stance 定义里硬绑定 LTH" | **◑ 倾向删除**,理由:LTH 90d %change 缓变,对波段方向贡献微弱;L2 stance 定义本身就应改写 |

**差异原因**:上次把 L2 stance 定义当成"不可改的约束",本次把它当成"可改的对象"。一旦 stance 定义可改,LTH 因子的"必要性"就坍塌。

### 冲突 3:`lth_realized_price` + `sth_realized_price`

| 上次 | 本次 |
|---|---|
| "保留 — Layer A 同源但角度不同" | **◑ 倾向删除**,理由:Layer A 已暴露三个 realized_price,Layer B 重复读取无波段价值 |

**差异原因**:上次承认"完全重叠但保留",本次按"波段判断价值"标准 — Layer B 重复读取没有不可替代价值就删。

### 冲突 4:总体结论

| 上次 | 本次 |
|---|---|
| 全保留(0 删 0 改) | 1 必删 + 5 倾向删 + 6 倾向保留(用途改写)+ 37 必留 |
| Backlog 归档,不动手 | 给出具体 9 处改动建议,等用户授权动手 |

---

## 8. 留给用户的关键决策点

### D1:L2 stance 定义改写方向(P0)

删除 LTH 锚点后,L2 stance 定义有两个写法:

- **写法 A(纯波段)**:
  > bullish — K 线 HH+HL 序列 + 价格站稳关键支撑 + 4h 与 1d 一致看多
  > bearish — 镜像
  > neutral — 结构混乱或多周期冲突
- **写法 B(波段 + Layer A 阶段)**:
  > bullish — 同上 + 与 Layer A 阶段(bear_bottom / recovery / bull_main)一致
  > bearish — 同上 + 与 Layer A 阶段(bull_late / top_distribution / bear_decline)一致
  > neutral — 结构混乱 或 与 Layer A 阶段反向(留给 anti_pattern 处理)

**推荐**:写法 A(更简洁,Layer A 阶段比对走 anti_pattern 路径)。

### D2:`composite/cycle_position.py CyclePositionFactor` 处置

`rule_cycle_position` 删除后,这个模块的处置:
- **选项 1**:整模块删除([src/composite/cycle_position.py](../../src/composite/cycle_position.py))
- **选项 2**:保留作 historic,只删 context_builder.py 中的调用(Layer B 主路径不再依赖)
- **选项 3**:重写为 Layer A fallback(Layer A 失败时用这个兜底)

**推荐**:选项 1(直接删,Layer A 失败时走 PROTECTION,不靠 Layer B 兜底)。但若用户希望保留历史功能可走选项 2。

### D3:`anti_pattern_signals.is_against_long_cycle` 重写

`rule_cycle_position` 删除后,`is_against_long_cycle` 改写为读 Layer A 阶段:
- bullish 但 Layer A 阶段 ∈ {bull_late, top_distribution, bear_decline} → True
- bearish 但 Layer A 阶段 ∈ {bear_bottom, recovery, bull_main} → True
- 其他 → False

或者**整个 anti_pattern 删除**(Layer A 已经报警,Layer B 重复检查无价值)。

**推荐**:重写而不是删除 — 这是 Layer B 唯一引用 Layer A 输出的入口,有架构价值。

### D4:`sth_realized_price` 是真删还是保留作波段背景

STH realized price 比 LTH 更贴近波段层(短期持有者成本基础)。
- 删:Layer B prompt 更聚焦,信息冗余消除
- 保留:用户网页能看到"价格 vs 短期成本"作为波段背景

**推荐**:删(信息已在 Layer A 暴露,用户能在 Layer A 因子卡区看到)。

### D5:`global_m2_yoy_pct` 是 ◯ 还是 ◑

M2 yoy 对波段直接影响极小(变化以季度计),但作为长期流动性背景仍合理。
- 保留:L5 prompt 完整 macro 维度(流动性 + 利率 + 风险情绪)
- 删:L5 prompt 减负,fed_balance_sheet_30d 已提供短中期流动性

**推荐**:保留(本次归 ◯,不强删)。但若用户偏好极简 prompt,可降为 ◑。

### D6:重构执行顺序

如果用户授权执行,建议顺序:
1. 先做 §4.1(删 `rule_cycle_position` + 重写 `is_against_long_cycle` 读 Layer A)— 这是核心改动,其他依赖它
2. 同 commit 做 §4.2-4.5(删 4 个 L2 LTH/STH/realized_price 字段 + L2 stance 定义改写)— 因为 L2 prompt 和 ctx 一起改避免不一致
3. 单独 commit 做 §4.6(删 L4 `lth_supply_30d_pct_change`)
4. (可选)第 4 步:删 `composite/cycle_position.py`(如选项 1)+ 删 `CyclePositionFactor` 测试

---

## 9. 数据完整性 + 部署四件事 + 删除清单

### 9.1 本审计数据完整性

- 5 个 prompt 全部读取完成(共 1794 行)
- context_builder.py 全文 887 行读取
- spot_cycle_context_builder.py 关键节读取(1331 行中读了 200+ 行)
- orchestrator.py 关键节读取(1003 行中读了 50+ 行)
- modeling.md §0.4 + §3.3.1-3.3.6 + §3.2 读取
- 上次审计 210 行完整读取

### 9.2 部署四件事清单(本次纯调查,无改动)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A(纯调查,无代码改动)|
| GitHub push | N/A |
| 服务器 git pull | N/A |
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 / 清污 | N/A |

### 9.3 本 sprint 删除清单(本次纯调查,无删除)

**本 sprint 无替代关系,无删除项** — 纯调查报告,等用户授权后另起执行 sprint 才动手。

---

## 10. 总结(给用户的一句话)

**Layer B 的 50 个因子,37 个 ★ 必留、6 个 ◯ 倾向保留、5 个 ◑ 倾向删除、1 个 ✗ 必删。最重要的改动是删除 L2 的 `rule_cycle_position` + 重写 `is_against_long_cycle` 改读 Layer A 阶段,这一改 Layer B 与 Layer A 的职责边界就彻底清晰了。其他 LTH/STH 相关字段(4 个 L2 + 1 个 L4)是顺便清理。剩余 43 个因子(K 线技术 + 衍生品 + macro + events)对波段判断都有真实贡献,不动。**
