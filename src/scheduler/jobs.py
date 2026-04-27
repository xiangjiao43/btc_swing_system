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


def job_data_collection(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    since_days: int = 7,
) -> dict[str, Any]:
    """Sprint 2.6-A:数据采集主任务,每小时调一次 3 个 collector 把最新数据写入 DB。

    Sprint 2.6-A.4:Yahoo 已弃用(腾讯云 IP 被 Yahoo 全局 429 封禁),
    macro 数据全部由 FRED 提供。当前 collector 列表:FRED / CoinGlass / Glassnode。

    优雅失败语义:
    - 单个 collector 抛异常 → 记日志 + by_collector[name]=0 + 继续其他
    - 全部失败 → 也不抛(scheduler 不能 crash),但 status='all_failed'
    - FRED key 未配置时 fred 优雅 skip,不算失败

    Returns:
      {status, total_upserted, by_collector: {fred, coinglass, glassnode},
       errors: {collector_name: msg}, duration_ms, since_days}
    """
    import time

    from ..data.storage.connection import get_connection

    cf = conn_factory or get_connection
    start_ts = time.time()
    by_collector: dict[str, int] = {}
    errors: dict[str, str] = {}
    conn = None

    try:
        conn = cf()

        # ---- FRED(无 key 时优雅 skip)----
        try:
            from ..data.collectors.fred import FredCollector
            fc = FredCollector()
            if fc.enabled:
                fred_stats = fc.collect_and_save_all(conn, since_days=since_days)
                by_collector["fred"] = sum(
                    v for k, v in fred_stats.items()
                    if isinstance(v, int) and not k.startswith("__")
                )
                conn.commit()
            else:
                by_collector["fred"] = 0
                logger.info("data_collection.fred skipped (no API key)")
        except Exception as e:
            logger.exception("data_collection.fred failed: %s", e)
            by_collector["fred"] = 0
            errors["fred"] = str(e)[:200]

        # ---- CoinGlass(增量,只更新最新)----
        try:
            from ..data.collectors.coinglass import CoinglassCollector
            from ..data.storage.dao import (
                BTCKlinesDAO, DerivativeMetric, DerivativesDAO, KlineRow,
            )
            cg = CoinglassCollector()
            cg_count = 0
            for tf in ("1h", "4h", "1d"):
                try:
                    rows = cg.fetch_klines(interval=tf, limit=24)
                    if rows:
                        klines = [
                            KlineRow(
                                timeframe=tf, timestamp=r["timestamp"],
                                open=r["open"], high=r["high"],
                                low=r["low"], close=r["close"],
                                volume_btc=r.get("volume", 0.0) or 0.0,
                            )
                            for r in rows
                        ]
                        cg_count += BTCKlinesDAO.upsert_klines(conn, klines)
                except Exception as inner:
                    logger.warning("coinglass klines.%s failed: %s", tf, inner)
            for fn_name in (
                "fetch_funding_rate_history", "fetch_long_short_ratio_history",
            ):
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
                        cg_count += DerivativesDAO.upsert_batch(conn, metrics)
                except Exception as inner:
                    logger.warning("coinglass %s failed: %s", fn_name, inner)
            by_collector["coinglass"] = cg_count
            conn.commit()
        except Exception as e:
            logger.exception("data_collection.coinglass failed: %s", e)
            by_collector["coinglass"] = 0
            errors["coinglass"] = str(e)[:200]

        # ---- Glassnode(增量,9 个指标)----
        try:
            from ..data.collectors.glassnode import GlassnodeCollector
            from ..data.storage.dao import OnchainDAO, OnchainMetric
            gn = GlassnodeCollector()
            gn_count = 0
            for fn_name in (
                "fetch_mvrv_z_score", "fetch_nupl", "fetch_lth_supply",
                "fetch_exchange_net_flow", "fetch_mvrv", "fetch_realized_price",
                "fetch_sopr", "fetch_reserve_risk", "fetch_puell_multiple",
            ):
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
                        gn_count += OnchainDAO.upsert_batch(conn, metrics)
                except Exception as inner:
                    logger.warning("glassnode.%s failed: %s", fn_name, inner)
            by_collector["glassnode"] = gn_count
            conn.commit()
        except Exception as e:
            logger.exception("data_collection.glassnode failed: %s", e)
            by_collector["glassnode"] = 0
            errors["glassnode"] = str(e)[:200]

        total = sum(by_collector.values())
        any_success = any(v > 0 for v in by_collector.values())
        status = "ok" if any_success else "all_failed"

        logger.info(
            "data_collection done: status=%s total=%d by=%s errors=%s",
            status, total, by_collector, list(errors.keys()),
        )

        return {
            "status": status,
            "total_upserted": total,
            "by_collector": by_collector,
            "errors": errors,
            "duration_ms": int((time.time() - start_ts) * 1000),
            "since_days": since_days,
        }
    except Exception as e:
        logger.exception("data_collection top-level failed: %s", e)
        return {
            "status": "fatal_error",
            "error_type": type(e).__name__,
            "error_message": str(e)[:300],
            "by_collector": by_collector,
            "duration_ms": int((time.time() - start_ts) * 1000),
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def job_cleanup() -> dict[str, Any]:
    """骨架。"""
    logger.info("job_cleanup: skeleton (no-op)")
    return {"status": "skipped", "reason": "skeleton_only"}


_JOB_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "pipeline_run": job_pipeline_run,
    "data_collection": job_data_collection,
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
        if name not in funcs:
            raise JobConfigError(f"job {name}: no registered function")
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
            func=funcs[name],
            trigger_kind=trigger_kind,
            trigger_kwargs=trigger_kwargs,
            misfire_grace_time=int(spec.get("misfire_grace_time", 300)),
            coalesce=bool(spec.get("coalesce", True)),
            max_instances=int(spec.get("max_instances", 1)),
            description=str(spec.get("description", "")),
        ))
    return out
