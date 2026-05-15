"""
api/models.py — Pydantic schemas for FastAPI responses.

只声明外部响应用的精简模型,不复用 pipeline 内部 dict
(pipeline 内部 state 字段太杂,API 以 dict 形式透传即可)。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(..., description="ok / degraded")
    version: str
    uptime_seconds: float
    db_accessible: bool
    preflight_alerts_24h: int = Field(
        0,
        description="Sprint 2.8-B:最近 24h pre_flight_degraded alerts 数量",
    )
    scheduler_running: bool = Field(
        False,
        description="Sprint 2.8-D:APScheduler 实例是否还活着",
    )
    scheduler_jobs_count: int = Field(
        0,
        description="Sprint 2.8-D:已注册的 cron job 数(scheduler 不活时为 0)",
    )
    review_pending: dict[str, Any] | None = Field(
        None,
        description=(
            "Sprint 1.10-I D2=a:review_pending 状态(active / reason / "
            "entered_at_utc / state_id)。无 active 时为 null。前端健康灯组件 + "
            "RP 红色横幅复用此字段。"
        ),
    )


class StrategyStateRow(BaseModel):
    run_timestamp_utc: str
    run_id: str
    run_trigger: str
    rules_version: str
    ai_model_actual: str | None = None
    state: dict[str, Any]
    created_at: str | None = None


class HistoryPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[StrategyStateRow]


class TriggerResponse(BaseModel):
    status: str
    run_id: str
    run_timestamp_utc: str
    persisted: bool
    ai_status: str
    duration_ms: int
    degraded_stages: list[str]
    failure_count: int


class FallbackLogItem(BaseModel):
    id: int | None = None
    run_timestamp_utc: str
    fallback_level: str
    triggered_by: str
    details: dict[str, Any] | None = None
    created_at: str | None = None


class FallbackLogPage(BaseModel):
    limit: int
    items: list[FallbackLogItem]


class DataSourceSummary(BaseModel):
    name: str
    latest_timestamp_utc: str | None = None
    row_count: int = 0


class DataSummaryResponse(BaseModel):
    sources: list[DataSourceSummary]


# Sprint 1.5n:系统自检面板
class HealthDetailEvidenceLayer(BaseModel):
    layer_id: int
    name: str
    health: str  # healthy / degraded / missing
    pillars_summary: str
    missing_reasons: list[str] = Field(default_factory=list)


class HealthDetailDataSource(BaseModel):
    name: str
    status: str  # ok / warn / critical / no_data
    age_minutes: float | None = None
    captured_at_bjt: str | None = None
    expected_cadence: str


class HealthDetailResponse(BaseModel):
    evidence_layers: list[HealthDetailEvidenceLayer]
    data_sources: list[HealthDetailDataSource]
    overall_status: str  # all_healthy / partial_degraded / critical


# Sprint B(数据真实性透明化)— /api/data_sources/freshness
class DataSourceFreshness(BaseModel):
    source: str                         # binance_kline / coinglass_derivatives / glassnode_onchain / fred_macro
    display_name: str                   # 中文展示名(网页直接显示)
    status: str                         # 'success' | 'partial' | 'failure' | 'no_data'
    last_attempt_at_utc: str | None = None
    last_attempt_at_bjt: str | None = None
    minutes_ago: int | None = None      # 距最近一次 attempt 的分钟数
    last_success_at_utc: str | None = None
    last_success_at_bjt: str | None = None
    failure_reason: str | None = None   # quota_exceeded / network_error / ...
    failure_reason_label: str | None = None   # 中文徽章
    error_message: str | None = None
    rows_upserted: int | None = None
    duration_ms: int | None = None
