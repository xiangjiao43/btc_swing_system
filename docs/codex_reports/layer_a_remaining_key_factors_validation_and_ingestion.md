# layer_a_remaining_key_factors_validation_and_ingestion

## 1. 任务目标

本轮继续补齐 Layer A「大周期现货策略」剩余 8 个关键缺失因子。

小白解释：上一轮已经让 Layer A 能看到一批真实链上和宏观数据，本轮继续补“更像大周期交易员会看的关键仪表盘”，包括长期/短期持有人 SOPR、RHODL、Reserve Risk、Puell、实际利率、CPI/Core CPI、长期持有人净头寸变化。

边界：

- 不改 Layer B L1-L5 / Master / Validator / thesis / C 级机会。
- 不改仓位、止损、止盈、开仓、平仓、反手。
- 不让 Layer A 进入虚拟账户。
- 不真实交易。
- 不把 404 / not_found / uncertain 伪装成真实数据。

## 2. 改动文件

| 文件 | 说明 |
|---|---|
| `config/data_catalog.yaml` | 登记本轮 8 个关键因子真实 endpoint / FRED series |
| `src/data/collectors/glassnode.py` | 新增 6 个 Glassnode Layer A 只读 fetcher |
| `src/data/collectors/fred.py` | 新增 DFII10 / CPIAUCSL / CPILFESL 映射 |
| `src/scheduler/jobs.py` | 将新增 Glassnode fetcher 纳入 onchain collector 列表 |
| `src/ai/spot_cycle_context_builder.py` | 新增 onchain cycle / holder / macro inflation 输入和 coverage 更新 |
| `src/ai/spot_strategy_normalizer.py` | 更新 critical coverage 口径，避免已接入因子继续被算作未接入 |
| `src/ai/agents/prompts/a1_spot_cycle.txt` | 轻微同步新增因子的建模意义 |
| `src/ai/agents/prompts/a2_onchain_macro.txt` | 同上 |
| `src/ai/agents/prompts/a4_spot_risk.txt` | 同上 |
| `src/ai/agents/prompts/a5_spot_adjudicator.txt` | 同上 |
| `web/assets/app.js` | 原始数据因子模块新增本轮因子卡片和人话解释 |
| `tests/test_layer_a_key_factor_collectors.py` | collector / catalog / FRED 映射测试 |
| `tests/test_layer_a_spot_context_builder.py` | context 和 timestamp 测试 |
| `tests/test_layer_a_spot_normalize.py` | confidence cap 测试更新 |
| `tests/test_glassnode_collect_all.py` | collect_all 注册测试 |
| `tests/test_sprint_1_7_factor_deletions.py` | 旧删除锁更新为“Layer B 仍禁用，Layer A 只读恢复” |
| `tests/test_web_modules_4_5_rp_failure.py` | 原始数据因子网页展示测试 |

## 3. 剩余 8 因子接口验证表

验证方式：在生产服务器 `/home/ubuntu/btc_swing_system` 用项目现有 collector 和环境配置小流量探测，只输出状态码、行数和最新值，不输出任何 key。

| factor_name | preferred_source | endpoint_or_series | current_status | code_evidence | can_ingest_this_round | reason | implementation_risk |
|---|---|---|---|---|---:|---|---|
| LTH SOPR | Glassnode | `/v1/metrics/indicators/sopr_more_155` | already_collected | `GlassnodeCollector._PATH_LTH_SOPR`，生产探测 HTTP 200 / 30 rows | true | 旧路径 `sopr_lth` 错；官方/代理可用新路径 | low |
| STH SOPR | Glassnode | `/v1/metrics/indicators/sopr_less_155` | already_collected | `GlassnodeCollector._PATH_STH_SOPR`，生产探测 HTTP 200 / 30 rows | true | 旧路径 `sopr_sth` 错；官方/代理可用新路径 | low |
| RHODL Ratio | Glassnode | `/v1/metrics/indicators/rhodl_ratio` | already_collected | `GlassnodeCollector._PATH_RHODL_RATIO`，生产探测 HTTP 200 / 30 rows | true | 标准 scalar 序列，可复用 `onchain_metrics` | low |
| Reserve Risk | Glassnode | `/v1/metrics/indicators/reserve_risk` | already_collected | `GlassnodeCollector._PATH_RESERVE_RISK`，生产探测 HTTP 200 / 30 rows | true | 历史因无 Layer B 引用删除；Layer A 大周期现在需要，只读恢复 | low |
| Puell Multiple | Glassnode | `/v1/metrics/indicators/puell_multiple` | already_collected | `GlassnodeCollector._PATH_PUELL_MULTIPLE`，生产探测 HTTP 200 / 30 rows | true | 历史因无 Layer B 引用删除；Layer A 大周期现在需要，只读恢复 | low |
| Real Yield | FRED | `DFII10` | already_collected | `SERIES_TO_METRIC["DFII10"] = "real_yield"`，生产探测 498 rows | true | 标准 FRED series，可复用 `macro_metrics` | low |
| CPI / Core CPI | FRED | `CPIAUCSL` / `CPILFESL` | already_collected | `SERIES_TO_METRIC["CPIAUCSL"] = "cpi"`，`SERIES_TO_METRIC["CPILFESL"] = "core_cpi"` | true | 标准 FRED monthly series；作为 Layer A 宏观通胀输入 | low |
| LTH Net Position Change | Glassnode | `/v1/metrics/supply/lth_net_change` | already_collected | `GlassnodeCollector._PATH_LTH_NET_CHANGE`，生产探测 HTTP 200 / 30 rows | true | 标准 Long-Term Holder Position Change，可复用 `onchain_metrics` | low |

## 4. 实际成功接入因子清单

本轮 8 个目标全部低风险接入：

Glassnode：

- `lth_sopr`
- `sth_sopr`
- `rhodl_ratio`
- `reserve_risk`
- `puell_multiple`
- `lth_net_position_change`

FRED：

- `real_yield`
- `cpi`
- `core_cpi`

说明：用户列表里 “CPI / Core CPI” 是一个缺失项，但工程上拆成 `cpi` 和 `core_cpi` 两个真实 series。

## 5. 仍未接入因子清单与真实原因

本轮目标 8 项全部已接入。其他仍未接入的 Layer A 预留因子不在本轮目标内：

| 因子 | 状态 | 原因 |
|---|---|---|
| market_cap_realized_cap | not_found | 当前未作为独立 metric 接入，MVRV 已间接覆盖部分含义 |
| liveliness | config_only | data_catalog 有历史登记，但 collector 未实现 |
| stablecoin_supply_liquidity | not_found | 当前项目无稳定数据源 |
| monthly_structure_1m | not_found | 当前未做 1M 结构预计算 |
| major_support_resistance | ai_derived_not_precomputed_for_layer_a | 当前由 AI/技术结构语境判断，不是预计算因子 |
| unemployment | deprecated_candidate | 历史退场；后续如纳入需重新建模 |
| futures_basis_premium | deprecated_candidate | 历史退场，不恢复 Binance/Yahoo |
| options_iv_skew | not_found | 当前无稳定 collector |
| liquidation_heatmap_levels | not_found | 当前未接入热力图结构 |

## 6. Glassnode 修改说明

新增 6 个 Layer A 只读 fetcher：

- `fetch_lth_sopr()` → `/v1/metrics/indicators/sopr_more_155`
- `fetch_sth_sopr()` → `/v1/metrics/indicators/sopr_less_155`
- `fetch_rhodl_ratio()` → `/v1/metrics/indicators/rhodl_ratio`
- `fetch_reserve_risk()` → `/v1/metrics/indicators/reserve_risk`
- `fetch_puell_multiple()` → `/v1/metrics/indicators/puell_multiple`
- `fetch_lth_net_position_change()` → `/v1/metrics/supply/lth_net_change`

这些数据只进入 Layer A context，不进入 Layer B 交易约束。

## 7. FRED 修改说明

新增 3 个 FRED 映射：

- `DFII10 -> real_yield`
- `CPIAUCSL -> cpi`
- `CPILFESL -> core_cpi`

CPI 和 Core CPI 是月频数据。网页显示抓取时间和数据日期，不把月频数据误装成日频。

## 8. Layer A context 修改说明

新增分类 / 字段：

```text
available_factors.onchain_holder_behavior
  lth_sopr
  sth_sopr
  lth_net_position_change

available_factors.onchain_valuation
  rhodl_ratio
  reserve_risk
  puell_multiple

available_factors.macro_inflation_rates
  real_yield
  cpi
  core_cpi
```

旧 `unavailable_factors` 中的 8 个关键项已移除。缺值时仍会显示 `missing`，不会填 0。

## 9. factor_coverage 接入前后对比

接入前生产 latest run：

- `critical_unavailable_count = 8`
- `confidence_cap = medium`

本地代码层预期：

- 这 8 个因子成功接入后不再算 critical unavailable。
- 如果生产采集成功，`critical_unavailable_count` 应下降。
- 若仍有已接入因子缺值，会进入 `missing_integrated_factor_count`，不会伪装为可用。

线上最终验证结果见第 14-19 节。

## 10. 原始数据因子网页显示同步说明

`web/assets/app.js` 在现有「原始数据因子」模块中新增本轮因子卡片，不新增独立模块。

新增卡片沿用老格式：

- 标题
- 右上角数值
- 一句话人话解释
- 状态行
- 抓取时间

新增人话解释覆盖：

- LTH SOPR：长期持有人获利/亏损卖出状态
- STH SOPR：短期持有人获利/亏损卖出状态
- RHODL Ratio：大周期估值温度
- Reserve Risk：长期持有者信心与价格风险
- Puell Multiple：矿工收入压力与周期位置
- LTH Net Position Change：长期持有人增持/减持方向
- Real Yield：实际利率压力
- CPI / Core CPI：通胀压力

## 11. Prompt 轻微同步说明

只轻微同步 A1/A2/A4/A5 对新增因子的认知：

- 不写死机械阈值。
- 不改 Layer B prompt。
- 不改 Layer A 输出 schema。
- 不让 Layer A 影响 Layer B。

## 12. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 路径 / 位置 | 原因 |
|---|---|---|
| 旧 LTH SOPR endpoint `/sopr_lth` | `config/data_catalog.yaml` | 生产验证 404；被 `/sopr_more_155` 替代 |
| 旧 STH SOPR endpoint `/sopr_sth` | `config/data_catalog.yaml` | 生产验证 404；被 `/sopr_less_155` 替代 |
| Reserve Risk / Puell “只能删除”的测试假设 | `tests/test_sprint_1_7_factor_deletions.py` | Layer B 仍不使用，但 Layer A 大周期只读恢复采集；测试改为锁住“不回到 Layer B” |

## 13. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_key_factor_collectors.py tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py tests/test_glassnode_collect_all.py tests/test_sprint_1_7_factor_deletions.py
```

结果：`43 passed`

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`118 passed`

```bash
uv run pytest -q tests/test_jobs_weekly_review_and_health_check.py tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py
```

结果：`68 passed`

```bash
uv run pytest -q tests/test_scheduler_2_7_b_collectors.py tests/test_sprint_1_6_new_factors.py
```

结果：`38 passed`

```bash
git diff --check
```

结果：通过。

说明：曾把 `test_scheduler_2_7_b_collectors.py` 和 weekly review 测试放在同一个 pytest 进程里跑，出现一次函数对象 identity 的顺序污染；单独按项目常规方式重跑全部通过，不是本轮因子逻辑失败。

## 14. 线上 pipeline run 结果

待部署后补充。

## 15. 最新 run_id

待部署后补充。

## 16. A1 cycle_stage

待部署后补充。

## 17. A5 spot_action

待部署后补充。

## 18. critical_unavailable_count 接入前后对比

| 项目 | 接入前 | 接入后 |
|---|---:|---:|
| critical_unavailable_count | 8 | 待部署后补充 |
| confidence_cap | medium | 待部署后补充 |

## 19. http://124.222.89.86/ 验证结果

待部署后补充。

## 20. 是否影响 Layer B

否。Layer B L1-L5 / Master / Validator / thesis / C 级机会未改。

## 21. 是否影响虚拟账户

否。Layer A 仍不进入虚拟账户。

## 22. 是否影响真实交易

否。本系统仍只是交易辅助，不真实下单。

## 23. 风险和未完成

- 本轮新增 Glassnode endpoint 在生产探测均为 HTTP 200，但正式 pipeline 仍依赖当天数据源和 AI 服务可用性。
- CPI/Core CPI 是月频数据，不能按日频指标理解；网页会显示真实抓取时间和数据日期。
- 公网 `http://124.222.89.86/` 有 Basic Auth，自动化验证可能只能验证服务器本机 API / HTML / JS，最终视觉需要用户登录后刷新确认。

## 24. 下一步建议

1. 先观察接入后 1-2 次生产 run 的 Layer A 阶段判断是否更稳定。
2. 如果 `confidence_cap` 仍被其他预留因子压住，再单独审计 remaining unavailable list，不要一次性恢复所有历史退场因子。
3. 后续再处理网页文字长短，不和本轮数据接入混在一起。

## 25. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待执行 |
| 服务器 git pull | 待执行 |
| 服务器 systemctl restart | 待执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待执行 |
