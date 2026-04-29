"""tests/test_factor_card_24h_window.py — Sprint 1.5e.1 24h 算法反退化。

§Z 真 hourly Series + 真 emit_factor_cards,断言:
- liquidation_24h = 24 行 sum(不是 1h 单点)
- OI 24h change = 24 个 hourly point 回看(不是 1 个)
- LSR 24h change = 同上
- 数据不足 24h(< 25 点)→ current_value = None,前端显示 "—"
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategy.factor_card_emitter import emit_factor_cards


def _make_state() -> dict:
    return {
        "evidence_reports": {
            "layer_1": {"regime": "range_mid"},
            "layer_2": {"stance": "neutral", "phase": "n_a"},
        },
    }


def _find(cards: list, fid_substr: str) -> dict | None:
    for c in cards:
        if fid_substr in (c.get("card_id") or ""):
            return c
    return None


# ============================================================
# 24h 清算累计 sum
# ============================================================

def test_liquidation_24h_sums_24_hourly_rows():
    """24 行 hourly 序列 each 1000 → current_value = 24000(不是 1000)。"""
    rng = pd.date_range("2026-04-29T00:00:00Z", periods=30, freq="h", tz="UTC")
    liq = pd.Series([1000.0] * 30, index=rng)
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"liquidation_total": liq, "open_interest": pd.Series([5e10] * 30, index=rng)},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_liquidation_24h")
    assert c is not None
    # 24 个 hourly 点 each 1000 = 24,000
    assert c["current_value"] == 24_000.0


def test_liquidation_24h_returns_none_when_insufficient():
    """只有 5 行 → current_value=None;interp 提示数据不足。"""
    rng = pd.date_range("2026-04-29T00:00:00Z", periods=5, freq="h", tz="UTC")
    liq = pd.Series([1000.0] * 5, index=rng)
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"liquidation_total": liq},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_liquidation_24h")
    assert c is not None
    assert c["current_value"] is None
    assert "数据不足" in (c.get("plain_interpretation") or "")


def test_liquidation_24h_picks_last_24_when_more():
    """30 行,前 6 行 0,后 24 行 each 5000 → sum=120,000(只取末尾 24)。"""
    rng = pd.date_range("2026-04-29T00:00:00Z", periods=30, freq="h", tz="UTC")
    values = [0.0] * 6 + [5000.0] * 24
    liq = pd.Series(values, index=rng)
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"liquidation_total": liq},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_liquidation_24h")
    assert c["current_value"] == 120_000.0


# ============================================================
# OI 24h change(_pct_change(.., 24))
# ============================================================

def test_oi_24h_change_uses_24_hourly_lookback():
    """OI 25 行,iloc[-25]=100, iloc[-1]=110 → +10%。
    旧 _pct_change(.., 1) 会拿 iloc[-2] 比较,新 24 → 拿 iloc[-25]。"""
    rng = pd.date_range("2026-04-29T00:00:00Z", periods=25, freq="h", tz="UTC")
    # 设计:iloc[-25] = 100;iloc[-1] = 110(中间随便)
    closes = [100.0, 105, 102, 108, 109, 110.5, 109, 108, 107.5, 109,
              108, 107, 109, 110, 110.2, 110.5, 109.8, 110.1, 110.3, 110.0,
              109.5, 109.8, 110.0, 110.2, 110.0]
    oi = pd.Series(closes, index=rng)
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"open_interest": oi, "liquidation_total": pd.Series([0.0] * 25, index=rng)},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_oi_24h_change")
    assert c is not None
    # (110.0 / 100.0 - 1) * 100 = 10.0
    assert c["current_value"] == pytest.approx(10.0, abs=0.01)


def test_oi_24h_change_returns_none_when_insufficient():
    """只 10 行 → < 25 → None。"""
    rng = pd.date_range("2026-04-29T00:00:00Z", periods=10, freq="h", tz="UTC")
    oi = pd.Series([5e10] * 10, index=rng)
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"open_interest": oi},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_oi_24h_change")
    assert c["current_value"] is None


# ============================================================
# LSR 24h change
# ============================================================

def test_lsr_24h_change_uses_24_hourly_lookback():
    """LSR 25 行,iloc[-25]=0.94, iloc[-1]=0.81 → ((0.81/0.94)-1)*100 ≈ -13.83%。"""
    rng = pd.date_range("2026-04-29T00:00:00Z", periods=25, freq="h", tz="UTC")
    values = [0.94] + [0.90] * 23 + [0.81]
    lsr = pd.Series(values, index=rng)
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"long_short_ratio": lsr, "open_interest": pd.Series([5e10] * 25, index=rng)},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_lsr_change_24h")
    assert c is not None
    expected = (0.81 / 0.94 - 1.0) * 100.0
    assert c["current_value"] == pytest.approx(expected, abs=0.01)


def test_lsr_partial_window_returns_none():
    """只有 5 行 LSR → current_value=None。"""
    rng = pd.date_range("2026-04-29T00:00:00Z", periods=5, freq="h", tz="UTC")
    lsr = pd.Series([1.5] * 5, index=rng)
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"long_short_ratio": lsr},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_lsr_change_24h")
    assert c["current_value"] is None


# ============================================================
# 关键反退化:不再"1h 当 24h"
# ============================================================

def test_24h_cards_not_using_single_point_diff():
    """显式构造场景:iloc[-2] 和 iloc[-25] 差异大,确认走 24 路径。
    series = [100, 100, 100, 100, ..., 110]  iloc[-1]=110, iloc[-2]=100,
    iloc[-25] 也是 100。

    旧 _pct_change(.., 1) 会拿 iloc[-2]=100 → +10%
    新 _pct_change(.., 24) 会拿 iloc[-25]=100 → +10%

    所以这个 case 两边一样 → 改用一个明确不一样的:
    最后一段 5 个 105,前面 20 个 100,iloc[-1]=105。
    iloc[-2]=105 → 老算法 0%(不变)
    iloc[-25]=100 → 新算法 +5%
    """
    rng = pd.date_range("2026-04-29T00:00:00Z", periods=25, freq="h", tz="UTC")
    values = [100.0] * 20 + [105.0] * 5
    oi = pd.Series(values, index=rng)
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"open_interest": oi},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_oi_24h_change")
    # 必须是 +5%(新),而不是 0%(老)
    assert c["current_value"] == pytest.approx(5.0, abs=0.1), (
        f"expected +5% (24h diff), got {c['current_value']}% — likely "
        f"reverted to _pct_change(.., 1) bug"
    )
