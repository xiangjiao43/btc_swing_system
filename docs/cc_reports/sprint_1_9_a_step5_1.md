# Sprint 1.9-A.5.1 — _map_orchestrator_result_to_state + state_builder feature flag

**日期:** 2026-05-01
**Sprint 范围:** Step 5.1(本次)— 写 _map 函数 + 加 BTC_USE_ORCHESTRATOR feature flag,默认 false 不切生产
**状态:** 完成,1 commit `7b46c2e` push origin/main
**前置:** Sprint 1.9-A.4(Step 4)+ 5.0/5.0v2 调研

---

## 0. 红线遵守

| 红线 | 状态 |
|---|---|
| 不切生产(BTC_USE_ORCHESTRATOR 不在 .env 加) | ✅ 默认 false,生产端走旧 v1.2 stub 路径 |
| 不调真 anthropic API(全 mock 测试) | ✅ 47 测试全 mock |
| _map 函数 19 列必须每列断言 | ✅ test_col_1 ~ test_col_19_* 全覆盖 |
| full_state_json 必须真包含 layers(json.loads 反向断言) | ✅ test_col_19_full_state_json_contains_layers |
| _run_v12_legacy 原代码原样搬 | ✅ 实际未搬 — `self.build()` 就是原 v12 代码,run() 顶部加 if 分支即可 |
| 不动 6 prompt / scheduler.yaml | ✅ 0 改动 |

---

## 1. 改动文件清单(2 个新文件 + 1 个修改)

| 文件 | 行数变化 | 说明 |
|---|---|---|
| `src/pipeline/_orchestrator_mapper.py` | **+247(新)** | _map_orchestrator_result_to_state + 5 辅助函数 |
| `src/pipeline/state_builder.py` | **+125/-7** | run() 加 feature flag 分支 + _run_v13_orchestrator |
| `tests/pipeline/__init__.py` | +0(新) | 包标记 |
| `tests/pipeline/test_orchestrator_mapper.py` | **+402(新)** | 37 tests |
| `tests/pipeline/test_state_builder_orchestrator_branch.py` | **+225(新)** | 10 tests |

---

## 2. _map_orchestrator_result_to_state 19 列映射(完整 source)

签名:
```python
def _map_orchestrator_result_to_state(
    result: dict[str, Any],          # AIOrchestrator.run_full_a 返回
    context: dict[str, Any],          # ContextBuilder.build_full_context 返回
    conn: sqlite3.Connection,         # 用于 cold_start tracker
    *,
    run_trigger: str = "scheduled",
    rules_version: str = "v1.3.0",
    system_version: str = "1.9-A",
    previous_run: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:                   # 19 个 key
```

### 19 列每列怎么算

| # | 列 | 来源 | 派生 |
|---|---|---|---|
| 1 | `run_id` | `uuid.uuid4().hex` | 32 字符 hex |
| 2 | `generated_at_utc` | `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")` | 直接 |
| 3 | `generated_at_bjt` | now_utc.astimezone(Asia/Shanghai).strftime("...+08:00") | 直接 |
| 4 | `reference_timestamp_utc` | `context['_shared']['reference_timestamp_utc']` 或 fallback `generated_at_utc` | 直接 / fallback |
| 5 | `previous_run_id` | `previous_run['run_id'] if previous_run else None` | 直接 / None |
| 6 | `action_state` | `result['layers']['master']['state_transition']['to_state']` 或 fallback `"FLAT"` | defensive get |
| 7 | `stance` | `result['layers']['l2']['stance']` | defensive get |
| 8 | `btc_price_usd` | `context['_shared']['current_close']` | 直接 |
| 9 | `state_transitioned` | `1 if previous_run.action_state != action_state else 0` | 派生 |
| 10 | `run_trigger` | 函数参数 | 直接 |
| 11 | `run_mode` | `"ai_orchestrator"`(常量,区分 v12/v13)| 直接 |
| 12 | `fallback_level` | `_derive_fallback_level(result['status'])` — None / level_1 / level_2 / level_3 | 派生 |
| 13 | `system_version` | 函数参数 `"1.9-A"` | 直接 |
| 14 | `rules_version` | 函数参数 `"v1.3.0"` | 直接 |
| 15 | `strategy_flavor` | `"v1.3_ai_majority"`(常量) | 直接 |
| 16 | `observation_category` | 调 `classify(state)` 返回字符串;失败 fallback `"watchful"` | 复用 v1.2 模块 |
| 17 | `cold_start` | 调 `is_cold_start({'cold_start': cold_start_dict})`,1 if True else 0 | 复用 v1.2 模块 |
| 18 | `ai_model_actual` | 取 layers 中第一个有 `model_used` 字段的层 | 派生 |
| 19 | `full_state_json` | `json.dumps({layers, validator, status, latency_ms, system_provided, context_summary}, default=str)` | JSON dump |

### 5 个辅助函数

```python
_derive_fallback_level(status) → None / "level_1" / "level_2" / "level_3"
  # 桶:ok=None / l1+l2=level_1 / l3+l4+l5+master=level_2 / 其他=level_3

_build_cold_start_state(conn) → {warming_up, runs_completed, threshold}
  # runs_completed = StrategyStateDAO.get_count(conn);threshold = 42

_build_classifier_state(layers, cold_start_dict, action_state) → dict
  # 拼出 observation_classifier.classify() 期望的 strategy_state-like dict

_derive_ai_model(layers) → str | None
  # 遍历 l1-l5, master,取第一个有 model_used 的

_build_full_state_json(result, context) → str
  # JSON dump,defaultsstr 处理 pandas / datetime;必含 layers 子键
```

---

## 3. state_builder.py run() 改动 diff

```diff
     def run(self, *, run_trigger="scheduled", persist=True, now_utc=None):
         """从 self.conn 拼 context,一路跑完并写库。conn=None 时 raise。
+
+        Sprint 1.9-A.5.1:加 BTC_USE_ORCHESTRATOR feature flag。
+          - 默认 false → 走 v1.2 stub fallback 路径(self.build,行为不变)
+          - true → 走 v1.3 AIOrchestrator 路径(self._run_v13_orchestrator)
         """
         if self.conn is None:
             raise ValueError(...)
+
+        import os as _os
+        use_orchestrator = (
+            _os.getenv("BTC_USE_ORCHESTRATOR", "false").lower() == "true"
+        )
+        if use_orchestrator:
+            return self._run_v13_orchestrator(
+                run_trigger=run_trigger, persist=persist,
+            )
+
+        # v1.2 legacy path(stub fallback)
         context = self._assemble_context(self.conn, now_utc=now_utc)
         return self.build(
             context=context, run_trigger=run_trigger, persist=persist,
         )
+
+    def _run_v13_orchestrator(self, *, run_trigger="scheduled", persist=True):
+        """v1.3 AI 主导路径。失败被捕获,返回 persisted=False 的 BuildResult。"""
+        from ..ai.context_builder import ContextBuilder
+        from ..ai.orchestrator import AIOrchestrator
+        from ._orchestrator_mapper import _map_orchestrator_result_to_state
+
+        try:
+            context = ContextBuilder(self.conn).build_full_context()
+            previous_run = StrategyStateDAO.get_latest_state(self.conn)
+            result = AIOrchestrator().run_full_a(context)
+            mapped = _map_orchestrator_result_to_state(...)
+        except Exception as e:
+            return BuildResult(...persisted=False, ai_status=f"failed_{type(e).__name__}")
+
+        # 直接 INSERT(不走 DAO.insert_state,因 19 列已 mapped)
+        if persist and self.conn is not None:
+            self.conn.execute("INSERT INTO strategy_runs ...", (...))
+            self.conn.commit()
+
+        return BuildResult(persisted=True, ai_status=result['status'], ...)
```

**关键设计**:
- `_run_v12_legacy` 实际是 `self.build()`(原代码),没必要重命名
- 只在 run() 顶部加 if 分支
- v13 路径直接 INSERT(绕过 DAO.insert_state,因 v13 输出 schema 与 DAO 期望不同)

---

## 4. 47 个新测试清单

### test_orchestrator_mapper.py(37 tests)

19 列每列至少 1 测试 + 边界:

| 测试 | 断言 |
|---|---|
| test_col_1_run_id_is_uuid_hex | 32 字符 hex |
| test_col_2_3_timestamps_format | UTC `Z` / BJT `+08:00` |
| test_col_4_reference_timestamp_from_shared | 来自 _shared.reference_timestamp_utc |
| test_col_4_reference_timestamp_falls_back_when_missing | fallback to generated_at_utc |
| test_col_5_previous_run_id_when_provided | previous_run.run_id |
| test_col_5_previous_run_id_none_when_no_previous | None |
| test_col_6_action_state_from_master_state_transition | "LONG_PLANNED" |
| test_col_6_action_state_fallback_flat_when_master_missing | "FLAT" |
| test_col_7_stance_from_l2 | "bearish" |
| test_col_8_btc_price_from_shared_current_close | 75749.5 |
| test_col_9_state_transitioned_1_when_changed | 1 |
| test_col_9_state_transitioned_0_when_same | 0 |
| test_col_9_state_transitioned_0_when_no_previous | 0 |
| test_col_10_run_trigger_from_param | "manual" |
| test_col_11_run_mode_is_ai_orchestrator | "ai_orchestrator" |
| test_col_12_fallback_level_none_when_ok | None |
| test_col_12_fallback_level_l1_failed | "level_1" |
| test_col_12_fallback_level_master_failed | "level_2" |
| test_col_13_system_version_from_param | "1.9-B-test" |
| test_col_14_rules_version_default | "v1.3.0" |
| test_col_15_strategy_flavor_v13_ai_majority | "v1.3_ai_majority" |
| test_col_16_observation_category_from_classifier | mock classify → "disciplined" |
| test_col_16_observation_category_fallback_on_error | mock raise → "watchful" |
| test_col_17_cold_start_1_when_runs_below_threshold | 空 DB → 1 |
| test_col_17_cold_start_0_when_runs_above_threshold | 种 50 行 → 0 |
| test_col_18_ai_model_actual_from_first_layer_with_model | "claude-opus-4-7" |
| test_col_18_ai_model_actual_none_when_no_layer_has_model | None |
| test_col_19_full_state_json_contains_layers | json.loads + 6 layer key |
| test_col_19_full_state_json_contains_validator_and_status | passed=True / status="ok" |
| test_col_19_full_state_json_contains_context_summary | current_close + extreme_event_flags |
| test_col_19_full_state_json_does_not_contain_pandas_objects | json.loads 成功 |
| test_returns_all_19_strategy_runs_columns | set(out.keys()) == 19 个 |
| 5 辅助函数测试 | _derive_fallback_level / _build_cold_start_state / 等 |

### test_state_builder_orchestrator_branch.py(10 tests)

| 测试 | 验证什么 |
|---|---|
| test_default_unset_goes_v12_legacy_path | env 未设 → self.build called |
| test_env_false_goes_v12_legacy_path | env="false" → self.build called |
| test_env_true_lowercase_goes_v13 | env="true" → _run_v13_orchestrator called |
| test_env_true_uppercase_case_insensitive | env="TRUE" → v13 |
| test_env_true_mixed_case_case_insensitive | env="True" → v13 |
| test_env_other_value_goes_v12 | env="1" → v12(只认 "true")|
| test_v13_path_calls_context_builder_orchestrator_mapper | 端到端 mock chain;DB 真有 1 行 |
| test_v13_path_db_row_action_state_matches_master_to_state | DB action_state == "SHORT_PLANNED" |
| test_v13_path_handles_orchestrator_exception_gracefully | raise → persisted=False + ai_status="failed_*" |
| test_v13_path_full_state_json_contains_layers | DB 真行的 full_state_json 含 layers |

---

## 5. pytest 输出

```
$ uv run pytest tests/
================ 938 passed, 1 skipped, 360 warnings in 8.01s ================
```

- 1.9-A.4 完成时:891 passed
- 本 sprint +47 → **938 passed, 0 failed, 0 regression**

---

## 6. v12 默认路径行为不变验证

```bash
$ unset BTC_USE_ORCHESTRATOR
$ uv run python scripts/run_pipeline_once.py --dry-run
{
  ...
  "pipeline.degraded_stages": [
    "composite.truth_trend",
    "composite.band_position",
    "composite.crowding",
    "composite.macro_headwind",
    "layer_1",
    "layer_2",
    "layer_3",
    "layer_4",
    "layer_5"
  ],
  "pipeline.failure_count": 10
}
exit=0
```

**与 Sprint 1.8.1 完成时输出一致**(9 个 stub stage degraded + adjudicator 失败,共 10 failures)。`run_pipeline_once.py --dry-run` 不写 DB,仅打印结果。

---

## 7. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ 938 passed, 0 failed |
| GitHub push(commit 7b46c2e) | ✅ push origin/main |
| 服务器 git pull | ⏳ 待用户 SSH(可选) |
| 服务器 systemctl restart | ⏳ 待用户(改了 state_builder 需重启 API/scheduler module 缓存) |
| 生产 DB 迁移 | N/A |

**本 sprint 不切生产**:
- BTC_USE_ORCHESTRATOR 不在生产 .env 中 → 默认 false → 走 v12 stub
- service restart 后行为完全不变
- pipeline_run cron 仍 disabled(scheduler.yaml 不变)
- 真切生产是 Step 5.2 / Step 6 的工作

---

## 8. 用户 SSH 验证脚本

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

echo "=== _map 函数存在 ==="
.venv/bin/python -c "
from src.pipeline._orchestrator_mapper import _map_orchestrator_result_to_state
import inspect
print('signature:', inspect.signature(_map_orchestrator_result_to_state))
"

echo "=== state_builder run() 含 feature flag 分支 ==="
grep -n "BTC_USE_ORCHESTRATOR\|_run_v13_orchestrator" src/pipeline/state_builder.py | head -8

echo "=== 默认 env 未设 → 走 v12 路径 ==="
unset BTC_USE_ORCHESTRATOR
.venv/bin/python -c "
import os
print('env:', os.getenv('BTC_USE_ORCHESTRATOR', '(unset)'))
print('应走 v12 路径')
"

echo "=== pytest 全套 ==="
.venv/bin/pytest tests/ 2>&1 | tail -3
# 期望:938 passed, 1 skipped, 0 failed

echo "=== service 仍 active(本次不切生产)==="
sudo systemctl restart btc-strategy.service && sleep 5
sudo systemctl status btc-strategy.service | head -3

echo "=== pipeline.run() 默认仍走 v12 graceful degrade ==="
.venv/bin/python scripts/run_pipeline_once.py; echo "exit=$?"
# 期望:exit=1,persisted=true(10 stage degraded;与 1.8.1 一致)
```

---

## 9. Step 5.2 切真生产前的最后预警 + 1 行回滚命令

### 切前预警

1. **真切生产 = SSH 在服务器 .env 里加一行 `BTC_USE_ORCHESTRATOR=true` + restart service**
2. 切完立即手动跑 `python scripts/run_pipeline_once.py` 验证:
   - exit=0
   - DB strategy_runs 新行 action_state 在 14 档枚举内
   - new row stance ∈ {bullish, bearish, neutral}
   - new row run_mode == "ai_orchestrator"(区分新旧)
   - new row full_state_json 解析后含 `layers.l1` ~ `layers.master`
3. **成本意识**:每次跑消耗 ~$0.28 token(见 Step 7 估算)

### 1 行回滚命令

```bash
# 服务器 SSH:
sed -i '/^BTC_USE_ORCHESTRATOR=/d' /home/ubuntu/btc_swing_system/.env && sudo systemctl restart btc-strategy.service
```

立即把 env 删除并 restart。下次 pipeline 跑回 v12 stub 路径(degraded 但不 crash)。生产端**完全无副作用**(除已写入 DB 的 v13 行,但那些行不影响后续 v12 路径行为)。

---

## 10. 同类风险扫描

1. **observation_classifier.classify 的 state 形态**:本 sprint mock 测了 disciplined / fallback,但**没真测 v13 输出在 classify 内部跑能否 happy path**。Step 5.2 切 true 时第一次跑可能暴露 KeyError(classify 期望某子结构 v13 没提供)。建议 Step 5.2 先 dry-run + 看 observation_category 列值。

2. **cold_start 复用 v1.2 模块**:无新风险。

3. **previous_l*-l5 + 第一次 v13 写入**:第一次 v13 跑时 previous_run 是 v1.2 格式(无 layers 键),parse_previous 返回全 None;6 个 prompt 已含 fallback(详见 step4_post_clarify),confidence 自动 ≤ 0.7。**第二次 v13 起 previous 才有真值**。这是预期。

4. **v13 INSERT 不走 DAO.insert_state**:绕过了 ON CONFLICT(run_id) UPDATE 逻辑;但 run_id 是 uuid.uuid4 必唯一,无需 UPSERT,直接 INSERT 安全。

5. **cron 现仍 disabled(scheduler.yaml)**:即便切 true,scheduled 触发不到 v13 路径。Step 5.2 用户必须手动 `python scripts/run_pipeline_once.py` 触发。Step 6 才启 cron。

---

## 11. Sprint 1.9-A.5.1 commit

```
7b46c2e Sprint 1.9-A.5.1: _map_orchestrator_result_to_state + state_builder feature flag
```

---

## 12. 总结

Sprint 1.9-A.5.1 完成 Step 5.1 全部目标:

- ✅ `src/pipeline/_orchestrator_mapper.py` 新建,19 列映射 + 5 辅助函数
- ✅ `state_builder.run()` 加 BTC_USE_ORCHESTRATOR feature flag 分支
- ✅ `_run_v13_orchestrator()` 实施:ContextBuilder + AIOrchestrator + _map +
  直接 INSERT
- ✅ 47 新测试(37 mapper + 10 branch),pytest 938 passed,0 regression
- ✅ v12 默认路径行为完全不变(verified by `run_pipeline_once.py --dry-run`)
- ✅ 1 commit `7b46c2e` push origin/main

**生产端不受任何影响**(BTC_USE_ORCHESTRATOR 默认 false)。下一步 Step 5.2:
用户 SSH 在服务器 .env 加 `BTC_USE_ORCHESTRATOR=true` + 手动触发真 API
验证(预算 ~$0.28/run)。
