# Audit Layer A Data For AI Precision

## 1. 任务目标

本轮只读扫描 Layer A 单层大周期裁决的数据输入，按四个数据包核实每个因子当前状态：

- 已抓取且有效；
- 必需但缺失；
- 已抓取但无效或冗余；
- 是否满足 AI 精准判断 BTC 大周期阶段的最低数据要求。

本轮没有修改代码、没有修改 prompt、没有改 Layer A / Layer B 策略逻辑、没有跑完整 pipeline、没有触碰真实交易。

## 2. 扫描依据

读取与核实的关键文件：

- `src/ai/agents/prompts/layer_a_cycle_adjudicator.txt`
- `src/ai/agents/spot_cycle_agents.py`
- `src/ai/orchestrator.py`
- `src/ai/spot_cycle_context_builder.py`
- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/fred.py`
- `src/data/collectors/coinglass.py`

只读查询本地 SQLite 最新 Layer A 结果：

| 字段 | 值 |
|---|---|
| run_id | `2e9ae25e6e124121999f45711b5a4c65` |
| generated_at_bjt | `2026-05-15 15:42:21 BJT` |
| architecture | `single_cycle_adjudicator` |
| ai_call_count | `1` |
| legacy_a1_a5_flow | `false` |
| official_stage | `accumulation` |
| spot_action | `hold` |
| validator_passed | `true` |

只读扫描摘要已保存到：

`/private/tmp/audit_layer_a_data_for_ai_precision/readonly_layer_a_data_scan.json`

## 3. 当前 Layer A 输入结构

当前 Layer A 单层 AI 裁决只接收四个 deterministic 数据包：

1. `technical_packet`
2. `onchain_packet`
3. `liquidity_macro_packet`
4. `risk_packet`

代码证据：

| 位置 | 证据 |
|---|---|
| `src/ai/agents/prompts/layer_a_cycle_adjudicator.txt:10` | prompt 明确列出四个数据包作为输入。 |
| `src/ai/agents/spot_cycle_agents.py:140` | `LayerACycleAdjudicator` 是当前单一 Layer A AI 裁决员。 |
| `src/ai/orchestrator.py:438` | runner 调用 `build_layer_a_cycle_adjudicator_context()` 并只调用 `layer_a_cycle`。 |
| `src/ai/spot_cycle_context_builder.py:610` | 构造四个 deterministic 数据包。 |

没有发现 Layer B L1-L5、thesis、虚拟账户、持仓、挂单、网页 factor card plain reading、完整 `full_state_json` 大对象进入 Layer A AI 裁决。

## 4. 技术指标数据包

数据包状态：`partial`

| 指标 | 当前状态 | 是否必需 | 是否冗余 | 判断 |
|---|---|---:|---:|---|
| `btc_price` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；AI 判断阶段必须知道当前价格。 |
| `ath_drawdown_pct` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；用于判断是否仍处低估/回撤区。 |
| `ma_200d` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；用于判断长期趋势恢复。 |
| `ma_200w` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；熊市底部/长期价值区锚点。 |
| `weekly_structure` | 结构字段存在但最新快照未给有效状态 | 是 | 否 | 必需但需要补充有效状态；用于高周期趋势判断。 |
| `monthly_ohlc_structure` | 已生成且可用 | 是 | 否 | 已满足最低要求；用于月线结构判断。 |
| `major_support_resistance_zones` | 已生成且可用 | 是 | 否 | 已满足最低要求；用于长期支撑/阻力定位。 |
| `realized_price` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；成本线核心锚点。 |
| `sth_realized_price` | 缺失 | 是 | 否 | 必需缺失；影响牛熊过渡/牛市初段判断。 |
| `lth_realized_price` | 缺失 | 是 | 否 | 必需缺失；影响长期持有人成本区判断。 |

结论：技术包结构正确，但当前价格、均线、成本线组不足。月线结构和支撑阻力已进入，但不能替代价格/成本线新鲜值。

## 5. 链上数据包

数据包状态：`partial`

| 指标 | 当前状态 | 是否必需 | 是否冗余 | 判断 |
|---|---|---:|---:|---|
| `mvrv` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；估值阶段基础指标。 |
| `mvrv_z_score` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；判断低估/过热。 |
| `nupl` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；市场盈利状态核心指标。 |
| `rhodl_ratio` | 缺失 | 是 | 否 | 必需缺失；周期顶部/底部温度计。 |
| `reserve_risk` | 已抓取且可用 | 是 | 否 | 有效；长期持有者信心/风险锚点。 |
| `puell_multiple` | 已抓取且可用 | 是 | 否 | 有效；矿工收入压力和周期位置。 |
| `lth_sopr` | 缺失 | 是 | 否 | 必需缺失；判断长期持有人是否获利卖出。 |
| `sth_sopr` | 缺失 | 是 | 否 | 必需缺失；判断短期筹码承压/盈亏平衡。 |
| `lth_supply` | 已抓取但过期 / 无有效值 | 是 | 否 | 必需但当前无效；长期筹码锁仓状态。 |
| `sth_supply` | 缺失 | 是 | 否 | 必需缺失；短期筹码占比影响阶段判断。 |
| `lth_supply_90d_pct_change` | 已抓取但过期 / 无有效值 | 建议 | 否 | 有价值但不是绝对 P0；可辅助判断吸筹/派发。 |
| `sth_supply_90d_pct_change` | 缺失 | 建议 | 否 | 有价值但不是绝对 P0。 |
| `lth_net_position_change` | 缺失 | 是 | 否 | 必需缺失；判断长期持有人增持/减持。 |
| `percent_supply_in_profit` | 缺失 | 是 | 否 | 必需缺失；判断市场盈利拥挤或深度亏损。 |
| `percent_supply_in_loss` | 缺失 | 是 | 否 | 必需缺失；判断底部/恐慌修复。 |
| `hodl_waves_1y_plus_aggregate` | 缺失 | 是 | 否 | 必需缺失；长期持有占比影响阶段确认。 |
| `cdd` | 缺失 | 建议 | 否 | 建议补；原值可用性不如长期均值/Z-score。 |
| `exchange_balance` | 缺失 | 是 | 否 | 必需缺失；判断交易所卖压/囤币。 |
| `exchange_net_position_change` | 缺失 | 是 | 否 | 必需缺失；判断交易所流入/流出压力。 |

结论：链上包是当前最大短板。只有 `reserve_risk` 和 `puell_multiple` 在最新快照中可用，不足以支撑精准阶段判断。

## 6. 流动性 / 宏观背景数据包

数据包状态：`partial`

| 指标 | 当前状态 | 是否必需 | 是否冗余 | 判断 |
|---|---|---:|---:|---|
| `etf_flow_7d_sum_usd` | 缺失 | 背景必需 | 否 | 应作为风险/置信度背景，不应单独驱动阶段。 |
| `etf_flow_30d_sum_usd` | 缺失 | 背景必需 | 否 | 同上，30d 比 7d 更适合 Layer A。 |
| `exchange_net_flow_30d_sum` | 已抓取但过期 / 无有效值 | 背景必需 | 否 | 应恢复；用于交易所流向背景。 |
| `m2` | 缺失 | 背景必需 | 否 | 宏观流动性核心背景。 |
| `fed_balance_sheet` | 缺失 | 背景必需 | 否 | 宏观流动性核心背景。 |
| `fed_funds_rate` | 缺失 | 背景必需 | 否 | 利率环境核心背景。 |
| `us2y` | 缺失 | 背景必需 | 否 | 短端利率压力。 |
| `real_yield` | 缺失 | 背景必需 | 否 | 实际利率压力。 |
| `dxy` | 缺失 | 建议 | 否 | 风险资产美元压力背景。 |
| `vix` | 缺失 | 建议 | 否 | 风险偏好背景。 |
| `nasdaq` | 缺失 | 建议 | 否 | 风险资产联动背景。 |
| `cpi` | 缺失 | 背景必需 | 否 | 通胀压力背景，月度数据需按月度 freshness。 |
| `core_cpi` | 缺失 | 背景必需 | 否 | 核心通胀压力背景。 |
| `stablecoin_liquidity_proxy` | 未进入当前数据包 | 是 | 否 | 当前缺失；crypto-native 流动性关键补充。 |
| `net_liquidity_tga_rrp` | 未进入当前数据包 | 建议 | 否 | 当前缺失；Fed balance sheet 的更准确派生。 |

结论：宏观包字段设计较完整，但最新 run 几乎都缺值。除此之外，稳定币流动性仍是关键结构性缺口。

## 7. 风险评估数据包

数据包状态：`partial`

| 指标 | 当前状态 | 是否必需 | 是否冗余 | 判断 |
|---|---|---:|---:|---|
| `confidence_cap` | 已生成且有效 | 是 | 否 | 当前为 `low`，正确反映数据不足。 |
| `confidence_cap_reason` | 已生成且有效 | 是 | 否 | 当前原因是 Layer A 已接入因子可用率低于 50%。 |
| `critical_unavailable_count` | 已生成且有效 | 是 | 否 | 当前为 0，但不能掩盖大量 integrated factor 缺值。 |
| `missing_integrated_factor_count` | 已生成且有效 | 是 | 否 | 当前为 44，是核心风险信号。 |
| `stale_factor_count` | 已生成且有效 | 是 | 否 | 当前为 19，是核心风险信号。 |
| `coverage_ratio` | 已生成且有效 | 是 | 否 | 当前约 0.0597，说明可用率很低。 |
| `unavailable_factors` | 已生成且有效 | 是 | 否 | 用于解释未接入/不支持因子。 |
| `near_long_term_resistance` | 已生成且可用 | 是 | 否 | 用于限制阶段升级和买入激进度。 |
| `etf_flow_7d_sum_usd` | 缺失 | 建议 | 否 | 风险背景缺失。 |
| `real_yield` | 缺失 | 建议 | 否 | 宏观风险缺失。 |
| `fed_funds_rate` | 缺失 | 建议 | 否 | 利率风险缺失。 |

结论：风险包的“数据质量风险”是有效的；但宏观/ETF 风险子项当前缺值。

## 8. 已抓取但无效或冗余项

本轮没有发现明显“已经进入 Layer A AI、但完全冗余且应删除”的字段。

但有三类需要注意：

1. `ETF 7d flow`：可以保留，但只能作为背景，不应直接决定阶段。
2. `DXY / VIX / NASDAQ`：可以保留为宏观风险背景，不应单独驱动阶段。
3. legacy `a1/a2/a3/a4/a5` 兼容字段：仍存在于 normalized output 和网页兼容层，但不是当前 Layer A 业务架构；不要把它们当作新的数据输入层。

## 9. 不应混入 Layer A 的数据

当前扫描没有发现以下内容进入单层 Layer A AI：

| 数据 | 当前是否混入 | 建议 |
|---|---:|---|
| funding rate | 否 | 保留在 Layer B / 风险背景外部，不进 Layer A 主裁决。 |
| open interest | 否 | 保留在 Layer B。 |
| liquidation | 否 | 保留在 Layer B。 |
| long/short ratio | 否 | 保留在 Layer B。 |
| futures basis | 否 | 不建议进入 Layer A 主裁决。 |
| options IV / skew | 否 | 如未来接入，只能作为风险背景。 |
| 24h derivatives changes | 否 | 不进 Layer A。 |
| 20D short-term momentum | 否 | 不进 Layer A 主裁决。 |
| Layer B L1-L5 完整分析 | 否 | 继续隔离。 |
| 当前 thesis | 否 | 继续隔离。 |
| 虚拟账户 | 否 | 继续隔离。 |
| 持仓 / 挂单 | 否 | 继续隔离。 |
| 网页 factor card plain_reading | 否 | 继续只用于网页。 |
| full_state_json 大对象 | 否 | 不进 AI。 |

## 10. 是否满足 AI 精准阶段判断的最低数据要求

结论：暂时没有完全满足。

原因：

1. 单层架构正确，四个数据包也正确。
2. 但最新 run 中四个数据包全部是 `partial`。
3. 链上包只有 `reserve_risk`、`puell_multiple` 可用，其他关键持有人/估值/交易所数据大多缺失或过期。
4. 技术包缺少新鲜价格、均线、成本线。
5. 宏观包当前缺少多数实际数值。
6. 风险包正确把 confidence cap 降到 `low`。

因此，当前 Layer A 可以作为“大周期参考分析”，但还不能作为“精准阶段判断 / 高可信交易辅助”的最低标准。

## 11. 最优先修复建议

P0：

1. 恢复技术包的新鲜价格、ATH 回撤、200D/200W、realized price / STH RP / LTH RP。
2. 恢复链上包的 LTH/STH SOPR、LTH net position、HODL 1Y+、profit/loss、exchange balance / net position。
3. 恢复宏观包的 M2、Fed balance sheet、Fed funds、US2Y、real yield、CPI/Core CPI。

P1：

1. 接入 stablecoin liquidity proxy。
2. 派生 net liquidity = Fed balance sheet - TGA - RRP。
3. 增加 halving phase / cycle age / cycle anchors。
4. 对 SOPR / CDD 增加长周期均值或 Z-score。

P2：

1. dormancy / liveliness。
2. realized cap HODL waves。
3. HODL waves 长期桶细分摘要。

## 12. 实际运行命令和结果

| 命令 | 结果 |
|---|---|
| `git status --short && git log -3 --oneline` | 确认当前 `HEAD=8d8473c`；存在遗留 `uv.lock` 修改，本轮未触碰。 |
| `rg ...` | 扫描 Layer A 数据包、数据源、collector、不可用因子、短线衍生品路径。 |
| `uv run python - <<'PY' ...` | 只读查询最新 Layer A run，生成 `/private/tmp/audit_layer_a_data_for_ai_precision/readonly_layer_a_data_scan.json`。 |
| `git diff --check` | 待提交前执行。 |

本轮仅报告改动，pytest 不适用。

## 13. 高风险区域确认

| 项目 | 结果 |
|---|---|
| 是否改 Layer A 逻辑 | 否 |
| 是否改 Layer B 逻辑 | 否 |
| 是否改 prompt | 否 |
| 是否改虚拟账户 | 否 |
| 是否改真实交易 | 否 |
| 是否跑完整 pipeline | 否 |
| 是否读取或输出 secret | 否 |
| 是否清空数据库 | 否 |

## 14. 删除清单 / 废弃清单

本轮是审计报告，无替代实现，无删除项。

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 无 | N/A | 本轮未删除代码或配置。 |

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A，本轮仅报告 |
| GitHub push | 待提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | N/A，本轮报告不需要重启 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | N/A |

## 16. 风险和未完成

1. 本轮读取的是本地 SQLite 最新 Layer A 快照；生产端最新快照可能不同。
2. 可用/缺失状态以最新快照为准，不代表接口永久不可用。
3. 下一步应专项排查为什么大量已接入字段在最新 run 中 `missing/stale`。
4. 本轮没有接入新数据，也没有改变 AI 裁决。

