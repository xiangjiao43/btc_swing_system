# fix_pipeline_log_permission_issue

## 1. 任务目标

修复 pipeline 阶段日志在服务器上可能写入 `/private/tmp/pipeline_debug_logs` 时遇到 `PermissionError` 的问题。

本轮目标：

- 把 pipeline 阶段日志目录改成当前运行用户主目录下的 `pipeline_debug_logs`。
- 服务器 ubuntu 用户运行时，日志路径变为 `/home/ubuntu/pipeline_debug_logs`。
- 本地运行时，日志路径变为当前本机用户主目录下的 `pipeline_debug_logs`。
- 保留 Layer A / Layer B 阶段日志、AI timeout、HTTP timeout 保护。
- 不改 Layer A / Layer B 策略判断逻辑。
- 不改 Layer B L1-L5 / Master / Validator / thesis / 虚拟账户逻辑。

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
- `docs/codex_reports/fix_pipeline_log_permission_issue.md`

未纳入提交：

- `uv.lock`：这是既有未提交改动，本轮未改依赖，不属于本轮修复范围。

## 4. 修复内容

修复前：

```python
LOG_DIR = Path("/private/tmp/pipeline_debug_logs")
```

修复后：

```python
LOG_DIR = Path.home() / "pipeline_debug_logs"
```

含义：

- 在服务器上用 `ubuntu` 用户运行时，日志目录是 `/home/ubuntu/pipeline_debug_logs`。
- 在本地运行时，日志目录是当前用户主目录下的 `pipeline_debug_logs`。
- `init_pipeline_logging()` 仍会执行 `mkdir(parents=True, exist_ok=True)`，确保目录不存在时自动创建。

这只改变日志落盘位置，不改变任何交易判断。

## 5. Layer A / Layer B 影响

不影响 Layer A 策略逻辑。

不影响 Layer B 策略逻辑。

本轮没有修改：

- Layer B L1-L5 prompt
- Master 主裁
- Validator 交易约束
- thesis 创建 / 持久化
- 虚拟账户
- 仓位、止损、止盈、开仓、平仓、反手规则
- Layer B C 级机会行为

Layer A 独立运行仍保持：

- 10:00 BJT 单独调度
- 不调用 Layer B
- 不创建 thesis
- 不进入虚拟账户
- 只更新 Layer A 最新结果

Layer B 仍保持：

- 11:35 BJT 主 pipeline
- 不依赖 Layer A 输出

## 6. Pipeline 日志验证

短验证命令：

```bash
uv run python scripts/run_layer_a_once.py --trigger manual --validate-stages
```

结果：

- 成功输出阶段日志。
- 未执行完整 AI。
- 未写数据库。
- 日志路径显示为：`/Users/shenjun/pipeline_debug_logs/validation_run.log`

同一代码到服务器后会变成：

```text
/home/ubuntu/pipeline_debug_logs/validation_run.log
```

短验证命令：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual --validate-stages
```

结果：

- 成功输出 Layer B / Layer A 阶段日志。
- Layer B L1-L5、Master、Validator、Layer A A1-A5 均为 skipped。
- 未执行完整 AI。
- 未写数据库。
- 日志路径显示为：`/Users/shenjun/pipeline_debug_logs/validation_run.log`

## 7. 测试命令和结果

```bash
uv run pytest -q tests/test_pipeline_progress_logging.py
```

结果：`3 passed`。

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

## 8. AI / HTTP timeout 状态

本轮没有改 AI / HTTP timeout 逻辑，只保留上一轮已有保护。

日志路径修改后，超时 / degraded / skipped / failure 仍会写入新的用户主目录日志文件。

## 9. 是否自动跑完整 pipeline

没有。

本轮只跑 `--validate-stages` 短验证，避免触发完整 AI 等待。

## 10. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 路径 / 位置 | 原因 |
|---|---|---|
| 固定日志目录 `/private/tmp/pipeline_debug_logs` | `src/utils/pipeline_progress.py` | 服务器上可能因目录权限导致 `PermissionError`，已改为用户主目录可写路径 |

## 11. 风险和未完成

1. 生产服务器需要 `git pull` 并重启服务后，才会使用新日志路径。
2. 如果服务器上曾经有旧 `/private/tmp/pipeline_debug_logs` 日志，本轮不迁移旧日志。
3. 本轮没有跑完整 AI pipeline，完整 pipeline 需要用户在服务器手动运行验证。

## 12. 用户后续手动命令

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
ls -lh /home/ubuntu/pipeline_debug_logs
tail -80 /home/ubuntu/pipeline_debug_logs/validation_run.log
```

刷新网页：

```text
http://124.222.89.86/
```

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 本轮提交后在最终对话中记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
