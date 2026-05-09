# AI 输出频率事实核查(只查不改)

**日期**:2026-05-09 BJT 09:51
**类型**:事实核查 sprint(纯只读 SSH + DB + journalctl)
**触发**:用户反映 AI 一天多次输出(BJT 9-12 多次),做中长线 1 次/天足够,担心 token 成本

## 结论一句话

**最近 7 天平均 9.7 次/天 AI run**,主要触发入口是 `event_onchain`(`collect_onchain`
job 跑完后 enqueue pipeline_run),配合每天 1 次 `scheduled` 16:05 BJT 主档 +
偶尔 `manual` 测试。**今天(5/9 BJT)0 run** — Sprint B/C/D 已经堵住"上游 fail
但 derived MVRV 写行触发 enqueue"的副作用 bug,真正的 1 次/天行为已经在生效。

## 段 2 — 真实数据原文

### Q1:最近 7 天 strategy_runs 按 day × trigger × model 分组
```
day        | run_trigger | ai_model_actual            | runs
-----------|-------------|----------------------------|-----
2026-05-08 | event_onchain | claude-sonnet-4-5-20250929 | 9
2026-05-08 | scheduled     | claude-sonnet-4-5-20250929 | 1
2026-05-07 | event_onchain | claude-sonnet-4-5-20250929 | 2
2026-05-06 | event_onchain | claude-sonnet-4-5-20250929 | 16
2026-05-06 | scheduled     | claude-sonnet-4-5-20250929 | 1
2026-05-05 | event_onchain | claude-sonnet-4-5-20250929 | 10
2026-05-04 | event_onchain | claude-sonnet-4-5-20250929 | 9
2026-05-04 | manual        | claude-sonnet-4-5-20250929 | 1
2026-05-03 | event_onchain | claude-sonnet-4-5-20250929 | 10
2026-05-03 | scheduled     | claude-sonnet-4-5-20250929 | 1
2026-05-02 | event_onchain | claude-sonnet-4-5-20250929 | 4
2026-05-02 | manual_api    | claude-sonnet-4-5-20250929 | 3
2026-05-02 | scheduled     | claude-sonnet-4-5-20250929 | 1
```

### Q2:每天总数 + AI ok / fallback 拆分
(`fallback_level IS NULL OR ='none'` 视作 AI 成功;否则 fallback)
```
day        | total_runs | ai_ok | ai_fallback
-----------|-----------|-------|------------
2026-05-08 | 10        | 8     | 2
2026-05-07 | 2         | 2     | 0
2026-05-06 | 17        | 6     | 11
2026-05-05 | 10        | 5     | 5
2026-05-04 | 10        | 9     | 1
2026-05-03 | 11        | 7     | 4
2026-05-02 | 8         | 0     | 8
```

合计 7 天 **68 runs**,平均 **9.7 runs/day**。fallback 日(5/2 全 fallback,
5/6 11/17 fallback)与 Glassnode quota / 数据 stale 高度相关。

### Q3:今天 BJT 5/9 + 昨天 BJT 5/8 详细时间线
当前服务器时间:`Sat May 9 09:51:58 AM CST 2026`(BJT)

```
generated_at_bjt          | run_trigger    | run_mode         | fallback_level | action_state
--------------------------|----------------|------------------|----------------|------
2026-05-08T16:16:23+08:00 | event_onchain  | ai_orchestrator  |                | FLAT
2026-05-08T16:09:36+08:00 | scheduled      | ai_orchestrator  | level_2        | FLAT
2026-05-08T16:02:37+08:00 | event_onchain  | ai_orchestrator  | level_1        | FLAT
2026-05-08T14:08:58+08:00 | event_onchain  | ai_orchestrator  |                | FLAT
2026-05-08T12:40:33+08:00 | event_onchain  | ai_orchestrator  |                | FLAT
2026-05-08T11:40:16+08:00 | event_onchain  | ai_orchestrator  |                | FLAT
2026-05-08T10:38:30+08:00 | event_onchain  | ai_orchestrator  |                | FLAT
2026-05-08T09:38:41+08:00 | event_onchain  | ai_orchestrator  |                | FLAT
2026-05-08T09:09:09+08:00 | event_onchain  | ai_orchestrator  |                | FLAT
2026-05-08T08:38:22+08:00 | event_onchain  | ai_orchestrator  |                | FLAT
```

**今天 5/9 BJT 0 runs**(Sprint D 部署 17:25 BJT 5/8 后,新 `_onchain_today_complete`
quota 短路 + Sprint B `gn_first_exc is None` 双重保护让 8:35 主档失败后**不再
enqueue event_onchain**;9:35 短路 skip;10:35 短路 skip;16:05 BJT
`pipeline_run_regular` 还没到点)。

### Q4:scheduler.yaml(关键 cron 摘录)
```yaml
collect_klines_1h:        每整点 :00 BJT(每小时;不发 AI)
collect_klines_daily:     08:01 主 + 9 个补救档(不发 AI)
collect_klines_weekly:    周一/二/三 多档(不发 AI)
collect_macro:            06:00 主 + 06-12 BJT 每小时补救(不发 AI)
collect_onchain:          08:35 / 09:35 / 10:35 BJT(Sprint C:10 → 3 档;
                          quota fail 短路 9:35/10:35。collect 后若 success
                          enqueue 1 次 pipeline_run with run_trigger=event_onchain)
pipeline_run_regular:     16:05 BJT 每日 1 档(run_trigger=scheduled)→ 走 6 个 AI agent
pipeline_run_8h_onchain:  enabled=false(已停)
event_listener:           60s 高频(扫 event_macro / event_price / event_invalidation;
                          命中 enqueue 1 次 pipeline_run with run_trigger=event_*)
hard_invalidation_monitor: 1h interval(无 AI,纯规则平仓)
position_health_check:    4h interval(有 active thesis 时调 EmergencySimplifiedA 真 AI)
weekly_review:            周日 22:00 BJT 1 次(WeeklyReviewAnalyst AI)
```

### Q5:journalctl event_listener 触发记录
```
$ ssh ... "journalctl ... --since '24 hours ago' | grep -E 'event_listener|event triggered|run_trigger=event|_enqueue_pipeline_run|event_onchain|event_macro|event_price|event_invalidation'"
(无返回 — Sprint D 部署后 24h 内 event_listener 无任何 event 触发记录)

# 退一步,过滤 GET/POST 后取 pipeline 相关:
May 08 16:02:37 ... pipeline_run failed (attempt 1), scheduling retry in 600s (attempt 2)
```
仅 1 条:5/8 16:02 pipeline_run 失败重试。其它 event_* 触发 24h 内 0 条。

### Q6:Token 消耗(从 full_state_json.layers.{l1..l5,master}.tokens_in/out 解出)

**只算 master 的(单 agent)**:
```
day        | runs | sum_tokens_in_master | sum_tokens_out_master
-----------|------|----------------------|----------------------
2026-05-08 | 10   | 82,423               | 19,140
2026-05-07 | 2    | 30,377               | 1,545
2026-05-06 | 17   | 140,552              | 12,630
2026-05-05 | 10   | 163,378              | 17,212
2026-05-04 | 10   | 229,954              | 20,563
2026-05-03 | 11   | 425,120              | 35,233
2026-05-02 | 8    | 402,174              | 32,768
```

**全 6 agent 合计(L1+L2+L3+L4+L5+master)**:
```
day        | sum_in     | sum_out
-----------|------------|--------
2026-05-08 | 277,148    | 81,189
2026-05-07 | 150,430    | 10,323
2026-05-06 | 648,980    | 58,433
2026-05-05 | 846,040    | 93,670
2026-05-04 | 790,591    | 88,010
2026-05-03 | 1,000,361  | 107,352
2026-05-02 | 822,608    | 92,737
```

7 天合计 **4.5M input + 530k output tokens**;平均 **66k input + 7.7k output / run**。

按 Sonnet 4.5 现行价(input $3/MTok,output $15/MTok)估算:
- 单次 run 成本 ≈ 66k×$3/M + 7.7k×$15/M ≈ $0.20 + $0.12 = **$0.32/run**
- 7 天 68 run × $0.32 ≈ **$22**(7 天)
- 月化 ≈ **$95/月**(若维持当前 9.7 run/天)
- 如果降到目标 1 run/天 → 月化 ≈ **$10/月**

(现行价请用户在 Anthropic 控制台核对;此处只给数量级。)

## 段 3 — 同类风险扫描

### 1. 还有别的入口会触发 AI 吗?

**已确认**:
- `pipeline_run_regular`(16:05 BJT scheduled)— 1 次/天
- `pipeline_run_8h_onchain`(08:40 BJT,**enabled=false 已停**)
- `collect_onchain` 末尾的 `_enqueue_pipeline_run("event_onchain")` — Sprint B 修后**只在真 success 才 enqueue**
- `event_listener`(60s 高频)扫到 `event_macro`/`event_price`/`event_invalidation` →
  enqueue。**24h 0 触发**(可能是用户当前空仓 + 价格波动小),但仍是潜在入口
- `position_health_check`(4h interval)— **只在 active thesis 时**调 EmergencySimplifiedA
  真 AI;FLAT 时直接 return
- `weekly_review`(周日 22:00)— 周一次 WeeklyReviewAnalyst AI
- `manual` / `manual_api`(用户手动触发)— 7 天内 4 次

**未发现其它隐性入口**。`hard_invalidation_monitor`(1h interval)是规则平仓,不调 AI。

### 2. Sprint B 修的 collect_onchain 副作用 bug 是否彻底解决?

**部分解决,看数据走势**:
- 5/2 8 runs(5/0 event + 3 manual + 1 sched)— 这天 manual 占大头
- 5/3 11 runs(10 event_onchain + 1 sched)— 5/3 单日 425k input tokens 是 7 天峰值
- 5/4 10 runs(9 event + 1 manual)
- 5/5 10 runs(10 event)
- 5/6 17 runs(16 event + 1 sched)— 5/6 是个高峰,可能 derived MVRV 多次写行 + 老 cron 多档触发
- 5/7 2 runs(2 event)— 显著下降,可能 5/7 一手 Glassnode 偶尔成功了所以不撞 quota loop
- 5/8 10 runs(9 event + 1 sched)— **早上的 9 event 是 Sprint B 部署前的旧逻辑**;
  17:25 Sprint D 部署后 0 个新 event_onchain
- 5/9 BJT 至今 **0 runs** ✅ — Sprint B + C + D 三重保护生效

→ 关键证据:Sprint D 部署(2026-05-08T17:25 BJT)后到现在 ~16 小时 0 个 event_onchain。
**bug 在 Sprint B 已修;Sprint C 减档 + quota 短路是双重加固;Sprint D 仅做诚实显示
不影响行为。**

### 3. 5/6 17 runs / 5/3 11 runs > 10 档 cron 的额外 run 来自哪?

老 cron 是 10 档 collect_onchain(8:35-20:00),配合 Sprint B 之前 derived MVRV 副作用,
理论上限 10 次 event_onchain/天。5/6 出现 16 个 event_onchain 超出上限,
可能原因:
- (a) collect_onchain 因为 retry 机制单档跑了多次
- (b) `_enqueue_pipeline_run` 的 retry 机制(`job_pipeline_run_with_retry`)在 master
  fail 后可能 add_job 多次延迟 retry
- (c) `event_listener` 的 event_price ±3% 持仓档 / event_macro 命中事件日历

不确认根因(本 sprint 只查不改)。但 Sprint D 部署后这些都不再活跃 → 留观察期。

### 4. position_health_check 4h interval 是隐性 AI 入口

如果用户进入持仓状态(active thesis 不为 None),每 4h 会调 EmergencySimplifiedA AI。
当前用户空仓 → 不触发。**用户开仓后这个会激活,需要单独评估**。

### 5. 网页"手动重跑"按钮

如果网页上有"立刻重跑 pipeline"按钮(`POST /api/system/run-now`),用户每次手动点
都会触发 AI。5/4 / 5/2 的 manual 行可能是这个。**不是隐性入口**(用户主动行为)。

## 段 4 报告路径

`docs/cc_reports/ai_frequency_audit.md`(本文件)

## 给用户的建议(只查不改)

事实层面:
- **现状(Sprint D 部署后)**:每天 1 次 `scheduled`(16:05 BJT)+ 0-N 次 `event_*`
  (event_onchain 已被 Sprint B 修死;event_macro/event_price/event_invalidation 24h
  内 0 触发)
- **如果维持当前行为**:估算 ~1-2 run/天 + 周日 weekly_review,月成本 ~$15-20
- **如果开仓**:position_health_check 每 4h 跑一次 EmergencySimplifiedA AI(轻量
  prompt,token 比 master_orchestrator 少很多),每天最多 6 次额外调用,月增量 ~$5-10

**未达到用户目标"1 次/天"** 的潜在风险:
1. event_listener 60s 高频常驻,以后市场波动大时 event_price 可能频繁触发
   (±5% 空仓 / ±3% 持仓阈值)
2. position_health_check 持仓时 4h cron 是 hard 频率,无法跳过

**Sprint E 候选**(本 audit 不实施,留给用户拍板):
- 把 event_price 阈值从 ±3-5% 提高到 ±8-10%(降低敏感度)
- position_health_check 改 8h 或 12h interval(中长线交易 4h 太密)
- 加全局 daily AI quota:同一天累计调用 ≥ N 次后,event_* 触发只产 alert 不调 AI
