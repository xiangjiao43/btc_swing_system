"""tests/test_l5_structured_macro_round3.py — Sprint 1.5c.5 字段名 mismatch 反退化。

§Z **测试 fixture 必须用 layer5_macro 真实输出格式**:
- _compute_trend 返回 {direction, magnitude_30d_pct, ema_alignment}
- _compute_vix_regime 返回 {level, latest_value, recent_change_pct, is_spike}
- _compute_btc_nasdaq_correlation 返回 {coefficient, strength_label, lookback_days, n_samples}

1.5c.4 翻车的根本教训:用假字段名(correlation_60d / regime / latest)写测试,
会让 helper bug 测试通过但生产仍空。
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.evidence import Layer5Macro
from src.evidence.layer5_macro import _build_structured_macro_rule
from src.evidence.pillars import _pillars_l5


# ============================================================
# 真实生产 fixture(从 SSH 实测拷贝的字段名 + 数值)
# ============================================================

_PROD_DXY_TREND = {
    "direction": "falling", "magnitude_30d_pct": -0.01512, "ema_alignment": "down",
}
_PROD_YIELDS_TREND = {
    "direction": "rising", "magnitude_30d_pct": 0.02837, "ema_alignment": "up",
}
_PROD_VIX_REGIME = {
    "level": "normal", "latest_value": 18.02,
    "recent_change_pct": 0.0045, "is_spike": False,
}
_PROD_BTC_NASDAQ_CORR = {
    "coefficient": 0.4403, "strength_label": "moderately_correlated",
    "lookback_days": 30, "n_samples": 30,
}


def test_helper_with_production_field_names():
    """直接用生产真实 fixture(从 SSH 实测拷贝)→ helper 应正确生成 sm。"""
    sm = _build_structured_macro_rule(
        dxy_trend=_PROD_DXY_TREND,
        yields_trend=_PROD_YIELDS_TREND,
        yields_series=pd.Series([3.95, 4.05, 4.18]),
        vix_regime=_PROD_VIX_REGIME,
        btc_nasdaq_corr=_PROD_BTC_NASDAQ_CORR,
        macro={"dxy": pd.Series([102.5, 101.8, 100.5])},
        completeness=90.0,
    )
    # DXY:trend + magnitude_30d_pct(真实字段名)
    assert sm["DXY"]["trend"] == "falling"
    assert sm["DXY"]["magnitude_30d_pct"] == pytest.approx(-0.01512)
    assert sm["DXY"]["latest"] == 100.5

    # US10Y
    assert sm["US10Y"]["trend"] == "rising"
    assert sm["US10Y"]["magnitude_30d_pct"] == pytest.approx(0.02837)
    assert sm["US10Y"]["latest"] == pytest.approx(4.18)

    # VIX:从 level 取 regime,从 latest_value 取 latest
    assert sm["VIX"]["regime"] == "normal"
    assert sm["VIX"]["latest"] == 18.02
    assert sm["VIX"]["is_spike"] is False

    # btc_nasdaq_corr:展开为 float(从 dict.coefficient)
    assert sm["btc_nasdaq_corr"] == pytest.approx(0.4403)
    assert isinstance(sm["btc_nasdaq_corr"], float)

    # data_completeness_pct
    assert sm["data_completeness_pct"] == 90.0


def test_helper_btc_nasdaq_corr_unwraps_dict_to_float():
    """1.5c.4 helper 把 corr 当 dict 存 → 1.5c.5 展开为 float。
    防回退 guard。"""
    sm = _build_structured_macro_rule(
        dxy_trend=None, yields_trend=None, yields_series=None,
        vix_regime=None,
        btc_nasdaq_corr={"coefficient": 0.65, "strength_label": "x"},
        macro={}, completeness=50.0,
    )
    assert sm["btc_nasdaq_corr"] == 0.65
    assert isinstance(sm["btc_nasdaq_corr"], float)


def test_helper_btc_nasdaq_corr_accepts_plain_float_too():
    """老路径 / 测试场景直接传 float → 也接受。"""
    sm = _build_structured_macro_rule(
        dxy_trend=None, yields_trend=None, yields_series=None,
        vix_regime=None,
        btc_nasdaq_corr=0.42,
        macro={}, completeness=50.0,
    )
    assert sm["btc_nasdaq_corr"] == 0.42


def test_helper_vix_uses_level_and_latest_value():
    """关键反退化:1.5c.4 老 helper 读 .regime / .latest 字段不存在 → entry 空。
    1.5c.5 改读 .level / .latest_value(真实字段)。"""
    sm = _build_structured_macro_rule(
        dxy_trend=None, yields_trend=None, yields_series=None,
        vix_regime=_PROD_VIX_REGIME,
        btc_nasdaq_corr=None,
        macro={}, completeness=20.0,
    )
    assert "VIX" in sm
    assert sm["VIX"]["regime"] == "normal"
    assert sm["VIX"]["latest"] == 18.02


# ============================================================
# 端到端:Layer5Macro.compute → _pillars_l5 都 ok
# ============================================================

def test_e2e_layer5_compute_to_pillars_l5_status_ok():
    """完整真跑 Layer5Macro.compute 120 天数据 → structured_macro 4 类齐 →
    _pillars_l5 status=ok + interp 含 latest 数值。"""
    rng = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    dxy = pd.Series([102.0 + 0.05 * i for i in range(120)], index=rng)
    us10y = pd.Series([4.0 + 0.005 * i for i in range(120)], index=rng)
    nasdaq = pd.Series([15_000.0 + 5 * i for i in range(120)], index=rng)
    vix = pd.Series([18.0 + 0.01 * i for i in range(120)], index=rng)
    sp500 = pd.Series([5_000.0 + 2 * i for i in range(120)], index=rng)
    klines_1d = pd.DataFrame({
        "open": [50_000] * 120, "high": [50_500] * 120,
        "low": [49_500] * 120, "close": [50_000 + 10 * i for i in range(120)],
        "volume": [1.0] * 120,
    }, index=rng)
    out = Layer5Macro().compute({
        "macro": {"dxy": dxy, "us10y": us10y, "nasdaq": nasdaq,
                  "vix": vix, "sp500": sp500},
        "klines_1d": klines_1d,
    })
    sm = out.get("structured_macro") or {}
    keys = sorted(k for k in sm if k != "data_completeness_pct")
    # 4 类全应到位
    assert "DXY" in keys
    assert "US10Y" in keys
    assert "VIX" in keys
    assert "btc_nasdaq_corr" in keys, sm

    # btc_nasdaq_corr 是 float
    assert isinstance(sm["btc_nasdaq_corr"], float)

    # _pillars_l5 应 ok 且 interp 含 DXY=… US10Y=… VIX=… BTC-NDX corr=…
    pillars = _pillars_l5(out)
    sm_pillar = next(p for p in pillars["pillars"] if p["id"] == "structured_macro")
    assert sm_pillar["status"] == "ok"
    # interp 至少要含三个数值之一
    interp = sm_pillar["interpretation"]
    assert "DXY=" in interp or "US10Y=" in interp or "VIX=" in interp


def test_pillars_l5_corr_float_in_interp():
    """1.5c.5 起 sm.btc_nasdaq_corr 是 float;_pillars_l5 应直接格式化。"""
    l5 = {"structured_macro": {
        "DXY": {"latest": 100.5},
        "btc_nasdaq_corr": 0.4403,
        "data_completeness_pct": 80.0,
    }}
    out = _pillars_l5(l5)
    sm = next(p for p in out["pillars"] if p["id"] == "structured_macro")
    assert sm["status"] == "ok"
    assert "BTC-NDX corr=0.44" in sm["interpretation"]


def test_pillars_l5_corr_dict_legacy_compat():
    """老 dict 形态(1.5c.4 暂留)也能解析。"""
    l5 = {"structured_macro": {
        "DXY": {"latest": 100.5},
        "btc_nasdaq_corr": {"value": 0.55, "amplified": False},
        "data_completeness_pct": 80.0,
    }}
    out = _pillars_l5(l5)
    sm = next(p for p in out["pillars"] if p["id"] == "structured_macro")
    assert "BTC-NDX corr=0.55" in sm["interpretation"]
