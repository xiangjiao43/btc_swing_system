# Sprint 2.7-no-opp-narrative — 8 种 AI 未触发场景的纯模板 narrative

**Date:** 2026-04-26
**Branch:** main
**Type:** feat (display layer fill-in) · 100% template, zero AI

---

## 一、3 个独立 commit

| commit | 文件 | 摘要 |
|---|---|---|
| `fb69f16` | `src/strategy/no_opportunity_narrator.py`(新建,390 行) | 8 个场景生成函数 + `detect_scenario` 优先级识别 + `generate_no_opportunity_narrative` 入口。返回结构与 AI 真触发输出 100% 兼容(narrative + primary_drivers + counter_arguments + what_would_change_mind) |
| `8ec57f7` | `src/ai/adjudicator.py`(+32 / −4) | `_build_rule_output` 新增可选参数 `facts` / `state`,内部调 narrator;4 处规则路径调用点(forced 硬约束 / `_should_call_ai` 假分支 / AI 客户端不可用 / AI parse 失败)全部传入 `facts=facts, state=strategy_state`。AI 真触发路径(`_validate_and_enforce_constraints`)完全没动 |
| `c67d72c` | `tests/test_no_opportunity_narrator.py`(新建,~250 行)+ `tests/test_human_readable_style.py`(+65 / −1) | 16 个新 case:8 优先级、8 长度结构、3 schema 兼容 + 1 综合守门员;guard pattern 调整为允许"建模 §X.Y"格式(用户明确放行),仍禁止裸 §X.Y |

未单独 commit:本报告(本次补)。

---

## 二、关键设计决策

### 2.1 narrator 模板内联 vs 外部翻译表
内联(每个 `_gen_*` 函数自带局部翻译表),保持函数自包含、易追踪。

### 2.2 输出结构与 AI 路径 100% 兼容
narrator 返回的 4 段(narrative / primary_drivers / counter_arguments / what_would_change_mind)字段名、类型、嵌套结构都与 `_validate_and_enforce_constraints` 返回值一致 → 前端不需要做任何兜底,直接读 `state.adjudicator.narrative` 等字段即可。

### 2.3 `_build_rule_output` 新参数为可选
新增的 `facts: Optional[dict] = None, state: Optional[dict] = None` 默认 None,保持向后兼容(已有测试仍可不传)。只有传两者才走 narrator,缺其一退回原 `rationale` 行为。

### 2.4 grade_none 场景优先用 L3.upgrade_conditions
`_gen_grade_none` 当 `state.evidence_reports.layer_3.rule_trace.upgrade_conditions` 已经是人话且 ≥ 3 条时,直接复用作为 `what_would_change_mind`,避免重复造轮子。Sprint 2.7-readability 已把 L3 升档条件改成纯中文,本次自动受益。

### 2.5 守门员"建模 §X.Y" 例外
原 pattern `§\d+\.\d+` 一刀切禁所有章节引用。按用户指令改为 `(?<!建模 )§\d+\.\d+`(负向后视),允许"建模 §5.5"等格式,仍禁止裸 `§5.5`。

---

## 三、AI 真触发路径 grep 验证

```
$ git diff fb69f16~1..c67d72c -- src/ai/adjudicator.py | grep -E "^\+|^-" | grep -E "_validate_and_enforce_constraints|_call_ai_decide|_check_hard_constraints|_should_call_ai|_SYSTEM_PROMPT|_build_user_prompt|_validate_trade_plan"
```

→ 0 命中。AI 真触发路径(`grade ∈ {A,B,C}` 时走的代码)代码字面零改动。

---

## 四、pytest 验收

```
$ .venv/bin/python -m pytest tests/ -q
411 passed, 1 skipped, 84 warnings in 1.82s
```

新增 16 个测试(395 → 411):
- `test_no_opportunity_narrator.py::TestScenarioDetection`:8 case(优先级)
- `test_no_opportunity_narrator.py::TestNarrativeStructure`:4 case(长度 + 字段)
- `test_no_opportunity_narrator.py::TestSchemaCompat`:3 case(字段兼容)
- `test_human_readable_style.py::TestNoOpportunityNarratorNoMachineTerms`:1 case(综合扫所有字段)

---

## 五、生产部署(已完成,c67d72c 合并后跑过一次)

```
ssh ubuntu@124.222.89.86 "cd ~/btc_swing_system && git pull && sudo systemctl restart btc-strategy && .venv/bin/python scripts/run_pipeline_once.py"
→ active / pipeline.failure_count: 0
```

curl 实测(冷启动场景命中):
- `narrative`: "系统刚启动不久,数据基线还在建立中,这期间不参与任何开仓。冷启动期满(几天后)开始,系统才能完整判断市场状态。现阶段先把数据补齐、把指标算稳。"
- `primary_drivers`: 3 条(数据采集 / 组合因子上线 / 冷启动期是纪律)
- `counter_arguments`: 2 条(可能错过大行情 / 用户可参考因子卡自决)
- `what_would_change_mind`: 3 条(冷启动天数计满 / 关键指标就绪 / 5 层证据健康)

无 stance= / regime= / phase= / cycle_position= / §裸引用 / english permission 等机器术语。

---

## 六、未覆盖项 / 风险

1. **守门员场景覆盖**:`TestNoOpportunityNarratorNoMachineTerms` 只跑 8 个 minimal mock 场景,真实数据下若 evidence_reports 里冒出系统枚举值会被传入 narrator 然后再传给前端。第二道防线在 narrator 内部翻译(每个 `_gen_*` 都查表),但若有未登记枚举(如未来新增 `chaos_2`)会原样输出英文 → 守门员才能在 CI 拦截。**建议:每次新增 regime/stance/phase/cycle_position 枚举值时,同步更新 narrator 内的翻译表 + 守门员的 fixture**
2. **生产仅验证 cold_start 场景**:其它 7 个场景在生产环境难触发(extreme_event 需真出 VIX 飙升、protection 需状态机走过 PROTECTION 等)。本 sprint 只通过 unit test + mock state 覆盖,实际触发时需做线上 sample 抽查
3. **`_gen_permission_restricted` 的"哪一层主导"识别简化**:目前只看 `permission_chain.suggestions` 是否非空,没区分具体是 L4 risk / L4 crowding / L4 event_risk / L5 macro 哪一个最严。如果用户希望叙事更精确,需扩展识别逻辑
4. **fallback_level 整数支持**:`detect_scenario` 接受 `2 / 3 / "level_2" / "level_3" / "l2" / "l3"`,但 `_gen_fallback_degraded` 的 `fl_label` dict 只列了 6 种;如果真实系统出现 `"L2"`(大写)会 fallback 到 `str(fl)`,文案会略生硬
5. **本 sprint 未触碰前端 app.js**:前端原有的"从 L3 rule_trace 兜底拼凑"逻辑仍在,不会被 narrator 输出冲突(narrator 字段只是补全更多内容),但下次有空可以删掉前端的兜底,让 narrator 成为唯一来源 — 当前两套并存,容错性最好
6. **本 sprint 未单独 commit 报告 → 本次补**

---

## 七、git log(本 sprint 范围)

```
c67d72c test(narrator): add coverage for no_opportunity_narrator + style guard
8ec57f7 feat(adjudicator): wire no_opportunity_narrator into _build_rule_output
fb69f16 feat(narrator): add no_opportunity_narrator for 8 non-AI scenarios
```
