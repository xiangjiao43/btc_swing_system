# audit_layer_a_a1_cycle_stage_model_and_transition_logic

## 1. 任务目标

本轮只读审计 Layer A A1「大周期阶段」当前怎么判断、实际看哪些数据、prompt / context / normalizer / validator 是否有阶段稳定机制，并解释最近为什么可能出现「底部吸筹」到「牛市中段」的快速变化。

本轮没有改 A1-A5 prompt，没有改 Layer A / Layer B 策略逻辑，没有改网页，没有改数据库，没有跑完整 pipeline。

## 2. 读取文件

- `AGENTS.md`
- `docs/codex_reports/layer_a_spot_cycle_strategy_full_model_and_implementation.md`
- `docs/codex_reports/schedule_layer_a_spot_strategy_at_10am.md`
- `docs/codex_reports/layer_a_remaining_key_factors_validation_and_ingestion.md`
- `docs/codex_reports/deploy_and_verify_layer_a_on_production_web.md`
- `docs/codex_reports/layer_a_modeling_optimization_phase_3_4.md`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/agents/prompts/a2_onchain_macro.txt`
- `src/ai/agents/prompts/a5_spot_adjudicator.txt`
- `src/ai/agents/spot_cycle_agents.py`
- `src/ai/orchestrator.py`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/spot_validator.py`
- `src/pipeline/layer_a_spot_runner.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_spot_normalize.py`
- `tests/test_layer_a_spot_validator.py`
- `tests/test_layer_a_orchestrator_integration.py`
- `tests/test_layer_a_standalone_schedule.py`
- `web/assets/app.js`

## 3. A1 当前输入数据清单

A1 的实际输入来自 `A1SpotCycleAnalyst._build_user_prompt()`，它会把调用方传入的 JSON 原样放进 prompt：

```text
===== Layer A A1 输入 =====
{ "spot_cycle_context": ... }
```

也就是说，A1 当前不是只看几个单独字段，而是能看到完整的 `spot_cycle_context`。这个 context 在 `src/ai/spot_cycle_context_builder.py` 中构建。

### 3.1 价格周期位置

当前进入 `spot_cycle_context.available_factors.price_structure`：

| 因子 | 当前是否进入 A1 | 说明 |
|---|---|---|
| BTC current close / price | 是 | `price_structure.current_close` |
| ATH drawdown | 是 | `price_structure.ath_drawdown_pct`，用 1D close 历史高点计算 |
| 200D MA | 是 | `price_structure.ma_200d`，当前实现来自 `compute_emas_1d()` 的 `ema_200_current`，名字叫 ma_200d，但更接近 EMA200 口径 |
| 200W MA | 是 | `price_structure.ma_200w`，用 1W close rolling 200 计算 |
| weekly structure | 是 | 13w / 52w change、bars_available |
| tf_alignment | 是 | 多周期结构字段，但当前没有看到 1M 结构 |
| 1M structure | 否 | 在 unavailable 里有 `monthly_structure_1m`，模型预留但未稳定接入 |
| major support / resistance | 否 | 在 unavailable 里有 `major_support_resistance` |

### 3.2 链上估值

当前进入 `available_factors.onchain_valuation`：

| 因子 | 当前是否进入 A1 | 说明 |
|---|---|---|
| MVRV Z-Score | 是 | `mvrv_z_score` |
| MVRV | 是 | `mvrv` |
| NUPL | 是 | `nupl` |
| Realized Price | 是 | `realized_price` |
| LTH Realized Price | 是 | `lth_realized_price` |
| STH Realized Price | 是 | `sth_realized_price` |
| LTH MVRV / STH MVRV | 是 | `lth_mvrv`, `sth_mvrv` |
| Percent Supply in Profit | 是 | `percent_supply_in_profit` |
| RHODL Ratio | 是 | `rhodl_ratio` |
| Reserve Risk | 是 | `reserve_risk` |
| Puell Multiple | 是 | `puell_multiple` |
| Market Cap / Realized Cap | 否 | 在 unavailable 预留，未稳定接入 |

### 3.3 持有人行为

当前进入 `available_factors.holder_behavior` 和 `available_factors.onchain_holder_behavior`：

| 因子 | 当前是否进入 A1 | 说明 |
|---|---|---|
| LTH Supply | 是 | `lth_supply` |
| STH Supply | 是 | `sth_supply` |
| LTH / STH Supply 90d change | 是 | 规则化派生字段 |
| LTH SOPR | 是 | `lth_sopr` |
| STH SOPR | 是 | `sth_sopr` |
| LTH Net Position Change | 是 | `lth_net_position_change` |
| Percent Supply in Loss | 是 | 由 `percent_supply_in_profit` 规则化派生 |
| Exchange Balance | 是 | `exchange_balance` |
| Exchange Net Position Change | 是 | 由 exchange balance delta 规则化派生 |
| HODL Waves | 字段有，但当前缺值 | `hodl_waves` 已接入字段，但最新 run 显示缺失 |
| CDD / SSR / aSOPR | 是 | `cdd`, `ssr`, `sopr_adjusted` |
| Liveliness | 否 | 在 unavailable 预留，未稳定接入 |

### 3.4 资金流

当前进入 `available_factors.exchange_and_flows`：

| 因子 | 当前是否进入 A1 | 说明 |
|---|---|---|
| Exchange Net Flow | 是 | `exchange_net_flow` 和 `exchange_net_flow_30d_sum` |
| Exchange Balance | 是 | 重复出现在估值/资金流相关组 |
| ETF Flow | 是 | `etf_flow`, `etf_flow_7d_sum_usd`, `etf_flow_30d_sum_usd` |
| Stablecoin supply / liquidity | 否 | 在 unavailable 预留，未稳定接入 |

衍生品数据也在 context 的 `market_context` 里，包括 funding、open interest、long/short ratio、liquidation_total、btc_dominance。A1 prompt 明确要求：Funding / OI / liquidation 只能作为背景风险，不要单独决定 `cycle_stage`。

### 3.5 宏观

当前进入 `available_factors.macro`, `macro_liquidity`, `macro_inflation_rates`：

| 因子 | 当前是否进入 A1 | 说明 |
|---|---|---|
| US10Y | 是 | `us10y` / `dgs10` alias |
| US2Y | 是 | `us2y` |
| Real Yield | 是 | `real_yield` |
| Fed Funds Rate | 是 | `fed_funds_rate` |
| CPI | 是 | `cpi` |
| Core CPI | 是 | `core_cpi` |
| M2 | 是 | `m2` |
| Fed Balance Sheet | 是 | `fed_balance_sheet` |
| DXY | 是 | `dxy` |
| VIX | 是 | `vix` |
| Nasdaq | 是 | `nasdaq` |
| BTC-Nasdaq 60d correlation | 是 | `btc_nasdaq_corr_60d` |
| Unemployment | 否 | 在 unavailable 预留，未稳定接入 |

### 3.6 数据质量

当前 A1 能看到：

- `unavailable_factors`
- `factor_coverage`
- `data_quality_notes`
- `series_samples`
- 每个因子的 `status / actual_value / timestamp / fetched_at / captured_at`

但注意：A1 只被 prompt 要求“缺失较多时 confidence 不得 high”。它没有被硬性要求根据 `stale_factor_count` 或阶段跳变降低 confidence。

## 4. A1 当前 prompt 审计

`src/ai/agents/prompts/a1_spot_cycle.txt` 当前要求：

- 只能输出固定 `cycle_stage`：
  - `bear_bottom`
  - `accumulation`
  - `early_bull`
  - `mid_bull`
  - `late_bull`
  - `distribution`
  - `bear_transition`
  - `deep_bear`
  - `unclear`
- 输出字段：
  - `cycle_stage`
  - `confidence`
  - `headline`
  - `human_summary`
  - `bullish_evidence`
  - `bearish_evidence`
  - `conflicting_evidence`
  - `data_quality_notes`

当前 prompt 合理的地方：

- 明确 Layer A 只做 BTC 现货大周期，不做空、不加杠杆、不创建 thesis、不进入虚拟账户。
- 明确不使用 Layer B 的 A/B/C/NONE。
- 明确大周期阶段要综合价格结构、链上估值、持有人行为、长期资金流。
- 明确衍生品只能作为背景风险。
- 明确缺失数据要写入 `data_quality_notes`。

当前 prompt 的关键缺口：

| 问题 | 当前情况 |
---|---|
| 是否定义“底部吸筹”和“牛市中段”的明确边界 | 没有。只有枚举，没有阶段边界表 |
| 是否要求读取上一轮 A1 | 没有 |
| 是否有 previous_cycle_stage | 没有 |
| 是否要求解释阶段变化 | 没有 |
| 是否禁止一天内大幅跳变 | 没有 |
| 是否要求 2-3 次连续确认 | 没有 |
| 是否有 pending / 待确认状态 | 没有 |
| 是否有阶段迁移路径 | 没有 |
| 是否有跨级跳变 confidence cap | 没有 |

结论：当前 A1 是“截面分类器”，不是“状态机判断器”。

用小白话说：它每次都像重新请一个交易员看今天这包数据，然后让他直接给阶段名字；它不会自动记住昨天说过什么，也不会问“从昨天那个阶段跳到今天这个阶段是否合理”。

## 5. normalizer / validator 审计

### 5.1 normalizer

`src/ai/spot_strategy_normalizer.py` 里：

- `CYCLE_STAGES` 只定义合法枚举。
- `normalize_a1()` 只做：
  - 非法 `cycle_stage` → `unclear`
  - 非法 `confidence` → `low`
  - 文本 / list 字段 fallback
- `_apply_confidence_cap()` 只根据 `factor_coverage.confidence_cap` 降低 A1-A5 confidence。

当前没有：

- previous stage 读取
- stage jump 检查
- accumulation → mid_bull 这种跨级跳变限制
- pending confirmation
- stage_change_reason
- stage_changed_from / to
- 大幅跳变时自动降 confidence

另外 `_CRITICAL_COVERAGE_FACTORS` 当前是空集合；这意味着 normalizer 里“critical_unavailable_count”不会因为预留因子自动增加，除非上游直接传入已有 coverage。最新 Layer A run 显示 `critical_unavailable_count=0`，但 `stale_factor_count=19`，confidence_cap 仍是 `high`。这对“数据过期时防止高置信度”不够严格。

### 5.2 validator

`src/ai/spot_validator.py` 当前主要检查：

- Layer A 不得输出 short / 做空 / hedge short。
- 不得输出 A/B/C/NONE 机会等级。
- 不得输出 thesis、entry、stop_loss、take_profit、position_size、leverage、virtual_account 等 Layer B 字段。
- aggressive_buy / aggressive_sell 必须有支持证据和反方证据。
- 缺失数据时必须有 data_quality_notes。
- A5 confidence 不得超过 factor_coverage cap。

当前没有：

- A1 阶段迁移检查。
- 上一轮 `cycle_stage` 读取。
- accumulation → mid_bull 这种跳变警告。
- 大跳时自动把 confidence 降到 low / medium。
- 要求 A1 解释阶段变化。

结论：validator 现在守的是 Layer A / Layer B 边界和输出格式，不守“大周期阶段稳定性”。

## 6. 持久化与历史读取审计

当前 Layer A 独立运行路径：

1. `scripts/run_layer_a_once.py`
2. `src/pipeline/layer_a_spot_runner.py`
3. `ContextBuilder.build_full_context()`
4. `SpotCycleContextBuilder.build_spot_cycle_context()`
5. `AIOrchestrator.run_layer_a_spot_only()`
6. A1 → A2 → A3 → A4 → A5
7. `LatestLayerASpotStrategyDAO.upsert()`
8. 写入 `latest_layer_a_spot_strategy`

`latest_layer_a_spot_strategy` 是单行表：

- `id = 1`
- 每次 Layer A 独立运行会覆盖最新 Layer A 结果。
- 不保存多条历史。

当前状态：

| 问题 | 当前情况 |
---|---|
| Layer A 单独运行是否读取上一轮 Layer A 结果 | 不读取 |
| A1 prompt 是否拿到 previous_cycle_stage | 没有 |
| A5 是否拿到 previous spot action | 没有 |
| 是否保存 A1 阶段历史 | 只保存最新一条，不保存历史序列 |
| 是否保存 stage_changed_from / to | 没有 |
| 是否保存 stage_change_reason | 没有 |
| 是否保存 pending_confirmation_count | 没有 |
| 是否有状态迁移记录 | 没有 |

但有一个好点：当前 Layer A 输出会保存 `input_context_snapshot`，所以最新一条可以审计当时 A1 看到的数据。问题是只有最新一条，无法从这张表回放最近 2-5 次独立 Layer A 的完整输入。

## 7. 最近运行结果对比

本轮只读查询了生产服务器：

- 项目目录：`/home/ubuntu/btc_swing_system`
- 数据库：`data/btc_strategy.db`
- 查询对象：`latest_layer_a_spot_strategy` 和历史 `strategy_runs.full_state_json`

查询摘要已保存到审查包：`recent_layer_a_runs_summary.json`。

### 7.1 当前最新 Layer A

| 字段 | 值 |
---|---|
| run_id | `2d69d6c6752e41aabce81ab98bdf9f54` |
| generated_at_bjt | `2026-05-15 11:12:37 BJT` |
| A1 cycle_stage | `mid_bull` |
| A1 confidence | `medium` |
| A5 spot_action | `hold` |
| A5 cycle_stage | `mid_bull` |
| A4 risk | `elevated` |
| validator.passed | `true` |
| coverage_ratio | `0.6875` |
| critical_unavailable_count | `0` |
| confidence_cap | `high` |
| missing_integrated_factor_count | `1` |
| stale_factor_count | `19` |

当前最新关键因子：

| 因子 | 值 | 状态 |
---|---:|---|
| BTC price | `81299.9` | available |
| ATH drawdown | `-34.7662%` | available |
| 200D | `82138.1471` | available |
| 200W | `61097.403` | available |
| MVRV Z | `0.9293` | stale |
| MVRV | `1.4933` | stale |
| NUPL | `0.3303` | stale |
| RHODL Ratio | `991.5457` | available |
| Reserve Risk | `0.0012` | available |
| Puell Multiple | `0.7816` | available |
| LTH SOPR | `0.8133` | available |
| STH SOPR | `1.0086` | available |
| LTH Net Position Change | `123394.3365` | available |
| Percent Supply in Profit | `0.6593` | stale |
| Exchange Balance | `3008998.7614` | stale |
| ETF 7d flow | `-1217200000` | available |
| ETF 30d flow | `2607600000` | available |
| US2Y | `3.98` | available |
| Real Yield | `1.99` | available |
| Fed Funds Rate | `3.64` | available |
| CPI | `332.407` | available |
| Core CPI | `335.423` | available |
| M2 | `22686.0` | available |
| Fed Balance Sheet | `6709505.0` | available |

### 7.2 历史可证据结果

由于 `latest_layer_a_spot_strategy` 是单行表，生产 DB 无法直接查询最近 2-5 次独立 Layer A 历史。可用证据来自历史报告和早期嵌入 `strategy_runs` 的 Layer A：

| 来源 | 时间 / run | A1 cycle_stage | A5 spot_action | coverage |
---|---|---|---|---|
| `deploy_and_verify_layer_a_on_production_web.md` | `2026-05-12T06:26:17Z`, run `f99ce07...` | `accumulation` | `dca_buy` | 当时提示 `high_confidence_with_many_missing_factors` |
| `layer_a_modeling_optimization_phase_3_4.md` | `2026-05-12T09:06:54Z`, run `19fac5...` | `accumulation` | `dca_buy` | `critical_unavailable_count=16`, `confidence_cap=medium` |
| `layer_a_remaining_key_factors_validation_and_ingestion.md` | `2026-05-13` 报告 | 最新 strategy_run 仍为 `209dea...` | A1 `accumulation` | 剩余因子代码接入完成，但新 run 当时还没刷新 |
| 当前生产 DB 最新 | `2026-05-15 11:12:37 BJT`, run `2d69d6...` | `mid_bull` | `hold` | `critical_unavailable_count=0`, `confidence_cap=high`, 但 `stale_factor_count=19` |

### 7.3 “底部吸筹 → 牛市中段”的真实原因分析

能确认的原因有三层：

1. **模型输入覆盖变了。**  
   早期 accumulation 运行时，报告显示 `critical_unavailable_count` 曾是 16 或 8，且 LTH/STH SOPR、RHODL、Reserve Risk、Puell、Real Yield、CPI/Core CPI、LTH Net Position Change 等关键因子还未稳定进入最新 run。当前最新 run 中这些因子大多已经进入 context，A1 看到的证据明显更完整。

2. **A1 是截面重分类，不是阶段迁移。**  
   代码里没有 previous_stage、stage transition、连续确认。AI 每次可以基于“今天这包数据”重新给阶段。因此从 accumulation 到 mid_bull，在当前系统里不是被状态机确认的“自然阶段推进”，而是一次“新证据集下的重新分类”。

3. **当前 latest 表不保留历史 context，无法精确回放两次输入差异。**  
   最新 run 保存了 input_context_snapshot，但历史独立 Layer A 的 snapshot 已被覆盖。只能从历史报告和当前最新 snapshot 对比，不能做到逐字段复盘“昨天那一包数据 vs 今天这一包数据”的完整差异。

从交易建模角度看：BTC 不应该因为一天数据就从“底部吸筹”自然推进到“牛市中段”。如果发生这种跳变，更合理的解释是“模型/数据覆盖重校准”，而不是“市场一天完成了大周期跃迁”。

## 8. 当前数据是否足够判断大周期阶段

当前 A1 的数据覆盖比 Layer A 初版明显好了，已经具备大周期判断的核心框架：

- 价格位置：price、ATH drawdown、200D、200W、weekly structure。
- 链上估值：MVRV Z、MVRV、NUPL、Realized Price、LTH/STH RP、RHODL、Reserve Risk、Puell。
- 持有人行为：LTH/STH SOPR、LTH/STH Supply、LTH Net Position Change、盈利/亏损供给比例、交易所余额。
- 资金流：ETF flow、Exchange flow / balance。
- 宏观：US2Y、Real Yield、Fed Funds、CPI/Core CPI、M2、Fed balance sheet、DXY、VIX、Nasdaq。
- 数据质量：factor_coverage、unavailable、stale/missing 状态。

但仍有不足：

| 缺口 | 影响 |
---|---|
| 没有 1M structure | 大周期结构判断缺少月线确认 |
| major support / resistance 未稳定接入 | 阶段边界缺少结构锚 |
| HODL Waves 当前缺值 | 持币年龄结构不完整 |
| market cap / realized cap、liveliness、stablecoin liquidity 等未稳定接入 | 顶底温度和流动性维度不完整 |
| 最新 run 19 个已接入因子 stale | 数据时效性影响判断可靠度 |
| `_CRITICAL_COVERAGE_FACTORS` 为空 | missing critical 对 confidence cap 的硬约束不够 |
| A1 没有 previous state | 阶段稳定性不足 |

结论：当前数据足够让 A1 做“截面阶段估计”，但不足以让它稳定判断“阶段迁移已经确认”。

## 9. 当前设置合理的地方

- Layer A / Layer B 边界清楚：A1 不创建 thesis、不进入虚拟账户、不做空、不使用 A/B/C。
- A1 输入数据覆盖方向正确：价格、链上、持有人、资金流、宏观都进入了 context。
- 最新 run 保存 `input_context_snapshot`，便于审计单次结果。
- normalizer 能防止非法枚举污染网页。
- spot_validator 能防止 Layer A 输出 Layer B 交易计划字段。

## 10. 当前不合理的地方

### 10.1 A1 没有状态记忆

A1 不读取上一轮 cycle_stage，不能知道自己是不是在“改口”。

### 10.2 没有阶段迁移规则

当前没有类似：

```text
bear_bottom → accumulation → early_bull → mid_bull → late_bull → distribution / overheated_top → bear_transition → deep_bear
```

这样的阶段路径。

### 10.3 没有连续确认机制

accumulation 到 mid_bull 这种跨级变化，至少应该需要连续 2-3 次 Layer A run 或多日确认。当前没有。

### 10.4 没有 pending 状态

当前枚举里没有 “accumulation_to_early_bull_pending” 或“牛市早期过渡 / 待确认”。因此 AI 只能硬选一个阶段。

### 10.5 confidence cap 对 stale 不够严格

最新 run 里 `stale_factor_count=19`，但 `confidence_cap=high`。A1 最终是 medium，属于 AI 自己谨慎，但系统没有硬性因为大量 stale 自动降 cap。

### 10.6 历史保存不足

`latest_layer_a_spot_strategy` 单行覆盖，无法保存最近 2-5 次 A1 snapshot；这让阶段跳变审计只能依赖报告和日志，不能完全从 DB 回放。

## 11. 为什么会发生一天内大幅阶段变化

一句话结论：

**不是代码确认了 BTC 一天从底部吸筹进入牛市中段，而是 A1 每次用当前数据重新分类；新增因子和数据覆盖改善后，AI 把同一段市场重新解释为 mid_bull。**

具体原因：

1. `a1_spot_cycle.txt` 没有上一轮状态输入。
2. `spot_cycle_context_builder.py` 不读取 latest Layer A 结果。
3. `layer_a_spot_runner.py` 不把 previous_stage 注入 context。
4. `normalize_a1()` 不限制阶段跳变。
5. `spot_validator.py` 不检查阶段迁移。
6. 最新数据覆盖从早期 `critical_unavailable_count=16/8` 变成当前 `0`，新增 RHODL / Reserve Risk / Puell / SOPR / Real Yield / CPI 等关键证据后，AI 可能做了“重校准”。
7. 当前枚举没有 pending 状态，AI 不能表达“从 accumulation 往 early_bull / mid_bull 过渡但待确认”，只能选一个正式阶段。

## 12. 建议的阶段迁移规则

建议保留现有枚举兼容网页，但增加“官方阶段 + 过渡状态”双层表达：

### 12.1 阶段路径

建议逻辑路径：

```text
deep_bear
→ bear_bottom
→ accumulation
→ early_bull
→ mid_bull
→ late_bull
→ distribution
→ bear_transition
→ deep_bear
```

可保留项目现有 `distribution` 和 `bear_transition` 命名，不强行改成 `overheated_top / transition_down`，避免破坏前端兼容。

### 12.2 禁止大跳

- `accumulation` 不应一天直接确认成 `mid_bull`。
- 如果证据明显变化，可以先显示：
  - official stage 仍为 `accumulation` 或 `early_bull`
  - transition_state = `accumulation_to_early_bull_pending`
  - stage_change_confirmed = false
- 除非满足“强确认条件”，才允许高置信重分类。

### 12.3 连续确认

建议：

- 普通阶段切换：至少 2 次连续 Layer A run 确认。
- 跨两级以上切换：至少 3 次连续确认，或标记 `high_confidence_reclassification`。
- 如果只是新增因子导致模型重校准：显示“模型重校准 / 待确认”，不要当成自然阶段变化。

### 12.4 confidence cap

建议规则：

- 大幅跳变但无连续确认：confidence 最高 medium。
- stale_factor_count 高于阈值：confidence 最高 medium。
- 核心阶段因子缺失：confidence 最高 medium 或 low。
- 数据冲突明显：confidence 不得 high。

### 12.5 输出字段建议

在不破坏现有字段的前提下，可新增：

- `raw_stage_assessment`
- `official_cycle_stage`
- `transition_state`
- `previous_cycle_stage`
- `stage_change_confirmed`
- `confirmation_needed`
- `stage_change_reason`
- `stage_change_type`
- `evidence_for_change`
- `evidence_against_change`

网页仍可继续读原 `cycle_stage`，新增字段用于审计和稳定。

## 13. 三档修复方案

### 方案 A：最小修复

内容：

- 修改 A1 prompt。
- 在 A1 输入里加入 previous_stage。
- 要求 AI 避免跨级大跳。
- 要求 AI 输出 stage_change_reason。
- 不改数据库结构。
- previous_stage 从 `latest_layer_a_spot_strategy` 推导。

优点：

- 改动小，测试简单。

缺点：

- 主要靠 AI 自律，仍可能被忽略。
- normalizer / validator 没有硬约束。

### 方案 B：中等修复

内容：

- 在 `layer_a_spot_runner.py` 或 `spot_cycle_context_builder.py` 读取 latest Layer A，注入 `previous_layer_a_state`。
- 增加 `stage_transition_helper` 或 normalizer 后处理。
- 对跨级跳变打 warning / pending / confidence cap。
- 保存 `previous_cycle_stage`、`stage_change_reason`、`stage_change_confirmed` 到 Layer A 输出。
- 不大改 DB，可先存在 `layer_a_json` 内。

优点：

- 既低风险，又能形成代码级约束。
- 不影响 Layer B，不影响虚拟账户。
- 不需要立即加新表。

缺点：

- 历史统计仍有限，只能用 latest + 当前 run 做 1 步确认；若要 2-3 次连续确认，最好后续加历史表。

### 方案 C：完整修复

内容：

- 新增 Layer A cycle state machine。
- 独立保存 stage history 表。
- 连续确认计数。
- 明确 transition rules。
- validator 强制执行阶段迁移规则。
- 网页展示 pending / confirmed。

优点：

- 最完整，适合长期稳定建模。

缺点：

- 改动大，需要 DB schema / API / web / tests 联动。
- 当前项目刚拆分 Layer A，不建议马上一次性做太大。

## 14. 推荐方案

推荐先做 **方案 B：中等修复**。

原因：

1. 只改 Layer A 自己，不碰 Layer B 交易逻辑。
2. 能解决“一天内阶段大跳没有刹车”的核心问题。
3. 不需要新数据库表，风险比完整状态机低。
4. 可以把“新增因子导致重校准”与“市场自然阶段变化”区分开。
5. 后续如果运行稳定，再升级到方案 C。

建议下一轮实施顺序：

1. `LatestLayerASpotStrategyDAO.get_latest()` 读取 previous A1。
2. `LayerASpotStrategyRunner` 把 previous stage 注入 `spot_cycle_context.previous_layer_a_state`。
3. A1 prompt 增加“必须解释阶段变化”和“跨级跳变需要 pending / 降 confidence”。
4. normalizer 增加 `stage_transition_review` 字段。
5. validator 增加“跨级跳变 warning，不阻断”。
6. 测试：
   - accumulation → mid_bull 时不直接 high confidence。
   - previous missing 时正常 fallback。
   - 新增字段不影响旧网页。

## 15. 是否本轮改代码

本轮没有改代码，只新增审计报告。

没有修改：

- Layer A A1-A5 prompt
- Layer A normalizer / validator
- Layer B
- 虚拟账户
- 真实交易逻辑
- 网页
- 数据库

## 16. 实际运行命令

```bash
rg -n "run_layer_a_spot_only|A1|a1_spot|latest_layer_a|input_context_snapshot|factor_coverage|unavailable_factors" src/ai src/pipeline src/data/storage tests | head -200
sed -n '240,640p' src/ai/spot_cycle_context_builder.py
sed -n '360,560p' src/ai/orchestrator.py
sed -n '1140,1235p' src/data/storage/dao.py
sed -n '295,325p' src/data/storage/schema.sql
sed -n '1,120p' src/ai/agents/spot_cycle_agents.py
sed -n '1,260p' src/ai/spot_strategy_normalizer.py
sed -n '1,210p' src/ai/spot_validator.py
rg -n "previous_cycle|previous_stage|stage_change|transition_state|pending_confirmation|cycle_stage" src tests web | head -200
ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && .venv/bin/python - <<'PY' ...只读查询 latest_layer_a_spot_strategy..."
rg -n "accumulation|底部吸筹|mid_bull|牛市中段|cycle_stage" docs/codex_reports web tests src | head -200
git diff --check
```

## 17. 测试 / 检查结果

本轮为只读审计 + 报告，不改策略代码，不跑 pytest。

已运行：

- `git diff --check`：通过。

## 18. 是否影响高风险区域

| 项目 | 结果 |
---|---|
| 是否影响 Layer A 策略逻辑 | 否 |
| 是否影响 Layer B | 否 |
| 是否影响虚拟账户 | 否 |
| 是否影响真实交易 | 否 |
| 是否读取或输出 key / token / secret | 否 |
| 是否跑完整 pipeline | 否 |

## 19. 删除清单 / 废弃清单

本轮无替代关系，无删除项。原因：本轮为只读建模审计和报告，没有引入替代实现。

## 20. 风险和未完成

1. 生产 DB 的 `latest_layer_a_spot_strategy` 只保留最新一条，无法从 DB 精确回放最近 2-5 次独立 Layer A 的完整 context。
2. 历史 accumulation 证据主要来自已提交报告和当时摘要，不是完整历史 context。
3. 当前最新 run 有 19 个 stale 因子，但 confidence_cap 仍是 high，这个问题建议下一轮纳入方案 B 一起处理。
4. 当前 A1 的 `mid_bull` 不一定错，但它缺少“阶段变更确认机制”，因此不应被理解为已确认的自然大周期跃迁。

## 21. 下一步实施建议

建议下一轮实施方案 B：

1. 给 A1 输入增加 previous_layer_a_state。
2. A1 prompt 要求解释阶段变化。
3. normalizer 增加 stage_transition_review。
4. validator 对跨级跳变给 warning / confidence cap。
5. 不先加新表，先把字段保存在 `layer_a_json`。
6. 等运行几天后，再决定是否升级完整 Layer A cycle state machine。

## 22. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A，本轮仅报告 |
| GitHub push | ✅ 已推送，本报告所在 commit 见最终对话 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | N/A，本轮只读审计 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | N/A，本轮未部署 |
