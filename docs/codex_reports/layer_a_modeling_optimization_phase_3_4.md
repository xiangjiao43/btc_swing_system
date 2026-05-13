# layer_a_modeling_optimization_phase_3_4

生成时间：2026-05-12  
任务性质：Layer A 建模质量优化 + 安全 pipeline 验证  
一句话结论：本轮给 Layer A 增加了因子覆盖度摘要、输入快照和 confidence cap；当关键因子缺失较多或已接入因子可用率太低时，AI 即使输出 high，也会被系统降到 medium/low。

## 1. 任务目标

基于最新线上 run 的建模审查结论，本轮优化 Layer A「大周期策略」判断质量：

- 让 A1-A5 输出更短、更像交易员建议；
- 增加 `factor_coverage`，明确当前有多少可用因子、缺失因子、关键未接入因子；
- 增加 `confidence cap`，避免缺失关键因子很多时仍给 `high confidence`；
- 保存轻量 `input_context_snapshot`，方便后续复盘知道当时 Layer A 看了哪些输入；
- 保持 Layer A / Layer B 边界，不改 Layer B，不改虚拟账户，不改真实交易。

## 2. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/ai/spot_cycle_context_builder.py` | 新增 Layer A 因子覆盖度统计和 confidence cap 来源 |
| `src/ai/spot_strategy_normalizer.py` | 新增 confidence cap 执行、`factor_coverage`、`confidence_adjustments`、`input_context_snapshot` 透传 |
| `src/ai/spot_validator.py` | 新增输出置信度高于 context cap 时的 warning |
| `src/ai/orchestrator.py` | 合并 Layer A 输出时写入 `factor_coverage` 和轻量输入快照 |
| `src/ai/agents/prompts/a1_spot_cycle.txt` | 要求 A1 摘要最多 2 句话，阶段判断更聚焦大周期因素 |
| `src/ai/agents/prompts/a2_onchain_macro.txt` | 要求 A2 摘要简短，并服从关键因子缺失导致的置信度约束 |
| `src/ai/agents/prompts/a3_spot_opportunity.txt` | 要求 A3 不写成 Layer B 入场单，摘要更聚焦 |
| `src/ai/agents/prompts/a4_spot_risk.txt` | 要求 A4 简短说明风险等级和主要风险源 |
| `src/ai/agents/prompts/a5_spot_adjudicator.txt` | 要求 A5 更像最终主裁，少重复指标，服从 `factor_coverage.confidence_cap` |
| `tests/test_layer_a_spot_context_builder.py` | 增加空库 factor coverage / cap 测试 |
| `tests/test_layer_a_spot_normalize.py` | 增加 confidence cap 测试 |
| `tests/test_layer_a_spot_validator.py` | 增加 context cap warning 测试 |

说明：`uv.lock` 是本轮开始前已有遗留修改，本轮未提交。

## 3. Prompt 优化内容摘要

本轮没有改变 Layer A 的五类动作，也没有改变边界，只优化表达约束：

- A1：阶段判断优先看周期结构、链上估值、持有人行为、长期资金流；Funding/OI/CPI 事件只能作为背景风险。
- A2：要求先说链上和宏观是否同向，再说最大冲突。
- A3：只写现货大周期节奏，不写成 Layer B 入场单，不输出 entry / stop_loss / take_profit。
- A4：先说风险等级，再说 2-3 个主要风险来源。
- A5：最多 2 句话给最终建议，不重复 A1-A4 长段指标解释；如果 `factor_coverage.confidence_cap` 不是 high，必须服从。

对交易系统的意义：Layer A 会更像“大周期现货建议”，不会继续把网页塞成很长的指标作文。

## 4. Confidence cap / coverage 规则说明

新增 `factor_coverage`：

| 字段 | 含义 |
|---|---|
| `available_factor_count` | 当前已接入且可用的 Layer A 因子数量 |
| `missing_integrated_factor_count` | 已接入但当前缺值的因子数量 |
| `stale_factor_count` | 已接入但过期的因子数量 |
| `coverage_ratio` | 已接入因子的可用比例 |
| `total_unavailable_factors` | 模型预留但项目未稳定接入的候选因子数量 |
| `critical_unavailable_count` | 关键候选因子缺失数量 |
| `critical_unavailable_factors` | 缺失的关键候选因子列表 |
| `confidence_cap` | 本次 Layer A 最高允许置信度 |
| `confidence_cap_reason` | 为什么限制置信度 |

规则：

| 条件 | confidence cap |
|---|---|
| 已接入因子可用率 `< 50%` | `low` |
| 关键 Layer A 因子缺失 `>= 10` | `medium` |
| 关键 Layer A 因子缺失 `>= 5` | `medium` |
| 以上都不触发 | `high` |

执行位置：

- prompt 先提醒 AI 自己不要乱给 high；
- normalizer 再强制执行 cap；
- validator 发现输出高于 context cap 时给 warning。

这意味着：以后即使 AI 忘了克制，系统也会把过高置信度压下来。

## 5. 本轮是否补齐新外部因子

本轮没有强行新增 Glassnode / CoinGlass / FRED collector。

原因：

- 当前缺失项里有不少是 `not_found` 或历史 `deprecated_candidate`；
- 新增外部接口会牵涉调度、入库、freshness、成本和额度，不适合在没有单独接口验证报告的情况下直接接入生产；
- 本轮先把这些关键缺失因子纳入 `factor_coverage` 和 confidence cap，让模型先学会“证据不够就不要 high confidence”。

本轮实际完成的是“把缺失关键因子纳入模型约束”，而不是伪造或硬接未验证数据。

## 6. 本地 pipeline run 结果

本地安全 pipeline 命令：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual
```

结果：

| 字段 | 值 |
|---|---|
| run_id | `6128ec67b116475f8a9a2ea4728ff859` |
| persisted | `true` |
| exit_code | `1` |
| ai_status | `degraded_l1_data_missing` |
| degraded_stages | `l1,l2,l5,l3,l4` |

解释：

本地数据库数据 freshness 全部过期，所以 pipeline 返回非 0，但已经成功持久化 run。这不是本轮代码失败，也不是真实交易问题。

本地最新 Layer A 摘要：

| 字段 | 值 |
|---|---|
| A1 cycle_stage | `unclear` |
| A1 confidence | `low` |
| A5 spot_action | `hold` |
| A5 confidence | `low` |
| factor_coverage.coverage_ratio | `0.0` |
| factor_coverage.confidence_cap | `low` |
| critical_unavailable_count | `16` |
| has_input_context_snapshot | `true` |
| validator.passed | `true` |

这说明 confidence cap 生效：本地数据严重过期时，Layer A 没有继续给 high confidence。

## 7. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_validator.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_orchestrator_integration.py tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：

```text
138 passed
```

已运行：

```bash
git diff --check
```

结果：通过。

## 8. 生产验证结果

生产服务器已执行：

```bash
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

结果：

| 项目 | 结果 |
|---|---|
| 服务器 commit | `50fb972 Optimize Layer A confidence and coverage modeling` |
| 服务状态 | `active` |
| `/api/system/health` | `status=ok`, `db_accessible=true`, `scheduler_running=true` |

生产安全 pipeline：

```bash
cd /home/ubuntu/btc_swing_system
.venv/bin/python scripts/run_pipeline_once.py --trigger manual
```

说明：SSH 包装命令本地侧未正常返回且日志为空，但远端已无 `run_pipeline_once.py` 残留进程；随后只读查询生产 DB，确认新 run 已写入。因此本轮按 DB 最新 run 结果作为生产验证证据。

生产最新 run：

| 字段 | 值 |
|---|---|
| run_id | `19fac5ec5a3241b9afdacc4427e81e33` |
| generated_at_utc | `2026-05-12T09:06:54Z` |
| btc_price_usd | `80862.5` |
| A1 cycle_stage | `accumulation` |
| A1 confidence | `medium` |
| A2 stance | `bullish` |
| A2 confidence | `medium` |
| A3 action candidate | `dca_buy` |
| A3 confidence | `medium` |
| A4 risk | `moderate` |
| A4 confidence | `medium` |
| A5 spot_action | `dca_buy` |
| A5 confidence | `medium` |
| factor_coverage.coverage_ratio | `0.9459` |
| factor_coverage.confidence_cap | `medium` |
| critical_unavailable_count | `16` |
| has_input_context_snapshot | `true` |
| validator.passed | `true` |
| validator.violations | `[]` |

线上 API 内部验证：

```text
has_layer_a=True
a1=accumulation
a1_conf=medium
a5=dca_buy
a5_conf=medium
coverage_cap=medium
validator={'passed': True, 'violations': [], 'warnings': []}
```

线上网页验证：

- 生产 FastAPI 首页返回 `200`；
- HTML 仍包含“大周期策略”模块；
- HTML 仍包含 Layer B “五层分析”；
- HTML 引用 `/assets/app.js?v=layer-a-web-display-20260512`；
- 公网 `http://124.222.89.86/` 未登录返回 `401`，仍是 Basic Auth 保护，属于预期。

## 9. 是否影响 Layer B / 虚拟账户 / 真实交易

| 项目 | 是否影响 |
|---|---|
| Layer B L1-L5 | 否 |
| Layer B Master | 否 |
| Layer B Validator | 否 |
| Layer B thesis | 否 |
| Layer B C 级机会 | 否 |
| 虚拟账户 | 否 |
| 真实交易 / 真实下单 | 否 |
| 仓位 / 止损 / 止盈 / 开平仓 / 反手 | 否 |

## 10. 风险和未完成

1. 本轮没有新增外部 collector，只把缺失关键因子纳入 coverage 和 confidence cap。真正补齐 RHODL、Percent Supply、LTH/STH SOPR、Exchange Balance、US2Y、M2 等，还需要单独接口验证和数据接入任务。
2. 本地 pipeline 因本地数据过期返回非 0，但 persisted=true，且 Layer A cap 行为符合预期。
3. A5 文案已经通过 prompt 限制变短，但最终文字长度仍取决于 AI 遵循程度；后续可进一步增加 post-process 摘要裁剪。
4. `input_context_snapshot` 会增加 `full_state_json` 大小，但只保存轻量因子状态和 12 条尾部样本，不保存 dataframe 或数据库。

## 11. 删除清单 / 废弃清单

本轮无替代关系，无删除项。

原因：本轮是在 Layer A 现有模块上增加 coverage / confidence cap 和 prompt 约束，没有替代旧实现。

## 12. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 138 passed |
| GitHub push | ✅ `50fb972` |
| 服务器 git pull | ✅ `50fb972` |
| 服务器 systemctl restart | ✅ `active` |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | ✅ `status=ok` |
