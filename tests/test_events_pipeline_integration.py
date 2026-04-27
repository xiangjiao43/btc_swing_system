"""tests/test_events_pipeline_integration.py — Sprint 2.6-D 集成验证。

证明 seed JSON → EventsCalendarDAO → state_builder context 注入 → event_risk
评分链路完整工作,FOMC 事件能驱动 L4 EventRisk 升档。

不调真实 state_builder.run()(那需要全量 K线/衍生品/链上),只测 events 通路。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.data.collectors.events_seeder import seed_events
from src.data.storage.dao import EventsCalendarDAO


@pytest.fixture
def db_with_events():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE events_calendar (
            event_id          TEXT PRIMARY KEY,
            date              TEXT NOT NULL,
            timezone          TEXT NOT NULL
                              CHECK (timezone IN ('America/New_York', 'UTC')),
            local_time        TEXT,
            utc_trigger_time  TEXT,
            event_type        TEXT NOT NULL,
            event_name        TEXT NOT NULL,
            impact_level      INTEGER CHECK (impact_level BETWEEN 1 AND 5),
            notes             TEXT
        )
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def fomc_in_36h_seed(tmp_path):
    """FOMC 事件,距 'now_utc' 锚点 36 小时(落在 24-48h 距离桶,multiplier=1.0)。"""
    seed_data = {"events": [
        {
            "event_id": "fomc_anchor",
            "date": "2026-04-29",
            "timezone": "America/New_York",
            "local_time": "14:00",
            # 锚点 = 2026-04-28T06:00:00Z;事件 = 2026-04-29T18:00:00Z;
            # 间隔 = 36 小时
            "utc_trigger_time": "2026-04-29T18:00:00Z",
            "event_type": "fomc",
            "event_name": "FOMC anchor",
            "impact_level": 5,
            "notes": "for integration test",
        },
    ]}
    p = tmp_path / "fomc.json"
    p.write_text(json.dumps(seed_data))
    return p


def test_seed_then_dao_query_returns_event_with_hours_to(
    db_with_events, fomc_in_36h_seed,
):
    """seed_events → DAO.get_upcoming_within_hours 返回事件并附带 hours_to。"""
    seed_events(db_with_events, fomc_in_36h_seed)

    events = EventsCalendarDAO.get_upcoming_within_hours(
        db_with_events,
        hours=72,
        now_utc="2026-04-28T06:00:00Z",
    )
    assert len(events) == 1
    ev = events[0]
    assert ev["event_id"] == "fomc_anchor"
    assert ev["event_type"] == "fomc"
    assert ev["hours_to"] == pytest.approx(36.0, abs=0.01)


def test_seed_then_event_risk_scores_medium_band(
    db_with_events, fomc_in_36h_seed,
):
    """seed → DAO → event_risk.compute → score=4.0(fomc 4 × 36h-bucket 1.0),band=medium。"""
    from src.composite.event_risk import EventRiskFactor

    seed_events(db_with_events, fomc_in_36h_seed)
    events = EventsCalendarDAO.get_upcoming_within_hours(
        db_with_events,
        hours=72,
        now_utc="2026-04-28T06:00:00Z",
    )

    factor = EventRiskFactor()
    out = factor.compute({
        "events_upcoming_48h": events,
        "is_volatility_extreme": False,
        "btc_nasdaq_correlated": False,
    })

    # fomc base_weight=4 × distance_multiplier(36h → [24,48] bucket)=1.0 → 4.0
    assert out["score"] == pytest.approx(4.0, abs=0.01)
    assert out["band"] == "medium"
    assert out["position_cap_multiplier"] == 0.85
    assert out["upcoming_events_count"] == 1
    assert out["contributing_events"][0]["type"] == "fomc"


def test_real_seed_loads_and_query_returns_apr29_fomc(db_with_events):
    """真实 seed 文件 → 至少包含 fomc_2026_04_29(本月 FOMC)。"""
    project_root = Path(__file__).resolve().parent.parent
    real_seed = project_root / "data" / "seeds" / "events_2026.json"
    seed_events(db_with_events, real_seed)

    # 拉一个跨整年的窗口(8760h),确认目标事件在表里
    events = EventsCalendarDAO.get_events_in_window(
        db_with_events,
        "2026-01-01T00:00:00Z",
        "2026-12-31T23:59:59Z",
    )
    event_ids = {e["event_id"] for e in events}
    assert "fomc_2026_04_29" in event_ids
    assert "fomc_2026_12_09" in event_ids
    assert "nfp_2026_05_01" in event_ids
    assert "cpi_2026_05_13" in event_ids
