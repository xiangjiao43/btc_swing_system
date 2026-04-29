"""tests/test_factor_card_24h_daily.py — Sprint 1.5f-revised 24h 卡 daily 语义。

§Z 真 daily Series → emit_factor_cards → 断言 3 张 24h 卡数值反映 daily 算法:
- liquidation_24h:`_latest(series)` = 最新 daily bar(本身就是当天 24h 累计)
- oi_24h_change:`_pct_change(series, days=1)` = 今 daily / 昨 daily - 1
- lsr_24h_change:同上

替代 1.5e.1 的 test_factor_card_24h_window.py(假设 hourly,经 SSH 复检后
反转为 daily 语义)。
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


def _daily_series(values: list[float], days_back_start: int | None = None) -> pd.Series:
    """构造 daily 频率的 Series(00:00:00Z 时间戳)。"""
    n = len(values)
    start = days_back_start or n
    rng = pd.date_range(
        end=pd.Timestamp("2026-04-29T00:00:00Z"),
        periods=n, freq="D", tz="UTC",
    )
    return pd.Series(values, index=rng)


# ============================================================
# liquidation 24h:daily bar 直接当 24h 累计
# ============================================================

def test_24h_liquidation_uses_daily_last_value():
    """daily series 末值 = 7,686,347.99 → current_value = 7,686,347.99
    (1.5e.1 老代码会 sum 24 行 = 假数据)。"""
    liq = _daily_series([1_000_000.0, 2_000_000.0, 7_686_347.99])
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"liquidation_total": liq},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_liquidation_24h")
    assert c is not None
    assert c["current_value"] == 7_686_347.99


def test_24h_liquidation_only_one_day_still_works():
    """只有 1 行 daily → 直接显示该值(daily bar 自带 24h 含义)。"""
    liq = _daily_series([5_000_000.0])
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"liquidation_total": liq},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_liquidation_24h")
    assert c["current_value"] == 5_000_000.0


def test_24h_liquidation_none_when_empty():
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_liquidation_24h")
    assert c["current_value"] is None


# ============================================================
# OI 24h change:_pct_change(daily, days=1)
# ============================================================

def test_24h_oi_uses_daily_pct_change():
    """daily series 末两值 [55_000, 56_000] → (56000/55000 - 1)*100 ≈ 1.82%。
    1.5e.1 老 _pct_change(.., 24) 会拿 iloc[-25] 比较 → < 25 行返 None。"""
    oi = _daily_series([54_000.0, 54_500.0, 55_000.0, 56_000.0])
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"open_interest": oi},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_oi_24h_change")
    assert c is not None
    expected = (56_000.0 / 55_000.0 - 1.0) * 100.0
    assert c["current_value"] == pytest.approx(expected, abs=0.01)


def test_24h_oi_none_when_only_one_day():
    """单 daily 行 → days=1 lookback 不到 → None。"""
    oi = _daily_series([55_000.0])
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"open_interest": oi},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_oi_24h_change")
    assert c["current_value"] is None


# ============================================================
# LSR 24h change:_pct_change(daily, days=1)
# ============================================================

def test_24h_lsr_uses_daily_pct_change():
    """daily 末两值 [0.94, 0.81] → ((0.81/0.94)-1)*100 ≈ -13.83%。"""
    lsr = _daily_series([1.0, 0.94, 0.81])
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"long_short_ratio": lsr},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_lsr_change_24h")
    assert c is not None
    expected = (0.81 / 0.94 - 1.0) * 100.0
    assert c["current_value"] == pytest.approx(expected, abs=0.01)


def test_24h_lsr_none_when_only_one_day():
    lsr = _daily_series([1.5])
    cards = emit_factor_cards(_make_state(), {
        "derivatives": {"long_short_ratio": lsr},
        "macro": {}, "onchain": {},
    })
    c = _find(cards, "derivatives_lsr_change_24h")
    assert c["current_value"] is None
