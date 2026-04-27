"""tests/test_event_next_cards_beyond_72h.py — Sprint 2.6-M B2。

Sprint 2.6-K 调研(已部署生产)发现:event_fomc_next/cpi_next/nfp_next 卡
依赖 events_upcoming_48h(state_builder 用 72h 窗口),所以即使 events_calendar
有 10 行(8 FOMC + May NFP + May CPI),Apr 27 看不到 May 1 NFP / May 13 CPI
(都 > 72h),用户网页一直显示"下次 X 数据未就绪"。

修法:state_builder 注入 next_events_by_type(不限窗口的 {type: row}),
emitter 优先用它;无该 key 时退回 events_upcoming_48h(向后兼容)。
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import EventRow, EventsCalendarDAO
from src.strategy.factor_card_emitter import _emit_events_reference


@pytest.fixture
def db_with_events():
    tmp = Path(tempfile.mkdtemp()) / "ev.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    EventsCalendarDAO.upsert_events(conn, [
        EventRow(event_id="fomc_2026_04_29", date="2026-04-29",
                 timezone="America/New_York", local_time="14:00",
                 utc_trigger_time="2026-04-29T18:00:00Z",
                 event_type="fomc", event_name="FOMC Apr",
                 impact_level=5, notes=None),
        EventRow(event_id="nfp_2026_05_01", date="2026-05-01",
                 timezone="America/New_York", local_time="08:30",
                 utc_trigger_time="2026-05-01T12:30:00Z",
                 event_type="nfp", event_name="NFP May",
                 impact_level=4, notes=None),
        EventRow(event_id="cpi_2026_05_13", date="2026-05-13",
                 timezone="America/New_York", local_time="08:30",
                 utc_trigger_time="2026-05-13T12:30:00Z",
                 event_type="cpi", event_name="CPI May",
                 impact_level=4, notes=None),
    ])
    conn.commit()
    yield conn
    conn.close()


def test_get_next_events_by_type_returns_all_three_beyond_72h(db_with_events):
    """从 Apr 27,FOMC 在 48h,NFP 在 96h,CPI 在 384h — 全部应被返回。"""
    out = EventsCalendarDAO.get_next_events_by_type(
        db_with_events,
        event_types=["fomc", "cpi", "nfp"],
        now_utc="2026-04-27T18:00:00Z",
    )
    assert out["fomc"] is not None
    assert out["nfp"] is not None
    assert out["cpi"] is not None
    # hours_to 都为正
    assert out["fomc"]["hours_to"] == pytest.approx(48.0, abs=0.01)
    assert out["nfp"]["hours_to"] == pytest.approx(90.5, abs=0.01)
    assert out["cpi"]["hours_to"] == pytest.approx(378.5, abs=0.01)


def test_get_next_events_by_type_skips_past_events(db_with_events):
    """从 Apr 30(FOMC 已过)→ FOMC 没下一个(2026 仅 seed 一个 Apr FOMC),
    实际本测试 db 只 seed 1 个 FOMC,过了就 None。"""
    out = EventsCalendarDAO.get_next_events_by_type(
        db_with_events,
        event_types=["fomc"],
        now_utc="2026-04-30T00:00:00Z",
    )
    assert out["fomc"] is None  # 没下一个


def test_emitter_uses_next_by_type_for_far_events(db_with_events):
    """生产场景重现:Apr 27 看 NFP 在 May 1(96h 外)。
    旧代码:events_upcoming_48h 没含 NFP → 卡 None。
    新代码:next_by_type 提供 NFP → 卡显示 96h。"""
    next_by_type = EventsCalendarDAO.get_next_events_by_type(
        db_with_events,
        event_types=["fomc", "cpi", "nfp"],
        now_utc="2026-04-27T18:00:00Z",
    )
    cards = _emit_events_reference(
        events=[],  # 模拟 72h 窗口什么都没收到
        today="20260427",
        next_by_type=next_by_type,
    )
    by_id = {c["card_id"]: c for c in cards}
    assert by_id["event_fomc_next_20260427"]["current_value"] == pytest.approx(48.0, abs=0.1)
    assert by_id["event_nfp_next_20260427"]["current_value"] == pytest.approx(90.5, abs=0.1)
    assert by_id["event_cpi_next_20260427"]["current_value"] == pytest.approx(378.5, abs=0.1)


def test_emitter_falls_back_to_events_when_next_by_type_missing(db_with_events):
    """无 next_by_type 提供时,退回老逻辑(events 72h 窗口)。"""
    events_72h = [
        {"event_type": "fomc", "name": "F",
         "hours_to": 48.0, "utc_trigger_time": "2026-04-29T18:00:00Z"},
    ]
    cards = _emit_events_reference(events_72h, "20260427")
    by_id = {c["card_id"]: c for c in cards}
    assert by_id["event_fomc_next_20260427"]["current_value"] == 48.0
    # NFP / CPI 不在 events 列表 → 仍 None(72h 窗口外)
    assert by_id["event_nfp_next_20260427"]["current_value"] is None
    assert by_id["event_cpi_next_20260427"]["current_value"] is None


def test_state_builder_injects_next_events_by_type(db_with_events):
    """端到端:state_builder._assemble_context 把字段注入 context。"""
    from src.pipeline.state_builder import StrategyStateBuilder
    builder = StrategyStateBuilder(db_with_events, events_window_hours=72)
    ctx = builder._assemble_context(
        db_with_events, now_utc="2026-04-27T18:00:00Z",
    )
    assert "next_events_by_type" in ctx
    assert ctx["next_events_by_type"]["fomc"] is not None
    assert ctx["next_events_by_type"]["nfp"] is not None
    assert ctx["next_events_by_type"]["cpi"] is not None
