"""
jobs.py — Sprint 1.15b 任务定义 + 配置装载

三个 job:
  * job_pipeline_run:调 StrategyStateBuilder.run();异常写 FallbackLog,不 crash。
  * job_data_collection:数据采集骨架(默认关闭,占位用)。
  * job_cleanup:清理骨架(默认关闭,占位用)。

build_job_configs(cfg) 把 yaml dict 拍平成 JobConfig 列表,
config 读完后交给 src/scheduler/main.py 注册到 APScheduler。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml


logger = logging.getLogger(__name__)


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH: Path = _PROJECT_ROOT / "config" / "scheduler.yaml"


class JobConfigError(Exception):
    """scheduler.yaml 解析错误。"""


@dataclass
class JobConfig:
    name: str
    enabled: bool
    func: Callable[[], Any]
    trigger_kind: str                 # 'interval' | 'cron'
    trigger_kwargs: dict[str, Any]
    misfire_grace_time: int = 300
    coalesce: bool = True
    max_instances: int = 1
    description: str = ""


# ============================================================
# Job function skeletons
# ============================================================

def job_pipeline_run(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    builder_factory: Optional[Callable[[Any], Any]] = None,
    run_trigger: str = "scheduled",
) -> dict[str, Any]:
    """
    主 Pipeline 任务。异常捕获后写 FallbackLog 并返回 error dict,不 crash。

    依赖注入:
      * conn_factory():返回 sqlite3.Connection。默认走 get_connection()。
      * builder_factory(conn):返回 StrategyStateBuilder。默认用项目类。

    Returns:
      * 成功 → {status: 'ok', run_id, persisted, ai_status, duration_ms}
      * 失败 → {status: 'error', error_type, error_message}
    """
    from ..data.storage.connection import get_connection
    from ..data.storage.dao import FallbackLogDAO

    cf = conn_factory or get_connection
    conn = None
    try:
        conn = cf()
        if builder_factory is None:
            from ..pipeline import StrategyStateBuilder
            builder = StrategyStateBuilder(conn)
        else:
            builder = builder_factory(conn)
        result = builder.run(run_trigger=run_trigger)
        return {
            "status": "ok",
            "run_id": result.run_id,
            "run_timestamp_utc": result.run_timestamp_utc,
            "persisted": result.persisted,
            "ai_status": result.ai_status,
            "duration_ms": result.duration_ms,
            "degraded_stages": result.degraded_stages,
            "failure_count": len(result.failures),
        }
    except Exception as e:
        logger.exception("job_pipeline_run crashed: %s", e)
        # 尝试写 FallbackLog(连接失败就只记日志)
        if conn is not None:
            try:
                from datetime import datetime, timezone
                FallbackLogDAO.log_stage_error(
                    conn,
                    run_timestamp_utc=(
                        datetime.now(timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ")
                    ),
                    stage="scheduler.pipeline_run",
                    error=e,
                    fallback_applied="skip_this_run",
                )
                conn.commit()
            except Exception as inner:
                logger.warning("failed to write FallbackLog: %s", inner)
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e)[:300],
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# Sprint 2.7-C:pipeline_run 拆 2 个 wrapper(对应 yaml 2 个 cron entry)。
# 不同 wrapper 传不同 run_trigger,state_builder 据此应用不同的 pre-flight 阈值。

def job_pipeline_run_regular(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    builder_factory: Optional[Callable[[Any], Any]] = None,
) -> dict[str, Any]:
    """常规档(00/04/12/16/20:05 BJT)。pre-flight 阈值宽松,允许 30h 链上 / 30h 宏观。"""
    return job_pipeline_run(
        conn_factory=conn_factory, builder_factory=builder_factory,
        run_trigger="scheduled",
    )


def job_pipeline_run_8h_onchain(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    builder_factory: Optional[Callable[[Any], Any]] = None,
) -> dict[str, Any]:
    """8 点链上档(08:40 BJT)。pre-flight 强约束:链上 < 10 min,1d/4h K 线 < 30 min。"""
    return job_pipeline_run(
        conn_factory=conn_factory, builder_factory=builder_factory,
        run_trigger="scheduled_8h_onchain",
    )


# Sprint 2.7-B §X:job_data_collection 已完整删除。
# 替代:job_collect_klines_1h / job_collect_klines_daily /
#       job_collect_klines_weekly / job_collect_macro / job_collect_onchain
# 老 yaml 条目 data_collection 在 Sprint 2.7-A 一并删除。
# 旧测试 tests/test_data_collection_job.py 同步删除。


def job_cleanup() -> dict[str, Any]:
    """骨架。"""
    logger.info("job_cleanup: skeleton (no-op)")
    return {"status": "skipped", "reason": "skeleton_only"}


# ============================================================
# Sprint 2.7-B:5 个独立 collector job(替代老的 job_data_collection)。
# 衍生品改 1h interval limit=168(每整点抓过去 7 天 168 个小时 bar)。
# ============================================================

_DERIVATIVES_FETCHERS_1H: tuple[str, ...] = (
    "fetch_funding_rate_history",
    "fetch_funding_rate_aggregated",
    "fetch_open_interest_history",
    "fetch_long_short_ratio_history",
    "fetch_liquidation_history",
)

_GLASSNODE_FETCHERS: tuple[str, ...] = (
    "fetch_mvrv_z_score", "fetch_nupl", "fetch_lth_supply",
    "fetch_exchange_net_flow", "fetch_mvrv", "fetch_realized_price",
    "fetch_lth_realized_price", "fetch_sth_realized_price",
    "fetch_sopr", "fetch_sopr_adjusted",
    "fetch_reserve_risk", "fetch_puell_multiple",
)


def _today_utc_iso_midnight() -> str:
    """今天 UTC 0 点的 ISO 字符串(LIKE 比较起点)。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat() + "T00:00:00Z"


def _current_iso_monday_utc_midnight() -> str:
    """本 ISO 周周一 UTC 0 点的 ISO 字符串。"""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())  # weekday: Mon=0
    return monday.isoformat() + "T00:00:00Z"


def _has_today_inserted_in_metric_table(
    conn: Any, table_name: str,
) -> bool:
    """Sprint 2.8-F:metric 表(macro_metrics / onchain_metrics)今天 UTC
    内是否有 inserted_at_utc(== 今天有过成功收集)。

    用 inserted_at_utc 而非 captured_at_utc:FRED CPI 可能 lag 月级,
    Glassnode 有些 metric 滞后,但 inserted_at_utc 是写入 wall clock,
    严格反映"今天的 collection 是否跑过"。
    """
    today = _today_utc_iso_midnight()
    cur = conn.execute(
        f"SELECT 1 FROM {table_name} "  # noqa: S608 — table_name 来自代码常量
        "WHERE inserted_at_utc IS NOT NULL AND inserted_at_utc >= ? LIMIT 1",
        (today,),
    )
    return cur.fetchone() is not None


def _has_today_kline_1d(conn: Any) -> bool:
    """1d K 线今天 UTC 是否已存在(open_time_utc 落在今天 00:00 之后)。"""
    today = _today_utc_iso_midnight()
    cur = conn.execute(
        "SELECT 1 FROM price_candles "
        "WHERE timeframe='1d' AND open_time_utc >= ? LIMIT 1",
        (today,),
    )
    return cur.fetchone() is not None


def _has_this_week_kline_1w(conn: Any) -> bool:
    """1w K 线本 ISO 周(周一 UTC 0 点)是否已存在。"""
    monday = _current_iso_monday_utc_midnight()
    cur = conn.execute(
        "SELECT 1 FROM price_candles "
        "WHERE timeframe='1w' AND open_time_utc >= ? LIMIT 1",
        (monday,),
    )
    return cur.fetchone() is not None


def _skipped_today_payload(reason: str, name: str) -> dict[str, Any]:
    """Sprint 2.8-F:多档 cron 跳过今天补救档时的统一返回 dict。

    不调 refresh_factor_cards(没有新数据 → 刷新无意义);
    返回 status='skipped' 让 _wrap_job 不再额外标 'ok'。
    """
    return {
        "status": "skipped",
        "reason": reason,
        "by_collector": {name: 0},
        "total_upserted": 0,
        "errors": {},
    }


def _wrap_job(
    name: str,
    body: Callable[[Any], dict[str, Any]],
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    refresh_cards_on_success: bool = False,
) -> dict[str, Any]:
    """Sprint 2.7-B:job 通用 wrapper。捕获 conn 异常 + 计时,不让 scheduler crash。

    Sprint 2.8-A:`refresh_cards_on_success=True` 时,body 成功后立即调
    refresh_factor_cards(conn),把最新 cards 写入 latest_factor_cards 单行表
    (网页"抓取于"实时刷新)。失败只 log warning,不影响主流程。
    """
    from ..data.storage.connection import get_connection
    cf = conn_factory or get_connection
    start_ts = time.time()
    conn = None
    try:
        conn = cf()
        result = body(conn)
        result.setdefault("status", "ok")
        result["duration_ms"] = int((time.time() - start_ts) * 1000)
        if refresh_cards_on_success and result.get("status") == "ok":
            try:
                from ..strategy.factor_cards_refresher import refresh_factor_cards
                refresh_result = refresh_factor_cards(conn)
                result["factor_cards_refresh"] = refresh_result
            except Exception as inner:
                logger.warning(
                    "%s: factor_cards_refresh failed (non-fatal): %s",
                    name, inner,
                )
                result["factor_cards_refresh"] = {
                    "refreshed": False, "error": str(inner)[:200],
                }
        return result
    except Exception as e:
        logger.exception("%s top-level failed: %s", name, e)
        return {
            "status": "fatal_error",
            "error_type": type(e).__name__,
            "error_message": str(e)[:300],
            "duration_ms": int((time.time() - start_ts) * 1000),
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def job_collect_klines_1h(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """每整点 :00 抓 CoinGlass 1h K 线(limit=24)+ 5 衍生品端点(daily, limit=7)。

    Sprint 1.5f-revised:衍生品**反转回 daily**(interval='1d', limit=7)。
    Sprint 2.7-B 一度改 1h limit=168 是误判;实际派生因子算法(7d 均 / 30d 分位 /
    90d Z)以及网页"24h 卡"语义都是基于 daily bar 设计的。hourly 入库导致 series
    平均间隔混乱,派生 tail(N) 行数语义全错(详见 Sprint 1.5f-revised 报告)。
    daily limit=7 + 每小时 cron 让"今天进行中的 daily bar"持续刷新。
    """
    def _body(conn: Any) -> dict[str, Any]:
        from ..data.collectors.coinglass import CoinglassCollector
        from ..data.storage.dao import (
            BTCKlinesDAO, DerivativeMetric, DerivativesDAO, KlineRow,
        )
        cg = CoinglassCollector()
        klines_count = 0
        derivatives_count = 0
        errors: dict[str, str] = {}

        # ---- K 线 1h(limit=24,过去 24 小时)----
        try:
            rows = cg.fetch_klines(interval="1h", limit=24)
            if rows:
                klines = [
                    KlineRow(
                        timeframe="1h", timestamp=r["timestamp"],
                        open=r["open"], high=r["high"],
                        low=r["low"], close=r["close"],
                        volume_btc=r.get("volume", 0.0) or 0.0,
                    )
                    for r in rows
                ]
                klines_count = BTCKlinesDAO.upsert_klines(conn, klines)
        except Exception as e:
            logger.warning("collect_klines_1h klines.1h failed: %s", e)
            errors["klines_1h"] = str(e)[:200]

        # ---- Sprint 1.5f-revised:衍生品 5 端点 daily limit=7(每小时 cron 刷新今天 bar)----
        for fn_name in _DERIVATIVES_FETCHERS_1H:
            try:
                fn = getattr(cg, fn_name, None)
                if fn is None:
                    continue
                rows = fn(interval="1d", limit=7)
                if rows:
                    metrics = [
                        DerivativeMetric(
                            timestamp=r["timestamp"],
                            metric_name=r.get("metric_name"),
                            metric_value=r.get("metric_value"),
                        )
                        for r in rows
                    ]
                    derivatives_count += DerivativesDAO.upsert_batch(conn, metrics)
            except Exception as e:
                logger.warning("collect_klines_1h derivatives.%s failed: %s",
                               fn_name, e)
                errors[fn_name] = str(e)[:200]

        conn.commit()
        return {
            "by_collector": {
                "klines_1h": klines_count,
                "derivatives_1h": derivatives_count,
            },
            "total_upserted": klines_count + derivatives_count,
            "errors": errors,
        }
    return _wrap_job("collect_klines_1h", _body, conn_factory=conn_factory,
                     refresh_cards_on_success=True)


def job_collect_klines_daily(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """每天 08:01 BJT 抓 CoinGlass 1d + 4h K 线(各 limit=24,覆盖 24 天 / 4 天)。

    Sprint 2.8-F:多档 cron 补救;入口若发现今天已有 1d 候,直接 skipped。
    """
    def _body(conn: Any) -> dict[str, Any]:
        if _has_today_kline_1d(conn):
            logger.info("collect_klines_daily: today's 1d candle already exists, skip")
            return _skipped_today_payload(
                "already_have_today_1d_candle", "klines_daily",
            )
        from ..data.collectors.coinglass import CoinglassCollector
        from ..data.storage.dao import BTCKlinesDAO, KlineRow
        cg = CoinglassCollector()
        by_tf: dict[str, int] = {}
        errors: dict[str, str] = {}

        for tf in ("1d", "4h"):
            try:
                rows = cg.fetch_klines(interval=tf, limit=24)
                if not rows:
                    by_tf[tf] = 0
                    continue
                klines = [
                    KlineRow(
                        timeframe=tf, timestamp=r["timestamp"],
                        open=r["open"], high=r["high"],
                        low=r["low"], close=r["close"],
                        volume_btc=r.get("volume", 0.0) or 0.0,
                    )
                    for r in rows
                ]
                by_tf[tf] = BTCKlinesDAO.upsert_klines(conn, klines)
            except Exception as e:
                logger.warning("collect_klines_daily klines.%s failed: %s", tf, e)
                errors[tf] = str(e)[:200]
                by_tf[tf] = 0

        conn.commit()
        return {
            "by_collector": by_tf,
            "total_upserted": sum(by_tf.values()),
            "errors": errors,
        }
    return _wrap_job("collect_klines_daily", _body, conn_factory=conn_factory,
                     refresh_cards_on_success=True)


def job_collect_klines_weekly(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """每周一 08:01 BJT 抓 1w K 线(limit=12,覆盖 ~3 个月)。

    Sprint 2.8-F:周一/二/三 多档 cron 补救;入口若发现本周已有 1w 候,直接 skipped。
    """
    def _body(conn: Any) -> dict[str, Any]:
        if _has_this_week_kline_1w(conn):
            logger.info("collect_klines_weekly: this week's 1w candle already exists, skip")
            return _skipped_today_payload(
                "already_have_this_week_1w_candle", "klines_weekly",
            )
        from ..data.collectors.coinglass import CoinglassCollector
        from ..data.storage.dao import BTCKlinesDAO, KlineRow
        cg = CoinglassCollector()
        try:
            rows = cg.fetch_klines(interval="1w", limit=12)
            if not rows:
                return {"by_collector": {"1w": 0}, "total_upserted": 0, "errors": {}}
            klines = [
                KlineRow(
                    timeframe="1w", timestamp=r["timestamp"],
                    open=r["open"], high=r["high"],
                    low=r["low"], close=r["close"],
                    volume_btc=r.get("volume", 0.0) or 0.0,
                )
                for r in rows
            ]
            n = BTCKlinesDAO.upsert_klines(conn, klines)
            conn.commit()
            return {"by_collector": {"1w": n}, "total_upserted": n, "errors": {}}
        except Exception as e:
            logger.warning("collect_klines_weekly failed: %s", e)
            return {"by_collector": {"1w": 0}, "total_upserted": 0,
                    "errors": {"1w": str(e)[:200]}}
    return _wrap_job("collect_klines_weekly", _body, conn_factory=conn_factory,
                     refresh_cards_on_success=True)


def job_collect_macro(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    since_days: int = 30,
) -> dict[str, Any]:
    """每天 06:00 BJT 抓 FRED 9 个 series。无 key 时优雅 skip。

    Sprint 2.8-F:06-12 BJT 多档 cron 补救;入口若发现今天 macro_metrics 已写过,
    直接 skipped 不浪费 FRED API quota。
    """
    def _body(conn: Any) -> dict[str, Any]:
        if _has_today_inserted_in_metric_table(conn, "macro_metrics"):
            logger.info("collect_macro: today's macro_metrics already written, skip")
            return _skipped_today_payload(
                "already_have_today_macro_inserted", "fred",
            )
        from ..data.collectors.fred import FredCollector
        fc = FredCollector()
        if not fc.enabled:
            logger.info("collect_macro: FRED key not configured, skipping")
            return {"by_collector": {"fred": 0}, "total_upserted": 0,
                    "errors": {"fred": "FRED_API_KEY not set"}, "status": "skipped"}
        stats = fc.collect_and_save_all(conn, since_days=since_days)
        n = sum(v for k, v in stats.items()
                if isinstance(v, int) and not k.startswith("__"))
        conn.commit()
        return {
            "by_collector": {"fred": n},
            "total_upserted": n,
            "errors": {},
            "fred_breakdown": stats,
        }
    return _wrap_job("collect_macro", _body, conn_factory=conn_factory,
                     refresh_cards_on_success=True)


def job_collect_onchain(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    since_days: int = 30,
) -> dict[str, Any]:
    """每天 08:35 BJT 抓 Glassnode 12 个 fetcher(primary 5 + display 7 含
    LTH/STH realized price + aSOPR)。

    Sprint 2.8-F:08:35-20:00 BJT 多档 cron 补救;入口若发现今天 onchain_metrics
    已写过,直接 skipped。注意:skip 不调 _enqueue_pipeline_run(没有新数据)。
    """
    def _body(conn: Any) -> dict[str, Any]:
        if _has_today_inserted_in_metric_table(conn, "onchain_metrics"):
            logger.info("collect_onchain: today's onchain_metrics already written, skip")
            return _skipped_today_payload(
                "already_have_today_onchain_inserted", "glassnode",
            )
        from ..data.collectors.glassnode import GlassnodeCollector
        from ..data.storage.dao import OnchainDAO, OnchainMetric
        gn = GlassnodeCollector()
        total = 0
        errors: dict[str, str] = {}

        for fn_name in _GLASSNODE_FETCHERS:
            try:
                fn = getattr(gn, fn_name, None)
                if fn is None:
                    continue
                rows = fn(since_days=since_days)
                if rows:
                    metrics = [
                        OnchainMetric(
                            timestamp=r["timestamp"],
                            metric_name=r.get("metric_name"),
                            metric_value=r.get("metric_value"),
                            source=r.get("source", "glassnode_primary"),
                        )
                        for r in rows
                    ]
                    total += OnchainDAO.upsert_batch(conn, metrics)
            except Exception as e:
                logger.warning("collect_onchain.%s failed: %s", fn_name, e)
                errors[fn_name] = str(e)[:200]

        conn.commit()
        # Sprint 2.7-D:onchain 抓完立即 enqueue 一次 pipeline_run(event_onchain)
        # 无节流(每天 08:35 只跑一次,天然不重复)
        if total > 0:
            _enqueue_pipeline_run("event_onchain")
        return {
            "by_collector": {"glassnode": total},
            "total_upserted": total,
            "events_triggered": ["event_onchain"] if total > 0 else [],
            "errors": errors,
        }
    return _wrap_job("collect_onchain", _body, conn_factory=conn_factory,
                     refresh_cards_on_success=True)


def job_event_listener(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """Sprint 2.7-D:60 秒高频常驻,扫 4 类 event。

    流程:
      1. check_and_trigger_events(conn) → list[event_type]
      2. 对每个返回的 event_type,调度一次 pipeline_run(run_trigger=event_type)
         (用 _enqueue_pipeline_run,写 active_scheduler 注入的全局引用)
    """
    def _body(conn: Any) -> dict[str, Any]:
        from .event_listener import check_and_trigger_events
        triggered = check_and_trigger_events(conn)
        for evt in triggered:
            _enqueue_pipeline_run(evt)
        return {
            "by_collector": {"events": len(triggered)},
            "total_upserted": 0,
            "events_triggered": triggered,
            "errors": {},
        }
    return _wrap_job("event_listener", _body, conn_factory=conn_factory)


# Sprint 2.7-D:scheduler 全局引用(由 build_scheduler 在创建后写入)。
# event_listener / collect_onchain 通过 _enqueue_pipeline_run 调度 event 触发的
# pipeline_run。无 scheduler 时(单测 / 直调)退化为 logger.info。
_active_scheduler: Optional[Any] = None


def set_active_scheduler(scheduler: Any) -> None:
    """build_scheduler 在创建后调用,把 scheduler 实例存为全局。"""
    global _active_scheduler
    _active_scheduler = scheduler


def _enqueue_pipeline_run(run_trigger: str, *, delay_sec: int = 10) -> bool:
    """把一次 pipeline_run 调度到 _active_scheduler,run_date=now+delay_sec。

    Returns True 表示成功调度,False 表示无 scheduler(单测/直调路径)或失败。
    delay_sec 默认 10s 让当前 collector job 有时间 commit。
    """
    sched = _active_scheduler
    if sched is None:
        logger.info(
            "event triggered but no active scheduler: run_trigger=%s "
            "(test or direct-invoke path, no enqueue)",
            run_trigger,
        )
        return False
    try:
        from datetime import datetime, timedelta, timezone
        run_date = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
        sched.add_job(
            func=job_pipeline_run,
            trigger="date",
            run_date=run_date,
            kwargs={"run_trigger": run_trigger},
            id=f"event_pipeline_{run_trigger}_{int(run_date.timestamp())}",
            replace_existing=True,
        )
        logger.info(
            "enqueued pipeline_run for run_trigger=%s at %s",
            run_trigger, run_date.isoformat(),
        )
        return True
    except Exception as e:
        logger.warning("_enqueue_pipeline_run failed: %s", e)
        return False


_JOB_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "pipeline_run": job_pipeline_run,  # 单测/直调入口,生产 yaml 用下面 2 个 wrapper
    # Sprint 2.7-C:pipeline 2 个 wrapper(对应 yaml 2 个 cron 条目)
    "pipeline_run_regular": job_pipeline_run_regular,
    "pipeline_run_8h_onchain": job_pipeline_run_8h_onchain,
    # Sprint 2.7-A/B:5 个 collector + event_listener(2.7-D 已完整实施 +
    # 1.5q 修注释:event_listener 真在跑,4 类 event 都通,但生产 30d 0 触发
    # 是因为 ±3% 24h 阈值在中长期波段并非高频信号 — 详见 sprint_1_5q.md A.1)
    "collect_klines_1h": job_collect_klines_1h,
    "collect_klines_daily": job_collect_klines_daily,
    "collect_klines_weekly": job_collect_klines_weekly,
    "collect_macro": job_collect_macro,
    "collect_onchain": job_collect_onchain,
    "event_listener": job_event_listener,
    "cleanup": job_cleanup,
}


# ============================================================
# Config loading
# ============================================================

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)


def _parse_interval(value: str) -> dict[str, Any]:
    """
    '4h' → {hours: 4}, '30m' → {minutes: 30}, '7200s' → {seconds: 7200}, '1d' → {days: 1}
    """
    m = _INTERVAL_RE.match(str(value))
    if not m:
        raise JobConfigError(f"invalid interval string: {value!r}")
    n, unit = int(m.group(1)), m.group(2).lower()
    mapping = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    return {mapping[unit]: n}


def load_scheduler_config(
    config_path: Optional[str | Path] = None,
) -> dict[str, Any]:
    """读 scheduler.yaml,返回原始 dict(便于测试注入)。"""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_job_configs(
    cfg: dict[str, Any],
    *,
    functions_override: Optional[dict[str, Callable[..., Any]]] = None,
) -> list[JobConfig]:
    """
    把 yaml 的 jobs 段转成 JobConfig 列表(含 disabled 的 — 调用方自行过滤)。
    """
    funcs = dict(_JOB_FUNCTIONS)
    if functions_override:
        funcs.update(functions_override)

    jobs_cfg = cfg.get("jobs") or {}
    if not isinstance(jobs_cfg, dict):
        raise JobConfigError("scheduler.yaml: 'jobs' section must be a dict")

    out: list[JobConfig] = []
    for name, spec in jobs_cfg.items():
        if not isinstance(spec, dict):
            raise JobConfigError(f"job {name}: spec must be a dict")
        # Sprint 2.7-C §X:`func:` 字段(2.7-A 引入用于 pipeline_run 双 cron
        # 共享函数)已废弃 — 现在 yaml job_name 必须直接命中 _JOB_FUNCTIONS。
        # pipeline 双档改用 job_pipeline_run_regular / _8h_onchain 两个独立函数。
        if name not in funcs:
            raise JobConfigError(f"job {name}: no registered function")
        if "interval" in spec:
            trigger_kind = "interval"
            trigger_kwargs = _parse_interval(spec["interval"])
        elif "cron" in spec:
            cron = spec["cron"]
            if isinstance(cron, dict):
                trigger_kind = "cron"
                trigger_kwargs = dict(cron)
            elif isinstance(cron, list):
                # Sprint 2.8-F:多档 cron → OrTrigger,单 job_id
                if not cron:
                    raise JobConfigError(
                        f"job {name}: 'cron' list must not be empty"
                    )
                for entry in cron:
                    if not isinstance(entry, dict):
                        raise JobConfigError(
                            f"job {name}: each cron list entry must be a dict"
                        )
                trigger_kind = "cron_or"
                trigger_kwargs = {"cron_list": [dict(c) for c in cron]}
            else:
                raise JobConfigError(
                    f"job {name}: 'cron' must be a dict or list of dicts"
                )
        else:
            raise JobConfigError(
                f"job {name}: must provide either 'interval' or 'cron'"
            )
        out.append(JobConfig(
            name=name,
            enabled=bool(spec.get("enabled", False)),
            func=funcs[name],
            trigger_kind=trigger_kind,
            trigger_kwargs=trigger_kwargs,
            misfire_grace_time=int(spec.get("misfire_grace_time", 300)),
            coalesce=bool(spec.get("coalesce", True)),
            max_instances=int(spec.get("max_instances", 1)),
            description=str(spec.get("description", "")),
        ))
    return out
