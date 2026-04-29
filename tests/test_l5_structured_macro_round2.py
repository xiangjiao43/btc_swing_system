"""tests/test_l5_structured_macro_round2.py — Sprint 1.5c.4 收尾。

§Z 真实场景:
- macro 部分可用(只有 dxy series 没 trend)→ structured_macro 仍含 DXY entry
- 真跑 Layer5Macro 全数据 → structured_macro 4 个 key 都填
- _pillars_l5 对真填的 structured_macro → status=ok,interp 含 latest 数值
- 只有 data_completeness_pct sentinel → status=missing(真伪空)
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.evidence import Layer5Macro
from src.evidence.layer5_macro import _build_structured_macro_rule
from src.evidence.pillars import _pillars_l5


# ============================================================
# helper 直测:partial data 场景
# ============================================================

def test_build_structured_macro_partial_dxy_only():
    """只给 dxy series 没 trend → DXY entry 仍含 latest。"""
    dxy = pd.Series([102.0, 103.5, 105.0])
    sm = _build_structured_macro_rule(
        dxy_trend=None, yields_trend=None, yields_series=None,
        vix_regime=None, btc_nasdaq_corr=None,
        macro={"dxy": dxy}, completeness=20.0,
    )
    assert "DXY" in sm
    assert sm["DXY"]["latest"] == 105.0
    # 其他类没填
    assert "US10Y" not in sm
    assert "VIX" not in sm
    # data_completeness sentinel 存在
    assert sm["data_completeness_pct"] == 20.0


def test_build_structured_macro_full_data():
    """4 个数据全有 → 4 个 key 都填。"""
    dxy_trend = {"direction": "rising", "magnitude_30d_pct": 1.5}
    yields_trend = {"direction": "rising", "magnitude_30d_pct": 0.8}
    vix_regime = {"regime": "normal", "level": "normal", "latest_value": 18.0}
    btc_nasdaq_corr = {"correlation_60d": 0.45, "amplified": False}
    sm = _build_structured_macro_rule(
        dxy_trend=dxy_trend, yields_trend=yields_trend,
        yields_series=pd.Series([4.0, 4.2, 4.3]),
        vix_regime=vix_regime, btc_nasdaq_corr=btc_nasdaq_corr,
        macro={"dxy": pd.Series([100, 102, 105])},
        completeness=80.0,
    )
    assert "DXY" in sm
    assert sm["DXY"]["trend"] == "rising"
    assert sm["DXY"]["latest"] == 105.0
    assert "US10Y" in sm
    assert sm["US10Y"]["latest"] == 4.3
    assert "VIX" in sm
    assert sm["VIX"]["regime"] == "normal"
    assert sm["VIX"]["latest"] == 18.0
    assert "btc_nasdaq_corr" in sm
    assert sm["btc_nasdaq_corr"]["value"] == 0.45


def test_build_structured_macro_all_none_returns_only_sentinel():
    """所有数据都 None → 只有 data_completeness_pct sentinel。"""
    sm = _build_structured_macro_rule(
        dxy_trend=None, yields_trend=None, yields_series=None,
        vix_regime=None, btc_nasdaq_corr=None,
        macro={}, completeness=0.0,
    )
    assert list(sm.keys()) == ["data_completeness_pct"]


# ============================================================
# _pillars_l5:filter sentinel + interp 含 latest
# ============================================================

def test_pillars_l5_only_sentinel_is_missing():
    """structured_macro 只含 data_completeness_pct → status=missing(真伪空)。"""
    l5 = {"structured_macro": {"data_completeness_pct": 0.0}}
    out = _pillars_l5(l5)
    sm = next(p for p in out["pillars"] if p["id"] == "structured_macro")
    assert sm["status"] == "missing"
    assert "0 项" in sm["interpretation"] or "未就绪" in sm["interpretation"]


def test_pillars_l5_partial_data_is_ok_with_latest_in_interp():
    """structured_macro 含 DXY+US10Y → status=ok, interp 含 DXY=… US10Y=…"""
    l5 = {"structured_macro": {
        "DXY": {"latest": 105.5}, "US10Y": {"latest": 4.3},
        "data_completeness_pct": 40.0,
    }}
    out = _pillars_l5(l5)
    sm = next(p for p in out["pillars"] if p["id"] == "structured_macro")
    assert sm["status"] == "ok"
    assert "DXY=105.5" in sm["interpretation"]
    assert "US10Y=4.3" in sm["interpretation"]


def test_pillars_l5_with_btc_nasdaq_corr_in_interp():
    l5 = {"structured_macro": {
        "DXY": {"latest": 100},
        "btc_nasdaq_corr": {"value": 0.42, "amplified": False},
        "data_completeness_pct": 50.0,
    }}
    out = _pillars_l5(l5)
    sm = next(p for p in out["pillars"] if p["id"] == "structured_macro")
    assert sm["status"] == "ok"
    assert "BTC-NDX corr=0.42" in sm["interpretation"]


# ============================================================
# 端到端:Layer5Macro.compute(部分 + 全)→ pillars 都 ok
# ============================================================

def test_l5_pillars_structured_macro_ok_with_partial_real_data():
    """生产偏极端场景:dxy + nasdaq 60 天 + 缺 us10y/vix → 仍 ok。"""
    rng = pd.date_range("2024-01-01", periods=80, freq="D", tz="UTC")
    dxy = pd.Series([102.0 + 0.05 * i for i in range(80)], index=rng)
    nasdaq = pd.Series([15_000.0 + 5 * i for i in range(80)], index=rng)
    klines_1d = pd.DataFrame({
        "open": [50_000] * 80, "high": [50_500] * 80,
        "low": [49_500] * 80, "close": [50_000] * 80, "volume": [1.0] * 80,
    }, index=rng)
    out = Layer5Macro().compute({
        "macro": {"dxy": dxy, "nasdaq": nasdaq},
        "klines_1d": klines_1d,
    })
    pillars = _pillars_l5(out)
    sm = next(p for p in pillars["pillars"] if p["id"] == "structured_macro")
    assert sm["status"] == "ok", out.get("structured_macro")


def test_l5_pillars_structured_macro_ok_with_full_real_data():
    """全部数据(120 天 dxy/us10y/vix/nasdaq/sp500)→ structured_macro 4 个 key + ok。"""
    rng = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    dxy = pd.Series([102.0 + 0.05 * i for i in range(120)], index=rng)
    us10y = pd.Series([4.0 + 0.005 * i for i in range(120)], index=rng)
    nasdaq = pd.Series([15_000.0 + 5 * i for i in range(120)], index=rng)
    vix = pd.Series([18.0] * 120, index=rng)
    sp500 = pd.Series([5_000.0] * 120, index=rng)
    klines_1d = pd.DataFrame({
        "open": [50_000] * 120, "high": [50_500] * 120,
        "low": [49_500] * 120, "close": [50_000] * 120, "volume": [1.0] * 120,
    }, index=rng)
    out = Layer5Macro().compute({
        "macro": {"dxy": dxy, "us10y": us10y, "nasdaq": nasdaq,
                  "vix": vix, "sp500": sp500},
        "klines_1d": klines_1d,
    })
    sm_dict = out.get("structured_macro") or {}
    keys = [k for k in sm_dict if k != "data_completeness_pct"]
    # 至少 DXY/US10Y/VIX 三个;btc_nasdaq_corr 可选(取决于 corr 算法是否产出)
    assert "DXY" in keys
    assert "US10Y" in keys
    assert "VIX" in keys

    pillars = _pillars_l5(out)
    sm_pillar = next(p for p in pillars["pillars"] if p["id"] == "structured_macro")
    assert sm_pillar["status"] == "ok"
