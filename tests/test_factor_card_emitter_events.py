"""tests/test_factor_card_emitter_events.py — Sprint 1.5d.1 前端事件卡覆盖。

§Z 真 _emit_events_reference 调用,断言 5 类(fomc/cpi/pce/nfp/options_expiry_major)
全渲染 → factor_cards 含对应 5 张事件卡。
"""

from __future__ import annotations

import pytest

from src.strategy.factor_card_emitter import _emit_events_reference


def _next(t: str, hours: float) -> dict:
    """构造 next_events_by_type 单条记录。"""
    return {"event_type": t, "name": f"Mock {t}", "hours_to": hours}


# ============================================================
# 5 类全渲染
# ============================================================

def test_emit_events_card_count_is_five():
    next_by_type = {
        "fomc": _next("fomc", 11.5),
        "cpi": _next("cpi", 341.0),
        "pce": _next("pce", 30.0),
        "nfp": _next("nfp", 54.0),
        "options_expiry_major": _next("options_expiry_major", 721.0),
    }
    cards = _emit_events_reference(events=[], today="20260429",
                                   next_by_type=next_by_type)
    assert len(cards) == 5
    ids = sorted(c["card_id"] for c in cards)
    assert ids == sorted([
        "event_fomc_next_20260429",
        "event_cpi_next_20260429",
        "event_pce_next_20260429",
        "event_nfp_next_20260429",
        "event_options_expiry_major_next_20260429",
    ])


def test_emit_events_card_includes_pce():
    cards = _emit_events_reference(
        events=[], today="20260429",
        next_by_type={"pce": _next("pce", 30.0)},
    )
    pce_card = next(
        (c for c in cards if "pce" in c["card_id"]), None
    )
    assert pce_card is not None
    assert pce_card["current_value"] == 30.0
    assert "PCE" in pce_card["name"] or "PCE" in pce_card.get("name_en", "")
    # strategy_impact 含 PCE 描述(Pinchuk 2024)
    assert "PCE" in pce_card["strategy_impact"]


def test_emit_events_card_includes_options_expiry_major():
    cards = _emit_events_reference(
        events=[], today="20260429",
        next_by_type={"options_expiry_major": _next("options_expiry_major", 721.0)},
    )
    opt_card = next(
        (c for c in cards if "options_expiry_major" in c["card_id"]), None
    )
    assert opt_card is not None
    assert opt_card["current_value"] == 721.0
    # strategy_impact 含季度 / 月度区分说明
    assert "季度" in opt_card["strategy_impact"] or "Q" in opt_card["strategy_impact"]


def test_emit_events_card_value_none_when_event_missing():
    """next_by_type 没 PCE → PCE 卡仍渲染但 value=None,interp 提示无未来事件。"""
    cards = _emit_events_reference(
        events=[], today="20260429",
        next_by_type={
            "fomc": _next("fomc", 11.5),
            # no pce
        },
    )
    # 5 张卡 仍要渲染
    assert len(cards) == 5
    pce_card = next(c for c in cards if "pce" in c["card_id"])
    assert pce_card["current_value"] is None


def test_emit_events_card_uses_fallback_from_events_when_next_by_type_empty():
    """next_by_type 空但 events(72h 内)有 PCE → 兜底使用。"""
    cards = _emit_events_reference(
        events=[
            {"event_type": "pce", "name": "PCE Apr",
             "hours_to": 36.5, "event_id": "pce_2026_04_30"},
        ],
        today="20260429",
        next_by_type=None,
    )
    pce_card = next(c for c in cards if "pce" in c["card_id"])
    assert pce_card["current_value"] == 36.5


def test_emit_events_card_pce_value_persisted_when_far_future():
    """PCE 30 天后(720h),仍正常渲染数值,不强制 None。"""
    cards = _emit_events_reference(
        events=[], today="20260429",
        next_by_type={"pce": _next("pce", 720.0)},
    )
    pce_card = next(c for c in cards if "pce" in c["card_id"])
    assert pce_card["current_value"] == 720.0
