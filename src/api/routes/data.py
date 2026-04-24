"""GET /api/data/summary — 各数据源最新时间戳概览。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..models import DataSourceSummary, DataSummaryResponse


router = APIRouter(prefix="/data", tags=["data"])


_TABLES: tuple[tuple[str, str, str], ...] = (
    # (display name, table, timestamp column)
    ("btc_klines", "btc_klines", "timestamp"),
    ("derivatives_snapshot", "derivatives_snapshot", "timestamp"),
    ("onchain_snapshot", "onchain_snapshot", "timestamp"),
    ("macro_snapshot", "macro_snapshot", "timestamp"),
    ("events_calendar", "events_calendar", "utc_trigger_time"),
    ("strategy_state_history", "strategy_state_history", "run_timestamp_utc"),
    ("fallback_log", "fallback_log", "run_timestamp_utc"),
    ("run_metadata", "run_metadata", "run_timestamp_utc"),
)


@router.get("/summary", response_model=DataSummaryResponse)
def get_data_summary(request: Request) -> DataSummaryResponse:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    sources: list[DataSourceSummary] = []
    try:
        for name, table, ts_col in _TABLES:
            try:
                latest_row = conn.execute(
                    f"SELECT MAX({ts_col}) AS latest FROM {table}"
                ).fetchone()
                count_row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"
                ).fetchone()
                latest = latest_row["latest"] if latest_row else None
                count = int(count_row["n"]) if count_row else 0
            except Exception:
                latest, count = None, 0
            sources.append(DataSourceSummary(
                name=name,
                latest_timestamp_utc=latest,
                row_count=count,
            ))
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return DataSummaryResponse(sources=sources)
