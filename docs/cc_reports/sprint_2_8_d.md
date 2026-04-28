# Sprint 2.8-D — 修复 _start_scheduler 启动失败(scheduler 引用被丢)

**Date:** 2026-04-28
**Branch:** main
**Status:** ✅ 完成,9 个新测试 + 646/646 全量回归过

---

## 一、症状与根因

**症状**:4 天 `strategy_state_history` 只有 1 行(4-24 manual);journal 12h
内 grep "pipeline_run" 完全空;手动 `build_scheduler() + start() + sleep(1)` 后
`next_run_time` 全部正确。

**根因**:`src/api/app.py::_start_scheduler` 启动序列存在 race condition:

```python
scheduler.start()                        # ① BackgroundScheduler 异步起来
app.state.scheduler = scheduler          # ② 存引用
for job in scheduler.get_jobs():
    nxt = job.next_run_time              # ③ ← race:scheduler 起了但 job 还没
                                         #    完成 schedule,这里抛 AttributeError
```

外层 `try/except` 包了 ①②③,异常 → `logger.exception(...) ; app.state.scheduler = None`。
意味着虽然 ① 已经把 BackgroundScheduler 后台线程起来了,但 ②的引用被 ③ 的
异常清掉了 → 没有强引用 → APScheduler 后台线程没有"持有者" → job 永远不会触发。

---

## 二、改动

### 2.1 `src/api/app.py`

把 `_start_scheduler` 拆成两阶段:

**阶段 1**(`scheduler.start()`):失败才清 `app.state.scheduler = None`。
**阶段 2**(`_log_scheduler_jobs`):
- 引用立刻存进 `app.state.scheduler`
- 用 `threading.Timer(2.0, ...)` 延迟跑(给 dispatcher 时间)
- 单 job `AttributeError` 在 `_log_scheduler_jobs` 内被吞,只 log "registered (next_run_time pending)"
- **任何**这阶段的错误都不会清 scheduler 引用

抽出 module-level helper `_log_scheduler_jobs(scheduler)`,便于测试直接调用模拟 race。

### 2.2 `src/api/models.py` + `src/api/routes/system.py`

`HealthResponse` 加两个字段:
- `scheduler_running: bool`
- `scheduler_jobs_count: int`

`_scheduler_status(request)` helper:从 `app.state.scheduler` 读取
`running` + `len(get_jobs())`,任何异常退化为 `(False, 0)`。

### 2.3 `tests/test_scheduler_startup_resilience.py`(新)

9 个测试:
- 3 个 helper 直测(`_log_scheduler_jobs` 吞 AttributeError / log BJT / log no-NRT)
- 3 个 `_start_scheduler` 行为(race 不丢引用 / start 失败清引用 / disabled 不起)
- 3 个 `/api/system/health` 字段(running=True / disabled / start_failed 三档)

---

## 三、测试

| 测试 | 验证 |
|---|---|
| `test_log_scheduler_jobs_swallows_attributeerror` | 2 个 fake job 都抛 AttributeError → 函数不传播,只 log "pending" |
| `test_log_scheduler_jobs_logs_bjt_when_set` | next_run_time = 12:05 UTC → log "20:05 BJT" |
| `test_log_scheduler_jobs_logs_no_next_run_time` | next_run_time = None → log "registered (no next_run_time)" |
| **`test_start_scheduler_preserves_ref_when_race_in_log`** | **关键反退化**:同步触发 race,断言 `app.state.scheduler is fake_scheduler` |
| `test_start_scheduler_clears_ref_on_real_start_failure` | `build_scheduler` 抛错 → `app.state.scheduler is None` |
| `test_start_scheduler_disabled_via_env` | SCHEDULER_ENABLED=false → 不起,引用为 None |
| `test_health_reports_scheduler_running_true` | 8 jobs 注册 → JSON 含 `scheduler_running=true, scheduler_jobs_count=8` |
| `test_health_reports_scheduler_off_when_disabled` | env disabled → JSON `scheduler_running=false, jobs_count=0` |
| `test_health_reports_scheduler_off_when_start_failed` | start raises → JSON `scheduler_running=false, jobs_count=0` |

**回归**:全量 `pytest tests/` = **646 passed, 1 skipped, 4.54s**(637 + 9 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 8

# 1. journal 应该有 8 个 [Scheduler] job 注册日志(2s 后 timer 跑出来)
journalctl -u btc-strategy.service --since "1 minute ago" | grep "\[Scheduler\]"
# 预期:
#   [Scheduler] started; 8 jobs registered
#   [Scheduler] job=pipeline_run next run at 2026-04-29 00:05 BJT
#   [Scheduler] job=collector_klines_1h next run at 2026-04-28 21:00 BJT
#   ... (8 行 next run / 或 "registered (next_run_time pending)")

# 2. /api/system/health 字段
curl -s -u admin:Y_RhcxeApFa0H- http://127.0.0.1:8000/api/system/health | \
  python3 -c "
import json, sys
d = json.load(sys.stdin)
print('scheduler_running:', d.get('scheduler_running'))
print('scheduler_jobs_count:', d.get('scheduler_jobs_count'))
"
# 预期:scheduler_running: True / scheduler_jobs_count: 8

# 3. 等 20:05 BJT 整点 cron 跑(或下个最近 pipeline_run 整点)
sleep $(( $(date -d "next 20:05 BJT" +%s) - $(date +%s) ))
sqlite3 data/btc_strategy.db <<EOF
SELECT run_trigger, generated_at_bjt FROM strategy_runs
ORDER BY generated_at_utc DESC LIMIT 3;
EOF
# 预期:最新行 run_trigger='scheduled'
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除)
- 抽出 `_log_scheduler_jobs` helper,删除原 inline `for job in scheduler.get_jobs():`
  循环 — 没留旧路径
- 没新加全局变量绕 race(用 FastAPI `app.state` 已有的命名空间)

### §Y
本 commit 立即 push。

### §Z 端到端断言
- `test_start_scheduler_preserves_ref_when_race_in_log` 显式 mock 出 race
  场景(`_FakeJobAttrErr` 的 `next_run_time` property 真抛 AttributeError),
  断言 `app.state.scheduler is fake_scheduler` — 这是反 4 天 0 触发症状的核心 guard
- `_ImmediateTimer` patch 让 `threading.Timer` 同步运行,使断言不需要等 2s
- /api/system/health 走真 TestClient + 真 startup event,断言 JSON 字段值

### 同类风险扫描
1. **`threading.Timer` 在测试中长留** — `_start_scheduler` 用真 Timer(2s);
   测试用 `_ImmediateTimer` patch 同步执行,test 退出时无后台线程残留
2. **Timer 跑时 app 可能已 shutdown** — 此时 `_log_scheduler_jobs` 仍能跑
   (持有 scheduler 闭包),只是 scheduler.get_jobs() 可能返回空。已在 helper
   外层 try/except `Exception` 包住,不会抛
3. **scheduler_jobs_count 在 race 期间可能是 0** — 因 Timer 还没跑;但
   `len(scheduler.get_jobs())` 是同步 API,start 后立即可读真实数。`/health`
   反映瞬时状态,值随 race 演进而变,这是预期
4. **APScheduler `running` 字段 API 一致性** — `BackgroundScheduler.running`
   在 3.x 版本一直存在;仍用 `getattr(..., "running", False)` 兜底
5. **不影响 `run_scheduler.py`(独立进程模式)** — 该脚本走 BlockingScheduler,
   没有 `next_run_time` 逻辑,不受本 sprint 改动

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/api/app.py` | 抽 `_log_scheduler_jobs` helper;`_start_scheduler` 分两阶段,scheduler 引用先存再 deferred log |
| `src/api/models.py` | `HealthResponse` 加 `scheduler_running` + `scheduler_jobs_count` |
| `src/api/routes/system.py` | `_scheduler_status(request)` + `_health_impl` 注入 |
| `tests/test_scheduler_startup_resilience.py` | 新文件,9 测试 |

---

## 七、部署 checklist

- [ ] git pull
- [ ] `sudo systemctl restart btc-strategy.service`
- [ ] 等 8 秒,journal 看 8 个 [Scheduler] 日志
- [ ] curl /api/system/health 看 scheduler_running / scheduler_jobs_count
- [ ] 等下个 pipeline_run 整点(00/04/08/12/16/20:05 BJT),
      sqlite 查最新 strategy_runs.run_trigger='scheduled'
