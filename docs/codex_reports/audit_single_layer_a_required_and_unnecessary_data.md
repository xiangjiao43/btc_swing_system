# Audit Single Layer A Required And Unnecessary Data

## 1. 任务目标

本轮只做只读审计：在 Layer A 已重构为“单一大周期裁决”的前提下，核实当前 Layer A AI 实际看了哪些数据、哪些关键数据仍缺失或不可用、哪些短线/执行类数据不应混入 Layer A。

本轮没有改代码、没有改 prompt、没有改 Layer A / Layer B 策略逻辑、没有跑完整 pipeline、没有触碰真实交易。

## 2. 读取过的关键文件

- `AGENTS.md`
- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `src/ai/agents/prompts/layer_a_cycle_adjudicator.txt`
- `src/ai/agents/spot_cycle_agents.py`
- `src/ai/orchestrator.py`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_cycle_stage_state.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/spot_validator.py`
- `src/pipeline/layer_a_spot_runner.py`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/fred.py`
- `src/data/collectors/coinglass.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `web/assets/app.js`
- `docs/codex_reports/refactor_layer_a_to_single_cycle_adjudicator.md`
- `docs/codex_reports/audit_layer_a_a1_required_and_unnecessary_data.md`
- `docs/codex_reports/implement_layer_a_a1_p0_data_and_prune_unnecessary_inputs.md`

## 3. 当前 Layer A 单层裁决输入链路

当前正式链路是：

`build_spot_cycle_context()` → `build_layer_a_cycle_adjudicator_context()` → `LayerACycleAdjudicator` → `normalize_layer_a_output()` → validator / state machine / persist。

代码证据：

| 证据 | 位置 | 说明 |
|---|---|---|
| 单一裁决 agent | `src/ai/agents/spot_cycle_agents.py:140` | `LayerACycleAdjudicator` 是当前 Layer A 唯一 AI 大周期裁决员。 |
| 单一裁决 prompt | `src/ai/agents/prompts/layer_a_cycle_adjudicator.txt:9` | prompt 明确输入为四个 deterministic 数据包和历史阶段摘要。 |
| runner 调用 | `src/ai/orchestrator.py:438` | Layer A runner 构造 `build_layer_a_cycle_adjudicator_context()` 并只调用 `layer_a_cycle`。 |
| 四数据包生成 | `src/ai/spot_cycle_context_builder.py:610` | `build_layer_a_cycle_adjudicator_context()` 生成正式 AI 输入。 |
| 排除 Layer B/交易执行 | `src/ai/spot_cycle_context_builder.py:613` | 注释明确排除 Layer B L1-L5、thesis、虚拟账户、持仓、挂单、raw factor cards、full debug JSON。 |
| legacy 兼容字段 | `src/ai/spot_strategy_normalizer.py:447` | 仍会映射出 `a1/a2/a3/a4/a5` 兼容字段，但它们不是当前业务架构。 |

最近一次本地 Layer A 结果只读摘要：

| 字段 | 值 |
|---|---|
| run_id | `2e9ae25e6e124121999f45711b5a4c65` |
| generated_at_bjt | `2026-05-15 15:42:21 BJT` |
| architecture | `single_cycle_adjudicator` |
| ai_call_count | `1` |
| legacy_a1_a5_flow | `false` |
| official_stage | `accumulation` |
| raw_stage | `accumulation` |
| spot_action | `hold` |
| validator_passed | `true` |

## 4. 四个数据包当前真实字段

### technical_packet 技术指标数据包

进入 AI 的字段：

- `btc_price`
- `ath_drawdown_pct`
- `ma_200d`
- `ma_200w`
- `weekly_structure`
- `monthly_ohlc_structure`
- `major_support_resistance_zones`
- `realized_price`
- `sth_realized_price`
- `lth_realized_price`

最新快照状态：

- 数据包状态：`partial`
- 可用：`monthly_ohlc_structure`、`major_support_resistance_zones`
- 过期或缺值：`btc_price`、`ath_drawdown_pct`、`ma_200d`、`ma_200w`、`realized_price`、`sth_realized_price`、`lth_realized_price`

### onchain_packet 链上数据包

进入 AI 的字段：

- `mvrv`
- `mvrv_z_score`
- `nupl`
- `rhodl_ratio`
- `reserve_risk`
- `puell_multiple`
- `lth_sopr`
- `sth_sopr`
- `lth_supply`
- `sth_supply`
- `lth_supply_90d_pct_change`
- `sth_supply_90d_pct_change`
- `lth_net_position_change`
- `percent_supply_in_profit`
- `percent_supply_in_loss`
- `hodl_waves_1y_plus_aggregate`
- `cdd`
- `exchange_balance`
- `exchange_net_position_change`

最新快照状态：

- 数据包状态：`partial`
- 可用：`reserve_risk`、`puell_multiple`
- 过期或缺值：多数持有人行为、利润/亏损供给、交易所余额、RHODL、MVRV/NUPL、CDD、HODL Waves 1Y+

### liquidity_macro_packet 流动性 / 宏观背景数据包

进入 AI 的字段：

- `etf_flow_7d_sum_usd`
- `etf_flow_30d_sum_usd`
- `exchange_net_flow_30d_sum`
- `real_yield`
- `fed_funds_rate`
- `us2y`
- `dxy`
- `vix`
- `nasdaq`
- `m2`
- `fed_balance_sheet`
- `cpi`
- `core_cpi`

最新快照状态：

- 数据包状态：`partial`
- `exchange_net_flow_30d_sum` 为过期状态
- 其余宏观/流动性字段在最新本地快照中缺值

### risk_packet 风险评估数据包

进入 AI 的字段：

- `confidence_cap`
- `confidence_cap_reason`
- `critical_unavailable_count`
- `stale_factor_count`
- `missing_integrated_factor_count`
- `coverage_ratio`
- `unavailable_factors`
- `near_long_term_resistance`
- `etf_flow_7d_sum_usd`
- `real_yield`
- `fed_funds_rate`

最新快照状态：

- 数据包状态：`partial`
- `confidence_cap = low`
- `confidence_cap_reason = Layer A 已接入因子可用率低于 50%`
- `missing_integrated_factor_count = 44`
- `stale_factor_count = 19`
- `critical_unavailable_count = 0`
- `coverage_ratio = 0.0597`

## 5. 已确认进入 AI 裁决的核心数据类别

当前单层 Layer A AI 已经能看到这几类核心摘要：

| 类别 | 是否进入 AI | 说明 |
|---|---:|---|
| 高周期价格结构 | 是 | 价格、ATH 回撤、200D/200W、周线/月线结构、长期支撑阻力、realized price 相关。 |
| 链上估值 | 是 | MVRV、MVRV Z、NUPL、RHODL、Reserve Risk、Puell。 |
| 持有人结构 | 是 | LTH/STH SOPR、LTH/STH supply、LTH net position、HODL 1Y+、profit/loss、CDD。 |
| 筹码流向 | 是 | exchange balance、exchange net position change、exchange net flow 30d。 |
| 宏观流动性背景 | 是 | ETF 7d/30d、M2、Fed balance sheet、Fed funds、US2Y、real yield、DXY、VIX、NASDAQ、CPI/Core CPI。 |
| 数据质量与风险 | 是 | missing/stale/source health/confidence cap/阻力区/宏观压力。 |

注意：这些字段“设计上已进入 AI”，但最新本地 run 里很多字段实际是 `missing` 或 `stale`。这意味着当前问题不是“结构完全没有”，而是“关键数据当前没有新鲜有效值”叠加“少数关键宏观/流动性补充因子仍未配置”。

## 6. 仍缺失且值得补的数据清单

只列当前单层 Layer A 仍缺失、不完整、或虽已设计进入但最新 run 不可用，且对大周期裁决有实际价值的数据。

| data_name | 中文名 | 所属数据包 | 为什么必须 | 当前状态 | 推荐数据源 / 派生方式 | 接入难度 | 优先级 | 必须补齐后才能提高可信度 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| `realized_price_bundle` | Realized Price / STH RP / LTH RP 成本线组 | technical_packet | 判断价格是否真正脱离熊市成本区、是否站稳短期/长期持有人成本线，是区分底部吸筹、牛熊过渡、牛市初段的重要锚点。 | `in_layer_a_but_stale` / `missing` | Glassnode realized price、STH/LTH realized price，或已有 collector 恢复 freshness | medium | P0 | yes | 字段已在 AI 包里，但最新 run 中 `realized_price` 过期，`sth_realized_price` / `lth_realized_price` 缺值。 |
| `holder_behavior_recovery_set` | 长期/短期持有人行为组 | onchain_packet | LTH/STH SOPR、LTH net position、profit/loss、HODL 1Y+ 直接决定是吸筹、派发还是趋势持有。缺失会让阶段更依赖少数估值指标。 | `in_layer_a_but_stale` / `missing` | Glassnode SOPR、LTH/STH supply、HODL waves、supply profit/loss、CDD | medium | P0 | yes | 字段设计已进入 AI，但最新 run 多数缺值，当前不能支撑高可信阶段结论。 |
| `core_macro_liquidity_values` | 核心宏观流动性当前值 | liquidity_macro_packet | M2、Fed balance sheet、US2Y、Fed funds、real yield、CPI/Core CPI 用于判断外部环境是顺风还是逆风；缺失会让“牛市中期”偏乐观。 | `in_layer_a_but_stale` / `missing` | FRED 已有 series 与 freshness 规则，优先修复最新值入包 | low/medium | P0 | yes | 字段已进入 AI，但最新 run 中大多缺值。先修复数据可用性，再考虑新增更多宏观因子。 |
| `stablecoin_liquidity_proxy` | 稳定币流动性代理 | liquidity_macro_packet | 稳定币供应/交易所余额是加密市场原生流动性，比单看 M2 或 Fed balance sheet 更贴近 BTC 风险偏好。 | `source_unavailable` / `not_configured` | DeFiLlama stablecoins、Glassnode stablecoin supply、CoinMetrics，需先验证接口和许可 | medium | P1 | no | 当前 `_UNAVAILABLE_MODEL_FACTORS` 中有 `stablecoin_supply_liquidity: not_found`。 |
| `net_liquidity_tga_rrp` | 美元净流动性 TGA/RRP | liquidity_macro_packet | Fed balance sheet 单独看不够，净流动性通常需要扣 TGA / RRP，能更准确判断美元流动性环境。 | `not_configured` | FRED RRP / TGA series，需验证准确 series；net liquidity 由规则派生 | medium | P1 | no | 是对已有 Fed balance sheet 的增强，不应单独驱动阶段。 |
| `cycle_anchor_halving_phase` | 周期锚点 / 减半阶段 | technical_packet | 给阶段判断一个低频时间锚，避免仅凭截面指标过早判断牛市中期。 | `not_configured` | 静态 halving 日期 + 历史 cycle high/low + K 线派生 | low/medium | P1 | no | `config/event_calendar.yaml` 有 halving 事件配置，但当前 Layer A packet 没有显式 days-after-halving / cycle-age 字段。 |
| `sopr_long_term_ma` | SOPR 长周期均线 | onchain_packet | 原始 SOPR 容易日内/短期噪音，长周期均线更适合判断持有人行为 regime。 | `collected_but_not_in_layer_a_ai` | 从 LTH/STH SOPR 历史派生 30D/90D 均线 | low/medium | P1 | no | 不是新外部数据，适合规则化派生。 |
| `cdd_long_term_zscore` | CDD 长周期 Z-score | onchain_packet | CDD 原值不如长周期 z-score 对派发/老币移动更稳。 | `collected_but_not_in_layer_a_ai` / `insufficient_history` | 从 CDD 历史派生 90D/365D 均值或 z-score | medium | P1 | no | 当前 packet 有 `cdd`，但缺少长周期平滑/异常度摘要。 |
| `dormancy_or_liveliness` | Dormancy / Liveliness 老币活跃度 | onchain_packet | 用于补充 CDD 与 HODL waves，判断老币是否开始移动、派发风险是否上升。 | `configured_but_not_collected` / `config_only` | Glassnode liveliness / dormancy，需验证接口与套餐 | medium | P2 | no | 当前 `liveliness` 标记为 `config_only`。 |
| `global_liquidity_proxy` | 全球流动性代理 | liquidity_macro_packet | 可补充美国单一流动性视角，但不是当前 P0。 | `not_configured` | 多区域 M2 或第三方 global liquidity proxy，需评估稳定性 | high | P2 | no | 接入复杂，先不作为阻塞项。 |
| `hodl_waves_long_bucket_detail` | HODL Waves 长期桶明细 | onchain_packet | 当前已有 1Y+ 聚合，细分 1-2Y、2-3Y、3-5Y 可帮助识别筹码成熟度。 | `collected_but_not_in_layer_a_ai` | 已有 Glassnode HODL waves 桶数据，规则摘要即可 | low | P2 | no | 避免把完整数组塞给 AI，只给摘要。 |

## 7. 不该进入 Layer A 裁决的数据清单

审计结果：当前单层裁决输入没有发现 Layer B 完整分析、thesis、虚拟账户、持仓/挂单、网页 factor card 文案或 full_state_json 大对象进入 AI。短线衍生品数据存在于项目和 Layer B context 中，但没有进入单层 Layer A AI 的四数据包。

| field_name | 当前是否进入 Layer A AI 裁决 | 为什么不适合 | 建议 |
|---|---:|---|---|
| `funding_rate` | 否 | 资金费率是短线拥挤/情绪指标，适合波段风险，不适合作为大周期阶段主驱动。 | `keep_in_layer_b` |
| `open_interest` | 否 | OI 反映杠杆拥挤，噪音高，容易误导大周期判断。 | `keep_in_layer_b` |
| `liquidation_total` | 否 | 清算是短期事件/波动结果，不适合判断长期阶段。 | `keep_in_layer_b` |
| `long_short_ratio` | 否 | 多空比偏交易情绪，适合 Layer B 或风险提示。 | `keep_in_layer_b` |
| `futures_basis_premium` | 否 | 当前已是 deprecated / unavailable；且更适合短中期拥挤判断。 | `no_action` |
| `options_iv_skew` | 否 | 当前 `not_found`；即使接入也更适合风险包或 Layer B，不应驱动阶段。 | `keep_in_risk_packet_summary` |
| `24h derivatives changes` | 否 | 时间尺度太短，会污染大周期阶段。 | `keep_in_layer_b` |
| `20D short-term momentum` | 否 | 可作为背景，但不能决定大周期阶段。 | `keep_in_layer_b` |
| `Layer B L1-L5 完整分析` | 否 | Layer A 与 Layer B 必须独立，不能让波段裁决反向影响现货大周期阶段。 | `no_action` |
| `current thesis` | 否 | thesis 是 Layer B 执行主线，不属于现货大周期裁决。 | `no_action` |
| `virtual_account` | 否 | 虚拟账户是 Layer B 执行表现，不应影响 Layer A 阶段。 | `no_action` |
| `holdings / orders` | 否 | 持仓/挂单属于执行层，不应输入 Layer A。 | `no_action` |
| `web factor card plain_reading` | 否 | 人读文案用于网页审计，不能作为 AI 输入。 | `keep_web_only` |
| `full_state_json` | 否 | 大对象会增加 token 和噪音，当前没有进入单层裁决。 | `no_action` |
| `debug fields / raw arrays` | 否 | 调试字段和完整数组不适合 AI 裁决。 | `no_action` |

需要注意的边界项：

- `ETF 7d/30d flow` 当前进入 `liquidity_macro_packet`，可以保留，但只能作为背景或反方证据，不能单独驱动阶段。
- `exchange_net_flow_30d_sum` 当前进入宏观/流动性包，合理，但最新值过期。
- `DXY/VIX/NASDAQ/CPI/Core CPI` 当前进入宏观包，合理，但只应影响置信度和背景，不应单独决定阶段。

## 8. P0 / P1 / P2 优先级

### P0 必须优先处理，最多 3 个

1. 恢复 `realized_price_bundle`：realized price、STH realized price、LTH realized price。
2. 恢复 `holder_behavior_recovery_set`：LTH/STH SOPR、LTH net position、profit/loss、HODL 1Y+、CDD、exchange balance。
3. 恢复 `core_macro_liquidity_values`：M2、Fed balance sheet、Fed funds、US2Y、real yield、CPI/Core CPI。

这三项不是都要新增接口，很多字段已经在代码里，但最新 run 缺值或过期。对用户来说，这意味着现在 Layer A 的“模型框架”已经搭好，但最新数据新鲜度还没跟上，不能当作高置信交易依据。

### P1 建议补，最多 5 个

1. `stablecoin_liquidity_proxy`
2. `net_liquidity_tga_rrp`
3. `cycle_anchor_halving_phase`
4. `sopr_long_term_ma`
5. `cdd_long_term_zscore`

### P2 可选观察，最多 5 个

1. `dormancy_or_liveliness`
2. `global_liquidity_proxy`
3. `hodl_waves_long_bucket_detail`
4. `realized_cap_hodl_waves`
5. `stablecoin_exchange_balance`

### 不建议进入 Layer A 主裁决，最多 10 个

1. funding rate
2. open interest
3. liquidation
4. long/short ratio
5. futures basis
6. options IV / skew
7. 24h derivatives changes
8. 20D short-term momentum
9. 当前 thesis
10. 虚拟账户 / 持仓 / 挂单

## 9. 当前 Layer A 数据是否足够

结论：

1. 当前 Layer A 单层裁决已经具备正确的数据包结构，适合做“大周期参考判断”。
2. 当前最新 run 的数据覆盖不足，不足以作为“高可信实际交易辅助”。
3. 最大问题不是 AI 架构，而是最新输入快照中大量核心字段 `missing/stale`，导致 `confidence_cap=low`。
4. 当前最核心缺口是：
   - 成本线组缺失或过期；
   - 持有人行为组缺失；
   - 宏观流动性当前值缺失；
   - crypto-native 稳定币流动性缺失。
5. 最可能导致阶段偏乐观、误判牛市中期的缺口：
   - 缺少 fresh 的 STH/LTH realized price 成本线；
   - 缺少 fresh 的 LTH/STH SOPR、profit/loss、HODL 1Y+；
   - 缺少 stablecoin liquidity / net liquidity 对流动性确认；
   - 缺少 cycle anchor / halving phase 这样的低频时间锚。
6. 当前更适合输出：`低置信度参考分析 / 过渡判断`，不适合输出强结论。

## 10. 下一步建议

建议下一轮不要先改 AI prompt，而是先做数据侧修复：

1. 先排查为什么最新 run 中大量已接入字段是 `missing/stale`，尤其是 Glassnode/FRED 关键字段。
2. 恢复 P0 三类数据的新鲜有效值，再重新跑 Layer A。
3. 再补 P1 的 stablecoin liquidity、net liquidity、cycle anchor / halving phase。
4. 保持当前四数据包 + 单一 AI 裁决架构，不要回到多 AI 分层。
5. 不要把 Layer B 短线衍生品和虚拟账户执行数据塞进 Layer A。

## 11. 实际运行命令和结果

| 命令 | 结果 |
|---|---|
| `git status --short` | 发现遗留 `uv.lock` 修改，本轮未触碰、未提交。 |
| `rg ... config src/data src/ai/spot_cycle_context_builder.py` | 用于核实 stablecoin、TGA/RRP、halving、liveliness、衍生品等配置/代码状态。 |
| `uv run python - <<'PY' ...` | 只读查询本地 SQLite 最新 Layer A 结果，生成 `/private/tmp/audit_single_layer_a_required_and_unnecessary_data/readonly_summary.json`。 |
| `git diff --check` | 待提交前执行。 |

本轮仅新增审计报告，pytest 不适用。

## 12. 高风险区域确认

| 项目 | 结果 |
|---|---|
| 是否改 Layer A 裁决逻辑 | 否 |
| 是否改 Layer A prompt | 否 |
| 是否改 Layer B | 否 |
| 是否改虚拟账户 | 否 |
| 是否改真实交易接口 | 否 |
| 是否跑完整 pipeline | 否 |
| 是否读取或输出 secret | 否 |
| 是否清空数据库 | 否 |

## 13. 删除清单 / 废弃清单

本轮是只读审计和报告新增，无替代实现，无删除项。

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 无 | N/A | 本轮未删除代码或配置。 |

## 14. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A，本轮仅报告 |
| GitHub push | 待提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | N/A，本轮报告不需要重启 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | N/A |

## 15. 风险和未完成

1. 本轮读取的是本地 SQLite 最新 Layer A run；生产端最新数据可能因用户部署和运行时间不同而略有差异。
2. 只读快照显示大量字段 `missing/stale`，需要下一轮针对数据采集/入库/freshness 做专项排查。
3. stablecoin liquidity、TGA/RRP、net liquidity 的具体 endpoint/series 仍需低成本 health check 后再决定接入方式。
4. 当前报告没有实现新数据接入，也没有改变 AI 裁决行为。

