"""Sprint B(数据真实性透明化)—— /api/data_sources/freshness。

读 fetch_attempts 表(Sprint A 引入),给每个数据源返回:
  - 最新 attempt 状态(success / failure / no_data)
  - 最近一次成功时间(失败时网页显示「沿用 X 月 X 日数据」)
  - 失败原因 + 中文徽章 + 完整 error_message(给 hover tooltip)
  - 距今分钟数

不依赖 inserted_at_utc 推断 — 那是 Sprint A 之前的 broken signal,
被 derived_mvrv 这种「上游 fail 但本地仍写行」的副作用骗过。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

from ..models import DataSourceFreshness


router = APIRouter(prefix="/data_sources", tags=["data_sources"])


_BJT = ZoneInfo("Asia/Shanghai")


# 4 个固定 source bucket(jobs.py 里 _record_fetch_attempt 写入的 source label)。
# 顺序就是网页显示顺序。
_EXPECTED_SOURCES: tuple[tuple[str, str], ...] = (
    ("binance_kline", "Binance K 线"),
    ("coinglass_derivatives", "CoinGlass 衍生品"),
    ("glassnode_onchain", "Glassnode 链上"),
    ("fred_macro", "FRED 宏观"),
)


_FAILURE_REASON_LABELS: dict[str, str] = {
    "quota_exceeded": "配额用尽",
    "network_error": "网络错误",
    "api_error": "API 错误",
    "parse_error": "数据格式错误",
    "unknown": "未知错误",
}


def _to_bjt_str(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(_BJT).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _minutes_ago(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        delta = (now - d).total_seconds() / 60.0
        return int(round(delta))
    except Exception:
        return None


def _row_for_source(
    conn: Any, source: str, display_name: str, now: datetime,
) -> DataSourceFreshness:
    """取 source 最新 attempt + 最近一次 success(失败时的「沿用」时间)。"""
    latest = conn.execute(
        "SELECT attempted_at_utc, status, failure_reason, error_message, "
        "       rows_upserted, duration_ms "
        "FROM fetch_attempts WHERE source = ? "
        "ORDER BY attempted_at_utc DESC, id DESC LIMIT 1",
        (source,),
    ).fetchone()

    if latest is None:
        return DataSourceFreshness(
            source=source, display_name=display_name, status="no_data",
        )

    last_attempt_at_utc = latest["attempted_at_utc"]
    status = latest["status"]
    failure_reason = latest["failure_reason"] if status == "failure" else None
    failure_reason_label = (
        _FAILURE_REASON_LABELS.get(failure_reason, _FAILURE_REASON_LABELS["unknown"])
        if failure_reason else None
    )

    last_success_at_utc: str | None
    if status == "success":
        last_success_at_utc = last_attempt_at_utc
    else:
        succ = conn.execute(
            "SELECT attempted_at_utc FROM fetch_attempts "
            "WHERE source = ? AND status = 'success' "
            "ORDER BY attempted_at_utc DESC, id DESC LIMIT 1",
            (source,),
        ).fetchone()
        last_success_at_utc = succ["attempted_at_utc"] if succ else None

    return DataSourceFreshness(
        source=source,
        display_name=display_name,
        status=status,
        last_attempt_at_utc=last_attempt_at_utc,
        last_attempt_at_bjt=_to_bjt_str(last_attempt_at_utc),
        minutes_ago=_minutes_ago(last_attempt_at_utc, now),
        last_success_at_utc=last_success_at_utc,
        last_success_at_bjt=_to_bjt_str(last_success_at_utc),
        failure_reason=failure_reason,
        failure_reason_label=failure_reason_label,
        error_message=latest["error_message"] if status == "failure" else None,
        rows_upserted=latest["rows_upserted"],
        duration_ms=latest["duration_ms"],
    )


@router.get("/freshness", response_model=list[DataSourceFreshness])
def get_data_sources_freshness(request: Request) -> list[DataSourceFreshness]:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        now = datetime.now(timezone.utc)
        return [
            _row_for_source(conn, source, display_name, now)
            for source, display_name in _EXPECTED_SOURCES
        ]
    finally:
        try:
            conn.close()
        except Exception:
            pass
