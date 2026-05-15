# Layer A 五阶段状态机与因子最终梳理报告

## 1. 任务目标

本轮把 Layer A“大周期策略 / 现货仓策略”从 AI 每次自由给阶段，改成“AI 给当前特征 raw_stage，系统给正式阶段 official_stage”的五阶段模型。

目标包括：
- 正式阶段只保留 5 类：`deep_value`、`accumulation`、`trend_hold`、`distribution`、`overheated_exit`。
- 5 个正式阶段和 5 个现货动作一一对应。
- 增加连续确认机制，避免一天内从“低位吸筹区”直接跳到“趋势持有区”或更远阶段。
- 梳理 Layer A 因子：A1 只看低频周期核心因子，短周期衍生品降级为 Layer B / 背景。
- 不改 Layer B、不改虚拟账户、不改真实交易。

## 2. 读取文件

- `AGENTS.md`
- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `config/ai.yaml`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/agents/prompts/a2_onchain_macro.txt`
- `src/ai/agents/prompts/a3_spot_opportunity.txt`
- `src/ai/agents/prompts/a4_spot_risk.txt`
- `src/ai/agents/prompts/a5_spot_adjudicator.txt`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/spot_validator.py`
- `src/ai/orchestrator.py`
- `src/pipeline/layer_a_spot_runner.py`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/fred.py`
- `src/data/collectors/coinglass.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `scripts/check_glassnode_health.py`
- `scripts/run_layer_a_once.py`
- `web/assets/app.js`
- `web/index.html`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_spot_normalize.py`
- `tests/test_layer_a_spot_validator.py`
- `tests/test_layer_a_orchestrator_integration.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`
- `docs/codex_reports/audit_layer_a_a1_cycle_stage_model_and_transition_logic.md`
- `docs/codex_reports/layer_a_remaining_key_factors_validation_and_ingestion.md`
- `docs/codex_reports/fix_glassnode_partial_health_detail_and_recovery.md`

## 3. 改动文件

- `src/ai/spot_cycle_stage_state.py`：新增五阶段状态机 helper。
- `src/ai/spot_strategy_normalizer.py`：拆分 raw_stage / official_stage，接入状态机、五动作归一和 confidence cap。
- `src/ai/spot_cycle_context_builder.py`：新增 A/B/C/D 因子归类，补充关键因子缺失/过期的 coverage 规则。
- `src/pipeline/layer_a_spot_runner.py`：Layer A 单独运行时读取上一轮最新 Layer A 状态，传给本轮 context。
- `src/ai/orchestrator.py`：把 previous_layer_a_state 和 factor_role_classification 放入 Layer A normalize / snapshot。
- `src/ai/agents/prompts/a1_spot_cycle.txt`：A1 只输出五阶段 raw_stage，强调 A1 核心因子和连续确认边界。
- `src/ai/agents/prompts/a3_spot_opportunity.txt`：现货动作统一为五动作。
- `src/ai/agents/prompts/a5_spot_adjudicator.txt`：A5 改为基于 official_stage 和 transition_status 出最终动作。
- `src/ai/agents/spot_cycle_agents.py`：fallback 改为五阶段安全默认。
- `src/ai/spot_validator.py`：强买/强卖 guardrail 改为 `strong_buy` / `strong_sell`。
- `web/index.html`：大周期策略摘要新增正式阶段、当前特征、确认状态。
- `web/assets/app.js`：新增五阶段、五动作和确认状态中文映射。
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_spot_normalize.py`
- `tests/test_layer_a_spot_validator.py`
- `tests/test_web_modules_1_2_3.py`

## 4. Layer A 5 阶段设计

| 正式阶段 | 中文 | 默认动作 | 含义 |
|---|---|---|---|
| `deep_value` | 深度低估区 | `strong_buy` / 强势买入 | 长周期估值、价格位置和持有人行为都偏深度低估。 |
| `accumulation` | 低位吸筹区 | `dca_buy` / 分批买入 | 底部修复或低位吸筹，适合缓慢加仓。 |
| `trend_hold` | 趋势持有区 | `hold` / 持有 | 趋势已经修复或延续，持有优先，避免追涨加速。 |
| `distribution` | 高位派发区 | `scale_sell` / 分批卖出 | 高位分发或估值偏热，适合逐步降低风险。 |
| `overheated_exit` | 顶部退出区 | `strong_sell` / 强力卖出 | 顶部过热或系统性风险升高，现货应主动退出。 |

兼容旧阶段映射：
- `bear_bottom` / `deep_bear` → `deep_value`
- `accumulation` / `early_bull` → `accumulation`
- `mid_bull` → `trend_hold`
- `late_bull` / `distribution` / `bear_transition` → `distribution`
- `overheated_exit` → `overheated_exit`

## 5. A1 数据因子最终清单

### A 类：A1 大周期阶段核心因子

这些因子用于判断正式周期阶段，要求低频、长周期、低噪音。

| factor_name | 当前来源 | 当前状态 | 当前进入 | 建议归类 | 是否保留 | 原因 |
|---|---|---|---|---|---|---|
| BTC price / current_close | derived / market context | 已接入 | A1 / web | A | 保留 | 周期阶段必须知道当前价格位置。 |
| ATH drawdown | derived | 已接入 | A1 | A | 保留 | 判断深度低估和顶部回撤位置。 |
| MA200D / MA200W | derived | 已接入或可派生 | A1 | A | 保留 | 长周期价格结构核心。 |
| realized_price | Glassnode | collector 支持 | A1 | A | 保留 | 判断链上成本线。 |
| STH / LTH realized price | Glassnode 聚合 | collector 支持 | A1 | A | 保留 | 判断短长持有人成本区域。 |
| mvrv_z_score | Glassnode | 已配置/collector 支持 | A1 | A | 保留 | 周期估值温度核心。 |
| mvrv | Glassnode | health check ok | A1 | A | 保留 | 估值偏高/偏低核心。 |
| nupl | Glassnode | 已配置/collector 支持 | A1 | A | 保留 | 盈亏结构判断。 |
| rhodl_ratio | Glassnode | 已配置/collector 支持 | A1 | A | 保留 | 顶部/底部估值温度。 |
| reserve_risk | Glassnode | health check ok | A1 | A | 保留 | 长期持有者信心与风险回报。 |
| puell_multiple | Glassnode | health check ok | A1 | A | 保留 | 矿工收入压力和周期位置。 |
| lth_sopr | Glassnode | health check ok | A1 | A | 保留 | 长期持有人获利/亏损卖出状态。 |
| sth_sopr | Glassnode | collector 支持 | A1 | A | 保留 | 短期持有人承压或修复。 |
| lth_supply / sth_supply | Glassnode | 已配置或派生 | A1 | A | 保留 | 筹码结构核心。 |
| lth_net_position_change | Glassnode | collector 支持 | A1 | A | 保留 | 长期持有人增减持方向。 |
| percent_supply_in_profit/loss | Glassnode / derived | 已接入 | A1 | A | 保留 | 盈利/亏损筹码比例，识别过热或底部。 |
| hodl_waves | Glassnode | collector 支持 | A1 | A | 保留 | 长持筹码结构。 |
| cdd | Glassnode | collector 支持 | A1 | A | 保留 | 老币移动和分发风险。 |
| exchange_balance / exchange_net_position_change | Glassnode / derived | 已接入 | A1 | A | 保留 | 交易所筹码压力。 |

### B 类：A2/A4 背景因子

这些因子可以影响置信度、风险和反方证据，但不应单独决定 A1 阶段。

| factor_name | 当前来源 | 当前状态 | 当前进入 | 建议归类 | 是否保留 | 原因 |
|---|---|---|---|---|---|---|
| ETF flow | derived / external if available | 部分可用 | A2/A4 | B | 保留为背景 | 资金流重要，但短期流入流出不能单独让周期跨级。 |
| real_yield | FRED `DFII10` | 已配置/collector 支持 | A2/A4 | B | 保留 | 宏观利率压力。 |
| fed_funds_rate | FRED `FEDFUNDS` | 已配置/collector 支持 | A2/A4 | B | 保留 | 政策利率环境。 |
| us2y | FRED `DGS2` | 已配置/collector 支持 | A2/A4 | B | 保留 | 短端利率压力。 |
| cpi / core_cpi | FRED `CPIAUCSL` / `CPILFESL` | 已配置/collector 支持 | A2/A4 | B | 保留 | 通胀压力，月度 freshness 单独处理。 |
| m2 | FRED `M2SL` | 已配置/collector 支持 | A2/A4 | B | 保留 | 美元流动性背景。 |
| fed_balance_sheet | FRED `WALCL` | 已配置/collector 支持 | A2/A4 | B | 保留 | 基础流动性背景。 |
| DXY / VIX / Nasdaq / BTC dominance | context / config 视可用性 | 部分可用 | A2/A4 | B | 保留为背景 | 风险偏好和美元流动性背景。 |

### C 类：更适合 Layer B 的波段因子

| factor_name | 当前来源 | 当前状态 | 当前进入 | 建议归类 | 是否保留 | 原因 |
|---|---|---|---|---|---|---|
| funding_rate | CoinGlass | 已接入 | Layer B / 背景 | C | 保留给 Layer B | 短周期衍生品拥挤度，不适合决定 A1 大周期。 |
| open_interest | CoinGlass | 已接入 | Layer B / 背景 | C | 保留给 Layer B | 波段风险更敏感。 |
| liquidation | CoinGlass | 已接入 | Layer B / 背景 | C | 保留给 Layer B | 短线杠杆清算信号。 |
| long_short_ratio | CoinGlass | 已接入 | Layer B / 背景 | C | 保留给 Layer B | 情绪/拥挤短周期噪音较高。 |
| basis / options IV/skew | 当前项目未稳定接入 | 不稳定或未接入 | unavailable | C/D | 暂缓 | 更适合风险背景，不作为 A1 主判断。 |

### D 类：暂不作为 A1 主判断

| factor_name | 当前来源 | 当前状态 | 当前进入 | 建议归类 | 是否保留 | 原因 |
|---|---|---|---|---|---|---|
| liquidation_heatmap_levels | CoinGlass candidate | not_found | unavailable | D | 暂缓 | 项目未稳定接入，不能伪装为可用。 |
| options_iv_skew | CoinGlass candidate | not_found | unavailable | D | 暂缓 | 没有稳定接口。 |
| stablecoin_supply / exchange_flow | candidate | not_found | unavailable | D | 暂缓 | 未稳定接入。 |
| 高频动量 / 20D change / funding 24h change | derived / CoinGlass | 可派生但噪音高 | Layer B | D for A1 | 不进 A1 | A1 是大周期，不用短线动量直接定阶段。 |

## 6. 每个核心因子接口状态

代码证据：
- Glassnode endpoint 在 `config/data_catalog.yaml` 和 `src/data/collectors/glassnode.py` 中登记。
- FRED series 在 `src/data/collectors/fred.py` 中登记。
- 本轮运行 `uv run python scripts/check_glassnode_health.py`，脱敏结果：
  - `mvrv` ok，latest_value_present=true
  - `lth_sopr` ok，latest_value_present=true
  - `reserve_risk` ok，latest_value_present=true
  - `puell_multiple` ok，latest_value_present=true

| 因子 | 接口 / series | 状态 | 是否进入 A1 |
|---|---|---|---|
| price | market context | 已有 | 是 |
| ATH drawdown | derived | 已有 | 是 |
| MA200D / MA200W | derived | 已有或可派生 | 是 |
| realized_price | `/v1/metrics/market/price_realized_usd_close` | collector 支持 | 是 |
| STH/LTH realized price | breakdown 聚合 | collector 支持 | 是 |
| mvrv_z_score | `/v1/metrics/market/mvrv_z_score` | collector 支持 | 是 |
| mvrv | `/v1/metrics/market/mvrv` | health check ok | 是 |
| nupl | `/v1/metrics/indicators/net_unrealized_profit_loss` | collector 支持 | 是 |
| rhodl_ratio | `/v1/metrics/indicators/rhodl_ratio` | collector 支持 | 是 |
| reserve_risk | `/v1/metrics/indicators/reserve_risk` | health check ok | 是 |
| puell_multiple | `/v1/metrics/indicators/puell_multiple` | health check ok | 是 |
| lth_sopr | `/v1/metrics/indicators/sopr_more_155` | health check ok | 是 |
| sth_sopr | `/v1/metrics/indicators/sopr_less_155` | collector 支持 | 是 |
| lth_net_position_change | `/v1/metrics/supply/lth_net_position_change` | collector 支持 | 是 |
| percent_supply_in_profit | `/v1/metrics/supply/profit_relative` | collector 支持 | 是 |
| percent_supply_in_loss | derived | 已派生 | 是 |
| exchange_balance | `/v1/metrics/distribution/balance_exchanges` | collector 支持 | 是 |
| exchange_net_position_change | derived from exchange_balance | 已派生 | 是 |
| hodl_waves | `/v1/metrics/supply/hodl_waves` | collector 支持 | 是 |
| cdd | `/v1/metrics/indicators/cdd` | collector 支持 | 是 |
| real_yield | FRED `DFII10` | collector 支持 | A2/A4 |
| CPI / Core CPI | FRED `CPIAUCSL` / `CPILFESL` | collector 支持 | A2/A4 |
| M2 / Fed balance sheet | FRED `M2SL` / `WALCL` | collector 支持 | A2/A4 |

## 7. 状态机迁移规则

正式阶段顺序：

`deep_value → accumulation → trend_hold → distribution → overheated_exit`

允许相邻回退：

`overheated_exit → distribution → trend_hold → accumulation → deep_value`

确认规则：
- 无历史状态：首次五阶段输出直接作为 official_stage。
- raw_stage 与 official_stage 一致：`confirmed`。
- 相邻阶段变化：需要连续 2 次确认。
- 跨 2 级或以上变化：需要连续 3 次确认。
- 上一轮不是五阶段模型：`recalibration`，先保留上一轮映射后的 official_stage，不把模型重校准当成市场一天完成跳变。
- 关键数据过期、关键因子未稳定接入、confidence_cap 不是 high、validator 有 hard violation、A4 风险 high/critical：不能确认升级，只能 pending。

新增字段：
- `raw_stage_assessment`
- `official_cycle_stage`
- `previous_official_stage`
- `transition_status`
- `transition_direction`
- `confirmation_count`
- `confirmation_required`
- `stage_change_reason`
- `evidence_for_change`
- `evidence_against_change`
- `confidence_cap_reason`

## 8. A5 如何使用 official_stage

A5 现在不能直接把 A1 raw_stage 当正式阶段。系统在 normalizer 中先计算 `official_cycle_stage`，再把 A5 的 `cycle_stage` 对齐到 official stage。

默认动作映射：
- `deep_value` → `strong_buy`
- `accumulation` → `dca_buy`
- `trend_hold` → `hold`
- `distribution` → `scale_sell`
- `overheated_exit` → `strong_sell`

保守调整：
- official_stage 是 `accumulation` 时，AI 若给 `strong_buy`，会保守归一为 `dca_buy`。
- official_stage 是 `trend_hold` 时，AI 若给买入动作，会保守归一为 `hold`。
- official_stage 是 `distribution` 时，AI 若给 `strong_sell`，会保守归一为 `scale_sell`。
- 风险 high/critical 时，买入动作会降为 `hold`。

这对交易系统的意义：Layer A 可以辅助现货仓方向，但不会因为一天的 AI 语气变化突然从低位买入切到趋势持有或高位卖出。

## 9. 网页展示变化

大周期策略摘要区新增：
- 正式阶段：`official_cycle_stage`
- 当前特征：`raw_stage_assessment`
- 确认状态：`transition_status`
- 确认进度：`confirmation_count / confirmation_required`
- 阶段变化说明：`stage_change_reason`

仍保留：
- 策略
- 置信度
- 风险
- A1-A5 详情卡片

网页不显示原始 JSON，不改变 Layer B、原始因子、周复盘模块。

## 10. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`32 passed`

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`139 passed`

```bash
uv run python scripts/check_glassnode_health.py
```

结果：Glassnode 低成本 health check 返回 `mvrv / lth_sopr / reserve_risk / puell_multiple` 均为 `ok`。

`git diff --check`：见最终提交前检查结果。

## 11. 是否影响高风险区域

| 项目 | 结果 |
|---|---|
| 是否改 Layer B 逻辑 | 否 |
| 是否改 Layer B C 级机会行为 | 否 |
| 是否改虚拟账户逻辑 | 否 |
| 是否改仓位 / 止损 / 止盈 / 开平仓 / 反手 | 否 |
| 是否改真实交易 | 否 |
| 是否泄露 key / token / secret | 否 |

## 12. 删除清单 / 废弃清单

| 对象 | 位置 | 处理 |
|---|---|---|
| Layer A 旧 8/9 阶段正式输出口径 | A1/A5 prompt 与 normalizer | 废弃为兼容映射，不再作为 official_stage。 |
| `aggressive_buy` / `scale_out` / `aggressive_sell` 作为标准动作 | normalizer / validator / prompt | 废弃为兼容别名，标准动作改为 `strong_buy` / `scale_sell` / `strong_sell`。 |

本轮没有删除生产文件；旧值仍作为 legacy 输入兼容，避免旧 run 和旧 AI 输出导致网页或 normalize 崩溃。

## 13. 风险和未完成

- 当前没有新增独立 stage history 表，而是优先从 `latest_layer_a_spot_strategy` 读取上一轮 Layer A 状态。好处是低风险，不改数据库；限制是只能做上一轮确认，不是完整长历史统计。
- `hodl_waves` 和 `cdd` 已作为 A1 核心因子，但如果生产端缺值或过期，会通过 factor_coverage 降低确认能力；本轮没有强行伪造数据。
- A1 prompt 已明确 ETF / 宏观只影响置信度和反方证据，但 AI 仍可能在文字中偏重宏观；normalizer/state machine 会阻止它直接造成正式阶段跨级确认。
- 首次迁移到五阶段模型时，如果上一轮不是五阶段模型，会进入 `recalibration`，这可能让正式阶段短期更保守，这是有意设计。

## 14. 下一步建议

1. 生产部署后先运行一次 Layer A，观察网页上“正式阶段 / 当前特征 / 确认状态”是否符合预期。
2. 连续 2-3 天观察 transition_status，确认阶段不会再一天内大跳。
3. 若需要更完整审计，可以下一轮增加轻量 `layer_a_cycle_stage_history` 表，保存连续确认历史和关键证据摘要。
4. 不建议马上把 Layer A 结果接入 Layer B 开平仓；目前仍应只作为现货大周期参考。

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待本轮提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 16. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

如果需要跑 Layer A：

```bash
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

刷新：

```text
http://124.222.89.86/
```
