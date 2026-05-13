# layer_a_web_factor_timestamp_and_missing_data_fix

## 1. 任务目标

修复 Layer A 新增因子在网页「原始数据因子」模块里的显示口径：

- 新增因子优先显示后台真实写入/抓取时间，而不是只显示数据点日期。
- `proxy_endpoint_404` 显示为 `unavailable / 未接入`。
- `uncertain_rate_limited` 显示为 `unavailable / 数据受限`。
- `factor_coverage`、`unavailable_factors`、`data_quality_notes` 在原始因子模块头部同步展示。
- 不新增独立模块，不改变原始因子模块的卡片、折叠、badge 和整体样式。

## 2. 改动文件

- `src/ai/spot_cycle_context_builder.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_web_modules_4_5_rp_failure.py`

## 3. 修复因子列表

本轮覆盖上一轮同步到原始因子模块的 10 个 Layer A 新因子：

- `lth_sopr`
- `sth_sopr`
- `percent_supply_in_profit`
- `percent_supply_in_loss`
- `exchange_balance`
- `exchange_net_position_change`
- `us2y`
- `fed_funds_rate`
- `m2`
- `fed_balance_sheet`

## 4. 抓取时间显示修正说明

`spot_cycle_context_builder` 现在从 `onchain_metrics` / `macro_metrics` 的 `inserted_at_utc` 读取系统侧真实写入时间，并为 Layer A context 中可用的新因子补充：

- `fetched_at_utc`
- `fetched_at_bjt`
- `captured_at_utc`

网页原始因子卡片优先显示 `fetched_at_bjt`；如果旧 run 没有该字段，再回退到数据点时间 `captured_at_utc` / `as_of`。

## 5. 缺失 / unavailable 处理说明

网页新增 Layer A 缺失状态映射：

- `proxy_endpoint_404` → `unavailable / 未接入`
- `uncertain_rate_limited` → `unavailable / 数据受限`
- `not_found` → `unavailable / 未接入`
- `config_only` → `unavailable / 未启用`
- `deprecated_candidate` → `unavailable / 已废弃`

缺失因子仍在原始数据因子卡片中显示，但数值为 `-`，红色 freshness 点沿用原模块规则。

## 6. factor_coverage / unavailable_factors 显示同步情况

`web/index.html` 在「原始数据因子」模块头部增加三行轻量说明，复用原模块小字样式：

- Layer A 因子覆盖
- Layer A 未接入因子
- Layer A 数据质量

这些内容来自 `layer_a_spot_strategy.factor_coverage`，或旧结构中的 `input_context_snapshot.factor_coverage`。

## 7. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`119 passed`

```bash
uv run pytest -q tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`22 passed`

```bash
git diff --check
```

结果：通过

## 8. pipeline run 结果

本地执行：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual
```

结果：420 秒超时，日志无有效输出。本轮未把本地 pipeline 超时视为交易逻辑失败；后续以服务器生产环境 pipeline 验证为准。

服务器 pipeline：待部署后补充。

## 9. 最新 run_id

待服务器 pipeline 验证后补充。

## 10. 线上网页截图

待服务器部署和验证后补充。若 `http://124.222.89.86/` 仍由 Basic Auth 保护，将记录 curl/API 验证结果，并保存可获取的验证产物。

## 11. 是否影响 Layer B / 虚拟账户 / 真实交易

- 是否影响 Layer B：否。本轮没有修改 L1-L5、Master、Layer B Validator、thesis、C 级机会。
- 是否影响虚拟账户：否。Layer A 仍不进入虚拟账户。
- 是否影响真实交易：否。本轮没有新增或触发真实交易接口。

## 12. 删除清单 / 废弃清单

本轮无替代关系，无删除项。原因：本轮为 Layer A 新增因子的网页显示口径修复，没有引入替代实现。

## 13. 风险和未完成

- 旧 run 中尚未包含 `fetched_at_bjt` 的 Layer A context 时，网页会回退显示数据点时间，直到下一次新 pipeline 写入新版 context。
- 本地 pipeline 超时，需以服务器生产环境 run 验证最新版字段是否写入最新 `strategy_run`。
- 若公网网页存在 Basic Auth，自动截图可能只能截到认证页面；最终仍需用户登录后刷新确认。

## 14. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待执行 |
| 服务器 git pull | 待执行 |
| 服务器 systemctl restart | 待执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待执行 |

## 15. 审查包路径

待生成。
