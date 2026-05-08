# Glassnode Cron 归属事实核查(只查不改)

**日期**:2026-05-08
**类型**:事实核查 sprint(纯只读 SSH + grep + journalctl)
**触发**:用户问「最近 24h 那 10 档 Glassnode 调用是不是全部来自 collect_onchain,还是混了别的 job」

## 结论一句话

**最近 24h journalctl 里 10 个出现 Glassnode 403 的 cron 时刻全部来自 `collect_onchain`
job 一个**(每档 13 个 fetcher × 10 档 = 130 次 403 全在它头上)。

**没有别的 job 直接打 Glassnode** —— 全代码搜 `GlassnodeCollector()` 实例化只有
`src/scheduler/jobs.py:691` 一处,在 `job_collect_onchain` 函数体内。

`pipeline_run_regular`(16:05 BJT)在 collect_onchain 之后跑,但它读 DB 现成的
`onchain_metrics` 表行,**不发 Glassnode 网络请求**。

---

## 段 2 — 原文证据(不摘要,直接贴)

### 2.1 `config/scheduler.yaml` 全文

```yaml
# ============================================================
# scheduler.yaml — APScheduler 任务配置(Sprint 2.7-A 重写)
# ============================================================
# 时区改为 BJT(Asia/Shanghai),所有 cron 时间都按北京时间。
# 7 个独立 cron job + 1 个 60s 常驻 event_listener:
#   collect_klines_1h        每整点 :00,衍生品 1h + K 线 1h
#   collect_klines_daily     每天 08:01,1d/4h K 线
#   collect_klines_weekly    每周一 08:01,1w K 线
#   collect_macro            每天 06:00,FRED 9 个 series
#   collect_onchain          每天 08:35,Glassnode + sopr_adjusted + LTH 等
#   pipeline_run             6 档:00:05/04:05/12:05/16:05/20:05 + 08:40
#   event_listener           60 秒高频,4 种 event 触发
#
# yaml 字段:
#   enabled              true/false。关掉即不注册到 scheduler。
#   func                 可选,默认 = job 名;允许多 yaml 条目共享同一函数
#                       (pipeline_run_regular + pipeline_run_8h_onchain
#                       都跑 pipeline_run)
#   interval             '60s' / '5m' / '1h' / '1d' interval trigger
#   cron                 dict,key 用 APScheduler CronTrigger kwargs
#                       (hour / minute / day / day_of_week)。
#   misfire_grace_time   错过触发的允许补跑秒数
#   coalesce             多次错过合并为一次
#   max_instances        并发上限(默认 1)
#
# Sprint 2.6-A 老配置(pipeline_run interval 4h + data_collection interval 1h)
# 已删除,Sprint 2.7-B 删除老的 job_data_collection 函数。
# ============================================================

timezone: 'Asia/Shanghai'

jobs:

  # ------------- 数据采集 ----------------------------

  collect_klines_1h:
    enabled: true
    cron: {minute: 0}                  # 每整点 :00 BJT
    misfire_grace_time: 240            # 4 分钟,不影响下个整点
    coalesce: true
    max_instances: 1
    description: '1h K 线 + 5 衍生品端点(1h interval, limit=168)'

  # Sprint 2.8-F:低频 collector 改多档 cron(主时刻 + 多个补救时刻),
  # 任一档成功后,job 入口 _has_today_* 检查会让后续档 status='skipped'。
  # 目的:API key 临时失效 / 网络抖动覆盖单个 cron 时,不再等下个周期。

  collect_klines_daily:
    enabled: true
    cron:                              # 08:01 主 + 9 个补救档(BJT)
      - {hour: 8, minute: 1}
      - {hour: 9, minute: 1}
      - {hour: 10, minute: 1}
      - {hour: 11, minute: 1}
      - {hour: 12, minute: 1}
      - {hour: 14, minute: 1}
      - {hour: 16, minute: 1}
      - {hour: 18, minute: 1}
      - {hour: 20, minute: 1}
    misfire_grace_time: 600
    coalesce: true
    max_instances: 1
    description: '1d / 4h K 线日级抓取(多档自动补救)'

  collect_klines_weekly:
    enabled: true
    cron:                              # 周一主 + 周一/二/三 补救档
      - {day_of_week: 'mon', hour: 8, minute: 1}
      - {day_of_week: 'mon', hour: 12, minute: 1}
      - {day_of_week: 'mon', hour: 16, minute: 1}
      - {day_of_week: 'mon', hour: 20, minute: 1}
      - {day_of_week: 'tue', hour: 8, minute: 1}
      - {day_of_week: 'tue', hour: 12, minute: 1}
      - {day_of_week: 'wed', hour: 8, minute: 1}
    misfire_grace_time: 1800
    coalesce: true
    max_instances: 1
    description: '1w K 线周级抓取(本周内多档补救)'

  collect_macro:
    enabled: true
    cron:                              # 06:00 主 + 06-12 每小时补救档(BJT)
      - {hour: 6, minute: 0}
      - {hour: 7, minute: 0}
      - {hour: 8, minute: 0}
      - {hour: 9, minute: 0}
      - {hour: 10, minute: 0}
      - {hour: 11, minute: 0}
      - {hour: 12, minute: 0}
    misfire_grace_time: 1800
    coalesce: true
    max_instances: 1
    description: 'FRED 9 个 series + alias(多档补救)'

  collect_onchain:
    enabled: true
    cron:                              # 08:35 主 + 多个补救档(BJT)
      - {hour: 8, minute: 35}
      - {hour: 9, minute: 5}
      - {hour: 9, minute: 35}
      - {hour: 10, minute: 35}
      - {hour: 11, minute: 35}
      - {hour: 12, minute: 35}
      - {hour: 14, minute: 0}
      - {hour: 16, minute: 0}
      - {hour: 18, minute: 0}
      - {hour: 20, minute: 0}
    misfire_grace_time: 600
    coalesce: true
    max_instances: 1
    description: 'Glassnode 13 个 metric(多档补救)'

  # ------------- 主 pipeline(2 个 cron entry,共享 pipeline_run 函数)-------

  # Sprint 1.9-B(2026-05-01)启用:1 档 16:05 BJT cron(= UTC 08:05),
  # 配合 BTC_USE_ORCHESTRATOR=true 走 v1.3 AI orchestrator 路径。
  # pipeline_run_8h_onchain 用户决策保持 disabled(8h 链上档是 v1.2 残余,
  # 1.9.1 持仓健康检查会重新设计)。
  pipeline_run_regular:
    enabled: true
    cron: {hour: 16, minute: 5}        # 16:05 BJT(= UTC 08:05),每日 1 档
    misfire_grace_time: 300
    coalesce: true
    max_instances: 1
    description: 'Pipeline 主循环(16:05 BJT 每日 1 档,run_trigger=scheduled);Sprint 1.9-B 启用'

  pipeline_run_8h_onchain:
    enabled: false
    cron: {hour: 8, minute: 40}        # 08:40 BJT(链上 08:35 抓完 + 5 分钟缓冲)
    misfire_grace_time: 300
    coalesce: true
    max_instances: 1
    description: 'Pipeline 8 点链上档(用户决策不启;1.9.1 重新设计持仓健康检查)'

  # ------------- 高频事件监听 ------------------------

  event_listener:
    enabled: true
    interval: '60s'                    # 60 秒高频常驻
    misfire_grace_time: 30
    coalesce: true
    max_instances: 1
    description: '事件触发器:event_macro(events_calendar 命中)+ event_price 双轨(±5% 空仓 / ±3% 持仓);1.10-G 后 event_invalidation 拆出 hard_invalidation_monitor 1h cron'

  # Sprint 1.10-G v1.4 §10.4.1 新增:硬失效位独立 1h cron(规则平仓,无 AI)
  hard_invalidation_monitor:
    enabled: true
    interval: '1h'
    misfire_grace_time: 60
    coalesce: true
    max_instances: 1
    description: 'event_invalidation:每 1h 检查 active thesis stop_loss 是否击穿 → 规则平仓(channel A,无 AI)'

  # Sprint 1.10-G v1.4 §10.4.1 新增:持仓期 4h 健康检查
  # Sprint 1.10-H D2=a:接通 EmergencySimplifiedA 真 AI(trigger='health_check' 区分场景)
  position_health_check:
    enabled: true
    interval: '4h'
    misfire_grace_time: 300
    coalesce: true
    max_instances: 1
    description: '持仓期 4h 健康检查;无 active thesis 直接返回;有 thesis 调 EmergencySimplifiedA(trigger=health_check)真 AI 评估'

  # Sprint 1.10-H v1.4 §3.3.9 + §8.1 新增:周复盘 AI(每周日 22:00 BJT)
  weekly_review:
    enabled: true
    cron: {day_of_week: 'sun', hour: 22, minute: 0}    # 周日 22:00 BJT
    misfire_grace_time: 3600                            # 1h 容忍度
    coalesce: true
    max_instances: 1
    description: '周复盘 AI(WeeklyReviewAnalyst);周日 22:00 BJT 自动跑,输出 4 段 JSON 写 weekly_reviews 表 + alerts'
```

### 2.2 `collect_onchain` 全代码引用

```
src/scheduler/jobs.py:193:  #       job_collect_klines_weekly / job_collect_macro / job_collect_onchain
src/scheduler/jobs.py:667:  def job_collect_onchain(
src/scheduler/jobs.py:683:                  "collect_onchain: today's all expected onchain metrics "
src/scheduler/jobs.py:713:                  logger.warning("collect_onchain.%s failed: %s", fn_name, e)
src/scheduler/jobs.py:744:      return _wrap_job("collect_onchain", _body, conn_factory=conn_factory,
src/scheduler/jobs.py:774:  # event_listener / collect_onchain 通过 _enqueue_pipeline_run 调度 event 触发的
src/scheduler/jobs.py:1298: "collect_onchain": job_collect_onchain,
src/scheduler/main.py:80:    # 让 event_listener / collect_onchain 能动态 add_job(date trigger)
src/scheduler/__init__.py:15:   job_collect_onchain,
src/scheduler/__init__.py:32:   "job_collect_onchain",
scripts/verify_cleanup_v14.py:311: "collect_klines_weekly", "collect_macro", "collect_onchain",
config/scheduler.yaml:10:   #   collect_onchain          每天 08:35,Glassnode + sopr_adjusted + LTH 等
config/scheduler.yaml:95:   collect_onchain:
```

### 2.3 全代码 `GlassnodeCollector` 实例化点扫描

```
src/data/collectors/glassnode.py:46:   class GlassnodeCollectorError(RuntimeError):
src/data/collectors/glassnode.py:58:   class GlassnodeCollector:
src/data/collectors/__init__.py:23:    from .glassnode import GlassnodeCollector, GlassnodeCollectorError
src/scheduler/jobs.py:689:              from ..data.collectors.glassnode import GlassnodeCollector
src/scheduler/jobs.py:691:              gn = GlassnodeCollector()        # ← 唯一一处 NEW
```

**唯一一处实例化在 `src/scheduler/jobs.py:691`**,位于 `job_collect_onchain._body()`
函数体内,由 yaml 的 `collect_onchain` cron 触发。

### 2.4 journalctl 最近 24h 的 collect_onchain 触发归属

```
$ ssh ubuntu@124.222.89.86 "journalctl -u btc-strategy.service --since '24 hours ago' --no-pager | \
  grep -E 'collect_onchain.fetch_' | awk '{print substr(\$0, 1, 12)}' | sort | uniq -c"

     13 May 07 16:00
     13 May 07 18:00
     13 May 07 20:00
     13 May 08 08:35
     13 May 08 09:05
     13 May 08 09:35
     13 May 08 10:35
     13 May 08 11:35
     13 May 08 12:35
     13 May 08 14:00
```

**对照 yaml `collect_onchain.cron` 10 个 entry**:
- {hour: 8, minute: 35} ✅ 14:00 当天 已过 (May 08 早上)
- {hour: 9, minute: 5} ✅ May 08 09:05
- {hour: 9, minute: 35} ✅ May 08 09:35
- {hour: 10, minute: 35} ✅ May 08 10:35
- {hour: 11, minute: 35} ✅ May 08 11:35
- {hour: 12, minute: 35} ✅ May 08 12:35
- {hour: 14, minute: 0} ✅ May 08 14:00
- {hour: 16, minute: 0} ✅ May 07 16:00
- {hour: 18, minute: 0} ✅ May 07 18:00
- {hour: 20, minute: 0} ✅ May 07 20:00

**10 / 10 完美对齐。**(May 08 08:35 BJT 也对应 yaml 第 1 档,在窗口内)

### 2.5 `job_collect_onchain` 函数体节选(Glassnode 实例化点)

```python
# src/scheduler/jobs.py:677-720
def _body(conn: Any) -> dict[str, Any]:
    if _onchain_today_complete(conn):
        logger.info(...)
        return _skipped_today_payload(...)
    from ..data.collectors.glassnode import GlassnodeCollector
    gn = GlassnodeCollector()       # ← 唯一一处 Glassnode HTTP 入口
    total = 0
    errors: dict[str, str] = {}
    for fn_name in _GLASSNODE_FETCHERS:    # 13 个 fetcher
        try:
            fn = getattr(gn, fn_name, None)
            if fn is None:
                continue
            rows = fn(since_days=since_days)
            if rows:
                metrics = [...]
                total += OnchainDAO.upsert_batch(conn, metrics)
        except Exception as e:
            logger.warning("collect_onchain.%s failed: %s", fn_name, e)
            errors[fn_name] = str(e)[:200]
    conn.commit()
```

### 2.6 `job_pipeline_run` 函数体节选(查证不调 Glassnode)

```python
# src/scheduler/jobs.py:53-150
def job_pipeline_run(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    builder_factory: Optional[Callable[[Any], Any]] = None,
    run_trigger: str = "scheduled",
) -> dict[str, Any]:
    """主 Pipeline 任务。异常捕获后写 FallbackLog 并返回 error dict,不 crash。"""
    from ..data.storage.connection import get_connection
    from ..data.storage.dao import FallbackLogDAO

    cf = conn_factory or get_connection
    conn = None
    try:
        conn = cf()
        # Sprint 1.10-H D3=a:S3 过度保守监控同步检查
        try:
            from src.strategy.conservative_monitor import ConservativeMonitor
            ConservativeMonitor.check_and_alert(conn)
            conn.commit()
        except Exception as _e:
            logger.warning("conservative_monitor pre-check raised: %s", _e)

        if builder_factory is None:
            from ..pipeline import StrategyStateBuilder
            builder = StrategyStateBuilder(conn)
        else:
            builder = builder_factory(conn)
        result = builder.run(run_trigger=run_trigger)

        # Sprint 1.10-H D4=b2:thesis 创建后联动 EXIT_D
        # ... (DB 操作,无网络)
        return {...}
    except Exception as e:
        logger.exception("job_pipeline_run crashed: %s", e)
        ...
        return {...}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
```

`job_pipeline_run` **没有任何 import 或调用 GlassnodeCollector**。它只调
`StrategyStateBuilder(conn).run()`,后者读 DB 现成的 `onchain_metrics` 行,
不发 Glassnode 网络请求。

### 2.7 `_enqueue_pipeline_run` 链路(收尾观察)

```python
# src/scheduler/jobs.py:732-738(在 job_collect_onchain._body 末尾)
# Sprint 2.7-D:onchain 抓完立即 enqueue 一次 pipeline_run(event_onchain)
# 无节流(每天 08:35 只跑一次,天然不重复)
if total > 0:
    _enqueue_pipeline_run("event_onchain")
```

`collect_onchain` 抓完后,如果 `total > 0` 就 enqueue 一次 `pipeline_run`(以
`run_trigger="event_onchain"`)。今天 `total = 748`(派生 MVRV 写了 748 行),
所以 pipeline_run 被多次额外触发(May 07 16:02 / 18:02 / 20:02 BJT 各跑一次,
每次都崩在 `state_builder.py:363 _run_v13_orchestrator`,但**这条链不发 Glassnode
请求**)。

---

## 段 3 — 同类风险扫描:还有别的 job 也会顺手撞 Glassnode 吗?

`grep -rn 'GlassnodeCollector\|glassnode' src/ --include='*.py' | grep -v __pycache__`
全量结果里,**所有非 collector 自身文件的引用**:

| 文件:行 | 引用类型 | 是否发 Glassnode 请求? |
|---|---|---|
| `src/api/routes/system.py:127` | 字符串 key `"glassnode_onchain"` 用于 health card 标签 | ❌ 否 |
| `src/api/routes/system.py:175` | DB freshness 查询 `SELECT MAX(inserted_at_utc) FROM onchain_metrics` | ❌ 否(读 DB)|
| `src/data/collectors/_config_loader.py:33` | docstring 例子 | ❌ 否 |
| `src/data/storage/dao.py:61` | source 字段允许值列表 `"glassnode_primary", ...` | ❌ 否 |
| `src/data/storage/dao.py:450` | `_default_source = "glassnode"` 在 OnchainDAO | ❌ 否 |
| `src/scheduler/jobs.py:687` | `_skipped_today_payload(..., "glassnode")` 字符串参数 | ❌ 否(skip 路径,不发请求)|
| `src/scheduler/jobs.py:689-691` | `from ... import GlassnodeCollector; gn = GlassnodeCollector()` | ✅ 唯一发请求点 |

**结论**:全代码只有 `job_collect_onchain` 一处会发 Glassnode 网络请求。
**没有其他 job 会顺手撞 Glassnode**。

---

## 段 3 补充观察:虽不撞 Glassnode,但以下行为放大了「失败-重试」噪音

1. `_enqueue_pipeline_run("event_onchain")` 触发条件是 `total > 0`,而本地派生
   MVRV 总是写若干行 → **即使 13 个 Glassnode fetcher 全 403,pipeline_run 也会
   被额外 enqueue 一次**,然后崩在 v1.3 orchestrator 的 stack trace 里。
   每个 collect_onchain cron(10 档)都会顺手再多跑一次失败的 pipeline_run。
2. `pipeline_run_regular` 每天 16:05 BJT 还会按 yaml cron 自跑一次(独立于
   collect_onchain)。
3. `event_listener` 每 60s 运行一次,如果检测到 event 也会 enqueue pipeline_run。

但这些都**不发 Glassnode 请求**,只是消耗 CPU + 触发其他错误日志。

---

## 改动清单

**本次纯查不改,无代码 / 配置改动**。仅产出本报告。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A(纯查不改)|
| GitHub push(commit hash) | ✅ 见下文 commit |
| 服务器 git pull | N/A |
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 / 清污 | N/A |

## 本 sprint 删除清单

**本 sprint 无替代关系,无删除项**(纯事实核查报告,无代码/配置改动)。
