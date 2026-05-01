# Sprint 1.9-A — Prompt 修偏离 + Context Helpers(类型 A + B)

**报告日期:** 2026-05-01
**Sprint 范围:** Step 1(L3 prompt v3)+ Step 2(context_builder 类型 A)+ Step 3(extreme_event_detector + anti_pattern_signals 类型 B)
**状态:** 全部本地完成,3 个 commit 已 push origin/main
**前置:** Sprint 1.8.1.2(commit d39cd8f)+ Sprint 1.9-A Step 0 v3 调研(commit 6fe08e2)
**红线对齐:** 不动 state_builder.py / jobs.py / scheduler.yaml / 6 个 agent 的 _build_user_prompt;严格遵守 v1.3 4 条铁律

---

## 0. 4 条铁律遵守证据

| 铁律 | 检查项 | 证据 |
|---|---|---|
| 1. 给 AI 视觉 + 客观数值,不给规则结论标签 | L3 prompt risk_preview 删 3 个标签字段 | Step 1 完成 |
| 1. 同上 | context_builder 不引入任何 *_label / *_signals 类标签 | helper 全部输出客观数值 / series / dict |
| 2. 系统精确算,AI 不算 | EMA / ADX / ATR / Swing 由 helper 算 | 12 个 helper 实施 |
| 3. AI 综合判断,不依赖单一阈值 | extreme_event B 类(VIX 35+/DXY 5%+)由 L5 AI 自判 | extreme_event_detector 不实施这些阈值 |
| 4. fewshot 给数据 + 图描述 | L3 fewshot risk_preview 同步改 v3 | 第 240-244 行已改 |

---

## 1. Step 1 — L3 prompt v2 → v3(commit 3083174)

### 1.1 改动文件

`src/ai/agents/prompts/l3_opportunity.txt`

### 1.2 完整 diff

```diff
@@ 1
-你是 BTC 中长线低频双向波段交易系统的 L3 机会执行分析师(对齐建模 v1.3 §3.3.3)。
+你是 BTC 中长线低频双向波段交易系统的 L3 机会执行分析师(对齐建模 v1.3 §3.3.3)。
+版本:v3 (Sprint 1.9-A.1, 删 risk_preview 中 crowding_level / event_risk_active /
+macro_warning_count 三个规则结论标签 — L4/L5 跑在 L3 之后,且这些是 AI 综合判断
+输出而非客观值。改用纯客观 funding_rate_z_score / open_interest_z_score /
+events_count_72h)。

@@ §2 输入数据
   "risk_preview": {
-    "crowding_level": "moderate",
-    "funding_rate_z_score": 0.85,
-    "open_interest_z_score": 0.42,
-    "macro_warning_count": 0,
-    "event_risk_active": false
+    "funding_rate_z_score_90d": 0.85,
+    "open_interest_z_score_90d": 0.42,
+    "events_count_72h": 1
   },

@@ §4 grade C 描述
   - L1 transition_* + L2 stance_confidence_tier=medium
-  - L4 风险预览给中等信号(crowding_level=elevated)
+  - 风险预览给中等信号(funding_z 偏高 + events_count_72h ≥ 2)

@@ §16 fewshot 1
   "risk_preview": {
-    "crowding_level": "moderate", "funding_rate_z_score": 0.85,
-    "macro_warning_count": 0, "event_risk_active": false
+    "funding_rate_z_score_90d": 0.85,
+    "open_interest_z_score_90d": 0.42,
+    "events_count_72h": 1
   },
```

### 1.3 偏离原因

| 删除字段 | 偏离铁律 | 原因 |
|---|---|---|
| crowding_level | 1 | L4 AI 综合判断输出,L3 跑在 L4 前拿不到;给 "moderate" 是规则结论标签 |
| event_risk_active | 1 | bool 标签是规则结论 |
| macro_warning_count | 1 | "warning" 来自 L5 AI,L3 跑在 L5 前 |

保留的 funding_rate_z_score / open_interest_z_score 是纯客观 z-score(系统算),
合规。新增 events_count_72h(72h 内事件数,纯计数,合规)。

---

## 2. Step 2 — `src/ai/context_builder.py`(commit ea755ab,类型 A,~470 行)

### 2.1 文件结构

12 个 type A helper(纯客观计算)+ 1 个 ContextBuilder 主类 + 1 个 build_risk_preview 派生:

| # | helper | 输出字段(关键) | 公式 / 来源 |
|---|---|---|---|
| 1 | `compute_emas_1d(klines_1d)` | ema_20/50/200_series + current | pandas EWM(span=N, adjust=False) |
| 2 | `compute_emas_4h(klines_4h)` | ema_20/50_4h_series + current | 同上 |
| 3 | `compute_adx_14(klines_1d)` | adx_series + current + 5d_avg | Wilder smoothing(EWM alpha=1/14):TR / +DM / -DM / +DI / -DI / DX / ADX |
| 4 | `compute_atr_features(klines_1d)` | atr_14_series + current + 180d 分位 + pct_series | TR EWM + rolling(180).rank(pct) |
| 5 | `detect_swing_points(klines_1d, depth=5)` | list of {date, type='high'\|'low', price} | zigzag:depth 根 K 线内 high == max + 高于上根 |
| 6 | `compute_lth_sth_changes(onchain)` | lth/sth_supply 30d/90d_pct_change + realized_price_current | (latest - then) / then × 100 |
| 7 | `compute_exchange_flow_features(onchain)` | net_flow_30d_sum + max_outflow + series | 30d sum / min |
| 8 | `compute_funding_features(derivatives)` | current + z_score_90d + 30d_max + series | (last - μ_90d) / σ_90d |
| 9 | `compute_oi_features(derivatives)` | current + z_score_90d + series | 同 funding |
| 10 | `compute_price_features(klines_1d)` | current_close + max_drawdown_60d_pct + ema_50_slope_30d | last 60d cummax 法 / EMA-50 30d % change |
| 11 | `compute_macro_features(macro)` | dxy/vix/nasdaq/us10y/us2y/m2/fed_balance/btc_dominance/etf_flow 各 current + 30d/90d %change | 含 alias(dgs10→us10y, global_m2→m2)+ vix_30d_avg + vix_90d_max + yield_curve_2_10_spread_bps + etf_flow_30d/7d_sum_usd |
| 12 | `compute_btc_macro_corr_60d(klines_1d, macro, key)` | float(60d Pearson on pct_change) | 对齐 date 索引 + concat join inner |

### 2.2 ContextBuilder.build_full_context() 输出 schema

24 个 top-level key 全覆盖(详见 Step 0 v3 报告 §2 表):

```python
{
    # 原始数据(给 chart 渲染 + helper 复用)
    "klines_1d", "klines_4h", "derivatives", "onchain", "macro",

    # 类型 A 派生 series
    "ema_20_1d", "ema_50_1d", "ema_200_1d",
    "ema_20_4h", "ema_50_4h",
    "adx_14_1d", "atr_14_1d", "atr_180d_pct_1d",
    "swing_points_1d",
    "funding_rate_series", "open_interest_series",
    "exchange_net_flow_series",

    # 给 6 agent 的字段
    "computed_indicators",          # L1+L2+L4 共用 dict
    "computed_macro_indicators",    # L5 dict
    "btc_macro_corr_60d",
    "current_close",

    # 类型 B 预览 + events
    "events_calendar_72h",
    "events_count_72h",
    "risk_preview",  # L3 用,纯客观 3 字段

    # 类型 C 状态机 + 历史
    "current_state",
    "previous_strategy_run",
    "previous_l1", "previous_l2", "previous_l3",
    "previous_l4", "previous_l5",   # 1.9-A 占位 None,等 1.9-B 接 AIOutputsDAO
}
```

### 2.3 类型 D(orchestrator 内部映射)

`_compute_crowding_multiplier` / `_compute_event_multiplier` 已在
`src/ai/orchestrator.py` 实现(Sprint 1.8 完成),不在本 sprint 改动。

---

## 3. Step 3 — Type B helpers(commit ea755ab)

### 3.1 `src/ai/extreme_event_detector.py`(~150 行)

**真实现 2 类**:

#### `detect_flash_crash_24h(klines_1d, threshold_pct=-8.0) → bool`

逻辑:
```python
drop_from_open = (today.low - today.open) / today.open × 100
drop_from_prev_close = (today.low - prev.close) / prev.close × 100
worst = min(drop_from_open, drop_from_prev_close)
return worst < -8.0
```

近似而非精确(理想是 1h K 线 8% 跌)— 1d 数据反映"日内最低相对开盘 / 昨收"
跌幅,通常意味着盘中真发生了快速崩盘。

#### `detect_stablecoin_depeg(macro, threshold=0.985) → bool`

逻辑:从 macro DAO 取 `usdt_price` 或 `usdc_price` 当日最新值,< 0.985(脱锚 1.5%+)→ True。

DB 没有这两个 metric → False(数据缺失不视为脱锚,**绝不伪造**)。

**Stub 3 类(占位 + TODO)**:

```python
def detect_geopolitical_conflict(conn) -> bool:
    """TODO Sprint 1.10: 接入数据源(GDELT / ACLED / SipriBank)"""
    return False

def detect_major_bank_crisis(conn) -> bool:
    """TODO Sprint 1.10: FRED TED spread / SOFR / Bloomberg"""
    return False

def detect_regulatory_crackdown(conn) -> bool:
    """TODO Sprint 1.10: 手动 yaml / SEC EDGAR / Coindesk"""
    return False
```

测试 `test_stub_functions_have_todo_comments` 用 `inspect.getsource()` 强制
检查每个 stub 必含 `'TODO Sprint 1.10'` — **防止伪造数据 / 提前接线时偷工**。

#### v1.3 哲学对齐

- 类型 B(显式定义系统给 5 类 bool):**在本 detector 实施**
- B 类客观档位(VIX 35+ / DXY 5%+):**不在本 detector 实施**,由 L5 AI 看
  `computed_macro_indicators` 自己识别(铁律 3 + L5 prompt §6.B 已说明)

### 3.2 `src/ai/anti_pattern_signals.py`(~150 行)

5 个独立检测器 + 主入口:

| 函数 | 逻辑 |
|---|---|
| `is_extending_late_phase(l2_output)` | L2 phase ∈ {late, exhausted} → True |
| `is_against_long_cycle(l2_output)` | stance vs cycle_position 反向(bullish + late_bull/distribution/bear → True;bearish + accumulation/early_bull → True) |
| `is_chasing_breakout_no_pullback(l2_output, current_close)` | stance=bullish + 突破 nearest_resistance < 1% + phase ∈ {early, mid} → True;bearish 镜像 |
| `is_failing_at_resistance(l2_output, current_close)` | stance=bullish + 距 nearest_resistance < 0.5% 但未突破 → True;bearish 镜像 |
| `is_after_extreme_event_no_reset(extreme_event_flags)` | 任一 flag True → True |

主入口 `compute_anti_pattern_signals(l1_output, l2_output, current_close, extreme_event_flags, klines_1d)` → 5 bool dict。

#### v1.3 哲学对齐

5 类 bool 是 v1.3 §3.3.3 显式定义的"系统计算给 L3 用"(类型 B),AI 看到 bool
后还要综合判断 grade(铁律 3)。**本 helper 不影响铁律 1**。

### 3.3 risk_preview 派生

`build_risk_preview(funding_z, oi_z, events_count_72h)` — 纯客观 3 字段 dict
(Step 1 已说明)。

### 3.4 cycle_position 调用

ContextBuilder 暂不调用 `CyclePositionFactor().compute()`(避免与 1.9-B
集成时 context 形态变化打架)。1.9-B 在 orchestrator 调用前显式拼装。

---

## 4. 测试覆盖(71 个,commit f97b007)

### 4.1 测试文件清单

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/ai/test_context_builder.py` | 30 | 12 helper 各 2-3 场景:正常 / 缺数据 / 已知值断言 |
| `tests/ai/test_extreme_event_detector.py` | 14 | 2 真实现各 3-4 场景 + 3 stub 必含 TODO 注释 + 主入口端到端 |
| `tests/ai/test_anti_pattern_signals.py` | 21 | 5 检测器各 2-4 场景 + 主入口 3 测试 + ai_alternative 优先 |
| `tests/ai/test_context_builder_integration.py` | 6 | build_full_context 真 SQLite + 种 200 天数据,断言所有 top-level key |

### 4.2 关键测试断言示例

```python
# 强趋势 vs 震荡 ADX 对比
trend_adx = compute_adx_14(steady_uptrend_df)["adx_current"]
rng_adx = compute_adx_14(sine_wave_df)["adx_current"]
assert trend_adx > rng_adx

# Stub 防伪造
import inspect
src = inspect.getsource(detect_geopolitical_conflict)
assert "TODO Sprint 1.10" in src

# risk_preview 只 3 字段(铁律 1)
out = build_risk_preview(funding_z=0.85, oi_z=0.42, events_count_72h=1)
assert set(out.keys()) == {"funding_rate_z_score_90d",
                          "open_interest_z_score_90d",
                          "events_count_72h"}
assert "crowding_level" not in out

# 集成测试 — build_full_context 必有 24 个 top-level key
ctx = ContextBuilder(conn).build_full_context()
for k in (...required keys...): assert k in ctx
```

### 4.3 pytest 输出

```
$ uv run pytest tests/
================ 880 passed, 1 skipped, 360 warnings in 7.62s ================
```

- 1.8.1.2 完成时:809 passed
- 本 sprint 添 71 测试 → 880 passed, 0 failed, 0 new failure
- 所有原 808 测试不受影响

---

## 5. Bug 修复(测试发现)

### 5.1 `compute_macro_features` 中 `s.get("a") or s.get("b")` 在 pandas Series 上 ambiguous

```python
# 原(错):
s10 = macro.get("us10y") or macro.get("dgs10")  # ValueError if Series truthy ambiguous

# 改(对):
s10 = macro.get("us10y")
if s10 is None:
    s10 = macro.get("dgs10")
```

### 5.2 `is_against_long_cycle` ai_alternative 优先级反了

```python
# 原:rule_cycle_position 优先,ai_alternative 永不生效
cycle_label = (long_ctx.get("rule_cycle_position")
               or long_ctx.get("ai_alternative") or "")

# 改:ai_alternative 优先(L2 显式覆盖 rule)
cycle_label = (long_ctx.get("ai_alternative")
               or long_ctx.get("rule_cycle_position") or "")
```

### 5.3 集成测试需要 sqlite3.Row factory

`detect_extreme_events` 内部调用 `BTCKlinesDAO.get_recent_as_df` 要求 conn 有
Row factory。集成测试前补 `conn.row_factory = sqlite3.Row`。

---

## 6. 与 v1.3 哲学有冲突的判断 + 解决方式

### 6.1 anti_pattern 用阈值会不会违反铁律 3?

**判定:不违反**,理由:
- v1.3 §3.3.3 显式说"系统计算给 5 类 bool 给 L3 用"(类型 B 例外)
- 这些 bool 是给 AI 的"信号",AI 看到 bool 后还要综合判断 grade(grade 不
  按 bool 直接映射,见 L3 prompt §6 anti_pattern_flags 处理逻辑)

### 6.2 stub 3 类返回 False 会不会让 L5 漏判极端事件?

**风险存在但可控**:
- 1.9-A 阶段 5 类只真做 2 类(flash_crash + stablecoin_depeg),3 类 stub
- L5 prompt §6.B 还会让 AI 看 macro 数值识别历史性极端(VIX 35+ / DXY 5%+)
- 3 类 stub 触发率本就低(1.10 接源后准确率会提升)
- TODO 注释强制可见,1.10 必须做

### 6.3 detect_flash_crash_24h 用 1d K 线近似 1h 跌幅 — 准确吗?

**部分准确**:
- 真定义:1h 内跌 8%(理想)
- 我们用:1d K 线最低点比开盘 / 昨收跌 8%(近似)
- 漏报场景:1h 内跌 8% 但盘中反弹回开盘价附近 → 我们检测不到
- 误报场景:24h 内 5% × 5% 累积跌(分散事件)→ 我们可能误报
- 1.10 接 1h K 线后可改进

---

## 7. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ai/ 129 passed(58 + 71)+ tests/ 880 passed, 0 failed |
| GitHub push(commits 3083174 + ea755ab + f97b007) | ✅ 全 push origin/main |
| 服务器 git pull | ⏳ 待用户 SSH(可选;不接入 jobs.py 不影响生产) |
| 服务器 systemctl restart | N/A(无 src/ 顶层 module 改动需重启) |
| 生产 DB 迁移 / 清污 | N/A |

---

## 8. 用户 SSH 验证脚本

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

echo "=== L3 prompt v3 验证(无 crowding_level / event_risk_active / macro_warning_count)==="
grep -in "crowding_level\|event_risk_active\|macro_warning_count" src/ai/agents/prompts/l3_opportunity.txt
# 期望:仅头部 v3 注释行匹配,不含字段引用

echo "=== context_builder.py 存在且 import OK ==="
.venv/bin/python -c "from src.ai.context_builder import ContextBuilder; print('OK')"

echo "=== extreme_event_detector.py 存在且 5 类 bool 输出 ==="
.venv/bin/python -c "
from src.ai.extreme_event_detector import detect_extreme_events
import sqlite3
conn = sqlite3.connect('data/btc_strategy.db')
conn.row_factory = sqlite3.Row
flags = detect_extreme_events(conn)
print('flags:', flags)
assert set(flags.keys()) == {'flash_crash_detected_24h', 'stablecoin_depeg_active',
    'geopolitical_conflict_active', 'major_bank_crisis_signal',
    'regulatory_crackdown_recent'}
print('OK: 5 类 flags')
"

echo "=== anti_pattern_signals.py 5 类输出 ==="
.venv/bin/python -c "
from src.ai.anti_pattern_signals import compute_anti_pattern_signals
out = compute_anti_pattern_signals({'regime': 'trend_up'},
    {'stance': 'bullish', 'phase': 'early',
     'key_levels': {'nearest_resistance': 78900, 'nearest_support': 75320},
     'long_cycle_context': {'rule_cycle_position': 'early_bull'}},
    current_close=75320.0)
print(out)
assert len(out) == 5
print('OK: 5 类 anti_pattern bool')
"

echo "=== pytest 全套 ==="
.venv/bin/pytest tests/ 2>&1 | tail -3
# 期望:880 passed, 1 skipped, 0 failed

echo "=== service 仍 active(本次不改主流程,service 不应受影响)==="
sudo systemctl status btc-strategy.service | head -3
```

---

## 9. 同类风险扫描

1. **5 个 agent 的 _build_user_prompt 与 v5 prompt 字段名漂移**:
   Sprint 1.9-A Step 0 v3 报告 §4 已列出 — 1.9-A 后续对话(2)需修。
   本对话(1)按红线"不动 6 个 agent _build_user_prompt"未做。

2. **AIOutputsDAO 未实施**:
   previous_l1-l5 均为 None 占位。1.9-B 需实施(新表 + 新 DAO + schema migration)。

3. **3 类 extreme stub 长期不接源**会让 AI 漏识极端事件 ⏭️ Sprint 1.10
   接数据源(代码已留 TODO 强制可见)。

4. **detect_flash_crash_24h 用 1d 数据近似 1h** — 1.10 接 1h K 线后改进。

5. **anti_pattern_signals 用阈值**(0.5% / 1% 等)— v1.3 §3.3.3 类型 B 例外
   允许,但 1.11 回测时如果 anti_pattern 误报率高,需调阈值或重写逻辑。

---

## 10. Sprint 1.9-A 全部 commit 列表(共 4 个)

```
f97b007 Sprint 1.9-A: 71 tests for context_builder + extreme_event_detector + anti_pattern_signals
ea755ab Sprint 1.9-A.2+3: 新建 context_builder + extreme_event_detector + anti_pattern_signals
3083174 Sprint 1.9-A.1: L3 prompt v3, 去 risk_preview 标签偏离
6fe08e2 docs(sprint): 1.9-A Step 0 v3 context gap (严格 v1.3 哲学)
```

---

## 11. 后续 Sprint 1.9 路线

| Sprint | 目标 |
|---|---|
| 1.9-A 对话 2 | 修 5 agent `_build_user_prompt`(对齐 v5 prompt 字段名)+ 类型 C(AIOutputsDAO + schema 迁移) |
| 1.9-B | state_builder.run() 切换到 AIOrchestrator + scheduler.yaml pipeline_run 重启 |
| 1.10 | 因子卡文案细化 + 3 类 extreme_event stub 接源 + 1h 数据接入 + freezegun 全局时间冻结 |
| 1.11 | M26 回测 + AI prompt 微调 + anti_pattern 阈值校准 |

---

## 12. 总结

Sprint 1.9-A 完成了 v1.3 主流程切换前的 context 构造层 + L3 prompt 偏离修复:

- ✅ Step 1:L3 prompt v3 删 3 个规则结论标签(铁律 1 合规)
- ✅ Step 2:`src/ai/context_builder.py` 12 个 type A helper + ContextBuilder 主类
  (~470 行纯客观计算)
- ✅ Step 3:`src/ai/extreme_event_detector.py`(2 真 + 3 stub)+
  `src/ai/anti_pattern_signals.py`(5 检测器)+ `build_risk_preview` 派生
- ✅ 71 个新测试全过,pytest tests/ 880 passed, 0 failed, 0 new failures
- ✅ 4 commit 全 push origin/main

红线全守住:不动 state_builder / jobs.py / scheduler.yaml / 6 agent
_build_user_prompt;无规则结论标签 helper;3 stub 必含 TODO Sprint 1.10。
