# dual_layer_factor_inventory_and_data_source_audit

生成时间：2026-05-12  
任务性质：只读审计 + 报告归档  
结论摘要：本轮没有改交易代码、没有改 prompt、没有改配置、没有改网页、没有改数据库。只新增本报告，供后续 ChatGPT 建模双层结构使用。

## 1. 任务目标

本轮目标是给 BTC 中长线交易辅助系统做一次“因子和数据源盘点”。用小白话说，就是先把系统现在到底看了哪些数据、这些数据在哪里被用、哪些适合继续给当前波段仓用、哪些适合未来大周期现货策略用，整理成清单。

本轮审计围绕未来双层结构：

| 层 | 定位 | 本轮结论边界 |
|---|---|---|
| Layer A 大周期策略 / 现货仓策略 | 只判断 BTC 现货方向；不做空；不进虚拟账户；不使用 A/B/C 机会等级；输出“分批买入 / 强势买入 / 持有 / 分批卖出 / 强力卖出” | 本轮只盘点因子和接口，不设计 prompt，不实现代码 |
| Layer B 中长线波段仓 | 继续保持现有 L1-L5 + Master + Validator；虚拟账户只管理 Layer B；可多可空；保留 A/B/C/NONE | 本轮只审计，不改现有 UI 和核心逻辑 |

## 2. 本轮是否改代码

没有改代码，只读审计。

更准确地说：

- 没有改任何交易逻辑。
- 没有改 L1/L2/L3/L4/L5/Master prompt。
- 没有改 Validator。
- 没有改仓位、止损、止盈、开仓、平仓、反手规则。
- 没有改 scheduler。
- 没有改数据库 migration。
- 没有改网页。
- 没有读取或记录任何真实 API key / token / secret。
- 只新增本报告文件：`docs/codex_reports/dual_layer_factor_inventory_and_data_source_audit.md`。

## 3. 读取的关键文件

### 3.1 本轮按要求读取 / 审计的入口

| 文件 | 用途 |
|---|---|
| `AGENTS.md` | 项目规则、交易边界、当前真实运行口径 |
| `README.md` | 项目定位和系统说明 |
| `config/data_catalog.yaml` | 因子、数据源、历史删除项登记 |
| `config/data_sources.yaml` | 当前真实数据源配置 |
| `config/scheduler.yaml` | 当前采集和周复盘调度 |
| `config/schemas.yaml` | L1-L5、Master、Validator 输出 schema |
| `config/thresholds.yaml` | 当前规则阈值和历史删除注释 |
| `config/ai.yaml` | 当前 AI SDK 和模型配置 |
| `src/ai/context_builder.py` | L1-L5 输入上下文的真实组装逻辑 |
| `src/ai/master_input_builder.py` | Master 输入组装 |
| `src/ai/orchestrator.py` | L1-L5 + Master + Validator 执行顺序 |
| `src/ai/agents/prompts/l1_regime.txt` | L1 当前职责 |
| `src/ai/agents/prompts/l2_direction.txt` | L2 当前职责 |
| `src/ai/agents/prompts/l3_opportunity.txt` | L3 当前职责和 C 级语义 |
| `src/ai/agents/prompts/l4_risk.txt` | L4 风险和失效位职责 |
| `src/ai/agents/prompts/l5_macro.txt` | L5 宏观职责 |
| `src/ai/agents/prompts/master_adjudicator.txt` | Master 综合裁决职责 |
| `src/ai/validator.py` | Validator 约束和 C 级兼容点 |
| `src/data/collectors/glassnode.py` | Glassnode 当前 collector |
| `src/data/collectors/coinglass.py` | CoinGlass 当前 collector |
| `src/data/collectors/fred.py` | FRED 当前 collector |
| `src/data/collectors/derived_onchain.py` | LTH/STH MVRV 等派生链上指标 |
| `src/data/storage/schema.sql` | 当前 SQLite 表结构 |
| `src/data/storage/dao.py` | 真实入库和读取 DAO |
| `src/data/freshness.py` | 数据新鲜度和 stale 判断 |
| `src/evidence/` | 网页人读解释和证据卡片规则 |
| `src/pipeline/` | 当前 pipeline 与 orchestrator 接入 |
| `web/index.html` | 当前网页区域结构 |
| `web/assets/app.js` | 当前网页 helper 和展示逻辑 |
| `tests/test_web_modules_1_2_3.py` | 网页模块顺序测试 |
| `tests/test_web_modules_4_5_rp_failure.py` | Layer cards / thesis / 周复盘网页测试 |
| `tests/web_helpers/test_normalize_state.py` | 前端归一化测试 |

### 3.2 要求读取但本仓库当前不存在的文件

用户任务中列了两个路径，但当前仓库没有找到：

| 要求路径 | 当前状态 | 实际替代读取 |
|---|---|---|
| `src/data/models.py` | 未找到 | `src/data/storage/schema.sql`、`src/data/storage/dao.py` |
| `src/data/database.py` | 未找到 | `src/data/storage/connection.py`、`src/data/storage/dao.py` |

这表示项目现在的数据层实际在 `src/data/storage/` 下，而不是旧路径。

### 3.3 重点参考的历史报告

| 报告 | 本轮引用原因 |
|---|---|
| `docs/codex_reports/weekly_review_guardrail_and_ui_alignment.md` | 当前网页 footer 已改为 CoinGlass / Glassnode / FRED / local calendar |
| `docs/codex_reports/weekly_review_evidence_diagnostics.md` | 周复盘只读诊断边界 |
| `docs/codex_reports/weekly_review_temporal_consistency_and_confidence.md` | 周复盘时间连续性边界 |
| `docs/codex_reports/weekly_review_recommendation_canonicalization.md` | 周复盘建议 ID 结构化边界 |
| `docs/cc_reports/sprint_1_2_v2.md` | CoinGlass 衍生品早期接入历史 |
| `docs/cc_reports/sprint_1_3.md` | Glassnode 扩展历史，含 reserve risk / puell 历史 |
| `docs/cc_reports/sprint_1_7_factor_cleanup.md` | reserve risk / puell / SOPR 等删除纪律 |
| `docs/cc_reports/sprint_1_8_1_full.md` | basis / put-call / Yahoo gold 等退场历史 |
| `docs/cc_reports/sprint_1_6_v13_factors.md` | ETF flow / BTC dominance 接入历史 |
| `docs/cc_reports/sprint_2_6_f.md` | Glassnode proxy 和展示指标历史 |
| `docs/cc_reports/sprint_data_truthfulness_c_glassnode_retry_and_derived_stale.md` | Glassnode 新鲜度、重试和派生指标 stale 规则 |
| `docs/cc_reports/l3_b_grade_visibility_audit.md` | C 级机会展示和历史行为 |
| `docs/cc_reports/sprint_g_p0_thesis_persistence.md` | C 级不落 thesis 的真实持久化行为 |

## 4. 当前因子总表

下面这张表是“项目真实情况”的总表。这里的“已采集”不是猜的，而是按 collector、scheduler、DAO 和 context_builder 交叉确认。

### 4.1 技术 / 价格结构因子

| 因子 | 数据来源 | 当前采集 / 入库 | 当前使用位置 | 当前用途 | 新鲜度 / fallback | 分层建议 |
|---|---|---|---|---|---|---|
| BTC K 线 1h | CoinGlass | 已采集，入 `price_candles` | scheduler、DAO、虚拟订单触发、freshness fallback | 执行确认 / 挂单触发，不是 L1/L2 主读数 | freshness 里历史 source label 仍叫 `binance_kline`，但实际表是 `price_candles` | Layer B 执行辅助；Layer A 不建议主用 1h |
| BTC K 线 4h | CoinGlass | 已采集，入 `price_candles` | `context_builder.py`、L1/L2/L4/Master | 结构、趋势、失效位参考 | 有数据源 freshness 和 orchestrator factor grain 检查 | Layer B primary |
| BTC K 线 1d | CoinGlass | 已采集，入 `price_candles` | L1/L2/L4、factor cards、cycle_position | 趋势、波动率、周期位置 | 有 freshness | Layer A secondary；Layer B primary |
| BTC K 线 1w | CoinGlass | 已采集，入 `price_candles` | multi-timeframe alignment | 大级别方向参考 | 依赖 K 线采集 | Layer A secondary；Layer B context |
| EMA 20/50/200 1d | derived | 已派生 | `compute_emas_1d()`、L1/L2 | 趋势结构 | 派生自 K 线 | Layer B primary；Layer A secondary |
| EMA 20/50 4h | derived | 已派生 | `compute_emas_4h()`、L1/L2 | 中期节奏 | 派生自 K 线 | Layer B primary |
| MA 20/60/120/200 | derived / factor cards | 已派生展示 | `factor_card_emitter.py` | 展示和辅助审计 | 派生自 K 线 | Layer A secondary；Layer B context |
| ADX 14 | derived | 已派生 | `compute_adx_14()`、L1 prompt | 趋势强度 | 派生自 K 线 | Layer B primary |
| ATR 14 / ATR 180d percentile | derived | 已派生 | `compute_atr_features()`、L1/L4、factor cards | 波动率和风险 | 派生自 K 线 | Layer B primary；shared_risk |
| swing high / swing low | derived | 已派生 | `detect_swing_points()`、L1/L2/L4 | 结构高低点、支撑阻力 | 派生自 K 线 | Layer B primary |
| 支撑 / 阻力 / key levels | AI-derived + derived | 已由 L2/L4 输出 | L2、L4、Master | 入场和失效位语境 | 依赖 K 线 freshness | Layer B primary |
| range position / band position | derived / historical composite | 部分存在 | `context_builder.py`、历史 catalog | 位置感，不是当前唯一主信号 | 派生自 K 线 | Layer B context；Layer A secondary |
| trend / transition / phase | AI-derived | 已输出 | L1 regime、L2 phase | 当前 Layer B 方向和阶段判断 | 依赖 L1/L2 AI 输出 | Layer B primary，不直接迁移到 Layer A |
| max drawdown 60d | derived | 已派生 | `compute_price_features()`、L4 | 风险和价格状态 | 派生自 K 线 | shared_risk |
| ATH drawdown | derived / factor card | 已展示 | factor cards、cycle_position | 大周期位置 | 派生自 K 线 | Layer A primary/secondary；Layer B context |
| multi-timeframe alignment | derived | 已派生 | `compute_tf_alignment()`、factor cards | 4H/1D/1W 趋势一致性 | 派生自 K 线 | Layer B primary；Layer A secondary |

### 4.2 衍生品 / 市场结构因子

| 因子 | 数据来源 | 当前采集 / 入库 | 当前使用位置 | 当前用途 | 新鲜度 / fallback | 分层建议 |
|---|---|---|---|---|---|---|
| funding rate | CoinGlass | 已采集，入 `derivatives_snapshots` | `compute_funding_features()`、L2/L4、factor cards | 拥挤度和风险 | coinglass_derivatives freshness | Layer B primary；shared_risk；Layer A secondary |
| funding rate aggregated | CoinGlass | 已采集 | scheduler、factor cards | OI 加权 funding 参考 | 同上 | Layer B context；shared_risk |
| funding 90d zscore / 30d history | derived | 已派生 | L2/L4 context | 极端拥挤判断 | 依赖 funding | Layer B primary risk |
| open interest | CoinGlass | 已采集 | `compute_oi_features()`、L4、factor cards | 杠杆拥挤度 | coinglass_derivatives freshness | Layer B primary；shared_risk |
| OI 90d zscore / 30d history | derived | 已派生 | L4 | 风险判断 | 依赖 OI | Layer B primary risk |
| long / short ratio | CoinGlass | 已采集 | DAO alias、factor cards、context | 多空拥挤 | coinglass_derivatives freshness | Layer B primary；shared_risk |
| liquidation long/short/total | CoinGlass | 已采集 | DAO、factor cards、context | 清算压力参考 | coinglass_derivatives freshness | Layer B primary risk |
| net_position long/short | CoinGlass | collector 有；当前 scheduler 未纳入 `_DERIVATIVES_FETCHERS_1H` | `fetch_net_position_history()` | 候选市场结构因子 | collector_exists_not_scheduled | Layer B context；Layer A secondary，需先调度设计 |
| ETF flow | CoinGlass | 已采集，写入 `derivatives_snapshots.full_data_json` | `job_collect_klines_daily()`、`compute_macro_features()`、L5 prompt、factor cards | 资金流背景 | daily job 细粒度门检查 | Layer A primary/secondary；Layer B context |
| BTC dominance | CoinGlass | 已采集，写入 `full_data_json` | `compute_macro_features()`、L5 prompt、factor cards | 市场风格背景 | daily job 细粒度门检查 | Layer A secondary；Layer B context |
| futures basis / premium | 历史 Binance / CoinGlass 计划 | 当前未实现；历史已退场 / 残留注释 | data_catalog、thresholds 注释、legacy composite | 已退役候选 | 无当前 freshness | deprecated_candidate；若重启需重新设计 |
| put/call ratio | 历史计划 | 当前未实现；Sprint 1.8.1 退役 | data_catalog 注释、legacy composite 注释 | 已退役候选 | 无当前 freshness | deprecated_candidate |
| options OI / skew / IV | config 历史登记部分存在，但 collector 当前未实现 | 未采集 | data_catalog 历史项 | 候选 | 无 | missing_but_recommended 需高成本评估 |
| stablecoin supply / exchange flow | 未找到当前 CoinGlass collector 支持 | 未采集 | 无直接使用 | 候选 | 无 | Layer A secondary 候选，需要新增数据源或 collector |

### 4.3 链上因子

| 因子 | 数据来源 | 当前采集 / 入库 | 当前使用位置 | 当前用途 | 新鲜度 / fallback | 分层建议 |
|---|---|---|---|---|---|---|
| MVRV Z-Score | Glassnode | 已采集，入 `onchain_metrics` | `CyclePositionFactor`、factor cards | 周期位置核心因子 | glassnode_onchain 48h stale | Layer A primary；Layer B context |
| MVRV Ratio | Glassnode | 已采集 | factor cards、catalog | 周期估值参考 | glassnode freshness | Layer A primary/secondary；Layer B context |
| NUPL | Glassnode | 已采集 | `CyclePositionFactor`、factor cards | 周期盈利状态 | glassnode freshness | Layer A primary；Layer B context |
| realized price | Glassnode | 已采集 | factor cards | 周期成本参考 | glassnode freshness | Layer A primary；Layer B context |
| LTH realized price | Glassnode breakdown 聚合 | 已采集 / 派生 | collector、factor cards、derived LTH MVRV | 长持成本线 | glassnode freshness | Layer A primary；Layer B context |
| STH realized price | Glassnode breakdown 聚合 | 已采集 / 派生 | collector、factor cards、derived STH MVRV | 短持成本线 | glassnode freshness | Layer A primary；Layer B context |
| LTH supply | Glassnode | 已采集 | `CyclePositionFactor`、`compute_lth_sth_changes()` | 长持筹码变化 | glassnode freshness | Layer A primary；Layer B context |
| STH supply | Glassnode | 已采集 | `compute_lth_sth_changes()`、factor cards | 短持筹码变化 | glassnode freshness | Layer A primary；Layer B context |
| LTH supply 90d change | derived | 已派生 | `CyclePositionFactor`、L2 long_cycle_context | 周期位置 | 派生自 LTH supply | Layer A primary；Layer B context |
| exchange net flow | Glassnode | 已采集 | `compute_exchange_flow_features()`、L2/L4、factor cards | 交易所流入流出压力 | glassnode freshness | Layer A secondary；Layer B context/risk |
| exchange net flow 30d sum/max outflow | derived | 已派生 | L2/L4 context | 风险和结构确认 | 派生自 exchange net flow | shared_risk |
| aSOPR | Glassnode | 已采集，metric 为 `sopr_adjusted` | factor cards、catalog | 已实现但当前主要是展示/背景 | glassnode freshness | Layer A secondary；Layer B context |
| LTH SOPR | Glassnode catalog 有登记，collector 当前未实现 | 未采集 | data_catalog delayed | 候选 | 无 | Layer A secondary，需新增 collector |
| STH SOPR | Glassnode catalog 有登记，collector 当前未实现 | 未采集 | data_catalog delayed | 候选 | 无 | Layer A secondary，需新增 collector |
| HODL waves | Glassnode | 已采集，按 bucket 展开 | collector、factor cards | 持币年龄结构 | glassnode freshness | Layer A primary/secondary |
| CDD | Glassnode | 已采集 | collector、factor cards | 老币移动风险 | glassnode freshness | Layer A secondary |
| liveliness | Glassnode catalog 有登记，collector 当前未实现 | 未采集 | data_catalog delayed | 候选 | 无 | Layer A secondary，需新增 collector |
| SSR | Glassnode | 已采集 | collector、factor cards | 稳定币购买力参考 | glassnode freshness | Layer A secondary |
| hash ribbon | Glassnode catalog 有登记，collector 当前未实现 | 未采集 | data_catalog delayed | 候选 | 无 | Layer A secondary，需新增 collector，成本中高 |
| active addresses | Glassnode catalog 有登记，collector 当前未实现 | 未采集 | data_catalog delayed | 候选 | 无 | Layer A secondary，需新增 collector |
| reserve risk | 历史 Glassnode | 已删除，当前 collector 无方法 | 历史报告、删除注释 | 退役候选 | 无 | deprecated_candidate；如重启需重新论证 |
| puell multiple | 历史 Glassnode | 已删除，当前 collector 无方法 | 历史报告、删除注释 | 退役候选 | 无 | deprecated_candidate；如重启需重新论证 |
| RHODL ratio | 未找到 | 未采集 | 无 | Layer A 候选 | 无 | missing_but_recommended |
| percent supply in profit/loss | 未找到 | 未采集 | 无 | Layer A 候选 | 无 | missing_but_recommended |
| market cap / realized cap | 未找到直接 collector；MVRV 间接用到概念 | 未采集为独立指标 | 无直接使用 | Layer A 候选 | 无 | missing_but_recommended |
| LTH/STH MVRV | derived | 已派生 | `derived_onchain.py`、factor cards | 长短持估值 | 依赖 price + realized price | Layer A primary/secondary；Layer B context |

### 4.4 宏观因子

| 因子 | 数据来源 | 当前采集 / 入库 | 当前使用位置 | 当前用途 | 新鲜度 / fallback | 分层建议 |
|---|---|---|---|---|---|---|
| DXY proxy / broad dollar | FRED `DTWEXBGS` | 已采集，metric `dxy` | `compute_macro_features()`、L5 prompt、factor cards | 美元压力 | fred_macro 72h stale | Layer A secondary；Layer B context/risk |
| US10Y / 10Y Treasury Yield | FRED `DGS10`，alias `us10y` | 已采集 | `compute_macro_features()`、L5 prompt、factor cards | 利率压力 | fred freshness | Layer A secondary；Layer B context/risk |
| VIX | FRED `VIXCLS` | 已采集 | L5 prompt、factor cards | 风险偏好 | fred freshness | shared_risk |
| Nasdaq | FRED `NASDAQCOM` | 已采集 | L5 prompt、BTC-Nasdaq corr | 风险资产联动 | fred freshness | Layer A secondary；Layer B context |
| BTC-Nasdaq 60d corr | derived | 已派生 | `compute_btc_macro_corr_60d()`、factor cards | 风险资产相关性 | 依赖 BTC + Nasdaq | Layer B context；Layer A secondary |
| US2Y | `context_builder.py` 支持字段，但 FRED collector 未实现 | 未采集 | L5 prompt 期望可用 | yield curve 候选 | 无 | missing_but_recommended，新增 FRED series 成本低 |
| 2Y-10Y yield curve | derived | 代码支持但缺 US2Y 数据 | `compute_macro_features()` | 宏观压力候选 | 数据缺口 | Layer A secondary；Layer B context |
| Fed Funds Rate | 历史删除 / 当前未实现 | 未采集 | 历史报告提过 DFF 删除 | 候选 | 无 | Layer A secondary，低成本新增 FRED series |
| CPI / Core CPI | 当前未采集；local event calendar 有 CPI 事件日期 | 部分：只有事件，不是数值 | events calendar、L5 event risk | 宏观事件风险 | local calendar | Layer A secondary；shared_risk |
| unemployment | 当前未采集 | 未采集 | 历史删除 | 候选 | 无 | Layer A secondary，低成本新增 FRED series |
| M2 / global liquidity | `context_builder.py` 支持字段名，但 collector 未实现 | 未采集 | L5 prompt 期望字段 | 流动性候选 | 无 | Layer A primary/secondary 候选，需新增 collector |
| Fed balance sheet | context 支持字段名，但 collector 未实现 | 未采集 | L5 prompt 期望字段 | 流动性候选 | 无 | Layer A secondary，需新增 FRED series |
| ETF flow | CoinGlass | 已采集 | L5 prompt、factor cards | 资金流 | daily CoinGlass job | Layer A primary/secondary；Layer B context |
| BTC dominance | CoinGlass | 已采集 | L5 prompt、factor cards | 市场风格 | daily CoinGlass job | Layer A secondary；Layer B context |
| macro event calendar | local calendar | 已入 `events_calendar` | L5 prompt、event risk、factor cards | 事件风险 | local config / DB | shared_risk |

### 4.5 AI 派生因子

| 因子 | 数据来源 | 当前采集 / 入库 | 当前使用位置 | 当前用途 | 分层建议 |
|---|---|---|---|---|---|
| L1 regime / volatility | AI-derived | `strategy_runs.full_state_json` | L1 prompt、orchestrator、web | 市场结构和波动状态 | Layer B primary |
| L2 direction / phase / long cycle context | AI-derived + cycle_position | `full_state_json` | L2 prompt、Master、web | 方向、阶段、关键位、周期背景 | Layer B primary；Layer A 不应直接复用其 A/B/C 体系 |
| L3 opportunity_grade | AI-derived | `full_state_json` | L3 prompt、Master、Validator、thesis persistence | A/B/C/NONE 机会等级 | Layer B primary，仅 Layer B |
| L3 execution_permission | AI-derived | `full_state_json` | L3 prompt、Validator | 是否允许开仓 / 观察 / 伏击 | Layer B primary，仅 Layer B |
| L3 anti_pattern_signals | AI-derived | `full_state_json`、weekly review diagnostics | 反追涨 / 反低位乱接 | Layer B primary risk |
| L4 risk_tier / risk_score | AI-derived | `full_state_json` | L4 prompt、Master、weekly review | 风险等级 | Layer B primary；shared_risk 观察 |
| L4 hard_invalidation_levels | AI-derived but constrained | `full_state_json` | Master stop_loss 唯一来源、Validator | 失效位 / 止损候选 | Layer B hard constraint，不给 Layer A 直接用 |
| L4 position_cap_multiplier | AI-derived | `full_state_json` | Master / Validator / weekly review | 仓位上限风险修正 | Layer B primary risk |
| L5 macro stance / warnings | AI-derived | `full_state_json` | Master、web | 宏观顺风/逆风 | Layer B context/risk；Layer A 可重新建一套宏观输入 |
| Master decision / thesis / trade_plan | AI-derived | `strategy_runs`、thesis tables | thesis、virtual orders、virtual account | Layer B 最终裁决 | Layer B only |
| Validator activations | rule-derived | `constraint_activations_json` | weekly review、alert、web | 硬约束审计 | Layer B safety/audit |

## 5. 当前 Layer B L1-L5 实际职能

### 5.1 L1 当前在判断什么

L1 是“市场结构层”。它不负责说买还是卖，只判断 BTC 当前是不是趋势清晰、震荡、转换、波动率高低等。

主要依据：

- 1D / 4H / 1W K 线结构；
- EMA 20/50/200；
- swing high / swing low；
- ADX；
- ATR / 波动率分位；
- 多周期一致性。

对交易系统的意义：L1 是 Layer B 后续判断的“地形图”，告诉系统现在是趋势路、震荡路，还是容易出假信号的路。

### 5.2 L2 当前在判断什么

L2 是“方向和阶段层”。它会判断偏多、偏空还是中性，也会判断当前处在 early / mid / late / exhausted 等阶段。

主要依据：

- L1 市场结构；
- 4H / 1D 趋势；
- key support / resistance；
- LTH/STH supply；
- LTH/STH realized price；
- exchange net flow；
- funding；
- cycle_position。

对交易系统的意义：L2 决定 Layer B 是在顺趋势找机会，还是应该防追高、防追空。

### 5.3 L3 当前在判断什么

L3 是“机会等级层”，是 A/B/C/NONE 的唯一权威来源。

L3 负责：

- `opportunity_grade`：A/B/C/none；
- `execution_permission`：例如 allow / cautious_open / ambush_only / watch；
- `anti_pattern_signals`：例如 late phase、追突破、关键阻力失败等。

L3 不负责：

- 不负责 entry_zone；
- 不负责 stop_loss；
- 不负责 take_profit；
- 不负责创建 thesis；
- 不负责虚拟账户。

对交易系统的意义：L3 是 Layer B 的“有没有值得做的波段机会”的评分器。

### 5.4 L4 当前在判断什么

L4 是“风险层”。它负责 risk_score、risk_tier、risk_breakdown、position_cap_multiplier，以及 hard_invalidation_levels。

特别重要：`hard_invalidation_levels` 是止损 / 失效位的唯一来源，Master 不能自己凭空发明止损价。

对交易系统的意义：L4 是 Layer B 的“刹车系统”，即使 L3 觉得机会好，L4 也可以通过风险等级和仓位上限让系统保守。

### 5.5 L5 当前在判断什么

L5 是“宏观和事件层”。它负责宏观顺风/逆风、极端事件、重大数据窗口、ETF flow、BTC dominance、DXY、利率、VIX、Nasdaq 等。

对交易系统的意义：L5 不直接决定买卖，但会告诉 Master：现在外部环境是在帮忙，还是在添堵。

### 5.6 Master 当前怎么综合

Master 是 Layer B 的“总裁决”。它读取 L1-L5 输出、active thesis、虚拟仓位、挂单、冷却期、熔断状态，然后决定：

- `new_thesis`：创建新 thesis；
- `evaluate_existing`：评估已有 thesis；
- `silent_cooldown`：冷却或观望；
- 其他保护态。

Master 不能改 L3 grade，不能自创 stop_loss，不能绕开 active thesis 主线锁。

### 5.7 Validator 当前怎么约束

Validator 是硬约束层，负责阻止 Master 违反交易纪律。典型约束包括：

- stop_loss 必须来自 L4 hard_invalidation_levels；
- 仓位不能超过 position cap；
- Master grade 必须等于 L3 grade；
- active thesis 存在时不能直接开新 thesis；
- break_conditions 必须客观；
- what_would_change_mind 和 conflict_resolution 必须结构化输出；
- 记录 constraint activations 供周复盘审计。

对小白说：Validator 就像“最后一道风控闸门”，AI 说得再漂亮，违反硬规则也不能放行。

### 5.8 哪些地方体现了右侧趋势倾向

当前 Layer B 的右侧趋势倾向主要体现在：

- L1 看趋势结构、ADX、EMA、多周期一致性；
- L2 判断 phase，只有结构更清楚时方向信号更可靠；
- L3 对 early/mid trend 的机会更友好，对 late/exhausted 更谨慎；
- Master 在无 active thesis 且 L3 有 A/B/C 机会时倾向不要“软抗拒”；
- Validator 有 soft resistance 识别，防止 Master 在有机会时一直逃避输出。

这也是为什么系统可能在低位不急着给机会，而等趋势站稳后才给 B 级多。

### 5.9 哪些地方有反追涨机制

反追涨 / 反追空机制主要在：

- L2 的 late / exhausted phase；
- L3 的 anti_pattern_signals；
- L3 的 `chasing_breakout_no_pullback`、`extending_late_phase`、`failing_at_resistance` 等逻辑；
- L4 的 elevated / extreme risk；
- L4 的 position cap multiplier；
- Master 对 C 级机会的 ambush-only 语义；
- Validator 对 grade/permission、position cap、stop_loss 来源的硬约束。

### 5.10 哪些地方支持做空

Layer B 当前支持做空，证据包括：

- L2 可以输出 bearish stance；
- L3 prompt 支持 bearish A/B/none；
- Master prompt 支持 direction = long / short；
- 虚拟账户代码里有 long / short 两套虚拟仓位；
- thesis 和 virtual order 体系支持方向字段。

注意：未来 Layer A 明确不做空，所以不能直接复用 Layer B 的 short 语义。

### 5.11 哪些地方会导致“低位 NONE，高位 B 级多”的行为

这种现象不一定是 bug，可能来自当前 Layer B 的右侧确认设计：

- 低位时结构还没确认，L1/L2 可能仍判断为弱势、震荡或转换；
- 低位时 L3 可能把机会评为 NONE，因为还没有形成可审计的趋势机会；
- 价格涨起来后，EMA、ADX、多周期一致性和 phase 变好，L3 才给 B；
- 如果上涨已经太晚，L3 又可能触发 late phase 反模式；
- 所以系统不是“抄底系统”，更像“等结构确认后的波段系统”。

对后续 Layer A 的启示：Layer A 如果要做大周期现货分批买入，不能简单拿 Layer B 的 A/B/C grade，因为 Layer B 本来就偏右侧。

### 5.12 C 级机会当前语义是否一致

结论：当前 C 级机会存在语义不一致，需要下一步建模先确认，不建议直接迁移到 Layer A。

证据：

| 位置 | 当前语义 |
|---|---|
| `src/ai/agents/prompts/master_adjudicator.txt` | 写着 L3 grade in A/B/C 时可以 `new_thesis`，C 级倾向 ambush-only |
| `src/ai/validator.py` | C grade 合法 permission 包括 `ambush_only`；V21 软抗拒逻辑也把 A/B/C 视为可能需要 new_thesis |
| `src/strategy/thesis_persistence.py` | `_ALLOWED_GRADES = ("A", "B")`，实际只允许 A/B 落 thesis |
| `docs/cc_reports/sprint_g_p0_thesis_persistence.md` | 记录 C grade 是观察，不创建 thesis |
| `docs/cc_reports/l3_b_grade_visibility_audit.md` | 近期 C 级样本多为 `permission=watch`，网页展示但不落 thesis |

小白版解释：文档和部分 prompt 像是说“C 也可能建观察型 thesis”，但真实持久化代码只让 A/B 创建 thesis。这不是本轮要修的问题，但做 Layer A 之前必须先定清楚。

## 6. 因子当前使用位置

这一节把“因子在哪里被用”按模块归类。

### 6.1 context_builder

`src/ai/context_builder.py` 是当前 L1-L5 输入的核心组装器。

| 函数 / 区域 | 使用因子 |
|---|---|
| `build_full_context()` | K 线、衍生品、链上、宏观、事件、freshness |
| `compute_emas_1d()` | EMA 20/50/200 |
| `compute_emas_4h()` | EMA 20/50 |
| `compute_tf_alignment()` | 4H/1D/1W EMA20 斜率一致性 |
| `compute_adx_14()` | ADX |
| `compute_atr_features()` | ATR、ATR/price、ATR 180d percentile |
| `detect_swing_points()` | swing high / swing low |
| `compute_lth_sth_changes()` | LTH/STH supply、LTH/STH realized price |
| `compute_exchange_flow_features()` | exchange net flow |
| `compute_funding_features()` | funding current、90d zscore、30d history |
| `compute_oi_features()` | OI current、90d zscore、30d history |
| `compute_price_features()` | close、60d max drawdown、EMA50 slope |
| `compute_macro_features()` | DXY、US10Y、US2Y、VIX、Nasdaq、M2、Fed balance sheet、BTC dominance、ETF flow |
| `compute_btc_macro_corr_60d()` | BTC 与 Nasdaq 相关性 |

### 6.2 evidence

| 文件 | 当前用途 |
|---|---|
| `src/evidence/pillars.py` | 把 L1-L5 和 Master 输出转成人读审计卡片 |
| `src/evidence/plain_reading.py` | 规则化中文解释，不让 AI 自由写网页解释 |
| `src/evidence/_anti_patterns.py` | 历史 / legacy 反模式扫描器，当前主要作为旧路径或参考 |

### 6.3 L1-L5 prompt

| 层 | 使用因子 |
|---|---|
| L1 | K 线结构、EMA、swing、ADX、ATR、volatility |
| L2 | L1、K 线结构、phase、key levels、LTH/STH、exchange flow、funding、cycle_position |
| L3 | L1/L2、phase、opportunity、execution_permission、anti-pattern、risk_preview |
| L4 | L1/L2/L3、funding、OI、exchange flow、LTH supply、drawdown、hard invalidation |
| L5 | DXY、US10Y、US2Y、yield curve、VIX、Nasdaq、M2、Fed balance sheet、BTC dominance、ETF flow、event calendar |
| Master | L1-L5 输出、active thesis、虚拟账户、挂单、cooldown、fuse、data freshness |

### 6.4 weekly review

周复盘主要使用 AI 派生结果和历史 `strategy_runs`：

- L3 anti_pattern_signals；
- L4 risk_tier / risk_score / risk_breakdown；
- Validator activations；
- Master trade_plan；
- strategy_quality；
- temporal diagnostics；
- recommendation recurrence。

它不应该自动改策略参数。

### 6.5 web

| 网页区域 | 文件 | 当前展示 |
|---|---|---|
| AI 策略建议 | `web/index.html`、`web/assets/app.js` | Master / thesis 总结 |
| Layer cards | `region-layer-cards` + app.js helpers | L1/L2/L3/L4/L5/Master 六张审计卡 |
| Raw factor cards | `region-4` + `factorGroups()` | 技术、衍生品、链上、宏观、事件因子 |
| Weekly review | `region-weekly-review` | 周复盘、诊断、建议 |

## 7. Layer A / Layer B 因子分层建议

注意：这里是“建模建议”，不是本轮实现。

### 7.1 建议作为 Layer A primary 的因子

Layer A 是大周期现货策略，适合更多使用周期估值、链上筹码、宏观流动性和大级别价格位置。

| 因子 | 原因 | 当前状态 |
|---|---|---|
| MVRV Z-Score | 大周期估值温度计 | 已采集 |
| MVRV Ratio | 估值高低参考 | 已采集 |
| NUPL | 全网盈利状态 | 已采集 |
| Realized Price | 全网成本中枢 | 已采集 |
| LTH realized price | 长持成本线 | 已采集 |
| STH realized price | 短持成本线 | 已采集 |
| LTH supply / 90d change | 长持筹码是否增加 | 已采集 / 已派生 |
| STH supply | 短持筹码结构 | 已采集 |
| HODL waves | 持币年龄结构 | 已采集 |
| LTH/STH MVRV | 长短持估值差异 | 已派生 |
| ATH drawdown | 大周期位置 | 已派生 / 展示 |
| ETF flow | 现货资金流 | 已采集 |
| DXY / US10Y / VIX / Nasdaq | 宏观压力和风险偏好 | 已采集 |
| macro event calendar | 重大事件风险 | 已接入 local calendar |

### 7.2 建议作为 Layer A secondary 的因子

| 因子 | 原因 | 当前状态 |
|---|---|---|
| aSOPR | 盈利卖压 / 花费行为 | 已采集 |
| CDD | 老币移动 | 已采集 |
| SSR | 稳定币购买力背景 | 已采集 |
| BTC dominance | 市场风格 | 已采集 |
| funding / OI / long-short ratio | 现货大周期不应过度依赖，但可识别过热 | 已采集 |
| liquidation | 极端风险背景 | 已采集 |
| BTC-Nasdaq correlation | 风险资产联动 | 已派生 |
| weekly / daily MA / EMA | 大周期趋势过滤 | 已派生 |

### 7.3 建议继续作为 Layer B primary 的因子

| 因子 | 原因 |
|---|---|
| 4H / 1D K 线结构 | 波段仓主战场 |
| EMA / ADX / ATR / swing | 当前 L1/L2/L4 核心输入 |
| L2 stance / phase / key levels | Layer B 方向和阶段核心 |
| L3 opportunity_grade / execution_permission | Layer B 机会等级唯一权威 |
| L3 anti_pattern_signals | 防追涨、防低位乱接 |
| L4 risk_tier / hard_invalidation_levels | 风控和失效位核心 |
| funding / OI / LSR / liquidation | 波段仓拥挤度和风险核心 |
| exchange net flow | 短中期风险和筹码流动参考 |
| L5 macro warnings | 波段仓背景风险 |
| Master + Validator | Layer B 最终裁决和安全闸门 |

### 7.4 建议作为 Layer B background / context 的因子

| 因子 | 原因 |
|---|---|
| MVRV-Z / NUPL / LTH supply | 适合告诉 Layer B 大周期位置，但不直接替代波段结构 |
| HODL waves / CDD / SSR / aSOPR | 适合背景和风险提示，不宜单独决定波段开仓 |
| ETF flow / BTC dominance | 可作为 L5 或背景，不宜替代 L3 grade |
| DXY / US10Y / VIX / Nasdaq | 宏观背景和风控，不直接给 A/B/C |
| weekly MA / ATH drawdown | 大背景，不直接替代 4H/1D 结构 |

### 7.5 shared_risk 因子

| 因子 | 说明 |
|---|---|
| funding 极端值 | Layer B 仓位和追涨风险；Layer A 也可用作过热提示 |
| OI 极端值 | 杠杆堆积风险 |
| liquidation | 波动放大风险 |
| VIX / DXY / US10Y | 宏观风险 |
| event calendar | FOMC、CPI、NFP 等事件窗口 |
| L4 risk_tier | Layer B 内部风险；Layer A 不应直接复用，但可参考其风险解释 |

### 7.6 deprecated_candidate

| 因子 | 当前状态 | 原因 |
|---|---|---|
| reserve risk | 已删除 | 历史报告写明“噪音因子，无 L 层引用” |
| puell multiple | 已删除 | 同上 |
| raw SOPR | 已删除 | aSOPR 替代 |
| put/call ratio | 已退役 | 数据源不稳定，历史删除 |
| basis_annualized | 已退役 / 残留 legacy 注释 | 当前 collector 未实现 |
| Yahoo macro / Yahoo gold | 已退场 | 当前真实口径为 CoinGlass / Glassnode / FRED |

### 7.7 missing_but_recommended

这些是 Layer A 可能有价值，但项目当前没接上的候选：

- RHODL Ratio；
- Percent Supply in Profit / Loss；
- LTH SOPR / STH SOPR；
- Liveliness；
- Hash Ribbon；
- Active Addresses；
- Exchange Balance；
- LTH Net Position Change；
- Exchange Net Position Change；
- Fed Funds Rate；
- US2Y；
- Real Yield；
- CPI / Core CPI 数值；
- Unemployment；
- M2 / global liquidity；
- Fed balance sheet；
- Options IV / skew。

## 8. Layer A 新增候选因子接口审计

### 8.1 Glassnode 候选

| candidate_name | preferred_source | project_status | code_evidence | likely_layer | implementation_effort | notes |
|---|---|---|---|---|---|---|
| MVRV Z-Score | Glassnode | already_collected | `GlassnodeCollector.fetch_mvrv_z_score()`、`_GLASSNODE_FETCHERS`、`onchain_metrics.metric_name=mvrv_z_score` | Layer A primary | none | 已可直接用于 Layer A 建模输入 |
| MVRV Ratio | Glassnode | already_collected | `fetch_mvrv()`、scheduler `_GLASSNODE_FETCHERS` | Layer A primary/secondary | none | 当前主要展示/背景 |
| NUPL | Glassnode | already_collected | `fetch_nupl()`、`CyclePositionFactor` | Layer A primary | none | 当前已进 cycle_position |
| Realized Price | Glassnode | already_collected | `fetch_realized_price()` | Layer A primary | none | 当前展示/背景 |
| LTH SOPR | Glassnode | config_only | `config/data_catalog.yaml` 有 delayed 登记；collector 无 fetch 方法 | Layer A secondary | medium | 需要新增 collector 和调度 |
| STH SOPR | Glassnode | config_only | data_catalog 有 delayed 登记；collector 无 fetch 方法 | Layer A secondary | medium | 同上 |
| aSOPR | Glassnode | already_collected | `fetch_sopr_adjusted()`、metric `sopr_adjusted` | Layer A secondary | none | raw SOPR 已删除，aSOPR 是当前实现 |
| RHODL Ratio | Glassnode | not_found | 未在 collector / scheduler / catalog 当前有效项找到 | Layer A primary/secondary | medium | 需新增接口并确认 proxy 支持 |
| Reserve Risk | Glassnode | not_found / deprecated_candidate | `glassnode.py` 注释：Sprint 1.7 删除；历史报告说明噪音因子 | Layer A secondary 候选 | medium | 若重启，需先证明对 Layer A 有价值 |
| Puell Multiple | Glassnode | not_found / deprecated_candidate | 同 reserve risk | Layer A secondary 候选 | medium | 历史已删除，不建议直接恢复 |
| Percent Supply in Profit | Glassnode | not_found | 未找到 collector / config 有效项 | Layer A primary | medium | 需新增接口 |
| Percent Supply in Loss | Glassnode | not_found | 未找到 | Layer A primary | medium | 需新增接口 |
| LTH Supply | Glassnode | already_collected | `fetch_lth_supply()`、`CyclePositionFactor` | Layer A primary | none | 已有 |
| STH Supply | Glassnode | already_collected | `fetch_sth_supply()` | Layer A primary | none | 已有 |
| LTH Net Position Change | Glassnode | not_found | 当前只计算 LTH supply pct change，不是 net position change | Layer A primary/secondary | medium | 需新增指标定义 |
| Exchange Net Position Change | Glassnode | not_found | 当前有 `exchange_net_flow`，没有 exchange balance/net position change | Layer A secondary | medium | 需区分 flow 与 position change |
| Exchange Balance | Glassnode | not_found | 未找到 | Layer A secondary | medium | 可作为 exchange netflow 的补充 |
| HODL Waves | Glassnode | already_collected | `fetch_hodl_waves()`、bucket 展开 | Layer A primary/secondary | none | 已有 |
| Coin Days Destroyed | Glassnode | already_collected | `fetch_cdd()` | Layer A secondary | none | 已有 |
| Liveliness | Glassnode | config_only | data_catalog 有 delayed 登记；collector 无方法 | Layer A secondary | medium | 需新增 collector |
| SSR | Glassnode | already_collected | `fetch_ssr()` | Layer A secondary | none | 已有 |
| Hash Ribbon | Glassnode | config_only | data_catalog 有 delayed 登记；collector 无方法 | Layer A secondary | medium/high | 可能需要多序列或派生逻辑 |
| Market Cap / Realized Cap | Glassnode | not_found | 未找到独立 collector；MVRV 间接表达二者关系 | Layer A primary/secondary | medium | 若要绝对值，需新增 |
| Short-Term Holder Realized Price | Glassnode | already_collected | `fetch_sth_realized_price()` 通过 breakdown 聚合 | Layer A primary | none | 已有 |
| Long-Term Holder Realized Price | Glassnode | already_collected | `fetch_lth_realized_price()` 通过 breakdown 聚合 | Layer A primary | none | 已有 |

### 8.2 CoinGlass 候选

| candidate_name | preferred_source | project_status | code_evidence | likely_layer | implementation_effort | notes |
|---|---|---|---|---|---|---|
| Funding Rate | CoinGlass | already_collected | `fetch_funding_rate_history()`、`_DERIVATIVES_FETCHERS_1H`、`DerivativesDAO` | Layer B primary / shared risk | none | Layer A 可做过热背景 |
| Open Interest | CoinGlass | already_collected | `fetch_open_interest_history()`、scheduler | Layer B primary / shared risk | none | 已有 |
| Liquidation Heatmap / Levels | CoinGlass | not_found | 当前只有 `fetch_liquidation_history()`，未找到 heatmap / levels | shared risk | high | “清算历史”不等于“清算热力图” |
| Long/Short Ratio | CoinGlass | already_collected | `fetch_long_short_ratio_history()` | Layer B primary / shared risk | none | 已有 |
| ETF Flow | CoinGlass | already_collected | `fetch_etf_flow_history()`、daily job、`compute_macro_features()` | Layer A primary/secondary | none | 已有 |
| Futures Basis / Premium | CoinGlass | not_found / deprecated_candidate | data_catalog 历史删除；collector 当前无 fetch_basis | Layer B context 候选 | medium | 历史实现不等于当前可用 |
| Options Skew / IV | CoinGlass / options source | not_found | 未找到 collector | shared risk 候选 | high | 需要新增外部数据源设计 |
| Stablecoin Supply / Exchange Flow | CoinGlass 或其他源 | not_found | 未找到当前 collector | Layer A secondary | high | Glassnode SSR 已有，但不是 stablecoin supply |
| BTC Dominance | CoinGlass | already_collected | `fetch_btc_dominance()`、daily job | Layer A secondary | none | 已有 |
| Net Position | CoinGlass | collector_exists_not_scheduled | `fetch_net_position_history()` 存在；scheduler 未纳入当前 derivatives fetchers | Layer B context / Layer A secondary | low/medium | 需要先明确是否调度和如何展示 |

### 8.3 FRED / Macro 候选

| candidate_name | preferred_source | project_status | code_evidence | likely_layer | implementation_effort | notes |
|---|---|---|---|---|---|---|
| Fed Funds Rate | FRED | not_found / historical_removed | 当前 `FredCollector.SERIES` 无 DFF | Layer A secondary | low | 历史删除过，如重启需加 series 和测试 |
| 10Y Treasury Yield | FRED | already_collected | `SERIES["dgs10"]`，alias `us10y` | Layer A secondary / shared risk | none | 已有 |
| 2Y Treasury Yield | FRED | not_found | context 支持 `us2y`，collector 未采集 | Layer A secondary | low | 新增 FRED series 成本较低 |
| Real Yield | FRED | not_found | 未找到 TIPS real yield series | Layer A secondary | low/medium | 需确定 series code |
| CPI / Core CPI | FRED + local calendar | partial | local event calendar 有 CPI 事件；collector 无 CPI 数值 | shared risk / Layer A secondary | low/medium | 事件和数值是两回事 |
| Unemployment | FRED | not_found / historical_removed | 当前 collector 无 unemployment | Layer A secondary | low | 历史删除过，需重新评估 |
| Liquidity proxy | FRED / other | not_found | context 支持 `m2/global_m2/fed_balance_sheet`，collector 未采集 | Layer A primary/secondary | medium | 数据字段预留不等于已接入 |
| DXY proxy | FRED | already_collected | `DTWEXBGS -> dxy` | Layer A secondary / shared risk | none | 已有 |
| M2 / global liquidity | FRED / other | not_found | collector 无 | Layer A primary/secondary | medium | 需要新增 series 或外部源 |
| Risk event calendar | local calendar | already_collected | `events_calendar`、L5 prompt、factor cards | shared risk | none/low | 当前走 local calendar，不是 FRED |

## 9. Glassnode / CoinGlass / FRED 支持情况

### 9.1 Glassnode

当前已支持并调度：

- `mvrv_z_score`
- `nupl`
- `lth_supply`
- `exchange_net_flow`
- `mvrv`
- `realized_price`
- `lth_realized_price`
- `sth_realized_price`
- `sopr_adjusted` / aSOPR
- `sth_supply`
- `ssr`
- `cdd`
- `hodl_waves`
- `lth_mvrv` / `sth_mvrv` 派生

当前只有配置 / 历史登记、collector 未实现或未调度：

- LTH SOPR；
- STH SOPR；
- active addresses；
- liveliness；
- hash ribbon。

当前已删除或不建议直接恢复：

- raw SOPR；
- reserve risk；
- puell multiple。

### 9.2 CoinGlass

当前已支持并调度：

- BTC K 线 1h / 4h / 1d / 1w；
- funding rate；
- funding rate aggregated；
- open interest；
- long/short ratio；
- liquidation history；
- ETF flow；
- BTC dominance。

collector 有但当前 scheduler 未纳入本轮确认的定时抓取：

- net position long/short。

未找到当前实现：

- liquidation heatmap / liquidation levels；
- futures basis / premium；
- options skew / IV；
- stablecoin supply / exchange flow。

### 9.3 FRED

当前已支持：

- DGS10 / US10Y；
- NASDAQCOM / Nasdaq；
- VIXCLS / VIX；
- DTWEXBGS / DXY proxy。

当前未支持：

- Fed Funds Rate；
- US2Y；
- real yield；
- CPI / Core CPI 数值；
- unemployment；
- M2；
- global liquidity；
- Fed balance sheet。

## 10. C 级机会当前语义是否一致

结论：不完全一致。

小白版解释：系统里有些地方把 C 级当成“很弱但可观察的伏击机会”，有些地方像是允许 C 级建 thesis，但真实落库代码只允许 A/B 创建 thesis。所以，C 级现在更接近“展示和观察”，不是稳定的“可执行建仓等级”。

关键证据：

| 文件 / 报告 | 证据 |
|---|---|
| `src/ai/agents/prompts/l3_opportunity.txt` | C 级是低质量机会，通常偏观察 |
| `src/ai/agents/prompts/master_adjudicator.txt` | A/B/C 都可能触发 new_thesis，C 倾向 ambush-only |
| `src/ai/validator.py` | C + ambush_only 在约束中是合法组合 |
| `src/strategy/thesis_persistence.py` | `_ALLOWED_GRADES = ("A", "B")`，实际只允许 A/B 落 thesis |
| `docs/cc_reports/sprint_g_p0_thesis_persistence.md` | C grade observation，不创建 thesis |
| `docs/cc_reports/l3_b_grade_visibility_audit.md` | C 级近期样本多为 watch |

下一步建模建议：在做 Layer A 前，先单独做一次“C 级语义裁决”。不要把 C 级迁移到 Layer A，因为 Layer A 本来就不使用 A/B/C。

## 11. 网页新增“大周期策略”模块建议

本轮不改网页，只给后续设计建议。

### 11.1 当前 Layer B 五层分析展示在哪些文件中实现

| 位置 | 当前作用 |
|---|---|
| `web/index.html` 的 `region-layer-cards` | L1/L2/L3/L4/L5/Master 六张审计卡容器 |
| `web/assets/app.js` 的 layer card helpers | 渲染六层卡片、badge、字段、人读摘要 |
| `src/evidence/pillars.py` | 后端规则化生成卡片结构 |
| `src/evidence/plain_reading.py` | 后端规则化中文解释 |
| `tests/web_helpers/test_normalize_state.py` | 验证 layer cards 数量和顺序 |

### 11.2 当前卡片样式、字体、badge、布局如何复用

建议复用：

- `audit-card`；
- 小号标题 + badge；
- 现有 `stat-label` / `stat-value`；
- 折叠 / 展开方式；
- 紧凑布局，不做复杂图表；
- 保持中文规则化解释，不展示原始 JSON。

### 11.3 新增“大周期策略”模块应放在哪里

建议位置：放在 AI 策略建议总览之后、Layer B 五层卡片之前。

理由：

- Layer A 是独立于虚拟账户的大周期现货策略，不应该塞进 Layer B 虚拟账户区域；
- 放在 Layer B 卡片之前，用户可以先看“大周期背景”，再看“波段仓具体机会”；
- 不改变现有 Layer B 卡片的顺序和含义。

### 11.4 哪些 helper 可以复用

可以复用：

- badge 渲染 helper；
- percent / price 格式化 helper；
- card field row helper；
- collapse section helper；
- 空数据 fallback 文案；
- 模块顺序测试思路。

不要复用：

- L3 A/B/C grade helper；
- Layer B thesis / virtual account helper；
- short direction 的展示语义。

### 11.5 哪些测试需要扩展

建议后续扩展：

- `tests/test_web_modules_1_2_3.py`：确认 Layer A 模块位置不破坏现有模块顺序；
- `tests/test_web_modules_4_5_rp_failure.py`：确认 Layer B cards、thesis timeline、weekly review 位置不变；
- `tests/web_helpers/test_normalize_state.py`：增加 Layer A state 兼容测试；
- 如果新增后端规则化人读解释，增加对应 evidence helper 测试。

## 12. 风险和不确定项

| 风险 / 不确定项 | 说明 |
|---|---|
| data_catalog 有历史口径 | `data_catalog.yaml` 里还留有 Binance/Yahoo/旧 basis/put-call 等历史登记，不能直接当成当前可用 |
| freshness source label 历史遗留 | `src/data/freshness.py` 仍有 `binance_kline` label，但当前真实 K 线来源按 AGENTS 和 data_sources 是 CoinGlass |
| factor_card_emitter 有旧文案 | 部分 source label 仍提到 Binance / Yahoo，这与当前真实口径不完全一致；本轮只记录，不修改 |
| L5 prompt 期望字段多于当前 collector | `us2y/m2/global_m2/fed_balance_sheet` 等 context 支持字段，但 FRED collector 当前未采集 |
| CoinGlass net_position 有 collector 但未确认定时调度 | 不能写成已稳定入库，只能写 collector_exists_not_scheduled |
| Glassnode delayed 指标不等于已接入 | LTH SOPR/STH SOPR/liveliness/hash ribbon 等在 catalog 有记录，但 collector 当前未实现 |
| C 级语义不一致 | Master / Validator / persistence 三处语义不完全统一，需后续单独建模裁决 |
| 本轮没有调用真实 API | 因此只做代码级接口审计，未验证外部 API 当前是否仍可返回 |
| `uv.lock` 预先有本地改动 | 本轮未触碰，不纳入提交 |

## 13. 下一步建模建议

建议按下面顺序推进，避免把两个系统混在一起：

1. 先定 Layer A 的输出 schema：只包含现货五类动作，不包含 A/B/C，不包含 short，不包含虚拟账户。
2. 单独设计 Layer A 输入：优先使用链上周期、ETF flow、宏观流动性、大周期价格位置。
3. 明确 Layer A 与 Layer B 的关系：Layer A 可以做大背景，但不要直接改 Layer B 的 grade、仓位、止损。
4. 先解决 C 级语义不一致：决定 C 到底只是观察，还是可落观察型 thesis。
5. 对缺失但推荐的 Layer A 因子分批接入，不要一次性恢复 reserve risk / puell / basis / put-call 等历史退场项。
6. 如果要补 FRED：优先低成本补 US2Y、Fed Funds、CPI/Core CPI、Unemployment、M2/Fed balance sheet。
7. 如果要补 Glassnode：优先 LTH SOPR、STH SOPR、percent supply profit/loss、RHODL，再考虑 hash ribbon。
8. 如果要补 CoinGlass：先确认 net_position 是否需要调度，再评估 liquidation heatmap / options IV 这类高成本项。
9. 网页新增 Layer A 模块时保持现有审计风格，不大改 Layer B UI。

## 14. 实际运行命令与测试结果

### 14.1 关键只读检索命令

本轮主要使用了以下只读命令：

```bash
sed -n '1,220p' AGENTS.md
sed -n '1,180p' README.md
sed -n '1,260p' config/data_catalog.yaml
sed -n '1,220p' config/data_sources.yaml
sed -n '1,220p' config/scheduler.yaml
sed -n '1,260p' src/ai/context_builder.py
sed -n '1,260p' src/data/collectors/glassnode.py
sed -n '1,260p' src/data/collectors/coinglass.py
sed -n '1,220p' src/data/collectors/fred.py
sed -n '1,260p' src/data/storage/schema.sql
sed -n '1,280p' src/data/freshness.py
rg -n "reserve_risk|puell|basis|put_call|lth_sopr|sth_sopr|hash_ribbon|liveliness|active_addresses|etf_flow|btc_dominance|net_position" config src docs/cc_reports docs/codex_reports
git status --short
git diff --check
```

### 14.2 测试结果

本轮不改代码，不跑全量 pytest。

按用户要求，本轮至少执行：

| 命令 | 结果 |
|---|---|
| `git status --short` | 通过；仅见预先存在的 `uv.lock` 本地改动 + 本轮新增报告，本轮不触碰 `uv.lock` |
| `git diff --check` | 通过，无空白错误 |
| 敏感信息扫描 | 通过，未发现真实 key / token / secret / 私钥 |

## 15. 删除清单

本轮无替代关系，无删除项。原因：本轮是只读审计报告，没有实现新代码，也没有替代旧实现。

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| N/A | N/A | 本轮无删除项 |

## 16. 部署状态四件事清单

按用户本轮要求：

| 项目 | 状态 |
|---|---|
| 是否已部署 | N/A |
| 是否需要重启 | N/A |
| 是否影响生产任务 | 否 |
| 是否影响真实交易 | 否 |

按 AGENTS.md 交付状态补充：

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A，本轮不改代码 |
| GitHub push(commit hash:xxxx) | 待提交后在对话和审查包 metadata 中记录 |
| 服务器 git pull | N/A |
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | N/A |
