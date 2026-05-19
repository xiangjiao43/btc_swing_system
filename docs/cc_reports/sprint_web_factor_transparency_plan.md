# Sprint 网页因子展示完整性 + 归属准确性修复计划

**日期**:2026-05-19
**性质**:**纯调查 + 修复计划**,不直接改代码,等用户审完计划再开下个 sprint
**前置 sprint**:[sprint_layer_b_factor_cleanup.md](sprint_layer_b_factor_cleanup.md)(Layer B 因子重构刚部署)
**前置审计 dump 文件**(都在 `ubuntu@124.222.89.86:/tmp/`):
- `/tmp/layer_a_state.json` / `/tmp/layer_a_factor_set.json`(64 inventory factors)
- `/tmp/layer_a_consumed.json`(**45 个 prompt 实际消费**)
- `/tmp/layer_b_factor_set.json` / `/tmp/layer_b_consumed.json`(**32 个 prompt 实际消费**)
- `/tmp/all_cards.json`(50 张 factor_cards 现状)

---

## 1. 调查范围 + 数据来源

### 1.1 用户两项要求

1. **Layer A 三个数据包"支持证据"区** 必须显示 Layer A 实际用到的每一个数据因子(完整性)
2. **网页"原始数据因子"71 张卡** 每张卡左下角的归属标签必须反映**真实使用情况**,简化为 3 档:
   - 只 Layer A 用 → `Layer A`
   - 只 Layer B 用 → `Layer B`
   - 两边都用 → `Layer A / B`

### 1.2 Ground truth(真相基准)

| 概念 | 来源 | 数量 |
|---|---|---|
| **Layer A 实际 prompt 消费** | [src/ai/spot_cycle_context_builder.py:636-685](../../src/ai/spot_cycle_context_builder.py#L636-L685)`build_layer_a_cycle_adjudicator_context()` 三个 packet 的 key_metrics | **45** |
| **Layer B 实际 prompt 消费** | [src/ai/context_builder.py:606-816](../../src/ai/context_builder.py#L606-L816)`build_full_context()` 各 layer ctx | **32** |
| 两层共用(prompt 真消费) | 集合交集 | **8** |
| 真实并集(系统在用) | 集合并集 | **69** |

> 注:Layer A 的 `available_factors` 字典有 64 个因子(`/tmp/layer_a_factor_set.json`),那是**系统级 inventory**(含 funding_rate / open_interest 等 Layer A 实际**不喂 prompt** 的);本表用更严格的"prompt 真消费"标准。

### 1.3 共用 8 个因子(A ∩ B,真实 prompt 消费交集)

| 因子 | Layer A 消费位置 | Layer B 消费位置 |
|---|---|---|
| `dxy` | macro_flow_packet | L5 macro |
| `exchange_net_flow_30d_sum` | macro_flow_packet | L2/L4 onchain |
| `fed_balance_sheet` | macro_flow_packet | L5 macro |
| `m2` | macro_flow_packet | L5 macro |
| `nasdaq` | macro_flow_packet | L5 macro |
| `sth_realized_price` | onchain_packet | L2 onchain(本次 cleanup 用户决策保留) |
| `us2y` | macro_flow_packet | L5 macro |
| `vix` | macro_flow_packet | L5 macro |

---

## 2. Layer A "支持证据"区核对结果

### 2.1 当前 UI 渲染逻辑

[web/assets/app.js:1368-1402 `spotLayerCards()`](../../web/assets/app.js#L1368-L1402):
- 读 `state.layer_a_spot_strategy.data_packets`
- 对每个 packet 把 **整个 `key_metrics` dict** 展开为"支持证据"行(Sprint 1.6.3 已去掉 `.slice(0,5)` 上限)
- UI 注释:"这才是 AI 真实看到的字段全集 — 用户审计需要看完整数据,不藏"

### 2.2 三个 packet 完整性核对(基于今天 10:00 BJT 最新 run)

| Packet | UI 显示字段数 | Prompt 消费字段数 | 缺失字段 (A3) | 冗余字段 (A4) | 结论 |
|---|---:|---:|---:|---:|---|
| **price_structure_packet** | 8 | 8 | **0** | **0** | ✅ 完全一致 |
| **onchain_packet** | 24 | 24 | **0** | **0** | ✅ 完全一致 |
| **macro_flow_packet** | 13 | 13 | **0** | **0** | ✅ 完全一致 |
| **合计** | **45** | **45** | **0** | **0** | ✅ |

### 2.3 详细字段列表(供用户对照)

**price_structure_packet 8 个字段**:
`btc_price` · `ath_drawdown_pct` · `ma_200d` · `ma_200w` · `ma_200w_deviation_pct` · `weekly_structure` · `monthly_ohlc_structure` · `major_support_resistance_zones`

**onchain_packet 24 个字段**:
- 估值(8):`mvrv_z_score` · `mvrv` · `nupl` · `rhodl_ratio` · `reserve_risk` · `puell_multiple` · `hash_rate` · `percent_supply_in_profit`
- 已实现价格(3):`realized_price` · `sth_realized_price` · `lth_realized_price`
- SOPR(3):`sopr` · `lth_sopr` · `sth_sopr`
- 持仓(6):`lth_supply` · `sth_supply` · `lth_supply_90d_pct_change` · `sth_supply_90d_pct_change` · `lth_net_position_change` · `percent_supply_in_loss`
- 链上时间序列(2):`hodl_waves_1y_plus_aggregate` · `cdd`
- 交易所(2):`exchange_balance` · `exchange_net_position_change`

**macro_flow_packet 13 个字段**:
- ETF + 链上流(3):`etf_flow_7d_sum_usd` · `etf_flow_30d_sum_usd` · `exchange_net_flow_30d_sum`
- 利率(3):`real_yield` · `fed_funds_rate` · `us2y`
- 货币 / 央行表(2):`m2` · `fed_balance_sheet`
- 美元 + 风险情绪 + 股市(3):`dxy` · `vix` · `nasdaq`
- 通胀(2):`cpi` · `core_cpi`

### 2.4 修复建议

**Layer A "支持证据"区无需任何代码改动**。当前实现已经做对了:
- 后端 `build_layer_a_cycle_adjudicator_context()` 把所有要给 AI 的字段塞进 `key_metrics`
- 前端 `spotLayerCards()` 全量展开 `key_metrics`,不截断不藏

**无新增 / 无删除**。

---

## 3. 71 张卡片的归属标签修复表(完整版)

### 3.1 总览统计

| 动作 | 数量 | 占比 |
|---|---:|---:|
| 不变(已经对) | 24 | 33.8% |
| 改标签 | 38 | 53.5% |
| 删除(死卡片) | 9 | 12.7% |

### 3.2 修复后标签分布(预期)

| 标签 | 卡片数 | 说明 |
|---|---:|---|
| `Layer A`(只 Layer A 用) | ~24 | 链上估值 / SOPR / hash / 200w MA 等 |
| `Layer B`(只 Layer B 用) | ~21 | K 线 EMA/ADX/ATR + funding/OI + 事件 + 部分 macro |
| `Layer A / B`(共用) | ~8 | dxy/vix/nasdaq/us2y/m2/fed_balance/sth_realized/exchange_net_flow |
| (已删除死卡) | 9 | ↓ |

### 3.3 完整 71 卡片表

**Section A — Emitter 产生的 45 张非 composite 卡(linked_layer 来自 factor_cards.linked_layer)**

| # | card_id(去日期) | 底层 raw 因子 | 当前标签 | 真实归属 | 建议新标签 | 动作 |
|---:|---|---|---|---|---|---|
| 1 | derivatives_btc_dominance | btc_dominance | L5 | Layer B only | `Layer B` | 改 |
| 2 | derivatives_etf_flow | etf_flow | L5 | Layer B only | `Layer B` | 改 |
| 3 | derivatives_funding_rate_30d_pctile | funding_rate | L4 | Layer B only | `Layer B` | 改 |
| 4 | derivatives_funding_rate_7d_avg | funding_rate | L4 | Layer B only | `Layer B` | 改 |
| 5 | derivatives_funding_rate_aggregated | funding_rate | L4 | Layer B only | `Layer B` | 改 |
| 6 | derivatives_funding_rate_current | funding_rate | L4 | Layer B only | `Layer B` | 改 |
| 7 | derivatives_funding_rate_zscore_90d | funding_rate | L4 | Layer B only | `Layer B` | 改 |
| 8 | **derivatives_liquidation_24h** | liquidation_total | L4 | **未使用** | — | **🗑 删** |
| 9 | **derivatives_lsr_change_24h** | long_short_ratio | L4 | **未使用** | — | **🗑 删** |
| 10 | derivatives_oi_24h_change | open_interest | L4 | Layer B only | `Layer B` | 改 |
| 11 | derivatives_oi_current | open_interest | L4 | Layer B only | `Layer B` | 改 |
| 12 | **derivatives_top_long_short_ratio** | long_short_ratio | L4 | **未使用** | — | **🗑 删** |
| 13 | event_cpi_next | events_calendar_72h | None | Layer B only | `Layer B` | 改 |
| 14 | event_fomc_next | events_calendar_72h | None | Layer B only | `Layer B` | 改 |
| 15 | event_nfp_next | events_calendar_72h | None | Layer B only | `Layer B` | 改 |
| 16 | event_options_expiry_major_next | events_calendar_72h | None | Layer B only | `Layer B` | 改 |
| 17 | event_pce_next | events_calendar_72h | None | Layer B only | `Layer B` | 改 |
| 18 | macro_btc_nasdaq_corr_60d | btc_nasdaq_corr_60d | L5 | Layer B only | `Layer B` | 改 |
| 19 | macro_dxy_20d_change | dxy | L5 | A ∩ B | `Layer A / B` | 改 |
| 20 | macro_nasdaq_20d_change | nasdaq | L5 | A ∩ B | `Layer A / B` | 改 |
| 21 | macro_us10y_30d_change | us10y | L5 | Layer B only | `Layer B` | 改 |
| 22 | macro_vix_current | vix | L5 | A ∩ B | `Layer A / B` | 改 |
| 23 | onchain_asopr_primary | sopr | L3 | Layer A only | `Layer A` | 改 |
| 24 | onchain_cdd | cdd | L3 | Layer A only | `Layer A` | 改 |
| 25 | onchain_exchange_flow_7d | exchange_net_flow_30d_sum | L2 | A ∩ B | `Layer A / B` | 改 |
| 26 | onchain_hodl_waves_long | hodl_waves_1y_plus_aggregate | L2 | Layer A only | `Layer A` | 改 |
| 27 | **onchain_lth_mvrv** | lth_mvrv(派生,Layer A 用 mvrv 不用 lth_mvrv) | L2 | **未使用** | — | **🗑 删** |
| 28 | onchain_lth_realized_price | lth_realized_price | L2 | Layer A only | `Layer A` | 改 |
| 29 | onchain_lth_supply_90d_change | lth_supply_90d_pct_change | Layer A | Layer A only | `Layer A` | 不变 |
| 30 | onchain_mvrv | mvrv | L2 | Layer A only | `Layer A` | 改 |
| 31 | onchain_mvrv_z | mvrv_z_score | L2 | Layer A only | `Layer A` | 改 |
| 32 | onchain_nupl | nupl | L2 | Layer A only | `Layer A` | 改 |
| 33 | onchain_realized_price | realized_price | L2 | Layer A only | `Layer A` | 改 |
| 34 | **onchain_ssr** | ssr | L5 | **未使用** | — | **🗑 删** |
| 35 | **onchain_sth_mvrv** | sth_mvrv(派生,Layer A 用 mvrv 不用) | L2 | **未使用** | — | **🗑 删** |
| 36 | onchain_sth_realized_price | sth_realized_price | L2 | A ∩ B | `Layer A / B` | 改 |
| 37 | onchain_sth_supply | sth_supply | L2 | Layer A only | `Layer A` | 改 |
| 38 | price_adx_14_1d | adx_14_1d | L1 | Layer B only | `Layer B` | 改 |
| 39 | price_atr_percentile_180d | atr_180d_percentile | L1 | Layer B only | `Layer B` | 改 |
| 40 | price_drawdown_from_ath | ath_drawdown_pct | L2 | Layer A only | `Layer A` | 改 |
| 41 | **price_ma_120** | ma_120(无人消费) | L1 | **未使用** | — | **🗑 删** |
| 42 | price_ma_20 | ema_20_1d | L1 | Layer B only | `Layer B` | 改 |
| 43 | price_ma_200 | ema_200_1d | L1 | Layer B only | `Layer B` | 改 |
| 44 | **price_ma_60** | ma_60(无人消费) | L1 | **未使用** | — | **🗑 删** |
| 45 | **price_tf_alignment_4h_1d_1w** | tf_alignment(Layer A inventory only,不进 packet) | L1 | **未使用** | — | **🗑 删** |

**Section B — layerAFactorCardSpecs() 26 张硬编码 spec 卡(linked_layer 渲染时都是 `Layer A`)**

| # | spec key | 底层 raw 因子 | 当前标签 | 真实归属 | 建议新标签 | 动作 |
|---:|---|---|---|---|---|---|
| 46 | ath_drawdown_pct | ath_drawdown_pct | Layer A | Layer A only | `Layer A` | 不变 |
| 47 | core_cpi | core_cpi | Layer A | Layer A only | `Layer A` | 不变 |
| 48 | cpi | cpi | Layer A | Layer A only | `Layer A` | 不变 |
| 49 | exchange_balance | exchange_balance | Layer A | Layer A only | `Layer A` | 不变 |
| 50 | exchange_net_position_change | exchange_net_position_change | Layer A | Layer A only | `Layer A` | 不变 |
| 51 | fed_balance_sheet | fed_balance_sheet | Layer A | A ∩ B | `Layer A / B` | 改 |
| 52 | fed_funds_rate | fed_funds_rate | Layer A | Layer A only | `Layer A` | 不变 |
| 53 | hash_rate | hash_rate | Layer A | Layer A only | `Layer A` | 不变 |
| 54 | hodl_waves_1y_plus_aggregate | hodl_waves_1y_plus_aggregate | Layer A | Layer A only | `Layer A` | 不变 |
| 55 | lth_net_position_change | lth_net_position_change | Layer A | Layer A only | `Layer A` | 不变 |
| 56 | lth_sopr | lth_sopr | Layer A | Layer A only | `Layer A` | 不变 |
| 57 | m2 | m2 | Layer A | A ∩ B | `Layer A / B` | 改 |
| 58 | ma_200d | ma_200d | Layer A | Layer A only | `Layer A` | 不变 |
| 59 | ma_200w | ma_200w | Layer A | Layer A only | `Layer A` | 不变 |
| 60 | ma_200w_deviation_pct | ma_200w_deviation_pct | Layer A | Layer A only | `Layer A` | 不变 |
| 61 | major_support_resistance_zones | major_support_resistance_zones | Layer A | Layer A only | `Layer A` | 不变 |
| 62 | monthly_ohlc_structure | monthly_ohlc_structure | Layer A | Layer A only | `Layer A` | 不变 |
| 63 | percent_supply_in_loss | percent_supply_in_loss | Layer A | Layer A only | `Layer A` | 不变 |
| 64 | percent_supply_in_profit | percent_supply_in_profit | Layer A | Layer A only | `Layer A` | 不变 |
| 65 | puell_multiple | puell_multiple | Layer A | Layer A only | `Layer A` | 不变 |
| 66 | real_yield | real_yield | Layer A | Layer A only | `Layer A` | 不变 |
| 67 | reserve_risk | reserve_risk | Layer A | Layer A only | `Layer A` | 不变 |
| 68 | rhodl_ratio | rhodl_ratio | Layer A | Layer A only | `Layer A` | 不变 |
| 69 | sopr | sopr | Layer A | Layer A only | `Layer A` | 不变 |
| 70 | sth_sopr | sth_sopr | Layer A | Layer A only | `Layer A` | 不变 |
| 71 | us2y | us2y | Layer A | A ∩ B | `Layer A / B` | 改 |

### 3.4 死卡片(9 张需删除)详情

| # | card_id | 底层因子 | 死因 |
|---:|---|---|---|
| 8 | derivatives_liquidation_24h | liquidation_total | Layer A 显式排除衍生品;Layer B L4 prompt 不读 |
| 9 | derivatives_lsr_change_24h | long_short_ratio | 同上 |
| 12 | derivatives_top_long_short_ratio | long_short_ratio | 同上 |
| 27 | onchain_lth_mvrv | lth_mvrv | Layer A onchain_packet 不含;Layer B 不用 |
| 34 | onchain_ssr | ssr | Layer A inventory 有但 packet 不含;Layer B 不用 |
| 35 | onchain_sth_mvrv | sth_mvrv | 同 lth_mvrv |
| 41 | price_ma_120 | ma_120 | 无人消费 — 历史遗留 |
| 44 | price_ma_60 | ma_60 | 同上 |
| 45 | price_tf_alignment_4h_1d_1w | tf_alignment | Layer A inventory 有但 packet 不含;Layer B 不计算 |

> **注释**:这 9 个因子的**数据采集仍然要保留**(避免破坏 DB / collector),只是不在 UI 显示。

---

## 4. 缺失卡片补全清单

并集 **69 个 prompt 实际消费因子** - 当前 62 张活卡所对应的 raw 因子 = **19 个缺失因子**。但其中:
- `klines_1d_30d_close`(K 线 list)、`swing_5_recent`(swing 点 list)— 不适合做单卡,**走图表展示**
- `btc_price` vs `current_close` — 同一概念,**合并 1 卡**
- `extreme_event_flags`(5 bool dict)— 建议 1 个 summary 卡 或随 events 区合并

调整后,**实际可新建 15 张卡**:

| # | 因子 | 数据源 | 哪边在用 | 建议归类 | 建议标签 | 卡片说明文案(中文) |
|---:|---|---|---|---|---|---|
| 1 | btc_price / current_close | CoinGlass klines 1d | A + B | 价格技术 | `Layer A / B` | 当前 BTC 收盘价;Layer A 比 200w MA 看大周期,Layer B 用作止损 / 仓位计算 |
| 2 | ema_20_4h | K 线 4h 派生 | Layer B | 价格技术 | `Layer B` | 4h EMA-20,L2 多周期一致性判定的短端 |
| 3 | ema_50_4h | K 线 4h 派生 | Layer B | 价格技术 | `Layer B` | 4h EMA-50,L2 多周期一致性判定的中端 |
| 4 | ema_20_slope_30d | K 线 1d 派生 | Layer B | 价格技术 | `Layer B` | EMA-20 30 天斜率,趋势加速度 |
| 5 | ema_50_slope_30d | K 线 1d 派生 | Layer B | 价格技术 | `Layer B` | EMA-50 30 天斜率,中期趋势加速度 |
| 6 | atr_14_1d | K 线 1d 派生 | Layer B | 价格技术 | `Layer B` | ATR-14 绝对值,L4 计算止损距离 |
| 7 | price_position_in_90d_range | K 线 1d 派生 | Layer B | 价格技术 | `Layer B` | 价格在 90d 区间相对位置(0-100),L1 判贵贱 |
| 8 | max_drawdown_60d_pct | K 线 1d 派生 | Layer B | 价格技术 | `Layer B` | 60 天滚动峰值回撤,L4 仓位削减依据 |
| 9 | yield_curve_2_10_spread_bps | FRED 派生 | Layer B | 宏观 | `Layer B` | 2y-10y 利差 bps,衰退预警信号 |
| 10 | extreme_event_flags(summary) | 5 bool 聚合 | Layer B | 事件 | `Layer B` | 5 类极端事件(地缘冲突/银行危机/监管/闪崩/稳定币脱锚)是否激活 |
| 11 | weekly_structure | K 线 1w 派生 | Layer A | 价格技术 | `Layer A` | 周线 OHLC 结构(higher highs / lower lows 等),Layer A 大周期支撑 |
| 12 | lth_supply | Glassnode | Layer A | 链上 | `Layer A` | LTH 长期持有者绝对持仓量,Layer A 大周期估值核心 |
| 13 | sth_supply_90d_pct_change | Glassnode 派生 | Layer A | 链上 | `Layer A` | STH 90 天 % 变化,Layer A 区分 STH 接货 / 派发 |
| 14 | etf_flow_7d_sum_usd | CoinGlass 派生 | Layer A | 宏观 | `Layer A` | ETF 7 日累计净流(美元),Layer A 短期资金动量 |
| 15 | etf_flow_30d_sum_usd | CoinGlass 派生 | Layer A | 宏观 | `Layer A` | ETF 30 日累计净流(美元),Layer A 中期资金动量 |

> 注:已有 `derivatives_etf_flow` 卡(spec key=`etf_flow`)显示原始 etf_flow series。新增 7d/30d 累计是 Layer A 真正消费的派生值,建议**单独建卡**或**在原 etf_flow 卡上加 7d/30d 两个 sub-value**。

---

## 5. 修复后预期效果

### 5.1 卡片总数变化

| 当前 | 删除 | 新增 | 修复后 |
|---:|---:|---:|---:|
| 71 | -9 | +15 | **77** |

### 5.2 各组卡片数变化(估)

| 组 | 当前(含死卡) | 删除 | 新增 | 修复后 |
|---|---:|---:|---:|---:|
| 价格技术 | 14 | -3(ma_60/120/tf_alignment) | +8(EMA-4h + slope + ATR + drawdown + price_position + btc_price) | 19 |
| 链上数据 | 19 | -3(ssr/lth_mvrv/sth_mvrv) | +2(lth_supply + sth_supply_90d) | 18 |
| 衍生品 | 11 | -3(LSR×2 + liquidation) | 0 | 8 |
| 宏观 | 17 | 0 | +3(yield_curve + ETF 7d/30d) | 20 |
| 事件 | 5 | 0 | +1(extreme_event_flags summary) | 6 |
| 其他(weekly_structure) | 0 | 0 | +1 | 1 |
| 已删除死卡 | (9 隐藏) | — | — | — |
| **合计** | **71** | **-9** | **+15** | **77** |

### 5.3 修复后标签分布(预期)

| 标签 | 卡片数 | 占比 |
|---|---:|---:|
| `Layer A` | 31 | 40% |
| `Layer B` | 36 | 47% |
| `Layer A / B` | 10 | 13% |

### 5.4 用户视角改善

| 改善点 | 现状 | 修复后 |
|---|---|---|
| MVRV-Z 标"L2"误导 | 看上去 Layer B L2 在用 | `Layer A` — 正确反映只 Layer A 用 |
| sth_realized_price 标"L2"漏掉 Layer A | 看不出 Layer A 也用 | `Layer A / B` — 完整反映双方都用 |
| funding_rate 标"L4"过细 | 用户要记 L4 = Layer B | `Layer B` — 简化 |
| 死卡(LSR/liquidation/ssr/tf_alignment 等)还在 | 占空间误导用户 | 删除 — 用户视线清洁 |
| EMA / ATR / drawdown 等 Layer B 真用因子无卡 | 用户看不到 Layer B 实际依据 | 补 8 张 — 完整 |

---

## 6. 涉及的代码改动范围

### 6.1 后端 emitter:`src/strategy/factor_card_emitter.py`

| 改动类型 | 数量 | 详情 |
|---|---:|---|
| 改 `linked_layer` 字段 | 31 卡 | L1→Layer B / L2→Layer A 或 Layer A/B / L3→Layer A / L4→Layer B / L5→Layer A/B 等 |
| 删除 emit 函数段 | 9 卡 | LSR×2 / liquidation / oi 留(还有用)/ ssr / lth_mvrv / sth_mvrv / tf_alignment / ma_60 / ma_120 |
| 新增 emit 函数段 | 8 卡 | EMA-4h ×2 / EMA-slope ×2 / atr_14_1d / price_position_90d / max_drawdown_60d / btc_price |

**注**:events 5 卡(`event_*_next`)目前 linked_layer 是 `None`,代码层是 `linked_layer=None` — 需要补成 `linked_layer="Layer B"`。

### 6.2 前端 web specs:`web/assets/app.js layerAFactorCardSpecs()`(line 1429-1672)

| 改动类型 | 数量 | 详情 |
|---|---:|---|
| 改 linked_layer 标签渲染逻辑 | 全 26 spec | 4 个改 Layer A / B(fed_balance / m2 / us2y / 另1)+ 22 个保持 Layer A |
| 新增 spec | 7 张 | weekly_structure / lth_supply / sth_supply_90d_pct_change / etf_flow_7d / etf_flow_30d / yield_curve_2_10 / extreme_event_flags summary |

### 6.3 前端 web 渲染:`web/assets/app.js layerAFactorCards()` + `rawFactorCards()` + index.html

| 改动 | 详情 |
|---|---|
| 渲染 `linked_layer` 字段 | 当前 `linked_layer: 'Layer A'` 硬编码,需读 emitter / spec 各自字段;3 档显示(Layer A / Layer B / Layer A / B) |
| 增加"未使用"区域(可选) | 把死卡藏起来,或者直接在 emitter 不 emit |
| 调整 grid 布局 | 总卡数 71 → 77,可能影响行数 |

### 6.4 Layer A context(spot_cycle_context_builder.py)

**无改动**。Layer A "支持证据"区已完整(45/45 一致)。

### 6.5 测试同步

| 文件 | 改动 |
|---|---|
| `tests/test_factor_card_emitter.py` | by_tier breakdown 需更新(composite 5 不变;primary/reference 改变);assert linked_layer 标签 |
| `tests/test_web_modules_*.py` | rawFactorCards 计数从 71 → 77;factorGroups 各组计数 |
| 新增 `tests/test_factor_label_accuracy.py` | 对每个卡的 linked_layer 与 A/B consumed set 做集合断言 |

---

## 7. 估计工作量(commit 数粗算)

| Commit | 内容 | 估时 |
|---|---|---|
| 1 | factor_card_emitter.py:删 9 死卡 + 改 31 linked_layer | 1-2h |
| 2 | factor_card_emitter.py:新增 8 卡 emit 函数 | 2-3h |
| 3 | app.js layerAFactorCardSpecs:新增 7 spec + 改 4 标签渲染 | 1-2h |
| 4 | app.js / index.html:渲染 3 档 label(`Layer A` / `Layer B` / `Layer A / B`)+ grid 布局复查 | 1-2h |
| 5 | 测试同步 + 全量 pytest | 1h |
| 6 | sprint 报告 + commit + push + 部署 | 0.5h |
| **合计** | | **6-10h(1-2 天)** |

---

## 8. 风险 / 边界 case

### 8.1 卡片名字映射歧义 case

| 卡片 | 歧义 | 决策 |
|---|---|---|
| `price_ma_200` | Layer A 用 `ma_200d`(SMA);Layer B 用 `ema_200_1d`(EMA)— 不同算法,同 200 期 | 当前卡显示 SMA 还是 EMA?需 grep emitter 代码确认;若是 EMA → `Layer B`;若 SMA → `Layer A` |
| `derivatives_etf_flow` | 显示 etf_flow series;Layer A 用 `etf_flow_7d_sum_usd` + `etf_flow_30d_sum_usd`(派生);Layer B 用 etf_flow raw | 视为同源 → `Layer A / B`,文案加 sub-period 说明 |
| `events_*` 5 卡 | 都派生自 `events_calendar_72h`;不是独立因子 | 简化为 `Layer B`(系统级 events 集成在 L5);考虑合并 5 卡为 1 个事件 summary 卡 + 5 个二级展开 |
| btc_price vs current_close | Layer A 命名 `btc_price`,Layer B 命名 `current_close` | 视为同一 metric;统一 1 卡(建议名"BTC 当前收盘") |

### 8.2 "幽灵需求"(用户希望显示但后端没注入)

未发现。Layer A "支持证据"区显示的就是 prompt 实际消费;Layer B 我们已经精确盘点 32 个,所有可建卡的都列了。

### 8.3 标签简化为 A / B 后失去细分粒度的反悔风险

**潜在反悔点**:
- 用户未来可能想看"具体哪一层用"(L1 / L2 / L3 / L4 / L5)
- 如果之后开发需要 fine-grained 调试,失去 linked_layer 细分会更麻烦

**缓解方案**:
- Emitter 内部 metadata 保留细分 `consumed_by_layers: ["L2", "L4"]`(JSON 数组)
- UI 只渲染简化的 3 档 label
- 用户点击卡片"详情"展开时可见 `consumed_by_layers` 细节

**建议**:实施时**保留** emitter 内部细分 metadata,前端只显示简化版。这是低成本的双保险。

### 8.4 死卡数据采集硬纪律

**绝对不删**:
- glassnode collector 中 `lth_mvrv` / `sth_mvrv` / `ssr` / `liquidation_total` / `long_short_ratio` 的采集代码
- DB `derivatives_snapshots` / `onchain_metrics` 表中对应列
- Layer A `_FACTOR_SOURCE` 字典 / `available_factors` 注册表 

死卡只是**前端不显示**,数据采集 / 入库 / 注册全部保留(避免未来需要时数据已断)。

### 8.5 缺失字段补全的范围争议

部分用户可能觉得 EMA-20 1d 已经隐含在"price_ma_20"卡;加 4h / slope 是否过于细化?

**建议**:把这些标记为"⊕ 可选高级因子",默认折叠不显示,用户点击"展开高级"才显示。这样 UI 默认仍是 71-9=62 张活卡(用户视觉简洁),但完整 77 张可访问。

---

**报告完**。修复计划等用户审完,确认范围 / 决策后,开下个 sprint 执行。
