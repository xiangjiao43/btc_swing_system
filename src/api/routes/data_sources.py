"""Sprint B(数据真实性)+ Sprint D(fallback 文案根治)—— /api/data_sources/freshness。

Sprint A:每次 collector 抓取写一行 fetch_attempts。
Sprint B:网页"数据源"那栏读这个 endpoint 真实显示。
Sprint D:加 fallback —— fetch_attempts 没 success 行时,从实际数据表 MAX 取
        last_success_at,网页文案不再「从未成功过」/「尚未抓取」,改「沿用 X 月
        X 日数据」。逻辑统一搬到 src/data/freshness.py 共用模块。
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

from ...data.freshness import EXPECTED_SOURCES, compute_all_freshness
from ..models import DataSourceFreshness


router = APIRouter(prefix="/data_sources", tags=["data_sources"])


_BJT = ZoneInfo("Asia/Shanghai")


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


@router.get("/freshness", response_model=list[DataSourceFreshness])
def get_data_sources_freshness(request: Request) -> list[DataSourceFreshness]:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        now = datetime.now(timezone.utc)
        rows = compute_all_freshness(conn, now=now)
        out: list[DataSourceFreshness] = []
        for f in rows:
            out.append(DataSourceFreshness(
                source=f.source,
                display_name=f.display_name,
                status=f.status,
                last_attempt_at_utc=f.last_attempt_at_utc,
                last_attempt_at_bjt=_to_bjt_str(f.last_attempt_at_utc),
                minutes_ago=f.minutes_since_last_attempt,
                last_success_at_utc=f.last_success_at_utc,
                last_success_at_bjt=_to_bjt_str(f.last_success_at_utc),
                failure_reason=f.failure_reason,
                failure_reason_label=f.failure_reason_label,
                error_message=f.error_message,
                rows_upserted=f.rows_upserted,
                duration_ms=f.duration_ms,
            ))
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


# Sprint D 兼容 export(避免外部仍 from src.api.routes.data_sources import _EXPECTED_SOURCES)
_EXPECTED_SOURCES = EXPECTED_SOURCES
