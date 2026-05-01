# Sprint 1.9-A Step 5.0 — `_map_orchestrator_result_to_state` schema 映射调研

**日期:** 2026-05-01
**范围:** 调研 only,不动代码
**目的:** 列出 `_map_orchestrator_result_to_state(result, context, run_trigger)` 的完整签名 + strategy_runs 表 19 列的来源映射

---

## 1. strategy_runs 表 schema(19 列,源文件 `src/data/storage/schema.sql:19-39`)

```sql
CREATE TABLE IF NOT EXISTS strategy_runs (
    run_id                   TEXT PRIMARY KEY,
    generated_at_utc         TEXT NOT NULL,
    generated_at_bjt         TEXT NOT NULL,
    reference_timestamp_utc  TEXT,
    previous_run_id          TEXT,
    action_state             TEXT NOT NULL,
    stance                   TEXT,
    btc_price_usd            REAL,
    state_transitioned       INTEGER,
    run_trigger              TEXT,
    run_mode                 TEXT,
    fallback_level           TEXT,
    system_version           TEXT,
    rules_version            TEXT,
    strategy_flavor          TEXT DEFAULT 'swing',
    observation_category     TEXT,
    cold_start               INTEGER DEFAULT 0,
    ai_model_actual          TEXT,
    full_state_json          TEXT NOT NULL
);
```

---

## 2. orchestrator.run_full_a(context) 返回结构

```python
{
    "layers": {
        "l1": <L1Output dict>,       # regime, regime_stability, volatility_regime, confidence, ...
        "l2": <L2Output dict>,       # stance, stance_confidence_tier, phase, key_levels, ...
        "l3": <L3Output dict>,       # opportunity_grade, execution_permission, anti_pattern_flags, ...
        "l4": <L4Output dict>,       # risk_score, risk_tier, hard_invalidation_levels, position_cap_multiplier, ...
        "l5": <L5Output dict>,       # macro_stance, headwind_score, extreme_event_detected, ...
        "master": <MasterOutput dict>,  # state_transition, trade_plan, position_cap_final, ...(已被 Validator 修正)
    },
    "validator": {"violations": [...], "passed": <bool>},
    "status": "ok" | "degraded_l1_*" | "degraded_master_*" | ...,
    "latency_ms": {"l1": int, "l2": int, ..., "master": int},
    "tokens": {},  # 现 orchestrator 没填,但保留位
}
```

每层 output 关键字段(`tokens_in`/`tokens_out`/`model_used`/`latency_ms` 由 BaseAgent 在 success 时填):

- L1: `regime` (9 档), `regime_stability`, `volatility_regime`, `confidence`, `model_used`, `tokens_in`, `tokens_out`
- L2: `stance` (3 档), `phase` (6 档), `key_levels`
- L3: `opportunity_grade` (A/B/C/none), `execution_permission`, `anti_pattern_flags`
- L4: `risk_tier`, `hard_invalidation_levels`, `position_cap_multiplier`
- L5: `macro_stance`, `extreme_event_detected`
- master: `state_transition.from_state`, `state_transition.to_state` (14 档), `trade_plan.action`, `trade_plan.direction`, `position_cap_final.value`

---

## 3. `_map_orchestrator_result_to_state` 签名

```python
def _map_orchestrator_result_to_state(
    result: dict[str, Any],         # orchestrator.run_full_a 返回
    context: dict[str, Any],        # ContextBuilder.build_full_context 返回(用 current_close + previous_strategy_run)
    *,
    run_trigger: str = "scheduled", # 来自 jobs.py 调用方("scheduled" / "scheduled_8h_onchain" / "manual" / "event_*")
    rules_version: str = "v1.3.0",
    system_version: str = "1.9-A",
) -> dict[str, Any]:
    """把 orchestrator 输出映射成 strategy_runs INSERT 用的 dict。

    返回 dict 的 key 与 strategy_runs 列名一一对应,可直接 dict-style INSERT。
    """
```

---

## 4. 字段映射表

| # | strategy_runs 列 | 来源 | 类型 | 状态 |
|---|---|---|---|---|
| 1 | `run_id` | `uuid.uuid4().hex`(每次调用新生成) | TEXT | ✅ 直接 map |
| 2 | `generated_at_utc` | `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` | TEXT | ✅ |
| 3 | `generated_at_bjt` | `now_utc.astimezone(BJT).strftime(...)` | TEXT | ✅ |
| 4 | `reference_timestamp_utc` | `context.get("reference_timestamp_utc")` 或 generated_at_utc | TEXT | ✅ |
| 5 | `previous_run_id` | `context["previous_strategy_run"].get("run_id") if any else None` | TEXT \| None | ⚠️ 嵌套字段 |
| 6 | `action_state` | `result["layers"]["master"]["state_transition"]["to_state"]` | TEXT | ⚠️ 嵌套 + 14 档枚举校验 |
| 7 | `stance` | `result["layers"]["l2"]["stance"]` | TEXT | ⚠️ 嵌套 |
| 8 | `btc_price_usd` | `context.get("current_close")` | REAL | ✅ |
| 9 | `state_transitioned` | `1 if from_state != to_state else 0`(从 master.state_transition) | INTEGER | ⚠️ 派生 |
| 10 | `run_trigger` | 函数参数 `run_trigger`("scheduled" / "manual" / 等) | TEXT | ✅ |
| 11 | `run_mode` | hardcode `"orchestrator_v1.3"`(区分新旧路径) | TEXT | ✅ |
| 12 | `fallback_level` | `_derive_fallback_level(result["status"])` — `"ok"` / `"degraded_l1"` / `"degraded_master"` 等 | TEXT | ⚠️ 派生 |
| 13 | `system_version` | 函数参数 `system_version`("1.9-A") | TEXT | ✅ |
| 14 | `rules_version` | 函数参数 `rules_version`("v1.3.0") | TEXT | ✅ |
| 15 | `strategy_flavor` | hardcode `"swing"`(本系统唯一 flavor) | TEXT | ✅ |
| 16 | `observation_category` | `result["layers"]["l3"]["opportunity_grade"]` 转换("A" → "A_high_quality" 等)— **❌ orchestrator 输出无此字段,需新派生函数** | TEXT \| None | ❌ |
| 17 | `cold_start` | `0`(cold_start 由独立 base.yaml + StrategyStateDAO 跟踪,不在本 map 改) | INTEGER | ✅ 占位 |
| 18 | `ai_model_actual` | `result["layers"]["l1"].get("model_used")` 或任一非 fallback 层的 model_used | TEXT \| None | ⚠️ 派生 |
| 19 | `full_state_json` | `json.dumps({"layers": result["layers"], "validator": result["validator"], "status": result["status"], "latency_ms": result["latency_ms"], "context_summary": {...}})` | TEXT | ⚠️ 大 JSON |

---

## 5. ❌ / ⚠️ 项详细说明

### ❌1 `observation_category` — orchestrator 没直接输出

**问题**:strategy_runs 期望此字段(老 v1.2 表设计有"机会观察分类")。
v1.3 没显式重新定义。

**方案**(优先级排序):
- **方案 a**:从 `master.opportunity_grade`(主裁也输出 grade,Validator 强制
  与 L3 一致)派生 → `"high_quality"` / `"medium_quality"` / `"low_quality"` / `"no_opportunity"`
- **方案 b**:写 None,留 1.10 做 observation 分类细化
- **方案 c**:复用 `master.state_transition.to_state` 生成("LONG_PLANNED" → "long_setup",等)

**推荐 a**(信息无损 + 兼容老查询)。**留 Step 5 实施**。

### ⚠️ 派生字段(都在 _map 函数内做)

- **state_transitioned**:`1 if master.state_transition.from_state != to_state else 0`(派生函数 1 行)
- **fallback_level**:从 `result["status"]` 解析。映射:
  - `"ok"` → `"none"`
  - `"degraded_l1_*"` → `"l1_degraded"`
  - `"degraded_master_*"` → `"master_degraded"`
  - 类似(派生函数 ~10 行)
- **ai_model_actual**:取第一个有 `model_used` 字段的层(派生 5 行)
- **full_state_json**:JSON dump,但需注意 — context 含 pandas Series / DataFrame 不可直接 JSON dump,必须**只 dump result + 必要 context summary(current_close、events_count 等数值)**

### ⚠️ 嵌套字段访问 — 防 KeyError

`result["layers"]["master"]["state_transition"]["to_state"]` — 任一层缺失会
KeyError。Need defensive `(result.get("layers") or {}).get("master", {}).get(
"state_transition", {}).get("to_state", "FLAT")` 风格。

`result["layers"]["l2"]["stance"]` — 同上,fallback `"neutral"`。

每个嵌套字段映射前**必须 defensive get**,因 fallback path / degraded 路径
缺字段是常态。

---

## 6. _derive 辅助函数清单

3 个小辅助函数:

```python
def _derive_fallback_level(status: str) -> str:
    """orchestrator status → strategy_runs.fallback_level"""
    if status == "ok": return "none"
    if "degraded_l1" in status: return "l1_degraded"
    if "degraded_l2" in status: return "l2_degraded"
    if "degraded_l3" in status: return "l3_degraded"
    if "degraded_l4" in status: return "l4_degraded"
    if "degraded_l5" in status: return "l5_degraded"
    if "degraded_master" in status: return "master_degraded"
    return "unknown_degraded"


def _derive_observation_category(grade: str | None) -> str | None:
    """master.opportunity_grade → 老 strategy_runs.observation_category 兼容映射"""
    return {
        "A": "high_quality",
        "B": "medium_quality",
        "C": "low_quality",
        "none": "no_opportunity",
    }.get(grade)


def _derive_ai_model_actual(layers: dict) -> str | None:
    """取第一个带 model_used 的层"""
    for layer_name in ("l1", "l2", "l3", "l4", "l5", "master"):
        m = (layers.get(layer_name) or {}).get("model_used")
        if m: return m
    return None
```

---

## 7. full_state_json 内部 schema(便于 1.9-A.4 previous_l*-l5 解析)

```json
{
  "layers": {
    "l1": {regime, regime_stability, volatility_regime, confidence, ...},
    "l2": {stance, phase, key_levels, ...},
    "l3": {opportunity_grade, execution_permission, ...},
    "l4": {risk_tier, hard_invalidation_levels, ...},
    "l5": {macro_stance, extreme_event_detected, ...},
    "master": {state_transition, trade_plan, position_cap_final, ...}
  },
  "validator": {"violations": [...], "passed": <bool>},
  "status": "ok" | "degraded_*",
  "latency_ms": {"l1": int, ..., "master": int},
  "context_summary": {
    "current_close": float,
    "events_count_72h": int,
    "btc_macro_corr_60d": float | null,
    "anti_pattern_signals": {5 bool},
    "extreme_event_flags": {5 bool},
    "computed_indicators_keys": [list of keys for audit]
  },
  "system_version": "1.9-A",
  "rules_version": "v1.3.0"
}
```

**注:** 不 dump pandas Series / DataFrame(too big + JSON 不支持)。Dump 数
值汇总即可。`previous_l*-l5` 从 `layers.l1-l5` 直接取。

---

## 8. 总览 + Step 5 实施清单

| 类型 | 数量 | 处置 |
|---|---|---|
| ✅ 直接 map | 9 列 | 直接赋值 |
| ⚠️ 嵌套访问 / 轻度派生 | 9 列 | defensive get + 3 个 _derive 辅助 |
| ❌ orchestrator 无,需新派生 | 1 列(observation_category) | **方案 a:从 master.opportunity_grade 派生** — 在 Step 5 实施 |

**结论**:Step 5 可执行,无 blocker;1 个 ❌ 项在 Step 5 实施时一并补 _derive_observation_category 函数。

---

## 9. 2 个 Step 5 待用户决策点

| 决策点 | 默认 | 备选 |
|---|---|---|
| `observation_category` 来源 | 方案 a(从 master.opportunity_grade 派生) | b: None 占位;c: 从 to_state 派生 |
| `cold_start` 字段 | 0 占位(独立 base.yaml + StrategyStateDAO 跟踪不动) | 在 _map 内 query DB 得 cold_start 状态(轻量) |

**推荐:** 都按默认。等用户审本报告后启动 Step 5。
