"""tests/test_field_export_alignment.py — Sprint 1.5c 字段名漂移修复反退化。

§Z 真实数据驱动:
- 真 Layer1Regime / Layer2Direction compute 用充足 K 线
- 断言建模标准字段(timeframe_alignment / ma_alignment / impulse_extension_ratio
  等)真实导出到顶层,不是 None / KeyError
- composite_composition / factor_card_emitter 读到的不是 None
- events seed 全年 NFP/CPI/期权/FOMC 都齐
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.composite import BandPositionFactor, TruthTrendFactor
from src.evidence import Layer1Regime, Layer2Direction


# ============================================================
# Klines fixtures
# ============================================================

def _build_trend_1d(n: int = 220, start: float = 50_000.0,
                    daily_pct: float = 0.003, noise: float = 0.003,
                    seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = [start]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 + daily_pct + rng.normal(0, noise)))
    highs = [c * 1.008 for c in closes]
    lows = [c * 0.992 for c in closes]
    opens = [closes[i - 1] if i else closes[0] for i in range(n)]
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume_btc": [10_000.0] * n,
        "volume_usdt": [c * 10_000.0 for c in closes],
    }, index=pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"))


def _build_4h_from_1d(klines_1d: pd.DataFrame) -> pd.DataFrame:
    """用 1d 拟合 6 倍密度的 4h 序列(够 ADX-14 + EMA-20 算)。"""
    n = len(klines_1d) * 6
    closes_1d = klines_1d["close"].values
    rng = np.random.default_rng(7)
    closes = []
    for i in range(n):
        d_idx = i // 6
        base = closes_1d[d_idx]
        closes.append(base * (1 + rng.normal(0, 0.002)))
    highs = [c * 1.004 for c in closes]
    lows = [c * 0.996 for c in closes]
    return pd.DataFrame({
        "open": [closes[max(i - 1, 0)] for i in range(n)],
        "high": highs, "low": lows, "close": closes,
        "volume_btc": [3_000.0] * n,
        "volume_usdt": [c * 3_000.0 for c in closes],
    }, index=pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"))


def _build_weekly_from_1d(klines_1d: pd.DataFrame) -> pd.DataFrame:
    return klines_1d.resample("W").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume_btc": "sum", "volume_usdt": "sum",
    }).dropna()


# ============================================================
# 任务 A:L1 顶层字段导出
# ============================================================

def test_layer1_exports_required_fields():
    klines_1d = _build_trend_1d()
    klines_4h = _build_4h_from_1d(klines_1d)
    klines_1w = _build_weekly_from_1d(klines_1d)
    out = Layer1Regime().compute({
        "klines_1d": klines_1d,
        "klines_4h": klines_4h,
        "klines_1w": klines_1w,
    })
    # adx_14_4h:有充足 4h 数据应是数值
    assert out.get("adx_14_4h") is not None, (
        f"adx_14_4h 应有数值,实际 {out.get('adx_14_4h')}"
    )
    assert isinstance(out["adx_14_4h"], (int, float))

    # timeframe_alignment 是 dict 含 tf_4h / tf_1d / tf_1w / aligned / direction / score
    tfa = out.get("timeframe_alignment")
    assert isinstance(tfa, dict), f"timeframe_alignment 必须是 dict,实际 {tfa}"
    for k in ("tf_4h", "tf_1d", "tf_1w", "aligned", "direction", "score"):
        assert k in tfa, f"timeframe_alignment 缺 {k}: {tfa}"
    # tf_alignment 是同 dict alias(双 key 指向同一份内容)
    assert out.get("tf_alignment") == tfa

    # ma_alignment:dict 含 ma_20/60/120/200 + direction + is_aligned
    ma = out.get("ma_alignment")
    assert isinstance(ma, dict)
    for k in ("ma_20", "ma_60", "ma_120", "ma_200", "direction", "is_aligned"):
        assert k in ma, f"ma_alignment 缺 {k}: {ma}"
    # 强上涨数据 → 短期 MA 在长期 MA 上方 → direction=up + is_aligned=True
    assert ma["direction"] == "up"
    assert ma["is_aligned"] is True
    assert ma["ma_20"] > ma["ma_60"] > ma["ma_120"] > ma["ma_200"]


def test_layer1_insufficient_path_keeps_schema():
    """数据不足时 schema 仍保持(None / 占位 dict),不让下游报 KeyError。"""
    out = Layer1Regime().compute({
        "klines_1d": pd.DataFrame(), "klines_4h": None, "klines_1w": None,
    })
    assert out.get("adx_14_4h") is None
    tfa = out.get("timeframe_alignment")
    assert isinstance(tfa, dict)
    assert tfa.get("aligned") is False
    ma = out.get("ma_alignment")
    assert ma["is_aligned"] is False


# ============================================================
# 任务 B:L2 顶层字段导出
# ============================================================

def test_layer2_exports_band_position_fields():
    klines_1d = _build_trend_1d()
    klines_4h = _build_4h_from_1d(klines_1d)
    klines_1w = _build_weekly_from_1d(klines_1d)

    # 真跑 L1 + truth_trend + band_position 给 L2 当 context
    l1_out = Layer1Regime().compute({
        "klines_1d": klines_1d, "klines_4h": klines_4h, "klines_1w": klines_1w,
    })
    tt = TruthTrendFactor().compute({
        "klines_1d": klines_1d, "klines_4h": klines_4h, "klines_1w": klines_1w,
        "layer_1_output": l1_out,
    })
    bp = BandPositionFactor().compute({
        "klines_1d": klines_1d, "klines_4h": klines_4h, "klines_1w": klines_1w,
        "layer_1_output": l1_out,
    })

    l2_out = Layer2Direction().compute({
        "layer_1_output": l1_out,
        "composite_factors": {
            "truth_trend": tt, "band_position": bp,
            "cycle_position": {"cycle_position": "early_bull", "cycle_confidence": 0.7},
        },
        "klines_1d": klines_1d,
    })

    # 4 个新增顶层字段
    assert l2_out.get("impulse_extension_ratio") is not None
    assert isinstance(l2_out["impulse_extension_ratio"], (int, float))
    assert l2_out.get("latest_pullback_depth") is not None
    assert l2_out.get("ma_60_distance_pct") is not None
    assert isinstance(l2_out["ma_60_distance_pct"], (int, float))
    tp = l2_out.get("trend_position")
    assert isinstance(tp, dict)
    assert tp["basis"] == "impulse_extension_ratio"
    assert tp["estimated_pct_of_move"] == l2_out["impulse_extension_ratio"]


def test_layer2_insufficient_path_keeps_schema():
    out = Layer2Direction().compute({"layer_1_output": {}, "composite_factors": {}})
    assert out.get("impulse_extension_ratio") is None
    assert out.get("trend_position") is None


# ============================================================
# 任务 C:composite_composition 读到真值
# ============================================================

def test_composite_composition_reads_real_values_from_l1_l2():
    """L1 / L2 真实输出 → composite_composition 各 factor 的 value 不是 None。"""
    from src.strategy import composite_composition as cc

    klines_1d = _build_trend_1d()
    klines_4h = _build_4h_from_1d(klines_1d)
    klines_1w = _build_weekly_from_1d(klines_1d)

    l1_out = Layer1Regime().compute({
        "klines_1d": klines_1d, "klines_4h": klines_4h, "klines_1w": klines_1w,
    })
    tt = TruthTrendFactor().compute({
        "klines_1d": klines_1d, "klines_4h": klines_4h, "klines_1w": klines_1w,
        "layer_1_output": l1_out,
    })
    bp = BandPositionFactor().compute({
        "klines_1d": klines_1d, "klines_4h": klines_4h, "klines_1w": klines_1w,
        "layer_1_output": l1_out,
    })
    l2_out = Layer2Direction().compute({
        "layer_1_output": l1_out,
        "composite_factors": {
            "truth_trend": tt, "band_position": bp,
            "cycle_position": {"cycle_position": "early_bull", "cycle_confidence": 0.7},
        },
        "klines_1d": klines_1d,
    })

    state = {
        "evidence_reports": {"layer_1": l1_out, "layer_2": l2_out},
        "composite_factors": {
            "truth_trend": tt, "band_position": bp,
            "cycle_position": {"cycle_position": "early_bull", "cycle_confidence": 0.7},
        },
    }
    cc.inject_composite_composition(state, context={})

    # 抽取 truth_trend 的 composition,断言 price_tf_alignment / price_ma_alignment 命中
    tt_block = state["composite_factors"]["truth_trend"]
    composition = tt_block.get("composition") or []
    by_id = {c.get("factor_id"): c for c in composition}
    assert by_id.get("price_tf_alignment", {}).get("value") is not None, (
        f"price_tf_alignment value 应非 None: {by_id.get('price_tf_alignment')}"
    )
    assert by_id.get("price_ma_stack", {}).get("value") is not None, (
        f"price_ma_stack value 应非 None: {by_id.get('price_ma_stack')}"
    )

    bp_block = state["composite_factors"]["band_position"]
    bp_comp = bp_block.get("composition") or []
    bp_by_id = {c.get("factor_id"): c for c in bp_comp}
    # ma_60_distance / pullback_depth 来自 L2 顶层
    assert bp_by_id.get("price_ma_60_distance", {}).get("value") is not None
    assert bp_by_id.get("price_pullback_depth", {}).get("value") is not None


# ============================================================
# 任务 D:events seed 覆盖率
# ============================================================

def test_events_seed_full_year_coverage():
    """data/seeds/events_2026.json 应覆盖全年 NFP/CPI/期权/FOMC。"""
    repo_root = Path(__file__).resolve().parent.parent
    path = repo_root / "data" / "seeds" / "events_2026.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events") or []
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
    assert by_type.get("nfp", 0) >= 12, f"NFP 至少 12 条:{by_type}"
    assert by_type.get("cpi", 0) >= 12, f"CPI 至少 12 条:{by_type}"
    assert by_type.get("options_expiry_major", 0) >= 12, (
        f"options_expiry_major 至少 12 条:{by_type}"
    )
    assert by_type.get("fomc", 0) >= 8, f"FOMC 至少 8 条:{by_type}"


def test_events_seed_utc_trigger_time_format():
    """utc_trigger_time 必须是 ISO 形如 'YYYY-MM-DDTHH:MM:SSZ'。"""
    import re
    repo_root = Path(__file__).resolve().parent.parent
    path = repo_root / "data" / "seeds" / "events_2026.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    for e in data["events"]:
        assert iso_pat.match(e["utc_trigger_time"] or ""), (
            f"event {e['event_id']} utc_trigger_time 格式异常:"
            f"{e['utc_trigger_time']}"
        )


def test_events_seeder_loads_full_year():
    """真跑 EventsSeeder 走 events_2026.json,upsert 后 events_calendar 表
    NFP/CPI/期权/FOMC 各类数量正确。"""
    import sqlite3
    import tempfile
    from pathlib import Path

    from src.data.collectors.events_seeder import seed_events
    from src.data.storage.connection import init_db

    tmp = Path(tempfile.mkdtemp()) / "events.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    try:
        seed_events(conn)
        rows = conn.execute(
            "SELECT event_type, COUNT(*) FROM events_calendar GROUP BY event_type"
        ).fetchall()
        by_type = dict(rows)
    finally:
        conn.close()
    assert by_type.get("nfp", 0) >= 12
    assert by_type.get("cpi", 0) >= 12
    assert by_type.get("options_expiry_major", 0) >= 12
    assert by_type.get("fomc", 0) >= 8
