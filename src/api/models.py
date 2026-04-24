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
