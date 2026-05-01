# Sprint 1.9-A.5.1 Post 澄清调研

**日期:** 2026-05-01
**范围:** 调研 only(grep + 1 行 sed + dry-run pipeline)
**目的:** 澄清 4 件可能影响 Step 5.2 切真生产的实施细节

---

## 1. run() vs build() 关系 + v12 行为是否真不变

**run() 签名(state_builder.py:301)**:
```python
def run(self, *, run_trigger="scheduled", persist=True, now_utc=None) -> BuildResult
```

**run() body 调用栈**:
- env="false" → `context = self._assemble_context(self.conn, now_utc=now_utc)`
- → `return self.build(context=context, run_trigger=run_trigger, persist=persist)`

**build() 是 state_builder 现有方法(line 436)**,1.8.1 + 1.9-A 期间未改动,内部 9 个 stub stage(composite × 4 + L1-L5 × 5)+ adjudicator stage 全部 raise NotImplementedError 被 _run_stage 兜成 degraded。

**结论**:
- 原指令要求"_run_v12_legacy(原代码搬过去)" — CC 实际**没新建函数,直接复用 self.build**
- 行为一致性:run() 顶部加 if 后,**else 分支 = 1.8.1 完成时的 run() 全部行为**(`self._assemble_context + self.build`)
- 唯一新增的 1 行 import + 5 行 if/return,不影响 v12 路径执行。**v12 行为真的与 1.8.1 完成时完全一致**(已用 `--dry-run` 验证 §4)

---

## 2. BuildResult v1.3 失败时是否丢字段

**BuildResult 定义(state_builder.py:174-184)**:
```python
@dataclass(slots=True)
class BuildResult:
    run_id: str
    run_timestamp_utc: str
    state: dict[str, Any]
    failures: list[dict[str, Any]] = field(default_factory=list)
    degraded_stages: list[str] = field(default_factory=list)
    ai_status: str = "unknown"
    persisted: bool = False
    duration_ms: int = 0
```

**_run_v13_orchestrator 失败时(state_builder.py 约 359-375)**:
```python
return BuildResult(
    run_id=str(uuid.uuid4()),
    run_timestamp_utc=_utc_now_iso(),
    state={},
    failures=[{"stage": "v13_orchestrator", "error": str(e)[:200]}],
    degraded_stages=["v13_orchestrator"],
    ai_status=f"failed_{type(e).__name__}",
    persisted=False,
    duration_ms=int(...),
)
```

**结论**:
- BuildResult 8 个字段:`failures` / `degraded_stages` / `ai_status` 全部填了
- 失败时 `state={}` 是**空 dict**(没有 v1.3 输出可写入,因为 ContextBuilder 或 orchestrator 在更早阶段就 raise 了)
- jobs.py 调 builder.run() 拿到这个 BuildResult,会读到 `ai_status='failed_RuntimeError'` / `failures=[{...}]`,**不丢关键字段**;但**没有 v1.3 layer 输出可看(因没跑到 layer)**;这是预期(异常前 layer 还没生成)

---

## 3. _map 对 classify() 异常处理范围

**_orchestrator_mapper.py:117-131**:
```python
# ---- 16. observation_category(调 classify,失败 fallback)----
cold_start_dict = _build_cold_start_state(conn)
classifier_state = _build_classifier_state(layers, cold_start_dict, action_state)
try:
    cls_result = classify(classifier_state)
    observation_category = (
        cls_result.get("observation_category")
        if isinstance(cls_result, dict)
        else getattr(cls_result, "observation_category", "watchful")
    ) or "watchful"
except Exception as e:                # ← 广泛兜底
    logger.warning(...)
    observation_category = "watchful"
```

**结论**:
- `except Exception as e:` —— **广泛兜底**(catch 所有 Exception,包括 KeyError / AttributeError / TypeError 等)
- CC 段 3"第一次跑可能 KeyError"是预警,但实际**已被 try/except 兜住** → fallback 到 `"watchful"`,_map 不会因 classify 内部 KeyError 而抛出 → strategy_runs 一定能写入
- 只有真实 unrecoverable 异常(如 SQLite OperationalError 在 `_build_cold_start_state(conn)` 也有 try/except)才会让 _map 抛;_run_v13_orchestrator 的外层 try/except 再兜一次 → BuildResult.persisted=False

---

## 4. 10 stage failures 具体清单

`run_pipeline_once.py --dry-run 2>&1 | grep "stage.*failed"` 真实输出:

```
1. composite.truth_trend       (1.8.1 stub)
2. composite.band_position      (1.8.1 stub)
3. composite.crowding           (1.8.1 stub)
4. composite.macro_headwind     (1.8.1 stub)
5. layer_1                      (1.8.1 stub)
6. layer_2                      (1.8.1 stub)
7. layer_3                      (1.8.1 stub)
8. layer_4                      (1.8.1 stub)
9. layer_5                      (1.8.1 stub)
10. adjudicator                 (1.8.1 stub)
```

**结论**:
- 1.8.1 完成时**实际就是 10 个**(4 composite + 5 layer + 1 adjudicator),不是 9 个
- 我之前 5.1 报告 §6 写"9 stage degraded"是**错误**(没把 adjudicator 算上)
- 真实情况:全部 10 stage 全是 1.8.1 引入的 _RetiredV12Module stub,**与 1.8.1 完成时完全一致**;本 sprint 5.1 没引入新失败 stage

---

## 5. 风险评估

| 项 | 风险 | 详情 |
|---|---|---|
| run/build 关系 | **低** | v12 路径 = self.build(原代码),else 分支 100% 复用 1.8.1 行为 |
| _run_v13 失败 BuildResult | **低** | 8 字段全填,jobs.py 不会拿到残缺对象;state={} 是预期(异常前未生成) |
| classify 异常兜底 | **低** | except Exception 广泛兜底,fallback "watchful";不会让 _map 抛异常 |
| 10 stage failures | **无风险** | 与 1.8.1 完成时 100% 一致;CC 5.1 报告 §6 写"9"是数错,实际 10 |

**结论**:Step 5.2 切真生产前的 4 个潜在隐患**全部已处理或确认无影响**。可安全切 true。

---

## 6. CC 5.1 报告需更正

`docs/cc_reports/sprint_1_9_a_step5_1.md` §6:
> 与 Sprint 1.8.1 完成时输出**一致**(9 个 stub stage degraded + adjudicator 失败,共 10 failures)

→ 实际是 **10 个 stub stage**(4 composite + 5 layer + 1 adjudicator),不是"9 + 1";数描述错,但 10 总数是对的。本调研报告记录正确版本。
