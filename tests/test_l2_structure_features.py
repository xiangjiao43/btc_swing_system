"""tests/test_l2_structure_features.py — Sprint 2.6-L Part 1。

Sprint 2.6-K 调研发现:L2 pillar `structure_sequence`(modeling §4.3.4)永远 missing
因为 layer2_direction.py 从未输出 `structure_features` 字段(grep 验证 0 处)。
L1 已经算出 swing HH/HL/LH/LL 在 diagnostics.swing_counts,但 L2 没读。

本测试用真实 swing 数据走完整 L1 → L2 链路,断言:
- L1 diagnostics.latest_structure 字段存在,值 ∈ {HH, HL, LH, LL, None}
- L2 输出 structure_features dict,包含 5 个字段
- 数据不足时(L1 insufficient)L2 structure_features = None → pillars.py 显示 missing
- §Z 端到端 — 不是 mock。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evidence.layer1_regime import (
    Layer1Regime, _analyze_swing, _latest_structure_label,
)
from src.evidence.layer2_direction import Layer2Direction


# ============================================================
# _latest_structure_label pure unit tests
# ============================================================

def test_latest_structure_label_hh():
    """最新 high 比前一个 high 更高 → HH。"""
    events = [
        {"type": "low", "price": 100, "index": 0},
        {"type": "high", "price": 110, "index": 5},
        {"type": "low", "price": 105, "index": 10},
        {"type": "high", "price": 120, "index": 15},  # latest
    ]
    assert _latest_structure_label(events) == "HH"


def test_latest_structure_label_lh():
    """最新 high 比前一个 high 更低 → LH。"""
    events = [
        {"type": "high", "price": 130, "index": 0},
        {"type": "low", "price": 100, "index": 5},
        {"type": "high", "price": 120, "index": 10},  # latest, < 130
    ]
    assert _latest_structure_label(events) == "LH"


def test_latest_structure_label_hl():
    """最新 low 比前一个 low 更高 → HL。"""
    events = [
        {"type": "low", "price": 100, "index": 0},
        {"type": "high", "price": 120, "index": 5},
        {"type": "low", "price": 110, "index": 10},  # latest, > 100
    ]
    assert _latest_structure_label(events) == "HL"


def test_latest_structure_label_ll():
    events = [
        {"type": "low", "price": 110, "index": 0},
        {"type": "high", "price": 120, "index": 5},
        {"type": "low", "price": 100, "index": 10},  # latest, < 110
    ]
    assert _latest_structure_label(events) == "LL"


def test_latest_structure_label_only_one_of_type():
    """只有 1 个 high 或 1 个 low → None(没法比较)。"""
    events = [{"type": "high", "price": 120, "index": 5}]
    assert _latest_structure_label(events) is None


def test_latest_structure_label_empty():
    assert _latest_structure_label([]) is None


# ============================================================
# Integration: real klines → L1 → L2
# ============================================================

def _synthetic_klines(n: int, seed: int = 42) -> pd.DataFrame:
    """构造带明显 swing 结构的 1d K 线。"""
    rng = np.random.RandomState(seed)
    rng_idx = pd.date_range("2025-01-01", periods=n, freq="D")
    # 上升趋势叠加波动 → 应产生 HH/HL 主导
    base = 50000 + np.cumsum(rng.randn(n) * 200 + 50)
    high = base + rng.uniform(50, 300, n)
    low = base - rng.uniform(50, 300, n)
    close = base + rng.uniform(-100, 100, n)
    open_ = np.r_[base[0], close[:-1]]
    df = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume_btc": rng.uniform(100, 1000, n),
    }, index=rng_idx)
    return df


def test_l1_diagnostics_includes_latest_structure():
    klines_1d = _synthetic_klines(150)
    klines_4h = _synthetic_klines(150 * 6)
    klines_1w = _synthetic_klines(30)
    klines_1h = _synthetic_klines(150 * 24)
    ctx = {
        "klines_1d": klines_1d, "klines_4h": klines_4h,
        "klines_1w": klines_1w, "klines_1h": klines_1h,
        "reference_timestamp_utc": "2025-05-31T00:00:00Z",
    }
    out = Layer1Regime().compute(ctx, rules_version="v1.2.0")
    diag = out.get("diagnostics") or {}
    assert "swing_counts" in diag
    assert "latest_structure" in diag
    sc = diag["swing_counts"]
    assert sc["HH"] >= 0 and sc["HL"] >= 0
    assert sc["LH"] >= 0 and sc["LL"] >= 0
    if diag["latest_structure"] is not None:
        assert diag["latest_structure"] in {"HH", "HL", "LH", "LL"}


def test_l2_emits_structure_features_when_l1_has_swing():
    klines_1d = _synthetic_klines(150)
    klines_4h = _synthetic_klines(150 * 6)
    klines_1w = _synthetic_klines(30)
    klines_1h = _synthetic_klines(150 * 24)
    ctx = {
        "klines_1d": klines_1d, "klines_4h": klines_4h,
        "klines_1w": klines_1w, "klines_1h": klines_1h,
        "reference_timestamp_utc": "2025-05-31T00:00:00Z",
    }
    l1_out = Layer1Regime().compute(ctx, rules_version="v1.2.0")
    ctx["layer_1_output"] = l1_out
    ctx["composite_factors"] = {
        "truth_trend": {"score": 3, "band": "weak_trend",
                        "direction": "up", "confidence": 0.6},
        "band_position": {"phase": "early", "phase_confidence": 0.5},
        "cycle_position": {"cycle_position": "early_bull",
                           "cycle_confidence": 0.6},
    }
    l2_out = Layer2Direction().compute(ctx, rules_version="v1.2.0")
    sf = l2_out.get("structure_features")
    assert sf is not None, "L2 must emit structure_features when L1 has swing data"
    assert isinstance(sf, dict)
    # 5 个字段都存在
    for key in ("hh_count", "hl_count", "lh_count", "ll_count", "latest_structure"):
        assert key in sf, f"missing {key} in {sf}"
    # 4 个 count 都应是 int >= 0
    for key in ("hh_count", "hl_count", "lh_count", "ll_count"):
        assert isinstance(sf[key], int)
        assert sf[key] >= 0
    # latest_structure 在合法 set
    assert sf["latest_structure"] in {"HH", "HL", "LH", "LL", None}


def test_l2_structure_features_none_when_l1_insufficient():
    """L1 swing 数据不足 → L2 structure_features = None,pillar 显示 missing。"""
    # 只给极少 K 线 → L1 _insufficient 路径
    short = _synthetic_klines(15)
    ctx = {
        "klines_1d": short, "klines_4h": short,
        "klines_1w": short, "klines_1h": short,
        "reference_timestamp_utc": "2025-05-31T00:00:00Z",
    }
    l1_out = Layer1Regime().compute(ctx, rules_version="v1.2.0")
    ctx["layer_1_output"] = l1_out
    ctx["composite_factors"] = {}
    l2_out = Layer2Direction().compute(ctx, rules_version="v1.2.0")
    assert l2_out.get("structure_features") is None


# ============================================================
# pillars.py downstream consumes the new field
# ============================================================

def test_pillars_l2_status_ok_when_structure_features_present():
    from src.evidence.pillars import _pillars_l2

    l2 = {
        "stance": "neutral",
        "phase": "n_a",
        "structure_features": {
            "hh_count": 5, "hl_count": 4, "lh_count": 2, "ll_count": 1,
            "latest_structure": "HH",
        },
        "trend_position": {},
        "long_cycle_context": {"cycle_position": "early_bull",
                              "cycle_confidence": 0.6},
    }
    out = _pillars_l2(l2)
    pillars = out["pillars"]
    s_pillar = next(p for p in pillars if p["id"] == "structure_sequence")
    assert s_pillar["status"] == "ok"
    # interpretation 应包含真实 HH/HL/LH/LL 数字
    assert "HH+HL=9" in s_pillar["interpretation"]
    assert "LH+LL=3" in s_pillar["interpretation"]


def test_pillars_l2_status_missing_when_structure_features_absent():
    from src.evidence.pillars import _pillars_l2

    l2 = {"stance": "neutral", "phase": "n_a", "structure_features": None}
    out = _pillars_l2(l2)
    pillars = out["pillars"]
    s_pillar = next(p for p in pillars if p["id"] == "structure_sequence")
    assert s_pillar["status"] == "missing"
