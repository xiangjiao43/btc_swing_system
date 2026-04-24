"""GET /api/data/summary — 各数据源最新时间戳概览。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..models import DataSourceSummary, DataSummaryResponse


router = APIRouter(prefix="/data", tags=["data"])


_TABLES: tuple[tuple[str, str, str], ...] = (
    # (display name, table, timestamp column) — Sprint 1.5c 对齐建模 §10.4
    ("price_candles", "price_candles", "open_time_utc"),
    ("derivatives_snapshots", "derivatives_snapshots", "captured_at_utc"),
    ("onchain_metrics", "onchain_metrics", "captured_at_utc"),
    ("macro_metrics", "macro_metrics", "captured_at_utc"),
    ("events_calendar", "events_calendar", "utc_trigger_time"),
    ("strategy_runs", "strategy_runs", "reference_timestamp_utc"),
    ("fallback_events", "fallback_events", "triggered_at_utc"),
    ("lifecycles", "lifecycles", "entry_time_utc"),
    ("alerts", "alerts", "raised_at_utc"),
    ("kpi_snapshots", "kpi_snapshots", "captured_at_utc"),
    ("evidence_card_history", "evidence_card_history", "captured_at_utc"),
    ("review_reports", "review_reports", "generated_at_utc"),
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
