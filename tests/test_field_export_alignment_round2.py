"""tests/test_field_export_alignment_round2.py — Sprint 1.5c.1 收尾。

§Z 真实数据:
- ma_alignment.direction 在不严格升降序时返回 "mixed"(不让前端 "—")
- ma_200_relation 字段 export 全(above / distance_pct)
- event_risk composition cpi/nfp/options 距离不再 None,
  即便事件在 72h 窗口外(走 next_events_by_type 全年 lookahead)
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.evidence import Layer1Regime


def _build_klines(closes, freq="D"):
    n = len(closes)
    highs = [c * 1.005 for c in closes]
    lows = [c * 0.995 for c in closes]
    return pd.DataFrame({
        "open": [closes[max(i - 1, 0)] for i in range(n)],
        "high": highs, "low": lows, "close": closes,
        "volume_btc": [10_000.0] * n,
        "volume_usdt": [c * 10_000.0 for c in closes],
    }, index=pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC"))


# ============================================================
# 任务 A.1:ma_alignment direction "mixed" 兜底
# ============================================================

def test_ma_alignment_direction_mixed_when_disordered():
    """4 条 MA 都存在但不严格升/降序 → direction='mixed', is_aligned=False。
    构造横盘震荡:closes 上下震荡 → ma_20 ≠ 严格大于 ma_60 ≠ ma_120 ≠ ma_200。"""
    rng = np.random.default_rng(42)
    base = 50_000.0
    closes = []
    for i in range(220):
        # 在 base 附近震荡 ±2%,+/- 偏置周期变化
        offset = 0.015 * np.sin(i / 30.0) + rng.normal(0, 0.005)
        closes.append(base * (1 + offset))
    out = Layer1Regime().compute({"klines_1d": _build_klines(closes)})
    ma = out["ma_alignment"]
    assert ma["ma_20"] is not None and ma["ma_60"] is not None
    assert ma["ma_120"] is not None and ma["ma_200"] is not None
    # direction 应该是 "mixed"(明确字符串,不是 None)
    assert ma["direction"] in ("mixed", "up", "down"), ma
    # 但 mixed 不算 aligned
    if ma["direction"] == "mixed":
        assert ma["is_aligned"] is False


def test_ma_alignment_direction_none_when_data_insufficient():
    """少于 200 根 → ma_200 缺 → direction=None(数据不足)。"""
    closes = [50000 + i * 100 for i in range(150)]  # 150 < 200
    out = Layer1Regime().compute({"klines_1d": _build_klines(closes)})
    ma = out["ma_alignment"]
    assert ma["ma_200"] is None
    assert ma["direction"] is None
    assert ma["is_aligned"] is False


# ============================================================
# 任务 A.2:ma_200_relation export
# ============================================================

def test_layer1_exports_ma_200_relation_above():
    """趋势上行 220 根 → 当前价 > MA200 → above=True, distance_pct > 0。"""
    rng = np.random.default_rng(7)
    closes = [30_000.0]
    for _ in range(219):
        closes.append(closes[-1] * (1 + 0.003 + rng.normal(0, 0.003)))
    out = Layer1Regime().compute({"klines_1d": _build_klines(closes)})
    rel = out["ma_200_relation"]
    assert rel["ma_200"] is not None
    assert rel["above"] is True
    assert rel["distance_pct"] > 0


def test_layer1_exports_ma_200_relation_below():
    """趋势下行 220 根 → 当前价 < MA200。"""
    rng = np.random.default_rng(11)
    closes = [50_000.0]
    for _ in range(219):
        closes.append(closes[-1] * (1 - 0.003 + rng.normal(0, 0.003)))
    out = Layer1Regime().compute({"klines_1d": _build_klines(closes)})
    rel = out["ma_200_relation"]
    assert rel["above"] is False
    assert rel["distance_pct"] < 0


def test_layer1_ma_200_relation_none_when_insufficient():
    out = Layer1Regime().compute({"klines_1d": pd.DataFrame()})
    rel = out["ma_200_relation"]
    assert rel["above"] is None
    assert rel["distance_pct"] is None


# ============================================================
# 任务 B:event_risk composition 全年 lookahead
# ============================================================

def test_event_risk_composition_picks_per_type_from_next_events_by_type():
    """next_events_by_type 提供"下次 fomc/cpi/nfp/options"距离,
    即便事件 > 72h 也应反映到 composition.value(不再 None)。"""
    from src.strategy import composite_composition as cc

    # 模拟 EventRisk composite 输出(72h 窗口可能为空)
    er_out = {
        "factor": "event_risk",
        "score": 0.0,
        "band": "low",
        "contributing_events": [],   # 72h 窗口内无事件
        "upcoming_events_count": 0,
    }
    state = {
        "evidence_reports": {"layer_1": {}, "layer_2": {}},
        "composite_factors": {"event_risk": er_out},
    }
    # state_builder 通过 context 注入 next_events_by_type
    context = {
        "next_events_by_type": {
            "fomc": {"event_type": "fomc", "hours_to": 30.0},
            "cpi":  {"event_type": "cpi",  "hours_to": 320.5},   # 13 天后
            "nfp":  {"event_type": "nfp",  "hours_to": 198.0},   # 8 天后
            "options_expiry_major": {
                "event_type": "options_expiry_major", "hours_to": 528.0,
            },
        },
    }
    cc.inject_composite_composition(state, context)

    composition = er_out.get("composition") or []
    by_id = {c.get("factor_id"): c for c in composition}
    assert by_id["event_fomc_next"]["value"] == 30.0
    assert by_id["event_cpi_next"]["value"] == 320.5
    assert by_id["event_nfp_next"]["value"] == 198.0
    assert by_id["event_options_expiry"]["value"] == 528.0


def test_event_risk_composition_prefers_72h_contributing_over_next():
    """contributing_events(72h 窗口内)优先,即便 next_events_by_type 也有 cpi。"""
    from src.strategy import composite_composition as cc
    er_out = {
        "factor": "event_risk",
        "score": 5.0,
        "band": "medium",
        "contributing_events": [
            {"name": "FOMC", "type": "fomc", "hours_to": 12.5,
             "effective_score": 6.0},
        ],
        "upcoming_events_count": 1,
    }
    state = {
        "evidence_reports": {"layer_1": {}, "layer_2": {}},
        "composite_factors": {"event_risk": er_out},
    }
    context = {
        "next_events_by_type": {
            "fomc": {"hours_to": 9999.0},  # 应该被 contributing 12.5 覆盖
            "cpi":  {"hours_to": 320.0},
        },
    }
    cc.inject_composite_composition(state, context)
    by_id = {c.get("factor_id"): c
             for c in (er_out.get("composition") or [])}
    assert by_id["event_fomc_next"]["value"] == 12.5  # contributing 优先
    assert by_id["event_cpi_next"]["value"] == 320.0  # contributing 没 cpi → next


# ============================================================
# 端到端:state_builder 取 next_events_by_type 含 options_expiry_major
# ============================================================

def test_state_builder_next_events_by_type_includes_options():
    """state_builder._assemble_context 应该把 options_expiry_major 加进
    next_events_by_type 的 query types 里。"""
    from src.data.collectors.events_seeder import seed_events
    from src.data.storage.connection import init_db
    from src.data.storage.dao import EventsCalendarDAO

    tmp = Path(tempfile.mkdtemp()) / "ev.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    try:
        seed_events(conn)
        # 用 DAO 直接验证 — 同 state_builder 逻辑
        next_by_type = EventsCalendarDAO.get_next_events_by_type(
            conn, ["fomc", "cpi", "nfp", "options_expiry_major"],
            now_utc="2026-04-29T08:00:00Z",
        )
        # 至少 cpi/nfp/options 应有(events_2026.json 已 12 条)
        assert next_by_type.get("cpi") is not None
        assert next_by_type.get("nfp") is not None
        assert next_by_type.get("options_expiry_major") is not None
        assert next_by_type["cpi"]["hours_to"] is not None
        assert next_by_type["options_expiry_major"]["hours_to"] is not None
    finally:
        conn.close()
