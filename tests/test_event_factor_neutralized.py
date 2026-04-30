"""tests/test_event_factor_neutralized.py — Sprint 1.5q.1 §X 反退化(真删版)。

EventRiskFactor 已在 Sprint 1.5q.1 真删:
- src/composite/event_risk.py 整文件 rm
- composite/__init__.py 不再 export EventRiskFactor
- pipeline/state_builder Stage 9 整段删
- L4 risk 删除 step 5(× event_risk)+ permission 不再含 l4_event_risk 建议
- 事件卡 impact_direction='neutral',strategy_impact='参考信息'

§Z 反退化锁:确保未来不被恢复。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.evidence.layer4_risk import _compose_position_cap
from src.strategy.factor_card_emitter import _emit_events_reference


# ============================================================
# A. EventRiskFactor 整文件已 rm — import 必须 ImportError
# ============================================================

def test_event_risk_factor_import_fails():
    """1.5q.1:src/composite/event_risk.py 已 rm,import 必须报 ModuleNotFoundError。"""
    with pytest.raises((ImportError, ModuleNotFoundError)):
        from src.composite.event_risk import EventRiskFactor  # noqa: F401


def test_composite_init_does_not_export_event_risk():
    """composite/__init__.py 的 __all__ 不应含 EventRiskFactor。"""
    import src.composite as composite_pkg
    assert "EventRiskFactor" not in (composite_pkg.__all__ or [])
    assert not hasattr(composite_pkg, "EventRiskFactor")


def test_state_builder_does_not_import_event_risk():
    """pipeline.state_builder 不再 import EventRiskFactor(只允许在解释性注释里)。"""
    src = (
        Path(__file__).resolve().parent.parent
        / "src" / "pipeline" / "state_builder.py"
    ).read_text(encoding="utf-8")
    # 检查每行:不能在 import 段或 active code 里出现 EventRiskFactor
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # 注释允许保留 1.5q.1 删除标记
        assert "EventRiskFactor" not in line, (
            f"state_builder.py 活跃代码仍含 EventRiskFactor: {line!r}"
        )


# ============================================================
# B. L4 删除 step 5 (× event_risk)
# ============================================================

def test_position_cap_composition_no_after_l4_event():
    """_compose_position_cap 输出不再含 after_l4_event / l4_event_risk_multiplier。"""
    final, comp = _compose_position_cap(
        base_pct=70.0,
        overall_risk_level="moderate",
        crowding_score=2,
        macro_headwind_score=0.0,
        event_risk_score=8.0,  # 即使传入也不应影响(向下兼容 signature)
        hard_floor_pct=15.0,
    )
    assert "after_l4_event" not in comp
    assert "l4_event_risk_multiplier" not in comp


def test_position_cap_composition_has_4_steps():
    """1.5q.1:剩 4 步乘数(base + l4_risk + l4_crowding + l5_macro_headwind)。"""
    final, comp = _compose_position_cap(
        base_pct=70.0,
        overall_risk_level="moderate",
        crowding_score=2,
        macro_headwind_score=0.0,
        event_risk_score=8.0,
        hard_floor_pct=15.0,
    )
    assert "l4_risk_multiplier" in comp
    assert "l4_crowding_multiplier" in comp
    assert "l5_macro_headwind_multiplier" in comp
    assert "l4_event_risk_multiplier" not in comp


# ============================================================
# C. 事件卡 impact_direction always neutral
# ============================================================

def test_event_card_impact_direction_always_neutral():
    cards = _emit_events_reference(
        events=[],
        today="20260430",
        next_by_type={
            "fomc": {"hours_to": 1.0, "event_type": "fomc"},
            "cpi":  {"hours_to": 6.0, "event_type": "cpi"},
            "nfp":  {"hours_to": 100.0, "event_type": "nfp"},
        },
    )
    for c in cards:
        assert c["impact_direction"] == "neutral", (
            f"event card {c.get('card_id')} impact_direction={c['impact_direction']},"
            "应永远 neutral"
        )


def test_event_card_strategy_impact_says_reference_only():
    cards = _emit_events_reference(
        events=[], today="20260430",
        next_by_type={"fomc": {"hours_to": 11.5, "event_type": "fomc"}},
    )
    fomc_card = next(c for c in cards if "fomc" in c["card_id"])
    assert "参考信息" in fomc_card["strategy_impact"]


def test_event_card_plain_interpretation_no_high_risk_label():
    cards = _emit_events_reference(
        events=[], today="20260430",
        next_by_type={"fomc": {"hours_to": 5.0, "event_type": "fomc"}},
    )
    for c in cards:
        assert "高风险窗口" not in c["plain_interpretation"]
        assert "系统降档" not in c["plain_interpretation"]


# ============================================================
# D. composite_factors 输出 5 个,不含 event_risk(end-to-end)
# ============================================================

def test_e2e_composite_factors_does_not_include_event_risk(tmp_path):
    """关键反退化:跑完 pipeline 后 composite_factors 不应有 'event_risk' 键。

    注入 fake ai_caller 跳过外部 AI 调用,加快测试。空 DB → fallback,
    但 composite_factors / L4 输出仍能 inspect。
    """
    import sqlite3
    from src.data.storage.connection import init_db
    from src.pipeline import StrategyStateBuilder

    db_path = tmp_path / "e2e.db"
    init_db(db_path=db_path, verbose=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # fake AI caller:返回 mock degraded 输出,避免外部 HTTP
        def _fake_ai(*args, **kwargs):
            return {
                "status": "degraded_skip",
                "summary_text": None,
                "model": "mock",
                "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
                "error": None,
            }
        builder = StrategyStateBuilder(conn, ai_caller=_fake_ai)
        result = builder.run(run_trigger="manual_e2e_1_5q1")
        state = getattr(result, "state", None) or {}
        comp = state.get("composite_factors") or {}
        assert "event_risk" not in comp, (
            f"composite_factors 仍含 event_risk:keys={list(comp.keys())}"
        )
        # L4 cap composition 不含 event_risk 字段
        l4 = (state.get("evidence_reports") or {}).get("layer_4") or {}
        cap_comp = l4.get("position_cap_composition") or {}
        assert "after_l4_event" not in cap_comp
        assert "l4_event_risk_multiplier" not in cap_comp
        # permission suggestions 不含 l4_event_risk
        perm_comp = l4.get("permission_composition") or {}
        suggestions = perm_comp.get("suggestions") or {}
        assert "l4_event_risk" not in suggestions
    finally:
        conn.close()
