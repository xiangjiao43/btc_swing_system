# Sprint 2.8-F — 低频 collector 失败自动重试(多档 cron + 入口 skip)

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,16 个新测试 + 5 个 2.7-A 测试更新 + 681/681 全量回归过

---

## 一、问题与决策

**真实事故(4-29)**:API key 临时失效正好覆盖单 cron 时刻 → 链上 + 宏观全天空,
直到手动补抓。周线更糟:周一失败 → 等下周一。

**用户决策**:低频数据失败必须自动重试到当天拿到,不能等下一周期。
1h 高频不需要(下个整点天然就是重试)。

**实施方案**:
1. `scheduler.yaml`:4 个低频 job 改多档 cron(主时刻 + 多个补救档)
2. `main.py::_build_trigger`:cron list → `OrTrigger([CronTrigger×N])`,单 job_id
3. `jobs.py`:每个低频 job 入口检查"今天/本周已有数据" → status='skipped',
   不浪费 API quota

---

## 二、改动

### 2.1 `config/scheduler.yaml`

4 个低频 job 的 `cron: {dict}` 改为 `cron: [list of dict]`:

| job | 主时刻(BJT) | 补救档数 | 总档数 |
|---|---|---|---|
| collect_macro | 06:00 | 6 (07:00-12:00 每小时) | 7 |
| collect_onchain | 08:35 | 9 (09:05-12:35 + 14/16/18/20:00) | 10 |
| collect_klines_daily | 08:01 | 8 (09-20:01 每小时/2小时) | 9 |
| collect_klines_weekly | 周一 08:01 | 6 (周一/二/三 多档) | 7 |

`collect_klines_1h` 和 `pipeline_run_*` 不变(高频不需要补救)。

### 2.2 `src/scheduler/jobs.py::build_job_configs`

`cron` 字段支持 dict(单 cron)和 list(多 cron)两种形态:
- dict → `trigger_kind="cron"`,kwargs 直接传 CronTrigger
- list → `trigger_kind="cron_or"`,kwargs={"cron_list": [...]}

### 2.3 `src/scheduler/main.py::_build_trigger`

新增 `cron_or` 分支:`OrTrigger([CronTrigger(**c) for c in cron_list])`。
`apscheduler.triggers.combining.OrTrigger` 自动选最近的下一档触发,
单 job_id 仍是 `collect_onchain` / `collect_macro` / etc。

### 2.4 `src/scheduler/jobs.py` 入口 skip 检查

新增 4 个 helper(无与现有 freshness 检查冲突,grep 已确认):

```python
def _today_utc_iso_midnight() -> str
def _current_iso_monday_utc_midnight() -> str
def _has_today_inserted_in_metric_table(conn, table_name: str) -> bool
def _has_today_kline_1d(conn) -> bool
def _has_this_week_kline_1w(conn) -> bool
def _skipped_today_payload(reason: str, name: str) -> dict
```

**关键设计选择**:用 `inserted_at_utc`(写入 wall-clock)而非 `captured_at_utc`(数据日期)。
理由:FRED CPI 月级 lag、Glassnode 部分 metric 滞后,`captured_at_utc` 不能反映"今天的
collection 是否已成功跑过"。`inserted_at_utc` 严格反映"今天的写入动作"。

接入 4 个 job body 顶部:

| job | 检查 | 命中 → 返回 |
|---|---|---|
| `job_collect_macro` | `_has_today_inserted_in_metric_table(conn, "macro_metrics")` | `status='skipped'`, FredCollector 不实例化 |
| `job_collect_onchain` | `_has_today_inserted_in_metric_table(conn, "onchain_metrics")` | `status='skipped'`, GlassnodeCollector 不实例化, **不 enqueue pipeline_run** |
| `job_collect_klines_daily` | `_has_today_kline_1d(conn)` | `status='skipped'` |
| `job_collect_klines_weekly` | `_has_this_week_kline_1w(conn)` | `status='skipped'` |

`_wrap_job` 现有逻辑保持兼容:`refresh_cards_on_success=True` 但 status='skipped',
不会触发 `refresh_factor_cards`(没有新数据 → 刷新无意义)。

### 2.5 测试更新

`tests/test_scheduler_2_7_a_cron.py`:5 个测试 expecting 单 cron dict,改为
expecting `trigger_kind='cron_or'` 和 `trigger_kwargs['cron_list'][0]`。
保留主时刻断言(主时刻仍是 yaml list 的第 0 项)。

`tests/test_collector_retry_skip.py`(新):16 个测试。

---

## 三、测试

`tests/test_collector_retry_skip.py`:

| 类别 | 测试 |
|---|---|
| Helper 直测(7) | `_has_today_inserted_in_metric_table` true/false/null;`_has_today_kline_1d` true/false (4h);`_has_this_week_kline_1w` true(本周一)/false(上周) |
| job_collect_macro(2) | skip 时 FredCollector 不实例化(`call_count==0`)+ no `factor_cards_refresh`;today 缺失 → 走真实 fetch |
| job_collect_onchain(2) | skip + GlassnodeCollector 不实例化 + **不 enqueue pipeline_run**;today 缺失 → 走真实 fetch |
| job_collect_klines_daily(2) | 1d 已有 → skip;只有 4h 候 → 仍跑(防止误判) |
| job_collect_klines_weekly(2) | 本周 1w 已有 → skip;只有上周 → 仍跑 |
| OrTrigger 注册(1) | `build_scheduler` 后 4 低频 job 的 trigger 是 OrTrigger,sub-trigger 数 == yaml list 长度;collect_klines_1h 仍是单 CronTrigger |

**回归**:全量 `pytest tests/` = **681 passed, 1 skipped, 4.58s**(665 + 16 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 8

# 1. journal 应看到 8 jobs registered + 4 个低频 job 的 OrTrigger 多档
journalctl -u btc-strategy.service --since "1 minute ago" | grep "\[Scheduler\]"

# 2. 用 Python 直接验证 trigger 类型
.venv/bin/python -c "
from src.scheduler.main import build_scheduler
s = build_scheduler(blocking=False)
s.start()
import time; time.sleep(1)
for j in s.get_jobs():
    trig = j.trigger
    if hasattr(trig, 'triggers'):
        print(j.id, type(trig).__name__, len(trig.triggers), 'sub-triggers',
              'next:', j.next_run_time)
    else:
        print(j.id, type(trig).__name__, 'next:', j.next_run_time)
"
# 预期:collect_onchain OrTrigger 10 sub / collect_macro OrTrigger 7 / etc

# 3. 故障演练:今天数据已经存在(刚才 cron 跑过)
#    下一档 cron(macro 10:00 / onchain 10:35 等)journal 应有 "skip"
journalctl -u btc-strategy.service --since "1 hour ago" | grep "today.*already"

# 4. 极端:删今天 onchain_metrics 数据,等下一档 cron 应该真跑
sqlite3 data/btc_strategy.db "DELETE FROM onchain_metrics
WHERE inserted_at_utc >= datetime('now', 'start of day');"
# 等下一档 → 应该真抓 + 写库
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(旧代码必须删除)
- `scheduler.yaml` 4 个低频 job 的旧单 cron dict 全部替换为 list,无新旧并存
- `_has_today_inserted_in_metric_table` 是新加 helper,grep 确认无同名 / 同语义旧函数
- `pipeline.state_builder._evaluate_freshness` 是 pre-flight 检查(目的是判断
  "数据足够新可以跑 pipeline"),与本 sprint 的"今天 collection 是否跑过"
  语义不同,无重复

### §Y
本 commit 立即 push。

### §Z 端到端断言
- 16 个新测试都用真 SQLite + 真 schema + SELECT 断言
- skip 测试断言 `Collector 类的 call_count == 0`(没浪费 API)
- run 测试断言 `Collector.fetch_*.called` + `total_upserted >= 1`
- OrTrigger 测试用真 build_scheduler 注册到 APScheduler,断言 `isinstance(trig, OrTrigger)` + `len(trig.triggers) == N`

### 同类风险扫描
1. **legacy `inserted_at_utc=NULL` 行** — 不会被误算"今天有数据"(WHERE 含 IS NOT NULL),
   测试覆盖
2. **`captured_at_utc=今天` 但 `inserted_at_utc=昨天`** — 这意味着昨天写过的数据点
   "数据日期"是今天,但今天没跑 collection。helper 只看 inserted_at_utc → 仍判 false
   → 今天会真跑,符合"今天补抓"语义
3. **小时跨 BJT/UTC** — 多档 cron 时间是 BJT(yaml `timezone: 'Asia/Shanghai'`),
   helper 比较的 `_today_utc_iso_midnight` 是 UTC 0 点。跨时区不影响:UTC 0 点
   = BJT 8 点。从 BJT 8 点到 BJT 24 点都属于同一个 UTC 日,对低频每天一次的
   collection 完全够用
4. **周一切到周二跨 ISO 周** — `_current_iso_monday_utc_midnight` 用 `date.weekday()`,
   weekday=0 即周一。周一 UTC 0 点之后整周内都返回同一个 monday → skip 检查正确
5. **OrTrigger 被 APScheduler 视为单 job** — 是的,APScheduler 会按 OrTrigger
   计算最近的 fire time,job_id 唯一。`coalesce=true` 防止短时多档重叠时重复跑
6. **新 cron 多档可能在同一分钟内重复触发** — `max_instances=1` 已存在,APScheduler
   不会启第二个实例

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `config/scheduler.yaml` | 4 个低频 job 的 cron 改 list |
| `src/scheduler/jobs.py` | build_job_configs 接受 cron list;新增 5 helper + skip logic 接入 4 jobs |
| `src/scheduler/main.py` | _build_trigger 加 cron_or 分支用 OrTrigger |
| `tests/test_scheduler_2_7_a_cron.py` | 5 个测试改为断言 cron_or trigger_kind |
| `tests/test_collector_retry_skip.py` | 新文件 16 测试 |

---

## 七、部署 checklist

- [ ] git pull
- [ ] `sudo systemctl restart btc-strategy.service`(无 schema 变更,无迁移)
- [ ] journal 看 [Scheduler] 8 jobs registered
- [ ] Python 验证 4 低频 job 是 OrTrigger,sub-trigger 数对
- [ ] 等下次低频 cron 档,journal 应有 "today's ... already exists, skip"
- [ ] 故障演练:删今天数据,下一档 cron 应该真跑
