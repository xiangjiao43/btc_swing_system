# weekly_review_recommendation_canonicalization

## 1. 任务目标

本轮目标是为 weekly review 的 `adjustment_recommendations` 增加 canonical recommendation id,让建议可以跨周稳定追踪、去重和统计 recurrence,避免 AI 改几个词就被当成新建议。

本轮只做 recommendation 结构化、normalize/fallback、temporal recurrence 统计改进、网页展示、测试和报告。不改变任何真实交易、仓位、止损、止盈、开仓、平仓、反手规则。

## 2. 读取文件

- `AGENTS.md`
- `README.md`
- `docs/modeling.md` §3.3.9 / §8.1
- `docs/codex_reports/weekly_review_guardrail_and_ui_alignment.md`
- `docs/codex_reports/weekly_review_evidence_diagnostics.md`
- `docs/codex_reports/weekly_review_temporal_consistency_and_confidence.md`
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
- `docs/codex_reports/weekly_review_recommendation_canonicalization.md`

未提交 `uv.lock`;该文件在本轮开始前已有本地未提交改动,本轮不纳入提交。

## 4. recommendation canonical 字段设计

normalize 后每条 `adjustment_recommendations` 至少包含:

- `recommendation_id`
- `normalized_recommendation_id`
- `recommendation_category`
- `recommendation_target`
- `recommendation_action_type`
- `evidence_confidence`
- `confidence_reason`

category enum:

- `l3_behavior`
- `l4_risk`
- `master_trade_plan`
- `validator_output_quality`
- `weekly_review_observability`
- `data_quality`
- `system_health`
- `web_ui`
- `other`

action type enum:

- `observe`
- `audit`
- `improve_prompt`
- `improve_schema`
- `improve_ui`
- `improve_diagnostics`
- `change_threshold`
- `fix_bug`
- `other`

## 5. fallback id 生成规则

normalize 兼容旧字段:

- `recommendation_id`
- `id`
- `canonical_id`
- `issue_id`

如果 AI 没给 ID,代码会根据建议文本和分类生成稳定 fallback id。示例:

- `audit_l3_extending_late_phase`
- `audit_l4_elevated_risk_breakdown`
- `improve_master_conflict_resolution_schema`
- `improve_v16_change_mind_structure`
- `improve_weekly_review_evidence_diagnostics`

规则:

- 输出 ID 强制 snake_case。
- 不使用随机数、日期、run_id。
- 观察 / 审计类建议如果误写为 `change_threshold`,normalize 会按“证据不足先审计”的原则改为 `audit`。
- fallback 输出也带完整 canonical 字段。

## 6. recurrence 改进方式

`weekly_review_input_builder` 的 `recommendation_recurrence` 现在优先用 canonical ID 聚合:

1. 优先使用 `normalized_recommendation_id`。
2. 其次使用 `recommendation_id` / `id` / `canonical_id` / `issue_id`。
3. 旧周报没有 ID 时,回退到 normalized text key。

recurrence 输出新增:

- `recommendation_id`
- `category`
- `target`
- `action_type`
- `weeks_seen`
- `last_seen`
- `confidence_levels_seen`
- `latest_priority`
- `latest_severity`

同时保留旧字段:

- `action`
- `recent_weeks`
- `latest_evidence_confidence`
- `key_source`

不新增数据库表。

## 7. duplicate / unstable id guardrail

新增两个只读提示:

- `duplicate_recommendation_id=true`
  - 同一份周报里多个 recommendation 使用同一 normalized ID 时标记。
  - 不删除、不合并原建议。

- `unstable_recommendation_id=true`
  - ID 中出现日期、百分比、run_id、UUID-like 或长随机串时标记。
  - 原始 `recommendation_id` 保留。
  - 生成稳定 `normalized_recommendation_id` 供网页和后续统计优先使用。

## 8. 网页展示

调整建议区域新增:

- ID
- category
- target
- action_type
- evidence_confidence
- confidence_reason
- duplicate / unstable 标记

时间连续性区域的 recurring recommendations 新增:

- recommendation_id
- category
- target
- action_type
- weeks_seen
- confidence_levels_seen
- latest_priority
- latest_severity

旧周报缺字段时继续显示 `-`,不影响打开。

## 9. 测试命令和结果

已运行:

```bash
uv run pytest -q tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py tests/test_web_modules_4_5_rp_failure.py
```

结果:通过,82 passed。

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

## 10. 是否触碰高风险交易逻辑

未触碰:

- 未改 L3 / L4 / Master 交易 prompt。
- 未改 Validator 交易约束逻辑。
- 未改仓位、止损、止盈、开仓、平仓、反手。
- 未改 scheduler 主裁决时间。
- 未启用 `position_health_check`。
- 未改 `.env` / API key / token / secret。
- 未自动应用周复盘建议。
- 未处理抓取数据和 AI 接入问题。

## 11. 风险和未完成

- 旧周报没有 canonical ID 时仍需回退文本 key;这比 ID 稳定性弱,但不会影响新周报。
- fallback ID 生成是保守启发式,可能把非常新颖的建议归到 `other`;网页会展示出来,方便后续人工调整规则。
- duplicate / unstable 只做提示,不会自动删除建议。
- 本轮未跑服务、未触碰生产 DB、未做 SSH 部署。

## 12. 下一步建议

- 等下一次真实周复盘生成后,检查 recurring recommendations 是否按稳定 ID 合并。
- 如果 `other` 类建议太多,下一轮可以扩展 category/target 推断规则。
- 若同一 ID 下长期 low confidence 重复,再考虑做“同类建议归并展示”,仍不自动改策略。

## 13. 本轮删除清单

**本轮无替代关系,无删除项**。原因:本轮为 recommendation 结构化、字段兼容和展示增强,没有引入替代实现。

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| N/A | N/A | 本轮无删除项 |

## 14. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash:b6b6fbb) | ✅ |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
