"""tests/test_composite_composition_value_pipeline.py — Sprint 1.5c.2 接通修复反退化。

§Z 真实 series + 真 compute,断言 4 项 missing 全部填到 composition[*].value:
- 长周期位置:LTH Supply 90d 变化
- 拥挤度:资金费率 30 日分位 / OI 24h 变化
- 宏观逆风:DXY 20 日 / US10Y 30 日 / 纳指 20 日
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.composite import (
    CrowdingFactor, CyclePositionFactor, MacroHeadwindFactor,
)
from src.strategy import composite_composition as cc


# ============================================================
# 任务 A:cycle_position lth_90d_chg_pct
# ============================================================

def test_cycle_position_exports_lth_90d_chg_pct():
    """100+ 天 LTH 序列 → cycle_position.compute → 顶层 lth_90d_chg_pct + diagnostics 都有。"""
    rng = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    # LTH 缓慢增加(每 90 天 +3%)
    lth = pd.Series([0.65 * (1 + 0.0003 * i) for i in range(120)], index=rng)
    mvrv_z = pd.Series([1.5] * 120, index=rng)
    nupl = pd.Series([0.55] * 120, index=rng)
    ctx = {"onchain": {"mvrv_z_score": mvrv_z, "nupl": nupl, "lth_supply": lth}}
    out = CyclePositionFactor().compute(ctx)
    assert out.get("lth_90d_chg_pct") is not None
    assert isinstance(out["lth_90d_chg_pct"], (int, float))
    # diagnostics 也有别名(供 composite_composition 兜底)
    assert out["diagnostics"].get("lth_90d_chg_pct") == out["lth_90d_chg_pct"]


def test_composite_composition_cycle_lth_value_not_none():
    """cycle_position.compute → composite_composition._cycle_position →
    composition[onchain_lth_supply].value 是数值,不是 None。"""
    rng = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    lth = pd.Series([0.65 * (1 + 0.0003 * i) for i in range(120)], index=rng)
    mvrv_z = pd.Series([1.5] * 120, index=rng)
    nupl = pd.Series([0.55] * 120, index=rng)
    cp_out = CyclePositionFactor().compute({
        "onchain": {"mvrv_z_score": mvrv_z, "nupl": nupl, "lth_supply": lth},
    })
    state = {
        "evidence_reports": {"layer_1": {}, "layer_2": {}},
        "composite_factors": {"cycle_position": cp_out},
    }
    cc.inject_composite_composition(state, context={})
    composition = cp_out.get("composition") or []
    by_id = {c.get("factor_id"): c for c in composition}
    val = by_id.get("onchain_lth_supply", {}).get("value")
    assert val is not None
    assert isinstance(val, (int, float))


# ============================================================
# 任务 B:crowding funding_rate_30d_pctile + oi_24h_change_pct
# ============================================================

def test_crowding_diagnostics_funding_pctile_and_oi():
    """funding 60+ 天 + OI ≥ 2 点 → crowding.compute diagnostics 含 pctile + 24h 变化。"""
    rng = pd.date_range("2024-01-01", periods=60, freq="D", tz="UTC")
    funding = pd.Series([0.0001 * (1 + 0.01 * i) for i in range(60)], index=rng)
    oi = pd.Series([1_000_000.0 * (1 + 0.02 * i) for i in range(60)], index=rng)
    out = CrowdingFactor().compute({"derivatives": {
        "funding_rate": funding, "open_interest": oi,
    }})
    diag = out.get("diagnostics") or {}
    assert diag.get("funding_rate_30d_pctile") is not None
    assert isinstance(diag["funding_rate_30d_pctile"], (int, float))
    assert 0 <= diag["funding_rate_30d_pctile"] <= 100
    assert diag.get("oi_24h_change_pct") is not None
    assert isinstance(diag["oi_24h_change_pct"], (int, float))


def test_composite_composition_crowding_values_not_none():
    """funding + OI 真 series → composite_composition._crowding → composition
    的 funding_rate_30d_pctile / oi_24h_change 行 value 不是 None。"""
    rng = pd.date_range("2024-01-01", periods=60, freq="D", tz="UTC")
    funding = pd.Series([0.0001 * (1 + 0.01 * i) for i in range(60)], index=rng)
    oi = pd.Series([1_000_000.0 * (1 + 0.02 * i) for i in range(60)], index=rng)
    cr_out = CrowdingFactor().compute({"derivatives": {
        "funding_rate": funding, "open_interest": oi,
    }})
    state = {
        "evidence_reports": {"layer_1": {}, "layer_2": {}},
        "composite_factors": {"crowding": cr_out},
    }
    # composite_composition._crowding 也读 ctx.derivatives,所以 context 也要给
    cc.inject_composite_composition(state, context={
        "derivatives": {"funding_rate": funding, "open_interest": oi},
    })
    by_id = {c.get("factor_id"): c for c in (cr_out.get("composition") or [])}
    pctile = by_id.get("derivatives_funding_rate_30d_pctile", {}).get("value")
    oi_chg = by_id.get("derivatives_oi_24h_change", {}).get("value")
    assert pctile is not None
    assert isinstance(pctile, (int, float))
    assert oi_chg is not None
    assert isinstance(oi_chg, (int, float))


# ============================================================
# 任务 C:macro_headwind composition 读 diagnostics
# ============================================================

def test_composite_composition_macro_headwind_values_not_none():
    """macro 60+ 天 → macro_headwind.compute → composition DXY/US10Y/纳指 都有数值。"""
    rng = pd.date_range("2024-01-01", periods=60, freq="D", tz="UTC")
    dxy = pd.Series([102.0 + 0.05 * i for i in range(60)], index=rng)
    us10y = pd.Series([4.0 + 0.005 * i for i in range(60)], index=rng)
    nasdaq = pd.Series([15_000.0 * (1 + 0.001 * i) for i in range(60)], index=rng)
    vix = pd.Series([18.0] * 60, index=rng)
    sp500 = pd.Series([5_000.0] * 60, index=rng)
    macro = {"dxy": dxy, "us10y": us10y, "nasdaq": nasdaq,
             "vix": vix, "sp500": sp500}

    # macro_headwind 需要 klines_1d 才能算 btc_nasdaq_corr;给一个无关的就行
    klines_1d = pd.DataFrame({
        "open": [50_000] * 60, "high": [50_500] * 60,
        "low": [49_500] * 60, "close": [50_000] * 60, "volume": [1.0] * 60,
    }, index=rng)
    mh_out = MacroHeadwindFactor().compute({
        "macro": macro, "klines_1d": klines_1d,
    })
    diag = mh_out.get("diagnostics") or {}
    assert diag.get("dxy_20d_change") is not None
    assert diag.get("us10y_30d_change_bp") is not None
    assert diag.get("nasdaq_20d_change") is not None

    state = {
        "evidence_reports": {"layer_1": {}, "layer_2": {}},
        "composite_factors": {"macro_headwind": mh_out},
    }
    cc.inject_composite_composition(state, context={"macro": macro})
    by_id = {c.get("factor_id"): c
             for c in (mh_out.get("composition") or [])}
    assert by_id["macro_dxy_20d_change"]["value"] is not None
    assert isinstance(by_id["macro_dxy_20d_change"]["value"], (int, float))
    assert by_id["macro_us10y_30d_change"]["value"] is not None
    assert by_id["macro_nasdaq_20d"]["value"] is not None


# ============================================================
# 任务 D 核心反退化:全 6 项 missing 都填上
# ============================================================

def test_all_six_missing_values_filled_when_data_sufficient():
    """端到端:cycle + crowding + macro_headwind 三个 composite 同时跑 →
    composite_composition 注入后,**6 项 user-reported missing 都不是 None**。"""
    rng = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    # cycle data
    lth = pd.Series([0.65 + 0.0002 * i for i in range(120)], index=rng)
    mvrv_z = pd.Series([1.5] * 120, index=rng)
    nupl = pd.Series([0.55] * 120, index=rng)
    # crowding data
    funding = pd.Series([0.0001 * (1 + 0.01 * i) for i in range(120)], index=rng)
    oi = pd.Series([1_000_000.0 * (1 + 0.02 * i) for i in range(120)], index=rng)
    # macro data
    dxy = pd.Series([102.0 + 0.05 * i for i in range(120)], index=rng)
    us10y = pd.Series([4.0 + 0.005 * i for i in range(120)], index=rng)
    nasdaq = pd.Series([15_000.0 * (1 + 0.001 * i) for i in range(120)], index=rng)
    vix = pd.Series([18.0] * 120, index=rng)
    sp500 = pd.Series([5_000.0] * 120, index=rng)
    klines_1d = pd.DataFrame({
        "open": [50_000] * 120, "high": [50_500] * 120,
        "low": [49_500] * 120, "close": [50_000] * 120, "volume": [1.0] * 120,
    }, index=rng)

    cp_out = CyclePositionFactor().compute({
        "onchain": {"mvrv_z_score": mvrv_z, "nupl": nupl, "lth_supply": lth},
    })
    cr_out = CrowdingFactor().compute({"derivatives": {
        "funding_rate": funding, "open_interest": oi,
    }})
    mh_out = MacroHeadwindFactor().compute({
        "macro": {"dxy": dxy, "us10y": us10y, "nasdaq": nasdaq,
                  "vix": vix, "sp500": sp500},
        "klines_1d": klines_1d,
    })

    state = {
        "evidence_reports": {"layer_1": {}, "layer_2": {}},
        "composite_factors": {
            "cycle_position": cp_out,
            "crowding": cr_out,
            "macro_headwind": mh_out,
        },
    }
    cc.inject_composite_composition(state, context={
        "derivatives": {"funding_rate": funding, "open_interest": oi},
        "macro": {"dxy": dxy, "us10y": us10y, "nasdaq": nasdaq,
                  "vix": vix, "sp500": sp500},
        "klines_1d": klines_1d,
    })

    def _val(factor_name: str, fid: str) -> Any:  # noqa: F821
        comp = state["composite_factors"][factor_name].get("composition") or []
        for it in comp:
            if it.get("factor_id") == fid:
                return it.get("value")
        return "NOT FOUND"

    # 6 项断言(user-reported missing 全部应该是数值)
    checks = [
        ("cycle_position", "onchain_lth_supply"),
        ("crowding", "derivatives_funding_rate_30d_pctile"),
        ("crowding", "derivatives_oi_24h_change"),
        ("macro_headwind", "macro_dxy_20d_change"),
        ("macro_headwind", "macro_us10y_30d_change"),
        ("macro_headwind", "macro_nasdaq_20d"),
    ]
    for factor, fid in checks:
        v = _val(factor, fid)
        assert v is not None, f"{factor}.{fid} 仍为 None"
        assert v != "NOT FOUND", f"{factor}.{fid} 未在 composition 里"
        assert isinstance(v, (int, float)), (
            f"{factor}.{fid} 期望数值,实际 {type(v).__name__}={v!r}"
        )


# Allow Any in test scope
from typing import Any  # noqa: E402
