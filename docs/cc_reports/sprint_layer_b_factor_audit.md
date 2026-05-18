# Sprint Layer B 因子审计(纯调查 + 三档清单 + 重构建议)

**日期**:2026-05-17
**目的**:Layer A 独立成型,Layer B 应回归"纯波段合约策略"。审计 Layer B 当前因子,识别 cycle-flavored 因子能否移除。
**范围**:纯调查,不改任何代码 / 配置 / 数据。
**当前状态**:**Backlog 归档**。本审计输入将作为未来 Layer B 建模工程的依据,**当前不动手**(原因:L2 判断核心逻辑改动需要先和用户做 Layer B 整体职责对齐设计,避免与 Layer B 建模工程返工)。

---

## ⭐ Backlog 待办(供未来 Layer B 建模工程取用)

> **BACKLOG-LAYER-B-01:L2 cycle 判断路径合并到 Layer A**
>
> Layer B 的 L2 层目前存在与 Layer A 六阶段大周期判断重复的逻辑(`rule_cycle_position` 9 档 + L2 输出 `long_cycle_context` + `anti_pattern_signals.is_against_long_cycle`),双轨独立计算 cycle 判断,存在 Layer A 6 阶段与 Layer B 9 档语义不一致风险。
>
> **未来 Layer B 建模工程必须执行(路径 B)**:
> - L2 input ctx 删 `rule_cycle_position`,改读 `latest_layer_a_spot_strategy.cycle_adjudicator.official_stage_recommendation`(Layer A 6 阶段)
> - L2 prompt 第 4 节(long_cycle_context)改写:从"读规则给的 cycle label 后同意/异议"变为"直接引用 Layer A 阶段输出"
> - `anti_pattern_signals.is_against_long_cycle` 改读 Layer A 6 阶段名,删去对 9-band cycle_position 集合的依赖
> - `composite/cycle_position.py CyclePositionFactor` 可保留作 historic / fallback,但 Layer B 主路径不再依赖
> - `_LAYER_B_CONTEXT_FACTORS` / `_FACTOR_SOURCE` 等不动(数据采集层无需改)
>
> **保留(不删)**:L2 的 `lth_realized_price` / `sth_realized_price` / `lth_supply_90d_pct_change` / `sth_supply_90d_pct_change` 这 4 个字段保留 — 它们被 L2 stance 定义硬绑定("LTH 累积/派发"),与 Layer A 数据源同源但角度不同(L2 用于"波段方向是否与长期持有者一致"),不应删除。
>
> **触发时机**:Layer B 整体建模 sprint 启动时 — **不要独立做此重构**(L2 stance 定义改动会影响波段判断质量,必须与 Layer B 其他模块的职责重定义同步)。
>
> **现在不要做**:本 sprint 决议保留全部因子和逻辑,审计入档作为 Layer B 建模 sprint 的 backlog 输入。

---

## 1. Layer B 完整因子清单(按层组织)

输入装配点:[src/ai/context_builder.py:588-810 `build_full_context()`](src/ai/context_builder.py#L588-L810),给每层组装一个 `lN_ctx` dict + 共享 `computed_indicators`。

### L1(regime / 市场状态) — context['l1']

只读 `computed_indicators` 子集 + `klines_1d_30d_close` + `previous_l1`。

| 因子 | 数据源 | 用途(L1 prompt 角度)|
|---|---|---|
| `ema_20_current` / `ema_50_current` / `ema_200_current` | 日 K rolling EMA | 趋势判定 |
| `ema_20_4h_current` / `ema_50_4h_current` | 4h K rolling EMA | 短中期趋势对齐 |
| `adx_14_1d_current` / `adx_14_1d_5d_avg` | 日 K | 趋势强度 |
| `atr_14_1d_current` / `atr_180d_percentile` | 日 K | 波动率水平 |
| `price_position_in_90d_range` | 日 K | 90 日相对位置 |
| `current_close` / `max_drawdown_60d_pct` / `ema_50_slope_30d` | 日 K | 当前价格 + 60 日回撤 + 50EMA 斜率 |
| `swing_5_recent` / `swing_high_3_recent` / `swing_low_3_recent` | 日 K | 最近 5 个摆动点 + 高低点 |
| `klines_1d_30d_close` | 日 K 最近 30 天收盘 | 给 AI 看完整序列 |

**性质**:**100% 波段技术因子**,与"大周期"无关。

### L2(direction / 方向 + phase + key_levels + long_cycle_context) — context['l2']

读 `computed_indicators`(同 L1)+ `rule_cycle_position` + `klines_1d_30d_close` + `previous_l2`,**+ orchestrator 注入的 l1_output**。

| 因子 | 数据源 | 用途 | 性质 |
|---|---|---|---|
| (L1 同款 EMA / swing / current_close 等)| 同 L1 | K 线结构 + EMA 对齐 | 波段 ✅ |
| **`lth_supply_90d_pct_change`** | onchain 派生(`compute_lth_sth_changes`)| stance 提示("LTH 累积/派发")| **长周期 ⚠️** |
| **`sth_supply_90d_pct_change`** | 同上 | 同上 | **长周期 ⚠️** |
| **`exchange_net_flow_30d_sum`** | onchain 派生 | stance 提示(流入流出)| 中期 ⚠️ |
| **`lth_realized_price`** | onchain | stance 提示(价格 vs 长期成本)| **长周期 ⚠️** |
| **`sth_realized_price`** | onchain | stance 提示(价格 vs 短期成本)| 中长周期 ⚠️ |
| **`funding_rate_current`** / **`funding_rate_z_score_90d`** | derivatives | stance 衍生品情绪 | 波段 ✅ |
| **`rule_cycle_position`**(label + confidence + voting_details)| [composite/cycle_position.py `CyclePositionFactor`](src/composite/cycle_position.py),输入是 MVRV-Z + NUPL + LTH 90d + ATH drawdown | L2 输出 `long_cycle_context.ai_assessment`(同意/异议规则给的 cycle label)| **典型大周期 ⚠️⚠️⚠️** |
| `previous_l2` | 上轮 strategy_state | 连续性 | 中性 |

**L2 prompt 第 4 条角色**:"long_cycle_context(长周期位置背景,可同意或异议规则给的 CyclePosition)"。**L2 显式承担长周期判断职能** —— 这是 Layer A 独立化前的设计遗产。

**L2 stance 定义里硬绑定 LTH**:
> bullish — ... **长持有者(LTH)持仓在累积**
> bearish — ... **LTH 持仓在派发**

去掉 LTH 字段需要同步改 stance 定义。

### L3(opportunity / 机会)— context['l3']

**不直接读 indicator**,只读:
- `risk_preview`(funding_z + oi_z + events_count 一句话总结)
- `current_state`(上一次 14 档 strategy_state)
- `previous_l3` + orchestrator 注入的 `l1_output / l2_output / anti_pattern_signals`

**性质**:**纯 routing 层**,无原始因子。

### L4(risk / 风险失效)— context['l4']

读 `computed_indicators`(短期风险子集)+ orchestrator 注入的 `l1_output / l2_output / l3_output`。

| 因子 | 数据源 | 用途 |
|---|---|---|
| `funding_rate_current` / `funding_rate_z_score_90d` / `funding_rate_30d_max` | derivatives | 多空拥挤度 |
| `open_interest_current` / `open_interest_z_score_90d` | derivatives | 杠杆水平 |
| `exchange_net_flow_30d_sum` / `exchange_net_flow_30d_max_outflow` | onchain | 流动性/流出极值 |
| `max_drawdown_60d_pct` / `ema_50_slope_30d` | 日 K | 短中期下行风险 |
| `current_close` | 日 K | 计算硬失效位 |

**性质**:**100% 波段风险因子**(衍生品情绪 + 30d 流 + 短中期回撤)。

### L5(macro / 宏观背景)— context['l5']

**完全独立**,不读 L1-L4 输出,只读 `computed_macro_indicators` + `events_calendar_72h` + `extreme_event_flags`。

| 因子 | 数据源 | 性质 |
|---|---|---|
| `dxy_current / _30d_change_pct / _90d_change_pct` | FRED | 短中期 ✅ |
| `us10y_yield_current / _30d_change_bps` | FRED | 短中期 ✅ |
| `us2y_yield_current / yield_curve_2_10_spread_bps` | FRED | 短中期 ✅ |
| `vix_current / _30d_avg / _90d_max` | FRED | 短中期 ✅ |
| `nasdaq_current / _30d_change_pct / _90d_change_pct` | FRED | 短中期 ✅ |
| `global_m2_yoy_pct` | FRED | **长周期 ⚠️** 但作为 macro stance 入参合理 |
| `fed_balance_sheet_30d_change_pct` | FRED | 中期 ✅ |
| `btc_dominance_current / _30d_change_pct` | coinglass | 中期 ✅ |
| `etf_flow_30d_sum_usd` / `etf_flow_7d_sum_usd` | coinglass | 短中期 ✅ |
| `events_calendar_72h`(数组)| events_calendar 表 | 短期事件 ✅ |
| `extreme_event_flags`(5 个 bool:flash_crash / stablecoin_depeg / 地缘冲突 / 银行危机 / 监管)| `detect_extreme_events()` | 短期事件 ✅ |

**性质**:**主体波段-macro,与 Layer A 宏观共享数据但用法不同**(L5 = 短期 macro stance / 极端事件;Layer A = 长周期估值环境)。

### 派生层:anti_pattern_signals

[src/ai/anti_pattern_signals.py:41-66 `is_against_long_cycle()`](src/ai/anti_pattern_signals.py#L41-L66) 读 L2 输出的 `long_cycle_context.ai_assessment` / `rule_cycle_position`,**间接依赖 L2 的长周期判断**。

---

## 2. 三档清单

### 【建议保留】L1 全员 + L3 全员 + L4 全员 + L5 全员(约 40 个因子)

理由:
- **L1**:ADX/ATR/EMA/swing 是波段判定的物理基础,无大周期成分
- **L3**:纯 routing,不带原始因子
- **L4**:funding/OI/30d 流 + 短中期回撤 = 波段交易风险标准面板
- **L5**:macro stance 的角度与 Layer A 长周期估值不同(短期事件 + DXY/VIX 30d 动量 + ETF 流);即使因子名重叠(DXY/M2/CPI/Nasdaq 等),**两边语义独立,保留无冗余成本**

特别说明:
- L5 的 `global_m2_yoy_pct` / `fed_balance_sheet_30d_change_pct` 看似长周期,但作为 macro stance 入参合理(流动性环境),保留
- L4 的 `exchange_net_flow_30d_sum` / `_max_outflow` 是 30 天滑窗,与 L2 的同名字段重复读,但 L4 用途是"流动性风险",L2 用途是"stance 提示",不同信号,保留

### 【建议删除】无确定"可以直接删"的因子

理由:
- 表面上看 L2 的 `rule_cycle_position` / `lth_realized_price` 等是"Layer A 重叠",但 L2 当前 prompt 把它们用作 stance 的链上锚点 — **直接删会让 L2 stance 失去客观依据,质量下降**
- "删除"不是无成本的;需要先重构 L2 prompt + stance 定义 + anti_pattern_signals,才能撤掉

### 【存疑 / 需用户判断】L2 的 4 个长周期字段 + anti_pattern 1 条规则

| 字段 | 位置 | 当前用途 | 与 Layer A 重叠?| 重构选项 |
|---|---|---|---|---|
| `rule_cycle_position`(label / confidence / voting_details)| L2 context | L2 输出 `long_cycle_context.ai_assessment`,供 anti_pattern 判 stance vs cycle 反向 | **完全重叠**(Layer A 6 阶段)| **重构路径 A**:删 `rule_cycle_position` 路径,改 L2 读 `latest_layer_a_spot_strategy.cycle_adjudicator.official_stage_recommendation`(Layer A 6 阶段直接当 long_cycle_context)|
| `lth_realized_price` / `sth_realized_price` | L2 `computed_indicators` | L2 stance 用作"价格 vs 长期成本"提示 | Layer A 用作 onchain_packet realized_price 三件套 | **重构路径 B**:保留两份独立读取(都来自同源 onchain_metrics);或 L2 prompt 改成"参考 Layer A 已实现价格"减少 prompt 长度 |
| `lth_supply_90d_pct_change` / `sth_supply_90d_pct_change` | L2 `computed_indicators` | L2 stance 定义里"LTH 累积/派发" | Layer A 用作 onchain_packet supply 变化 | 同上,**保留两份独立**最简单 |
| `anti_pattern_signals.is_against_long_cycle` | L3 输入 | stance 与 cycle_position 反向 → 反模式信号 | 与 Layer A 6 阶段语义重叠 | 若选重构路径 A,这里要从读 Layer A `cycle_adjudicator` 阶段判定;若不重构,保留 |

**3 条重构路径(待用户选择)**:

**路径 A(轻度)— 完全保留,不改任何代码**
- 优点:零风险,L2 / anti_pattern 继续工作
- 缺点:Layer A 与 Layer B 双轨重复计算 cycle 判断;`composite/cycle_position.py CyclePositionFactor` 9 档与 Layer A 6 阶段语义不一致(potential 不一致风险)
- 何时选:Layer A 还需更长时间 stabilize、希望 Layer B 独立 fallback

**路径 B(中度)— L2 改读 Layer A 输出作 long_cycle_context**
- 改动面:`src/ai/context_builder.py:l2_ctx` 不再带 `rule_cycle_position`,改带 Layer A 最新阶段 + 置信度;L2 prompt 改写第 4 节(long_cycle_context 来源 + ai_assessment 含义);anti_pattern_signals.is_against_long_cycle 改读 Layer A 6 阶段名;`CyclePositionFactor` 可以保留作 historic,但 Layer B 不再依赖
- 优点:Cycle 判断统一在 Layer A,Layer B 引用,避免不一致;Layer A 的 6 阶段比 9 档 cycle_position 更精炼
- 缺点:L2 失去独立 fallback(Layer A 跑失败时 L2 不知道 cycle);需要兼容旧记录(stage 名映射)
- 何时选:Layer A 已稳定 ≥ 1-2 周,愿意把 Layer B 与 Layer A 软耦合

**路径 C(重度)— L2 完全去掉所有 cycle / LTH 字段,纯波段**
- 改动面:L2 ctx 删 `rule_cycle_position` + `lth_supply_90d_pct_change` + `sth_supply_90d_pct_change` + `lth_realized_price` + `sth_realized_price`;L2 prompt 改 stance 定义去掉"LTH 累积/派发"句、删第 4 节 long_cycle_context;anti_pattern_signals 删 `is_against_long_cycle`;Master 输出 schema 去掉 long_cycle_context 字段
- 优点:Layer B 彻底纯波段,与 Layer A 完全解耦;prompt 大幅简化
- 缺点:L2 stance 失去链上锚点(只剩 K 线 + EMA + 4h 一致性),牛熊不同方向下质量可能下降;用户每天看 Layer B,可能感觉 stance "不够厚"
- 何时选:愿意接受 stance 质量小幅下降换取架构清晰;Layer A 永远跑成功

---

## 3. 与网页"原始数据因子"模块对照

模块来源:[web/assets/app.js:1940-1944 `rawFactorCards()`](web/assets/app.js#L1940-L1944) = `state.factor_cards`(Layer B emitter)+ `layerAFactorCardSpecs`(Layer A specs)。

Layer B emitter 产生的卡片由 [src/strategy/factor_card_emitter.py `emit_factor_cards()`](src/strategy/factor_card_emitter.py) 动态产出,约 25-35 张,与 L1-L5 实际读的因子相关。

**网页可见但属"L2 大周期嫌疑"的卡片**(对应路径 A/B/C 决策):
- `rule_cycle_position` 卡片(若 emitter 产)→ 重构路径 B/C 删
- `lth_realized_price` / `sth_realized_price` 卡片 → 这两个 Layer A specs 已有(`onchain_packet` 字段),L2 这边重复展示;C 路径下 L2 那张可删
- `lth_supply_90d_pct_change` / `sth_supply_90d_pct_change` 卡片 → 同上

**网页可见但属 Layer A 复制嫌疑的因子**(已知重叠):
- Layer A 6 阶段(在交易员结论横幅)+ Layer B emitter 的 `cycle_position` 卡片(若有)→ 两个不同模型同时展示给用户看,可能让用户困惑。**重构路径 B/C 后 cycle_position 卡片应删**

---

## 4. 数据完整性提醒

本次纯审计,所有数据完整:
- `src/composite/cycle_position.py` 完整保留(Layer B 的 9-band cycle 因子)
- `_FACTOR_SOURCE` / `_A1_CORE_FACTORS` / `_LAYER_B_CONTEXT_FACTORS` 集合完整
- 测试套 1880 + 1 + 1 不变

未来按选定路径开 sprint 时,本报告作为 backlog 参考。

---

## 5. 部署四件事清单(纯调查)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A(无改动)|
| GitHub 推送 | N/A(无改动)|
| 服务器 git pull | N/A |
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 | N/A |
