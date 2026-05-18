"""src/data/freshness.py — Sprint D(2026-05-08)

「数据真实性透明化」共用查询模块 — 给 4 个数据源算出 dual-source freshness:
fetch_attempts(Sprint A 引入)是首选信号;若该 source 还没有 success 行,
fallback 到实际数据表 MAX(captured_at_utc / open_time_utc / inserted_at_utc)。

被多处消费:
  - src/api/routes/data_sources.py        网页"数据源"那栏
  - src/api/routes/system.py              evidence_layers 显示侧 stale 覆盖
  - src/pipeline/state_builder.py         state.data_freshness 块
  - src/ai/master_input_builder.py(若需要)→ master_adjudicator prompt 注入

Stale 阈值(每源不同):
  - binance_kline:        > 3 小时(K 线 1h 频率,容忍 3 倍)
  - coinglass_derivatives:> 3 小时
  - glassnode_onchain:    > 48 小时(沿用 Sprint C 派生指标守卫常量)
  - fred_macro:           > 72 小时(日级数据,周末不更新)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

# 4 个固定 source label —— jobs.py:_record_fetch_attempt 的写入点
EXPECTED_SOURCES: tuple[tuple[str, str], ...] = (
    ("binance_kline", "Binance K 线"),
    ("coinglass_derivatives", "CoinGlass 衍生品"),
    ("glassnode_onchain", "Glassnode 链上"),
    ("fred_macro", "FRED 宏观"),
)


# 各源 stale 阈值(秒)
STALE_THRESHOLD_SECONDS: dict[str, int] = {
    "binance_kline":         3 * 3600,
    "coinglass_derivatives": 3 * 3600,
    "glassnode_onchain":    48 * 3600,
    "fred_macro":           72 * 3600,
}


# 每源 ↔ 数据表 + 时间戳列 的 fallback 映射(success 行缺失时查询)
# 用 inserted_at_utc 而非 captured_at_utc 因为前者反映"何时写入"(对应"何时
# 抓取到"),后者只是 bar 数据的日期(daily bar 比抓取时间老 8-24 小时正常)。
# glassnode_onchain / fred_macro 加 source 过滤,排除派生。
_FALLBACK_QUERIES: dict[str, str] = {
    "binance_kline": (
        "SELECT MAX(inserted_at_utc) FROM price_candles "
        "WHERE timeframe = '1h' AND symbol = 'BTCUSDT'"
    ),
    "coinglass_derivatives": (
        "SELECT MAX(inserted_at_utc) FROM derivatives_snapshots"
    ),
    "glassnode_onchain": (
        "SELECT MAX(inserted_at_utc) FROM onchain_metrics "
        "WHERE source IN ('glassnode_primary','glassnode_display',"
        "                 'glassnode_derived_breakdown_by_age')"
    ),
    "fred_macro": (
        "SELECT MAX(inserted_at_utc) FROM macro_metrics "
        "WHERE source = 'fred'"
    ),
}


_FAILURE_REASON_LABELS: dict[str, str] = {
    "partial_failure": "部分异常",
    "quota_exceeded": "配额用尽",
    "rate_limited": "瞬时限流",
    "auth_error": "API key 无效 / 未授权",
    "permission_denied": "套餐不支持 / 权限不足",
    "endpoint_not_found": "接口不存在 / 配置错误",
    "provider_error": "服务异常",
    "timeout": "请求超时",
    "network_error": "网络错误",
    "api_error": "API 错误",
    "parse_error": "数据格式错误",
    "unknown": "未知错误",
}

_GLASSNODE_HEALTH_CACHE_PATH = (
    Path.home() / "pipeline_logs" / "glassnode_health_check_latest.json"
)

_HTTP_PATTERN = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)
_ENDPOINT_PATTERN = re.compile(r"(/v1/metrics/[^\s'\";}]+)")
_METRIC_ON_PATTERN = re.compile(r"\bon\s+([a-z][a-z0-9_]+)\b", re.IGNORECASE)

_METRIC_DISPLAY_NAMES: dict[str, str] = {
    "puell_multiple": "Puell Multiple",
    "mvrv": "MVRV",
    "lth_sopr": "LTH SOPR",
    "sth_sopr": "STH SOPR",
    "reserve_risk": "Reserve Risk",
    "rhodl_ratio": "RHODL Ratio",
}

_METRIC_ENDPOINTS: dict[str, str] = {
    "puell_multiple": "/v1/metrics/indicators/puell_multiple",
    "mvrv": "/v1/metrics/market/mvrv",
    "lth_sopr": "/v1/metrics/indicators/sopr_more_155",
    "sth_sopr": "/v1/metrics/indicators/sopr_less_155",
    "reserve_risk": "/v1/metrics/indicators/reserve_risk",
    "rhodl_ratio": "/v1/metrics/indicators/rhodl_ratio",
}


# 哪些 evidence 层依赖哪些 source(显示侧 stale 覆盖用)
LAYER_SOURCE_DEPS: dict[int, tuple[str, ...]] = {
    1: ("binance_kline",),                              # L1 价格 / regime
    2: ("binance_kline", "glassnode_onchain"),          # L2 方向结构
    3: (),                                               # L3 衍生(L1/L2 联动)
    4: ("coinglass_derivatives", "glassnode_onchain"),  # L4 衍生品 + onchain
    5: ("fred_macro",),                                 # L5 宏观
}


# ============================================================
# Dataclass
# ============================================================

@dataclass(frozen=True)
class SourceFreshness:
    source: str
    display_name: str
    status: str                          # 'success' | 'partial' | 'failure' | 'no_data'
    last_attempt_at_utc: Optional[str]
    last_success_at_utc: Optional[str]
    minutes_since_last_attempt: Optional[int]
    hours_since_last_success: Optional[float]
    is_stale: bool
    failure_reason: Optional[str]
    failure_reason_label: Optional[str]
    error_message: Optional[str]
    rows_upserted: Optional[int]
    duration_ms: Optional[int]
    last_success_source: Optional[str]   # 'fetch_attempts' | 'data_table' | None
    display_label: Optional[str] = None
    main_failure_metric: Optional[str] = None
    main_failure_metric_label: Optional[str] = None
    main_failure_endpoint: Optional[str] = None
    main_failure_http_status: Optional[int] = None
    main_failure_age_label: Optional[str] = None
    latest_success_after_failure: bool = False
    recovered: bool = False


# ============================================================
# 内部
# ============================================================

def _parse_iso(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def _query_latest_attempt(conn: Any, source: str) -> Optional[Any]:
    return conn.execute(
        "SELECT attempted_at_utc, status, failure_reason, error_message, "
        "       rows_upserted, duration_ms "
        "FROM fetch_attempts WHERE source = ? "
        "ORDER BY attempted_at_utc DESC, id DESC LIMIT 1",
        (source,),
    ).fetchone()


def _query_latest_success(conn: Any, source: str) -> Optional[str]:
    row = conn.execute(
        "SELECT attempted_at_utc FROM fetch_attempts "
        "WHERE source = ? AND status = 'success' "
        "ORDER BY attempted_at_utc DESC, id DESC LIMIT 1",
        (source,),
    ).fetchone()
    return row[0] if row else None


def _query_data_table_max(conn: Any, source: str) -> Optional[str]:
    sql = _FALLBACK_QUERIES.get(source)
    if not sql:
        return None
    try:
        row = conn.execute(sql).fetchone()
        return row[0] if row and row[0] else None
    except Exception as e:
        logger.warning("freshness fallback query for %s failed: %s", source, e)
        return None


def _latest_success_candidate(
    fetch_success_iso: Optional[str],
    data_table_iso: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Pick the freshest success signal from fetch_attempts and real data table."""
    best_iso: Optional[str] = None
    best_dt: Optional[datetime] = None
    best_source: Optional[str] = None
    for value, source in (
        (fetch_success_iso, "fetch_attempts"),
        (data_table_iso, "data_table"),
    ):
        dt = _parse_iso(value)
        if dt is None:
            continue
        if best_dt is None or dt > best_dt:
            best_iso = value
            best_dt = dt
            best_source = source
    return best_iso, best_source


def _metric_label(metric: Optional[str]) -> Optional[str]:
    if not metric:
        return None
    return _METRIC_DISPLAY_NAMES.get(
        metric, metric.replace("_", " ").title()
    )


def _age_label(minutes: Optional[int]) -> Optional[str]:
    if minutes is None:
        return None
    if minutes < 60:
        return f"{minutes} 分钟前"
    if minutes < 1440:
        return f"{minutes / 60:.1f} 小时前"
    return f"{minutes / 1440:.1f} 天前"


def _extract_failure_detail(error_message: Optional[str]) -> dict[str, Any]:
    text = error_message or ""
    http_match = _HTTP_PATTERN.search(text)
    endpoint_match = _ENDPOINT_PATTERN.search(text)
    endpoint = endpoint_match.group(1) if endpoint_match else None
    metric = endpoint.rsplit("/", 1)[-1] if endpoint else None
    if metric is None:
        metric_match = _METRIC_ON_PATTERN.search(text)
        metric = metric_match.group(1) if metric_match else None
    if endpoint is None and metric:
        endpoint = _METRIC_ENDPOINTS.get(metric)
    http_status = int(http_match.group(1)) if http_match else None
    return {
        "metric": metric,
        "metric_label": _metric_label(metric),
        "endpoint": endpoint,
        "http_status": http_status,
    }


def _query_metric_latest_inserted(conn: Any, metric: Optional[str]) -> Optional[str]:
    if not metric:
        return None
    try:
        row = conn.execute(
            "SELECT MAX(inserted_at_utc) FROM onchain_metrics "
            "WHERE metric_name = ? "
            "  AND source IN ('glassnode_primary','glassnode_display',"
            "                 'glassnode_derived_breakdown_by_age')",
            (metric,),
        ).fetchone()
        return row[0] if row and row[0] else None
    except Exception as e:
        logger.warning("metric recovery query for %s failed: %s", metric, e)
        return None


def _read_glassnode_health_cache() -> dict[str, Any]:
    try:
        if not _GLASSNODE_HEALTH_CACHE_PATH.exists():
            return {}
        return json.loads(_GLASSNODE_HEALTH_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("glassnode health cache read failed: %s", e)
        return {}


def _health_cache_recovered(
    detail: dict[str, Any],
    *,
    failure_dt: Optional[datetime],
) -> bool:
    if failure_dt is None:
        return False
    metric = detail.get("metric")
    endpoint = detail.get("endpoint")
    if not metric and not endpoint:
        return False
    cache = _read_glassnode_health_cache()
    generated_at = _parse_iso(cache.get("generated_at_utc"))
    if generated_at is None or generated_at <= failure_dt:
        return False
    for check in cache.get("checks", []) or []:
        if check.get("status") != "ok" or not check.get("latest_value_present"):
            continue
        if metric and check.get("metric") == metric:
            return True
        if endpoint and check.get("endpoint") == endpoint:
            return True
    return False


# ============================================================
# Public API
# ============================================================

def compute_source_freshness(
    conn: Any,
    source: str,
    *,
    now: Optional[datetime] = None,
) -> SourceFreshness:
    """单 source freshness:fetch_attempts 优先,fallback 到数据表 MAX。"""
    display_name = dict(EXPECTED_SOURCES).get(source, source)
    now = now or datetime.now(timezone.utc)

    latest = _query_latest_attempt(conn, source)
    if latest is None:
        # 完全没 attempt 记录 → fallback 到数据表
        fallback_iso = _query_data_table_max(conn, source)
        last_dt = _parse_iso(fallback_iso)
        hours = ((now - last_dt).total_seconds() / 3600.0
                 if last_dt is not None else None)
        is_stale = bool(
            hours is not None
            and hours * 3600.0 > STALE_THRESHOLD_SECONDS[source]
        )
        if hours is None:
            is_stale = True
        return SourceFreshness(
            source=source, display_name=display_name,
            status="no_data",
            last_attempt_at_utc=None,
            last_success_at_utc=fallback_iso,
            minutes_since_last_attempt=None,
            hours_since_last_success=hours,
            is_stale=is_stale,
            failure_reason=None,
            failure_reason_label=None,
            error_message=None,
            rows_upserted=None,
            duration_ms=None,
            last_success_source="data_table" if fallback_iso else None,
        )

    last_attempt_at_utc = latest["attempted_at_utc"]
    status = latest["status"]
    last_attempt_dt = _parse_iso(last_attempt_at_utc)
    minutes_since_attempt = (
        int(round((now - last_attempt_dt).total_seconds() / 60.0))
        if last_attempt_dt is not None else None
    )
    detail = _extract_failure_detail(
        latest["error_message"] if status == "failure" else None
    )

    # 算 last_success_at_utc:
    #   - status=success → 自己
    #   - status=failure → 历史 fetch_attempts success / 数据表 fallback 取更新者
    last_success_at_utc: Optional[str]
    last_success_source: Optional[str]
    if status == "success":
        last_success_at_utc = last_attempt_at_utc
        last_success_source = "fetch_attempts"
    else:
        succ = _query_latest_success(conn, source)
        fallback_iso = _query_data_table_max(conn, source)
        last_success_at_utc, last_success_source = _latest_success_candidate(
            succ, fallback_iso
        )

    last_success_dt = _parse_iso(last_success_at_utc)
    hours_since_last_success = (
        (now - last_success_dt).total_seconds() / 3600.0
        if last_success_dt is not None else None
    )
    is_stale = bool(
        hours_since_last_success is not None
        and hours_since_last_success * 3600.0
        > STALE_THRESHOLD_SECONDS[source]
    )
    if hours_since_last_success is None:
        is_stale = True

    rows_upserted = latest["rows_upserted"]
    effective_status = status
    recovered = False
    latest_success_after_failure = False
    if status == "failure" and not is_stale:
        metric_success_dt = _parse_iso(
            _query_metric_latest_inserted(conn, detail.get("metric"))
        )
        if (
            metric_success_dt is not None
            and last_attempt_dt is not None
            and metric_success_dt > last_attempt_dt
        ):
            latest_success_after_failure = True
            recovered = True
            effective_status = "success"
        elif _health_cache_recovered(detail, failure_dt=last_attempt_dt):
            latest_success_after_failure = True
            recovered = True
            effective_status = "success"
        # 同一轮 Glassnode 已经写入数据,说明是"部分 endpoint 失败",
        # 不应让一个单点失败把整个 Glassnode 源显示成全源失败/配额用尽。
        elif rows_upserted and rows_upserted > 0:
            effective_status = "partial"
        else:
            last_success_dt_for_cmp = _parse_iso(last_success_at_utc)
            if (
                last_success_dt_for_cmp is not None
                and last_attempt_dt is not None
                and last_success_dt_for_cmp > last_attempt_dt
            ):
                effective_status = "success"
                latest_success_after_failure = True
                recovered = True

    failure_reason = (
        latest["failure_reason"]
        if effective_status in {"failure", "partial"} else None
    )
    if effective_status == "partial":
        failure_reason_label = _FAILURE_REASON_LABELS["partial_failure"]
    else:
        failure_reason_label = (
            _FAILURE_REASON_LABELS.get(failure_reason, _FAILURE_REASON_LABELS["unknown"])
            if failure_reason else None
        )
    display_label = failure_reason_label
    if effective_status == "partial":
        metric_label = detail.get("metric_label") or "未知指标"
        http_status = detail.get("http_status")
        suffix = f" {http_status}" if http_status else ""
        display_label = f"部分异常：{metric_label}{suffix}"

    return SourceFreshness(
        source=source, display_name=display_name,
        status=effective_status,
        last_attempt_at_utc=last_attempt_at_utc,
        last_success_at_utc=last_success_at_utc,
        minutes_since_last_attempt=minutes_since_attempt,
        hours_since_last_success=hours_since_last_success,
        is_stale=is_stale,
        failure_reason=failure_reason,
        failure_reason_label=failure_reason_label,
        error_message=(
            latest["error_message"] if effective_status in {"failure", "partial"} else None
        ),
        rows_upserted=rows_upserted,
        duration_ms=latest["duration_ms"],
        last_success_source=last_success_source,
        display_label=display_label,
        main_failure_metric=detail.get("metric"),
        main_failure_metric_label=detail.get("metric_label"),
        main_failure_endpoint=detail.get("endpoint"),
        main_failure_http_status=detail.get("http_status"),
        main_failure_age_label=_age_label(minutes_since_attempt),
        latest_success_after_failure=latest_success_after_failure,
        recovered=recovered,
    )


def compute_all_freshness(
    conn: Any, *, now: Optional[datetime] = None,
) -> list[SourceFreshness]:
    """4 个固定 source 全部计算,顺序 = EXPECTED_SOURCES。"""
    now = now or datetime.now(timezone.utc)
    return [
        compute_source_freshness(conn, src, now=now)
        for src, _ in EXPECTED_SOURCES
    ]


def stale_summary_for_layer(
    layer_id: int, all_freshness: list[SourceFreshness],
) -> list[str]:
    """给一个 layer_id,返回该层依赖的 source 中 is_stale=True 的人读句子。
    用于 evidence_layers.missing_reasons / state.data_freshness 显示侧覆盖。
    """
    deps = LAYER_SOURCE_DEPS.get(layer_id, ())
    if not deps:
        return []
    by_source = {f.source: f for f in all_freshness}
    out: list[str] = []
    for src in deps:
        f = by_source.get(src)
        if f is None or not f.is_stale:
            continue
        if f.hours_since_last_success is None:
            out.append(f"依赖的 {f.display_name} 数据从未成功抓取过")
        else:
            out.append(
                f"依赖的 {f.display_name} 数据已过期 "
                f"{f.hours_since_last_success:.1f} 小时"
            )
    return out


def compute_stale_state(conn: Any) -> tuple[dict[str, bool], dict[str, float]]:
    """Sprint E Step 3:批量算 stale_map + hours_map(orchestrator 喂 sub-agent
    用)。stale_map = {source: is_stale};hours_map = {source: hours_since_last
    _success}(None 时填 0.0)。"""
    rows = compute_all_freshness(conn)
    stale_map: dict[str, bool] = {}
    hours_map: dict[str, float] = {}
    for f in rows:
        stale_map[f.source] = f.is_stale
        hours_map[f.source] = (
            f.hours_since_last_success
            if f.hours_since_last_success is not None else 0.0
        )
    return stale_map, hours_map


def freshness_to_dict(f: SourceFreshness) -> dict[str, Any]:
    """SourceFreshness → dict(用于 JSON / state.data_freshness 持久化)。"""
    return {
        "source": f.source,
        "display_name": f.display_name,
        "status": f.status,
        "last_attempt_at_utc": f.last_attempt_at_utc,
        "last_success_at_utc": f.last_success_at_utc,
        "minutes_since_last_attempt": f.minutes_since_last_attempt,
        "hours_since_last_success": (
            round(f.hours_since_last_success, 2)
            if f.hours_since_last_success is not None else None
        ),
        "is_stale": f.is_stale,
        "failure_reason": f.failure_reason,
        "failure_reason_label": f.failure_reason_label,
        "error_message": f.error_message,
        "rows_upserted": f.rows_upserted,
        "duration_ms": f.duration_ms,
        "last_success_source": f.last_success_source,
        "display_label": f.display_label,
        "main_failure_metric": f.main_failure_metric,
        "main_failure_metric_label": f.main_failure_metric_label,
        "main_failure_endpoint": f.main_failure_endpoint,
        "main_failure_http_status": f.main_failure_http_status,
        "main_failure_age_label": f.main_failure_age_label,
        "latest_success_after_failure": f.latest_success_after_failure,
        "recovered": f.recovered,
    }
