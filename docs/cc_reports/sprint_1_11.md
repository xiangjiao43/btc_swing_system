# Sprint 1.11 — L5 Macro + AI Summary + Permission 顺序全局统一

**日期**:2026-04-23
**对应建模章节**:§4.6 L5 Macro、§4.7 AI summary 契约、§9 context_summary

---

## ⚠️ Triggers for Human Attention

### 1. **Permission 顺序 Sprint 1.10 版本与 Sprint 1.2 v2 版本保留分歧**,现用 Sprint 1.10 顺序作权威

Sprint 1.10 我选了 `can_open > cautious_open > ambush_only > no_chase > hold_only > watch > protective`(wide → strict)。Sprint 1.2 v2 里有另一版 `severity_rank`(不含 hold_only,ambush/no_chase 顺序相反)。

**Task A 决定**:把 Sprint 1.10 的顺序**提升为全局权威**(写到 thresholds.yaml 顶层 `permission_strictness_order`),其他所有地方(L3 _anti_patterns / L4 / 将来 state_machine / AI adjudicator)通过 `src/utils/permission.merge_permissions()` 调用。

Sprint 1.2 v2 的老 `severity_rank` 保留在 `layer_4_risk.execution_permission_merging` 下作文档,**代码不再读它**。后续如果 backtest 发现新顺序有问题,可回到 yaml 改全局一个字段,无需改代码。

### 2. `hold_only` vs `watch`:我的顺序把 watch 更严 — 合理吗?

顺序:`... no_chase > hold_only > watch > protective`。
语义理解:
- `hold_only`:持有现有仓位,禁新开仓(但不减仓)
- `watch`:完全不动,只看
- `protective`:主动平仓保护

语义上"完全不动 > 持有"的严格度取决于场景:若已持仓,hold_only 和 watch 都不 open 新仓,差异在是否允许减仓 trim。hold_only 允许 trim(状态机的 TRIM 动作),watch 不允许任何动作。从"系统主动性"看 watch 比 hold_only 更克制,更严。

**保留当前顺序**,但在 `merge_permissions` 测试里明确验证了这个不直观的次序。

### 3. L5 `data_completeness_pct` 建立在"全集 10 个 metric"的基础上

10 个 metric 清单:`dxy / us10y / vix / sp500 / nasdaq / gold_price / dgs10 / dff / cpi / unemployment_rate`。L5 用 len(available) / 10 算完整度。

**实际影响**:
- 只有 Yahoo 6 个 → 60%
- 只有 FRED 4 个 → 40%
- Yahoo 全 + FRED 全 → 100%

这个分母是**理想清单**,v1 实际很少达到 100%(FRED 需要 key)。若 Sprint 1.14+ 加事件日历等新 macro metric,分母也要扩。当前实现把这个清单硬编码在 `_ALL_MACRO_METRICS`,后续可配置化。

### 4. yields 计算**优先用 Yahoo 的 us10y,FRED 的 dgs10 兜底**

两者理论上是同一指标(10 年期美债收益率)。我的降级链:
```python
yields_series = macro.get("us10y") if isinstance(...) else macro.get("dgs10")
```

好处:Yahoo 可用时优先(频率高);Yahoo 限速时自动走 FRED。
副作用:若两者同时存在,Yahoo 的值被用(FRED 数据被忽略)。这是预期的,因为 FRED 作为备用。

### 5. L5 `macro_environment` **综合打分用了 4 个信号源**

信号来源:DXY 方向、yields 方向、VIX 档位、股指方向。每个信号贡献 ±1 分到 risk_on 或 risk_off。净分 ≥ +2 → risk_on,≤ -2 → risk_off,其间 → neutral。全空 → unclear。

**注意**:`yields_trend 下降 → 不直接给 risk_on +1`(yields 下降可能是衰退预期)。仅 `yields 上升 → risk_off +1`(加息担忧)。这是不对称的。

### 6. `macro_headwind_vs_btc` 新增 `mild_tailwind` band(非用户描述)

用户任务描述给了 6 个 headwind 档:`strong_headwind / mild_headwind / neutral / tailwind / independent / unknown`。实现时发现需要一个中间档表达 "risk_on 环境 + 中等相关性",我添加了 `mild_tailwind`。

若不希望扩展,改 `_derive_headwind_vs_btc` 把 mild_tailwind 合并到 tailwind。

### 7. AI Summary 的 system prompt 中文,**强制禁止价格目标/具体建议**

我写的默认 system prompt 明确要求:"禁止提供任何价格目标、具体买卖建议、止损止盈点位"。这是建模 §6 AI 纪律核心条款的落地。

若有幻觉或越界的响应,可以截断或拒收。Sprint 1.14 的 output validator 会二次校验。

### 8. AI 调用**始终返回 dict,不抛异常**

任何失败情况(无 key / 超时 / API 错):
```
{
  summary_text: None,
  status: 'degraded_error' or 'degraded_timeout',
  error: str,
  ...
}
```
下游必须检查 `status == 'success'` 才能用 summary_text。Sprint 1.14 会加规则兜底(无 AI 时生成纯拼接摘要)。

### 9. `OPENAI_API_KEY` 未设时**不构造 OpenAI client**

避免 openai SDK 在初始化时就失败。`call_ai_summary` 先检查 env,无 key 则立即返回 degraded,不尝试调用。

### 10. `tests/test_ai_summary_smoke.py` **默认 skip**

用 `@pytest.mark.skipif(not os.getenv("RUN_AI_SMOKE"))` 保护,用户手工 `RUN_AI_SMOKE=1 uv run pytest ...` 触发才真实打 API。CI 跑 `uv run pytest tests/` 永远 skip,不花 token。

跨 Sprint 联测结果:**165 passed + 1 skipped**(smoke 跳过)。

### 11. `build_evidence_summary_prompt` 接受两种 layer key 风格

`evidence_reports['layer_1']` 或 `['L1']` 都接受(`.get("layer_1") or .get("L1")`)。方便 pipeline 传统构造风格和简写混用。

### 12. `_summarize_layer` 每层提取的**字段清单**

| Layer | 提取字段 |
|---|---|
| L1 | regime, volatility_regime, regime_stability, health, tier |
| L2 | stance, phase, stance_confidence, thresholds_applied, health, tier |
| L3 | grade, execution_permission, anti_pattern_flags, observation_mode, health, tier |
| L4 | position_cap, risk_reward_ratio+rr_pass_level, stop_loss 有无, risk_permission, health |
| L5 | macro_environment, macro_headwind_vs_btc, data_completeness_pct, health |

**不送完整 diagnostics 或原始证据卡**。控制 prompt 长度 + 避免 AI 被过多字段干扰。后续 Sprint 若需要更多字段(如 swing_amplitude),改这个函数即可。

---

## 1. Task A — 统一 permission 顺序

### 变更清单
| 文件 | 说明 |
|---|---|
| `config/thresholds.yaml` | 顶层新增 `permission_strictness_order`(7 值,带中文注释);删除 `layer_4_risk.permission_strictness_order_wide_to_strict` |
| `src/utils/__init__.py` + `permission.py` | **新建**,提供 `get_permission_order / merge_permissions / is_permission_strict_enough` |
| `src/evidence/_anti_patterns.py` | 删本地 `_PERMISSION_STRICTNESS` 和 `_stricter`,改用 `merge_permissions` |
| `src/evidence/layer3_opportunity.py` | import 从 `_anti_patterns._stricter` → `utils.permission.merge_permissions` |
| `src/evidence/layer4_risk.py` | 删 `_DEFAULT_STRICTNESS` 和 `_stricter_permission`,全用 `merge_permissions` |
| `tests/test_permission_utils.py` | **新建** 15 个单测 |

### 验收
```
tests/test_permission_utils.py  15 passed
+ 跨 Sprint 全套 128 passed(L1-L4 不破坏)
```

commit `227ce08`。

---

## 2. Task B — Layer 5 Macro

### 变更清单
| 文件 | 行数 | 说明 |
|---|---|---|
| `src/evidence/layer5_macro.py` | ~360 | Layer5Macro + 辅助(trend/vix/corr/derive) |
| `src/evidence/__init__.py` | +2 | 暴露 Layer5Macro |
| `tests/test_layer5_macro.py` | ~290 | 12 tests |

### 判定流程
```
_compute_specific:
  1. metrics availability 统计(10 全集)
  2. 若全缺 → insufficient_data + unclear
  3. 逐子项计算:dxy/yields/vix/correlation(各独立,缺则 None)
  4. _derive_macro_environment(dxy, yields, vix, stock)
     → risk_on / risk_off / neutral / unclear
  5. _derive_headwind_vs_btc(env, correlation)
     → strong_headwind / mild_headwind / neutral / tailwind / mild_tailwind / independent / unknown
  6. 组装 output + diagnostics
```

### 验收
```
tests/test_layer5_macro.py  12 passed
+ 全套 140 passed(L1-L5 + permission_utils)
```

commit `68436e0`。

---

## 3. Task C — AI Summary

### 变更清单
| 文件 | 行数 | 说明 |
|---|---|---|
| `pyproject.toml` / `uv.lock` | 新增 openai>=2.32 |
| `src/ai/__init__.py` + `summary.py` | **新建**,~220 行 |
| `tests/test_ai_summary.py` | 10 tests with mock |
| `tests/test_ai_summary_smoke.py` | **默认 skip**,用户 RUN_AI_SMOKE=1 触发真实调用 |

### 关键设计
- **OpenAI-compatible** 协议,`base_url=OPENAI_API_BASE`(novaiapi.com)
- 45s 超时,最多重试 2 次(共 3 次尝试),间隔 3s
- **不抛异常**,全部通过 dict.status 字段传递结果
- `openai_client` 参数可 mock 注入,便于测试
- system prompt 强制中性、3 段、≤120 字/段、禁价格目标

### 验收
```
tests/test_ai_summary.py  10 passed(mock)
tests/test_ai_summary_smoke.py  1 skipped(默认)
+ 全套 165 passed + 1 skipped
```

commit(待提)。

### 用户手工 smoke(可选)
```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV
RUN_AI_SMOKE=1 uv run pytest tests/test_ai_summary_smoke.py -v -s
```
会真实调用 novaiapi.com,消耗 ~300-500 token,打印返回的 3 段中文摘要。

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A1 | permission 顺序采用 Sprint 1.10 版(含 hold_only)| 7 值完整,Sprint 1.2 v2 版本缺 hold_only |
| A2 | 新建 `src/utils/permission.py` 作唯一真相 | 跨层单一来源,避免重复 |
| A3 | 保留 Sprint 1.2 v2 severity_rank yaml 配置作文档 | 删除可能影响其他未知引用 |
| B1 | yields 优先 Yahoo 次 FRED | 频率 > 精度 |
| B2 | 新增 `mild_tailwind` band(6→7 档)| risk_on + 中相关 的中间态 |
| B3 | `_ALL_MACRO_METRICS` 硬编码 10 个 | 完整度分母;加新 metric 需改此清单 |
| B4 | vix 7 日急升 > 20% → is_spike flag | 未在用户任务,但 L5 对 VIX 异动的监测价值 |
| C1 | System prompt 强制禁价格目标 + 3 段 + ≤120 字 | 建模 §6 AI 纪律 |
| C2 | 失败不抛异常,dict.status 传递结果 | 下游容错友好 |
| C3 | `openai_client` 参数可注入 | 测试用 mock,避免真实调用 |
| C4 | 两种 layer key 风格(`layer_1` / `L1`)都接受 | 兼容 pipeline 传参习惯 |
| C5 | Smoke 测试默认 skip(RUN_AI_SMOKE=1 触发)| CI 免费;手工按需真跑 |
| C6 | 重试 sleep 在测试里 mock 掉 | 测试快 |
| C7 | `_summarize_layer` 每层只提取 5-6 个关键字段 | 控 prompt 长度 + 避免 AI 分心 |

---

## 5. 最终 pytest 状态

```
================ test session starts =================
...
tests/test_composite_factors.py      23 passed
tests/test_indicators.py             30 passed
tests/test_layer1_regime.py          15 passed
tests/test_layer2_direction.py       19 passed
tests/test_layer3_opportunity.py     19 passed
tests/test_layer4_risk.py            22 passed
tests/test_layer5_macro.py           12 passed  ← NEW
tests/test_ai_summary.py             10 passed  ← NEW
tests/test_ai_summary_smoke.py        1 skipped ← NEW
tests/test_permission_utils.py       15 passed  ← NEW

================ 165 passed, 1 skipped ================
```

---

## 6. Sprint 1.11 → Sprint 1.12+ 衔接

Sprint 1.11 结束后,5 层 evidence 全部就位,AI summary 打通。下一步:
- **Sprint 1.12**:Pipeline 协调层 + Observation Classifier + state_machine 骨架 + last_stable_cycle_position 对接 StrategyStateDAO
- **Sprint 1.13**:AI adjudicator(最终裁决,消费所有 evidence + summary)
- **Sprint 1.14**:Output validator + review_report(规则摘要回退)

`src.utils.permission.merge_permissions` 在 Sprint 1.12 的 state_machine 归并最终 permission 时会被继续使用,保持单一真相源。
