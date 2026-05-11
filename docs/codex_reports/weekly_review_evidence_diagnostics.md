# weekly_review_evidence_diagnostics

## 1. 任务目标

本轮继续优化周复盘模块,目标是让周复盘能解释“为什么 L3/L4/Validator 异常”,而不是只显示触发比例。

本轮只做只读诊断、网页展示、测试和报告,不改变任何交易决策逻辑。

## 2. 读取文件

- `AGENTS.md`
- `README.md`
- `docs/codex_reports/weekly_review_guardrail_and_ui_alignment.md`
- `src/ai/weekly_review_input_builder.py`
- `src/ai/agents/weekly_review_analyst.py`
- `src/ai/agents/prompts/weekly_review_analyst.txt`
- `src/api/routes/review_weekly.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_weekly_review_input_builder.py`
- `tests/test_weekly_review_analyst.py`
- `tests/test_web_modules_4_5_rp_failure.py`

## 3. 改动文件

- `src/ai/weekly_review_input_builder.py`
  - 新增 L3 / L4 / Validator 只读诊断聚合。
  - 所有诊断均从 `strategy_runs.full_state_json` 和 `constraint_activations_json` 读取,不写 DB。
  - 字段缺失时返回空结构,不抛异常。

- `src/ai/agents/weekly_review_analyst.py`
  - user prompt 注入三类 diagnostics。
  - fallback 输出空 diagnostics。
  - normalize 兜底 diagnostics 字段,并兼容旧 rate 文案。

- `src/ai/agents/prompts/weekly_review_analyst.txt`
  - 增加 L3 / L4 / Validator 诊断证据要求。
  - 明确 diagnostics 为空时必须写“证据不足,建议补诊断”。
  - 明确不得单凭比例建议改 L3/L4/Validator。

- `src/scheduler/jobs.py`
  - 周复盘输出缺诊断字段时,从 input_builder 原样注入只读 diagnostics。

- `web/index.html`
  - 周复盘区域新增“诊断证据”小节。
  - 展示 L3 phase/grade/anti-pattern 样本、L4 risk/risk_breakdown 样本、Validator V16/V23 样本。
  - 旧周报无诊断字段时显示“旧周报未记录该诊断字段”。

- `web/assets/app.js`
  - 新增 diagnostics 展示 helper。

- 测试文件
  - `tests/test_weekly_review_input_builder.py`
  - `tests/test_weekly_review_analyst.py`
  - `tests/test_web_modules_4_5_rp_failure.py`

## 4. 新增诊断字段

### L3

`l3_diagnostics`:
- `phase_distribution`
- `anti_pattern_signal_distribution`
- `opportunity_grade_distribution`
- `execution_permission_distribution`
- `anti_pattern_by_grade`
- `extending_late_phase_samples`

样本最多 10 条,包含:
- `run_id` / `run_at`
- `phase`
- `opportunity_grade`
- `execution_permission`
- `anti_pattern_signals`
- `master_action`
- `btc_price`

### L4

`l4_diagnostics`:
- `risk_tier_distribution`
- `risk_score_summary`
- `position_cap_multiplier_summary`
- `risk_breakdown_top_reasons`
- `elevated_samples`

样本最多 10 条,包含:
- `run_id` / `run_at`
- `risk_tier`
- `risk_score`
- `position_cap_multiplier`
- `risk_breakdown`
- `master_action`
- `btc_price`

### Validator

`validator_diagnostics`:
- `top_triggered_validators`
- `v16_samples`
- `v23_samples`
- `validator_sample_base`

V16/V23 样本最多各 10 条,包含:
- `run_at`
- `validator_id`
- `validator_name`
- `activation_reason` / `message`
- `master_action`
- `what_would_change_mind`
- `conflict_resolution`

## 5. 测试命令和结果

```bash
uv run pytest -q tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py tests/test_web_modules_4_5_rp_failure.py
```

结果:`73 passed in 4.40s`

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/web_helpers/test_normalize_state.py tests/test_jobs_weekly_review_and_health_check.py
```

结果:`95 passed in 0.39s`

```bash
uv run pytest -q tests/test_sprint_h_part_b_input_extension.py tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py tests/test_web_modules_4_5_rp_failure.py tests/test_web_modules_1_2_3.py tests/web_helpers/test_normalize_state.py tests/test_jobs_weekly_review_and_health_check.py
```

结果:`178 passed in 4.73s`

```bash
git diff --check
```

结果:通过。

## 6. 是否触碰高风险交易逻辑

未触碰:
- 未改 L3 / L4 / Master 交易 prompt。
- 未改 Validator 交易约束逻辑。
- 未改仓位、止损、止盈、开仓、平仓、反手规则。
- 未改 scheduler 主裁决时间。
- 未启用 `position_health_check`。
- 未改 `.env`、API key、token、secret。
- 未处理抓取数据和 AI 接入问题。
- 未把周复盘建议自动应用到策略参数。

## 7. 风险和未完成

- diagnostics 依赖历史 `full_state_json` 和 `constraint_activations_json` 的实际字段质量;旧 run 缺字段时会显示空结构。
- `activation_reason` 主要从 Master notes / Validator retry hints 推导,如果历史 run 没写 notes,会退回通用触发说明。
- 本轮没有做图表,只做轻量表格和样本展示,避免 UI 大改。
- 本轮没有改变 L3/L4/Validator 阈值;它只帮助下一次周复盘解释原因。

## 8. 下一步建议

- 等下一次真实周复盘生成后,检查网页“诊断证据”是否能解释 elevated / extending_late_phase / V16 / V23。
- 如果 diagnostics 连续为空,再单独检查生产端 `full_state_json` 和 `constraint_activations_json` 写入质量。
- 如果连续多周证据都指向同一原因,再开新任务讨论是否人工调整策略 prompt 或阈值。

## 9. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash:bdbba29) | ✅ |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
