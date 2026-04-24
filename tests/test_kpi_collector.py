"""
tests/test_kpi_collector.py — Sprint 1.16a 单测

覆盖:
  1. 空库不 crash,各类返回合理默认
  2. 总次数正确 + 日均计算
  3. state 分布百分比合理(已知输入/输出映射)
  4. AI 成功率计算(含 degraded)
  5. top 3 fallback 排序
  6. 时间窗口过滤(lookback_days=1 vs 7 差异)
  7. 冷启动进度计算
  8. data_freshness 非空
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import FallbackLogDAO, StrategyStateDAO
from src.kpi import KPICollector


# ==================================================================
# Fixtures
# ==================================================================

@pytest.fixture
def conn():
    tmp = Path(tempfile.mkdtemp()) / "kpi.db"
    init_db(db_path=tmp, verbose=False)
    c = get_connection(tmp)
    yield c
    c.close()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(
    *,
    sm_state: str = "neutral_observation",
    lifecycle: str = "FLAT",
    l2_stance: str = "neutral",
    l2_confidence: float = 0.55,
    l3_grade: str = "none",
    adj_action: str = "watch",
    adj_confidence: float = 0.5,
    adj_status: str = "success",
    ai_status: str = "success",
    degraded: list[str] | None = None,
    cold_start_runs: int = 100,
    cold_start_warming: bool = False,
    macro_completeness: float = 80.0,
    ref_ts: str | None = None,
    gen_ts: str | None = None,
) -> dict[str, Any]:
    ref = ref_ts or _iso(datetime.now(timezone.utc))
    gen = gen_ts or ref
    return {
        "reference_timestamp_utc": ref,
        "generated_at_utc": gen,
        "cold_start": {
            "warming_up": cold_start_warming,
            "runs_completed": cold_start_runs,
            "threshold": 42,
        },
        "evidence_reports": {
            "layer_2": {"stance": l2_stance, "stance_confidence": l2_confidence},
            "layer_3": {"opportunity_grade": l3_grade},
            "layer_5": {"data_completeness_pct": macro_completeness},
        },
        "context_summary": {"status": ai_status},
        "state_machine": {"current_state": sm_state},
        "lifecycle": {"current_lifecycle": lifecycle},
        "adjudicator": {
            "action": adj_action,
            "confidence": adj_confidence,
            "status": adj_status,
        },
        "pipeline_meta": {
            "degraded_stages": degraded or [],
        },
    }


def _insert_state(
    conn,
    *,
    run_ts: str,
    run_id: str,
    state: dict[str, Any],
) -> None:
    StrategyStateDAO.insert_state(
        conn,
        run_timestamp_utc=run_ts,
        run_id=run_id,
        run_trigger="scheduled",
        rules_version="v1.2.0",
        ai_model_actual="mock",
        state=state,
    )
    conn.commit()


# ==================================================================
# 1. Empty DB — no crash
# ==================================================================

def test_empty_db_returns_sensible_defaults(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    k = KPICollector(conn, now_utc=now).compute_kpis(lookback_days=7)
    assert k["execution"]["runs_total"] == 0
    assert k["execution"]["runs_per_day"] == 0.0
    assert k["fallback"]["events_total"] == 0
    # 分布全 0
    assert all(v == 0.0 for v in k["state_distribution"]["state_machine_distribution"].values())
    assert k["decision"]["avg_stance_confidence"] is None
    assert k["data_quality"]["macro_completeness_avg"] is None


# ==================================================================
# 2. Total runs + per-day rate
# ==================================================================

def test_runs_total_and_per_day(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    # 7 轮,分散 7 天
    for i in range(7):
        ts = _iso(now - timedelta(days=i))
        _insert_state(
            conn, run_ts=ts, run_id=f"r{i}",
            state=_state(ref_ts=ts, gen_ts=ts),
        )
    k = KPICollector(conn, now_utc=now).compute_kpis(lookback_days=7)
    assert k["execution"]["runs_total"] == 7
    assert k["execution"]["runs_per_day"] == pytest.approx(1.0)
    assert k["execution"]["last_run_at"] is not None


# ==================================================================
# 3. State distribution percentages
# ==================================================================

def test_state_distribution_sums(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    states = [
        "neutral_observation", "neutral_observation",
        "active_long_execution", "active_long_execution",
        "cold_start_warming_up",
    ]
    for i, sm in enumerate(states):
        ts = _iso(now - timedelta(hours=i))
        _insert_state(
            conn, run_ts=ts, run_id=f"r{i}",
            state=_state(ref_ts=ts, gen_ts=ts, sm_state=sm),
        )
    k = KPICollector(conn, now_utc=now).compute_kpis(lookback_days=7)
    dist = k["state_distribution"]["state_machine_distribution"]
    assert dist["neutral_observation"] == pytest.approx(0.4)
    assert dist["active_long_execution"] == pytest.approx(0.4)
    assert dist["cold_start_warming_up"] == pytest.approx(0.2)
    # Total of all non-zero entries = 1.0
    total = sum(dist.values())
    assert total == pytest.approx(1.0, abs=0.01)


# ==================================================================
# 4. AI / adjudicator success rates (含 degraded)
# ==================================================================

def test_ai_and_adjudicator_success_rates(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    configs = [
        {"ai_status": "success", "adj_status": "success"},
        {"ai_status": "success", "adj_status": "success"},
        {"ai_status": "success", "adj_status": "success"},
        {"ai_status": "degraded_error", "adj_status": "degraded_structured"},
    ]
    for i, c in enumerate(configs):
        ts = _iso(now - timedelta(hours=i))
        _insert_state(
            conn, run_ts=ts, run_id=f"r{i}",
            state=_state(ref_ts=ts, gen_ts=ts, **c),
        )
    agg = KPICollector(conn, now_utc=now).compute_stage_success_rate(
        lookback_days=7
    )["_aggregate"]
    assert agg["ai_summary_success_rate"] == pytest.approx(0.75)
    assert agg["adjudicator_success_rate"] == pytest.approx(0.75)


# ==================================================================
# 5. Top 3 fallback stages
# ==================================================================

def test_top_3_fallback_stages(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    # stage 计数:ai_summary=5, macro_collection=3, event_risk=2, layer_1=1
    stage_counts = [
        ("ai_summary", 5), ("macro_collection", 3),
        ("event_risk", 2), ("layer_1", 1),
    ]
    i = 0
    for stage, n in stage_counts:
        for _ in range(n):
            ts = _iso(now - timedelta(minutes=i))
            FallbackLogDAO.log_stage_error(
                conn, run_timestamp_utc=ts,
                stage=stage, error="boom",
                fallback_applied="default",
            )
            i += 1
    conn.commit()
    k = KPICollector(conn, now_utc=now).compute_fallback_stats(lookback_days=7)
    assert k["events_total"] == 11
    assert [t["stage"] for t in k["top_3_stages"]] == [
        "ai_summary", "macro_collection", "event_risk",
    ]
    assert k["top_3_stages"][0]["count"] == 5


# ==================================================================
# 6. Lookback window filter
# ==================================================================

def test_lookback_window_filters_old_rows(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    # 3 条在 1 天内,4 条在 5-7 天前
    for i in range(3):
        ts = _iso(now - timedelta(hours=i))
        _insert_state(
            conn, run_ts=ts, run_id=f"recent-{i}",
            state=_state(ref_ts=ts, gen_ts=ts),
        )
    # 4 条跨越 5~10 天,其中前 2 条(5d, 6d)仍在 7 天窗口内
    for i in range(4):
        ts = _iso(now - timedelta(days=5 + i))
        _insert_state(
            conn, run_ts=ts, run_id=f"old-{i}",
            state=_state(ref_ts=ts, gen_ts=ts),
        )
    collector = KPICollector(conn, now_utc=now)
    k1 = collector.compute_kpis(lookback_days=1)
    k7 = collector.compute_kpis(lookback_days=7)
    k30 = collector.compute_kpis(lookback_days=30)
    assert k1["execution"]["runs_total"] == 3         # 仅近 24h
    assert k7["execution"]["runs_total"] == 6         # 3 + 3(5d, 6d, 7d)
    assert k30["execution"]["runs_total"] == 7        # 3 + 4


# ==================================================================
# 7. Cold-start progress
# ==================================================================

def test_cold_start_progress(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    ts = _iso(now - timedelta(hours=1))
    _insert_state(
        conn, run_ts=ts, run_id="r",
        state=_state(
            ref_ts=ts, gen_ts=ts,
            cold_start_runs=10,
            cold_start_warming=True,
        ),
    )
    dist = KPICollector(conn, now_utc=now).compute_state_distribution(
        lookback_days=7
    )
    cs = dist["cold_start_progress"]
    assert cs["runs_completed"] == 10
    assert cs["threshold"] == 42
    assert cs["percent"] == pytest.approx(23.81, abs=0.01)
    assert cs["warming_up"] is True


# ==================================================================
# 8. data_freshness available
# ==================================================================

def test_data_freshness_computed(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    ref = now - timedelta(hours=1)
    gen = ref + timedelta(minutes=15)  # 15 分钟滞后
    _insert_state(
        conn, run_ts=_iso(ref), run_id="r",
        state=_state(ref_ts=_iso(ref), gen_ts=_iso(gen)),
    )
    k = KPICollector(conn, now_utc=now).compute_kpis(lookback_days=7)
    dq = k["data_quality"]
    assert dq["data_freshness_avg_minutes"] == pytest.approx(15.0, abs=0.1)
    assert dq["macro_completeness_avg"] == pytest.approx(80.0)
