# fix_ai_fallback_and_run_layer_a_ready_command

## 1. 任务目标

本轮目标是继续优化 AI 调用稳定性，让 Layer A 可以更可靠地完整运行，不再因为 A2/A3 模型过载或 403 restricted 卡住几百秒。

本轮只允许修改 AI client / BaseAgent retry / timeout / fallback 支持，不改 Layer A / Layer B 策略逻辑，不改 prompt，不改网页，不真实交易。

## 2. 当前 primary model / base_url 脱敏信息

| 项 | 当前值 |
|---|---|
| provider / SDK | `anthropic` Python SDK |
| base_url host | `https://us.novaiapi.com` |
| primary model | `claude-sonnet-4-5-20250929` |
| API key | `OPENAI_API_KEY=<exists, hidden>` |
| Anthropic key | `ANTHROPIC_API_KEY=missing` |
| SDK hidden retry | 已关闭，`max_retries=0` |
| 单次请求 timeout | 默认 `120s`，health check 使用 `30s` |

说明：`.env` 只检查变量名与是否存在，没有输出任何 key/token/secret。

## 3. Fallback model 状态

当前没有可用 fallback model 配置。

检查结果：

- `.env` 未发现 `OPENAI_FALLBACK_MODEL`
- `.env` 未发现 `OPENAI_FALLBACK_MODELS`
- `config/ai.yaml` 本轮新增了空的 `fallback_models` 配置段，但没有填入任何未验证模型

本轮实现了 fallback model 支持：

1. 优先读取 `OPENAI_FALLBACK_MODELS`，支持逗号分隔多个模型。
2. 其次读取 `OPENAI_FALLBACK_MODEL`。
3. 最后读取 `config/ai.yaml::fallback_models.model_name_defaults`。
4. 自动过滤掉与 primary 相同的模型和重复项。

没有乱填 fallback model 的原因：

- 当前没有项目内证据能证明某个备用模型在 `us.novaiapi.com` 上稳定可用。
- 不能把未验证模型伪装成已可用。

## 4. Primary health check 结果

命令：

```bash
uv run python scripts/check_ai_provider_health.py --timeout 30
```

脱敏结果：

```json
{
  "anthropic_api_key": "missing",
  "fallback": "no_fallback_model_configured",
  "openai_api_key": "exists_hidden",
  "primary": {
    "base_url_host": "https://us.novaiapi.com",
    "elapsed_seconds": 3.72,
    "error_message_summary": null,
    "error_type": null,
    "model": "claude-sonnet-4-5-20250929",
    "provider": "anthropic_sdk_via_configured_base_url",
    "response_model": "claude-sonnet-4-5-20250929",
    "status": "ok",
    "timeout_sec": 30.0
  }
}
```

结论：

- 当前 primary model 最小 ping 可用。
- 这说明 A2/A3 的失败不是“模型永久不可用”。
- 更可能是中转站 / 上游 provider 的间歇性 overloaded 或 restricted 路由问题。

## 5. Fallback health check 结果

当前没有 fallback model 配置，因此未测试 fallback。

health check 输出：

```text
fallback = no_fallback_model_configured
```

## 6. 403 restricted 处理方式

本轮继续保留并完善上一轮修复：

- 识别 401 / 403 为 terminal error。
- 识别错误文案：
  - `restricted to Claude Code clients only`
  - `cannot be accessed through other API clients`
  - `permission denied`
  - `invalid api key`
  - `unauthorized`
- primary 遇到 403 restricted 时，不再重试 primary。
- 如果配置了 fallback model，立即切 fallback。
- 如果没有 fallback model，立即 degraded。

这能避免 A3 这种“权限错误还反复重试”的无意义等待。

## 7. 500 overloaded 处理方式

本轮逻辑：

- 识别 overloaded 文案：
  - `model is currently overloaded`
  - `当前模型过载`
  - `overloaded`
- primary 遇到 overloaded 时，最多短重试 1 次。
- 第二次仍 overloaded，则切 fallback。
- 如果没有 fallback model，则 degraded。

这能避免 A2 因 overloaded 重试太久而拖到几百秒。

## 8. Timeout 处理方式

本轮逻辑：

- Anthropic SDK 初始化仍有显式 timeout。
- SDK 内部隐藏 retry 继续关闭：`max_retries=0`。
- Timeout 被识别为不可继续重试的错误。
- 如果配置 fallback model，timeout 后切 fallback。
- 如果没有 fallback model，立即 degraded。

注意：单次请求仍可能等待到 timeout 上限，但不会再被 SDK hidden retry 放大。

## 9. 日志改进

每次 AI 失败会记录：

- agent name
- model
- attempt
- fallback_used
- elapsed_ms
- error_type
- retryable
- error 摘要

不会输出 API key / token / secret。

## 10. 是否关闭 SDK 内部 retry

是。

`src/ai/client.py` 中 `build_anthropic_client()` 显式传入：

```python
max_retries=0
```

## 11. 是否仍存在外层 retry

是。

项目外层 `BaseAgent` 仍保留显式 retry，因为它有：

- 可观测日志
- fallback 输出
- tokens / latency 记录
- 错误分类

但它现在会：

- 403 直接停
- timeout 直接停
- overloaded 最多短重试一次
- 配置 fallback 后自动切 fallback

## 12. 改动文件

本轮改动：

- `config/ai.yaml`
- `src/ai/client.py`
- `src/ai/agents/_base.py`
- `scripts/check_ai_provider_health.py`
- `tests/test_ai_client.py`
- `tests/test_sprint_i_base_agent_retry.py`
- `docs/codex_reports/fix_ai_fallback_and_run_layer_a_ready_command.md`

未纳入提交：

- `uv.lock`：既有未提交改动，本轮未改依赖，不属于本轮范围。

## 13. 测试命令和结果

```bash
uv run pytest -q tests/test_ai_client.py tests/test_sprint_i_base_agent_retry.py tests/test_pipeline_progress_logging.py
```

结果：`20 passed`。

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`24 passed`。

```bash
uv run python -m py_compile scripts/check_ai_provider_health.py src/ai/client.py src/ai/agents/_base.py
```

结果：通过。

```bash
git diff --check
```

结果：通过。

## 14. Validate-stages 结果

命令：

```bash
uv run python scripts/run_layer_a_once.py --trigger manual --validate-stages
```

结果：

- 成功。
- 未执行完整 AI。
- 未写数据库。
- 日志路径：`/Users/shenjun/pipeline_logs/validation_run.log`
- 部署到服务器后，对应路径为：`/home/ubuntu/pipeline_logs/validation_run.log`

## 15. 是否影响 Layer A 策略逻辑

否。

本轮不改 A1-A5 prompt，不改现货策略判断逻辑。

## 16. 是否影响 Layer B 策略逻辑

否。

本轮不改 L1-L5 / Master / Validator / thesis / C 级机会 / 虚拟账户。

## 17. 是否影响虚拟账户

否。

## 18. 是否影响真实交易

否。

本轮没有新增真实交易接口，没有真实下单。

## 19. 用户最终手动命令

部署最新代码：

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

如果用户只想先验证日志：

```bash
.venv/bin/python scripts/run_layer_a_once.py --trigger manual --validate-stages
tail -80 /home/ubuntu/pipeline_logs/validation_run.log
```

刷新网页：

```text
http://124.222.89.86/
```

## 20. 下一步建议

P0：

- 在中转站确认一个普通 Python API 可调用的 fallback model。
- 确认后配置到 `.env`：

```bash
OPENAI_FALLBACK_MODEL=<普通 API 可用模型名>
```

或多个：

```bash
OPENAI_FALLBACK_MODELS=<模型A>,<模型B>
```

P1：

- 配好 fallback 后再运行：

```bash
.venv/bin/python scripts/check_ai_provider_health.py --timeout 30
```

确认 primary 和 fallback 都可用。

P2：

- 未来可以按 agent 分模型，例如 A2/A3 使用更稳模型，Master 使用更强模型。
- 这属于模型配置优化，不应和交易逻辑改动混在一起。

## 21. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 本轮提交后在最终对话中记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
