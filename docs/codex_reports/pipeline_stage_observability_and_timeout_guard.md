# Pipeline Stage Observability And Timeout Guard

## 1. 任务目标

本轮目标是解决手动 pipeline 在 `[env_loader] loaded .env: 7 keys` 后长时间无输出时无法判断卡点的问题。

本轮只做可观测性、超时保护和短时验证能力：

- 为 pipeline 主要阶段增加开始、结束、耗时、状态、错误类型和错误信息记录。
- 日志统一写入 `/private/tmp/pipeline_debug_logs/`。
- 普通 pipeline run 使用唯一日志文件，不覆盖历史日志。
- `--validate-stages` 短时验证固定输出 `/private/tmp/pipeline_debug_logs/validation_run.log`。
- AI 单次调用默认 timeout 调整为 120 秒。
- Glassnode / CoinGlass / FRED 外部请求 timeout 统一为 15 秒。
- 不修改 Layer A / Layer B 的策略判断逻辑、prompt、网页、真实交易和虚拟账户逻辑。

## 2. 读取文件

- `AGENTS.md`
- `README.md`
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
- `src/data/collectors/glassnode.py`
- `src/data/collectors/coinglass.py`
- `src/data/collectors/fred.py`
- `config/data_sources.yaml`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_spot_normalize.py`
- `tests/test_layer_a_spot_validator.py`
- `tests/test_layer_a_orchestrator_integration.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 3. 改动文件

- `src/utils/pipeline_progress.py`
- `scripts/run_pipeline_once.py`
- `src/ai/client.py`
- `src/ai/agents/_base.py`
- `src/ai/summary.py`
- `src/ai/macro_l5_adjudicator.py`
- `src/ai/orchestrator.py`
- `src/pipeline/state_builder.py`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/coinglass.py`
- `src/data/collectors/fred.py`
- `config/data_sources.yaml`
- `tests/test_pipeline_progress_logging.py`
- `docs/codex_reports/pipeline_stage_observability_and_timeout_guard.md`

说明：`uv.lock` 在本轮开始前已有本地脏改动，本轮没有把它纳入提交。

## 4. 阶段日志设计

新增统一日志工具 `src/utils/pipeline_progress.py`：

- `init_pipeline_logging()` 初始化本次 run 日志路径。
- `pipeline_stage(name)` 记录阶段开始和结束。
- `record_instant_stage()` 记录 skipped / instant 阶段，仍包含 started_at 和 ended_at。
- `record_pipeline_result()` 写入最终 pipeline 状态。

每条 `stage_finished` 日志包含：

- `stage_name`
- `started_at`
- `ended_at`
- `elapsed_sec`
- `status`
- `error_type`
- `error_message`

普通 run 日志示例路径：

- `/private/tmp/pipeline_debug_logs/pipeline_YYYYMMDDTHHMMSSZ_<pid>_<time_ns>_manual.jsonl`

短时验证固定路径：

- `/private/tmp/pipeline_debug_logs/validation_run.log`

普通 run 不覆盖历史日志；validation run 按用户要求固定写入 `validation_run.log`。

## 5. 覆盖阶段

本轮增加或强化记录的主要阶段：

- `load env`
- `init_db`
- `open_db_connection`
- `build StrategyStateBuilder`
- `build data context`
- `fetch / load market data`
- `fetch / load derivatives data`
- `fetch / load onchain data`
- `fetch / load macro data`
- `fetch / load event calendar`
- `build Layer B context indicators`
- `compute data freshness`
- `build Layer A context`
- `run Layer B L1`
- `run Layer B L2`
- `run Layer B L3`
- `run Layer B L4`
- `run Layer B L5`
- `run Layer B Master`
- `validators`
- `run Layer A spot strategy`
- `run Layer A A1`
- `run Layer A A2`
- `run Layer A A3`
- `run Layer A A4`
- `run Layer A A5`
- `thesis persistence check`
- `persist strategy_run`

## 6. AI Timeout

本轮将 AI client 默认单次调用 timeout 统一为 120 秒：

- `src/ai/client.py`
- `src/ai/agents/_base.py`
- `src/ai/summary.py`
- `src/ai/macro_l5_adjudicator.py`

含义：

- 如果 AI 或中转站长时间不返回，单次请求不会无限等。
- 现有 BaseAgent fallback / degraded 机制继续负责降级结果。
- 本轮没有改模型、prompt、策略判断规则。

## 7. 外部请求 Timeout

本轮将主要外部数据源请求 timeout 统一为 15 秒：

- `config/data_sources.yaml`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/coinglass.py`
- `src/data/collectors/fred.py`

同时外部请求也纳入 pipeline stage 日志，例如：

- `external Glassnode request ...`
- `external CoinGlass request ...`
- `external FRED request ...`

含义：

- 某个外部数据源慢或失败时，会留下具体阶段日志。
- 原有 collector 异常处理和上层 degraded/fallback 机制保持不变。
- 没有恢复 Binance / Yahoo。

## 8. 短时验证机制

新增命令：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual --validate-stages
```

该模式只做：

- 环境加载日志
- DB 连接
- Layer B context 构建
- 数据 freshness 计算
- Layer A context 构建
- AI / validators / thesis / persist 阶段统一记录为 `skipped`

该模式不做：

- 不跑完整 Layer A/B AI
- 不跑 Master 主裁
- 不做 thesis persistence
- 不写入新的 strategy_run
- 不触发真实交易

验证日志：

- `/private/tmp/pipeline_debug_logs/validation_run.log`

## 9. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_pipeline_progress_logging.py tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`27 passed`

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`118 passed`

```bash
uv run pytest -q tests/test_layer_a_key_factor_collectors.py tests/test_coinglass_endpoints_contract.py tests/test_coinglass_no_silent_zero.py tests/test_glassnode_collect_all.py
```

结果：`19 passed`

```bash
uv run python -m py_compile scripts/run_pipeline_once.py src/utils/pipeline_progress.py src/ai/context_builder.py src/ai/orchestrator.py src/ai/client.py src/ai/agents/_base.py src/ai/summary.py src/ai/macro_l5_adjudicator.py src/pipeline/state_builder.py src/data/collectors/glassnode.py src/data/collectors/coinglass.py src/data/collectors/fred.py
```

结果：通过。

```bash
uv run python scripts/run_pipeline_once.py --trigger manual --validate-stages
```

结果：通过，`pipeline_status=success`，日志写入 `/private/tmp/pipeline_debug_logs/validation_run.log`。

```bash
git diff --check
```

结果：通过。

## 10. 是否触碰高风险区域

没有。

本轮没有修改：

- Layer B L1-L5 策略逻辑
- Layer B Master prompt 或硬约束
- Layer B Validator 交易约束
- Layer B thesis 创建规则
- Layer B C 级机会行为
- Layer A A1-A5 prompt / 判断逻辑
- 仓位、止损、止盈、开仓、平仓、反手
- 虚拟账户
- 真实交易接口
- 网页 UI
- `.env` / API key / token / secret

## 11. 删除清单 / 废弃清单

本轮无替代关系，无删除项。原因：本轮是 pipeline 可观测性、timeout 和短时验证能力增强，没有引入替代交易逻辑或替代 UI。

## 12. 风险和未完成

- 本轮没有自动跑完整 pipeline，避免再次卡在长时间 AI 调用。
- 本轮没有重启服务器服务，按用户要求不自动 systemd restart。
- AI timeout 是单次请求 120 秒；如果完整 pipeline 有多次 AI 调用，总耗时仍可能较长，但现在可以从日志看到卡在哪一层。
- 外部请求 timeout 统一为 15 秒；如果上游服务持续慢，会记录失败并由原有 degraded/fallback 流程处理。
- `uv.lock` 仍是本轮前已有的本地脏改动，本轮没有提交它。

## 13. 用户后续手动命令

服务器上执行：

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
.venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

如果只想先验证日志，不跑完整 AI：

```bash
.venv/bin/python scripts/run_pipeline_once.py --trigger manual --validate-stages
tail -80 /private/tmp/pipeline_debug_logs/validation_run.log
```

## 14. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待本轮提交后执行 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

