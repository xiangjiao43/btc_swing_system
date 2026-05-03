"""Sprint 1.10-C 单测:CooldownManager(v1.4 §4.3)。"""
from __future__ import annotations

import pytest

from src.strategy.cooldown_manager import (
    determine_close_channel, compute_cooldown_end, is_in_cooldown,
)


# ============================================================
# determine_close_channel
# ============================================================

def test_natural_close_profit_returns_a():
    assert determine_close_channel("all_take_profit_filled") == "A"


def test_natural_close_loss_returns_a():
    assert determine_close_channel("stop_loss_filled") == "A"


def test_invalidated_default_returns_b():
    """invalidated 无任何 C 条件 → B(默认)。"""
    assert determine_close_channel("invalidated") == "B"


def test_invalidated_4_of_4_returns_c():
    """4/4 → C(立即反手 0 冷却)。"""
    ch = determine_close_channel(
        "invalidated",
        stop_loss_breached=True,
        l1_regime_fully_reversed=True,
        l2_stance_strong_flip=True,
        l5_extreme_event_or_risk_off=True,
    )
    assert ch == "C"


def test_invalidated_3_of_4_returns_c():
    """3/4 → C。"""
    ch = determine_close_channel(
        "invalidated",
        stop_loss_breached=True,
        l1_regime_fully_reversed=True,
        l2_stance_strong_flip=True,
        # l5 false
    )
    assert ch == "C"


def test_invalidated_2_of_4_with_l1_reversed_returns_b():
    """2/4 + L1 完全反转 → B(显式 B,不升 C)。"""
    ch = determine_close_channel(
        "invalidated",
        stop_loss_breached=True,
        l1_regime_fully_reversed=True,
    )
    assert ch == "B"


def test_invalidated_2_of_4_no_l1_returns_b():
    """2/4 无 L1 反转 → B(默认)。"""
    ch = determine_close_channel(
        "invalidated",
        l2_stance_strong_flip=True,
        l5_extreme_event_or_risk_off=True,
    )
    assert ch == "B"


def test_invalidated_1_of_4_returns_b():
    """1/4 → B(invalidated 默认,master AI 已决定关闭)。"""
    ch = determine_close_channel(
        "invalidated",
        l5_extreme_event_or_risk_off=True,
    )
    assert ch == "B"


def test_60d_cap_returns_a():
    assert determine_close_channel("60d_cap") == "A"


def test_protection_returns_a():
    assert determine_close_channel("protection") == "A"


def test_unknown_reason_defaults_to_a():
    """未知 reason 默认 A(最保守,避 0 冷却快通道)。"""
    assert determine_close_channel("hallucinated_reason") == "A"


# ============================================================
# compute_cooldown_end
# ============================================================

def test_cooldown_end_channel_a_72h():
    end = compute_cooldown_end("2026-05-10T08:00:00Z", "A")
    assert end == "2026-05-13T08:00:00Z"


def test_cooldown_end_channel_b_24h():
    end = compute_cooldown_end("2026-05-10T08:00:00Z", "B")
    assert end == "2026-05-11T08:00:00Z"


def test_cooldown_end_channel_c_0h():
    end = compute_cooldown_end("2026-05-10T08:00:00Z", "C")
    assert end == "2026-05-10T08:00:00Z"


def test_cooldown_end_invalid_channel_raises():
    with pytest.raises(ValueError):
        compute_cooldown_end("2026-05-10T08:00:00Z", "Z")


# ============================================================
# is_in_cooldown
# ============================================================

def test_no_closed_thesis_not_in_cooldown():
    r = is_in_cooldown("2026-05-10T08:00:00Z", None)
    assert not r["in_cooldown"]
    assert r["remaining_hours"] == 0.0
    assert r["thesis_id"] is None


def test_in_cooldown_channel_a_within_72h():
    """closed at 5-10 + 72h → cooldown ends 5-13 08:00。
    now at 5-12 08:00 → 24h remaining。"""
    r = is_in_cooldown(
        "2026-05-12T08:00:00Z",
        latest_closed_thesis={
            "thesis_id": "th1", "closed_at_utc": "2026-05-10T08:00:00Z",
            "close_channel": "A",
        },
    )
    assert r["in_cooldown"]
    assert abs(r["remaining_hours"] - 24.0) < 0.01
    assert r["channel"] == "A"
    assert r["cooldown_end_utc"] == "2026-05-13T08:00:00Z"


def test_cooldown_just_expired():
    """now 刚过 cooldown_end 1 秒 → not in cooldown。"""
    r = is_in_cooldown(
        "2026-05-13T08:00:01Z",
        latest_closed_thesis={
            "thesis_id": "th1", "closed_at_utc": "2026-05-10T08:00:00Z",
            "close_channel": "A",
        },
    )
    assert not r["in_cooldown"]
    assert r["remaining_hours"] == 0.0


def test_cooldown_channel_c_immediately_expires():
    """channel C 0h → 即关 即过(in_cooldown=False)。"""
    r = is_in_cooldown(
        "2026-05-10T08:00:01Z",
        latest_closed_thesis={
            "thesis_id": "th1", "closed_at_utc": "2026-05-10T08:00:00Z",
            "close_channel": "C",
        },
    )
    assert not r["in_cooldown"]


def test_cooldown_invalid_channel_in_thesis():
    """thesis 字段缺失 close_channel → not in cooldown(防御)。"""
    r = is_in_cooldown(
        "2026-05-12T08:00:00Z",
        latest_closed_thesis={"thesis_id": "th1", "closed_at_utc": "2026-05-10T08:00:00Z"},
    )
    assert not r["in_cooldown"]


def test_cooldown_remaining_decimal_precision():
    """remaining_hours 应为 4 位小数(round)。"""
    r = is_in_cooldown(
        "2026-05-10T18:30:30Z",
        latest_closed_thesis={
            "thesis_id": "th1", "closed_at_utc": "2026-05-10T08:00:00Z",
            "close_channel": "B",
        },
    )
    # cooldown_end = 5-11 08:00; now = 5-10 18:30:30; remaining = 13.5 hours - 30s = 13.4917
    assert abs(r["remaining_hours"] - 13.4917) < 0.001
