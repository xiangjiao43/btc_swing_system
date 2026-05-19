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

# Sprint Web Transparency Commit 3 删除:test_24h_liquidation_* 3 个测试
# 原因:derivatives_liquidation_24h 卡是死卡(Layer A 排除衍生品,Layer B L4
# prompt 不消费 liquidation_total),已从 emitter 删除。
# coinglass.py liquidation collector + DB 列保留。


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

# Sprint Web Transparency Commit 3 删除:test_24h_lsr_* 2 个测试
# 原因:derivatives_lsr_change_24h 卡是死卡(Layer A 排除衍生品,Layer B L4
# prompt 不消费 long_short_ratio),已从 emitter 删除。
# coinglass.py long_short_ratio collector + DB 列保留。
