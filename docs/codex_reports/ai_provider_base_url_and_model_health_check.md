# ai_provider_base_url_and_model_health_check

## 1. 任务目标

本轮只做 AI provider / base_url / model / client 的根因审计和最小健康检查。

背景问题：

- 用户在服务器手动运行 Layer A。
- `validate-stages` 正常，日志已写入 `/home/ubuntu/pipeline_logs`。
- A1 成功，耗时约 44 秒。
- A2 出现 `500 model overloaded`，之后较长时间 degraded。
- A3 出现 `403 This model is restricted to Claude Code clients only and cannot be accessed through other API clients.`

本轮目标：

- 查清项目当前 pipeline 使用哪个 AI provider / base_url / model / client。
- 判断 403 是否为 Claude Code 专用模型 / 凭证 / 路由问题。
- 判断 500 overloaded 是否为中转站或上游负载问题。
- 做最小 ping 健康检查。
- 允许低风险修复 AI 错误分类、隐藏 retry、timeout/retry 放大问题。
- 不改 Layer A / Layer B 策略逻辑，不改 prompt，不改网页，不真实交易。

## 2. 当前 AI 配置脱敏摘要

| 项 | 当前值 |
|---|---|
| SDK / provider | `anthropic` Python SDK |
| 协议 | Anthropic Messages API 风格 |
| base_url 域名 | `https://us.novaiapi.com` |
| API key 变量 | `OPENAI_API_KEY=<exists, hidden>` |
| Anthropic key 变量 | `ANTHROPIC_API_KEY=missing` |
| model 变量 | `OPENAI_MODEL` |
| 当前 model | `claude-sonnet-4-5-20250929` |
| fallback model | 未发现 `OPENAI_FALLBACK_MODEL` 配置 |
| 默认 max_tokens | BaseAgent 默认 `2048`，config adjudicator `4000`，L5 config `800` |
| 单次 AI timeout | 当前代码默认 `120s` |
| 外层 BaseAgent retry | 普通临时错误最多 3 次 |
| retry sleep | `2s` |
| SDK 内部 retry | 本轮修复后已显式 `max_retries=0` |

说明：

- `.env` 只检查了变量名与是否存在，没有输出任何 key/token/secret。
- `OPENAI_API_BASE` / `OPENAI_API_KEY` 是历史兼容命名；代码实际使用的是 `anthropic` SDK。
- `OPENAI_API_BASE` 指向中转站 `us.novaiapi.com`，不是 Anthropic 官方直连域名。

## 3. Layer A A1-A5 使用模型

Layer A A1-A5 都继承 `BaseAgent`，未单独传 model override，因此都使用：

```text
effective_model() -> OPENAI_MODEL -> claude-sonnet-4-5-20250929
```

| Layer A agent | prompt 文件 | model |
|---|---|---|
| A1 `a1_spot_cycle` | `a1_spot_cycle.txt` | `claude-sonnet-4-5-20250929` |
| A2 `a2_onchain_macro` | `a2_onchain_macro.txt` | `claude-sonnet-4-5-20250929` |
| A3 `a3_spot_opportunity` | `a3_spot_opportunity.txt` | `claude-sonnet-4-5-20250929` |
| A4 `a4_spot_risk` | `a4_spot_risk.txt` | `claude-sonnet-4-5-20250929` |
| A5 `a5_spot_adjudicator` | `a5_spot_adjudicator.txt` | `claude-sonnet-4-5-20250929` |

## 4. Layer B L1-L5 / Master 使用模型

Layer B L1-L5 / Master 也继承 `BaseAgent`，未单独传 model override，因此默认同一个模型。

| Layer B agent | prompt 文件 | model |
|---|---|---|
| L1 `l1_regime` | `l1_regime.txt` | `claude-sonnet-4-5-20250929` |
| L2 `l2_direction` | `l2_direction.txt` | `claude-sonnet-4-5-20250929` |
| L3 `l3_opportunity` | `l3_opportunity.txt` | `claude-sonnet-4-5-20250929` |
| L4 `l4_risk` | `l4_risk.txt` | `claude-sonnet-4-5-20250929` |
| L5 `l5_macro` | `l5_macro.txt` | `claude-sonnet-4-5-20250929`，除非设置 `OPENAI_L5_MODEL` |
| Master `master_adjudicator` | `master_adjudicator.txt` | `claude-sonnet-4-5-20250929` |

结论：当前 Layer A 和 Layer B 所有主要 AI agent 共用同一个 base_url / key / model。

## 5. 当前 AI client 实现

代码路径：

- `src/ai/client.py`
- `src/ai/agents/_base.py`

当前实现：

1. 使用 `anthropic` Python SDK。
2. 通过 `OPENAI_API_BASE` 配置中转站 base_url。
3. 通过 `OPENAI_API_KEY` 传入 API key。
4. `normalize_base_url()` 会去掉 `/v1` 后缀，避免 Anthropic SDK 拼接重复路径。
5. `BaseAgent` 外层负责重试、fallback、JSON 解析、tokens/latency 记录。

本轮发现：

- 修改前，Anthropic SDK 可能存在内部隐藏 retry。
- 项目外层 `BaseAgent` 又有最多 3 次 retry。
- 两层 retry 叠加，会把一个 agent 的失败时间放大到几分钟。

本轮低风险修复：

- `build_anthropic_client(..., max_retries=0)`，关闭 SDK 隐藏 retry。
- 保留项目外层 BaseAgent retry，因为它有明确日志和 fallback。

## 6. 最小 ping 测试结果

新增只读脚本：

```bash
scripts/check_ai_provider_health.py
```

执行命令：

```bash
uv run python scripts/check_ai_provider_health.py --timeout 30
```

脱敏结果：

```json
{
  "openai_api_key": "exists_hidden",
  "anthropic_api_key": "missing",
  "primary": {
    "provider": "anthropic_sdk_via_configured_base_url",
    "base_url_host": "https://us.novaiapi.com",
    "model": "claude-sonnet-4-5-20250929",
    "timeout_sec": 30.0,
    "status": "ok",
    "elapsed_seconds": 3.57,
    "response_model": "claude-sonnet-4-5-20250929"
  },
  "fallback": "no_fallback_model_configured"
}
```

解释：

- 同一个 model 当前最小 ping 可以成功。
- 因此不能简单判断“这个 model 永远不能被普通 Python pipeline 调用”。
- 但历史 A3 的 403 说明：中转站或上游路由中，存在某个 channel / provider 返回了 Claude Code 客户端限制。

## 7. 403 restricted 根因判断

历史错误：

```text
This model is restricted to Claude Code clients only and cannot be accessed through other API clients.
```

判断：

1. 这不是 prompt 太长、数据太多导致。
2. 这不是原始因子说明调用 AI 导致。
3. 这是 provider / 中转站 / 上游 channel 的模型权限错误。
4. 当前配置使用 `OPENAI_API_KEY` 经过 `us.novaiapi.com` 代理，不是官方 `ANTHROPIC_API_KEY` 直连。
5. 最小 ping 成功，说明该 model 在某些路由下可用；但 A3 历史 403 说明中转站可能路由到 Claude Code 专用后端或受限 channel。

本轮修复：

- 403 / restricted 被归类为 terminal error。
- 这类错误不再重试。
- 立即返回 degraded fallback，避免 A3 等无意义重试。

## 8. 500 overloaded 根因判断

历史错误：

```text
Provider API error: 当前模型过载 / That model is currently overloaded
```

判断：

1. 这是中转站或上游模型负载问题。
2. 不是 Layer A 数据太多的直接证据。
3. 因为最小 ping 当前成功，说明并非所有请求都持续 overloaded。
4. 当前没有 fallback model 配置，所以 overloaded 时只能 retry 或 degraded。

本轮修复：

- overloaded 最多短重试 1 次。
- 第二次仍 overloaded 时立即 degraded。
- 不再尝试第三次，避免单个 agent 拖到几百秒。

## 9. A2 为什么耗时约 425 秒

根因是 retry / timeout 放大，而不是交易逻辑本身。

修复前链路：

1. `BaseAgent` 外层最多 3 次 attempt。
2. 每次 attempt 的 client timeout 是 120 秒。
3. Anthropic SDK 还可能有内部隐藏 retry。
4. 中转站 overloaded / 上游慢返回时，请求会在 read 等待中消耗大量时间。

因此一个 agent 在最坏情况下可能接近：

```text
外层 3 次 × 单次 120 秒 + SDK 内部 retry / 上游等待 / sleep
```

这能解释 A2 为什么不是几十秒结束，而是拖到几百秒。

本轮修复后：

- SDK 隐藏 retry 关闭。
- 403 不重试。
- overloaded 最多 2 次外层 attempt。
- 日志会输出 agent/model/attempt/elapsed/error_type/retryable。

## 10. 是否发现 Claude Code 专用模型 / 凭证被 pipeline 使用

审计结论：

- 当前模型名：`claude-sonnet-4-5-20250929`。
- 当前 key 变量：`OPENAI_API_KEY=<exists, hidden>`。
- 当前 `ANTHROPIC_API_KEY` 未配置。
- 当前 base_url：`https://us.novaiapi.com`。

无法在不查看 key 原文的情况下判断这个 key 是否来自 Claude Code OAuth/session。

但从 403 文案看，至少有一次请求被中转站 / 上游判定为“Claude Code clients only”。这更像中转站路由或模型权限问题，而不是策略 prompt 问题。

## 11. 是否是 prompt 太长 / 数据太多问题

当前证据不支持“主要是 prompt 太长 / 数据太多”。

理由：

- A3 返回 403 restricted，这是权限 / client 类型错误。
- A2 返回 500 overloaded，这是上游负载错误。
- 最小 ping 当前可用，说明通道不是完全坏，但可能不稳定。

不过，Layer A A2 输入链上 / 宏观 context 较大，可能会增加模型处理耗时，但它不是 403 的根因。

## 12. 本轮是否改代码

有，属于低风险 AI 错误处理修复，不涉及策略判断。

改动文件：

- `src/ai/client.py`
- `src/ai/agents/_base.py`
- `scripts/check_ai_provider_health.py`
- `tests/test_ai_client.py`
- `tests/test_sprint_i_base_agent_retry.py`
- `docs/codex_reports/ai_provider_base_url_and_model_health_check.md`

修复内容：

1. 关闭 Anthropic SDK 内部隐藏 retry：`max_retries=0`。
2. 403 / Claude Code restricted 归类为 terminal error，不重试。
3. overloaded 最多短重试 1 次。
4. AI 失败日志增加 agent/model/attempt/elapsed/error_type/retryable。
5. 新增只读健康检查脚本。

没有修改：

- Layer A A1-A5 prompt
- Layer B L1-L5 / Master prompt
- Validator / thesis / 虚拟账户
- 仓位、止损、止盈、开仓、平仓、反手
- 网页 UI

## 13. 测试和检查命令

```bash
uv run python scripts/check_ai_provider_health.py --timeout 30
```

结果：`status=ok`，最近一次耗时约 `3.57s`。

```bash
uv run pytest -q tests/test_ai_client.py tests/test_sprint_i_base_agent_retry.py tests/test_pipeline_progress_logging.py
```

结果：`17 passed`。

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`24 passed`。

```bash
git diff --check
```

结果：通过。

## 14. 是否影响 Layer A 策略逻辑

否。

本轮只改 AI provider 错误处理与健康检查脚本，不改 A1-A5 策略判断逻辑。

## 15. 是否影响 Layer B 策略逻辑

否。

本轮不改 Layer B L1-L5 / Master / Validator / thesis / C 级机会。

## 16. 是否影响虚拟账户

否。

## 17. 是否影响真实交易

否。

本系统仍未接真实交易。本轮也没有新增真实交易能力。

## 18. 下一步建议

P0：

- 用户需要检查中转站 `us.novaiapi.com` 对 `claude-sonnet-4-5-20250929` 的可用性和权限配置。
- 如果中转站把请求路由到 Claude Code only channel，需要更换普通 API 可调用的模型或 channel。

P1：

- 增加明确的 `OPENAI_FALLBACK_MODEL` 配置，例如一个确认普通 API 可用、稳定性更高的模型。
- Layer A / Layer B 可以继续共用主模型，但 overloaded 时 fallback 到备用模型。

P2：

- 后续可把不同 agent 的 model 显式配置化，例如 A2/A3 使用更稳的模型，Master 使用更强模型。
- 这属于模型配置优化，不应混入交易逻辑修改。
