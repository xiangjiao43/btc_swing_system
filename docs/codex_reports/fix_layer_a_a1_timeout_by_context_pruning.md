# 修复 Layer A A1 超时：精简 A1 Context 报告

## 1. 任务目标

用户手动运行 Layer A 时，A1 大周期阶段分析出现 120 秒 timeout，并退回 degraded/fallback。A1 是 Layer A 大周期策略核心，不能长期依赖 fallback。

本轮目标：
- 查清 A1 为什么慢。
- 不通过简单拉长 timeout 解决。
- 为 A1 新增专用轻量 context，只保留大周期阶段判断必要数据。
- 保留五阶段状态机原则：五阶段、raw_stage / official_stage、连续确认、禁止跳级。
- 不改 Layer B、不改交易逻辑、不改真实交易。

## 2. 读取文件

- `AGENTS.md`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_cycle_stage_state.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/orchestrator.py`
- `src/pipeline/layer_a_spot_runner.py`
- `src/ai/agents/spot_cycle_agents.py`
- `src/ai/agents/_base.py`
- `config/ai.yaml`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_spot_normalize.py`
- `tests/test_layer_a_orchestrator_integration.py`
- `docs/codex_reports/layer_a_five_stage_state_machine_and_factor_finalization.md`
- 最新本地 Layer A 验证日志：`/Users/shenjun/pipeline_logs/pipeline_20260515T051000Z_35768_1778821800803078000_layer_a_manual.jsonl`

说明：用户给出的服务器日志路径在本地不可直接读取，但用户贴出的关键信息已明确：A1 `APITimeoutError`，elapsed 约 120 秒；本轮用本地同配置构建了 before/after context size，并跑了一次完整 Layer A 验证。

## 3. A1 超时原因分析

A1 之前收到的是完整 `spot_cycle_context`：

- `available_factors` 全量因子树
- `factor_role_classification` 全量 A/B/C/D 分类表
- `unavailable_factors`
- `factor_coverage`
- `data_quality_notes`
- `series_samples`
- Layer A boundaries

这对 A1 来说太重。A1 只需要判断“大周期阶段当前像什么”，不需要：

- Layer B 短线衍生品细节；
- 原始因子网页卡片字段；
- 完整 factor role 分类；
- 时间序列 tail；
- 所有 unavailable candidate 明细；
- A2/A3/A4/A5 用的完整 context。

本地 size 诊断：

| 项目 | 修复前 | 修复后 |
|---|---:|---:|
| A1 prompt chars | 约 3212 | 1490 |
| A1 user context chars | 48530 | 6378 |
| A1 user context tokens 估算 | 12132 | 1594 |
| A1 context top-level keys | `spot_cycle_context` | `stage_model`, `cycle_evidence_summary`, `recent_stage_history`, `instructions` |

最长的旧字段主要是：
- `factor_role_classification.a1_core`
- `factor_role_classification.a2_a4_background`
- `factor_role_classification.not_suitable_or_unavailable`
- `series_samples.*`
- `data_quality_notes`

结论：A1 超时主要是 context 太大 + prompt 偏长 + provider 正常响应慢的组合原因；不是交易逻辑问题，也不是状态机本身导致。

## 4. 新增 A1 专用轻量 context

新增 helper：

- `build_a1_cycle_stage_context(context)`

输出结构：

```json
{
  "stage_model": {},
  "cycle_evidence_summary": {},
  "recent_stage_history": [],
  "instructions": {}
}
```

### 保留数据

A1 现在只看：

1. 价格周期位置摘要
   - BTC price
   - ATH drawdown
   - 200D / 200W
   - realized price
   - STH/LTH realized price

2. 链上估值摘要
   - MVRV Z
   - MVRV
   - NUPL
   - RHODL Ratio
   - Reserve Risk
   - Puell Multiple

3. 持有人结构摘要
   - LTH SOPR
   - STH SOPR
   - LTH/STH supply
   - LTH net position change
   - supply in profit/loss
   - HODL waves
   - CDD

4. 交易所/资金流摘要
   - exchange balance
   - exchange net position change
   - exchange net flow 30d
   - ETF 7d / 30d flow summary

5. 宏观背景摘要
   - real yield
   - fed funds
   - US2Y
   - DXY / VIX / Nasdaq
   - M2
   - Fed balance sheet
   - CPI / Core CPI

6. 数据质量摘要
   - confidence cap
   - confidence cap reason
   - critical unavailable count
   - stale factor count
   - missing integrated factor count
   - coverage notes

7. 历史阶段摘要
   - previous official stage
   - previous raw stage
   - transition status
   - confirmation count / required
   - previous A5 action

### 移除输入

A1 不再接收：
- `available_factors` 全量树；
- `factor_role_classification` 全量表；
- `series_samples`；
- funding / OI / liquidation / long-short ratio；
- Layer B L1-L5 / Master 全量内容；
- 原始因子 plain_reading 长文本；
- 网页展示字段；
- 完整历史 run JSON。

## 5. A1 prompt 压缩

`a1_spot_cycle.txt` 已重写为短 prompt：

- 明确只输出 5 个 raw_stage。
- 明确 official_stage 由系统状态机确认。
- 明确不要写长篇报告。
- `human_summary` 限制 1-2 句、80 字以内。
- 支持/反方/冲突证据各最多 3 条。
- 宏观只作置信度和反方证据。
- 不重复列出所有指标。

## 6. 日志增强

A1 调用前新增阶段日志：

`Layer A A1 input size`

日志记录：
- `a1_prompt_context_chars`
- `a1_estimated_context_tokens`
- `a1_context_top_keys`
- `a1_history_count`
- `timeout_sec`

本轮验证日志显示：

```text
Layer A A1 input size:
a1_prompt_context_chars=6378
a1_estimated_context_tokens=1594
a1_context_top_keys=[stage_model, cycle_evidence_summary, recent_stage_history, instructions]
a1_history_count=0
timeout_sec=120
```

## 7. 状态机是否保持

保持。

没有改五阶段状态机原则：
- `deep_value`
- `accumulation`
- `trend_hold`
- `distribution`
- `overheated_exit`

没有改：
- raw_stage / official_stage 拆分；
- 连续确认；
- 禁止跨级直接确认；
- 数据质量 cap；
- A5 使用 official_stage；
- Layer A 不进入虚拟账户；
- Layer A 不创建 thesis；
- Layer A 不影响 Layer B 开平仓。

## 8. 测试命令和结果

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`33 passed`

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`139 passed`

```bash
git diff --check
```

结果：通过。

## 9. Layer A 手动运行结果

本轮只运行一次完整 Layer A：

```bash
uv run python scripts/run_layer_a_once.py --trigger manual
```

结果摘要：

| 字段 | 结果 |
|---|---|
| run_id | `625f041820d7429dacd3a52163181e56` |
| persisted | true |
| status | success |
| A1 status | success |
| A1 elapsed | 18.107 秒 |
| A1 cycle stage | accumulation |
| A5 spot action | hold |
| validator_passed | true |
| degraded_stages | [] |
| failures | [] |

验收结论：A1 已从 120 秒 timeout/degraded 变为 18 秒 success。

## 10. 是否影响高风险区域

| 项目 | 结果 |
|---|---|
| 是否改 Layer B 逻辑 | 否 |
| 是否改 Layer A 五阶段状态机原则 | 否 |
| 是否改真实交易 | 否 |
| 是否改虚拟账户 | 否 |
| 是否改 thesis persistence | 否 |
| 是否改仓位 / 止损 / 止盈 / 开平仓 / 反手 | 否 |
| 是否泄露 key / token / secret | 否 |

## 11. 删除清单 / 废弃清单

| 对象 | 位置 | 处理 |
|---|---|---|
| A1 使用完整 `spot_cycle_context` 作为 user prompt | `A1SpotCycleAnalyst._build_user_prompt` | 废弃，改为 `build_a1_cycle_stage_context` 的轻量输入。 |
| A1 长 prompt | `src/ai/agents/prompts/a1_spot_cycle.txt` | 替换为短 prompt，限制字段和证据长度。 |

没有删除业务数据、数据库表或交易逻辑。

## 12. 风险和未完成

- 本地完整 Layer A 已成功，但生产端仍需用户 `git pull` 后再跑一次确认。
- A2-A5 仍使用完整 context；本轮只处理 A1 timeout。如果未来 A4 或 A3 也慢，可以按同样方式拆专用 context。
- `recent_stage_history` 当前以最近 `latest_layer_a_spot_strategy` 为主，尚未新增完整历史表；这不影响本轮 timeout 修复。
- 本轮本地运行会在本地 SQLite 写入一次 Layer A latest 结果；没有触碰真实交易。

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待本轮提交后完成 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 14. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

刷新：

```text
http://124.222.89.86/
```
