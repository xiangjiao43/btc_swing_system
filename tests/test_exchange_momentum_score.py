"""tests/test_exchange_momentum_score.py — Sprint 2.6-M C2。

modeling §3.8 把 ExchangeMomentum 从 composite 降级为 L2 内部 stance_confidence
修正项。L2 read 'single_factors.exchange_momentum_score' 但**从未被任何
producer 写入**,导致 cold_notes 永远是 "exchange_momentum not provided in
context, skipped"。

修法:新建 src/single_factors/exchange_momentum.py 计算 score,state_builder
注入 context["single_factors"]。

约定:正值 = bullish(BTC 流出交易所),负值 = bearish(流入)。
对应 L2 §B5 逻辑:em_score < 0 + candidate=bullish → × 0.85 修正。

§Z 端到端:state_builder._assemble_context → context["single_factors"] →
L2.compute → notes 不再有 "exchange_momentum not provided"。
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.storage.connection import init_db
from src.single_factors.exchange_momentum import compute_exchange_momentum_score


# ============================================================
# Pure unit
# ============================================================

def _series(values: list[float]) -> pd.Series:
    rng = pd.date_range("2025-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=rng, dtype=float)


def test_positive_inflow_gives_negative_em_score():
    """7 天平均 net_flow 正值(BTC 流入交易所 = 卖压)→ em_score 负 = bearish。"""
    flows = [0.0] * 173 + [100.0] * 7  # 最近 7 天大幅流入
    s = _series(flows)
    em = compute_exchange_momentum_score({"exchange_net_flow": s})
    assert em is not None
    assert em < 0
    # 100 流入,180 天 abs 最大 = 100 → -100/100 = -1
    assert em == pytest.approx(-1.0, abs=0.01)


def test_negative_outflow_gives_positive_em_score():
    """7 天平均 net_flow 负值(BTC 流出 = 累积)→ em_score 正 = bullish。"""
    flows = [0.0] * 173 + [-100.0] * 7
    s = _series(flows)
    em = compute_exchange_momentum_score({"exchange_net_flow": s})
    assert em is not None
    assert em > 0
    assert em == pytest.approx(1.0, abs=0.01)


def test_balanced_flow_near_zero():
    flows = [50.0, -50.0] * 90
    s = _series(flows)
    em = compute_exchange_momentum_score({"exchange_net_flow": s})
    assert em is not None
    assert abs(em) < 0.5  # 平均接近 0


def test_clamped_at_extremes():
    """极端值不超过 [-1, +1]。"""
    flows = [0.0] * 173 + [1e9] * 7  # 最近一周量极端
    s = _series(flows)
    em = compute_exchange_momentum_score({"exchange_net_flow": s})
    assert em is not None
    assert -1.0 <= em <= 1.0


def test_returns_none_on_short_series():
    s = _series([1.0, -2.0, 3.0])  # < 7 days
    assert compute_exchange_momentum_score({"exchange_net_flow": s}) is None


def test_returns_none_when_missing():
    assert compute_exchange_momentum_score({}) is None
    assert compute_exchange_momentum_score(None) is None  # type: ignore[arg-type]


def test_returns_none_when_not_pd_series():
    assert compute_exchange_momentum_score(
        {"exchange_net_flow": [1, 2, 3]}
    ) is None


# ============================================================
# state_builder integration: context["single_factors"]
# ============================================================

def test_state_builder_injects_single_factors_with_em_score():
    """端到端:_assemble_context → onchain.exchange_net_flow → em_score 写入。"""
    tmp = Path(tempfile.mkdtemp()) / "em.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row

    # Seed exchange_net_flow rows: 7 天大幅流入
    from src.data.storage.dao import OnchainDAO, OnchainMetric
    rng = pd.date_range("2026-04-21", periods=10, freq="D")
    rows = [
        OnchainMetric(timestamp=ts.strftime("%Y-%m-%dT00:00:00Z"),
                      metric_name="exchange_net_flow",
                      metric_value=200.0,  # 流入
                      source="glassnode_primary")
        for ts in rng
    ]
    OnchainDAO.upsert_batch(conn, rows)
    conn.commit()

    from src.pipeline.state_builder import StrategyStateBuilder
    builder = StrategyStateBuilder(conn)
    ctx = builder._assemble_context(conn, now_utc="2026-05-01T00:00:00Z")
    assert "single_factors" in ctx
    em = ctx["single_factors"]["exchange_momentum_score"]
    assert em is not None
    assert em < 0  # 流入 → bearish
    conn.close()


def test_l2_no_longer_skips_when_em_provided():
    """端到端:L2 收到 em_score → notes 不再含 'not provided in context'。"""
    from src.evidence.layer2_direction import Layer2Direction
    ctx = {
        "layer_1_output": {
            "regime": "trend_up",
            "regime_stability": "stable",
            "swing_stability": "more_higher_highs",
            "diagnostics": {"swing_counts": {"HH": 5, "HL": 5, "LH": 1, "LL": 1},
                           "latest_structure": "HH"},
        },
        "composite_factors": {
            "truth_trend": {"score": 6, "band": "real_trend",
                           "direction": "up", "confidence": 0.7},
            "band_position": {"phase": "early", "phase_confidence": 0.6},
            "cycle_position": {"cycle_position": "early_bull",
                              "cycle_confidence": 0.7},
        },
        "single_factors": {"exchange_momentum_score": -0.5},  # bearish flow
    }
    out = Layer2Direction().compute(ctx, rules_version="v1.2.0")
    notes = " ".join(out.get("notes") or [])
    assert "not provided in context" not in notes, (
        f"L2 still skips em_score: notes={notes}"
    )
    # exchange_momentum_score 应原样反映在 output
    assert out.get("exchange_momentum_score") == -0.5
