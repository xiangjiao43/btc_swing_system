# Sprint F.1 — 删 event_onchain enqueue + pipeline_run 16:05 → 11:35 BJT

**日期**:2026-05-09 BJT
**类型**:Sprint F backlog 第 1 项,用户决策立刻做(不等观察期)
**Commit**:`5a495ea`

## 背景

Sprint A→E 完整收官后,docs/cc_reports/ai_frequency_audit.md 暴露了:
- 7 天 68 runs(平均 9.7 run/天),token 高峰日 1.1M / 天
- 主要触发入口是 `event_onchain`(`collect_onchain` 末尾的
  `_enqueue_pipeline_run("event_onchain")`),Sprint B/C 修后理论上只在
  Glassnode 真 success 时触发,但配额墙偶尔放行的"间断 success" 仍频繁
  触发 master pipeline

用户决策:**严守一天 1 次 master 原则**,因为:
1. 中长线策略每日 1 次评估足够
2. Sprint E 邵底机制(event_price ±3%/±5% / event_macro / hard_invalidation
   1h 规则平仓)足以应对突发
3. token 成本敏感

加上:
- BJT 16:05 用户太晚看不到
- 改 11:35 BJT(等 Glassnode 10:35 终档 + 1h 缓冲),用户上午能看到当日 master 输出

## 改动清单

| 路径 | 行 | 类型 | 说明 |
|---|---|---|---|
| `src/scheduler/jobs.py` | -2 / +13 | 修改 | 删 `_enqueue_pipeline_run("event_onchain")` 整行,events_triggered 永远 []。加诊断字段 glassnode_fetch_success |
| `config/scheduler.yaml` | -2 / +7 | 修改 | pipeline_run_regular cron 16:05 → 11:35 BJT(注释说明) |
| `tests/test_event_onchain_chain.py` | 全文重写 | 修改 | 原"成功 → enqueue"反向成"成功也不 enqueue"反退化 |
| `tests/test_jobs_fetch_attempts_integration.py` | -3 / +6 | 修改 | `test_collect_onchain_real_success_does_NOT_enqueue_pipeline_run`(改名 + 反向断言)|
| `tests/test_scheduler_2_7_a_cron.py` | -3 / +4 | 修改 | `test_pipeline_run_regular_cron_at_1135_bjt`(改名 + 改 hour 11) |

合计 +51 / -53 行(净 -2,因为重写部分文件)。

## 关键 diff

### `src/scheduler/jobs.py`

```diff
-        # Sprint B fix:只有 Glassnode bucket 真 success(无 exc + 入库 > 0)才
-        # enqueue pipeline_run。
-        gn_success = (gn_first_exc is None) and (glassnode_rows > 0)
-        if gn_success:
-            _enqueue_pipeline_run("event_onchain")
+        # Sprint F.1(2026-05-09)用户决策:删 event_onchain enqueue。
+        # 中长线策略每天只跑 1 次 master,collect_onchain 完成后不再 enqueue
+        # 额外 pipeline_run。邵底机制仍在:event_price 持仓 ±3% / event_macro
+        # / hard_invalidation_monitor 1h 规则平仓。
+        gn_success = (gn_first_exc is None) and (glassnode_rows > 0)
+        # NOTE:不再调 _enqueue_pipeline_run("event_onchain")。
         return {
             "by_collector": {
                 "glassnode": glassnode_rows,
                 "derived_mvrv": sum(derived_stats.values()),
             },
             "total_upserted": total,
-            "events_triggered": ["event_onchain"] if gn_success else [],
+            "events_triggered": [],
             "errors": errors,
+            "glassnode_fetch_success": gn_success,
         }
```

### `config/scheduler.yaml`

```diff
   pipeline_run_regular:
     enabled: true
-    cron: {hour: 16, minute: 5}        # 16:05 BJT(= UTC 08:05),每日 1 档
+    # Sprint F.1(2026-05-09):16:05 BJT → 11:35 BJT(= UTC 03:35)。
+    # 用户中长线一天 1 次,16:05 太晚看不到。新时刻 11:35 在 Glassnode
+    # 10:35 终档 + 1h 缓冲后,严守"一天 1 次 master"原则。
+    cron: {hour: 11, minute: 35}
     misfire_grace_time: 300
     coalesce: true
     max_instances: 1
-    description: 'Pipeline 主循环(16:05 BJT 每日 1 档,run_trigger=scheduled);Sprint 1.9-B 启用'
+    description: 'Pipeline 主循环(11:35 BJT 每日 1 档,run_trigger=scheduled;Sprint F.1 从 16:05 改 11:35)'
```

## AI 入口完整核实(段 3 同类风险扫描的核心)

`grep -rn '_enqueue_pipeline_run\|run_full_a\|EmergencySimplifiedA' src/`
全量结果(去掉文档/注释):

| 路径:行 | 触发条件 | 频率 | AI? |
|---|---|---|---|
| `src/pipeline/state_builder.py:375` `AIOrchestrator().run_full_a(context)` | 由 pipeline_run_regular cron 调 | 1 次/天 BJT 11:35 | ✅ master pipeline |
| `src/scheduler/jobs.py:902` `_enqueue_pipeline_run(evt)` 在 `job_event_listener` | event_listener 60s 扫到 event_price/event_macro 时 | 0+ 次/天(取决于市场)| ✅ 间接 master |
| `src/scheduler/jobs.py:1042` `_enqueue_pipeline_run(...)` 在 `job_pipeline_run_with_retry` | master 失败 retry 自调 | 失败时 | ✅(retry)|
| `src/scheduler/jobs.py:1224` `EmergencySimplifiedA()` 在 `position_health_check` body | **disabled (Sprint E Step 0)** | 0 | ❌ |
| `src/ai/orchestrator.py:392` `EmergencySimplifiedA(...)` 在 `run_event_a` | event_listener event_price 触发时调 | 触发时 | ✅ 单 AI |
| `weekly_review` cron | 周日 22:00 BJT | 1 次/周 | ✅ 单 AI |

**Sprint F.1 后 AI 调用频率上限**(假设市场平静):
- 1 次/天 master(BJT 11:35)
- 0-2 次/月 event_price(开仓后 ±3% / 空仓 ±5% 触发)
- 0-3 次/月 event_macro(events_calendar 命中)
- 1 次/周 weekly_review

7 天预期:7-10 runs(对比 Sprint F.1 之前的 7 天 68 runs,**降幅 ~85%**)。

**邵底完整性确认**:
- ✅ 持仓时价格异动:event_price 触发 EmergencySimplifiedA
- ✅ 宏观事件:event_macro 触发 master pipeline
- ✅ 硬失效位击穿:hard_invalidation_monitor 1h cron 规则平仓(无 AI 也安全)
- ✅ 周复盘:weekly_review 周日 22:00

**没有遗漏的隐性 AI 入口**:
- `event_onchain` 已删 ✅
- `position_health_check` 已 disabled ✅
- `event_invalidation` 已早 sprint(1.10-G)拆到 hard_invalidation_monitor(规则平仓)✅
- `pipeline_run_8h_onchain` enabled=false 已停 ✅

## 验收记录

### 本地 pytest

`1662 passed, 1 skipped, 0 failed`(从 Sprint E 后 1664 → -2 是
test_event_onchain_chain.py 重写整合了原 2 个测试为 2 个新测的语义反转,
没改净数;但有 1 个测被合并删除 → 实际 -2)。

### 服务器部署

- Fast-forward `4bfd8e8..5a495ea`
- systemd `is-active = active`(restart 完成)
- `cat config/scheduler.yaml | grep -A 8 'pipeline_run_regular'` 确认 11:35
  BJT 已生效

### 服务器 pytest(强制项)

(后台跑中,完成后会贴具体行数)

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1662 passed, 0 failed |
| GitHub push(commit hash:5a495ea) | ✅ 已 push origin/main |
| 服务器 git pull | ✅ Fast-forward 成功 |
| 服务器 systemctl restart | ✅ is-active = active |
| 服务器 pytest 全 suite | ⏳ 后台跑中(预期 ~140s,与本地一致) |

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `_enqueue_pipeline_run("event_onchain")` 整行 | src/scheduler/jobs.py:867(原) | 用户决策严守一天 1 次原则,event_onchain 是 9.7 run/天的根因 |
| `events_triggered: ["event_onchain"]` 条件分支 | src/scheduler/jobs.py:874(原) | enqueue 删后该字段永远 [](保留 key 供下游兼容)|
| `cron: {hour: 16, minute: 5}` | config/scheduler.yaml:119(原) | 用户决策改 BJT 11:35,16:05 太晚 |
| `test_collect_onchain_success_enqueues_pipeline_run` | tests/test_event_onchain_chain.py | 旧"成功 → enqueue"语义反转,改名为 `_does_not_enqueue_anymore` |
| `test_pipeline_run_regular_cron_at_1605_bjt` | tests/test_scheduler_2_7_a_cron.py | 16:05 已改,改名为 `_at_1135_bjt` |

`git grep '_enqueue_pipeline_run("event_onchain")\|hour: 16, minute: 5'`
在 src/ + tests/ 中应该 0 命中(只剩注释 + 本报告引用)。

## 段 3 风险提示

1. **明天 BJT 11:35 的最终验证**:用户验证脚本里跑 1 次 SQL 查 strategy_runs
   是否准点出现 1 行(scheduled trigger),确认 cron 改动生效。
   ```
   ssh ubuntu@124.222.89.86 "sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \"
   SELECT generated_at_bjt, run_trigger
   FROM strategy_runs
   WHERE date(generated_at_bjt, 'localtime') = '2026-05-10'
   ORDER BY generated_at_bjt;\""
   ```
   预期:1 行 trigger=scheduled,时间 ≈ 11:35 BJT。
2. **`events_triggered: []` 永久空 list 对下游兼容**:`grep events_triggered
   src/`:仅 `kpi/collector.py:226` 注释 + `scheduler/jobs.py` 自己写入,
   下游无 hard 依赖。安全。
3. **诊断字段 `glassnode_fetch_success`**:新加,便于以后排查 fetch 真实
   状态(events_triggered 不再可靠表达"fetch 是否成功")。
4. **如果某日 11:35 master 失败**:`job_pipeline_run_with_retry` 仍会 retry
   一次(自动 backoff),不需要等到次日 11:35。
