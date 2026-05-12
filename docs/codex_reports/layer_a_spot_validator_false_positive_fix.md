# Layer A Spot Validator False Positive Fix

## 1. 任务目标

本轮任务名：`layer_a_spot_validator_false_positive_fix`。

目标是修复 Layer A 大周期策略模块里 Spot Validator 的误判：以前 validator 会把整份 Layer A 输出当成一段文本扫关键词，所以 AI 正确写出“不要做空 / 不使用 A/B/C / 不创建 thesis / 不进入虚拟账户”这类边界说明时，也可能被误判为违规。

本轮只修 Layer A validator / normalizer / Layer A prompt 边界提示 / 测试，不改 Layer B，不改交易逻辑，不改网页大布局。

## 2. 读取文件

- `AGENTS.md`
- `README.md`
- `src/ai/spot_validator.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/agents/prompts/a2_onchain_macro.txt`
- `src/ai/agents/prompts/a3_spot_opportunity.txt`
- `src/ai/agents/prompts/a4_spot_risk.txt`
- `src/ai/agents/prompts/a5_spot_adjudicator.txt`
- `tests/test_layer_a_spot_validator.py`
- `tests/test_layer_a_spot_normalize.py`
- `tests/test_layer_a_orchestrator_integration.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

## 3. 改动文件

- `src/ai/spot_validator.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/agents/prompts/a2_onchain_macro.txt`
- `src/ai/agents/prompts/a3_spot_opportunity.txt`
- `src/ai/agents/prompts/a4_spot_risk.txt`
- `src/ai/agents/prompts/a5_spot_adjudicator.txt`
- `tests/test_layer_a_spot_validator.py`
- `tests/test_layer_a_spot_normalize.py`
- `docs/codex_reports/layer_a_spot_validator_false_positive_fix.md`

说明：`uv.lock` 在本轮开始前已有本地未提交修改，本轮未处理、未提交。

## 4. 修了什么误判

修复前：

- Spot Validator 会扫描整份输出，只要出现 `做空 / short / A/B/C / NONE / thesis / entry / stop_loss / take_profit` 等词，就可能判违规。
- 这会导致正确边界说明也被误判。例如：
  - “不要做空”
  - “Layer A 不做空”
  - “Layer A 不使用 A/B/C 机会等级”
  - “不创建 thesis，不进入虚拟账户”

修复后：

- 字段名级别仍严格拦截。
- 文本级别改为只拦截“行动性违规表达”。
- 如果文本前后明确是禁止性边界说明，不再触发 hard violation。
- normalizer 的轻量 warning 也改为同样逻辑，不会因为 `model_notes` 写“Layer A 不创建 thesis”而每次报警。

## 5. 不再误判的表达

以下表达不再触发 hard violation：

- “不要做空”
- “Layer A 不做空”
- “Layer A 不使用 A/B/C 机会等级”
- “不创建 thesis，不进入虚拟账户”
- 其他类似“不得 / 不能 / 不允许 / 禁止 / 避免 / do not / should not”等边界说明。

这对交易系统意味着：Layer A 可以正常告诉用户“自己不能做什么”，不会因为讲清边界而被系统误判为越界。

## 6. 仍然违规的表达

以下表达仍会触发 hard violation：

- “建议做空”
- “开空”
- `hedge short`
- `trend_short`
- “创建 thesis”
- “设置 entry / stop_loss / take_profit / position_size / leverage”
- “使用 A/B/C 机会等级”
- 输出对象字段中真实包含：
  - `entry`
  - `entry_zone`
  - `entry_orders`
  - `stop_loss`
  - `take_profit`
  - `thesis`
  - `trade_plan`
  - `virtual_account`
  - `position_size`
  - `leverage`

这对交易系统意味着：Layer A 仍然不能越界成 Layer B 的波段交易计划，也不能变成做空、杠杆、thesis 或虚拟账户模块。

## 7. Layer A Prompt 小修

5 个 Layer A prompt 都补了一句边界提示：

- 可以写“不要做空 / 不使用 A/B/C / 不创建 thesis”这种边界说明。
- 不能输出“建议做空 / 创建 thesis / 设置止损”等行动计划。

这只是提醒 Layer A AI 如何表达边界，不改变 Layer B 交易 prompt，也不改变交易决策逻辑。

## 8. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_validator.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_orchestrator_integration.py
```

结果：

```text
16 passed
```

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：

```text
114 passed
```

已运行：

```bash
git diff --check
```

结果：通过，无空白错误。

## 9. 是否影响 Layer B

不影响。

本轮没有修改：

- Layer B L1-L5 prompt
- Layer B Master prompt
- Layer B Validator
- Layer B thesis 创建规则
- Layer B C 级机会行为
- Layer B 仓位、止损、止盈、开仓、平仓、反手规则

## 10. 是否影响虚拟账户

不影响。

Layer A 仍然不进入虚拟账户，虚拟账户仍然只管理 Layer B。

## 11. 是否影响真实交易

不影响。

本轮没有新增真实交易接口，没有触碰 API key、secret、token，也没有任何真实下单逻辑。

## 12. 删除清单 / 废弃清单

本轮无替代关系，无删除项。

原因：本轮是 Layer A Spot Validator 的误判修复，没有新增替代模块，也没有发现可安全删除的旧 Layer A 逻辑。

## 13. 风险和未完成

- 当前文本判断已经覆盖本轮列出的典型误判和违规表达，但自然语言变化很多，未来如果 AI 写出新的奇怪行动表达，可能还需要继续补充 pattern。
- 字段级拦截保持严格；如果将来 Layer A 需要展示某些“禁止使用的字段名”作为纯说明字段，需要单独设计安全字段名，不能直接用 `entry` / `stop_loss` 等交易字段。
- `uv.lock` 仍有本轮开始前就存在的本地未提交修改，本轮未处理。

## 14. 下一步建议

- 下一轮可以观察真实 Layer A 输出中是否还有误判样本。
- 如果误判继续出现，建议把 validator 的文本判断升级为更明确的“结构化意图字段”校验，而不是继续扩大关键词表。

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash:107c237) | ✅ |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
