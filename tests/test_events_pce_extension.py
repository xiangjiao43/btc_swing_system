"""tests/test_events_pce_extension.py — Sprint 1.5d PCE + 季度期权区分。

§Z 真 init_db + EventsSeeder + 真 thresholds + 真 _event_risk:
- events_2026.json 含 12 PCE
- PCE utc_trigger_time DST 切换正确
- options_expiry Q1/Q2/Q3/Q4 impact=4 / 其他 8 月 impact=2
- thresholds.yaml event_type_weights 含 pce=4
- composite_composition._event_risk 含 PCE 行 + 拾取 next_events_by_type.pce
- event_risk.py _US_MACRO_TYPES 含 pce(相关性加成生效)
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ============================================================
# events_2026.json 内容
# ============================================================

def _load_seed():
    repo = Path(__file__).resolve().parent.parent
    return json.loads(
        (repo / "data" / "seeds" / "events_2026.json").read_text(encoding="utf-8")
    )


def test_events_seed_contains_12_pce():
    events = _load_seed()["events"]
    pce = [e for e in events if e["event_type"] == "pce"]
    assert len(pce) == 12, f"expected 12 PCE, got {len(pce)}"


def test_pce_utc_trigger_time_format_and_dst():
    """所有 pce utc_trigger_time 符合 ISO + DST 切换正确。"""
    iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    pce = [e for e in _load_seed()["events"] if e["event_type"] == "pce"]
    for e in pce:
        assert iso_pat.match(e["utc_trigger_time"]), e["utc_trigger_time"]
        # 8:30 ET → EDT 12:30 UTC / EST 13:30 UTC
        d = datetime.fromisoformat(e["date"]).date()
        if d.month == 3 and d.day >= 8:
            expected = "12:30"
        elif 4 <= d.month <= 10:
            expected = "12:30"
        elif d.month == 11 and d.day == 1:
            expected = "13:30"  # Nov 1 EST starts
        elif d.month <= 2 or d.month >= 11:
            expected = "13:30"
        else:
            expected = "12:30"
        assert e["utc_trigger_time"].endswith(f"T{expected}:00Z"), (
            f"{e['date']} expected UTC {expected}, got "
            f"{e['utc_trigger_time']}"
        )


def test_pce_jan_feb_have_shutdown_reschedule_notes():
    """1/2 月 PCE notes 应标 '2025 government shutdown' rescheduled。"""
    by_id = {
        e["event_id"]: e for e in _load_seed()["events"]
        if e["event_type"] == "pce"
    }
    for evid in ("pce_2026_01_29", "pce_2026_02_26"):
        assert evid in by_id
        notes = by_id[evid].get("notes") or ""
        assert "shutdown" in notes.lower(), notes


# ============================================================
# 季度 vs 月度 期权 impact_level
# ============================================================

def test_options_expiry_quarterly_impact_4():
    options = [
        e for e in _load_seed()["events"]
        if e["event_type"] == "options_expiry_major"
    ]
    by_id = {e["event_id"]: e for e in options}
    # Q1=Mar / Q2=Jun / Q3=Sep / Q4=Dec
    quarterly = (
        "options_expiry_major_2026_03",
        "options_expiry_major_2026_06",
        "options_expiry_major_2026_09",
        "options_expiry_major_2026_12",
    )
    for evid in quarterly:
        assert by_id[evid]["impact_level"] == 4, (
            f"{evid} expected impact=4, got {by_id[evid]['impact_level']}"
        )
        assert "quarterly" in by_id[evid]["notes"].lower(), by_id[evid]["notes"]


def test_options_expiry_monthly_impact_2():
    options = [
        e for e in _load_seed()["events"]
        if e["event_type"] == "options_expiry_major"
    ]
    by_id = {e["event_id"]: e for e in options}
    monthly = (
        "options_expiry_major_2026_01", "options_expiry_major_2026_02",
        "options_expiry_major_2026_04", "options_expiry_major_2026_05",
        "options_expiry_major_2026_07", "options_expiry_major_2026_08",
        "options_expiry_major_2026_10", "options_expiry_major_2026_11",
    )
    for evid in monthly:
        assert by_id[evid]["impact_level"] == 2, (
            f"{evid} expected impact=2, got {by_id[evid]['impact_level']}"
        )


# ============================================================
# events_seeder 真写库
# ============================================================

def test_events_seeder_loads_pce_into_db():
    from src.data.collectors.events_seeder import seed_events
    from src.data.storage.connection import init_db
    tmp = Path(tempfile.mkdtemp()) / "evpce.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    try:
        seed_events(conn)
        rows = conn.execute(
            "SELECT event_type, COUNT(*) FROM events_calendar "
            "GROUP BY event_type"
        ).fetchall()
        by_type = dict(rows)
    finally:
        conn.close()
    assert by_type.get("pce", 0) == 12
    assert by_type.get("fomc", 0) == 8
    assert by_type.get("cpi", 0) == 12
    assert by_type.get("nfp", 0) == 12
    assert by_type.get("options_expiry_major", 0) == 12
    # 总数 56
    assert sum(by_type.values()) >= 56


# ============================================================
# thresholds.yaml event_type_weights pce
# ============================================================

def test_thresholds_pce_weight():
    import yaml
    repo = Path(__file__).resolve().parent.parent
    cfg = yaml.safe_load(
        (repo / "config" / "thresholds.yaml").read_text(encoding="utf-8")
    )
    weights = cfg["event_risk_scoring"]["event_type_weights"]
    assert weights.get("pce") == 4
    # FOMC 仍 4
    assert weights.get("fomc") == 4


# ============================================================
# composite_composition._event_risk PCE 行
# ============================================================

def test_event_risk_composition_includes_pce_row():
    """composition 含 event_pce_next 一行,从 next_events_by_type.pce 拾取距离。"""
    from src.strategy import composite_composition as cc
    er_out = {
        "factor": "event_risk", "score": 0.0, "band": "low",
        "contributing_events": [],
    }
    state = {
        "evidence_reports": {"layer_1": {}, "layer_2": {}},
        "composite_factors": {"event_risk": er_out},
    }
    context = {
        "next_events_by_type": {
            "fomc": {"hours_to": 30.0},
            "cpi":  {"hours_to": 320.0},
            "pce":  {"hours_to": 168.0},  # ~7 days
            "nfp":  {"hours_to": 198.0},
            "options_expiry_major": {"hours_to": 528.0},
        },
    }
    cc.inject_composite_composition(state, context)
    composition = er_out.get("composition") or []
    by_id = {c.get("factor_id"): c for c in composition}
    assert "event_pce_next" in by_id, [c.get("factor_id") for c in composition]
    assert by_id["event_pce_next"]["value"] == 168.0
    assert by_id["event_pce_next"]["weight"] > 0


# ============================================================
# event_risk.py:PCE 走美宏相关性加成
# ============================================================

def test_event_risk_pce_in_us_macro_types():
    """_US_MACRO_TYPES 应含 pce(相关性 > 0.7 时美宏事件 +1)。"""
    from src.composite.event_risk import _US_MACRO_TYPES
    assert "pce" in _US_MACRO_TYPES
    assert "fomc" in _US_MACRO_TYPES
    assert "cpi" in _US_MACRO_TYPES


def test_event_risk_compute_picks_pce_event():
    """contributing_events 含 pce 时,base_weight 应 = 4(从 thresholds 读)。"""
    from src.composite.event_risk import EventRiskFactor

    factor = EventRiskFactor()
    out = factor.compute({
        "events_upcoming_48h": [
            {"event_type": "pce", "name": "PCE", "hours_to": 36.0},
        ],
        "is_volatility_extreme": False,
        "btc_nasdaq_correlated": False,
    })
    contributing = out.get("contributing_events") or []
    assert len(contributing) == 1
    pce_evt = contributing[0]
    assert pce_evt["type"] == "pce"
    assert pce_evt["base_weight"] == 4.0
    # 24-48h 距离 multiplier=1.0 → effective_score=4.0
    assert pce_evt["effective_score"] == 4.0
