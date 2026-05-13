# remove_ai_from_raw_factor_plain_readings

## 1. 任务目标

本轮修正 Layer A 新增原始数据因子的人话说明边界:

- 原始数据因子卡片需要有人话说明;
- 说明必须由 `plain_reading` / 模板 / 规则化代码生成;
- 原始因子说明不允许调用 AI;
- AI 只继续用于 Layer A A1-A5 大周期策略分析、Layer B L1-L5/Master、weekly review 等已有 AI 模块;
- 本轮不自动跑长时间 pipeline。

## 2. 读取文件

- `AGENTS.md`
- `docs/codex_reports/layer_a_remaining_key_factors_validation_and_ingestion.md`
- `docs/codex_reports/fix_layer_a_factor_cards_to_match_existing_raw_factor_cards.md`
- `src/evidence/plain_reading.py`
- `src/evidence/pillars.py`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/agents/prompts/a2_onchain_macro.txt`
- `src/ai/agents/prompts/a3_spot_opportunity.txt`
- `src/ai/agents/prompts/a4_spot_risk.txt`
- `src/ai/agents/prompts/a5_spot_adjudicator.txt`
- `src/ai/orchestrator.py`
- `src/ai/context_builder.py`
- `src/ai/agents/spot_cycle_agents.py`
- `src/pipeline/state_builder.py`
- `web/assets/app.js`
- `web/index.html`
- `tests/test_plain_reading.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_orchestrator_integration.py`

## 3. 是否发现 raw factor 说明调用 AI

结论:没有发现“每个新增原始因子单独调用 AI 生成说明”的代码。

代码证据:

- `web/assets/app.js` 中 `layerAFactorPlainReading(...)` 是前端确定性模板函数,根据 `spec.key`、`actual_value`、`statusLabel` 拼接说明。
- `web/assets/app.js` 中 `layerAFactorCards()` 把 `layerAFactorPlainReading(...)` 的结果写入 `plain_interpretation`。
- `web/assets/app.js` 的 Layer A A1-A5 卡片会读取 `human_summary`,但这是“大周期策略”模块,不是“原始数据因子”模块。
- `src/ai/orchestrator.py` 中 Layer A AI 调用点固定是 A1、A2、A3、A4、A5 五个 agent。
- `src/ai/agents/spot_cycle_agents.py` 中 A1-A5 继承 `BaseAgent`,用于大周期策略综合判断,没有逐个 raw factor agent。
- `src/pipeline/state_builder.py` 中仍有历史 `ai_summary` 阶段,但它输入是 L1-L5 总结,不是新增 Layer A 原始因子卡片说明。

因此,当前 pipeline 卡住更可能来自已有 AI 调用等待,例如 Layer A A1-A5、Layer B L1-L5/Master 或历史 `ai_summary`,不是“每个原始因子一条 AI 说明”。

## 4. 修复前调用链

修复前与原始因子说明相关的链路是:

`layer_a_spot_strategy.input_context_snapshot.available_factors`
→ `web/assets/app.js::layerAFactorContextValue`
→ `web/assets/app.js::layerAFactorPlainReading`
→ `web/assets/app.js::layerAFactorCards`
→ 原始数据因子模块展示。

这条链路本身已经是规则化前端模板,不是 AI。

但问题是后端 `src/evidence/plain_reading.py` 还没有覆盖这些新增 Layer A raw factor 的确定性说明模板,容易让后续维护误以为说明可以交给 AI。  
本轮把新增因子说明也补进后端 `plain_reading` 体系,并加测试锁住边界。

## 5. 修复后调用链

修复后边界明确为:

- 后端规则模板: `src/evidence/plain_reading.py::plain_reading_layer_a_raw_factor`
- 前端规则模板: `web/assets/app.js::layerAFactorPlainReading`
- 网页卡片字段: `plain_interpretation`
- 不读取 A1-A5 的 `human_summary`
- 不调用 `ai_client` / `call_ai` / `run_agent` / `BaseAgent`

AI 调用点仍然只保留在:

- Layer B L1-L5 / Master 等既有 AI 体系;
- Layer A A1-A5 大周期策略综合判断;
- weekly review 等既有 AI 模块;
- 历史 `ai_summary` 阶段。

原始因子说明不再增加任何 AI 调用。

## 6. 新增 plain_reading 因子清单

本轮在 `src/evidence/plain_reading.py` 增加了 17 个 Layer A raw factor 的确定性说明模板:

- `lth_sopr`
- `sth_sopr`
- `percent_supply_in_profit`
- `percent_supply_in_loss`
- `exchange_balance`
- `exchange_net_position_change`
- `us2y`
- `fed_funds_rate`
- `m2`
- `fed_balance_sheet`
- `rhodl_ratio`
- `reserve_risk`
- `puell_multiple`
- `lth_net_position_change`
- `real_yield`
- `cpi`
- `core_cpi`

可用数据时,说明包含:

- 当前值;
- 简短含义;
- 高低或方向解释。

缺失数据时,说明包含:

- 因子用途;
- 用户可读状态,例如“未接入”“数据受限”“当前缺值”;
- 不暴露 `proxy_endpoint_404`、`uncertain_rate_limited` 等内部错误码。

## 7. 网页显示规则

网页原始数据因子模块保持现有卡片体系:

- 不新增独立模块;
- 不改字体、字号、badge、颜色、卡片布局;
- 新增因子仍进入现有“链上数据 / 宏观”分类;
- 可用因子显示“数值 + 人话说明 + 状态 + 抓取时间”;
- 不可用因子显示“- + 用途说明 + 未接入/数据受限/不可用状态”;
- 不显示 `Layer A context: 可用`;
- 不显示两行状态;
- 不显示 `proxy_endpoint_404` / `uncertain_rate_limited` 主文本。

## 8. 改动文件

- `src/evidence/plain_reading.py`
- `tests/test_plain_reading.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/remove_ai_from_raw_factor_plain_readings.md`

## 9. 测试命令和结果

已运行:

```bash
uv run pytest -q tests/test_plain_reading.py
```

结果:34 passed。

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果:118 passed。

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果:24 passed。

`git diff --check` 将在提交前执行。

```bash
git diff --check
```

结果:通过,无空白错误。

## 10. 是否自动跑 pipeline

没有。  
本轮按用户要求不跑长时间 pipeline,避免继续卡在 AI 等待。

## 11. 用户手动 pipeline 命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
.venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

然后刷新:

```text
http://124.222.89.86/
```

## 12. 是否影响 Layer A A1-A5

否。  
本轮没有修改 A1-A5 prompt,也没有修改 Layer A 策略判断逻辑。  
Layer A A1-A5 仍然是 AI 综合判断;原始因子说明是规则化展示。

## 13. 是否影响 Layer B

否。  
本轮没有修改 Layer B L1-L5、Master、Validator、thesis、C 级机会、虚拟账户。

## 14. 是否影响虚拟账户

否。  
本轮只改 raw factor 人话说明和测试,不进入虚拟账户。

## 15. 是否影响真实交易

否。  
本系统仍不是自动真实下单机器人。本轮没有真实交易接口、下单、仓位、止损、止盈、开平仓改动。

## 16. 删除清单 / 废弃清单

本轮无替代关系,无删除项。  
原因:没有发现独立的“raw factor AI 说明生成器”可删除;本轮是补齐 deterministic plain_reading 模板和测试保护。

## 17. 风险和未完成

- 前端 `layerAFactorPlainReading` 与后端 `plain_reading_layer_a_raw_factor` 当前是两套确定性模板,含义保持一致,但未来最好抽成同一份共享源,避免长期维护时文字漂移。
- 本轮没有跑 pipeline,所以没有生成新的 production `strategy_run`;这是按用户要求避免长时间 AI 等待。
- 如果后续仍卡 pipeline,应优先排查 A1-A5、Layer B agent、历史 `ai_summary` 的单次响应耗时或超时配置,而不是原始因子说明。

## 18. 下一步建议

1. 用户按上面的手动命令在服务器拉代码、重启服务、跑一次 pipeline。
2. 如果 pipeline 仍卡住,下一轮只做 AI 调用耗时审计:统计每个 agent 开始/结束时间、超时、重试次数。
3. 中期建议把前端/后端 raw factor plain reading 模板统一到一个源文件生成,减少重复维护。

## 19. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待提交后填写 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
