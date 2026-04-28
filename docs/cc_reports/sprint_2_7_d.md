# Sprint 2.7-D — event 触发(4 种)

**Date:** 2026-04-28
**Branch:** main
**Status:** ✅ 完成,24 个新测试全过 + 88 个 scheduler/events 范畴回归通过

---

## 一、改动总览

### 1.1 新建表 + 列(SQLite)
- `event_throttle(event_type PK, last_triggered_at_utc)` — invalidation/price 2h 冷却
- `events_calendar.triggered_at_utc TEXT` — macro 类 event 防重(每个 calendar 行天然只触发 1 次)

### 1.2 新建文件
- `migrations/006_add_event_throttle.sql` — 全新 DB 用
- `scripts/migrate_2_7_d.py` — 幂等 runner(检查 PRAGMA table_info 防重跑 ALTER)
- `src/scheduler/event_listener.py` — 核心模块,154 行,3 个内部 check_* + 1 公开 `check_and_trigger_events`
- `tests/test_event_listener.py` — 20 测试,§Z 真 SQLite + 真插数据 + 断言 throttle 表 / triggered_at_utc 列写入
- `tests/test_event_onchain_chain.py` — 4 测试,§Z 真 OnchainDAO + mock _enqueue 断言 enqueue_calls
- `docs/cc_reports/sprint_2_7_d.md` — 本报告

### 1.3 改动文件
- `src/data/storage/schema.sql`:`events_calendar` 加 `triggered_at_utc`,新建 `event_throttle` 表
- `config/schemas.yaml`:`run_trigger` 枚举加 `scheduled_8h_onchain`(Sprint 2.7-C 漏加)
- `src/scheduler/jobs.py`:
  - `job_event_listener` stub → 真实实施(调 check_and_trigger_events + 对每个返回值 _enqueue_pipeline_run)
  - `job_collect_onchain` 成功(total > 0)→ enqueue 一次 `pipeline_run(run_trigger='event_onchain')`,返回 dict 加 `events_triggered` 字段
  - 新增 `_active_scheduler` 模块全局 + `set_active_scheduler` setter + `_enqueue_pipeline_run(run_trigger, delay_sec=10)` 助手
- `src/scheduler/main.py::build_scheduler` 末尾调 `set_active_scheduler(scheduler)` — 让 event_listener / collect_onchain 拿到 scheduler 引用动态 add_job

---

## 二、4 种 event 实施细节

### event_invalidation(event_listener.py:_check_event_invalidation)
1. event_throttle 2h 内已触发 → 跳过
2. 读 strategy_runs 最新一行 lifecycle.direction(long/short) + L4.hard_invalidation_levels[0] 数值
3. 读 price_candles 最新 1h close
4. long + close < level 或 short + close > level → 触发 + `_record_trigger`
5. 任一字段缺失 → silent skip

### event_price(event_listener.py:_check_event_price)
1. event_throttle 2h 内已触发 → 跳过
2. 距上次 `run_trigger LIKE 'scheduled%'` 的 strategy_run < 30 min → 跳过
3. 取最新 1h close + 该 ts - 24h 的最近 1h close
4. abs(pct_change) ≥ 3% → 触发 + `_record_trigger`

### event_macro(event_listener.py:_check_event_macro)
1. SQL 一条:
   ```sql
   SELECT * FROM events_calendar
   WHERE utc_trigger_time IS NOT NULL
     AND triggered_at_utc IS NULL
     AND impact_level >= 2
     AND utc_trigger_time > now-16min
     AND utc_trigger_time <= now-15min
   ```
2. 命中 → UPDATE triggered_at_utc=now + 返回 True(不走 event_throttle,行级防重)

### event_onchain(jobs.py:job_collect_onchain 末尾)
- 不在 event_listener 里。`job_collect_onchain` 成功后(total > 0)直接 `_enqueue_pipeline_run("event_onchain")` —— 每天 08:35 只跑一次,天然唯一,无需冷却

---

## 三、用户验证脚本

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull

# 1. 跑迁移(幂等可重跑)
.venv/bin/python scripts/migrate_2_7_d.py
# 预期输出:event_throttle_table: ok
#          triggered_at_utc_column: added(首次)或 skipped (已存在)

# 2. 重启服务
sudo systemctl restart btc-strategy.service
sleep 5
journalctl -u btc-strategy.service -n 50 | grep -E "event|next run"

# 3. 验证 schema(应有 event_throttle 表 + events_calendar.triggered_at_utc 列)
sqlite3 data/btc_strategy.db ".schema event_throttle"
sqlite3 data/btc_strategy.db "PRAGMA table_info(events_calendar)" | grep triggered_at

# 4. 等下个 60s event_listener tick → 看 logs
journalctl -u btc-strategy.service -n 100 | grep -E "event_listener|event_invalidation|event_price|event_macro"

# 5. 手工模拟 event_macro 触发(需先关停服务避免 race;或在 prod 直接观察自然命中)
# 假设当前 BJT 14:30,塞一个 utc_trigger 14:14 BJT(= now-16min UTC)的事件
sqlite3 data/btc_strategy.db <<EOF
INSERT OR REPLACE INTO events_calendar
  (event_id, date, timezone, local_time, utc_trigger_time,
   event_type, event_name, impact_level, notes)
VALUES (
  'test_macro_2_7_d',
  date('now'),
  'UTC', '00:00',
  datetime('now', '-15 minutes', '-30 seconds'),
  'cpi', 'Test event for 2.7-D', 4, 'manual seed for verification'
);
EOF
# 等 1 分钟后:
sqlite3 data/btc_strategy.db \
  "SELECT event_id, triggered_at_utc FROM events_calendar WHERE event_id='test_macro_2_7_d'"
# 预期 triggered_at_utc 已被写入(非 NULL)

# 6. 验证 strategy_runs 出现 run_trigger='event_macro' 的行
sqlite3 data/btc_strategy.db \
  "SELECT run_id, run_trigger, generated_at_utc FROM strategy_runs ORDER BY id DESC LIMIT 5"
SSH
```

---

## 四、§X / §Y / §Z + 同类风险扫描

### §X 删除清单
- `job_event_listener` stub("stub_pre_2_7_d, no-op")整个函数体替换为真实实施 — **没保留 stub 注释或 disabled 路径**
- `_active_scheduler` 模块全局是新加,无对应"老路径"待删
- 老的 `events_upcoming_48h` 在 emitter 仍用,但 event_listener 用不限时间窗的 `events_calendar` 直查 — 两者职责分离,**无重复路径**

### §Y
每个 commit 立即 push;本 sprint 1 个 commit。

### §Z 端到端断言
- test_event_listener.py:每个 event 路径用真 SQLite + 真插入 strategy_runs/price_candles/events_calendar 行,断言 (a) 返回值精确含 `event_X`,(b) `event_throttle` 表插入 / `events_calendar.triggered_at_utc` 写入,(c) 节流场景返回空 list
- test_event_onchain_chain.py:真 Glassnode mock + 真 DB upsert + mock _enqueue → 断言 `events_triggered=['event_onchain']` 且 enqueue_calls 精确

### 同类风险扫描

1. **`_active_scheduler` 全局可能被多次 set**(例如测试反复 build)
   - 已加 `set_active_scheduler` 函数,测试可手动 reset 为 None
   - 风险:并发 build_scheduler 时最后一次 wins。生产端单实例,不影响

2. **event_listener 60s tick 与 collect_onchain 同时跑**
   - APScheduler `max_instances=1` 默认控制单 job;但跨 job 不互斥
   - 假如 collect_onchain (08:35) 还在跑(典型 30s),event_listener 60s tick 期间不会收到 onchain 数据(还没 commit),所以 event_invalidation/price 用的是上一轮快照
   - 不会导致错误 enqueue,只是该轮 tick 看不到最新数据

3. **event_macro 窗口边界**
   - 窗口 `[now - 16min, now - 15min)`,event_listener 60s tick 内必至少一次落入
   - 若 scheduler 因负载或时钟漂移延迟 > 60s → 该事件可能被跳过
   - 缓解:user spec 已设计 misfire_grace_time + coalesce,且 macro 是 15min 之后才触发,有缓冲

4. **enqueue 的 pipeline_run 与 cron pipeline_run 撞车**
   - id=`event_pipeline_<run_trigger>_<timestamp>`,replace_existing=True
   - cron pipeline_run id=`pipeline_run_regular` 等,id 不同,不冲突
   - 若同一秒 enqueue 多次同种 event(理论不会发生 —— 节流挡住),id 含 timestamp 防重

5. **运行中 check_and_trigger_events 抛异常**
   - 包了 try/except 逐 event,任一失败不阻塞其他
   - logger.warning 记录,scheduler 不 crash

---

## 五、统计

- 24 个新测试(20 event_listener + 4 onchain chain)全过
- 88 个 scheduler/events 范畴回归通过(含 2.7-A/B/C 既有测试)
- 1 个 commit:`feat(scheduler): 2.7-D — 4 event types + listener + migration`
