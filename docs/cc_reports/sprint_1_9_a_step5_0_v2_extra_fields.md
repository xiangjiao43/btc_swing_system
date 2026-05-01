# Sprint 1.9-A Step 5.0 v2 — observation_category + cold_start 字段补充调研

**日期:** 2026-05-01
**范围:** 调研 only,不动代码;基于 SSH `data/btc_strategy.db` 实测 + 源码核对

---

## 1. observation_category schema 字段定义

```
observation_category     TEXT,
```

**结论**:NULLABLE,无 default 值;允许 NULL / 空串 / 任意字符串。

## 2. observation_category 历史值分布

```
|7              ← NULL 或空串 7 行
disciplined|5   ← "disciplined" 5 行
```

**结论**:本地 12 行中 7 行为空 / 5 行为 "disciplined";字段是合规可空,DB 不会因 NULL 报错。

## 3. cold_start_tracker 模块

**位置**:`src/utils/cold_start.py:DEFAULT_COLD_START_RUNS=42` + `is_cold_start(strategy_state, threshold_runs=42)`
**口径**:读 `strategy_state['cold_start']['warming_up']` 或 `runs_completed < 42`(任一为真即冷启动)
**runs_completed 算法**:`state_builder._determine_cold_start` 内 `runs = int(StrategyStateDAO.get_count(self.conn))`(直接 count strategy_runs 行数)

## 4. cold_start 字段历史值分布

```
1|12   ← 本地 12 行全部 cold_start=1(warming_up)
```

**结论**:本地 DB(12 行 < 42)处于冷启动期;**生产端 102 行已过 threshold,实际生产 cold_start 应为 0**。DAO 写法(line 1010):`1 if cold_start.get("warming_up") else 0`。

## 5. observation_category / observation_classifier 残余引用

**仍活跃模块**:
- `src/strategy/observation_classifier.py`:`classify(strategy_state)` 函数,输出 4 档枚举(disciplined / watchful / possibly_suppressed / cold_start_warming_up)
- `src/pipeline/state_builder.py:1062` `_run_observation_classifier`(stage 调用)+ `_observation_fallback_payload`(line 1421,degraded 时 fallback "watchful")
- `src/strategy/__init__.py`:`from .observation_classifier import ObservationResult, classify`
- `src/data/storage/dao.py:1008`:写 strategy_runs 时 `observation.get("observation_category")`
- `src/utils/cold_start.py`:与 observation_classifier 共用 `is_cold_start`

**结论**:observation_classifier 是 v1.2 仍活跃的"自我观察分类器"模块,**不在 1.8.1 退役清单**。可在 1.9-A.5 直接复用。

---

## 6. 1 行建议(_map 函数实施)

### observation_category(NULLABLE,有现成 classifier)

**建议**:**调用现有 `classify(strategy_state)`,pass orchestrator result + cold_start dict 拼出 strategy_state-like 输入**。失败 fallback `"watchful"`(与 v1.2 行为一致,DAO 已能接 None)。

理由:
- schema 允许 NULL,所以"写 None"是合法 fallback
- 但 observation_classifier.py 是活模块,有现成 4 档分类逻辑,不调 = 浪费
- classify() 需要的输入是 dict {l1_output, l2_output, l3_output, l4_output, l5_output, composite_factors, cold_start, state_machine},orchestrator 输出能 map 80%(composite_factors 用 cycle_position 占位;state_machine 用 master.state_transition;cold_start 由 §7 处理)

### cold_start(INTEGER DEFAULT 0,有现成 tracker)

**建议**:**调用现有 `is_cold_start(state)` 算 bool,写 `1 if True else 0`**;state['cold_start'] dict 在 _map 内即时构造(`runs_completed = StrategyStateDAO.get_count(conn)`,`warming_up = runs_completed < 42`)。

理由:
- schema 有 default 0 但 v1.2 行为是"算实值"(冷启动期写 1,过期写 0)
- 写死 0 会让 cold_start 追踪失效(可能影响下游 KPI / observation_classifier)
- is_cold_start + StrategyStateDAO.get_count 是现成的 5 行调用,维持原语义零风险

---

## 7. 实施清单(给 Step 5)

新增 1 个辅助函数:

```python
def _build_observation_state_for_classifier(
    result: dict, context: dict, cold_start_dict: dict,
) -> dict:
    """把 orchestrator result 拼成 observation_classifier.classify() 期望的
    strategy_state 形状(L1-L5 outputs + cold_start + state_machine)。"""
    layers = result.get("layers") or {}
    return {
        "evidence_reports": {
            f"layer_{i}": layers.get(f"l{i}") or {}
            for i in (1, 2, 3, 4, 5)
        },
        "composite_factors": {
            # cycle_position 是 1.8.1 唯一保留的 composite,
            # 其他从 context 取(orchestrator 不算 composite)
            "cycle_position": context.get("rule_cycle_position") or {},
        },
        "cold_start": cold_start_dict,
        "state_machine": {
            "current_state": (layers.get("master") or {})
                .get("state_transition", {}).get("to_state", "FLAT"),
        },
        "ai_decision": layers.get("master") or {},
    }


def _compute_cold_start_dict(conn) -> dict:
    """复用 state_builder._determine_cold_start 口径(无需重 import)。"""
    runs = int(StrategyStateDAO.get_count(conn))
    return {
        "warming_up": runs < DEFAULT_COLD_START_RUNS,
        "runs_completed": runs,
        "threshold": DEFAULT_COLD_START_RUNS,
    }
```

`_map_orchestrator_result_to_state` 内调用:

```python
cold_start_dict = _compute_cold_start_dict(conn)
classifier_state = _build_observation_state_for_classifier(
    result, context, cold_start_dict,
)
try:
    obs_result = classify(classifier_state)
    observation_category = obs_result.observation_category
except Exception:
    observation_category = "watchful"     # fallback,与 state_builder
                                          # _observation_fallback_payload 一致
cold_start_int = 1 if cold_start_dict["warming_up"] else 0
```

无新数据源,无 schema 改动,**纯组合现有模块**。

---

## 8. 总览

| 字段 | schema | 历史 | 建议处置 | 实施 |
|---|---|---|---|---|
| observation_category | TEXT NULLABLE | 7 NULL / 5 disciplined | 调现有 `classify()` + fallback "watchful" | ~15 行调用 |
| cold_start | INTEGER DEFAULT 0 | 本地 12 行全 1(冷启动);生产 102 行应 0 | 调现有 `is_cold_start` / `StrategyStateDAO.get_count` | ~5 行调用 |

**结论**:两个字段都不写 None / 不写死 0,直接复用 v1.2 现成模块,Step 5 实施时一并补上。
