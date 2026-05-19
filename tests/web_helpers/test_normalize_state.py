"""tests/web_helpers/test_normalize_state.py — Sprint 1.8.2-A 测试。

§Z 端到端断言:不只 mock .called=True,断言字段值。
"""

from __future__ import annotations

import pytest

from src.web_helpers import normalize_state, translate
from src.web_helpers.labels import (
    ANTI_PATTERN_LABELS,
    EXTREME_EVENT_LABELS,
    L1_REGIME,
    L2_STANCE,
    L3_OPPORTUNITY_GRADE,
    MASTER_STATE,
)
from src.web_helpers.normalize_state import (
    _build_headline,
    _detect_schema,
    _first_sentence,
)


# ============================================================
# v13 真实形态测试
# ============================================================

def _v13_state_full() -> dict:
    """构造一个完整 v13 state(模拟 17:49 真生产数据形态)。"""
    return {
        "layers": {
            "l1": {
                "regime": "transition_up",
                "regime_stability": "stable",
                "volatility_regime": "normal",
                "confidence": 0.65,
                "key_observations": [
                    "EMA 排列开始向上",
                    "ADX 28,趋势力度温和",
                ],
                "contradicting_signals": [],
                "narrative": "BTC 处于上行过渡阶段。EMA-20 已上穿 EMA-50,但 ADX 仅 28,趋势力度温和。",
                "status": "success",
            },
            "l2": {
                "stance": "bullish",
                "stance_confidence_tier": "medium",
                "phase": "early",
                "key_levels": {"nearest_support": 75320,
                                "nearest_resistance": 78900},
                # Sprint Layer-B Cleanup: long_cycle_context 整段删除
                "narrative": "看多结构成立。HH+HL 序列连续 3 根。多头方向中等可信。",
                "key_observations": ["HH+HL 序列成立"],
                "confidence": 0.7,
            },
            "l3": {
                "opportunity_grade": "C",
                "execution_permission": "watch",
                "anti_pattern_flags": [],
                "narrative": "C 级机会(一般)。L2 stance 中等可信但 phase early,等待更确认信号。",
                "confidence": 0.6,
            },
            "l4": {
                "risk_tier": "moderate",
                "position_cap_multiplier": 0.78,
                "hard_invalidation_levels": [
                    {"price": 73200, "type": "swing_low"},
                ],
                "risk_breakdown": {"crowding_risk": 30,
                                   "structure_risk": 25},
                "narrative": "中等风险。funding Z=0.85 偏高但未极端。",
                "confidence": 0.85,
            },
            "l5": {
                "macro_stance": "neutral",
                "headwind_score": 28,
                "extreme_event_detected": False,
                "extreme_event_type": None,
                "narrative": "宏观中性。NASDAQ 30d +3.5%,DXY 小幅走弱。",
                "confidence": 0.8,
            },
            "master": {
                "state_transition": {"from_state": "FLAT", "to_state": "FLAT",
                                     "transition_reasoning":
                                         "L3=C 等待,无开仓信号"},
                "trade_plan": {"action": "watch", "direction": None,
                                "stop_loss": None},
                "position_cap_final": {"value": 0.4409},
                "narrative": "BTC 处于上行过渡 + L3=C 一般机会。保持空仓观察,等待 L3 升 B 级以上。",
                "key_observations": ["5 层判断:中等乐观但未确认"],
                "counter_arguments": ["若 swing_high 突破失败,趋势可能回到 chaos"],
                "confidence": 0.65,
            },
        },
        "validator": {"violations": [], "passed": True},
        "status": "ok",
        "context_summary": {
            # Sprint Layer-B Cleanup: 反模式 5 类 → 4 类(删 is_against_long_cycle)
            "anti_pattern_signals": {
                "is_extending_late_phase": False,
                "is_chasing_breakout_no_pullback": False,
                "is_failing_at_resistance": False,
                "is_after_extreme_event_no_reset": False,
            },
            "extreme_event_flags": {
                "flash_crash_detected_24h": False,
                "stablecoin_depeg_active": False,
                "geopolitical_conflict_active": False,
                "major_bank_crisis_signal": False,
                "regulatory_crackdown_recent": False,
            },
        },
    }


def test_v13_full_state_returns_v14_schema_version():
    """1.10-K-B commit 4:run_mode='ai_orchestrator' + 无显式 schema_version
    → 默认 'v14'(1.10-I commit 7 后 backend 默认写 v14)。"""
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert out["schema_version"] == "v14"


def test_v13_summary_card_action_state_translated():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert out["summary_card"]["action_state_label"] == "空仓观察"


def test_v13_summary_card_stance_translated():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert out["summary_card"]["stance_label"] == "看多"


def test_v13_summary_headline_for_flat_grade_c():
    """FLAT + grade=C → 观察型机会,不暗示已计划开仓。"""
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert "C 级观察型机会" in out["summary_card"]["headline"]
    assert "不创建 thesis" in out["summary_card"]["headline"]
    assert "保持空仓" in out["summary_card"]["headline"]


def test_v13_layer_cards_count_is_6():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert len(out["layer_cards"]) == 6
    layers = [c["layer"] for c in out["layer_cards"]]
    assert layers == ["l1", "l2", "l3", "l4", "l5", "master"]


def test_v13_layer_a_spot_strategy_passthrough_when_present():
    state = _v13_state_full()
    state["layer_a_spot_strategy"] = {
        "enabled": True,
        "a5_spot_adjudicator": {"spot_action": "dca_buy"},
    }
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert out["layer_a_spot_strategy"]["a5_spot_adjudicator"]["spot_action"] == "dca_buy"


def test_v13_layer_a_spot_strategy_none_for_old_runs():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert "layer_a_spot_strategy" in out
    assert out["layer_a_spot_strategy"] is None


def test_v13_l1_label_translated():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    l1_card = out["layer_cards"][0]
    assert l1_card["label"] == "上行过渡(方向偏多但还没确立)"


def test_v13_l3_label_contains_c_grade():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    l3_card = out["layer_cards"][2]
    assert "C" in l3_card["label"]


def test_v13_l1_narrative_passthrough_chinese():
    """narrative 字段直接透传,不重新生成。"""
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    l1_card = out["layer_cards"][0]
    assert l1_card["narrative"].startswith("BTC 处于上行过渡阶段")


def test_v13_l1_summary_is_first_sentence():
    """summary 是 narrative 第一个完整句子。"""
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    l1_card = out["layer_cards"][0]
    assert l1_card["summary"] == "BTC 处于上行过渡阶段。"


def test_v13_l4_supporting_data_includes_hard_invalidation():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    l4_card = out["layer_cards"][3]
    assert "hard_invalidation_levels" in l4_card["supporting_data"]
    val = l4_card["supporting_data"]["hard_invalidation_levels"]["value"]
    assert val[0]["price"] == 73200


def test_v13_master_card_secondary_includes_position_cap():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    master_card = out["layer_cards"][5]
    sec = " ".join(s for s in master_card["secondary_labels"] if s)
    assert "44" in sec or "0.44" in sec  # 0.4409 → "44.09%"


def test_v13_raw_preserved():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert "raw" in out
    assert out["raw"]["status"] == "ok"


# ============================================================
# anti_pattern + extreme_event 过滤
# ============================================================

def test_anti_patterns_all_false_returns_empty():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert out["anti_patterns_active"] == []


def test_anti_patterns_one_true_shows_only_that():
    state = _v13_state_full()
    state["context_summary"]["anti_pattern_signals"]["is_chasing_breakout_no_pullback"] = True
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert len(out["anti_patterns_active"]) == 1
    assert "突破追单" in out["anti_patterns_active"][0]


def test_extreme_events_all_false_returns_empty():
    out = normalize_state(_v13_state_full(), run_mode="ai_orchestrator")
    assert out["extreme_events_active"] == []


def test_extreme_events_flash_crash_true():
    state = _v13_state_full()
    state["context_summary"]["extreme_event_flags"]["flash_crash_detected_24h"] = True
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert len(out["extreme_events_active"]) == 1
    assert "闪崩" in out["extreme_events_active"][0]


# ============================================================
# v12 路径 graceful degrade
# ============================================================

def _v12_state_legacy() -> dict:
    """v12 老 state(无 layers,有 evidence_reports + adjudicator)。"""
    return {
        "evidence_reports": {
            "layer_1": {"regime": "trend_up",
                        "volatility_regime": "normal",
                        "narrative": "趋势向上,稳定。"},
            "layer_2": {"stance": "bullish", "phase": "mid",
                        "narrative": "多头中段。"},
            "layer_3": {"opportunity_grade": "B",
                        "execution_permission": "cautious_open",
                        "narrative": "B 级机会。"},
            "layer_4": {"overall_risk_level": "moderate",
                        "narrative": "中等风险。"},
            "layer_5": {"macro_environment": "supportive",
                        "narrative": "宏观顺风。"},
        },
        "adjudicator": {
            "action": "watch",
            "narrative": "v12 主裁文案,中等观望。",
            "confidence": 0.6,
        },
        "state_machine": {"current_state": "FLAT", "stable_in_state": True},
    }


def test_v12_legacy_does_not_crash():
    out = normalize_state(_v12_state_legacy(), run_mode=None)
    assert out["schema_version"] == "v12"


def test_v12_layer_cards_still_6():
    out = normalize_state(_v12_state_legacy(), run_mode=None)
    assert len(out["layer_cards"]) == 6


def test_v12_l1_label_translated():
    out = normalize_state(_v12_state_legacy(), run_mode=None)
    assert out["layer_cards"][0]["label"] == "上升趋势(明确向上)"


def test_v12_summary_card_action_state():
    out = normalize_state(_v12_state_legacy(), run_mode=None)
    assert out["summary_card"]["action_state_label"] == "空仓观察"


# ============================================================
# 边界:translate / 错值 / 空 state
# ============================================================

def test_translate_unknown_value_returns_default():
    """字典里没有的 key → '未知' 不抛 KeyError。"""
    assert translate(L1_REGIME, "nonexistent_regime") == "未知"
    assert translate(L2_STANCE, None) == "未知"
    assert translate(MASTER_STATE, "INVALID_STATE") == "未知"


def test_translate_known_value():
    assert translate(L1_REGIME, "trend_up") == "上升趋势(明确向上)"
    assert translate(L3_OPPORTUNITY_GRADE, "A") == "A 级机会(非常好)"


def test_normalize_state_empty_dict():
    """空 dict → 走 v12 路径,所有 label 显示 '未知',不抛。"""
    out = normalize_state({}, run_mode=None)
    assert out["schema_version"] == "v12"
    assert out["summary_card"]["action_state_label"] == "空仓观察"  # FLAT 默认


def test_normalize_state_invalid_input():
    """非 dict 输入 → 不抛,返回 invalid 标记。"""
    out = normalize_state(None, run_mode=None)  # type: ignore
    assert out["schema_version"] == "unknown"
    assert "数据无法解析" in out["summary_card"]["headline"]


# ============================================================
# Schema 检测
# ============================================================

def test_detect_schema_v14_by_run_mode():
    """1.10-K-B commit 4:run_mode='ai_orchestrator' 默认 'v14'。"""
    assert _detect_schema({}, "ai_orchestrator") == "v14"


def test_detect_schema_v14_by_layers_key():
    """1.10-K-B commit 4:state.layers 存在默认 'v14'。"""
    assert _detect_schema({"layers": {}}, None) == "v14"


def test_detect_schema_v12_default():
    assert _detect_schema({"evidence_reports": {}}, None) == "v12"
    assert _detect_schema({}, None) == "v12"


# 1.10-K-B commit 4:explicit schema_version 字段优先级
def test_detect_schema_explicit_v14_wins():
    """state.schema_version='v14' 覆盖任何 fallback 推断。"""
    assert _detect_schema(
        {"schema_version": "v14", "evidence_reports": {}}, None,
    ) == "v14"


def test_detect_schema_explicit_v13_backward_compat():
    """state.schema_version='v13' 老数据走 v13 路径(backward compat)。"""
    assert _detect_schema(
        {"schema_version": "v13", "layers": {}}, "ai_orchestrator",
    ) == "v13"


def test_detect_schema_explicit_v12_wins():
    assert _detect_schema(
        {"schema_version": "v12", "layers": {}}, None,
    ) == "v12"


def test_explicit_v13_state_outputs_v13_label():
    """显式 schema_version='v13' → output['schema_version'] == 'v13'(backward compat)。"""
    state = _v13_state_full()
    state["schema_version"] = "v13"
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert out["schema_version"] == "v13"


def test_explicit_v14_state_outputs_v14_label():
    """显式 schema_version='v14' → output['schema_version'] == 'v14'。"""
    state = _v13_state_full()
    state["schema_version"] = "v14"
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert out["schema_version"] == "v14"


# ============================================================
# Headline 拼装
# ============================================================

def test_headline_long_hold():
    assert _build_headline("LONG_HOLD", "B", "bullish") == "持有多单"


def test_headline_protection():
    assert "保护" in _build_headline("PROTECTION", "none", "neutral")


def test_headline_flat_grade_a():
    h = _build_headline("FLAT", "A", "bullish")
    assert "建议" in h or "高级别" in h


def test_headline_flat_grade_none():
    h = _build_headline("FLAT", "none", "neutral")
    assert "空仓" in h or "无机会" in h


def test_first_sentence_chinese():
    assert _first_sentence("BTC 处于上行过渡。EMA 排列向上。") == "BTC 处于上行过渡。"


def test_first_sentence_empty():
    assert _first_sentence("") == ""


def test_first_sentence_truncate():
    long = "字" * 100
    out = _first_sentence(long, max_chars=20)
    assert len(out) <= 21  # 20 + 省略号


# ============================================================
# v13 with run_mode unset still detects via layers
# ============================================================

def test_layered_detected_without_run_mode_defaults_v14():
    """run_mode=None 但 state 含 layers → 默认识别为 'v14'(1.10-K-B commit 4)。"""
    out = normalize_state(_v13_state_full(), run_mode=None)
    assert out["schema_version"] == "v14"
    assert out["layer_cards"][0]["label"] != "未知"


# ============================================================
# Sprint 1.8.2-A 收尾:decision_time UTC → BJT 转换
# ============================================================

def test_decision_time_format_bjt():
    """传入 UTC ISO → summary_card.decision_time 是 BJT 格式 'YYYY-MM-DD HH:MM BJT'。"""
    out = normalize_state(
        _v13_state_full(), run_mode="ai_orchestrator",
        generated_at_utc="2026-05-01T12:48:00Z",
    )
    # UTC 12:48 → BJT 20:48
    assert out["summary_card"]["decision_time"] == "2026-05-01 20:48 BJT"


def test_decision_time_handles_none_generated_at_utc():
    """generated_at_utc=None 时不抛,优先从 state 内部 timestamp 提。"""
    state = _v13_state_full()
    state["generated_at_utc"] = "2026-05-01T08:00:00Z"
    out = normalize_state(state, run_mode="ai_orchestrator",
                          generated_at_utc=None)
    # fallback 到 state['generated_at_utc'] → BJT 16:00
    assert out["summary_card"]["decision_time"] == "2026-05-01 16:00 BJT"


def test_decision_time_invalid_utc_returns_none():
    """无效 UTC 字符串 → decision_time=None,不抛。"""
    out = normalize_state(
        _v13_state_full(), run_mode="ai_orchestrator",
        generated_at_utc="not-a-date",
    )
    assert out["summary_card"]["decision_time"] is None


def test_decision_time_handles_iso_with_offset():
    """带 +00:00 后缀的 ISO 也支持。"""
    out = normalize_state(
        _v13_state_full(), run_mode="ai_orchestrator",
        generated_at_utc="2026-05-01T00:00:00+00:00",
    )
    assert out["summary_card"]["decision_time"] == "2026-05-01 08:00 BJT"
