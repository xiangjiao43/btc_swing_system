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

服务器执行：

```bash
cd /home/ubuntu/btc_swing_system
.venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

结果：

- `run_id=97cbe8ac7ad84091bfea0e209e32b0da`
- `persisted=true`
- `ai_status=degraded_master_degraded_ai_failed`
- `degraded_stages=["master"]`

说明：本轮关注的是 Layer A context 和网页显示。虽然本次主裁 Master AI 降级，但最新 run 已成功持久化，且 `layer_a_spot_strategy` 存在、validator 通过。

## 9. 最新 run_id

- 最新 run_id：`97cbe8ac7ad84091bfea0e209e32b0da`
- run 时间：`2026-05-13T02:18:30Z`
- A1 cycle_stage：`mid_bull`
- A5 spot_action：`dca_buy`
- Layer A validator：`passed=true`
- validator violations：`[]`
- validator warnings：`[]`
- `critical_unavailable_count=10`
- `confidence_cap=medium`
- `percent_supply_in_profit.fetched_at_bjt=2026-05-13 09:35:14 (BJT)`
- `us2y.fetched_at_bjt=2026-05-13 09:15:09 (BJT)`

## 10. 线上网页截图

公网自动访问结果：

- `curl http://124.222.89.86/api/strategy/current` 返回 `401 Authorization Required`
- `curl -I http://124.222.89.86/` 返回网关/认证保护响应

因此本轮无法在未提供认证信息的自动环境中截取登录后的真实网页。已保存可获取的验证图：

- `/private/tmp/layer_a_web_factor_timestamp_fix/verification/production_web_auth_check.png`

服务器本机验证结果：

- `http://127.0.0.1:8000/` HTML 包含「大周期策略」「原始数据因子」「layerAFactorCoverageSummary()」
- `http://127.0.0.1:8000/api/strategy/current` 返回 `layer_a_spot_strategy`
- API 中 `percent_supply_in_profit` 和 `us2y` 均包含 `fetched_at_bjt`

## 11. 是否影响 Layer B / 虚拟账户 / 真实交易

- 是否影响 Layer B：否。本轮没有修改 L1-L5、Master、Layer B Validator、thesis、C 级机会。
- 是否影响虚拟账户：否。Layer A 仍不进入虚拟账户。
- 是否影响真实交易：否。本轮没有新增或触发真实交易接口。

## 12. 删除清单 / 废弃清单

本轮无替代关系，无删除项。原因：本轮为 Layer A 新增因子的网页显示口径修复，没有引入替代实现。

## 13. 风险和未完成

- 旧 run 中尚未包含 `fetched_at_bjt` 的 Layer A context 时，网页会回退显示数据点时间；新 run 已包含新版字段。
- 本地 pipeline 超时，服务器 pipeline 已完成并 `persisted=true`，但 Master AI 降级。Layer A 输出和网页字段验证不受影响。
- 公网网页存在认证/网关保护，自动环境无法看到登录后的真实页面；最终仍需用户登录后刷新确认。

## 14. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash: `0c303cb`) | ✅ |
| 服务器 git pull | ✅ |
| 服务器 systemctl restart | ✅ |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | ✅ |

## 15. 审查包路径

`/private/tmp/layer_a_web_factor_timestamp_fix/layer_a_web_factor_timestamp_and_missing_data_fix_audit_bundle.zip`
