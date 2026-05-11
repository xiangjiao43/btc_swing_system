# weekly_review_guardrail_and_ui_alignment

## 1. 任务目标

本轮只优化周复盘的可信度、展示、样本口径、告警分级和字段兼容,不改变任何真实交易、下单、仓位、止损、止盈、反手规则。

核心目标:
- Validator 激活率分母从误导性的 `days` 改为有效决策样本 `valid_runs`。
- 区分 `优先级=high` 与 `severity=critical`,避免 high 建议误触发 critical 告警。
- 兼容 `具体调整路径` / `建议` / `suggested_action` 三种建议字段。
- 给周复盘 prompt 加 guardrail,避免单周数据诱导过拟合调参。
- 网页补充样本口径、策略质量、AI vs 实际走势展示。
- 修复最大回撤 0 值显示和颜色。
- 清理网页数据源文案中不符合当前口径的 Yahoo / Binance 展示。

## 2. 读取过的关键文件

- `AGENTS.md`
- `README.md`
- `docs/modeling.md` §8 / §9 周复盘与网页 API
- `src/ai/weekly_review_input_builder.py`
- `src/ai/agents/weekly_review_analyst.py`
- `src/ai/agents/prompts/weekly_review_analyst.txt`
- `src/scheduler/jobs.py` 中 `job_weekly_review`
- `src/api/routes/review_weekly.py`
- `web/index.html` 周复盘区域
- `web/assets/app.js` 周复盘 helper
- `tests/test_weekly_review_input_builder.py`
- `tests/test_weekly_review_analyst.py`
- `tests/test_jobs_weekly_review_and_health_check.py`
- `tests/test_web_modules_4_5_rp_failure.py`

## 3. 改动文件

- `src/ai/weekly_review_input_builder.py`
  - 新增 `sample_base`: `total_strategy_runs` / `valid_constraint_runs` / `missing_constraint_runs` / `window_days`。
  - Validator rate 改为 `N/M valid_runs`。
  - 无有效 Validator JSON 时显示 `0/0 valid_runs`。
  - 保留 `total_days_in_window`,并注明历史命名不准确。

- `src/ai/agents/weekly_review_analyst.py`
  - fallback 输出改为 5 段口径并包含 `sample_base`。
  - normalize 兼容 `具体调整路径` / `建议` / `suggested_action`。
  - normalize 将旧 `days` rate 转为 `valid_runs`。
  - `count_critical_recommendations` 只统计 explicit `severity=critical` / `严重级别=critical`。
  - 新增 `count_high_priority_recommendations`,只用于文案和告警摘要。

- `src/ai/agents/prompts/weekly_review_analyst.txt`
  - 修复 “4 段 JSON” 与实际 5 段不一致。
  - 明确 severity 与 priority 分离。
  - 对 L3 anti_pattern、L4 elevated、entry_zone、0 成交 / 1 thesis 加 guardrail。
  - 明确 entry_zone / stop_loss / take_profit 属于 Master trade_plan / thesis lifecycle,不归因给 L3。

- `src/scheduler/jobs.py`
  - weekly review alert message 改为 `critical_count=N;high_priority_count=M`。
  - 只有 `critical_count > 0` 才写 `weekly_review_critical_recommendation`。
  - high-only 建议写普通 `weekly_review` warning,不再写 critical。
  - AI 输出缺 `sample_base` 时从 input_builder 注入。

- `web/index.html`
  - 周复盘顶部新增样本口径展示。
  - 调整建议显示优先使用 `具体调整路径`。
  - 新增 “策略质量 / AI vs 实际走势” 小节。
  - 最大回撤改用专用 formatter 和颜色规则。
  - footer 数据源改为 `CoinGlass / Glassnode / FRED / local calendar`。

- `web/assets/app.js`
  - 新增 `weeklyReviewSampleBase` / `formatValidatorRate` / `weeklyReviewRecommendationAction` / `weeklyReviewAiVsActual`。
  - 新增 `formatDrawdownPct` / `drawdownColorClass` / `formatReviewValue`。
  - 页面数据源展示口径从 Yahoo/Binance 调整为 CoinGlass / Glassnode / FRED。

- 测试文件
  - `tests/test_weekly_review_input_builder.py`
  - `tests/test_weekly_review_analyst.py`
  - `tests/test_jobs_weekly_review_and_health_check.py`
  - `tests/test_web_modules_4_5_rp_failure.py`

## 4. 实际运行命令

```bash
uv run pytest -q tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py tests/test_jobs_weekly_review_and_health_check.py tests/test_web_modules_4_5_rp_failure.py
uv run pytest -q tests/test_web_modules_1_2_3.py tests/web_helpers/test_normalize_state.py
uv run pytest -q tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py tests/test_jobs_weekly_review_and_health_check.py tests/test_web_modules_4_5_rp_failure.py tests/test_web_modules_1_2_3.py tests/web_helpers/test_normalize_state.py
git diff --check
rg -n "<敏感关键词扫描表达式>" ...
```

## 5. 测试结果

- 指定测试: `94 passed in 4.61s`
- 额外网页 helper 测试: `71 passed in 0.02s`
- 合并回归测试: `165 passed in 4.47s`
- `git diff --check`:通过
- 敏感信息扫描:未命中真实 key / token / secret / 私钥

## 6. 是否触碰高风险区域

未触碰:
- 未改任何交易执行、下单、仓位、止损、止盈、反手规则。
- 未改 `src/ai/agents/prompts/l3_opportunity.txt`。
- 未改 `src/ai/agents/prompts/l4_risk.txt`。
- 未改 `src/ai/agents/prompts/master_adjudicator.txt` 的交易硬约束。
- 未改 validator 交易约束逻辑。
- 未改 scheduler 主裁决时间。
- 未启用 `position_health_check`。
- 未改 `.env`、API key、secret、token。
- 未恢复 Binance / Yahoo 数据源。
- 未把周复盘建议自动应用到策略参数。

## 7. 删除清单

本轮无替代关系,无删除项。原因:本轮为周复盘展示、字段兼容和告警分级修复,没有引入替代实现。

## 8. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash:2b8c7a2) | ✅ |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |

## 9. 风险和未完成

- 旧周报里如果没有 `sample_base`,网页会从旧 rate 分母保守推断;推断不了时显示“样本口径：旧报告未记录”。
- 本轮没有修改 L3/L4/Master 交易 prompt,所以不会直接改变交易结论。
- 可选的 L4 `risk_score` / `risk_breakdown` / `position_cap_multiplier` 更细诊断暂未展开,原因是当前输入字段稳定性需要再确认,避免网页误读。
- 周复盘 prompt 已要求先补诊断再调参,但 AI 文案质量仍取决于下一次真实周复盘输出;normalize 会兜底字段兼容和 critical 计数。

## 10. 下一步建议

- 下次周复盘生成后,重点看 `sample_base` 是否显示为真实有效样本。
- 观察 high-only 建议是否只产生 warning / info,不再误报 critical。
- 如果连续多周 L4 elevated 偏高,再单独做一轮只读诊断增强,补 `risk_breakdown` 和 `position_cap_multiplier` 的网页解释。
