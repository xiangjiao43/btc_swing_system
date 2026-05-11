# weekly_review_recommendation_outcome_tracking

## 1. 任务目标

本轮目标是给每条 canonical recommendation 增加 `outcome_tracking`,用于记录建议是否已实施、后续效果如何,并让后续周复盘能用 outcome 支撑 evidence confidence 的长期稳定性。

本轮只做周复盘 recommendation 结构化、normalize/fallback、temporal recurrence 统计增强、网页展示、测试和报告。不改变任何交易逻辑。

## 2. 读取文件

- `AGENTS.md`
- `README.md`
- `docs/modeling.md` §3.3.9 / §8.1
- `docs/codex_reports/weekly_review_guardrail_and_ui_alignment.md`
- `docs/codex_reports/weekly_review_evidence_diagnostics.md`
- `docs/codex_reports/weekly_review_temporal_consistency_and_confidence.md`
- `docs/codex_reports/weekly_review_recommendation_canonicalization.md`
- `src/ai/weekly_review_input_builder.py`
- `src/ai/agents/weekly_review_analyst.py`
- `src/ai/agents/prompts/weekly_review_analyst.txt`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_weekly_review_input_builder.py`
- `tests/test_weekly_review_analyst.py`
- `tests/test_web_modules_4_5_rp_failure.py`

## 3. 改动文件

- `src/ai/agents/weekly_review_analyst.py`
- `src/ai/agents/prompts/weekly_review_analyst.txt`
- `src/ai/weekly_review_input_builder.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_weekly_review_analyst.py`
- `tests/test_weekly_review_input_builder.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/weekly_review_recommendation_outcome_tracking.md`

未提交 `uv.lock`;该文件在本轮开始前已有本地未提交改动,本轮不纳入提交。

## 4. outcome_tracking 字段设计

每条 `adjustment_recommendations` normalize 后新增:

```json
{
  "outcome_tracking": {
    "recommendation_id": "...",
    "implemented": false,
    "observed_outcome": "positive | neutral | negative | unknown",
    "confidence_accuracy": "low | medium | high",
    "evaluation_notes": "可选文本说明原因",
    "week_of_outcome": "ISO week"
  }
}
```

默认规则:

- `implemented`:默认 `false`。
- `observed_outcome`:默认 `unknown`。
- `confidence_accuracy`:默认 `low`。
- `evaluation_notes`:默认空字符串。
- `week_of_outcome`:没有可评估结果时为空字符串。

这些字段只记录复盘建议状态,不会自动应用任何策略参数。

## 5. normalize / fallback

`WeeklyReviewAnalyst.normalize_output` 会兼容:

- 嵌套 `outcome_tracking`
- 旧式扁平字段 `implemented`
- 旧式扁平字段 `observed_outcome`
- 旧式扁平字段 `confidence_accuracy`
- 旧式扁平字段 `evaluation_notes`
- 旧式扁平字段 `week_of_outcome`

fallback 输出也带完整 `outcome_tracking`,默认表示“尚未实施、结果未知、低准确度”。

## 6. recurrence 改进方式

`weekly_review_input_builder` 在历史 `weekly_reviews.output_json` 中读取 recommendation outcome,并在 `recommendation_recurrence` 中新增:

- `implemented_weeks`
- `outcomes_seen`
- `latest_observed_outcome`
- `latest_confidence_accuracy`
- `outcome_history`

用途:

- 后续周复盘可看某条 recommendation 是否真的被实施过。
- 如果长期 high confidence 建议后续 outcome 不好,可以反过来降低对该类建议的信任。
- 如果某类建议被实施后多次 positive,长期 confidence 才更有依据。

## 7. 网页展示

调整建议区域新增 outcome 展示:

- `implemented`
- `observed_outcome`
- `confidence_accuracy`
- `week_of_outcome`
- `evaluation_notes`

时间连续性 recurring recommendations 区域新增:

- `implemented_weeks`
- `outcomes_seen`
- `latest_observed_outcome`
- `latest_confidence_accuracy`

旧周报缺字段时显示 `-`,不影响打开。

## 8. 测试命令和结果

已运行:

```bash
uv run pytest -q tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py tests/test_web_modules_4_5_rp_failure.py
```

结果:通过,83 passed。

已运行:

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/web_helpers/test_normalize_state.py
```

结果:通过,71 passed。

已运行:

```bash
git diff --check
```

结果:通过。

## 9. 是否触碰高风险交易逻辑

未触碰:

- 未改 L3 / L4 / Master 交易 prompt。
- 未改 Validator 交易约束逻辑。
- 未改仓位、止损、止盈、开仓、平仓、反手。
- 未改 scheduler 主裁决时间。
- 未启用 `position_health_check`。
- 未改 `.env` / API key / token / secret。
- 未自动应用周复盘建议。
- 未处理抓取数据和 AI 接入问题。

## 10. 风险和未完成

- 目前 outcome 主要来自历史周报 JSON;没有新增人工登记表,所以如果过去周报没写 outcome,历史 outcome 会是 unknown。
- `implemented` 只是记录字段,不代表系统真的自动实施过任何建议。
- outcome 与 confidence 目前只作为证据输入和网页展示,不会自动调参。
- 本轮未跑服务、未触碰生产 DB、未做 SSH 部署。

## 11. 下一步建议

- 等下一次真实周复盘后,检查每条 recommendation 是否都有完整 outcome_tracking。
- 后续如果需要更强的人工登记,可以单独设计一个只读/手动维护的 recommendation outcome 文件或表,但本轮不新增。
- 连续 3-4 周后再看 outcome 是否能帮助过滤反复出现但低价值的建议。

## 12. 本轮删除清单

**本轮无替代关系,无删除项**。原因:本轮为 recommendation outcome 字段增强、字段兼容和展示增强,没有引入替代实现。

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| N/A | N/A | 本轮无删除项 |

## 13. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash:待提交后记录) | 待提交后记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |

