# Layer A/B Pipeline Optimization With Observability And Timeout

## 1. 任务目标

本轮目标是确认并交付 BTC 系统 pipeline 的阶段日志、超时保护、短时验证和原始因子 plain_reading 规则。

核心边界：

- Layer A 大周期策略和 Layer B 波段策略保持独立。
- 不修改 Layer A A1-A5 策略判断逻辑。
- 不修改 Layer B L1-L5 / Master / Validator / thesis / C 级机会 / 虚拟账户逻辑。
- 原始因子说明使用 deterministic plain_reading 模板，不调用 AI。
- 不自动跑完整 pipeline，不重启服务，不触发真实交易。

## 2. 本轮是否改代码

本轮新增本报告文件；pipeline 日志、timeout、`--validate-stages`、原始因子 deterministic plain_reading 能力已经在当前代码中存在并通过验证。

当前相关代码 commit：

- `17e05b7 Add pipeline observability and timeout guards`
- `6e567b7 Use deterministic plain readings for raw Layer A factors`

## 3. 读取和核对文件

- `AGENTS.md`
- `scripts/run_pipeline_once.py`
- `src/utils/pipeline_progress.py`
- `src/ai/client.py`
- `src/ai/agents/_base.py`
- `src/ai/summary.py`
- `src/ai/macro_l5_adjudicator.py`
- `src/ai/orchestrator.py`
- `src/pipeline/state_builder.py`
- `src/ai/context_builder.py`
- `src/ai/spot_cycle_context_builder.py`
- `src/evidence/plain_reading.py`
- `web/assets/app.js`
- `config/data_sources.yaml`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/coinglass.py`
- `src/data/collectors/fred.py`
- `tests/test_pipeline_progress_logging.py`
- `tests/test_plain_reading.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 4. 阶段日志状态

已确认 pipeline 主要阶段会输出：

- 阶段名
- 开始时间
- 结束时间
- 耗时
- 状态：`success` / `failure` / `degraded` / `skipped` / `partial`
- 错误类型
- 错误信息

日志目录：

```text
/private/tmp/pipeline_debug_logs/
```

短时验证日志：

```text
/private/tmp/pipeline_debug_logs/validation_run.log
```

普通 run 使用带时间戳、PID 和 `time_ns` 的唯一 JSONL 文件，不覆盖历史日志。

## 5. AI / HTTP Timeout 状态

AI timeout：

- `src/ai/client.py` 默认 `DEFAULT_TIMEOUT_SEC = 120.0`
- `src/ai/agents/_base.py` 默认 `_DEFAULT_TIMEOUT_SEC = 120.0`
- `src/ai/summary.py` 默认 `_DEFAULT_TIMEOUT_SEC = 120.0`
- `src/ai/macro_l5_adjudicator.py` 默认 `_DEFAULT_TIMEOUT_SEC = 120.0`

外部数据源 timeout：

- `config/data_sources.yaml` 默认 `timeout_sec = 15`
- CoinGlass `timeout_sec = 15`
- Glassnode `timeout_sec = 15`
- FRED `timeout_sec = 15`

外部请求已接入阶段日志：

- `external Glassnode request ...`
- `external CoinGlass request ...`
- `external FRED request ...`

含义：AI 或外部请求慢时，系统不再“无声卡住”；日志能看到卡在哪个阶段。

## 6. 短时验证 run

执行命令：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual --validate-stages
```

结果：

- `pipeline_status=success`
- 输出 `/private/tmp/pipeline_debug_logs/validation_run.log`
- 已验证 env、DB connection、Layer B context、data freshness、Layer A context
- Layer B L1-L5、Master、validators、Layer A A1-A5、thesis、persist 均按预期 `skipped`

该命令没有跑完整 AI，没有写入新的 strategy_run。

## 7. 原始因子 Plain Reading 验证

已确认新增原始因子说明使用 deterministic plain_reading / 前端规则模板：

- 不调用 AI
- 不读取 Layer A A1-A5 的 AI human_summary
- 不显示 `Layer A context: 可用`
- 不把 `proxy_endpoint_404` / `uncertain_rate_limited` 当主文案展示
- 可用因子显示数值、说明、状态、抓取时间
- 不可用因子显示用途说明和未接入 / 数据受限状态

覆盖因子包括：

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
- `rhodl_ratio`
- `reserve_risk`
- `puell_multiple`
- `lth_net_position_change`
- `real_yield`
- `cpi`
- `core_cpi`

## 8. 测试命令和结果

```bash
uv run pytest -q tests/test_pipeline_progress_logging.py tests/test_plain_reading.py tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`61 passed`

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`118 passed`

```bash
uv run pytest -q tests/test_layer_a_key_factor_collectors.py tests/test_coinglass_endpoints_contract.py tests/test_coinglass_no_silent_zero.py tests/test_glassnode_collect_all.py
```

结果：`19 passed`

```bash
uv run python scripts/run_pipeline_once.py --trigger manual --validate-stages
```

结果：通过，未跑完整 AI，未写入新 strategy_run。

```bash
git diff --check
```

结果：通过。

## 9. 是否影响策略逻辑

没有影响。

本轮没有修改：

- Layer A A1-A5 prompt / 策略判断逻辑
- Layer B L1-L5 / Master / Validator / thesis / C 级机会
- 仓位、止损、止盈、开仓、平仓、反手规则
- 虚拟账户
- 真实交易接口
- 网页 UI 样式

Layer A 与 Layer B 仍保持两套机制。Layer A 不进入虚拟账户，不创建 thesis，不影响 Layer B 开平仓。

## 10. 删除清单 / 废弃清单

本轮无替代关系，无删除项。原因：本轮主要是交付核对、验证和报告补充，没有引入新的替代实现。

## 11. 风险和未完成

- 本轮没有自动跑完整 pipeline，这是按用户要求避免长时间卡住。
- 本轮没有自动重启 `btc-strategy.service`。
- `uv.lock` 仍有本轮前遗留的本地未提交改动，本轮未提交它。
- 完整 pipeline 仍可能因为多次 AI 调用整体耗时较长，但现在可以通过 `/private/tmp/pipeline_debug_logs/` 定位卡点。

## 12. 用户手动命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
.venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

刷新网页：

```text
http://124.222.89.86/
```

如果只想先验证阶段日志：

```bash
.venv/bin/python scripts/run_pipeline_once.py --trigger manual --validate-stages
tail -80 /private/tmp/pipeline_debug_logs/validation_run.log
```

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待本报告提交后执行 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

