# Layer A 七阶段大周期模型更新报告

## 1. 任务目标

本轮把 Layer A「大周期策略 / 现货仓策略」的 A1 大周期阶段，从上一版 5 阶段模型更新为用户确认的 7 阶段模型，并同步 A5 动作倾向、状态机迁移规则、normalizer、validator、A1/A5 prompt、网页中文映射和测试。

本轮没有修改 Layer B 波段策略逻辑，没有修改 thesis、虚拟账户、仓位、止损、止盈、真实交易接口。

## 2. 为什么采用 7 阶段

5 阶段更像“交易动作阶段”，会把「趋势持有」和「牛市中期」混在一起，也缺少「牛熊过渡」和「牛市初段」这两个对 BTC 大周期很重要的缓冲区。

7 阶段更适合做 A1 的职责：判断 BTC 当前大周期位置；A5 再根据 A1 正式阶段、A2 链上宏观、A3 机会、A4 风险，给出最终现货动作。

## 3. 7 阶段定义

| official_cycle_stage | 中文 | 阶段含义 | A5 倾向动作 |
|---|---|---|---|
| `bear_bottom` | 熊市底部 | 极度低估、市场恐慌、长期价值区 | `strong_buy` / 强势买入 |
| `accumulation` | 底部吸筹 | 恐慌缓解、长期资金吸筹、牛市未充分确认 | `dca_buy` / 分批买入 |
| `bull_bear_transition` | 牛熊过渡 | 已脱离熊市底部，但牛市结构未充分确认 | `hold` 或谨慎分批 |
| `early_bull` | 牛市初段 | 趋势初步确认、估值未过热 | `dca_buy` 或 `hold` |
| `mid_bull` | 牛市中期 | 趋势健康，但不再便宜 | `hold` / 持有 |
| `late_bull` | 牛市后期 | 估值、盈利、情绪偏高，开始控制风险 | `scale_sell` / 分批卖出 |
| `overheated_top` | 顶部过热 | 多项指标极端，泡沫和派发风险高 | `strong_sell` / 强力卖出 |

## 4. 旧 5 阶段兼容映射

| 旧值 | 新值 |
|---|---|
| `deep_value` | `bear_bottom` |
| `trend_hold` | `mid_bull` |
| `distribution` | `late_bull` |
| `overheated_exit` | `overheated_top` |
| `accumulation` | `accumulation` |
| 无法判断的旧值 | `bull_bear_transition` |

如果上一轮不是当前 `layer_a_seven_stage_v1` 模型，状态机会标记 `recalibration`，避免把模型口径变化误读成市场一天完成阶段跳变。

## 5. 阶段迁移规则

正式阶段顺序：

`bear_bottom → accumulation → bull_bear_transition → early_bull → mid_bull → late_bull → overheated_top`

迁移规则：

- 无变化：`confirmed`
- 相邻变化：至少连续 2 次确认
- 跨级变化：至少连续 3 次确认
- 数据源异常、关键因子 stale、coverage cap 偏低、A4 high/critical 风险：不能确认升级，只能 `pending`
- 上一轮不是七阶段模型：`recalibration`

## 6. 连续确认规则

本轮继续保留上一轮状态机机制：

- A1 AI 只输出 `raw_stage_assessment`
- 系统结合上一轮状态输出 `official_cycle_stage`
- A5 只能基于 `official_cycle_stage` 做主裁
- `raw_stage_assessment` 不能直接变成正式阶段
- 跨级不能当天直接 confirmed

## 7. A5 动作映射

A5 最终动作仍保持现有 Layer A 现货动作集：

- `strong_buy`
- `dca_buy`
- `hold`
- `scale_sell`
- `strong_sell`

七阶段默认倾向：

- `bear_bottom` → `strong_buy`
- `accumulation` → `dca_buy`
- `bull_bear_transition` → `hold`，必要时谨慎分批，但不能激进买入
- `early_bull` → `dca_buy` 或 `hold`
- `mid_bull` → `hold`
- `late_bull` → `scale_sell`
- `overheated_top` → `strong_sell`

保守归一规则仍生效：

- A4 风险 high / critical 时，买入动作降为 `hold`
- `accumulation` / `early_bull` 中 AI 若给 `strong_buy`，降为 `dca_buy`
- `mid_bull` 中 AI 若给买入动作，降为 `hold`
- `late_bull` 中 AI 若给 `strong_sell`，降为 `scale_sell`

## 8. A1 context 是否保持轻量

保持轻量。

本轮没有把 Layer B 全量 context、原始因子卡片、网页字段、完整历史 JSON 塞给 A1。

本轮手动 Layer A run 的 A1 输入日志：

- A1 context 字符数：`6617`
- 估算 token：`1654`
- top-level keys：`stage_model`、`cycle_evidence_summary`、`recent_stage_history`、`instructions`
- history count：`1`

这低于本轮要求的 `< 12k`，也低于建议目标 `< 8k`。

## 9. 网页展示变化

网页大周期策略阶段中文映射同步为 7 阶段：

- 熊市底部
- 底部吸筹
- 牛熊过渡
- 牛市初段
- 牛市中期
- 牛市后期
- 顶部过热

旧值兼容显示：

- `trend_hold` 显示为「牛市中期」，不再显示旧的「趋势持有区」
- `deep_value` 显示为「熊市底部」
- `distribution` 显示为「牛市后期」
- `overheated_exit` 显示为「顶部过热」

## 10. 改动文件

| 文件 | 说明 |
|---|---|
| `src/ai/spot_cycle_stage_state.py` | 七阶段枚举、默认动作、旧阶段映射、状态迁移规则 |
| `src/ai/spot_strategy_normalizer.py` | model version 改为 `layer_a_seven_stage_v1`，fallback 和 invalid stage 归一 |
| `src/ai/spot_cycle_context_builder.py` | A1 历史阶段摘要兼容旧值映射 |
| `src/ai/agents/prompts/a1_spot_cycle.txt` | A1 prompt 改为七阶段，仍保持短输出 |
| `src/ai/agents/prompts/a5_spot_adjudicator.txt` | A5 prompt 同步七阶段动作倾向 |
| `src/ai/agents/spot_cycle_agents.py` | A1/A5 fallback 阶段改为 `mid_bull` |
| `src/ai/spot_validator.py` | warning 规则同步新阶段名 |
| `web/assets/app.js` | 七阶段中文映射、旧阶段兼容显示 |
| `tests/test_layer_a_spot_context_builder.py` | A1 轻量 context 七阶段测试 |
| `tests/test_layer_a_spot_normalize.py` | 七阶段 normalize、迁移、动作映射测试 |
| `tests/test_layer_a_spot_validator.py` | validator 测试同步新阶段 |
| `tests/test_web_modules_4_5_rp_failure.py` | 网页七阶段中文映射测试 |

## 11. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`36 passed in 0.81s`

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`139 passed in 0.08s`

待提交前运行：

```bash
git diff --check
```

## 12. Layer A 手动运行结果

已在本地执行一次：

```bash
.venv/bin/python scripts/run_layer_a_once.py --trigger manual
```

结果：

- run_id：`b8dbdea5945245a2827f90dabfc2dded`
- persisted：`true`
- status：`success`
- A1 status：`success`
- A1 elapsed：`36.19s`
- A2 status：`success`
- A3 status：`success`
- A4 status：`success`
- A5 status：`success`
- A1 cycle_stage：`accumulation`
- A5 spot_action：`hold`
- validator_passed：`true`
- violations：`[]`
- warnings：`[]`
- degraded_stages：`[]`

## 13. 是否影响 Layer B

否。

本轮没有修改 Layer B L1-L5、Master、Validator、thesis persistence、虚拟账户、订单、仓位、止损、止盈、反手规则。

## 14. 是否影响虚拟账户

否。

Layer A 仍不进入虚拟账户，不创建 thesis，不生成 entry / stop_loss / take_profit。

## 15. 是否影响真实交易

否。

本项目仍是策略建议和虚拟账户系统。本轮没有新增真实交易接口，没有真实下单。

## 16. 删除清单 / 废弃清单

| 对象 | 处理 | 原因 |
|---|---|---|
| 旧 5 阶段正式模型 | 废弃为 legacy mapping | 用户确认采用 7 阶段；旧值只做兼容映射，不再作为新输出口径 |
| `layer_a_five_stage_v1` | 废弃为旧模型版本 | 新输出版本为 `layer_a_seven_stage_v1`；旧版本触发 `recalibration` |
| 网页「趋势持有区」文案 | 废弃 | 七阶段中文改为「牛市中期」 |

## 17. 风险和未完成

1. 生产服务器需要 `git pull` 和重启服务后才会看到新七阶段映射。
2. 旧历史 run 中的五阶段值会被兼容映射；首次从旧模型切到七阶段时可能出现 `recalibration`，这是刻意设计，用来避免误判自然阶段跳变。
3. `bull_bear_transition` 在最终动作上没有新增独立动作枚举，A5 仍使用现有五个 spot_action；网页可通过阶段说明表达“谨慎分批 / 持有观察”。

## 18. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push | 待提交后记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

## 19. 用户后续命令

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
