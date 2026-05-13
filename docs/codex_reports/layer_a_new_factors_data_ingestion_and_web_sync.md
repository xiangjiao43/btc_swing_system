# layer_a_new_factors_data_ingestion_and_web_sync

## 1. 任务目标

本轮目标是继续补齐 Layer A 新增因子的真实数据接入，并保持「原始数据因子」网页显示与老因子一致：

- 可用因子显示 `actual_value`、一句话解释、状态、抓取时间。
- 不可用因子显示用户可读的 `未接入 / 数据受限`，不在主卡片暴露内部错误。
- 不新增独立模块，不改变 UI 风格。
- 不改 Layer B，不改 Layer A A1-A5 AI 判断逻辑，不改虚拟账户和真实交易。

## 2. 改动文件

- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_strategy_normalizer.py`
- `web/assets/app.js`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_spot_normalize.py`
- `docs/codex_reports/layer_a_new_factors_data_ingestion_and_web_sync.md`

## 3. 接口验证结果

服务器使用项目生产配置只读验证 Glassnode 代理端点，不输出任何 key：

| 因子 | 验证结果 | 本轮处理 |
|---|---|---|
| LTH SOPR | `/v1/metrics/indicators/sopr_lth` 返回 404 | 继续标为 `未接入`，不伪造值 |
| STH SOPR | `/v1/metrics/indicators/sopr_sth` 返回 404 | 继续标为 `未接入`，不伪造值 |
| 盈利供给比例 | 已有真实 Glassnode 入库 `percent_supply_in_profit` | 保持真实值 |
| 亏损供给比例 | `/v1/metrics/supply/loss_relative` 返回 404 | 用真实盈利供给比例派生 `1 - profit` |
| 交易所余额 | 已有真实 Glassnode 入库 `exchange_balance` | 保持真实值 |
| 交易所净头寸变化 | 多个候选独立端点返回 404 | 用真实交易所余额日变化派生 |
| US2Y | 已有 FRED `DGS2 -> us2y` | 保持真实值 |
| Fed Funds | 已有 FRED `FEDFUNDS -> fed_funds_rate` | 保持真实值 |
| M2 | 已有 FRED `M2SL -> m2` | 保持真实值 |
| Fed Balance Sheet | 已有 FRED `WALCL -> fed_balance_sheet` | 保持真实值 |

重要说明：本轮没有把 404 / 未支持端点伪装成真实数据。LTH SOPR / STH SOPR 仍需要数据代理或替代数据源支持。

## 4. 实际数据接入 / 派生方式

新增两个低风险真实派生因子：

- `percent_supply_in_loss`
  - 来源：真实 Glassnode `percent_supply_in_profit`
  - 公式：`1 - percent_supply_in_profit`
  - `fetched_at_bjt` 沿用 `percent_supply_in_profit` 的真实入库时间

- `exchange_net_position_change`
  - 来源：真实 Glassnode `exchange_balance`
  - 公式：最新交易所余额 - 上一条交易所余额
  - `fetched_at_bjt` 沿用最新 `exchange_balance` 的真实入库时间

这两个因子已从 `unavailable_factors` 移出，进入 `available_factors.onchain_holder_behavior`。

## 5. 网页同步

网页上一轮已改为老因子卡片风格。本轮保持该 UI，不新增模块：

- 可用因子显示数值。
- 一句话解释由 `layerAFactorPlainReading()` 规则化生成。
- 状态行只显示一行。
- 抓取时间来自 `fetched_at_bjt`。
- 旧的 `proxy_endpoint_404` 如出现在旧 run 中，也只映射为用户可读的 `未接入`。

## 6. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`24 passed`

```bash
uv run pytest -q tests/test_layer_a_key_factor_collectors.py tests/test_glassnode_collect_all.py tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`125 passed`

```bash
git diff --check
```

结果：通过

## 7. pipeline 日志和线上验证

待部署后补充。

## 8. 是否影响范围

- 是否影响 Layer A AI 判断 / A1-A5 prompt：否。
- 是否影响 Layer B：否。
- 是否影响 thesis / C 级机会：否。
- 是否影响虚拟账户：否。
- 是否影响真实交易：否。

## 9. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 路径 / 位置 | 原因 |
|---|---|---|
| `percent_supply_in_loss` 作为不可用占位 | `src/ai/spot_cycle_context_builder.py` | 已由真实 `percent_supply_in_profit` 派生 |
| `exchange_net_position_change` 作为不可用占位 | `src/ai/spot_cycle_context_builder.py` | 已由真实 `exchange_balance` 日变化派生 |
| `percent_supply_in_loss` / `exchange_net_position_change` 作为 critical unavailable | `src/ai/spot_cycle_context_builder.py`, `src/ai/spot_strategy_normalizer.py` | 两者已进入可用/可缺值的 integrated factor 口径 |

## 10. 风险和未完成

- LTH SOPR / STH SOPR 在当前代理仍 404，无法真实接入；网页会显示 `未接入`。
- 亏损供给比例是由盈利供给比例派生，依赖 Glassnode `profit_relative` 的口径稳定性。
- 交易所净头寸变化是由交易所余额相邻两点变化派生，等价于“余额变化”，不是独立 Glassnode 端点。
- 如果生产 pipeline 因 Master AI 等待或降级失败，本轮会用最新 DB / API 字段做只读验证，不伪造成功。

## 11. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待执行 |
| 服务器 git pull | 待执行 |
| 服务器 systemctl restart | 待执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待执行 |

## 12. 审查包路径

待生成。
