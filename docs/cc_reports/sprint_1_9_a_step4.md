# Sprint 1.9-A.4 — 重构 5 agent _build_user_prompt + previous_l*-l5 + 5 ❌ ContextBuilder 补项

**日期:** 2026-05-01
**Sprint 范围:** Step 4 实施(基于 Step 4.0 调研 d9f7923 + Step 5.0 v2 调研 905b1fb)
**状态:** 完成,1 commit 已 push origin/main(`2f45cd9`)
**前置:** Sprint 1.9-A.3 / Step 0 调研

---

## 0. 红线遵守

| 红线 | 状态 |
|---|---|
| 不动 6 prompt 文件(已审定) | ✅ 0 改动 |
| 不动 state_builder.py(留 Step 5) | ✅ 0 改动 |
| 不动 jobs.py / scheduler.yaml | ✅ 0 改动 |
| 不删 observation_classifier.py / cold_start.py | ✅ 不涉及 |
| 测试 §Z 端到端字段值断言 | ✅ 11 新测试全用真值断言,0 mock .called |
| 无规则结论标签 helper | ✅ crowding_signals / key_levels_rule_estimate 仍 0 引用 |

---

## 1. 改动文件清单

| 文件 | 行数变化 | 说明 |
|---|---|---|
| `src/ai/context_builder.py` | +160/-100 | 重构 build_full_context() 为 per-agent nested + 加 5 ❌ + parse_previous |
| `src/ai/orchestrator.py` | +95/-90 | 6 个 _run_* 方法重写 + L5 提前到 L3 前 + anti_pattern_signals 注入 |
| `src/ai/agents/l1_regime_analyst.py` | +6/-7 | _build_user_prompt 字段名改 |
| `src/ai/agents/l2_direction_analyst.py` | +9/-7 | 同上 |
| `src/ai/agents/l3_opportunity_analyst.py` | +10/-9 | 同上 |
| `src/ai/agents/l4_risk_analyst.py` | +9/-7 | 同上 |
| `src/ai/agents/l5_macro_analyst.py` | +8/-6 | 同上 |
| `src/ai/agents/master_adjudicator.py` | +12/-9 | 同上 + 加 _system_provided dump |
| `tests/ai/test_step4_field_alignment.py` | +191 | 新建,11 测试 |
| `tests/ai/test_context_builder_integration.py` | +51/-21 | 6 tests 改 nested 结构 |
| `tests/ai/test_orchestrator.py` | +50/-15 | _build_context helper 改 nested |

---

## 2. 5 个 ❌ 项 完整 diff

### ❌1 + ❌2:`klines_1d_30d_close` + `price_position_in_90d_range`

```python
# context_builder.py 新增 helper
def compute_price_position_in_90d_range(klines_1d):
    """0=底,100=顶。需 ≥ 90 行。"""
    if len(klines_1d) < 90: return None
    last_90 = klines_1d.iloc[-90:]
    high_90 = float(last_90["high"].max())
    low_90  = float(last_90["low"].min())
    current = float(klines_1d.iloc[-1]["close"])
    return round((current - low_90) / (high_90 - low_90) * 100, 1)

# build_full_context 内调用
klines_1d_30d_close = klines_1d["close"].iloc[-30:].tolist()
price_position_90d = compute_price_position_in_90d_range(klines_1d)

# 加入 computed_indicators dict
computed_indicators = {
    ...,
    "price_position_in_90d_range": price_position_90d,
}
```

### ❌3:`rule_cycle_position`

```python
# build_full_context 内
try:
    cp_dict = CyclePositionFactor().compute({
        "onchain": onchain, "klines_1d": klines_1d,
    })
    rule_cycle_position = {
        "label": cp_dict.get("cycle_position", "unclear"),
        "confidence": cp_dict.get("cycle_confidence", 0.30),
        "voting_details": cp_dict.get("voting_breakdown") or {},
    }
except Exception:
    rule_cycle_position = {"label": "unclear", "confidence": 0.30, ...}
```

### ❌4:`extreme_event_flags`

```python
# build_full_context 内
try:
    extreme_event_flags = detect_extreme_events(self.conn)
except Exception:
    extreme_event_flags = {<5 keys all False>}
```

### ❌5:`anti_pattern_signals`

```python
# orchestrator._run_l3 内(L5 提前跑后)
extreme_event_flags = (context.get("l5") or {}).get("extreme_event_flags") or {}
anti_pattern_signals = compute_anti_pattern_signals(
    l1_output=l1_out, l2_output=l2_out,
    current_close=shared.get("current_close"),
    extreme_event_flags=extreme_event_flags,
)
l3_input["anti_pattern_signals"] = anti_pattern_signals
```

---

## 3. 5 agent _build_user_prompt 改动清单

### L1 (`l1_regime_analyst.py`)

```diff
-    "klines_1d_summary": context.get("klines_1d_summary"),
-    "klines_4h_summary": context.get("klines_4h_summary"),
-    "indicators": context.get("indicators"),
+    "klines_1d_30d_close": context.get("klines_1d_30d_close"),
+    "computed_indicators": context.get("computed_indicators"),
     "previous_l1": context.get("previous_l1"),
```

### L2 (`l2_direction_analyst.py`)

```diff
-    "previous_l1_output": context.get("l1_output"),
-    "derivatives_snapshot": context.get("derivatives_snapshot"),
-    "onchain_structure_snapshot": context.get("onchain_structure"),
-    "price_structure": context.get("price_structure"),
+    "klines_1d_30d_close": context.get("klines_1d_30d_close"),
+    "computed_indicators": context.get("computed_indicators"),
+    "l1_output": context.get("l1_output"),
+    "rule_cycle_position": context.get("rule_cycle_position"),
+    "previous_l2": context.get("previous_l2"),
```

### L3 (`l3_opportunity_analyst.py`)

```diff
-    "previous_l1": context.get("l1_output"),
-    "previous_l2": context.get("l2_output"),
-    "asopr": context.get("asopr_value"),
-    "cdd": context.get("cdd_value"),
-    "cycle_position_rule": context.get("cycle_position_rule"),
-    "funding_pressure": context.get("funding_pressure"),
+    "l1_output": context.get("l1_output"),
+    "l2_output": context.get("l2_output"),
+    "risk_preview": context.get("risk_preview"),
+    "anti_pattern_signals": context.get("anti_pattern_signals"),
+    "current_state": context.get("current_state"),
+    "previous_l3": context.get("previous_l3"),
```

### L4 (`l4_risk_analyst.py`)

```diff
-    "previous_l1": context.get("l1_output"),
-    "previous_l2": context.get("l2_output"),
-    "previous_l3": context.get("l3_output"),
-    "current_price": context.get("current_price"),
-    "crowding_signals": context.get("crowding_signals"),   # 违反铁律 1
-    "account_state": context.get("account_state"),
+    "computed_indicators": context.get("computed_indicators"),
+    "l1_output": context.get("l1_output"),
+    "l2_output": context.get("l2_output"),
+    "l3_output": context.get("l3_output"),
+    "current_state": context.get("current_state"),
+    "previous_l4": context.get("previous_l4"),
```

### L5 (`l5_macro_analyst.py`)

```diff
-    "macro_factors": context.get("macro_factors"),
-    "events_72h": context.get("events_72h"),
-    "btc_corr_60d": context.get("btc_corr_60d"),
+    "computed_macro_indicators": context.get("computed_macro_indicators"),
+    "events_calendar_72h": context.get("events_calendar_72h"),
+    "extreme_event_flags": context.get("extreme_event_flags"),
+    "previous_l5": context.get("previous_l5"),
```

### master (`master_adjudicator.py`)

```diff
-    "state_machine_current": context.get("state_machine_current"),
-    "allowed_transitions": context.get("allowed_transitions"),
-    "account_state": context.get("account_state"),
-    "hard_invalidation_levels": context.get("hard_invalidation_levels"),
+    "current_state": context.get("current_state"),
+    "previous_strategy_run": context.get("previous_strategy_run"),
+    "_system_provided": context.get("_system_provided"),
```

---

## 4. parse_previous_layer_outputs 函数 schema

```python
def parse_previous_layer_outputs(strategy_run):
    """从 StrategyStateDAO.get_latest_state() 返回 dict 解析 layers。

    用户决策 b 方案:零 schema 变更,从现有 strategy_runs.full_state_json 解析。

    返回 6 个 key dict:
      previous_l1 / previous_l2 / previous_l3 / previous_l4 / previous_l5 /
      previous_master(各为 dict 或 None)
    """
```

支持 3 种输入:
1. `strategy_run["state"]["layers"]["l*"]`(新 v1.3 orchestrator 写入格式)
2. raw `strategy_run["full_state_json"]` 字符串(JSON parse 后取 layers.l*)
3. 旧 v1.2 格式(无 layers 键)→ 全 None

---

## 5. 11 个新测试清单

| 文件 | 测试 | 验证什么 |
|---|---|---|
| test_step4_field_alignment.py | test_l1_prompt_contains_klines_30d_close_and_computed_indicators | L1 prompt 含新字段 + 不含旧字段 |
| 同 | test_l2_prompt_contains_required_v2_fields | L2 prompt 5 字段 + 排除 4 旧字段 |
| 同 | test_l3_prompt_contains_v3_fields_no_label_drift | L3 prompt v3 字段 + 不含 3 个删除标签 |
| 同 | test_l4_prompt_contains_required_v2_fields | L4 prompt + 排除 crowding_signals(铁律 1) |
| 同 | test_l5_prompt_contains_v3_fields | L5 prompt 4 字段 + 排除旧名 |
| 同 | test_master_prompt_contains_v2_fields | master prompt 含 _system_provided + 排除 4 旧字段 |
| 同 | test_parse_previous_handles_none | parse_previous(None) → 全 None |
| 同 | test_parse_previous_handles_empty_state | empty state → 全 None |
| 同 | test_parse_previous_extracts_layers_from_full_state_json | nested layers 提取 |
| 同 | test_parse_previous_handles_raw_full_state_json_string | raw JSON 字符串解析 |
| 同 | test_parse_previous_handles_v12_legacy_format | 旧 v1.2 格式 → 全 None(不抛错) |

---

## 6. pytest 输出

```
$ uv run pytest tests/
=========== 891 passed, 1 skipped, 360 warnings in 7.92s ===========
```

- 1.9-A.3 完成时:880 passed
- 本 sprint 添 11 测试 → 891 passed, 0 failed
- 0 regression
- AI 子集:140/140 passed(58 1.8 + 71 1.9-A.3 + 11 1.9-A.4)

---

## 7. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ai/ 140/140 + tests/ 891 passed |
| GitHub push(commit 2f45cd9) | ✅ push origin/main |
| 服务器 git pull | ⏳ 待用户 SSH(可选,不接生产) |
| 服务器 systemctl restart | N/A(不动 state_builder / api routes) |
| 生产 DB 迁移 / 清污 | N/A |

**说明**:本 sprint 只动 AI orchestrator + ContextBuilder + 6 agent 文件。
state_builder.py 仍走 _RetiredV12Module stub 路径,生产 service 不受影响。

---

## 8. 用户 SSH 验证脚本

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

echo "=== ContextBuilder per-agent 嵌套结构 ==="
.venv/bin/python -c "
from src.ai.context_builder import ContextBuilder
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db'); conn.row_factory = sqlite3.Row
ctx = ContextBuilder(conn).build_full_context()
print('top keys:', sorted(ctx.keys()))
print('l1 keys:', sorted(ctx['l1'].keys()))
print('l2 keys:', sorted(ctx['l2'].keys()))
print('l3 keys:', sorted(ctx['l3'].keys()))
print('l4 keys:', sorted(ctx['l4'].keys()))
print('l5 keys:', sorted(ctx['l5'].keys()))
print('master keys:', sorted(ctx['master'].keys()))
print('extreme_event_flags:', ctx['l5']['extreme_event_flags'])
print('rule_cycle_position:', ctx['l2']['rule_cycle_position'])
print('klines_1d_30d_close len:', len(ctx['l1']['klines_1d_30d_close']))
print('price_position_in_90d:', ctx['l1']['computed_indicators'].get('price_position_in_90d_range'))
print('previous_l1 type:', type(ctx['l1']['previous_l1']).__name__)
"

echo "=== 6 agent _build_user_prompt 不报错 + 含期望字段 ==="
.venv/bin/python -c "
from src.ai.agents import L1RegimeAnalyst, L2DirectionAnalyst, L3OpportunityAnalyst, L4RiskAnalyst, L5MacroAnalyst, MasterAdjudicator
from src.ai.context_builder import ContextBuilder
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db'); conn.row_factory = sqlite3.Row
ctx = ContextBuilder(conn).build_full_context()
for cls, key in [(L1RegimeAnalyst,'l1'),(L5MacroAnalyst,'l5')]:
    agent = cls(client=None)
    prompt = agent._build_user_prompt(ctx[key])
    assert len(prompt) > 100, f'{cls.__name__} prompt too short'
    assert 'computed_indicators' in prompt or 'computed_macro_indicators' in prompt
    print(f'{cls.__name__}: prompt len={len(prompt)} OK')
print('agents OK')
"

echo "=== pytest 全套 ==="
.venv/bin/pytest tests/ 2>&1 | tail -3
# 期望:891 passed, 1 skipped, 0 failed

echo "=== service 仍 active ==="
sudo systemctl status btc-strategy.service | head -3
```

---

## 9. 与 v1.3 哲学冲突 + 解决

无新冲突。本 sprint 严格遵守:
- 删 L4 _build_user_prompt 的 `crowding_signals`(违反铁律 1,L4 自己看 funding/OI 数值判断)
- L3 `risk_preview` 仍是 1.9-A.1 的 3 客观字段(funding_z + oi_z + events_count_72h)
- 类型 B 5 类 bool(extreme_event_flags + anti_pattern_signals)是 v1.3 §3.3.5 / §3.3.3 显式定义的"系统给信号",不是规则结论标签

---

## 10. 同类风险扫描(Step 5 预警)

下一步 Step 5(state_builder.py 切 orchestrator + feature flag)风险:

1. **state_builder.py 是生产入口**(api routes + jobs 都依赖)— 任何错误立即影响 API/scheduler
2. **feature flag `BTC_USE_ORCHESTRATOR=true` 切换是单点**:
   - 切前必须本地真测一次完整 pipeline.run() with use_orchestrator=true
   - 切后必须 SSH 看 strategy_runs 新行 L1-L5 字段不再 null
3. **`_map_orchestrator_result_to_state` 是新代码**,需要测试覆盖 strategy_runs 19 列映射(尤其 observation_category + cold_start 复用 v1.2 模块)
4. **真 anthropic API 调用**(Step 7)消耗 token,需用户授权 + 单次 ≈ $0.28

5. **previous_l1-l5 解析依赖 strategy_runs.full_state_json 含 layers 键**:
   - 当前生产端 strategy_runs.full_state_json 是 v1.2 格式(无 layers 键)
   - parse_previous_layer_outputs 兼容 → 返回全 None
   - 切到 use_orchestrator 后第一次跑 previous_l*=None,从第二次起才有真值
   - 这是预期行为(冷启动)

---

## 11. Sprint 1.9-A.4 commit

```
2f45cd9 Sprint 1.9-A.4: 重构 5 agent _build_user_prompt + previous_l*-l5 + 5 ❌ ContextBuilder 补项
```

---

## 12. 总结

Sprint 1.9-A.4 完成 Step 4 全部目标:

- ✅ ContextBuilder 重构 per-agent 嵌套 + 5 ❌ 缺项全补(klines_1d_30d_close /
  price_position_in_90d_range / rule_cycle_position / extreme_event_flags
  / anti_pattern_signals 在 orchestrator)
- ✅ parse_previous_layer_outputs 实施(用户 b 方案,零 schema 改动)
- ✅ 5 agent _build_user_prompt + master 全部对齐 v3/v5 prompt 字段名
  (~25 处命名漂移修复)
- ✅ Orchestrator._run_l*() 6 个方法重写,适配新 ctx 形态 + 注入
  anti_pattern_signals + _system_provided
- ✅ 11 新测试(6 agent prompt + 5 parse_previous),pytest 891 passed,
  0 regression
- ✅ 1 commit push origin/main,生产端不受影响

下一步:Step 5 — state_builder.py 切 orchestrator + BTC_USE_ORCHESTRATOR
feature flag(高风险,需用户 SSH 验证)。
