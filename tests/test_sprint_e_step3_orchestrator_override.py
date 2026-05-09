"""Sprint E Step 3 — orchestrator 因子粒度 confidence 降级 + data_missing skip。

§Z 端到端:mock 不同 fresh_ratio,断言 layer.health/confidence + AI 调用次数
(用 mock 计数器)真按规则变化。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.ai.orchestrator import (
    _apply_factor_grain_override,
    _build_data_missing_stub,
    _stale_state_from_context,
)
from src.strategy.factor_dependencies import (
    SRC_BINANCE_KLINE,
    SRC_COINGLASS_DERIV,
    SRC_FRED_MACRO,
    SRC_GLASSNODE_ONCHAIN,
)


# ============================================================
# 1. _stale_state_from_context: 向后兼容
# ============================================================

def test_stale_state_empty_context():
    s, h = _stale_state_from_context({})
    assert s == {} and h == {}


def test_stale_state_extracts_from_context():
    ctx = {
        "_source_stale_map": {SRC_BINANCE_KLINE: False, SRC_GLASSNODE_ONCHAIN: True},
        "_source_hours_map": {SRC_BINANCE_KLINE: 0.5, SRC_GLASSNODE_ONCHAIN: 67.5},
    }
    s, h = _stale_state_from_context(ctx)
    assert s[SRC_GLASSNODE_ONCHAIN] is True
    assert h[SRC_GLASSNODE_ONCHAIN] == 67.5


# ============================================================
# 2. _build_data_missing_stub
# ============================================================

def test_data_missing_stub_marks_layer_skipped():
    agent = MagicMock()
    agent._fallback_output.return_value = {
        "agent": "l2_direction",
        "stance": "neutral",
        "stance_confidence": 0.5,  # 必须被覆盖到 0.0
        "confidence": 0.5,
        "narrative": "old fallback narrative",
        "notes": [],
    }
    stub = _build_data_missing_stub(2, agent, 0.0)
    assert stub["status"] == "degraded_data_missing"
    assert stub["confidence"] == 0.0
    assert stub["stance_confidence"] == 0.0
    assert "fresh_ratio=0" in stub["narrative"]
    assert stub["_factor_grain"]["data_missing"] is True
    assert stub["_factor_grain"]["ai_skipped"] is True
    assert "factor_grain_data_missing_ai_skipped" in stub["notes"]


# ============================================================
# 3. _apply_factor_grain_override:不同 fresh_ratio 的输出
# ============================================================

def test_override_no_change_when_all_fresh():
    out = {"confidence": 0.85, "status": "success"}
    res = _apply_factor_grain_override(1, out, 1.0)
    assert res["confidence"] == 0.85
    assert res["status"] == "success"
    assert res["_factor_grain"]["fresh_ratio"] == 1.0


def test_override_partial_stale_60pct():
    """fresh_ratio=0.6(>= 0.5)→ confidence × 0.6,status=degraded_factor_grain。"""
    out = {"confidence": 0.85, "status": "success", "notes": []}
    res = _apply_factor_grain_override(2, out, 0.6)
    assert abs(res["confidence"] - 0.85 * 0.6) < 0.001
    assert res["status"] == "degraded_factor_grain"
    assert any("fresh_ratio=0.60" in n for n in res["notes"])
    assert res["_factor_grain"]["confidence_multiplier"] == 0.6


def test_override_severe_stale_30pct():
    """fresh_ratio=0.3(< 0.5)→ confidence × 0.3。"""
    out = {"confidence": 0.85, "status": "success"}
    res = _apply_factor_grain_override(2, out, 0.3)
    assert abs(res["confidence"] - 0.85 * 0.3) < 0.001
    assert res["_factor_grain"]["confidence_multiplier"] == 0.3


def test_override_zero_ratio_falls_to_data_missing():
    out = {"confidence": 0.85, "stance_confidence": 0.7, "status": "success"}
    res = _apply_factor_grain_override(2, out, 0.0)
    assert res["status"] == "degraded_data_missing"
    assert res["confidence"] == 0.0
    assert res["stance_confidence"] == 0.0


def test_override_preserves_existing_degraded_status():
    """原本就 degraded_l2_failed → 保留,只调 confidence。"""
    out = {"confidence": 0.5, "status": "degraded_l2_failed"}
    res = _apply_factor_grain_override(2, out, 0.6)
    assert res["status"] == "degraded_l2_failed"  # 不被覆盖回 degraded_factor_grain


# ============================================================
# 4. orchestrator 端到端:mock AI 计数器
# ============================================================

def _make_orchestrator(stale_map):
    """构造一个 orchestrator,mock 6 个 agent.analyze 让它不调真 AI。"""
    from src.ai.orchestrator import AIOrchestrator
    from src.ai.agents.chart_renderer import ChartRenderer

    fake_chart = MagicMock(spec=ChartRenderer)
    fake_chart.render_l1_chart.return_value = None
    fake_chart.render_l2_chart.return_value = None
    fake_chart.render_l4_chart.return_value = None

    agents = {}
    call_counts: dict[str, int] = {}
    for name in ("l1", "l2", "l3", "l4", "l5", "master"):
        a = MagicMock()
        a.AGENT_NAME = name

        def _make_analyze(_name=name):
            def _analyze(input_dict, *, client=None):
                call_counts[_name] = call_counts.get(_name, 0) + 1
                return {
                    "agent": _name, "status": "success",
                    "confidence": 0.7,
                    "stance_confidence": 0.7,
                    "narrative": f"{_name} normal",
                    "notes": [],
                }
            return _analyze
        a.analyze.side_effect = _make_analyze()
        a._fallback_output.return_value = {
            "agent": name, "status": "fallback",
            "confidence": 0.0, "stance_confidence": 0.0,
            "narrative": f"{name} fallback",
            "notes": [],
        }
        agents[name] = a

    orch = AIOrchestrator(chart_renderer=fake_chart, agents=agents)
    return orch, call_counts


def _mk_context(stale_map, hours_map):
    """最小 orchestrator context — 只放 Sprint E 守卫真用得到的字段。"""
    return {
        "_source_stale_map": stale_map,
        "_source_hours_map": hours_map,
        "_shared": {"klines_1d": [], "current_close": 50000.0},
        "l1": {"klines_1d_30d_close": []},
        "l2": {"computed_indicators": {}},
        "l3": {"current_state": "FLAT"},
        "l4": {"computed_indicators": {}},
        "l5": {"computed_macro_indicators": {}, "events_calendar_72h": [],
                "extreme_event_flags": {}},
        "master": {},
    }


def test_orchestrator_skips_ai_when_l1_data_missing():
    """K 线 stale → L1 fresh_ratio=0 → 跳过 L1 AI 调用。"""
    stale_map = {SRC_BINANCE_KLINE: True, SRC_GLASSNODE_ONCHAIN: False,
                 SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False}
    hours_map = {SRC_BINANCE_KLINE: 5.0}
    orch, counts = _make_orchestrator(stale_map)
    ctx = _mk_context(stale_map, hours_map)
    result = orch.run_full_a(ctx)

    assert counts.get("l1", 0) == 0, "L1 AI 不应被调用(数据全 stale)"
    l1 = result["layers"]["l1"]
    assert l1["status"] == "degraded_data_missing"
    assert l1["_factor_grain"]["ai_skipped"] is True


def test_orchestrator_calls_ai_when_partial_stale():
    """Glassnode stale 但 K 线 fresh → L2 partial → 仍调 AI 但 confidence 降。"""
    stale_map = {SRC_BINANCE_KLINE: False, SRC_GLASSNODE_ONCHAIN: True,
                 SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False}
    hours_map = {SRC_GLASSNODE_ONCHAIN: 67.5}
    orch, counts = _make_orchestrator(stale_map)
    ctx = _mk_context(stale_map, hours_map)
    result = orch.run_full_a(ctx)

    # L2 仍调用 AI
    assert counts.get("l2", 0) == 1
    l2 = result["layers"]["l2"]
    assert "_factor_grain" in l2
    assert l2["_factor_grain"]["fresh_ratio"] < 1.0
    # confidence 被降
    assert l2["confidence"] < 0.7
    assert l2["status"] == "degraded_factor_grain"


def test_orchestrator_l3_data_missing_when_l1_l2_data_missing():
    """L1 + L2 都 data_missing → L3 也 data_missing(衍生联动)。"""
    stale_map = {s: True for s in (SRC_BINANCE_KLINE, SRC_GLASSNODE_ONCHAIN)}
    hours_map = {s: 100.0 for s in stale_map}
    stale_map.update({SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False})
    orch, counts = _make_orchestrator(stale_map)
    ctx = _mk_context(stale_map, hours_map)
    result = orch.run_full_a(ctx)

    assert counts.get("l1", 0) == 0   # L1 跳过
    assert counts.get("l2", 0) == 0   # L2 也跳过(K 线 stale)
    assert counts.get("l3", 0) == 0   # L3 衍生联动跳过
    l3 = result["layers"]["l3"]
    assert l3["status"] == "degraded_data_missing"


def test_orchestrator_no_stale_map_no_override():
    """state_builder 没注入 stale_map → 走老路径,所有层正常调 AI。"""
    orch, counts = _make_orchestrator({})
    ctx = {
        "_shared": {"klines_1d": [], "current_close": 50000.0},
        "l1": {}, "l2": {}, "l3": {}, "l4": {}, "l5": {}, "master": {},
    }
    result = orch.run_full_a(ctx)

    # 6 个 agent 全调用过(无 stale 守卫干扰)
    assert counts.get("l1", 0) == 1
    assert counts.get("l2", 0) == 1
    assert counts.get("l3", 0) == 1
    assert counts.get("l4", 0) == 1
    assert counts.get("l5", 0) == 1
    # 没有 _factor_grain 字段(因为没 stale_map)
    for lid in ("l1", "l2", "l4", "l5"):
        assert "_factor_grain" not in result["layers"][lid]


# ============================================================
# 5. compute_stale_state helper(state_builder 用)
# ============================================================

def test_compute_stale_state_returns_two_dicts(tmp_path):
    """compute_stale_state(conn) 返 (stale_map, hours_map),分别给
    orchestrator 子 agent。空 DB 走数据表 fallback 也 OK。"""
    import sqlite3
    from src.data.freshness import compute_stale_state
    from src.data.storage.connection import init_db

    db = tmp_path / "stale.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        stale, hours = compute_stale_state(conn)
        assert isinstance(stale, dict) and isinstance(hours, dict)
        # 4 个 source 全在
        for src in (SRC_BINANCE_KLINE, SRC_COINGLASS_DERIV,
                    SRC_GLASSNODE_ONCHAIN, SRC_FRED_MACRO):
            assert src in stale
            assert src in hours
        # 空 DB → 全 stale(fallback null)
        assert all(stale.values()) is True
    finally:
        conn.close()
