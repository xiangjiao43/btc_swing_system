# Sprint 2.7-C — Pre-flight 数据就绪检查 (Stage 0)

**Date:** 2026-04-27
**Branch:** main
**Status:** ✅ 完成

---

## 一、改动

### `src/scheduler/jobs.py` 拆 pipeline_run 为 2 wrapper

`job_pipeline_run` 加 `run_trigger` kwarg(默认 `'scheduled'`),透传给 `builder.run`。

新增 2 个 wrapper:
- `job_pipeline_run_regular` → `run_trigger='scheduled'`(常规档,宽松阈值)
- `job_pipeline_run_8h_onchain` → `run_trigger='scheduled_8h_onchain'`(8 点档,严格阈值)

**§X 删除** Sprint 2.7-A 引入的 `func:` yaml 字段 alias 机制 — 现在每个 yaml 条目直接命中 `_JOB_FUNCTIONS`。

### `config/scheduler.yaml`
- 删除 `func: pipeline_run` 行(2 处)
- yaml job 名 `pipeline_run_regular / pipeline_run_8h_onchain` 直接对应函数名

### `src/pipeline/state_builder.py`(核心实施)

**新增模块级:**
- `_query_metric_inserted_at(conn)` — 重用 Sprint 2.6-J 的 4 个 DAO 查询(从 `_assemble_context` 提取出来给 pre-flight 重读用)
- `_PREFLIGHT_THRESHOLDS_SEC` 字典(2 个 run_trigger × 5 个 group):
  - `scheduled`(常规):klines_1h <10min / derivatives <10min / klines_1d_4h <30h / onchain <30h / macro <30h
  - `scheduled_8h_onchain`(8 点):klines_1h <10min / derivatives <10min / klines_1d_4h <30min / onchain <10min / macro <30h
- `_latest_iso_for_group(metric_inserted_at, group)` — 从 dict 取该 group 最新 ts
- `_evaluate_freshness(metric_inserted_at, run_trigger, now_fn)` — 返回失败 group 列表
- `_run_pre_flight_freshness_check(conn, mia, run_trigger, retry_after_sec=300, sleep_fn=time.sleep)` — 主流程
  1. 立即评估 → 全 OK 直接返回
  2. 有失败 → sleep 5 min(retry_after_sec)→ 重读 inserted_at → 再评估
  3. 仍失败 → 返回失败 group 列表

**`build()` 新增 Stage 0:** 在 `RunMetadataDAO.start_run` 之后、`cold_start_check` 之前调 `_run_pre_flight_freshness_check`,把失败 group 加入 `degraded_stages` 命名为 `pre_flight.<group>`。

不阻塞:即便 retry 后还失败,pipeline 继续跑(标 degraded);只是用户在 strategy_state_history 能看到 `pre_flight.macro` 等告警。

### `tests/test_scheduler_2_7_a_cron.py` 更新

老测试 `test_pipeline_run_dual_entries_share_function` 改为 `test_pipeline_run_dual_entries_have_dedicated_wrappers`,断言 2 个 wrapper 是 2 个独立函数(2.7-A 老的"共享 func"设计已 §X 删除)。

---

## 二、新增测试 `tests/test_state_builder_pre_flight.py`(14 测试)

| 测试 | 覆盖 |
|---|---|
| `test_threshold_table_has_two_run_triggers` | yaml 与 thresholds 一致 |
| `test_8h_onchain_thresholds_strictly_tighter_for_onchain` | 8h 档 onchain 阈值 < 常规档 |
| `test_8h_onchain_klines_1d_4h_tighter` | 同上 klines_1d_4h |
| `test_latest_iso_for_group_klines_1d_4h_takes_max` | max(1d, 4h) |
| `test_latest_iso_for_group_onchain_takes_max` | max() over per-metric dict |
| `test_latest_iso_for_group_returns_none_for_empty` | 空降级 |
| `test_evaluate_freshness_all_fresh_returns_empty` | 5 group 全 fresh → 空失败 |
| `test_evaluate_freshness_klines_1h_stale_for_regular` | klines_1h 11 min 前 → 失败 |
| `test_evaluate_freshness_8h_onchain_strict_kicks_in` | 25h 前 onchain 在常规档 OK,8h 档失败 |
| `test_evaluate_freshness_unknown_run_trigger_uses_scheduled` | event_macro 等用 scheduled 阈值 |
| `test_pre_flight_passes_with_fresh_data` | 真 SQLite + 真数据 → 无 sleep,无降级 |
| `test_pre_flight_fails_then_retries_then_still_fails` | 空 DB → sleep 1 次(300s)→ 5 group 全降级 |
| `test_pre_flight_fails_then_retry_succeeds_after_data_arrives` | sleep 期间数据落地 → 重试通过 |
| `test_pre_flight_returns_refreshed_metric_inserted_at` | 重读后的 dict 回传给上游 |
| `test_build_includes_pre_flight_in_degraded_stages_when_data_missing` | 端到端 build() → degraded_stages 含 pre_flight.* |

§Z:测试用真 SQLite + 真 DAO,断言 `result.degraded_stages` 字符串列表精确含 `pre_flight.X`。

---

## 三、用户验证

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 3
sqlite3 data/btc_strategy.db <<'SQL'
SELECT run_id, run_trigger,
       json_extract(full_state_json, '$.degraded_stages') AS degraded
FROM strategy_runs
ORDER BY generated_at_utc DESC
LIMIT 5;
SQL
SSH
```

预期:正常档(`scheduled`)无 pre_flight 降级;8 点档(`scheduled_8h_onchain`)如果 onchain 慢可能含 `pre_flight.onchain`。

---

## 四、§X / §Y / §Z

- ✅ §X:Sprint 2.7-A 引入的 `func:` yaml alias 机制本 sprint 删除(`build_job_configs` 不再读 `func` 字段)。yaml 同步删除 `func: pipeline_run` 行。
- ✅ §Y:本 commit 立即 push origin/main
- ✅ §Z:14 测试断言真 DB + degraded_stages 字符串精确匹配,sleep_fn 用 monkeypatch 注入观察重试次数

---

## 五、后续

- 2.7-D:`job_event_listener` 实施 + 4 种 event 触发(onchain / invalidation / price / macro)+ `event_throttle` 表 + `events_calendar.triggered_at` 列 migration + 4 个新 run_trigger 枚举值
