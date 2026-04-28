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
        result = builder.run(run_trigger="scheduled")
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


def _wrap_job(
    name: str,
    body: Callable[[Any], dict[str, Any]],
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """Sprint 2.7-B:job 通用 wrapper。捕获 conn 异常 + 计时,不让 scheduler crash。"""
    from ..data.storage.connection import get_connection
    cf = conn_factory or get_connection
    start_ts = time.time()
    conn = None
    try:
        conn = cf()
        result = body(conn)
        result.setdefault("status", "ok")
        result["duration_ms"] = int((time.time() - start_ts) * 1000)
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
    """每整点 :00 抓 CoinGlass 1h K 线(limit=24)+ 5 衍生品端点(1h interval, limit=168)。

    衍生品 1h interval 是 Sprint 2.7-B 关键变更:之前 interval='1d' limit=7
    导致衍生品被强制日级 → 用户永远看不到小时级精度。
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

        # ---- 衍生品 5 端点 1h interval limit=168(过去 7 天的 1h bar)----
        for fn_name in _DERIVATIVES_FETCHERS_1H:
            try:
                fn = getattr(cg, fn_name, None)
                if fn is None:
                    continue
                rows = fn(interval="1h", limit=168)
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
    return _wrap_job("collect_klines_1h", _body, conn_factory=conn_factory)


def job_collect_klines_daily(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """每天 08:01 BJT 抓 CoinGlass 1d + 4h K 线(各 limit=24,覆盖 24 天 / 4 天)。"""
    def _body(conn: Any) -> dict[str, Any]:
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
    return _wrap_job("collect_klines_daily", _body, conn_factory=conn_factory)


def job_collect_klines_weekly(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """每周一 08:01 BJT 抓 1w K 线(limit=12,覆盖 ~3 个月)。"""
    def _body(conn: Any) -> dict[str, Any]:
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
    return _wrap_job("collect_klines_weekly", _body, conn_factory=conn_factory)


def job_collect_macro(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    since_days: int = 30,
) -> dict[str, Any]:
    """每天 06:00 BJT 抓 FRED 9 个 series。无 key 时优雅 skip。"""
    def _body(conn: Any) -> dict[str, Any]:
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
    return _wrap_job("collect_macro", _body, conn_factory=conn_factory)


def job_collect_onchain(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    since_days: int = 30,
) -> dict[str, Any]:
    """每天 08:35 BJT 抓 Glassnode 12 个 fetcher(primary 5 + display 7 含
    LTH/STH realized price + aSOPR)。"""
    def _body(conn: Any) -> dict[str, Any]:
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
        return {
            "by_collector": {"glassnode": total},
            "total_upserted": total,
            "errors": errors,
        }
    return _wrap_job("collect_onchain", _body, conn_factory=conn_factory)


def job_event_listener(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """Sprint 2.7-A stub:60s 高频常驻,扫 events_calendar + 价格异动 + 失效位。
    2.7-D 实施。"""
    logger.info("job_event_listener: stub_pre_2_7_d (no-op)")
    return {"status": "skipped", "reason": "stub_pre_2_7_d"}


_JOB_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "pipeline_run": job_pipeline_run,
    # Sprint 2.7-A/B:5 个 collector + event_listener(stub,2.7-D 实施)
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
        # Sprint 2.7-A:可选 'func' 字段允许多 yaml 条目共享同一函数
        # (例如 pipeline_run_regular + pipeline_run_8h_onchain 都跑 pipeline_run)。
        # 默认 func = name(向后兼容)。
        func_key = str(spec.get("func") or name)
        if func_key not in funcs:
            raise JobConfigError(
                f"job {name}: no registered function (func={func_key!r})"
            )
        if "interval" in spec:
            trigger_kind = "interval"
            trigger_kwargs = _parse_interval(spec["interval"])
        elif "cron" in spec:
            cron = spec["cron"]
            if not isinstance(cron, dict):
                raise JobConfigError(f"job {name}: 'cron' must be a dict")
            trigger_kind = "cron"
            trigger_kwargs = dict(cron)
        else:
            raise JobConfigError(
                f"job {name}: must provide either 'interval' or 'cron'"
            )
        out.append(JobConfig(
            name=name,
            enabled=bool(spec.get("enabled", False)),
            func=funcs[func_key],
            trigger_kind=trigger_kind,
            trigger_kwargs=trigger_kwargs,
            misfire_grace_time=int(spec.get("misfire_grace_time", 300)),
            coalesce=bool(spec.get("coalesce", True)),
            max_instances=int(spec.get("max_instances", 1)),
            description=str(spec.get("description", "")),
        ))
    return out
