# weekly_review_temporal_consistency_and_confidence

## 1. 任务目标

本轮目标是继续优化周复盘模块,让周复盘能区分“单周异常”和“连续系统性异常”,并给每条调整建议增加 evidence confidence(证据置信度)。

本轮只做周复盘只读诊断、周复盘 prompt、normalize/fallback、网页展示、测试和报告。不改真实交易、仓位、止损、止盈、开仓、平仓、反手规则。

## 2. 读取文件

- `AGENTS.md`
- `README.md`
- `docs/modeling.md` §3.3.9 / §8.1
- `docs/codex_reports/weekly_review_guardrail_and_ui_alignment.md`
- `docs/codex_reports/weekly_review_evidence_diagnostics.md`
- `src/ai/weekly_review_input_builder.py`
- `src/ai/agents/weekly_review_analyst.py`
- `src/ai/agents/prompts/weekly_review_analyst.txt`
- `src/scheduler/jobs.py` 的 `job_weekly_review`
- `src/api/routes/review_weekly.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_weekly_review_input_builder.py`
- `tests/test_weekly_review_analyst.py`
- `tests/test_web_modules_4_5_rp_failure.py`

## 3. 改动文件

- `src/ai/weekly_review_input_builder.py`
- `src/ai/agents/weekly_review_analyst.py`
- `src/ai/agents/prompts/weekly_review_analyst.txt`
- `src/scheduler/jobs.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_weekly_review_input_builder.py`
- `tests/test_weekly_review_analyst.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/weekly_review_temporal_consistency_and_confidence.md`

未改动 `uv.lock`;该文件在本轮开始前已有本地未提交改动,本轮不纳入提交。

## 4. temporal diagnostics 设计

新增顶层只读字段:

```json
{
  "temporal_consistency_diagnostics": {
    "l3_extending_late_phase_trend": [],
    "l4_elevated_trend": [],
    "validator_v16_trend": [],
    "validator_v23_trend": [],
    "thesis_creation_trend": [],
    "trade_execution_trend": [],
    "recommendation_recurrence": [],
    "anomaly_streaks": {}
  }
}
```

设计原则:

- 不新增数据库表。
- 当前周从 `strategy_runs` / `theses` / `virtual_orders` 的现有聚合得到。
- 历史周从 `weekly_reviews.output_json` 尽量读取已有字段。
- 旧周报缺字段时跳过对应点,不抛异常。
- 每条趋势最多保留最近 8 周。
- 重复建议最多保留 10 条。
- 只做复盘输入和网页展示,不自动应用到策略参数。

当前使用的连续异常阈值只用于诊断展示:

- L3 `extending_late_phase` rate > 40% 计入连续异常。
- L4 `elevated` rate > 50% 计入连续异常。
- V16/V23 rate > 40% 计入连续偏高。
- `thesis_created == 0` 计入连续 0 thesis。
- `orders_filled == 0` 计入连续 0 trade。

这些阈值不改变任何交易判断。

## 5. evidence confidence 规则

`adjustment_recommendations` 每条建议新增规范字段:

- `evidence_confidence`: `low | medium | high`
- `confidence_reason`: 说明为什么是该置信度

normalize 兼容旧字段:

- `evidence_confidence`
- `confidence`
- `confidence_level`

默认规则:

- 单周异常 → `low`
- 2-3 周重复 → `medium`
- 长期持续 + diagnostics 支撑 → `high`
- fallback 输出默认 `low`
- 观察 / 审计 / 补诊断建议不能保持 `high`
- `thesis_created <= 1`、`orders_filled == 0` 或 diagnostics 缺失时,不应高置信度调参
- high priority 不等于 high evidence confidence

## 6. recommendation repetition guardrail

新增只读提示:

```json
{
  "possible_repetition_without_confirmation": true
}
```

触发条件:

- 历史周报里出现连续重复建议;
- 当前建议仍是 `evidence_confidence=low`;
- 只做提示,不删除、不合并、不自动降级建议。

网页展示文案:

> 该建议已连续出现，但证据仍不足

## 7. 网页展示

周复盘新增“时间连续性 / 证据置信度”小节,展示:

- recent anomaly streaks
- recurring recommendations
- 连续 elevated 周数
- 连续 V16/V23 偏高周数
- 连续 0 thesis / 0 trade 周数
- 每条 recommendation 的 evidence confidence 与 confidence reason

旧周报无字段时显示:

> 旧周报未记录时间连续性诊断字段

## 8. 测试命令和结果

已运行:

```bash
uv run pytest -q tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py tests/test_web_modules_4_5_rp_failure.py
```

结果:通过,78 passed。

已运行:

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/web_helpers/test_normalize_state.py
```

结果:通过,71 passed。

已运行:

```bash
git diff --check
```

结果:通过,无空白错误。

## 9. 是否触碰高风险交易逻辑

未触碰:

- 未改 L3 / L4 / Master 交易 prompt。
- 未改 Validator 交易约束逻辑。
- 未改仓位、止损、止盈、开仓、平仓、反手规则。
- 未改 scheduler 主裁决时间。
- 未启用 `position_health_check`。
- 未改 `.env` / API key / token / secret。
- 未处理抓取数据和 AI 接入。
- 未把周复盘建议自动应用到策略参数。

## 10. 风险和未完成

- 历史趋势依赖旧 `weekly_reviews.output_json` 是否保存过对应字段。旧周报字段缺失时会跳过该周的部分趋势。
- `trade_execution_trend` 对历史周报优先读取 `orders_filled` / `total_trades`;如果旧报告没写,历史成交趋势会少点。
- 重复建议识别使用文本相似的保守规则,只做“可能重复”提示,不做自动去重。
- 本轮未跑服务、未触碰生产 DB、未做 SSH 部署。

## 11. 下一步建议

- 观察 2-4 周新周报后,再判断 temporal diagnostics 是否足够稳定。
- 若历史周报成交字段长期缺失,下一轮可只读补充更稳定的历史 `orders_filled` 聚合口径。
- 若重复建议越来越多,可继续加强“同类建议归并展示”,但仍不自动改策略。

## 12. 本轮删除清单

**本轮无替代关系,无删除项**。原因:本轮为周复盘只读诊断、字段兼容和网页展示增强,没有引入替代实现。

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| N/A | N/A | 本轮无删除项 |

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash:6076278) | ✅ |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
