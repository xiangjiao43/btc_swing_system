# fix_layer_a_b_pipeline_log_and_ai_using_claude_reference

## 1. 任务目标

本轮按用户要求，把 Layer A / Layer B pipeline 阶段日志目录从用户主目录下的 `pipeline_debug_logs` 调整为 Claude 参考写法：

```python
LOG_DIR = Path.home() / "pipeline_logs"
```

服务器 ubuntu 用户运行时，日志目录为：

```text
/home/ubuntu/pipeline_logs
```

本轮只改日志目录命名和对应测试，不改策略逻辑。

## 2. 读取文件

本轮重点读取：

- `src/utils/pipeline_progress.py`
- `tests/test_pipeline_progress_logging.py`
- `scripts/run_layer_a_once.py`
- `scripts/run_pipeline_once.py`
- `config/scheduler.yaml`
- `src/scheduler/jobs.py`
- `web/assets/app.js`
- `web/index.html`

## 3. 改动文件

本轮改动：

- `src/utils/pipeline_progress.py`
- `tests/test_pipeline_progress_logging.py`
- `docs/codex_reports/fix_layer_a_b_pipeline_log_and_ai_using_claude_reference.md`

未纳入提交：

- `uv.lock`：既有未提交改动，本轮未改依赖，不属于本轮修复范围。

## 4. 日志路径修复

修复前：

```python
LOG_DIR = Path.home() / "pipeline_debug_logs"
```

修复后：

```python
LOG_DIR = Path.home() / "pipeline_logs"
```

含义：

- 本地：`/Users/shenjun/pipeline_logs`
- 服务器：`/home/ubuntu/pipeline_logs`
- `init_pipeline_logging()` 仍会自动 `mkdir(parents=True, exist_ok=True)`。

这样避免 `/private/tmp` 权限问题，同时对齐用户指定的 Claude Layer B 写法。

## 5. Layer A / Layer B 独立性

本轮没有改 Layer A / Layer B 独立运行设计，只确认保持现状：

- Layer A 独立入口：`scripts/run_layer_a_once.py`
- `scripts/run_pipeline_once.py` 支持 `--layer spot / swing / all`
- Layer A scheduler：10:00 BJT
- Layer B scheduler：11:35 BJT
- Layer A 最新结果独立保存，不覆盖 Layer B strategy_run
- API overlay 最新 Layer A 给网页，不干预 Layer B

## 6. AI / HTTP timeout 状态

本轮没有修改 AI / HTTP timeout 逻辑。

上一轮已有的阶段日志、AI timeout、HTTP timeout 保护保持不变，只是日志落盘目录变为 `~/pipeline_logs`。

## 7. 原始因子 plain_reading

本轮没有改原始因子说明逻辑。

原始数据因子说明仍由 deterministic plain_reading / 规则化前端展示生成，不调用 AI。

## 8. 网页显示

本轮没有改网页 UI。

现有逻辑保持：

- “大周期策略”显示最新 Layer A 结果和独立更新时间。
- “五层分析 / 最终策略 / 虚拟账户”显示最新 Layer B 结果。
- 两者互不覆盖。

## 9. 测试命令和结果

```bash
uv run pytest -q tests/test_pipeline_progress_logging.py tests/test_layer_a_standalone_schedule.py tests/test_scheduler_2_7_a_cron.py
```

结果：`24 passed`。

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`24 passed`。

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`118 passed`。

```bash
git diff --check
```

结果：通过。

## 10. 短验证结果

Layer A 短验证：

```bash
uv run python scripts/run_layer_a_once.py --trigger manual --validate-stages
```

结果：

- 成功输出阶段日志。
- 未执行完整 AI。
- 未写数据库。
- 日志路径：`/Users/shenjun/pipeline_logs/validation_run.log`

主 pipeline 短验证：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual --validate-stages
```

结果：

- 成功输出 Layer B / Layer A 阶段日志。
- Layer B L1-L5、Master、Validator、Layer A A1-A5 均为 skipped。
- 未执行完整 AI。
- 未写数据库。
- 日志路径：`/Users/shenjun/pipeline_logs/validation_run.log`

服务器部署后，对应路径为：

```text
/home/ubuntu/pipeline_logs/validation_run.log
```

## 11. 是否影响 Layer B

否。

本轮没有修改：

- Layer B L1-L5
- Master
- Validator
- thesis
- 虚拟账户
- C 级机会行为
- 仓位、止损、止盈、开仓、平仓、反手规则

## 12. 是否影响虚拟账户

否。

## 13. 是否影响真实交易

否。

本轮没有新增真实交易接口，没有真实下单。

## 14. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 路径 / 位置 | 原因 |
|---|---|---|
| `pipeline_debug_logs` 目录名 | `src/utils/pipeline_progress.py` | 按用户要求对齐 Claude 写法，改为 `pipeline_logs` |

## 15. 风险和未完成

1. 生产服务器需要 `git pull` 并重启服务后，才会使用新日志路径。
2. 旧目录里的历史日志不会自动迁移。
3. 本轮没有跑完整 AI pipeline，只跑了短验证，完整 pipeline 由用户手动运行。

## 16. 用户后续手动命令

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

检查日志：

```bash
ls -lh /home/ubuntu/pipeline_logs
tail -80 /home/ubuntu/pipeline_logs/validation_run.log
```

刷新网页：

```text
http://124.222.89.86/
```

## 17. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 本轮提交后在最终对话中记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
