# Sprint 1.9-A.5.3 + 1.9-B 合并 — 修 summary 提取 + 启用 scheduler

**日期:** 2026-05-01
**Sprint 范围:** Step D(_build_summary_v13)+ Step A(scheduler 16:05 BJT)
**状态:** 完成,1 commit `bbc7b8e` push origin/main
**前置:** Sprint 1.9-A.5.2 真生产 v1.3 第一行 DB 写入(7m42s,run_id 72da6250...)

---

## 0. 红线遵守

| 红线 | 状态 |
|---|---|
| 不动 6 prompt 文件 | ✅ 0 改动 |
| 不动 6 agent 文件 | ✅ 0 改动 |
| 不动 orchestrator.run_full_a 主逻辑 | ✅ 只动 _build_summary_v13(在 mapper) |
| 不删 v12 路径 | ✅ state_builder.run() 仍按 BTC_USE_ORCHESTRATOR 分支 |
| .env 不在 commit 改 | ✅ 用户 SSH 自己加 BTC_USE_ORCHESTRATOR=true |
| 不主动手动触发 run_pipeline_once | ✅ 等用户决定何时跑 |

---

## 1. Step D — _build_summary_v13 提取 bug 根因 + 修法

### 1.1 根因

用户 /tmp/v13_final.log 显示 summary 字段全 null:

```json
"summary": {
  "L1.regime": null,
  "L2.stance": null,
  "adjudicator.action": null,
  ...
}
```

但 `strategy_runs.full_state_json` 有真值(L1.regime="transition_up"
/ L2.stance="bullish" / 等)。

**根因**:`scripts/run_pipeline_once.py::_summarize(state)` 读取路径是
**v1.2 形态**:
```python
l1 = (state.get("evidence_reports") or {}).get("layer_1") or {}
adj = state.get("adjudicator") or {}
```

但 v13 `BuildResult.state` 是 `{"v13_orchestrator": True, "mapped": {...}}`
—— **不含 evidence_reports / adjudicator / state_machine 等 v12 字段**,
全部 `.get()` 返回 None。

### 1.2 修法

#### (a) `src/pipeline/_orchestrator_mapper.py` 新增 `_build_summary_v13`

返回 27 字段 dict,与 v12 _summarize 同名 key 一一对应:

| key | v13 来源 |
|---|---|
| L1.regime | result["layers"]["l1"]["regime"] |
| L1.volatility | l1["volatility_regime"] |
| L2.stance | l2["stance"] |
| L2.phase | l2["phase"] |
| L2.stance_confidence | l2["stance_confidence_tier"] |
| L3.opportunity_grade | l3["opportunity_grade"] |
| L3.execution_permission | l3["execution_permission"] |
| L3.anti_pattern_flags | l3["anti_pattern_flags"] |
| L4.position_cap | l4["position_cap_multiplier"] |
| L5.macro_environment | l5["macro_stance"] |
| L5.macro_headwind_vs_btc | l5["headwind_score"] |
| ai.status | result["status"] |
| ai.tokens_in | sum(layer["tokens_in"] for layer in layers) |
| ai.tokens_out | sum(layer["tokens_out"] for layer in layers) |
| ai.summary_preview | master["narrative"][:200] |
| state_machine.previous | master["state_transition"]["from_state"] |
| state_machine.current | master["state_transition"]["to_state"] |
| state_machine.transition_reason | master["state_transition"]["transition_reasoning"] |
| state_machine.stable_in_state | from_state == to_state |
| adjudicator.action | master["trade_plan"]["action"] |
| adjudicator.direction | master["trade_plan"]["direction"] |
| adjudicator.confidence | master["confidence"] |
| adjudicator.status | master["status"] |
| adjudicator.rationale_preview | master["narrative"][:200] |
| pipeline.degraded_stages | [name for name, layer in layers if status not success] |
| pipeline.failure_count | count of degraded layers |
| run_id / reference_ts / cold_start | 从 mapped dict 取 |

#### (b) `state_builder._run_v13_orchestrator` 把 summary 放进 BuildResult.state

```python
summary = _build_summary_v13(result, mapped)
return BuildResult(
    ...,
    state={
        "v13_orchestrator": True,
        "summary": summary,           # ← 新增
        "mapped": {...},
    },
    degraded_stages=summary["pipeline.degraded_stages"],   # ← 同步派生
    ...
)
```

#### (c) `scripts/run_pipeline_once.py::_summarize()` 加 v13 检测

```python
def _summarize(state):
    # Sprint 1.9-A.5.3:v13 优先,否则走 v12
    if state.get("v13_orchestrator") is True and isinstance(
        state.get("summary"), dict,
    ):
        return state["summary"]
    # v12 原代码不变...
    l1 = (state.get("evidence_reports") or {}).get("layer_1") or {}
    ...
```

零破坏 v12 路径,只加 6 行检测分支。

---

## 2. Step A — scheduler.yaml 启用 16:05 BJT(对应 1.9-B)

### 2.1 改动

`config/scheduler.yaml`:
```diff
   pipeline_run_regular:
-    enabled: false
-    cron: {hour: '0,4,12,16,20', minute: 5}  # 5 档
+    enabled: true
+    cron: {hour: 16, minute: 5}        # 16:05 BJT(= UTC 08:05),每日 1 档
```

`pipeline_run_8h_onchain` 保持 `enabled: false`(用户决策不启)。

### 2.2 选 1 档而非 5 档的理由

- v1.3 AI orchestrator 单次跑 7-8 分钟(实测 7m42s)
- 单次成本 ~$0.30 token(全 6 AI)
- 5 档/天 = $1.5/天 = $45/月,1 档/天 = $9/月
- 16:05 BJT(= UTC 08:05)对齐美股早晨 / 亚洲日内尾段,信号最有意义
- Sprint 1.9.1 会做"持仓 4h 健康检查"补足触发频率

### 2.3 测试同步

`tests/test_scheduler_2_7_a_cron.py`:
- `expected_6 → expected_7`(加回 pipeline_run_regular)
- `test_pipeline_run_regular_cron_5_hours` 改名 `test_pipeline_run_regular_cron_at_1605_bjt`
  + 期望 `{"hour": 16, "minute": 5}`(原 `"0,4,12,16,20":5`)

---

## 3. 测试

### 3.1 新增 3 个 _build_summary_v13 测试(`tests/pipeline/test_orchestrator_mapper.py`)

| 测试 | 验证什么 |
|---|---|
| test_build_summary_v13_extracts_real_fields | 完整 result + mapped → 22+ 字段全部断言值,无 null |
| test_build_summary_v13_marks_degraded_layers | L1+L4 status="degraded_*" → degraded_stages 含 l1+l4,failure_count=2 |
| test_build_summary_v13_handles_empty_result | 空 dict → 全 None / 0,不抛异常 |

### 3.2 pytest 输出

```
$ uv run pytest tests/
================ 941 passed, 1 skipped, 360 warnings in 9.85s ================
```

- 1.9-A.5.2 完成时 938 passed
- 本 sprint +3 _build_summary_v13 测试 → 941 passed,0 failed

---

## 4. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ 941 passed, 0 failed |
| GitHub push(commit bbc7b8e) | ✅ push origin/main |
| 服务器 git pull | ⏳ 待用户 SSH |
| 服务器 .env 加 BTC_USE_ORCHESTRATOR=true | ⏳ 待用户 SSH 手加 |
| 服务器 systemctl restart | ⏳ 待用户 SSH(必做,scheduler.yaml 改了 + .env 改了) |
| 生产 DB 迁移 | N/A |

**关键**:本 commit 让代码就绪,**.env 改 + restart 由用户决定时机**。
restart 后下次 16:05 BJT cron 自动触发 v1.3 AI 跑;手动触发用
`scripts/run_pipeline_once.py`。

---

## 5. 用户 SSH 验证脚本

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

echo "=== 1. .env 加 BTC_USE_ORCHESTRATOR=true(用户决定时机)==="
grep BTC_USE_ORCHESTRATOR .env || echo "BTC_USE_ORCHESTRATOR=true" >> .env
grep BTC_USE_ORCHESTRATOR .env

echo ""
echo "=== 2. scheduler.yaml 含 16:05 BJT cron ==="
grep -A 5 "pipeline_run_regular:" config/scheduler.yaml | head -8

echo ""
echo "=== 3. pytest 全套 ==="
.venv/bin/pytest tests/ 2>&1 | tail -3
# 期望:941 passed, 1 skipped, 0 failed

echo ""
echo "=== 4. service restart + 加载新配置 ==="
sudo systemctl restart btc-strategy.service && sleep 5
sudo systemctl status btc-strategy.service | head -3

echo ""
echo "=== 5. scheduler 看新 cron 注册 ==="
sudo journalctl -u btc-strategy.service --since '1 minute ago' | grep -iE "cron|pipeline_run" | head -10

# 6.(可选)手动触发 v1.3 测一次,看 summary 字段是否真值
.venv/bin/python scripts/run_pipeline_once.py 2>&1 | tee /tmp/v13_summary_test.log
# 期望:summary.L1.regime / L2.stance / adjudicator.action 等字段都不再 null
tail -50 /tmp/v13_summary_test.log
```

---

## 6. 同类风险扫描

1. **其他 summary 提取 bug**:本 sprint 只看了 `scripts/run_pipeline_once.py::_summarize`。
   如果有其他消费 BuildResult.state 的地方(如 web API、KPI tracker、监控
   面板),它们也可能假设 v12 形态读 `evidence_reports.layer_*`。
   **建议**:`grep -rn "evidence_reports\|adjudicator\.\|state_machine\." src/api/ src/web/ src/kpi/` 排查。

2. **lifecycle / review_generator 在 v13 路径不跑**:
   v12 路径在 build() 内调 lifecycle_manager + review_generator;
   v13 路径(`_run_v13_orchestrator`)直接 INSERT,没调这些。
   **影响**:lifecycles 表 + review_reports 表在 v13 行不更新。
   1.9.1 / 1.10 时需把 lifecycle 集成进 v13 路径。

3. **scheduler.yaml `pipeline_run_8h_onchain.enabled=false`**:
   用户决策不启,但 scheduler.yaml 还保留 entry(配置对照可见性)。
   1.9.1 持仓健康检查时重新设计是否启用。

4. **16:05 BJT cron 时间合理性**:UTC 08:05 是美股开盘前 1.5 小时。
   亚洲市场已收盘。如想覆盖美股开盘后(亚洲晚上),可考虑额外加 1 档
   (如 22:05 BJT)。1.10 复盘看效果。

---

## 7. Sprint 1.9-A.5.3 + 1.9-B commit

```
bbc7b8e Sprint 1.9-A.5.3 + 1.9-B: 修 summary 提取 + 启用 scheduler 16:05 BJT
```

---

## 8. 总结

合并完成 Step D + Step A:

- ✅ `_build_summary_v13` 新增,从 result/mapped 提取 27 字段(与 v12
  _summarize 同名)
- ✅ `_run_v13_orchestrator` 填 BuildResult.state["summary"]
- ✅ `scripts/run_pipeline_once.py::_summarize` 加 v13 检测分支
- ✅ scheduler.yaml `pipeline_run_regular` 启用 + 改 16:05 BJT 每日 1 档
- ✅ 3 个 _build_summary_v13 unit 测试,pytest 941 passed
- ✅ 1 commit `bbc7b8e` push origin/main

**下一步**:用户 SSH 加 .env BTC_USE_ORCHESTRATOR=true + restart →
明日 16:05 BJT cron 首次自动触发 v1.3 AI;或手动 `python
scripts/run_pipeline_once.py` 立即验 summary 字段是否真值显示。
