# Sprint 1.9-A.4 Post 澄清调研

**日期:** 2026-05-01
**范围:** 调研 only(只读 grep + git show + 1 行 python)
**目的:** 澄清 1.9-A.4 ContextBuilder 重构对原有代码 / 测试的实际破坏范围 +
首次 use_orchestrator 跑时 previous_l*-l5 全 None 的真实风险

---

## 1. ContextBuilder 重构破坏范围

### 1.1 build_full_context() 实际返回结构(已切换)

```
top keys: ['_shared', 'l1', 'l2', 'l3', 'l4', 'l5', 'master']
is nested: True
```

**结论**:已切换为 per-agent 嵌套结构。**旧的 flat dict API 不再存在**(无 adapter / 双轨,**直接替换**)。

### 1.2 1.9-A 对话 1 的 71 个测试 影响范围

`git show 2f45cd9 --stat -- tests/ai/test_context_builder*`:

| 文件 | 改动 |
|---|---|
| `tests/ai/test_context_builder.py`(30 helper unit tests)| **0 行改动**(unit tests 测的是独立 helper 函数,不依赖 ContextBuilder 的整体结构)|
| `tests/ai/test_context_builder_integration.py`(6 集成 tests)| **+56/-27 行改动**(全部 6 个 test 改写为 nested 断言;无 adapter,无双轨)|
| `tests/ai/test_extreme_event_detector.py`(14 tests)| **0 行改动**(测独立 detect_* 函数)|
| `tests/ai/test_anti_pattern_signals.py`(21 tests)| **0 行改动**(测独立 compute_* 函数)|
| `tests/ai/test_orchestrator.py`(11 tests)| **+50/-15 行改动**(_build_context helper 改 nested)|

**结论**:**71 个对话 1 测试中 65 个 0 改动,6 个 integration 测试改写**;最终 891 passed 0 failed,**无 regression**。重构方式 = **直接替换 + 改老测试**(不是加 adapter / 不是双轨)。

---

## 2. 6 prompt 对 previous_l1-l5 引用强度

逐 prompt grep + 关键句解读:

### L1 prompt(强引用)

| 行号 | 引用场景 | 必填 / 可选 |
|---|---|---|
| 89-90 | "stable: 当前 regime 与 previous_l1.regime 一致" / "shifting: 不同" | **regime_stability 输出依赖** |
| 93 | "特殊情况:previous_l1 不存在(首次运行)→ regime_stability='uncertain' + notes 加 'first_run_no_previous_l1'" | **明确 fallback** |
| 117 | "首次运行(无 previous_l1)→ confidence 在 0.5-0.7" | confidence 校准 fallback |
| 141 | "缺 previous_l1 → 不扣分(首次运行属正常)" | data_completeness 不扣 |
| 146 | "优先维持与 previous_l1 一致的判断" | 切换信号阈值 |

**结论 L1**:**有 fallback** — 缺时输出 regime_stability='uncertain' + first_run notes,confidence 自动降到 0.5-0.7。

### L2 prompt(弱引用)

| 行号 | 引用场景 | 必填 / 可选 |
|---|---|---|
| 185 | "首次运行(无 previous_l2)→ confidence 在 0.5-0.7" | confidence 校准 |
| 211 | "缺 previous_l2 → 不扣分" | data_completeness 不扣 |

**结论 L2**:**有 fallback** — 仅影响 confidence 校准 + 不扣 data_completeness 分。

### L3 prompt(弱引用)

| 行号 | 引用场景 | 必填 / 可选 |
|---|---|---|
| 161 | "首次运行(无 previous_l3)→ confidence 在 0.5-0.7" | confidence 校准 |
| 189 | "缺 previous_l3 → 不扣" | data_completeness 不扣 |

**结论 L3**:**有 fallback** — 同 L2。

### L4 prompt(中等引用)

| 行号 | 引用场景 | 必填 / 可选 |
|---|---|---|
| 195 | "首次运行 → 0.5-0.7" | confidence 校准 |
| 214 | "缺 previous_l4 → 不扣" | data_completeness 不扣 |
| 230-231 | "数据严重缺失 → 若 previous_l4 存在,保留上次 risk_tier;首次运行且数据缺失 → risk_tier=moderate,confidence ≤ 0.5" | **跨条件 fallback** |

**结论 L4**:**有 fallback + 数据缺失 + 首次运行双重处理**。

### L5 prompt(中等引用)

| 行号 | 引用场景 | 必填 / 可选 |
|---|---|---|
| 222 | "首次运行 → 0.5-0.7" | confidence 校准 |
| 246 | "缺 previous_l5 → 不扣" | data_completeness 不扣 |
| 270-271 | "若 previous_l5 存在,保留上次 macro_stance(系统连续性);首次运行且缺失 → macro_stance=neutral, confidence ≤ 0.5" | **跨条件 fallback** |

**结论 L5**:**有 fallback** — 同 L4。

### master prompt(弱引用)

| 行号 | 引用场景 | 必填 / 可选 |
|---|---|---|
| 301 | "首次运行 → 0.5-0.7" | confidence 校准(对 previous_strategy_run 整体,不是 previous_l*) |

**结论 master**:**仅 confidence 校准**。

### 总览

**6 个 prompt 全部显式处理"首次运行 / 缺 previous_l*"场景**,行为是:
- regime_stability / macro_stance fallback 到保守档位(uncertain / neutral)
- confidence 自动降到 0.5-0.7
- data_completeness 不扣分(首次运行属正常)
- L1 还会在 notes 加 "first_run_no_previous_l1" 标记

---

## 3. 风险评估

### 3.1 ContextBuilder 重构对原有代码 / 测试破坏范围

**结论:低风险,已全过**。
- 6 prompt 文件 0 改动(不在本 sprint 范围)
- 71 helper unit tests 0 改动(测独立函数)
- 6 integration tests + 11 orchestrator tests 已同步改写,全过
- 11 新 step4_field_alignment tests 验证 6 agent 字段对齐,全过
- pytest tests/ 891 passed 0 failed
- **无 regression,无双轨,无 adapter,直接替换**

### 3.2 第一次 use_orchestrator=true 跑时 previous_l*-l5 全 None 的风险

**等级:低**(prompt 已显式 fallback,行为保守可预测)。

理由:
- 6 个 prompt 全部含"首次运行 / 缺 previous_l*"分支(详见 §2 表)
- L1 输出会自带 `regime_stability="uncertain"` + `notes=["first_run_no_previous_l1"]`,Validator 不会拒绝
- L4 / L5 给保守 fallback(risk_tier=moderate / macro_stance=neutral)
- 整套 confidence 自动降到 0.5-0.7,master 信心也下调,不会触发激进 trade_plan
- 第二次跑(distance ≥ 1 cron 间隔)起,parse_previous_layer_outputs 从
  上一次 run 的 full_state_json 提取 previous_l*,行为正常

**唯一风险点**:首次写入的 strategy_runs.full_state_json 必须含 layers 子结构(由 Step 5 `_map_orchestrator_result_to_state` 保证)。如果该函数没正确 dump layers,parse_previous 会一直返回 None → previous_l* 永远缺失 → confidence 永远 ≤ 0.7。**Step 5 实施时需用断言验证 full_state_json 含 layers。**

---

## 4. 总览结论(贴对话用)

1. **ContextBuilder 重构破坏范围**:直接替换 + 改老 integration test(无双轨/无 adapter);71 helper tests 0 改动 + 6 integration + 11 orchestrator tests 改写;891 passed 0 regression。**风险:低。**

2. **首次 use_orchestrator previous=None 的风险**:6 prompt 全部含"首次运行"显式 fallback(L1=uncertain + first_run notes / L4=moderate / L5=neutral / 全部 confidence 0.5-0.7 / data_completeness 不扣),**风险:低**。**唯一关注点**:Step 5 `_map_orchestrator_result_to_state` 必须正确 dump full_state_json.layers,否则 parse_previous 永远返回 None。
