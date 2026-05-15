"""
jobs.py — APScheduler 任务定义 + 配置装载。

核心 job:
  * job_pipeline_run:调 StrategyStateBuilder.run();异常写 FallbackLog,不 crash。
  * collector jobs:按 scheduler.yaml 写入 K 线、衍生品、链上、宏观与事件数据。
  * event / hard_invalidation / weekly_review jobs:处理 v1.4 触发与复盘。

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
        # Sprint 1.10-H D3=a:S3 过度保守监控同步检查(builder.run 之前)
        # 规则计算 < 1ms;告警立即体现在下一次网页刷新 / 主裁决输出。
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
        # 检测:builder.run 期间是否有新 thesis 创建 → 调 exit_d_thesis_resumed
        # 退出 active 'overly_conservative' review_pending(若有)
        try:
            from datetime import datetime as _dt, timezone as _tz
            from src.data.storage.dao import ThesesDAO
            from src.strategy.review_pending import (
                exit_d_thesis_resumed, is_in_review_pending,
            )
            rp = is_in_review_pending(conn)
            if rp.get("in_review_pending") and rp.get("reason") == "overly_conservative":
                # 检测最新一条 thesis 是否在本次 run 后创建
                # 简化:取最新 thesis,若 created_at_utc > 本次 run 起始 → 触发 exit_d
                row = conn.execute(
                    "SELECT thesis_id FROM theses ORDER BY created_at_utc DESC LIMIT 1"
                ).fetchone()
                if row is not None:
                    now_iso = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    exit_d_thesis_resumed(
                        conn, exit_at_utc=now_iso,
                        new_thesis_id=row["thesis_id"]
                                       if hasattr(row, "keys") else row[0],
                    )
                    conn.commit()
                    logger.info(
                        "exit_d_thesis_resumed triggered after new thesis creation",
                    )
        except Exception as _e:
            logger.warning("exit_d post-check raised: %s", _e)
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
    """每日主裁决档(当前 scheduler.yaml 为 11:35 BJT)。

    pre-flight 阈值宽松,允许 30h 链上 / 30h 宏观。
    """
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


def job_layer_a_spot_strategy(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """每日 10:00 BJT 独立运行 Layer A 大周期现货策略。

    只运行 A1-A5 + Spot Validator + latest_layer_a_spot_strategy 持久化。
    不运行 Layer B,不创建 thesis,不触碰虚拟账户。
    """
    from ..data.storage.connection import get_connection
    from ..pipeline.layer_a_spot_runner import LayerASpotStrategyRunner

    cf = conn_factory or get_connection
    conn = None
    try:
        conn = cf()
        runner = LayerASpotStrategyRunner(conn)
        result = runner.run(run_trigger="scheduled_layer_a_spot", persist=True)
        return {
            "status": result.status,
            "run_id": result.run_id,
            "generated_at_utc": result.generated_at_utc,
            "generated_at_bjt": result.generated_at_bjt,
            "persisted": result.persisted,
            "duration_ms": result.duration_ms,
            "degraded_stages": result.degraded_stages,
            "failure_count": len(result.failures),
        }
    except Exception as e:
        logger.exception("job_layer_a_spot_strategy crashed: %s", e)
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
    "fetch_sopr_adjusted",
    # Layer A 大周期现货策略专用因子;只采集入库,不改变 Layer B 交易逻辑。
    "fetch_percent_supply_in_profit", "fetch_exchange_balance",
    "fetch_lth_sopr", "fetch_sth_sopr", "fetch_rhodl_ratio",
    "fetch_reserve_risk", "fetch_puell_multiple",
    "fetch_lth_net_position_change",
    # Sprint 1.7:删除 Layer B 的 fetch_sopr / reserve_risk / puell 用法。
    # 2026-05:reserve_risk / puell_multiple 仅作为 Layer A 只读周期因子恢复采集。
    # Sprint 1.6(建模 v1.3 §2.4):4 新链上端点
    "fetch_sth_supply", "fetch_ssr", "fetch_cdd", "fetch_hodl_waves",
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


# Sprint C(2026-05-08):onchain "今日完整性"门简化 — 任一一手 Glassnode 行
# 今天写过就算完成。老的 _ONCHAIN_EXPECTED_METRICS_TODAY 13-metric 全集合检查 +
# _ONCHAIN_HODL_WAVES_PREFIX 已删除(13 个 fetcher 共用一个 fetch_attempts
# bucket,所以"全部 13 metric 今天都写过"和"任一一手 source 今天有行"在 quota
# 分流后语义等价)。
_ONCHAIN_FIRST_HAND_SOURCES: tuple[str, ...] = (
    "glassnode_primary",
    "glassnode_display",
    "glassnode_derived_breakdown_by_age",
)


def _onchain_today_complete(conn: Any) -> bool:
    """Sprint C(2026-05-08)重写:今天满足任一即返 True,abort 后续档。

    (a) 今天 onchain_metrics 表有任意一手 Glassnode 数据
        (source IN _ONCHAIN_FIRST_HAND_SOURCES,排除 'computed' 派生)
    (b) 今天 fetch_attempts 表有 source='glassnode_onchain' status='failure'
        failure_reason='quota_exceeded' 的行(撞配额墙别再抓)
        且 rows_upserted=0。若同轮已写入部分 Glassnode 数据,说明只是
        endpoint-level 部分失败,不能阻止后续重试。

    非 quota 失败(network/api/parse)继续返 False → 后续档重试。
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # (a) 今天有一手 Glassnode 数据
    placeholders = ",".join(["?"] * len(_ONCHAIN_FIRST_HAND_SOURCES))
    try:
        row = conn.execute(
            f"SELECT 1 FROM onchain_metrics "
            f"WHERE captured_at_utc LIKE ? "
            f"  AND source IN ({placeholders}) "
            f"LIMIT 1",
            (f"{today}%", *_ONCHAIN_FIRST_HAND_SOURCES),
        ).fetchone()
        if row is not None:
            logger.info(
                "_onchain_today_complete: 今天已有一手 Glassnode 数据 → skip",
            )
            return True
    except Exception as e:
        logger.warning("_onchain_today_complete (a) onchain_metrics 查询失败: %s", e)

    # (b) 今天撞 quota
    try:
        row = conn.execute(
            "SELECT 1 FROM fetch_attempts "
            "WHERE source = 'glassnode_onchain' "
            "  AND status = 'failure' "
            "  AND failure_reason = 'quota_exceeded' "
            "  AND COALESCE(rows_upserted, 0) = 0 "
            "  AND attempted_at_utc LIKE ? "
            "LIMIT 1",
            (f"{today}%",),
        ).fetchone()
        if row is not None:
            logger.info(
                "_onchain_today_complete: 今天 fetch_attempts 已撞 quota → skip 后续档",
            )
            return True
    except Exception as e:
        logger.warning("_onchain_today_complete (b) fetch_attempts 查询失败: %s", e)

    return False


def _has_today_btc_dominance_or_etf_flow(conn: Any) -> bool:
    """Sprint 1.6.1:derivatives_snapshots 今天是否已有 btc_dominance / etf_flow。

    本 sprint 这两个 metric 通过 DerivativesDAO.upsert_batch 进 wide 表的
    full_data_json extras。直接 LIKE 匹配 full_data_json 里出现的字段名。
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        cur = conn.execute(
            "SELECT 1 FROM derivatives_snapshots "
            "WHERE captured_at_utc LIKE ? "
            "  AND (full_data_json LIKE '%btc_dominance%' "
            "       OR full_data_json LIKE '%etf_flow%') "
            "LIMIT 1",
            (f"{today}%",),
        )
    except Exception:
        return False
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
    Sprint A(数据真实性):skip 路径不写 fetch_attempts(没有真正 fetch)。
    """
    return {
        "status": "skipped",
        "reason": reason,
        "by_collector": {name: 0},
        "total_upserted": 0,
        "errors": {},
    }


def _record_fetch_attempt(
    conn: Any,
    *,
    source: str,
    start_ts: float,
    rows_upserted: int,
    first_exc: Optional[BaseException],
) -> None:
    """Sprint A(数据真实性透明化底座)— bucket 跑完后写一行 fetch_attempts。

    first_exc=None 时记 success;否则记 failure 并取首个 exception 分类。
    时间用 time.time() 起点 → 当前的 wall-time 差,不调 commit(调用方 commit)。
    """
    from ..data.collectors._classify_failure import classify_fetch_failure
    from ..data.storage.dao import FetchAttemptsDAO
    duration_ms = int((time.time() - start_ts) * 1000)
    if first_exc is None:
        FetchAttemptsDAO.record_attempt(
            conn, source=source, status="success",
            rows_upserted=rows_upserted, duration_ms=duration_ms,
        )
    else:
        reason, msg = classify_fetch_failure(first_exc)
        FetchAttemptsDAO.record_attempt(
            conn, source=source, status="failure",
            failure_reason=reason, error_message=msg,
            rows_upserted=rows_upserted, duration_ms=duration_ms,
        )


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
        kl_first_exc: Optional[BaseException] = None
        deriv_first_exc: Optional[BaseException] = None

        # ---- K 线 1h(limit=24,过去 24 小时)----
        kl_start = time.time()
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
            kl_first_exc = e
            logger.warning("collect_klines_1h klines.1h failed: %s", e)
            errors["klines_1h"] = str(e)[:200]

        # ---- Sprint 1.5f-revised:衍生品 5 端点 daily limit=7(每小时 cron 刷新今天 bar)----
        deriv_start = time.time()
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
                if deriv_first_exc is None:
                    deriv_first_exc = e
                logger.warning("collect_klines_1h derivatives.%s failed: %s",
                               fn_name, e)
                errors[fn_name] = str(e)[:200]

        # Sprint A:每个 source bucket 跑完写一行 fetch_attempts
        _record_fetch_attempt(
            conn, source="binance_kline", start_ts=kl_start,
            rows_upserted=klines_count, first_exc=kl_first_exc,
        )
        _record_fetch_attempt(
            conn, source="coinglass_derivatives", start_ts=deriv_start,
            rows_upserted=derivatives_count, first_exc=deriv_first_exc,
        )

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
        # Sprint 1.6.1 任务 B.2:细粒度门 — 1d 候 + 1.6 新 CoinGlass 2 metric
        # 都今天写过才 skip;否则继续(K 线 upsert 幂等,不重复抓)。
        kline_done = _has_today_kline_1d(conn)
        cg_metrics_done = _has_today_btc_dominance_or_etf_flow(conn)
        if kline_done and cg_metrics_done:
            logger.info(
                "collect_klines_daily: today's 1d candle + btc_dominance/etf_flow "
                "all written, skip",
            )
            return _skipped_today_payload(
                "already_have_today_1d_and_cg_metrics", "klines_daily",
            )
        from ..data.collectors.coinglass import CoinglassCollector
        from ..data.storage.dao import BTCKlinesDAO, KlineRow
        cg = CoinglassCollector()
        by_tf: dict[str, int] = {}
        errors: dict[str, str] = {}
        kl_first_exc: Optional[BaseException] = None
        deriv_first_exc: Optional[BaseException] = None

        kl_start = time.time()
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
                if kl_first_exc is None:
                    kl_first_exc = e
                logger.warning("collect_klines_daily klines.%s failed: %s", tf, e)
                errors[tf] = str(e)[:200]
                by_tf[tf] = 0
        klines_count = by_tf.get("1d", 0) + by_tf.get("4h", 0)

        # Sprint 1.6(建模 v1.3 §2.6):2 个机构/市场结构 daily 端点
        # btc_dominance + etf_flow → 入 derivatives_snapshots(daily timestamp guard 1.5f)
        from ..data.storage.dao import DerivativeMetric, DerivativesDAO
        deriv_start = time.time()
        for fn_name in ("fetch_btc_dominance", "fetch_etf_flow_history"):
            try:
                fn = getattr(cg, fn_name, None)
                if fn is None:
                    continue
                rows = fn(interval="1d", limit=720)
                if not rows:
                    by_tf[fn_name] = 0
                    continue
                metrics = [
                    DerivativeMetric(
                        timestamp=r["timestamp"],
                        metric_name=r["metric_name"],
                        metric_value=r["metric_value"],
                    )
                    for r in rows
                ]
                by_tf[fn_name] = DerivativesDAO.upsert_batch(conn, metrics)
            except Exception as e:
                if deriv_first_exc is None:
                    deriv_first_exc = e
                logger.warning("collect_klines_daily.%s failed: %s",
                               fn_name, e)
                errors[fn_name] = str(e)[:200]
                by_tf[fn_name] = 0
        deriv_count = (
            by_tf.get("fetch_btc_dominance", 0)
            + by_tf.get("fetch_etf_flow_history", 0)
        )

        # Sprint A:每个 source bucket 跑完写一行 fetch_attempts
        _record_fetch_attempt(
            conn, source="binance_kline", start_ts=kl_start,
            rows_upserted=klines_count, first_exc=kl_first_exc,
        )
        _record_fetch_attempt(
            conn, source="coinglass_derivatives", start_ts=deriv_start,
            rows_upserted=deriv_count, first_exc=deriv_first_exc,
        )

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
        kl_start = time.time()
        try:
            rows = cg.fetch_klines(interval="1w", limit=12)
            if not rows:
                _record_fetch_attempt(
                    conn, source="binance_kline", start_ts=kl_start,
                    rows_upserted=0, first_exc=None,
                )
                conn.commit()
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
            _record_fetch_attempt(
                conn, source="binance_kline", start_ts=kl_start,
                rows_upserted=n, first_exc=None,
            )
            conn.commit()
            return {"by_collector": {"1w": n}, "total_upserted": n, "errors": {}}
        except Exception as e:
            _record_fetch_attempt(
                conn, source="binance_kline", start_ts=kl_start,
                rows_upserted=0, first_exc=e,
            )
            conn.commit()
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
        fred_start = time.time()
        first_exc: Optional[BaseException] = None
        n = 0
        stats: dict[str, Any] = {}
        try:
            stats = fc.collect_and_save_all(conn, since_days=since_days)
            n = sum(v for k, v in stats.items()
                    if isinstance(v, int) and not k.startswith("__"))
        except Exception as e:
            first_exc = e
            logger.warning("collect_macro fred failed: %s", e)

        _record_fetch_attempt(
            conn, source="fred_macro", start_ts=fred_start,
            rows_upserted=n, first_exc=first_exc,
        )
        conn.commit()
        if first_exc is not None:
            return {
                "by_collector": {"fred": n},
                "total_upserted": n,
                "errors": {"fred": str(first_exc)[:200]},
                "fred_breakdown": stats,
            }
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
        # Sprint 1.6.1 任务 B:细粒度"今日完整性"门 — 期望集合(老 12 + 1.6 新 4)
        # 全在 onchain_metrics 今天写过才 skip;否则继续 fetch 缺的部分
        if _onchain_today_complete(conn):
            logger.info(
                "collect_onchain: today's all expected onchain metrics "
                "already written, skip",
            )
            return _skipped_today_payload(
                "already_have_today_onchain_complete", "glassnode",
            )
        from ..data.collectors.glassnode import GlassnodeCollector
        from ..data.storage.dao import OnchainDAO, OnchainMetric
        gn = GlassnodeCollector()
        total = 0
        errors: dict[str, str] = {}
        # Sprint A:13 fetcher 共用一个 source bucket,任一失败 → bucket=failure
        gn_first_exc: Optional[BaseException] = None
        gn_start = time.time()
        glassnode_rows = 0

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
                    n = OnchainDAO.upsert_batch(conn, metrics)
                    total += n
                    glassnode_rows += n
            except Exception as e:
                if gn_first_exc is None:
                    gn_first_exc = e
                logger.warning("collect_onchain.%s failed: %s", fn_name, e)
                errors[fn_name] = str(e)[:200]

        # Sprint A:13 fetcher 跑完写一行 fetch_attempts(rows_upserted 不含派生)
        _record_fetch_attempt(
            conn, source="glassnode_onchain", start_ts=gn_start,
            rows_upserted=glassnode_rows, first_exc=gn_first_exc,
        )

        conn.commit()

        # Sprint 1.6:Glassnode fetch 完后跑本地派生 MVRV 计算
        # (alphanode 不开 mvrv_more,改 price/realized_price 比率)
        derived_stats: dict[str, int] = {}
        try:
            from ..data.collectors.derived_onchain import (
                compute_and_save_derived_mvrv,
            )
            derived_stats = compute_and_save_derived_mvrv(conn)
            total += sum(derived_stats.values())
        except Exception as e:
            logger.warning("derived_mvrv compute failed: %s", e)
            errors["derived_mvrv"] = str(e)[:200]

        # Sprint F.1(2026-05-09)用户决策:删 event_onchain enqueue。
        # 中长线策略每天只跑 1 次 master(BJT 11:35 pipeline_run_regular,
        # 等 Glassnode 10:35 终档 + 1h 缓冲)。collect_onchain 完成后不再
        # enqueue 额外 pipeline_run,严守"一天 1 次"原则,大幅省 token。
        # 邵底机制仍在:event_price 持仓 ±3% / event_macro / hard_invalidation
        # 1h 规则平仓。
        # 历史:Sprint B 曾把"任一 success 就 enqueue"修成"真 success 才 enqueue";
        # Sprint F.1 进一步删整条 enqueue 路径(gn_success 仍计算供 events_triggered
        # 字段保留语义,日志还能看出 fetch 是否真成功)。
        gn_success = (gn_first_exc is None) and (glassnode_rows > 0)
        # NOTE:不再调 _enqueue_pipeline_run("event_onchain")。
        return {
            "by_collector": {
                "glassnode": glassnode_rows,
                "derived_mvrv": sum(derived_stats.values()),
            },
            "total_upserted": total,
            # Sprint F.1:enqueue 已删,events_triggered 永远为空 list。
            # 保留 key 供下游兼容(no_opportunity_narrator / KPI collector 读)。
            "events_triggered": [],
            "errors": errors,
            # 诊断字段(便于排查 collect_onchain fetch 真实状态)
            "glassnode_fetch_success": gn_success,
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


def _enqueue_pipeline_run(
    run_trigger: str,
    *,
    delay_sec: int = 10,
    attempt: int = 1,
    retry_start_utc: Optional[Any] = None,
) -> bool:
    """把一次 pipeline_run 调度到 _active_scheduler,run_date=now+delay_sec。

    Sprint 1.10-G(D3=a)接通 RetryPolicy 异步调度:
      - attempt: 第几次尝试(1=首次,2/3 = retry)
      - retry_start_utc: 首次失败的时间点(用于 RetryPolicy.is_within_window 2h 检查)

    Returns True 表示成功调度,False 表示无 scheduler(单测/直调路径)或失败。
    delay_sec 默认 10s 让当前 collector job 有时间 commit;retry 由 RetryPolicy
    给(5/10/20 分钟 backoff)。
    """
    sched = _active_scheduler
    if sched is None:
        logger.info(
            "event triggered but no active scheduler: run_trigger=%s attempt=%d "
            "(test or direct-invoke path, no enqueue)",
            run_trigger, attempt,
        )
        return False
    try:
        from datetime import datetime, timedelta, timezone
        run_date = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
        sched.add_job(
            func=job_pipeline_run_with_retry,
            trigger="date",
            run_date=run_date,
            kwargs={
                "run_trigger": run_trigger,
                "attempt": attempt,
                "retry_start_utc": retry_start_utc,
            },
            id=(
                f"event_pipeline_{run_trigger}_attempt{attempt}_"
                f"{int(run_date.timestamp())}"
            ),
            replace_existing=True,
        )
        logger.info(
            "enqueued pipeline_run for run_trigger=%s attempt=%d at %s",
            run_trigger, attempt, run_date.isoformat(),
        )
        return True
    except Exception as e:
        logger.warning("_enqueue_pipeline_run failed: %s", e)
        return False


# ============================================================
# Sprint 1.10-G:RetryPolicy 异步调度 wrapper(D3=a APScheduler one-shot)
# ============================================================

def job_pipeline_run_with_retry(
    *,
    run_trigger: str = "scheduled",
    attempt: int = 1,
    retry_start_utc: Optional[Any] = None,
    conn_factory: Optional[Callable[[], Any]] = None,
    builder_factory: Optional[Callable[[Any], Any]] = None,
) -> dict[str, Any]:
    """job_pipeline_run 包装 + RetryPolicy 异步重试(v1.4 §6.3 D3=a 接通)。

    1. 调 job_pipeline_run(run_trigger)
    2. 若 status='error' 或 ai_status startswith 'degraded':
       - attempt < 3 且 in 2h window → 用 RetryPolicy.compute_backoff_seconds
         schedule 同 job 在 backoff 秒后再跑(attempt+1)
       - 否则 → 放弃 + 推 critical 告警(暂只 logger.error)
    3. 成功 → 直接返回

    retry_start_utc 由首次失败时记录(ISO 字符串),后续 attempt 携带传递,
    RetryPolicy.is_within_window 用它判定 2h 总窗口。
    """
    from datetime import datetime, timezone
    from src.ai.retry_policy import RetryPolicy

    result = job_pipeline_run(
        conn_factory=conn_factory, builder_factory=builder_factory,
        run_trigger=run_trigger,
    )
    # 判定是否需要 retry
    failed = (
        result.get("status") == "error"
        or str(result.get("ai_status", "")).startswith("degraded")
    )
    if not failed:
        return result

    rp = RetryPolicy()
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # 首次失败:retry_start_utc 设为现在(ISO 字符串,RetryPolicy 接口要求)
    if retry_start_utc is None:
        retry_start_utc = now_iso

    if not rp.should_retry(
        attempt=attempt + 1,
        run_started_at_utc=str(retry_start_utc),
        now_utc=now_iso,
    ):
        logger.error(
            "pipeline_run RETRY EXHAUSTED: run_trigger=%s attempt=%d "
            "(超 max_attempts=3 或超 2h 窗口)— critical 告警",
            run_trigger, attempt,
        )
        result["retry_exhausted"] = True
        result["retry_attempts"] = attempt
        return result

    backoff = rp.compute_backoff_seconds(attempt + 1)
    logger.warning(
        "pipeline_run failed (attempt %d), scheduling retry in %ds (attempt %d)",
        attempt, backoff, attempt + 1,
    )
    enq = _enqueue_pipeline_run(
        run_trigger,
        delay_sec=backoff,
        attempt=attempt + 1,
        retry_start_utc=retry_start_utc,
    )
    result["retry_scheduled"] = enq
    result["retry_next_attempt"] = attempt + 1
    result["retry_next_delay_sec"] = backoff
    return result


# ============================================================
# Sprint 1.10-G:1h hard_invalidation_monitor + 4h position_health_check
# ============================================================

def job_hard_invalidation_monitor(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """v1.4 §6.2.3 + §10.4.1:每 1h 检查 active thesis stop_loss 是否击穿。

    击穿 → HardInvalidationMonitor.execute_invalidation 规则平仓(channel A,
    无 AI),retry_log_marker 由 caller(本 job)塞入 event_throttle 兼容老 sink。

    流程:
      1. HardInvalidationMonitor.get_latest_btc_price(conn) 取最新 1h close
      2. check_active_theses(conn, current_btc_price) 取击穿列表
      3. 对每条 breach,execute_invalidation → fill + close + retry_log_marker
      4. 写 event_throttle(event_type='event_invalidation', class='event_invalidation')
      5. 推 critical 告警(本 sprint 用 logger.error;1.10-I 网页层加 toast)

    本 job **不调 AI**(v1.4 §6.2.3 硬约束)。
    """
    def _body(conn: Any) -> dict[str, Any]:
        from datetime import datetime, timezone
        from src.strategy.event_trigger import (
            EVENT_CLASS_INVALIDATION, EventTrigger,
        )
        from src.strategy.hard_invalidation_monitor import HardInvalidationMonitor

        now = datetime.now(timezone.utc)
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        current_px = HardInvalidationMonitor.get_latest_btc_price(conn)
        if current_px is None:
            return {
                "by_collector": {"hard_invalidation": 0},
                "total_upserted": 0,
                "events_triggered": [],
                "errors": {"no_kline": "no 1h close available"},
            }

        breaches = HardInvalidationMonitor.check_active_theses(
            conn, current_btc_price=current_px, now_utc=now,
        )
        if not breaches:
            return {
                "by_collector": {"hard_invalidation": 0,
                                  "current_btc_price": current_px},
                "total_upserted": 0,
                "events_triggered": [],
                "errors": {},
            }

        # 读 initial_capital(virtual_account 第一行)
        initial_capital = 100000.0
        try:
            row = conn.execute(
                "SELECT initial_capital FROM virtual_account "
                "ORDER BY snapshot_at_utc ASC LIMIT 1"
            ).fetchone()
            if row is not None:
                initial_capital = float(
                    row[0] if not hasattr(row, "keys") else row["initial_capital"]
                )
        except Exception:
            pass  # fallback to default

        executed: list[dict[str, Any]] = []
        for b in breaches:
            res = HardInvalidationMonitor.execute_invalidation(
                conn,
                thesis_id=b["thesis_id"],
                stop_loss_order_id=b["stop_loss_order_id"],
                current_btc_price=current_px,
                initial_capital=initial_capital,
                now_utc=now,
            )
            executed.append(res)
            if res.get("status") == "event_invalidation_executed":
                # 写 event_throttle 标记 event_invalidation 已触发
                EventTrigger.record_event(
                    conn,
                    event_type="event_invalidation",
                    event_class=EVENT_CLASS_INVALIDATION,
                    triggered_at_utc=now_iso,
                )
                logger.error(
                    "CRITICAL: event_invalidation TRIGGERED "
                    "thesis=%s direction=%s stop_loss=%.2f current=%.2f",
                    b["thesis_id"], b["direction"],
                    b["stop_loss_price"], current_px,
                )

        return {
            "by_collector": {
                "hard_invalidation": len(executed),
                "current_btc_price": current_px,
            },
            "total_upserted": len([
                e for e in executed
                if e.get("status") == "event_invalidation_executed"
            ]),
            "events_triggered": ["event_invalidation"] if executed else [],
            "errors": {},
            "executed": executed,
        }

    return _wrap_job(
        "hard_invalidation_monitor", _body, conn_factory=conn_factory,
    )


def job_position_health_check(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """v1.4 §10.4.1 + Sprint 1.10-H D2=a:持仓期 4h 健康检查接通真 AI。

    流程:
      1. ThesesDAO.get_active → 无 active 直接返(节约 AI 成本)
      2. 调 EmergencySimplifiedA.analyze(trigger='health_check')
         - baseline = 上次 strategy_run BTC 价格
         - current = 最新 1h K 线 close
         - active_thesis 注入 ctx
      3. 不真改持仓 / stop_loss(本 sprint 只输出建议,执行留 1.10-I 网页 + 用户确认)
      4. immediate_action 写 alerts 用 info severity 通知

    输入复用 1.10-G EventTrigger.get_baseline_price + HardInvalidationMonitor
    .get_latest_btc_price helper。
    """
    def _body(conn: Any) -> dict[str, Any]:
        from src.ai.agents.emergency_simplified_a import EmergencySimplifiedA
        from src.ai.client import build_anthropic_client
        from src.data.storage.dao import ThesesDAO
        from src.strategy.event_trigger import EventTrigger
        from src.strategy.hard_invalidation_monitor import HardInvalidationMonitor

        active = ThesesDAO.get_active(conn)
        if active is None:
            return {
                "by_collector": {"position_health_check": "no_active_thesis"},
                "total_upserted": 0,
                "events_triggered": [],
                "errors": {},
            }

        baseline = EventTrigger.get_baseline_price(conn)
        current = HardInvalidationMonitor.get_latest_btc_price(conn)
        if baseline is None or current is None:
            logger.warning(
                "position_health_check: 缺 baseline (%s) 或 current_price (%s),跳过",
                baseline, current,
            )
            return {
                "by_collector": {"position_health_check": "skipped_no_price_data"},
                "total_upserted": 0,
                "events_triggered": [],
                "errors": {"price_data": "missing"},
            }

        pct = (current - baseline) / baseline if baseline > 0 else 0.0
        ctx = {
            "trigger": "health_check",      # D2=a 区分 event_price
            "current_strategy_state": _state_from_thesis(active),
            "triggered_at_price": current,
            "baseline_price": baseline,
            "pct_change": pct,
            "key_factors": {},               # 本 sprint 简化:留 1.10-L 真 API 时丰富
            "active_thesis": active,
        }
        agent = EmergencySimplifiedA()
        try:
            out = agent.analyze(ctx, client=build_anthropic_client())
        except Exception as e:
            logger.warning("position_health_check: agent raised: %s", e)
            out = agent._fallback_output()
        out = EmergencySimplifiedA.normalize_output(out)

        # 写一行 alerts 通知(severity 由 immediate_action 决定)
        action = out.get("immediate_action", "maintain")
        sev_map = {
            "emergency_exit": "critical",
            "tighten_stop": "warning",
            "wait_next_full": "info",
            "maintain": "info",
        }
        severity = sev_map.get(action, "info")
        from datetime import datetime as _dt, timezone as _tz
        now_iso = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            # Sprint 1.10-J commit 7 §X:裸 INSERT 改 AlertsDAO.insert_alert
            from src.data.storage.dao import AlertsDAO
            AlertsDAO.insert_alert(
                conn,
                alert_type="position_health_check",
                severity=severity,
                message=(
                    f"position_health_check: {action}; "
                    f"reason={out.get('reasoning', '')[:120]}"
                ),
                raised_at_utc=now_iso,
                related_run_id=active["thesis_id"],
            )
        except Exception as e:
            logger.warning("position_health_check: write alert failed: %s", e)

        conn.commit()
        return {
            "by_collector": {
                "position_health_check": "ai_evaluated",
                "active_thesis_id": active["thesis_id"],
                "immediate_action": action,
                "thesis_still_valid": out.get("thesis_still_valid"),
            },
            "total_upserted": 1,  # alerts 写一行
            "events_triggered": (
                ["position_health_check_critical"]
                if severity == "critical" else []
            ),
            "errors": {},
            "ai_output": out,
        }

    return _wrap_job(
        "position_health_check", _body, conn_factory=conn_factory,
    )


def _state_from_thesis(active: dict[str, Any]) -> str:
    """根据 thesis.lifecycle_stage + direction 推导 14 档状态。"""
    direction = (active.get("direction") or "").upper()
    stage = (active.get("lifecycle_stage") or "").lower()
    if direction == "LONG":
        return {
            "planned": "LONG_PLANNED", "opened": "LONG_OPEN",
            "holding": "LONG_HOLD", "trim": "LONG_TRIM",
            "closed": "FLAT",
        }.get(stage, "LONG_HOLD")
    if direction == "SHORT":
        return {
            "planned": "SHORT_PLANNED", "opened": "SHORT_OPEN",
            "holding": "SHORT_HOLD", "trim": "SHORT_TRIM",
            "closed": "FLAT",
        }.get(stage, "SHORT_HOLD")
    return "FLAT"


# ============================================================
# Sprint 1.10-H:weekly_review cron job(每周日 22:00 BJT)
# ============================================================

def job_weekly_review(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """v1.4 §3.3.9 + §8.1:周复盘 AI 自动跑。

    流程:
      1. build_weekly_review_input(conn) → 7 类聚合 dict
      2. WeeklyReviewAnalyst.analyze(input) → 5 段 JSON
      3. normalize_output(out) 补漏 V
      4. UPSERT weekly_reviews 表(PK = week_start_utc 周一 UTC,幂等)
      5. critical_count = count_critical_recommendations(out)
      6. 写 alerts(severity = critical_count > 0 ? 'critical' : 'info';
         alert_type='weekly_review' 或 'weekly_review_critical_recommendation')

    triggered_at_utc = now;week_start_utc = 周一 00:00 UTC of the most recent Monday before now。
    """
    def _body(conn: Any) -> dict[str, Any]:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        import json as _json
        from src.ai.agents.weekly_review_analyst import WeeklyReviewAnalyst
        from src.ai.client import build_anthropic_client
        from src.ai.weekly_review_input_builder import build_weekly_review_input

        now = _dt.now(_tz.utc)
        # week_start_utc = 周一 00:00 UTC(Python weekday: Mon=0, Sun=6)
        days_since_monday = now.weekday()
        monday = (now - _td(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        week_start_iso = monday.strftime("%Y-%m-%d")
        triggered_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. 聚合输入
        try:
            inp = build_weekly_review_input(conn, now_utc=now, window_days=7)
        except Exception as e:
            logger.warning("weekly_review: input_builder raised: %s", e)
            return {
                "by_collector": {"weekly_review": "input_builder_failed"},
                "total_upserted": 0,
                "events_triggered": [],
                "errors": {"input_builder": str(e)[:200]},
            }

        # 2. 调 AI(失败 fallback)
        agent = WeeklyReviewAnalyst()
        try:
            out = agent.analyze(inp, client=build_anthropic_client())
        except Exception as e:
            logger.warning("weekly_review: agent raised: %s", e)
            out = agent._fallback_output()

        # 3. normalize 补漏 V
        out = WeeklyReviewAnalyst.normalize_output(out)
        if isinstance(out, dict) and "sample_base" not in out:
            sample_base = (
                inp.get("sample_base")
                or (inp.get("hard_constraint_activation_raw") or {}).get("sample_base")
            )
            if sample_base:
                out["sample_base"] = sample_base
        if isinstance(out, dict):
            for diag_key in (
                "l3_diagnostics",
                "l4_diagnostics",
                "validator_diagnostics",
                "temporal_consistency_diagnostics",
            ):
                if diag_key not in out and inp.get(diag_key) is not None:
                    out[diag_key] = inp[diag_key]

        # 4. UPSERT weekly_reviews
        critical_count = WeeklyReviewAnalyst.count_critical_recommendations(out)
        high_priority_count = WeeklyReviewAnalyst.count_high_priority_recommendations(out)
        out_json = _json.dumps(out, ensure_ascii=False)
        try:
            conn.execute(
                "INSERT INTO weekly_reviews "
                "(week_start_utc, triggered_at_utc, output_json, "
                " critical_count, notification_sent) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(week_start_utc) DO UPDATE SET "
                "  triggered_at_utc = excluded.triggered_at_utc, "
                "  output_json = excluded.output_json, "
                "  critical_count = excluded.critical_count",
                (week_start_iso, triggered_iso, out_json, critical_count, 0),
            )
        except Exception as e:
            logger.warning("weekly_review: upsert weekly_reviews failed: %s", e)

        # 5. 写 alerts(D1=a)
        severity = "critical" if critical_count > 0 else (
            "warning" if high_priority_count > 0 else "info"
        )
        alert_type = (
            "weekly_review_critical_recommendation"
            if critical_count > 0 else "weekly_review"
        )
        msg = (
            f"weekly_review {week_start_iso} 完成:"
            f"critical_count={critical_count};"
            f"high_priority_count={high_priority_count};"
            f"weekly_pnl_pct="
            f"{(out.get('performance_summary') or {}).get('weekly_pnl_pct', 'N/A')}"
        )
        try:
            # Sprint 1.10-J commit 7 §X:裸 INSERT 改 AlertsDAO.insert_alert
            from src.data.storage.dao import AlertsDAO
            AlertsDAO.insert_alert(
                conn,
                alert_type=alert_type, severity=severity, message=msg,
                raised_at_utc=triggered_iso, related_run_id=None,
            )
        except Exception as e:
            logger.warning("weekly_review: write alert failed: %s", e)

        conn.commit()
        return {
            "by_collector": {
                "weekly_review": "completed",
                "week_start_utc": week_start_iso,
                "critical_count": critical_count,
                "high_priority_count": high_priority_count,
                "ai_status": out.get("status", "unknown"),
            },
            "total_upserted": 1,
            "events_triggered": (
                ["weekly_review_critical_recommendation"]
                if critical_count > 0 else []
            ),
            "errors": {},
        }

    return _wrap_job(
        "weekly_review", _body, conn_factory=conn_factory,
    )


# ============================================================
# Sprint H Part A(2026-05-09):weekly_review 加 retry
#   设计:复用 ai_retry 配置(30/60/60 + 3h 窗口,Sprint F.2)。
#   时间表:周日 22:00 主跑失败 → 22:30 / 23:30 / 0:30 三次重试 → 1:00 放弃,
#   等下周日 22:00。跨日不补救(一周一次任务,跨日补救扰乱节奏)。
# ============================================================

def _enqueue_weekly_review(
    *,
    delay_sec: int,
    attempt: int,
    retry_start_utc: Optional[str] = None,
) -> bool:
    """schedule weekly_review_with_retry 在 delay_sec 后再跑(date trigger)。

    Returns:
        True 调度成功;False 无 _active_scheduler(单测 / 直调路径)。
    """
    sched = _active_scheduler
    if sched is None:
        logger.info(
            "weekly_review retry: no active scheduler "
            "(test/direct-invoke path),attempt=%d not enqueued",
            attempt,
        )
        return False
    try:
        from datetime import datetime, timedelta, timezone
        run_date = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
        sched.add_job(
            func=job_weekly_review_with_retry,
            trigger="date",
            run_date=run_date,
            kwargs={
                "attempt": attempt,
                "retry_start_utc": retry_start_utc,
            },
            id=f"weekly_review_retry_{attempt}_{run_date.isoformat()}",
            replace_existing=True,
        )
        logger.info(
            "weekly_review retry enqueued: attempt=%d run_date=%s",
            attempt, run_date.isoformat(),
        )
        return True
    except Exception as e:
        logger.warning("_enqueue_weekly_review failed: %s", e)
        return False


def job_weekly_review_with_retry(
    *,
    attempt: int = 1,
    retry_start_utc: Optional[Any] = None,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    """job_weekly_review 包装 + RetryPolicy 异步重试(共享 ai_retry 间隔)。

    Sprint H Part A(2026-05-09):
      - 共享 base.yaml::ai_retry.intervals_minutes ([30, 60, 60])
      - 但 max_attempts_per_layer=4 覆盖(允许 main + 3 retry,匹配用户
        spec "22:30 / 23:30 / 0:30 三次重试")
      - compute_backoff_seconds(attempt) 用 attempt 直接索引(intervals[0]=30
        作首次 retry,intervals[1]=60 第二次,intervals[2]=60 第三次)
      - 与 pipeline_run_with_retry 不同(pipeline 用 attempt+1,实际 main
        + 2 retry);理由:pipeline 一天一次窗口短可只 2 retry,
        weekly 一周一次需更长抢救窗口

    时间表(BJT 22:00 main 失败):
      22:00 main fail (attempt=1)
      22:30 retry 1     (attempt=2,+30min = intervals[0])
      23:30 retry 2     (attempt=3,+60min = intervals[1])
      0:30  retry 3     (attempt=4,+60min = intervals[2])
      1:00  exhausted   (3h 窗口 + max_attempts=4 双重收敛)

    流程:
      1. 调 job_weekly_review()
      2. 若 ai_status startswith 'degraded' 或 input_builder_failed:
         - attempt+1 ≤ 4 且 in 3h 窗口 → schedule 同 job
         - 否则 → 放弃,result 标 retry_exhausted
      3. 成功 → 直接返回(注意:job_weekly_review 即使 AI 失败也写 fallback,
         retry 下次 UPSERT 覆盖)
    """
    from datetime import datetime, timezone
    from src.ai.retry_policy import RetryPolicy

    result = job_weekly_review(conn_factory=conn_factory)

    # 判定:AI 失败 OR input builder 失败
    by_collector = result.get("by_collector") or {}
    ai_status = str(by_collector.get("ai_status") or "")
    failed = (
        ai_status.startswith("degraded")
        or "input_builder_failed" in by_collector.values()
        or result.get("status") in ("error", "fatal_error")
    )
    if not failed:
        return result

    # max_attempts=4 覆盖:1 main + 3 retry
    rp = RetryPolicy(max_attempts_per_layer=4)
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if retry_start_utc is None:
        retry_start_utc = now_iso

    if not rp.should_retry(
        attempt=attempt + 1,
        run_started_at_utc=str(retry_start_utc),
        now_utc=now_iso,
    ):
        logger.error(
            "weekly_review RETRY EXHAUSTED: attempt=%d "
            "(超 max_attempts=4 或超 %.1fh 窗口)",
            attempt, rp.total_window_hours,
        )
        result["retry_exhausted"] = True
        result["retry_attempts"] = attempt
        return result

    # compute_backoff_seconds(attempt) — attempt=1 main fail → intervals[0]=30min
    backoff = rp.compute_backoff_seconds(attempt)
    logger.warning(
        "weekly_review failed (attempt %d, ai_status=%s), "
        "scheduling retry in %ds (attempt %d)",
        attempt, ai_status, backoff, attempt + 1,
    )
    enq = _enqueue_weekly_review(
        delay_sec=backoff,
        attempt=attempt + 1,
        retry_start_utc=retry_start_utc,
    )
    result["retry_scheduled"] = enq
    result["retry_next_attempt"] = attempt + 1
    result["retry_next_delay_sec"] = backoff
    return result


_JOB_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "pipeline_run": job_pipeline_run,  # 单测/直调入口,生产 yaml 用下面 2 个 wrapper
    # Sprint 2.7-C:pipeline 2 个 wrapper(对应 yaml 2 个 cron 条目)
    "pipeline_run_regular": job_pipeline_run_regular,
    "pipeline_run_8h_onchain": job_pipeline_run_8h_onchain,
    "layer_a_spot_strategy": job_layer_a_spot_strategy,
    # Sprint 1.10-G:RetryPolicy 异步 wrapper(D3=a,event 触发的 pipeline_run 走它)
    "pipeline_run_with_retry": job_pipeline_run_with_retry,
    # Sprint 2.7-A/B:5 个 collector + event_listener(2.7-D 已完整实施 +
    # 1.5q 修注释:event_listener 真在跑,4 类 event 都通,但生产 30d 0 触发
    # 是因为 ±3% 24h 阈值在中长期波段并非高频信号 — 详见 sprint_1_5q.md A.1)
    "collect_klines_1h": job_collect_klines_1h,
    "collect_klines_daily": job_collect_klines_daily,
    "collect_klines_weekly": job_collect_klines_weekly,
    "collect_macro": job_collect_macro,
    "collect_onchain": job_collect_onchain,
    "event_listener": job_event_listener,
    # Sprint 1.10-G v1.4 §10.4.1 新增 2 个独立 cron job
    "hard_invalidation_monitor": job_hard_invalidation_monitor,
    "position_health_check": job_position_health_check,
    # Sprint 1.10-H v1.4 §3.3.9 + §8.1 周复盘 cron(每周日 22:00 BJT)
    # Sprint H Part A(2026-05-09):生产 yaml 用 retry wrapper;
    # job_weekly_review 单独保留供单测 / 直调
    "weekly_review": job_weekly_review_with_retry,
    "weekly_review_no_retry": job_weekly_review,   # 单测直调入口
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
