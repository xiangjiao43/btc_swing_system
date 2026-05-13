# layer_a_key_factor_interface_validation_and_ingestion

## 1. 任务目标

本轮沿着双层 BTC 策略主线，只补 Layer A「大周期策略」第一批关键因子。

目标是让 Layer A 的大周期阶段、链上宏观判断、现货风险判断有更多真实输入：

- 代码级验证第一批 Glassnode / FRED 因子接口、collector、配置、入库状态。
- 对低风险因子完成采集器接入、通用表入库路径接入、Layer A context 接入。
- 更新 `factor_coverage`、`unavailable_factors`、`data_quality_notes`。
- 轻微同步 A1/A2/A4/A5 prompt 对新增因子的认知。
- 不改 Layer B 交易逻辑，不改虚拟账户，不接真实交易。

## 2. 改动文件

| 文件 | 说明 |
|---|---|
| `config/data_catalog.yaml` | 登记 2 个已验证 Glassnode + 4 个 FRED Layer A 第一批因子；未验证 Glassnode 因子不伪装成可用 |
| `src/data/collectors/glassnode.py` | 新增盈利供给比例、交易所余额 fetcher |
| `src/data/collectors/fred.py` | 新增 DGS2、FEDFUNDS、M2SL、WALCL series 映射 |
| `src/scheduler/jobs.py` | 将新增 Glassnode fetcher 纳入 onchain collector 列表 |
| `src/ai/spot_cycle_context_builder.py` | 新增 `onchain_holder_behavior`、`macro_liquidity`，更新 coverage / unavailable |
| `src/ai/spot_strategy_normalizer.py` | 更新 critical missing 因子集合，避免已接入因子继续压低置信度 |
| `src/ai/agents/prompts/a1_spot_cycle.txt` | 补充新增因子在大周期阶段判断里的意义 |
| `src/ai/agents/prompts/a2_onchain_macro.txt` | 补充新增因子在链上宏观判断里的意义 |
| `src/ai/agents/prompts/a4_spot_risk.txt` | 补充新增因子在现货风险判断里的意义 |
| `src/ai/agents/prompts/a5_spot_adjudicator.txt` | 补充主裁使用新增因子的边界 |
| `tests/test_layer_a_key_factor_collectors.py` | 新增 collector/config 映射测试 |
| `tests/test_glassnode_collect_all.py` | 更新 Glassnode collect_all 反退化清单 |
| `tests/test_layer_a_spot_context_builder.py` | 验证新增因子进入 Layer A context 和 unavailable 移除 |
| `tests/test_layer_a_spot_normalize.py` | 更新 confidence cap 测试口径 |

## 3. 第一批因子接口验证表

| factor_name | preferred_source | current_project_status | code_evidence | can_ingest_this_round | estimated_risk | reason |
|---|---|---|---|---:|---|---|
| LTH SOPR | Glassnode | config_only / proxy_404 | `config/data_catalog.yaml` 有旧登记 `/v1/metrics/indicators/sopr_lth`，但生产 alphanode 返回 404 | false | medium | 当前代理不支持，退回延期清单 |
| STH SOPR | Glassnode | config_only / proxy_404 | `config/data_catalog.yaml` 有旧登记 `/v1/metrics/indicators/sopr_sth`，但生产 alphanode 返回 404 | false | medium | 当前代理不支持，退回延期清单 |
| Percent Supply in Profit | Glassnode | not_found → already_collected | 官方文档 supply endpoint `/v1/metrics/supply/profit_relative`；本轮新增 catalog + collector | true | low | scalar 序列，可复用 `onchain_metrics` |
| Percent Supply in Loss | Glassnode | proxy_404 | 生产 alphanode 对 `/v1/metrics/supply/loss_relative` 返回 404 | false | medium | 当前代理不支持，不硬接 |
| Exchange Balance | Glassnode | not_found → already_collected | 官方文档 distribution endpoint `/v1/metrics/distribution/balance_exchanges`；本轮新增 catalog + collector | true | low | scalar 序列，可复用 `onchain_metrics` |
| Exchange Net Position Change | Glassnode | uncertain | 生产验证时被 429 限流，未能确认当前代理可稳定返回 | false | medium | 本轮不硬接，后续单独低频验证 |
| US2Y | FRED | not_found → already_collected | `src/data/collectors/fred.py::SERIES_TO_METRIC["DGS2"] = "us2y"` | true | low | FRED 标准 series，复用 `macro_metrics` |
| Fed Funds Rate | FRED | deprecated_candidate → already_collected | `SERIES_TO_METRIC["FEDFUNDS"] = "fed_funds_rate"` | true | low | Layer A 大周期需要短端政策利率；不恢复旧 Layer B 用法 |
| M2 | FRED | not_found → already_collected | `SERIES_TO_METRIC["M2SL"] = "m2"` | true | low | FRED 标准 monthly series，复用 `macro_metrics` |
| Fed Balance Sheet | FRED | not_found → already_collected | `SERIES_TO_METRIC["WALCL"] = "fed_balance_sheet"` | true | low | FRED 标准 weekly series，复用 `macro_metrics` |

外部接口参考只用于路径验证，不记录任何 key：

- Glassnode supply endpoints: `https://docs.glassnode.com/basic-api/endpoints/supply`
- Glassnode distribution endpoints: `https://docs.glassnode.com/basic-api/endpoints/distribution`
- FRED series 走项目既有 `/series/observations` collector。

## 4. 实际接入因子清单

本轮实际接入 6 个：

- Glassnode: `percent_supply_in_profit`, `exchange_balance`
- FRED: `us2y`, `fed_funds_rate`, `m2`, `fed_balance_sheet`

这些因子都复用现有通用表：

- 链上：`onchain_metrics(metric_name, captured_at_utc, value, source, inserted_at_utc)`
- 宏观：`macro_metrics(metric_name, captured_at_utc, value, source, inserted_at_utc)`

没有新增复杂表，没有迁移数据库。

## 5. 未接入 / 延期因子清单与原因

| 因子 | 状态 | 原因 |
|---|---|---|
| RHODL Ratio | not_found | 当前项目无配置、无 collector，未在第一批范围内 |
| Reserve Risk | deprecated_candidate | 历史报告显示曾因噪音因子、无 L 层引用删除；本轮不恢复 |
| Puell Multiple | deprecated_candidate | 同上，本轮不恢复 |
| LTH SOPR | proxy_endpoint_404 | 生产 alphanode 返回 404，不能当作已接入 |
| STH SOPR | proxy_endpoint_404 | 生产 alphanode 返回 404，不能当作已接入 |
| Percent Supply in Loss | proxy_endpoint_404 | 生产 alphanode 返回 404，不能当作已接入 |
| Exchange Net Position Change | uncertain_rate_limited | 生产验证遇到 429，未确认稳定支持 |
| LTH Net Position Change | not_found | 当前项目无稳定配置 / collector，需后续单独验证接口 |
| Real Yield | not_found | 当前项目无稳定 FRED 组合实现，需后续定义口径 |
| CPI / Core CPI | partial_event_calendar_only | 当前只在事件层有部分口径，不作为 Layer A 数值因子接入 |
| Unemployment | deprecated_candidate | 历史曾删除；后续如接入需重新说明 Layer A 价值 |
| Futures Basis / Premium | deprecated_candidate | 历史已退役；本轮不恢复 |
| Options IV / Skew | not_found | 当前项目无稳定 collector |
| Liquidation Heatmap / Levels | not_found | 当前项目未接入热力图结构 |

## 6. Glassnode 修改说明

新增 2 个 fetcher，全部复用 `_fetch_series()`：

- `fetch_percent_supply_in_profit()`
- `fetch_exchange_balance()`

它们写入 `source="glassnode_primary"`，供 Layer A 读取，不改变 Layer B 交易约束。

`src/scheduler/jobs.py::_GLASSNODE_FETCHERS` 已纳入这些 fetcher，后续 onchain collector 会自动采集。

## 7. FRED 修改说明

新增 4 个 FRED series 映射：

- `DGS2 -> us2y`
- `FEDFUNDS -> fed_funds_rate`
- `M2SL -> m2`
- `WALCL -> fed_balance_sheet`

这些只扩展宏观数据池，仍走原有 FRED collector 和 `macro_metrics`。

## 8. Layer A context 修改说明

新增 / 扩展字段：

```text
available_factors.onchain_holder_behavior
  percent_supply_in_profit
  exchange_balance

available_factors.macro_liquidity
  us2y
  fed_funds_rate
  m2
  fed_balance_sheet
```

同时也把估值和交易所压力相关因子补到 `onchain_valuation`、`exchange_and_flows`、`macro`，方便 A1-A5 综合判断。

字段缺失时状态仍是 `missing`，不会伪造成中性。

## 9. factor_coverage 修改说明

本轮把已经真实接入的 6 个因子从 `_UNAVAILABLE_MODEL_FACTORS` 和 normalizer 的 critical missing 集合中移除。

含义：

- 如果这些因子已经有真实数据，会进入 `available_factor_count`。
- 如果暂时没抓到，会作为“已接入但缺值”，进入 `missing_integrated_factor_count` 和 `data_quality_notes`。
- 不再把它们算成“项目完全未接入”的 `critical_unavailable_count`。

接入前用户提供的生产 run 状态：

- `critical_unavailable_count = 16`
- `confidence_cap = medium`

生产验证后的新状态见第 13-18 节。

## 10. Prompt 轻微同步说明

本轮只改 Layer A A1/A2/A4/A5 prompt，且只补“新增因子怎么理解”：

- Percent Supply in Profit：盈利筹码比例是否过高。
- Exchange Balance：交易所潜在卖压。
- US2Y / Fed Funds / M2 / Fed Balance Sheet：利率压力和宏观流动性。

没有改 Layer B prompt。
没有写死机械阈值。
没有让 Layer A 影响 Layer B。

## 11. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 路径 / 位置 | 原因 |
|---|---|---|
| 无删除项 | N/A | 本轮是新增数据因子接入，没有替代旧实现 |
| 已废弃旧状态: `lth_sopr`, `sth_sopr` 为 config_only | `src/ai/spot_cycle_context_builder.py` | 已有 collector 和 context，不能继续当未接入 |
| 已废弃旧状态: `percent_supply_in_profit/loss`, `exchange_balance`, `exchange_net_position_change`, `us2y`, `fed_funds_rate`, `m2`, `fed_balance_sheet` 为 not_found/deprecated | `src/ai/spot_cycle_context_builder.py`, `src/ai/spot_strategy_normalizer.py` | 本轮已完成低风险接入，coverage 需反映真实状态 |

## 12. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_key_factor_collectors.py tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`27 passed`

```bash
uv run pytest -q tests/test_glassnode_collect_all.py tests/test_sprint_1_6_new_factors.py tests/test_scheduler_2_7_b_collectors.py
```

结果：`41 passed`

修正不稳定 Glassnode 因子后合并重跑：

```bash
uv run pytest -q tests/test_layer_a_key_factor_collectors.py tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py tests/test_glassnode_collect_all.py tests/test_sprint_1_6_new_factors.py tests/test_scheduler_2_7_b_collectors.py
```

结果：`68 passed`

```bash
uv run pytest -q tests/test_jobs_weekly_review_and_health_check.py tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py
```

结果：`68 passed`

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`115 passed`

修正不稳定 Glassnode 因子后合并重跑：

```bash
uv run pytest -q tests/test_jobs_weekly_review_and_health_check.py tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`183 passed`

```bash
git diff --check
```

结果：通过。

## 13. 线上 pipeline run 结果

待部署后补充。

## 14. 最新 run_id

待部署后补充。

## 15. A1 cycle_stage

待部署后补充。

## 16. A5 spot_action

待部署后补充。

## 17. critical_unavailable_count 接入前后对比

| 项目 | 接入前 | 接入后 |
|---|---:|---:|
| critical_unavailable_count | 16 | 待生产 run 验证 |

## 18. confidence_cap 接入前后对比

| 项目 | 接入前 | 接入后 |
|---|---|---|
| confidence_cap | medium | 待生产 run 验证 |

## 19. http://124.222.89.86/ 验证结果

待部署后补充。

## 20. 是否影响 Layer B

不影响。

本轮没有修改：

- Layer B L1-L5 prompt
- Layer B Master prompt
- Layer B Validator
- thesis 创建规则
- C 级机会行为
- 仓位、止损、止盈、开仓、平仓、反手规则

## 21. 是否影响虚拟账户

不影响。Layer A 仍不进入虚拟账户。

## 22. 是否影响真实交易

不影响。系统仍不真实下单，本轮没有新增真实交易接口。

## 23. 风险和未完成

- 新增 Glassnode endpoint 已用生产代理验证：`percent_supply_in_profit` 和 `exchange_balance` 成功；`lth_sopr`、`sth_sopr`、`percent_supply_in_loss` 返回 404；`exchange_net_position_change` 被限流，未确认稳定支持。
- `FEDFUNDS`、`M2SL` 是月度数据，`WALCL` 是周度数据；它们适合 Layer A 大周期，不适合短线新鲜度判断。
- 如果生产当日 onchain collector 已跑过，`job_collect_onchain` 的今日完整性门会跳过；生产验证时需要用安全手动采集方式补跑新增因子。
- `uv.lock` 是本轮开始前已有遗留修改，本轮不提交。

## 24. 下一步建议

1. 生产部署后先验证新增因子是否真实入库，再看 Layer A 最新 run。
2. 若 `critical_unavailable_count` 下降但 `confidence_cap` 仍是 medium，下一批优先验证 `LTH/STH SOPR` 的正确代理路径、`Percent Supply in Loss` 替代路径、`Exchange Net Position Change` 低频重试，以及 `RHODL / Reserve Risk / Puell / LTH Net Position Change / Real Yield`。
3. 等新增因子积累几天后，再审查 Layer A 是否仍偏乐观或偏保守，不要只看单次 run 调 prompt。

## 25. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待执行 |
| 服务器 git pull | 待执行 |
| 服务器 systemctl restart | 待执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待执行 |
