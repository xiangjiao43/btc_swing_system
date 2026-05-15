# Audit A1 Required And Unnecessary Data

## 1. 任务目标

本轮只读审计 Layer A A1「大周期阶段判断」当前真实输入、仍缺失的关键数据，以及是否混入不该由 A1 主判断使用的数据。

本轮没有改代码、没有改 prompt、没有改 Layer A / Layer B 逻辑、没有跑完整 pipeline、没有触碰真实交易。

## 2. 读取和核实方式

读取文件：

- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_cycle_stage_state.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/spot_validator.py`
- `src/ai/orchestrator.py`
- `src/pipeline/layer_a_spot_runner.py`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/fred.py`
- `src/data/collectors/coinglass.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `tests/test_layer_a_spot_context_builder.py`
- 相关历史报告

只读查询摘要：

- 查询文件：`/private/tmp/audit_layer_a_a1_required_and_unnecessary_data/readonly_a1_required_unnecessary_summary.json`
- 本地 DB：`data/btc_strategy.db`
- 最新本地 Layer A run：
  - `run_id`: `b8dbdea5945245a2827f90dabfc2dded`
  - `generated_at_bjt`: `2026-05-15 13:43:34 BJT`
  - A1 raw / official：`accumulation`
  - A1 confidence：`low`
  - A5 action：`hold`
  - validator：passed

注意：该最新本地 run 生成于 `0357626 Sync Layer A P0 factors to raw factor cards` 之前，因此它的 snapshot 仍显示 `monthly_structure_1m` / `major_support_resistance` 为未接入。当前代码已经补了 `monthly_ohlc_structure`、`major_support_resistance_zones`、`hodl_waves_1y_plus_aggregate`，但需要下一次 Layer A run 才会进入最新 run snapshot。

## 3. A1 当前真实输入链路

| 环节 | 代码证据 | 说明 |
|---|---|---|
| Layer A 独立入口 | `src/pipeline/layer_a_spot_runner.py::LayerASpotStrategyRunner.run` | 只构建 Layer A context，调用 `AIOrchestrator().run_layer_a_spot_only(context)`，不跑 Layer B L1-L5 / Master。 |
| Layer A context 构建 | `src/ai/spot_cycle_context_builder.py::SpotCycleContextBuilder.build_spot_cycle_context` | 读取 K 线、onchain、macro、derivatives 和事件，但按 `available_factors` 分组。 |
| A1 专用轻量 context | `src/ai/spot_cycle_context_builder.py::build_a1_cycle_stage_context` | A1 不拿完整 `spot_cycle_context`，只拿 `stage_model`、`cycle_evidence_summary`、`recent_stage_history`、`instructions`。 |
| A1 prompt 注入 | `src/ai/agents/spot_cycle_agents.py::A1SpotCycleAnalyst._build_user_prompt` | 调用 `build_a1_cycle_stage_context(context)` 后 compact JSON 传给 AI。 |
| A1 prompt 规则 | `src/ai/agents/prompts/a1_spot_cycle.txt` | 明确七阶段、优先看价格周期/估值/持有人结构/长期资金流，禁止把 funding/OI/liquidation/long-short 当阶段驱动。 |
| A1 输出归一 | `src/ai/spot_strategy_normalizer.py::normalize_a1` | 将 AI 输出映射到七阶段，并交给状态机确认 official stage。 |
| 阶段状态机 | `src/ai/spot_cycle_stage_state.py::evaluate_stage_transition` | 根据 previous official stage、factor coverage、risk、validator 做 pending / confirmed / recalibration。 |

## 4. A1 当前真实输入字段摘要

最近 run 的 A1 lightweight context top-level keys：

- `stage_model`
- `cycle_evidence_summary`
- `recent_stage_history`
- `instructions`

`cycle_evidence_summary` 分组：

| 分组 | 当前 A1 字段 |
|---|---|
| `price_position` | `btc_price`, `ath_drawdown_pct`, `ma_200d`, `ma_200w`, `weekly_structure`, `monthly_ohlc_structure`, `major_support_resistance_zones`, `realized_price`, `sth_realized_price`, `lth_realized_price` |
| `valuation` | `mvrv_z_score`, `mvrv`, `nupl`, `rhodl_ratio`, `reserve_risk`, `puell_multiple`, `percent_supply_in_profit` |
| `holder_behavior` | `lth_sopr`, `sth_sopr`, `lth_supply`, `sth_supply`, `lth_supply_90d_pct_change`, `sth_supply_90d_pct_change`, `lth_net_position_change`, `percent_supply_in_profit`, `percent_supply_in_loss`, `hodl_waves_1y_plus_aggregate`, `cdd` |
| `flows` | `exchange_balance`, `exchange_net_position_change`, `exchange_net_flow_30d_sum`, `etf_flow_7d_sum_usd`, `etf_flow_30d_sum_usd` |
| `macro` | `real_yield`, `fed_funds_rate`, `us2y`, `dxy`, `vix`, `nasdaq`, `m2`, `fed_balance_sheet`, `cpi`, `core_cpi` |
| `data_quality` | `confidence_cap`, `confidence_cap_reason`, `critical_unavailable_count`, `stale_factor_count`, `missing_integrated_factor_count`, `coverage_ratio`, `coverage_notes`, `data_quality_notes`, `unavailable_factors` |

字段来源：

- 原始采集数据：CoinGlass K 线、Glassnode 链上、FRED 宏观、CoinGlass ETF / 衍生数据。
- 规则计算 / 派生：ATH drawdown、200D/200W、weekly structure、月线结构、长期支撑阻力、HODL Waves 1Y+ 聚合、exchange net position change、percent supply in loss、BTC-Nasdaq correlation、factor coverage。
- 历史 Layer A：`previous_layer_a_state` 被压缩为 `recent_stage_history` 和 `previous_official_stage`。
- 网页展示但不进入 A1：`rawFactorCards()` 生成的 plain_reading、状态行、抓取时间显示、原始因子卡片 UI 字段。

## 5. 已确认进入 A1 的核心数据类别

已进入 A1 主判断的类别：

- 高周期价格结构：日线价格、周线结构、ATH drawdown、200D、200W、月线结构、长期支撑/阻力区。
- 链上估值：MVRV、MVRV Z、NUPL、RHODL、Reserve Risk、Puell、profit supply。
- 长期持有人结构：LTH/STH SOPR、LTH/STH supply、LTH net position change、profit/loss supply、HODL Waves 1Y+、CDD。
- 交易所/资金流：exchange balance、exchange net position change、exchange net flow 30d、ETF 7d/30d。
- 宏观/流动性背景：real yield、Fed funds、US2Y、DXY、VIX、Nasdaq、M2、Fed balance sheet、CPI/Core CPI。
- 数据质量：coverage、stale、missing、confidence cap、unavailable factors。

重要说明：进入 A1 不等于最近 run 一定有值。最新本地 snapshot 中不少字段因为本地 DB 旧或生成早于新代码，显示 missing / stale；这属于数据新鲜度和 run 版本问题，不等于字段没有接入。

## 6. 进入 Layer A context 但没有进入 A1 的字段

这些字段在 `spot_cycle_context.available_factors` 中存在，但 A1 lightweight context 没有使用，或只被压缩后保留极少摘要：

| 字段 / 分组 | 当前位置 | 是否进 A1 | 说明 |
|---|---|---:|---|
| `market_context.funding_rate` | Layer A context | 否 | 短线衍生品，适合 Layer B / A4，不适合作为 A1 阶段驱动。 |
| `market_context.open_interest` | Layer A context | 否 | 同上。 |
| `market_context.long_short_ratio` | Layer A context | 否 | 同上。 |
| `market_context.liquidation_total` | Layer A context | 否 | 同上。 |
| `event_risk.events` | Layer A context | 否 | A1 只判断周期阶段，事件更多影响 A4 风险或 A5 执行谨慎度。 |
| `factor_role_classification` | Layer A context | 否 | 审计/报告用，不应进入 A1 prompt。 |
| `series_samples` | Layer A context | 否 | 调试/样本用，不进入 A1，避免 prompt 变重。 |

## 7. 进入 A2/A4/A5 但不该作为 A1 主驱动的数据

- A2/A4/A5 可以读取完整 `spot_cycle_context`，因此能看到更完整的宏观、资金流、风险背景。
- A1 prompt 已明确：宏观只作置信度和反方证据；短线衍生品不能作为阶段驱动。
- 这对交易系统意味着：A1 判断“周期处在哪”，A5 才根据 A1 + A2/A3/A4 决定“现货策略怎么做”。

## 8. 仍缺失或不完整，且值得补的数据清单

以下只列「缺失或不完整，且确实值得补」的数据；不重复列已经正常进入 A1 的数据，也不列短线 Layer B 因子。

| data_name | 中文名 | 为什么 A1 需要 | 当前状态 | 推荐数据源 | 可能 endpoint / series | 难度 | 优先级 | 是否必须补齐后才能提高 A1 可信度 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| `cycle_anchors_halving_phase` | 周期锚点 / 减半阶段 | A1 需要知道现在距上一轮 ATH、周期低点、减半时间多远，避免把短期修复误读成牛市中期。 | not_configured | 本地规则化计算 | 从历史 K 线推导 previous cycle ATH / cycle low；减半日期可配置静态表 | low-medium | P0 | yes | 对区分底部吸筹、牛熊过渡、牛市初段非常关键。 |
| `stablecoin_liquidity_proxy` | 稳定币流动性代理 | 大周期牛初/中期通常需要风险资金弹药，稳定币总供给和交易所稳定币余额可辅助确认流动性。 | source_unavailable | Glassnode / DeFiLlama / CoinMetrics，需验证 | stablecoin total supply、USDT/USDC supply trend、stablecoin exchange balance | medium-high | P0 | yes | 当前 `_UNAVAILABLE_MODEL_FACTORS` 仍有 `stablecoin_supply_liquidity: not_found`。 |
| `net_liquidity_tga_rrp` | 美元净流动性 | 仅有 Fed balance sheet / M2 不够，净流动性需要扣 TGA 和 RRP，更贴近风险资产流动性背景。 | not_configured | FRED | WALCL - TGA - RRP；RRP 常见 `RRPONTSYD`，TGA 需确认 FRED series | medium | P0 | yes | 最可能影响 A1 对“牛市中期是否成立”的宏观确认。 |
| `cdd_long_term_zscore` | CDD 长周期均值 / Z-score | 单点 CDD 噪音大，长周期均值或 Z-score 更能判断老币移动与派发。 | configured_but_not_collected / in_a1_but_missing | Glassnode + 本地派生 | `/v1/metrics/indicators/cdd` 后做 90d/180d 均值或 Z-score | medium | P1 | no | A1 已有 `cdd` 字段，但最新 snapshot 缺值，且没有长周期平滑版本。 |
| `liveliness_or_dormancy` | Liveliness / Dormancy | 判断长期持有人从囤币转向分发，尤其有助于区分牛市中期、后期、顶部过热。 | configured_but_not_collected | Glassnode | `/v1/metrics/indicators/liveliness`；Dormancy endpoint 需验证 | medium | P1 | no | `data_catalog.yaml` 有 liveliness，但 context 仍标记 `config_only`。 |
| `realized_cap_hodl_waves` | Realized Cap HODL Waves | 比普通 HODL Waves 更强调币龄筹码的价值权重，适合判断顶部/底部温度。 | source_unavailable | Glassnode，需验证套餐/中转 | `/v1/metrics/indicators/realized_cap_hodl_waves` 或相近 endpoint | high | P2 | no | 价值高，但接口与套餐不确定，不适合先做 P0。 |
| `sopr_long_term_ma` | SOPR 长周期均值 | LTH/STH SOPR 单点可能受日内噪音影响，长周期均值更适合 A1。 | collected_but_not_in_a1 | Glassnode + 本地派生 | lth_sopr / sth_sopr 的 30d/90d MA | low-medium | P2 | no | 当前 A1 有 LTH/STH SOPR 单点，缺平滑确认。 |

## 9. 不该进入 A1 主判断的数据清单

| field_name | 当前是否进入 A1 | 为什么不适合 A1 | 建议 |
|---|---:|---|---|
| `funding_rate` | 否 | 8h/短周期拥挤指标，容易造成阶段误判。 | keep_in_layer_b / move_to_a4 |
| `open_interest` | 否 | 杠杆和拥挤度指标，更适合波段风险。 | keep_in_layer_b / move_to_a4 |
| `liquidation_total` | 否 | 短线清算压力，不代表大周期阶段。 | keep_in_layer_b |
| `long_short_ratio` | 否 | 短线情绪和杠杆方向，不应驱动 A1。 | keep_in_layer_b |
| `futures_basis_premium` | 否 | 当前未稳定接入且偏衍生品结构，不适合作 A1 主驱动。 | no_action / keep_in_layer_b |
| `options_iv_skew` | 否 | 更偏风险/情绪，不应决定周期阶段。 | move_to_a4 |
| `24h derivatives changes` | 否 | 高频变化，噪音高。 | keep_in_layer_b |
| `20D short-term momentum` | 否 | 太短，容易把反弹当周期切换。 | keep_in_layer_b |
| `Layer B L1-L5 full context` | 否 | 会污染 Layer A/B 边界。 | no_action |
| `active thesis / current thesis` | 否 | thesis 是 Layer B 交易主线，不属于现货大周期阶段输入。 | no_action |
| `virtual_account` | 否 | 虚拟账户只管理 Layer B，不参与 A1。 | no_action |
| `positions / pending_orders` | 否 | 挂单和持仓是执行层，不是周期判断输入。 | no_action |
| `web factor card plain_reading` | 否 | 网页人读说明是展示层，不应反喂给 AI。 | no_action |
| `full_state_json` | 否 | 大对象会增加 prompt 体积并混入无关上下文。 | no_action |
| `debug fields / series_samples` | 否 | 调试与样本序列不应进入 A1 prompt。 | no_action |

结论：当前 A1 lightweight context 没有明显混入这些不该进入 A1 的数据。短线衍生品仍在完整 Layer A context 的 `market_context` 中，但没有进入 A1 lightweight context。

## 10. 当前 A1 数据是否足够

### 10.1 是否足够做大周期阶段参考判断

可以。

当前 A1 已经具备价格周期、链上估值、持有人结构、交易所/ETF 流、宏观背景、数据质量、历史阶段状态这些核心框架。它可以作为“大周期阶段参考判断”。

### 10.2 是否足够作为辅助实际交易的高可信阶段判断

还不够。

原因不是 A1 框架不对，而是仍缺少三类对大周期确认很关键的数据：

1. 周期锚点 / 减半阶段。
2. 稳定币流动性。
3. Fed net liquidity（TGA / RRP）。

此外，CDD、liveliness/dormancy、SOPR MA 这类“老币移动/派发”指标还不够稳定，容易让 A1 对牛市中期/后期的判断缺少长期筹码确认。

### 10.3 当前更适合输出什么

当前 A1 更适合输出：

- 过渡判断
- 中低置信度判断
- 辅助参考分析

不适合单独作为强交易结论。最终策略仍应由 A5 综合 A1 + A2/A3/A4 + validator 给出。

## 11. 哪些缺口可能导致“牛市中期”偏乐观

最可能导致 A1 过早判断为 `mid_bull` 的缺口：

1. 缺周期锚点 / 减半阶段：不知道这轮周期时间位置，容易把价格修复误读成周期成熟。
2. 缺 stablecoin liquidity：无法确认场外资金弹药是否支持牛市中期。
3. 缺 net liquidity：Fed balance sheet 单独看不够，扣除 TGA/RRP 后的净流动性更关键。
4. 缺 CDD / liveliness / dormancy 的长周期平滑：无法稳健判断老币是否开始派发。

## 12. 最终优先级建议

### P0 必须补，最多 3 个

1. `cycle_anchors_halving_phase`
2. `stablecoin_liquidity_proxy`
3. `net_liquidity_tga_rrp`

### P1 建议补，最多 5 个

1. `cdd_long_term_zscore`
2. `liveliness_or_dormancy`
3. `sopr_long_term_ma`

### P2 可选观察，最多 5 个

1. `realized_cap_hodl_waves`

### 不建议进入 A1，最多 10 个

1. funding rate
2. open interest
3. liquidation
4. long/short ratio
5. futures basis / premium
6. options IV / skew
7. 24h derivatives changes
8. 20D short-term momentum
9. current thesis
10. virtual account / pending orders

## 13. 下一步建议

下一步不要继续加一堆因子。建议按顺序做：

1. 先补 `cycle_anchors_halving_phase`，这是最低风险的本地规则化派生，不依赖新 API。
2. 再验证稳定币流动性数据源，确认是否走 Glassnode、DeFiLlama、CoinMetrics 或其它稳定来源。
3. 再补 FRED 的 TGA/RRP，并计算 net liquidity。
4. 最后再考虑 CDD Z-score、liveliness/dormancy、SOPR MA。

## 14. 是否改代码 / 是否影响系统

- 是否改代码：否
- 是否改 prompt：否
- 是否影响 Layer A 逻辑：否
- 是否影响 Layer B：否
- 是否影响虚拟账户：否
- 是否影响真实交易：否

## 15. 测试 / 检查

本轮只写报告，pytest 不适用。

已运行：

```bash
git diff --check
```

## 16. 删除清单 / 废弃清单

本轮无替代关系，无删除项。

## 17. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A，本轮只读报告 |
| GitHub push | 待提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | N/A |

## 18. 用户后续命令

本轮是报告，不需要部署、不需要重启、不需要跑 pipeline。

