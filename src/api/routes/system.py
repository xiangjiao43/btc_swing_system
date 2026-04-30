"""建模 §9.10 #9-#10:系统级路由。

  GET /api/system/health         — 系统健康(替代 /api/health;保留老路径 alias)
  GET /api/system/health-detail  — Sprint 1.5n:系统自检面板(5 层 + 数据源)
  POST /api/system/run-now       — 手动触发一次 Pipeline
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from ...pipeline import StrategyStateBuilder
from ..models import (
    HealthDetailDataSource, HealthDetailEvidenceLayer, HealthDetailResponse,
    HealthResponse, TriggerResponse,
)


router = APIRouter(prefix="/system", tags=["system"])


# ---------- GET /api/system/health ----------

def _count_preflight_alerts_24h(conn) -> int:
    """Sprint 2.8-B:最近 24h pre_flight_degraded alerts 数量。"""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM alerts "
        "WHERE alert_type = 'pre_flight_degraded' AND raised_at_utc >= ?",
        (since,),
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row["n"])
    except (TypeError, KeyError, IndexError):
        return int(row[0]) if row else 0


def _scheduler_status(request: Request) -> tuple[bool, int]:
    """Sprint 2.8-D:返回 (running, jobs_count)。

    任何错误 → (False, 0)。
    """
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        return False, 0
    try:
        running = bool(getattr(sched, "running", False))
    except Exception:
        running = False
    if not running:
        return False, 0
    try:
        jobs_count = len(sched.get_jobs())
    except Exception:
        jobs_count = 0
    return True, jobs_count


def _health_impl(request: Request) -> HealthResponse:
    ctx = request.app.state.ctx
    db_ok = False
    preflight_24h = 0
    try:
        conn = ctx.conn_factory()
        try:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
            try:
                preflight_24h = _count_preflight_alerts_24h(conn)
            except Exception:
                preflight_24h = 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        db_ok = False

    sched_running, sched_jobs = _scheduler_status(request)

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=ctx.version,
        uptime_seconds=round(time.time() - ctx.started_at, 3),
        db_accessible=db_ok,
        preflight_alerts_24h=preflight_24h,
        scheduler_running=sched_running,
        scheduler_jobs_count=sched_jobs,
    )


@router.get("/health", response_model=HealthResponse)
def get_system_health(request: Request) -> HealthResponse:
    """§9.10 #9:系统健康。"""
    return _health_impl(request)


# ---------- GET /api/system/health-detail (Sprint 1.5n) ----------

_BJT = ZoneInfo("Asia/Shanghai")

# 数据源新鲜度阈值(分钟)— 后续可挪 thresholds.yaml,留 1.5n.1
_SOURCE_CADENCE: dict[str, dict[str, Any]] = {
    "binance_kline_1h": {
        "label": "Binance K 线 (1h)", "warn": 120, "critical": 360,
        "expected_cadence": "每 1 小时",
    },
    "coinglass_derivatives": {
        "label": "CoinGlass 衍生品",   "warn": 30 * 60, "critical": 48 * 60,
        "expected_cadence": "每日 (daily bar)",
    },
    "glassnode_onchain": {
        "label": "Glassnode 链上",     "warn": 30 * 60, "critical": 72 * 60,
        "expected_cadence": "每日 (daily bar)",
    },
    "yahoo_macro": {
        "label": "Yahoo 宏观",         "warn": 120, "critical": 24 * 60,
        "expected_cadence": "交易日每小时",
    },
    "fred_macro": {
        "label": "FRED 宏观",          "warn": 120, "critical": 24 * 60,
        "expected_cadence": "交易日每小时",
    },
}

_LAYER_NAMES = {
    1: "市场状态层", 2: "方向结构层", 3: "机会执行层",
    4: "风险失效层", 5: "背景事件层",
}


def _to_bjt_str(iso: str) -> str:
    try:
        s = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(_BJT).strftime("%Y-%m-%d %H:%M (BJT)")
    except Exception:
        return iso


def _classify_age(age_min: Optional[float], cfg: dict[str, Any]) -> str:
    if age_min is None:
        return "no_data"
    if age_min >= cfg["critical"]:
        return "critical"
    if age_min >= cfg["warn"]:
        return "warn"
    return "ok"


def _query_data_source_freshness(conn) -> list[HealthDetailDataSource]:
    """各数据源最新一行 inserted_at_utc → age_minutes + status。"""
    now = datetime.now(timezone.utc)
    out: list[HealthDetailDataSource] = []

    queries = [
        ("binance_kline_1h",
         "SELECT MAX(inserted_at_utc) AS ts FROM price_candles "
         "WHERE timeframe = '1h'"),
        ("coinglass_derivatives",
         "SELECT MAX(inserted_at_utc) AS ts FROM derivatives_snapshots"),
        ("glassnode_onchain",
         "SELECT MAX(inserted_at_utc) AS ts FROM onchain_metrics"),
        # 宏观源:macro_metrics 用 source 字段(yfinance / fred)区分
        ("yahoo_macro",
         "SELECT MAX(inserted_at_utc) AS ts FROM macro_metrics "
         "WHERE source LIKE 'yfinance%' OR source LIKE 'yahoo%'"),
        ("fred_macro",
         "SELECT MAX(inserted_at_utc) AS ts FROM macro_metrics "
         "WHERE source = 'fred'"),
    ]

    for source_key, sql in queries:
        cfg = _SOURCE_CADENCE[source_key]
        try:
            row = conn.execute(sql).fetchone()
            ts_iso = row["ts"] if row else None
        except Exception:
            ts_iso = None

        if ts_iso:
            try:
                ts_str = ts_iso.replace("Z", "+00:00") \
                    if ts_iso.endswith("Z") else ts_iso
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_min = (now - ts).total_seconds() / 60.0
            except Exception:
                age_min = None
        else:
            age_min = None

        out.append(HealthDetailDataSource(
            name=cfg["label"],
            status=_classify_age(age_min, cfg),
            age_minutes=round(age_min, 1) if age_min is not None else None,
            captured_at_bjt=_to_bjt_str(ts_iso) if ts_iso else None,
            expected_cadence=cfg["expected_cadence"],
        ))
    return out


def _query_evidence_layers_health(
    conn,
) -> list[HealthDetailEvidenceLayer]:
    """从最近一条 strategy_run 的 full_state_json 抽 5 层 health_status + pillars。"""
    layers: list[HealthDetailEvidenceLayer] = []
    try:
        row = conn.execute(
            "SELECT full_state_json FROM strategy_runs "
            "ORDER BY generated_at_utc DESC LIMIT 1"
        ).fetchone()
    except Exception:
        row = None

    if row is None:
        for lid in range(1, 6):
            layers.append(HealthDetailEvidenceLayer(
                layer_id=lid, name=_LAYER_NAMES[lid],
                health="missing", pillars_summary="尚无 strategy_run",
                missing_reasons=["pipeline 尚未首次运行"],
            ))
        return layers

    try:
        state = json.loads(row["full_state_json"])
    except (TypeError, ValueError, KeyError):
        state = {}
    er = state.get("evidence_reports") or {}

    for lid in range(1, 6):
        layer = er.get(f"layer_{lid}") or {}
        health = str(layer.get("health_status") or "missing")
        pillars = layer.get("pillars") or []
        if isinstance(pillars, list) and pillars:
            n_total = len(pillars)
            n_ok = sum(
                1 for p in pillars
                if isinstance(p, dict)
                and p.get("status") in ("ok", "healthy", "passed")
            )
            missing_pillars = [
                str(p.get("name") or p.get("pillar_id") or "?")
                for p in pillars
                if isinstance(p, dict)
                and p.get("status") not in ("ok", "healthy", "passed")
            ]
            if missing_pillars:
                summary = (
                    f"{n_ok}/{n_total} 支柱齐"
                    f"({', '.join(missing_pillars)} missing)"
                )
            else:
                summary = f"{n_ok}/{n_total} 支柱齐"
        elif lid == 5:
            comp = layer.get("data_completeness_pct")
            summary = (
                f"完整度 {comp}%" if comp is not None else "—"
            )
        elif lid == 3:
            rt = layer.get("rule_trace") or {}
            mr = rt.get("matched_rule") or layer.get("opportunity_grade") or "—"
            summary = f"规则匹配:{mr}"
        else:
            summary = "—"

        missing_reasons: list[str] = []
        if health in ("degraded", "missing"):
            mr = layer.get("missing_reasons") or layer.get("notes") or []
            if isinstance(mr, list):
                missing_reasons = [str(x) for x in mr][:5]
            elif isinstance(mr, str):
                missing_reasons = [mr]

        layers.append(HealthDetailEvidenceLayer(
            layer_id=lid, name=_LAYER_NAMES[lid],
            health=health, pillars_summary=summary,
            missing_reasons=missing_reasons,
        ))
    return layers


def _aggregate_overall(
    layers: list[HealthDetailEvidenceLayer],
    sources: list[HealthDetailDataSource],
) -> str:
    has_critical = any(s.status == "critical" for s in sources) or \
        any(l.health == "missing" for l in layers)
    has_warn = any(s.status in ("warn", "no_data") for s in sources) or \
        any(l.health == "degraded" for l in layers)
    if has_critical:
        return "critical"
    if has_warn:
        return "partial_degraded"
    return "all_healthy"


@router.get("/health-detail", response_model=HealthDetailResponse)
def get_system_health_detail(request: Request) -> HealthDetailResponse:
    """Sprint 1.5n 系统自检面板:5 层证据健康 + 5 数据源新鲜度 + 聚合状态。"""
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        layers = _query_evidence_layers_health(conn)
        sources = _query_data_source_freshness(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return HealthDetailResponse(
        evidence_layers=layers,
        data_sources=sources,
        overall_status=_aggregate_overall(layers, sources),
    )


# ---------- POST /api/system/run-now ----------

def _run_now_impl(request: Request) -> TriggerResponse:
    ctx = request.app.state.ctx
    now_ts = time.time()

    with ctx.trigger_lock:
        if ctx.within_cooldown(now_ts):
            remaining = int(
                ctx.pipeline_trigger_cooldown_sec
                - (now_ts - (ctx.last_trigger_ts or now_ts))
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    "pipeline trigger rate-limited; "
                    f"retry in ~{max(1, remaining)}s"
                ),
            )
        ctx.register_trigger(now_ts)

    conn = ctx.conn_factory()
    try:
        builder = StrategyStateBuilder(conn)
        result = builder.run(run_trigger="manual_api")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return TriggerResponse(
        status="success" if result.persisted else "failed",
        run_id=result.run_id,
        run_timestamp_utc=result.run_timestamp_utc,
        persisted=result.persisted,
        ai_status=result.ai_status,
        duration_ms=result.duration_ms,
        degraded_stages=result.degraded_stages,
        failure_count=len(result.failures),
    )


@router.post("/run-now", response_model=TriggerResponse)
def trigger_run_now(request: Request) -> TriggerResponse:
    """§9.10 #10:手动触发一次 Pipeline(调试 / 排查)。"""
    return _run_now_impl(request)
