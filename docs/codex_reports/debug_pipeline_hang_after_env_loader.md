# debug_pipeline_hang_after_env_loader

## 1. 任务目标

用户手动运行 production pipeline 时,终端停在:

```text
[env_loader] loaded .env: 7 keys
```

超过 30 分钟没有新输出。  
本轮目标是查清楚卡在哪个阶段,并加最小侵入的阶段耗时日志和 timeout 保护。  
本轮不改 Layer A / Layer B 策略判断逻辑,不改交易规则,不跑无限 pipeline。

## 2. 卡住现象

服务器进程检查时发现一个仍在运行的手动 pipeline:

```text
PID 2465956
.venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

本轮没有 kill 这个生产手动进程。后续复查时该进程已自行结束,只剩 API 服务进程。

## 3. 日志检查

执行过:

```bash
ps aux | grep run_pipeline_once | grep -v grep
ps aux | grep python | grep btc_swing_system | grep -v grep
cd /home/ubuntu/btc_swing_system
find . -maxdepth 3 -type f \( -name "*.log" -o -name "*.out" \) -printf "%TY-%Tm-%Td %TH:%TM %p\n" | sort | tail -30
journalctl -u btc-strategy.service -n 200 --no-pager
```

结果:

- 项目目录下没有找到最近的 `.log` / `.out` 文件;
- `journalctl` 主要是网页 API 请求日志;
- 生产服务日志里看到 CoinGlass spot 1m 请求有 read timeout,但这属于网页实时价格接口 fallback,不是本轮手动 pipeline 卡住的直接证据;
- 手动 pipeline 自身没有 stdout 阶段日志,所以用户只能看到 env_loader 输出。

## 4. `[env_loader]` 后第一个执行阶段

代码路径:

`scripts/run_pipeline_once.py`

`[env_loader]` 后实际执行顺序是:

1. `init_db(verbose=False)`
2. `get_connection()`
3. `StrategyStateBuilder(conn, ...)`
4. `StrategyStateBuilder.run(...)`
5. 如果 `BTC_USE_ORCHESTRATOR=true`,进入 `StrategyStateBuilder._run_v13_orchestrator(...)`
6. 第一大阶段是 `ContextBuilder(self.conn).build_full_context()`

所以“卡在 env_loader 后”并不代表 env_loader 卡住,而是后续没有 stdout 进度日志。

## 5. 可能阻塞点

排查结果:

- DB / context 读取本地 SQLite,正常情况下很快;
- collector 里 CoinGlass / Glassnode / FRED 请求已有 requests timeout;
- Layer B / Layer A 的 AI agent 调用有 SDK timeout,但此前默认工厂 timeout 是 300 秒;
- `BaseAgent` 每个 agent 最多 3 次尝试,如果上游 AI 网关慢或返回 502,单层看起来会长时间无输出;
- 手动脚本没有每个阶段开始/结束日志,导致用户看到 `[env_loader]` 后像是完全卡死。

本地短验证显示,前面阶段全部很快完成,最后停在:

```text
[pipeline] START run Layer B L5 ...
```

随后 AI 中转站返回 `502 Bad Gateway`,短验证在 300 秒时按要求停止。  
因此本次可确认的实际等待点是 Layer B L5 的 AI 调用,不是 env_loader、DB 初始化或 Layer A context。

## 6. 是否发现无 timeout 的 AI / HTTP 调用

结论:

- CoinGlass collector:有 `timeout=self.timeout_sec`;
- Glassnode collector:有 `timeout=self.timeout_sec`;
- FRED collector:有 `timeout=20`;
- Anthropic client:已有 timeout 参数,但默认工厂 timeout 此前是 300 秒,用户手动运行时体感过长。

本轮低风险修复:

- 将 `src/ai/client.py` 的默认 AI SDK timeout 从 300 秒收紧到 60 秒;
- 超时仍走现有 `BaseAgent` retry / fallback / degraded 逻辑;
- 不改模型、prompt、交易判断、仓位、止损、开平仓。

## 7. 新增阶段日志

新增 `src/utils/pipeline_progress.py`,提供一个小的 `pipeline_stage(...)` 上下文管理器,只负责 stdout 打印:

```text
[pipeline] START <stage> started_at=<utc>
[pipeline] END <stage> elapsed=<seconds>s success=true
[pipeline] FAIL <stage> elapsed=<seconds>s error_type=<ExceptionType>
```

已覆盖主要阶段:

- load env
- init_db
- open_db_connection
- build StrategyStateBuilder
- run StrategyStateBuilder
- build data context
- fetch / load market data
- fetch / load derivatives data
- fetch / load onchain data
- fetch / load macro data
- fetch / load event calendar
- build Layer B context indicators
- load previous strategy_run
- compute data freshness
- build Layer A context
- run AI orchestrator
- run Layer B L1
- run Layer B L2
- run Layer B L3
- run Layer B L4
- run Layer B L5
- run Layer B Master
- validators
- run Layer A spot strategy
- run Layer A A1
- run Layer A A2
- run Layer A A3
- run Layer A A4
- run Layer A A5
- thesis persistence check
- persist strategy_run

这些日志只打印阶段耗时,不输出 prompt、API key、token、secret、完整响应或交易细节。

## 8. 改动文件

- `scripts/run_pipeline_once.py`
- `src/utils/pipeline_progress.py`
- `src/ai/context_builder.py`
- `src/ai/orchestrator.py`
- `src/pipeline/state_builder.py`
- `src/ai/client.py`
- `docs/codex_reports/debug_pipeline_hang_after_env_loader.md`

说明:`uv.lock` 在本轮开始前已有未提交修改,本轮不会提交它。

## 9. 测试结果

已运行:

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果:24 passed。

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果:118 passed。

```bash
uv run python -m py_compile scripts/run_pipeline_once.py src/ai/context_builder.py src/ai/orchestrator.py src/ai/client.py src/pipeline/state_builder.py src/utils/pipeline_progress.py
```

结果:通过。

```bash
git diff --check
```

结果:通过。

## 10. 短验证结果

本机没有 GNU `timeout`,因此使用 Python `subprocess.run(..., timeout=300)` 做等价短验证:

```bash
uv run python scripts/run_pipeline_once.py --trigger manual --dry-run
```

300 秒后按要求停止。最后可见 stage:

```text
[pipeline] START run Layer B L5 started_at=...
```

期间出现 AI 中转站 502:

```text
l5_macro: attempt 1 failed: 502 Bad Gateway
```

结论:

- 新增阶段日志有效;
- 卡点不是 `.env`、DB、数据 context 或 Layer A context;
- 短验证定位到 Layer B L5 AI 调用等待;
- 本轮没有继续长时间等待。

## 11. 是否改交易逻辑

没有。  
本轮只加 stdout 进度日志和 AI SDK 请求 timeout 保护,没有修改:

- Layer B L1-L5 / Master / Validator / thesis / 虚拟账户交易逻辑;
- Layer A A1-A5 策略判断逻辑;
- C 级机会行为;
- 仓位、止损、止盈、开仓、平仓、反手;
- 真实交易接口。

## 12. 用户后续如何手动跑 pipeline

部署本轮代码后,用户可以手动运行:

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
.venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

如果希望强制最多等 5 分钟:

```bash
cd /home/ubuntu/btc_swing_system
timeout 300 .venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

看到输出停在哪一行,就能判断卡在哪个 stage。

## 13. 删除清单 / 废弃清单

本轮无替代关系,无删除项。  
原因:本轮只新增进度日志工具并补 timeout 保护,没有替换旧交易模块。

## 14. 风险和未完成

- AI 中转站如果持续 502,即使有 60 秒 timeout,单个 agent 仍可能经历多次 retry 后 fallback;但现在用户能看到卡在哪个 layer。
- 本轮没有修改 AI retry 次数,避免改变现有降级策略。
- 生产上仍需用户执行 git pull / restart 后才能看到新进度日志。
- 若后续仍嫌单层等待过长,下一轮可专门审计 `BaseAgent` retry 次数和 per-agent 总超时,但这会更接近 AI 运行策略,需要单独评估。

## 15. 下一步建议

1. 先部署本轮日志,让下一次手动 pipeline 能看到真实卡点。
2. 如果仍停在 L5,下一轮只审计 L5 prompt 大小、中转站返回 502 频率、retry 次数和 fallback 时机。
3. 如果 L5 正常但停在其他 layer,按 stdout 最后一条 stage 定点排查。

## 16. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待提交后填写 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
