# BTC Swing System — Backlog

跨 Sprint 的待办事项,按"触发原因 + 影响面"组织。每条要么列举到 sprint
计划被采纳,要么因优先级降低被 archive。

---

## 工程债 / 架构债

### BACKLOG-AI-CONFIG-UNIFY-01:Model 配置传递路径不统一

**触发日期**:2026-06-05
**触发场景**:novaiapi distributor 把 `claude-sonnet-4-5-20250929`
通道下线,临时切换到 `claude-sonnet-4-6`。改 `.env` 的
`OPENAI_MODEL=claude-sonnet-4-6` 后,**Layer A spot_cycle_agents** 正确读
取了新 model,**Layer B L1-L5/Master** 也最终正确(restart 后)。但调查
中发现 model 配置散落在**至少 4 处**,任一漏改都会导致 fallback:

| 位置 | 类型 | 当前默认值 |
|---|---|---|
| `.env: OPENAI_MODEL` | env var(优先) | (用户配) |
| `config/ai.yaml:53 adjudicator.model_name_default` | hardcoded fallback | claude-sonnet-4-6 |
| `config/ai.yaml:94 layer5_macro_summary.model_name_default` | hardcoded fallback | claude-sonnet-4-6 |
| `src/ai/client.py:30 DEFAULT_MODEL` | Python module level | claude-sonnet-4-6 |
| `src/ai/summary.py:36 _DEFAULT_MODEL` | Python module level | claude-sonnet-4-6 |

**问题**:
1. **多副本就是真相分裂**:本次调试时发现这 4 处的值必须人工保持同步,
   否则 env 没传到 / Python 路径绕过 yaml 等情况都会触发 hardcoded
   `4-5-20250929` fallback
2. **调试反馈不直观**:每个 agent 失败时 log 里写 `model_requested:
   <hardcoded>`,看起来像 env 没设,但 env 其实是设了的 — 用户被误
   导,排查时间从 5 分钟变成 1 小时
3. **未来切换 model 风险**:如果只改 `.env` 不改 yaml 默认值,在某次
   重启 / 错传 env / 别人误改 env 时,系统会静默 fallback 到 hardcoded
   value(可能是个已经下线的 model)

**修复方向**(等独立 sprint):
- 让所有 model 名读取统一走 `src/ai/_env_loader.py` 之类的单一入口
- 入口函数明文:`def resolve_ai_model(env_key="OPENAI_MODEL",
  yaml_path="adjudicator.model_name_default") -> str`
- 删除 client.py / summary.py 里的 `DEFAULT_MODEL` hardcoded —
  改成显式从 ai.yaml 注入
- 任何 hardcoded `claude-sonnet-X-Y` 字面量都视为 lint 错误

**触发时机**:下次需要切换 model(预期 sonnet-4-7 / sonnet-5 上线时)
或者 sprint backlog 里 AI infra 相关任务排到时

### BACKLOG-AI-FAILURE-LOGGING-01:中转站 silent timeout 没有打印 attempt

**触发日期**:2026-06-05
**触发场景**:用 sonnet-4-6 跑 Layer A,前一次 120s timeout 触发后,
全无 attempt failed 日志,只有 stage END `status=degraded elapsed=160s`。
对比 sonnet-4-5 失败时清晰的 `attempt 1/2/3 failed Error code: 503`,
4-6 silent timeout 模式让调试时无法立刻定位是 timeout 还是 5xx。

**修复方向**:
- `src/ai/agents/_base.py:_call_ai_with_retry` 在每次 attempt 内捕获
  `TimeoutError` 时显式 logger.warning(...)
- 区分"中转站 hang" vs "我方 timeout 触发" 在日志里

**优先级**:低(已通过 timeout 抬高绕过,但下次中转站故障复发时还会踩)

---

## 数据 / 采集

### BACKLOG-COLLECTOR-COMMIT-01:`collect_and_save_all` 不自动 commit

**触发日期**:2026-06-05
**触发场景**:Glassnode 通道恢复后,手动调
`GlassnodeCollector.collect_and_save_all(conn)` 返回 success counts 字典
(180 / 720 等),看起来一切正常 — 但 DB 0 行入库,因为调用方没
`conn.commit()`,close 时 rollback。这个 bug 让用户以为 collector
真在跑,实际数据完全没更新。

**修复方向**:
- 让 `collect_and_save_all` 内部自动 commit,或在 docstring 显式说明
  "调用方必须 commit"
- 或加 commit 防御:函数最后一行 `conn.commit()`,失败也不报错

**优先级**:中(scheduler 端调用是 OK 的,因为 scheduler 自带 commit;
但 backfill / 手动 / 测试容易踩)

---

## 文档 / 纪律

### BACKLOG-CLAUDE-MD-SYNC:删 AI 判断层时同步改 CLAUDE.md

**触发日期**:2026-06-08
**触发场景**:项目方向调整为"保留数据采集 + 退出本系统内 AI 判断 + 简化网页",
新增 `/api/export/snapshot.md` 端点供外部 AI 读数据自己判。但 CLAUDE.md 里
以下段落仍按"AI 判断在系统内"假设写:

- **§双轨输出原则**(L19-36):"AI 只参与综合裁决,不参与因子解释" — 一旦
  Master / L5 删除,这条原则失效
- **§合规 AI 出口清单**(L28-32):#1 Master、#2 L5 — 删除后清单为空
- **§系统硬纪律 #10 AI 裁决 System Prompt**(L73-75):指向已删除的 prompt 段
- **§工程纪律 §X 旧代码必须删除**(L199-232):举例仍引用 `master_adjudicator`、
  `l5_macro_analyst` — 这俩本身就是要删的对象

**修复方向**(等"AI 判断层删除"sprint):
- 删除上述 4 段或改写为"用户外部 AI 工作流"语义
- 在 §合规 AI 出口清单 加 #3 `/api/export/snapshot.md`(供外部 AI 的唯一出口)
- 把"双轨输出"重写为"数据采集 + 数据导出"

**触发时机**:启动"删 AI 判断层 + 简化网页"sprint 时,CLAUDE.md 改动必须
作为该 sprint 的一部分一起 commit,不能事后补

---

### BACKLOG-TESTS-54f89a5-DRIFT:Sprint sonnet-4-6 切换遗留 4 个 test 失败

**触发日期**:2026-06-08
**触发场景**:commit 54f89a5(sonnet-4-6 + timeout 120→180)未更新对应测试,
全量 pytest 暴露 4 个 pre-existing 失败:

| 测试 | 失败点 | 根因 |
|---|---|---|
| `test_ai_client_default_timeout_is_120_seconds` | `assert DEFAULT_TIMEOUT_SEC == 120.0` | 已改 180 |
| `test_restricted_model_error_uses_configured_fallback` | hardcoded `claude-sonnet-4-5-20250929` | 已切 4-6 |
| `test_overloaded_error_uses_fallback_after_short_retry` | 同上 | 同上 |
| `test_jobs_fetch_attempts_integration::test_collect_klines_1h_kline_succeeds_derivatives_fail` | 期望 `api_error`,实际 `provider_error` | failure_reason 分类语义漂移 |

**修复方向**:
- 前 3 个:改 assertion 跟随 54f89a5(`120.0 → 180.0`、`4-5-20250929 → 4-6`)
- 第 4 个:对齐 collector 实际 failure_reason 分类(`api_error` → `provider_error`)
- 一次 commit 修完,或纳入 BACKLOG-AI-CONFIG-UNIFY-01 sprint 一起做

**优先级**:中(不影响生产,只是回归 baseline 持续显示 4 fail)

---
