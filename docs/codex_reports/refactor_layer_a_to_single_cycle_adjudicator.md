# Refactor Layer A To Single Cycle Adjudicator

## 1. 任务目标

本轮把 Layer A「大周期策略 / 现货仓策略」从旧的 A1-A5 五个 AI agent 串行结构，重构为：

1. 四个 deterministic 数据包：
   - 技术指标数据包 `technical_packet`
   - 链上数据包 `onchain_packet`
   - 流动性 / 宏观背景数据包 `liquidity_macro_packet`
   - 风险评估数据包 `risk_packet`
2. 一个 AI 大周期裁决 `layer_a_cycle_adjudicator`
3. 一个 deterministic normalizer / state machine / spot validator

目标是减少 Layer A AI 调用次数、减少重复分析和 A1/A5 口径冲突，同时继续保留七阶段大周期模型、阶段稳定机制和 Layer A / Layer B 边界。

## 2. 读取文件

- `AGENTS.md`
- `config/ai.yaml`
- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/agents/prompts/a2_onchain_macro.txt`
- `src/ai/agents/prompts/a3_spot_opportunity.txt`
- `src/ai/agents/prompts/a4_spot_risk.txt`
- `src/ai/agents/prompts/a5_spot_adjudicator.txt`
- `src/ai/agents/spot_cycle_agents.py`
- `src/ai/orchestrator.py`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_cycle_stage_state.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/spot_validator.py`
- `src/pipeline/layer_a_spot_runner.py`
- `scripts/run_layer_a_once.py`
- `web/assets/app.js`
- `web/index.html`
- `src/evidence/plain_reading.py`
- 相关 Layer A / Web 测试文件

## 3. 改动文件

- `src/ai/agents/__init__.py`
- `src/ai/agents/spot_cycle_agents.py`
- `src/ai/agents/prompts/layer_a_cycle_adjudicator.txt`
- `src/ai/orchestrator.py`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/spot_validator.py`
- `src/evidence/plain_reading.py`
- `src/pipeline/layer_a_spot_runner.py`
- `src/scheduler/jobs.py`
- `web/assets/app.js`
- `web/index.html`
- `tests/test_layer_a_orchestrator_integration.py`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_spot_normalize.py`
- `tests/test_web_modules_1_2_3.py`

说明：工作区存在既有 `uv.lock` 未提交改动，本轮未纳入提交范围。

## 4. 为什么重构

旧结构是：

`A1 大周期阶段 → A2 链上与宏观 → A3 现货机会 → A4 现货风险 → A5 主裁`

问题是五个 AI 层会重复读取同一批长周期数据，容易出现：

- 重复结论；
- 链上、宏观、风险、策略在多层里反复解释；
- prompt/context 变长；
- AI 调用耗时大；
- A1 和 A5 可能对阶段/动作出现口径不一致；
- Layer A 作为低频现货大周期策略，不需要五次 AI 裁决。

新结构把数据解释前置为 deterministic 数据包，让 AI 只做一次最终大周期裁决。

## 5. 新架构说明

新正式流程：

`raw data → deterministic data packets → single AI cycle adjudicator → deterministic state machine / validator → persisted Layer A result → web display`

正式 Layer A runner 现在只调用：

- `LayerACycleAdjudicator`

旧 A1-A5 agent 类和 prompt 仍保留为 legacy / compatibility，原因是历史测试、旧数据兼容和回滚审计仍可能引用；但正式 `run_layer_a_spot_only` 不再调用 A1-A5。

## 6. 四个数据包字段

### 6.1 技术指标数据包

`technical_packet`

包含：

- BTC price
- ATH drawdown
- 200D MA
- 200W MA
- weekly structure
- monthly OHLC structure
- major support / resistance zones
- realized price
- STH realized price
- LTH realized price

用途：判断高周期价格位置和结构，不包含短线波段噪音。

### 6.2 链上数据包

`onchain_packet`

包含：

- MVRV / MVRV Z / NUPL
- RHODL Ratio
- Reserve Risk
- Puell Multiple
- percent supply in profit / loss
- LTH SOPR / STH SOPR
- LTH supply / STH supply
- LTH net position change
- HODL Waves 1Y+
- CDD
- exchange balance
- exchange net position change

用途：判断链上估值、长期筹码和吸筹/派发行为。

### 6.3 流动性 / 宏观背景数据包

`liquidity_macro_packet`

包含：

- ETF 7d / 30d flow
- exchange net flow 30d summary
- Real Yield
- Fed Funds Rate
- US2Y
- DXY
- VIX
- NASDAQ
- M2
- Fed Balance Sheet
- CPI / Core CPI

用途：判断外部流动性和宏观环境，只作为确认或反方证据，不让单一宏观指标直接决定阶段。

### 6.4 风险评估数据包

`risk_packet`

包含：

- factor coverage
- confidence cap
- missing / stale factor count
- unavailable factors 摘要
- 是否靠近长期阻力区
- ETF flow 风险背景
- real yield / fed funds 风险背景

用途：决定是否允许确认阶段升级、是否需要降置信度、是否只能 pending。

## 7. 单一 AI 裁决 prompt

新增：

`src/ai/agents/prompts/layer_a_cycle_adjudicator.txt`

AI 输入只包含四个数据包、最近阶段历史、允许阶段迁移、上一轮正式阶段和 Layer A 边界。

AI 输出字段：

- `raw_stage_assessment`
- `official_stage_recommendation`
- `transition_status_recommendation`
- `cycle_stage_confidence`
- `spot_action_recommendation`
- `risk_level`
- `headline`
- `trader_summary`
- `supporting_evidence`
- `opposing_evidence`
- `data_quality_notes`
- `stage_change_reason`
- `what_would_confirm_next_stage`
- `what_would_invalidate_current_stage`

注意：AI 的 `official_stage_recommendation` 只是建议，最终正式阶段仍由 deterministic state machine 决定。

## 8. 状态机如何保留

保留 `src/ai/spot_cycle_stage_state.py` 七阶段状态机：

- `bear_bottom`
- `accumulation`
- `bull_bear_transition`
- `early_bull`
- `mid_bull`
- `late_bull`
- `overheated_top`

保留规则：

- 读取 `previous_official_stage`
- 读取最近阶段历史
- 相邻变化需要连续确认
- 跨级变化不能直接 confirmed
- 数据质量差不能确认升级
- 风险过高不能确认激进升级

## 9. 策略动作如何绑定阶段

`normalize_layer_a_output` 现在把单一裁决输出归一成兼容结构，并继续调用：

- `evaluate_stage_transition`
- `conservative_action_for_official_stage`
- `validate_spot_strategy_output`

动作仍受阶段和风险约束：

- `bear_bottom → strong_buy`
- `accumulation → dca_buy`
- `bull_bear_transition → hold`
- `early_bull → dca_buy`
- `mid_bull → hold`
- `late_bull → scale_sell`
- `overheated_top → strong_sell`

风险偏高或 transition pending 时，动作会保守化，不能因 AI 文字而激进化。

## 10. 网页如何变化

大周期策略模块保留顶部摘要和交易员结论，但底部不再显示：

- A1 大周期阶段
- A2 链上与宏观
- A3 现货策略机会
- A4 现货风险
- A5 大周期主裁

改为显示：

1. 技术指标
2. 链上数据
3. 流动性 / 宏观
4. 风险评估
5. 大周期裁决

四个数据包不是 AI 分析，是 deterministic 摘要；详细原始因子仍在「原始数据因子」模块。

## 11. 系统自检如何变化

系统自检 Layer A 列从旧的 “Layer A 五层” 改为 “Layer A 数据包”：

1. 技术指标包
2. 链上数据包
3. 流动性 / 宏观包
4. 风险评估包
5. 大周期裁决

Layer B 五层和数据源列不变。

## 12. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：

```text
39 passed
```

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：

```text
140 passed
```

## 13. Layer A 手动运行结果

本地只运行一次：

```bash
uv run python scripts/run_layer_a_once.py --trigger manual
```

结果摘要：

- `run_id`: `2e9ae25e6e124121999f45711b5a4c65`
- `generated_at_bjt`: `2026-05-15 15:42:21 BJT`
- `status`: `success`
- `persisted`: `true`
- `validator_passed`: `true`
- `violations`: `[]`
- `warnings`: `[]`
- `official_stage`: `accumulation`
- `spot_action`: `hold`
- `duration_ms`: `31740`
- `pipeline_log_path`: `/Users/shenjun/pipeline_logs/pipeline_20260515T074221Z_54547_1778830941402760000_layer_a_manual.jsonl`

## 14. AI call count 是否为 1

确认是 1。

证据：

- pipeline 只出现 `run Layer A cycle adjudicator`
- 不再出现 `run Layer A A1` / `run Layer A A2` / `run Layer A A3` / `run Layer A A4` / `run Layer A A5`
- latest Layer A 存储摘要显示：
  - `architecture = single_cycle_adjudicator`
  - `ai_call_count = 1`
  - `legacy_a1_a5_flow = false`
  - `data_packets = technical_packet / onchain_packet / liquidity_macro_packet / risk_packet`

## 15. 删除清单 / 废弃清单

| 对象 | 处理 | 原因 | 测试覆盖 |
|---|---|---|---|
| Orchestrator 正式 A1-A5 串行调用路径 | 已移除正式调用 | 新架构只允许一次 Layer A AI 调用 | `tests/test_layer_a_orchestrator_integration.py` 确认旧 A1-A5 agent 不被调用 |
| A1-A5 prompt / agent 类 | 暂保留 legacy | 历史数据、测试兼容和回滚审计仍可能引用；正式 pipeline 不再调用 | `run_layer_a_spot_only` 只调用 `layer_a_cycle` |
| 网页 A1-A5 五张 AI 卡片 | 已从新展示中废弃 | 新结构展示四个 deterministic 数据包 + 一个裁决结果 | Web 测试确认旧标题不再出现在 `app.js` 主展示逻辑 |

## 16. 是否影响 Layer B

否。

本轮没有修改 Layer B L1-L5、Master、Validator、thesis persistence、虚拟账户、挂单、持仓、开平仓、反手规则。

## 17. 是否影响虚拟账户

否。

Layer A 仍不进入虚拟账户。

## 18. 是否影响真实交易

否。

本系统仍不真实下单；本轮没有新增交易接口。

## 19. 风险和未完成

1. 旧 A1-A5 prompt 和类仍保留为 legacy，后续若确认无历史兼容需求，可以再做删除清理。
2. 生产端需要 `git pull` 和重启服务后才会使用新结构。
3. 本地手动运行成功，但生产端 AI 中转站状态仍需要上线后用一次 Layer A 手动 run 验证。
4. 本轮未合并 Layer A / Layer B 调度时间，按任务要求留到下一轮。

## 20. 后续是否可以和 Layer B 同时间窗口运行

建议：可以重新评估。

Layer A 现在只剩一次 AI 调用，理论上比旧 A1-A5 五连调更适合靠近 Layer B 调度窗口运行。但是否合并调度时间仍建议下一轮单独做，因为需要看生产端中转站稳定性、单次耗时和 502/503 频率。

## 21. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待本轮提交后执行 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 22. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

如需跑 Layer A：

```bash
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

刷新：

```text
http://124.222.89.86/
```
