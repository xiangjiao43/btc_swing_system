# schedule_layer_a_spot_strategy_at_10am

## 1. 任务目标

本轮目标是把 Layer A“大周期策略 / 现货仓策略”AI A1-A5 从 11:35 主策略 pipeline 中拆出来，单独安排在北京时间每天 10:00 运行；Layer B 中长线波段仓继续保持北京时间每天 11:35 的主策略 pipeline。

核心边界：

- Layer A 独立运行，不影响 Layer B 开仓、平仓、仓位、止损、止盈、反手。
- Layer A 不进入虚拟账户，不创建 thesis，不做空，不使用 A/B/C/NONE。
- Layer B 不因为 Layer A 的结果被禁止运行。
- 网页“大周期策略”显示最近一次 Layer A 结果。
- 网页“五层分析 / 最终策略 / 虚拟账户”继续显示最近一次 Layer B 结果。
- 原始数据因子说明仍由 deterministic plain_reading / 前端规则化展示，不调用 AI 生成。

## 2. 读取文件

本轮重点读取：

- `AGENTS.md`
- `README.md`
- `config/scheduler.yaml`
- `src/scheduler/jobs.py`
- `scripts/run_pipeline_once.py`
- `src/pipeline/state_builder.py`
- `src/ai/orchestrator.py`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/spot_validator.py`
- `src/api/routes/strategy.py`
- `web/index.html`
- `web/assets/app.js`
- `docs/codex_reports/layer_a_b_pipeline_optimization_with_observability_and_timeout.md`
- `docs/codex_reports/remove_ai_from_raw_factor_plain_readings.md`
- `docs/codex_reports/layer_a_remaining_key_factors_validation_and_ingestion.md`
- 相关测试文件：`tests/test_scheduler_2_7_a_cron.py`、`tests/test_web_modules_1_2_3.py`、`tests/test_layer_a_standalone_schedule.py`

## 3. 当前调用链审查

修复前调用链：

1. `scripts/run_pipeline_once.py` 调用 `StrategyStateBuilder.build_and_persist(...)`。
2. `src/pipeline/state_builder.py` 构建数据 context。
3. `src/ai/orchestrator.py::AIOrchestrator.run_full_a(...)` 在同一次 run 中先跑 Layer B L1-L5 + Master + Validator，再跑 Layer A A1-A5。
4. Layer A 输出作为 `layer_a_spot_strategy` 合并进同一条 `strategy_runs.full_state_json`。
5. API `/api/strategy/current` 返回最新 strategy_run，网页从同一份 state 读取 Layer A 和 Layer B。

问题：

- 11:35 主 pipeline 会连续调用 Layer B 和 Layer A 的 AI，容易把单次 AI 压力集中在一起。
- Layer A 和 Layer B 的结果时间戳无法自然分离。
- 如果只想刷新 Layer A，过去没有独立安全入口。

## 4. Layer A / Layer B 拆分方案

本轮采用“独立 Layer A runner + 独立最新结果表 + API overlay”的方式。

新增 Layer A 独立入口：

- `scripts/run_layer_a_once.py`
- `src/pipeline/layer_a_spot_runner.py`

Layer A 单独运行时只执行：

1. build data context
2. compute data freshness
3. build Layer A context
4. run Layer A A1-A5
5. spot validator
6. persist Layer A latest result

Layer A 单独运行时不会执行：

- Layer B L1-L5
- Layer B Master
- Layer B Validator
- thesis persistence
- virtual account
- Layer B strategy_run 覆盖

Layer B 11:35 主 pipeline 默认变为 Layer B only：

- `StrategyStateBuilder(..., include_layer_a=False)` 为默认值。
- `AIOrchestrator.run_full_a(..., include_layer_a=False)` 会跳过 Layer A A1-A5。
- 如需兼容旧行为，可用 `scripts/run_pipeline_once.py --layer all` 显式跑全部。

## 5. 持久化方案

新增独立 latest 表：

- `latest_layer_a_spot_strategy`

对应文件：

- `src/data/storage/schema.sql`
- `migrations/018_add_latest_layer_a_spot_strategy.sql`
- `src/data/storage/dao.py::LatestLayerASpotStrategyDAO`

设计原因：

- Layer A 单独 10:00 运行时，只更新 Layer A 最新结果。
- 不覆盖最新 Layer B `strategy_runs`，避免把“五层分析 / 最终策略 / 虚拟账户”误改成 Layer A run。
- API 返回当前策略时，把最新 Layer A 结果 overlay 到最新 Layer B state 上，网页可以同时看到两套不同时间的结果。

网页读取方式：

- “大周期策略”：读取 overlay 后的 `layer_a_spot_strategy`。
- “五层分析 / 最终策略 / 虚拟账户”：仍读取最新 Layer B strategy_run。
- 两者可以有不同更新时间。

## 6. Scheduler 修改

`config/scheduler.yaml` 新增：

- `layer_a_spot_strategy`
- 北京时间每天 10:00

Layer B 保持：

- `pipeline_run_regular`
- 北京时间每天 11:35

时区说明：

- 北京时间 10:00 = UTC 02:00
- 北京时间 11:35 = UTC 03:35

项目当前 scheduler 配置使用本地 BJT 口径的 `hour/minute` 字段，因此文件中直接写：

- Layer A: `hour: 10`, `minute: 0`
- Layer B: `hour: 11`, `minute: 35`

`src/scheduler/jobs.py` 新增 `job_layer_a_spot_strategy`，并注册到 `_JOB_FUNCTIONS`。

## 7. 新增手动命令

只跑 Layer A：

```bash
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

只跑 Layer A 短验证，不执行 AI、不写入最新结果：

```bash
.venv/bin/python scripts/run_layer_a_once.py --trigger manual --validate-stages
```

只跑 Layer B：

```bash
.venv/bin/python scripts/run_pipeline_once.py --trigger manual --layer swing
```

兼容旧的 Layer A + Layer B 全量模式：

```bash
.venv/bin/python scripts/run_pipeline_once.py --trigger manual --layer all
```

主 pipeline 短验证：

```bash
.venv/bin/python scripts/run_pipeline_once.py --trigger manual --validate-stages
```

## 8. 网页读取方案

API 层：

- `src/api/routes/strategy.py` 从最新 Layer B `strategy_runs` 构造 state。
- 再读取 `latest_layer_a_spot_strategy`。
- 如果存在 Layer A 最新结果，则 overlay 到 `state["layer_a_spot_strategy"]`。
- 同时写入 `state["meta"]["layer_a_spot_updated_at_utc"]` / `state["meta"]["layer_a_spot_updated_at_bjt"]`。

网页层：

- `web/index.html` 在“大周期策略”模块显示“大周期策略更新时间”。
- `web/assets/app.js` 新增 `spotStrategyUpdatedAt()`，优先展示 Layer A 自己的时间。

旧 run 没有 Layer A 独立结果时，网页继续走原有 fallback。

## 9. 改动文件

本轮改动 / 新增：

- `config/scheduler.yaml`
- `scripts/run_pipeline_once.py`
- `scripts/run_layer_a_once.py`
- `src/ai/orchestrator.py`
- `src/api/routes/strategy.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `src/pipeline/state_builder.py`
- `src/pipeline/layer_a_spot_runner.py`
- `src/scheduler/jobs.py`
- `migrations/018_add_latest_layer_a_spot_strategy.sql`
- `tests/test_layer_a_standalone_schedule.py`
- `tests/test_scheduler_2_7_a_cron.py`
- `tests/test_web_modules_1_2_3.py`
- `docs/codex_reports/schedule_layer_a_spot_strategy_at_10am.md`

未纳入本轮提交：

- `uv.lock`：本轮未修改依赖，`uv.lock` 为既有遗留改动，不属于本轮范围。

## 10. 测试命令和结果

已运行：

```bash
uv run python -m py_compile scripts/run_pipeline_once.py scripts/run_layer_a_once.py src/pipeline/layer_a_spot_runner.py src/ai/orchestrator.py src/pipeline/state_builder.py src/data/storage/dao.py src/api/routes/strategy.py src/scheduler/jobs.py
```

结果：通过。

```bash
uv run pytest -q tests/test_layer_a_standalone_schedule.py tests/test_scheduler_2_7_a_cron.py
```

结果：`21 passed`。

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`24 passed`。

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`118 passed`。

```bash
uv run pytest -q tests/pipeline/test_state_builder_orchestrator_branch.py tests/pipeline/test_orchestrator_mapper.py
```

结果：`52 passed`。

```bash
uv run pytest -q tests/test_jobs_weekly_review_and_health_check.py tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py
```

结果：`68 passed`。

```bash
git diff --check
```

结果：通过。

## 11. 短验证结果

Layer A 独立短验证：

```bash
uv run python scripts/run_layer_a_once.py --trigger manual --validate-stages
```

结果：

- build Layer A context：success
- Layer A A1-A5：skipped
- spot validator：skipped
- persist Layer A：skipped
- `persisted=false`
- 未执行完整 AI，未写数据库。

主 pipeline 短验证：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual --validate-stages
```

结果：

- Layer B context / data freshness / Layer A context 阶段日志正常输出。
- Layer B L1-L5、Master、Validator、Layer A A1-A5 均为 skipped。
- 未执行完整 AI，未写数据库。

## 12. 是否影响 Layer B

不影响 Layer B 交易逻辑。

本轮没有修改：

- Layer B L1-L5 prompt
- Master 交易硬约束
- Validator 交易约束
- thesis 创建 / 持久化规则
- C 级机会行为
- 仓位、止损、止盈、开仓、平仓、反手规则

Layer B 只是默认不再在 11:35 主 pipeline 内附带运行 Layer A。

## 13. 是否影响虚拟账户

不影响。

Layer A 独立 runner 不调用虚拟账户，不写虚拟订单，不参与 thesis persistence。

## 14. 是否影响真实交易

不影响。

本项目仍是策略建议 / 审计系统。本轮没有新增真实交易接口，没有下单能力，也没有触发真实交易。

## 15. 删除清单 / 废弃清单

本轮无直接删除项。

废弃 / 兼容说明：

| 对象 | 位置 | 处理 |
|---|---|---|
| 11:35 主 pipeline 默认同时跑 Layer A + Layer B | `StrategyStateBuilder` / `AIOrchestrator.run_full_a` | 已改为默认 Layer B only；如需旧全量行为，使用 `--layer all` 显式运行，属于兼容入口 |

## 16. 风险和未完成

1. 生产服务器需要 `git pull` 后重启服务，scheduler 才会加载新 job。
2. 新表 `latest_layer_a_spot_strategy` 会在项目 `init_db` 时创建；如果生产服务长期不重启，表不会自动出现。
3. 本轮没有自动跑完整 AI pipeline，避免再次卡在长时间 AI 等待；需要用户按手动命令在服务器验证。
4. `uv.lock` 仍有既有未提交改动，本轮未纳入提交。

## 17. 用户后续手动部署命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

只跑 Layer A：

```bash
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

只跑 Layer B：

```bash
.venv/bin/python scripts/run_pipeline_once.py --trigger manual --layer swing
```

刷新网页：

```text
http://124.222.89.86/
```

## 18. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 本轮提交后在审查包 metadata 和最终对话中记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A，schema 通过 `init_db` 幂等创建 |
| 生产健康检查 `/api/system/health` | 待用户执行 |
