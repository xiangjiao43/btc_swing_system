"""tests/test_human_readable_style.py — Sprint 2.7-readability 守门员

对照 docs/style_guide_human_readable.md §3 的禁止术语清单,扫描 4 个人读输出层
的所有展示字段,确保未来任何重写都不再引入"机器味"字符串。
"""

from __future__ import annotations

import re
from typing import Any

from src.evidence.pillars import inject_pillars
from src.evidence.plain_reading import inject_plain_readings
from src.strategy.composite_composition import inject_composite_composition
from src.strategy.factor_card_emitter import emit_factor_cards
from src.strategy.no_opportunity_narrator import (
    SCENARIO_COLD_START,
    SCENARIO_EXTREME_EVENT,
    SCENARIO_FALLBACK_DEGRADED,
    SCENARIO_GRADE_NONE,
    SCENARIO_PERMISSION_RESTRICTED,
    SCENARIO_POSITION_CAP_ZERO,
    SCENARIO_POST_PROTECTION,
    SCENARIO_PROTECTION,
    generate_no_opportunity_narrative,
)


# 禁止模式清单(对照风格指南 §3)
FORBIDDEN_PATTERNS = [
    (r'\bstance\s*=\s*\w+', 'stance=*'),
    (r'\bregime\s*=\s*\w+', 'regime=*'),
    (r'\bphase\s*=\s*\w+', 'phase=*'),
    # 允许 "建模 §X.Y" 形式(用户明确放行,见 sprint_2_7_no_opp_narrative spec);
    # 其它裸 §X.Y 引用仍禁止
    (r'(?<!建模 )§\d+\.\d+', '裸 §X.Y 章节引用(用"建模 §X.Y"代替)'),
    (r'\bL\d\.\w+_\w+', 'L*. 字段路径(如 L4.crowding_multiplier)'),
    (r'\bambush_only\b', 'ambush_only'),
    (r'\bcautious_open\b', 'cautious_open'),
    (r'\bcan_open\b', 'can_open'),
    (r'\bno_chase\b', 'no_chase'),
    (r'\bhold_only\b', 'hold_only'),
    (r'\btrade_plan\b', 'trade_plan(用"交易计划")'),
    (r'\btransition_up\b|\btransition_down\b', 'transition_*'),
    # 周期英文枚举(出现在 strategy_impact / interpretation 时禁止;但允许在
    # "中文标签 (英文)" 这种解释性括号中,故只匹配独立出现)
    (r'\bearly_bull\b', 'early_bull'),
    (r'\bmid_bull\b', 'mid_bull'),
    (r'\blate_bull\b', 'late_bull'),
    (r'\bearly_bear\b', 'early_bear'),
    (r'\bmid_bear\b', 'mid_bear'),
    (r'\blate_bear\b', 'late_bear'),
]


# ============================================================
# 公共 sample state
# ============================================================

def _build_sample_state() -> dict[str, Any]:
    """构造一组涵盖各种状态的 mock state。"""
    return {
        "evidence_reports": {
            "layer_1": {
                "regime": "trend_up",
                "regime_stability": "stable",
                "volatility_regime": "normal",
                "adx_14_1d": 28.0,
                "timeframe_alignment": {"aligned": True},
                "volatility_level": "normal",
                "volatility_percentile": 55.0,
                "health_status": "healthy",
            },
            "layer_2": {
                "stance": "bullish",
                "stance_confidence": 0.62,
                "phase": "mid",
                "structure_features": {
                    "hh_count": 3, "hl_count": 2, "lh_count": 1, "ll_count": 0,
                    "latest_structure": "HH",
                },
                "trend_position": {"estimated_pct_of_move": 65.0},
                "long_cycle_context": {
                    "cycle_position": "early_bull", "cycle_confidence": 0.7,
                },
                "ma_60_distance_pct": 0.05,
                "latest_pullback_depth": 0.3,
                "health_status": "healthy",
            },
            "layer_3": {
                "opportunity_grade": "B",
                "execution_permission": "cautious_open",
                "anti_pattern_flags": [],
            },
            "layer_4": {
                "overall_risk_level": "moderate",
                "position_cap": 0.35,
                "execution_permission": "cautious_open",
                "hard_invalidation_levels": [
                    {"price": 80000, "priority": 1, "basis": "swing low",
                     "confirmation_timeframe": "4H"},
                ],
                "position_cap_composition": {
                    "base": 70, "final": 35,
                },
                "permission_composition": {
                    "merged_before_buffer": "cautious_open",
                    "final_permission": "cautious_open",
                },
            },
            "layer_5": {
                "macro_stance": "neutral",
                "macro_environment": "neutral",
                "extreme_event_detected": False,
                "data_completeness_pct": 80.0,
                "structured_macro": {"DXY": 104.0, "VIX": 18.5},
                "active_event_summaries": [],
                "active_macro_tags": [],
            },
        },
        "composite_factors": {
            "truth_trend": {
                "score": 6,
                "composition": [
                    {"factor_id": "price_adx_14_1d", "value": 28.5},
                ],
            },
            "band_position": {
                "phase": "mid",
                "composition": [
                    {"factor_id": "price_swing_extension_ratio", "value": 0.65},
                ],
            },
            "cycle_position": {
                "cycle_position": "early_bull",
                "composition": [
                    {"factor_id": "onchain_mvrv_z", "value": 1.5},
                ],
            },
            "crowding": {
                "score": 3,
                "composition": [
                    {"factor_id": "derivatives_funding_rate_current", "value": 0.0001},
                ],
            },
            "macro_headwind": {
                "score": -1,
                "composition": [
                    {"factor_id": "macro_vix_current", "value": 18.5},
                ],
            },
            "event_risk": {
                "score": 0,
                "composition": [
                    {"factor_id": "event_fomc_next", "value": None},
                ],
            },
        },
    }


def _check_text(label: str, text: str) -> None:
    """对单个字符串跑禁止模式扫描,失败时报告完整 label + pattern + text。"""
    if not isinstance(text, str) or not text:
        return
    for pattern, name in FORBIDDEN_PATTERNS:
        m = re.search(pattern, text)
        assert m is None, (
            f"\n{label}\n"
            f"  含禁止术语 [{name}] (pattern: {pattern})\n"
            f"  匹配到: '{m.group()}'\n"
            f"  文本: {text[:200]}"
        )


# ============================================================
# Pillars
# ============================================================

class TestPillarsNoMachineTerms:
    def test_inject_pillars_all_layers(self):
        state = _build_sample_state()
        inject_pillars(state)
        for layer_id in range(1, 6):
            layer = state["evidence_reports"][f"layer_{layer_id}"]
            _check_text(f"L{layer_id}.core_question",
                        layer.get("core_question") or "")
            _check_text(f"L{layer_id}.downstream_hint",
                        layer.get("downstream_hint") or "")
            _check_text(f"L{layer_id}.completeness_warning",
                        layer.get("completeness_warning") or "")
            for i, p in enumerate(layer.get("pillars") or []):
                _check_text(f"L{layer_id}.pillars[{i}].interpretation",
                            p.get("interpretation") or "")
            rt = layer.get("rule_trace") or {}
            if rt:
                _check_text(f"L{layer_id}.rule_trace.matched_rule",
                            rt.get("matched_rule") or "")
                for i, c in enumerate(rt.get("upgrade_conditions") or []):
                    _check_text(f"L{layer_id}.rule_trace.upgrade_conditions[{i}]",
                                str(c))


# ============================================================
# Composite narratives
# ============================================================

class TestCompositeNarrativesNoMachineTerms:
    def test_inject_composite_composition_all_keys(self):
        state = _build_sample_state()
        inject_composite_composition(state, context={})
        for key, c in (state.get("composite_factors") or {}).items():
            if not isinstance(c, dict):
                continue
            for field in ("current_analysis", "strategy_impact",
                          "value_interpretation", "rule_description",
                          "affects_layer"):
                _check_text(f"composite[{key}].{field}",
                            c.get(field) or "")


# ============================================================
# Plain reading
# ============================================================

class TestPlainReadingNoMachineTerms:
    def test_inject_plain_readings_all_layers(self):
        state = _build_sample_state()
        inject_plain_readings(state)
        for layer_id in range(1, 6):
            text = (state["evidence_reports"][f"layer_{layer_id}"]
                    .get("plain_reading") or "")
            _check_text(f"L{layer_id}.plain_reading", text)


# ============================================================
# Factor cards
# ============================================================

class TestFactorCardsNoMachineTerms:
    def test_emit_factor_cards_no_machine_terms(self):
        state = _build_sample_state()
        cards = emit_factor_cards(state, context={})
        assert len(cards) > 0
        for card in cards:
            cid = card.get("card_id", "?")
            _check_text(f"card[{cid}].plain_interpretation",
                        card.get("plain_interpretation") or "")
            _check_text(f"card[{cid}].strategy_impact",
                        card.get("strategy_impact") or "")


# ============================================================
# No-opportunity narrator(8 个场景)
# ============================================================

class TestNoOpportunityNarratorNoMachineTerms:
    """8 种 AI 未触发场景的 narrator 输出全部扫描禁止术语。"""

    _ALL_SCENARIOS = [
        ("cold_start",
         {"cold_start_warming_up": True},
         {"meta": {"cold_start": {"days_remaining": 5}}}),
        ("extreme_event",
         {"l5_extreme_event_detected": True},
         {}),
        ("protection",
         {"state_machine_current": "PROTECTION"},
         {}),
        ("fallback_degraded",
         {"fallback_level": "level_2"},
         {}),
        ("post_protection",
         {"state_machine_current": "POST_PROTECTION_REASSESS"},
         {}),
        ("permission_restricted",
         {"l3_permission": "watch"},
         {}),
        ("position_cap_zero",
         {"l4_position_cap": 0.0},
         {}),
        ("grade_none",
         {"l3_grade": "none"},
         {"evidence_reports": {
             "layer_1": {"regime": "transition_up"},
             "layer_2": {"stance": "neutral"},
             "layer_3": {"rule_trace": {
                 "upgrade_conditions": [
                     "做多信心达到 55% 以上",
                     "趋势状态稳定",
                     "波段位置出现初段或中段",
                 ]}},
             "layer_5": {"macro_stance": "neutral"},
         }}),
    ]

    def test_all_scenarios_no_machine_terms(self):
        for label, facts, state in self._ALL_SCENARIOS:
            out = generate_no_opportunity_narrative(facts, state)
            _check_text(f"narrator[{label}].narrative", out["narrative"])
            for i, d in enumerate(out["primary_drivers"]):
                _check_text(f"narrator[{label}].primary_drivers[{i}].text",
                            d.get("text") or "")
            for i, c in enumerate(out["counter_arguments"]):
                _check_text(f"narrator[{label}].counter_arguments[{i}].text",
                            c.get("text") or "")
            for i, s in enumerate(out["what_would_change_mind"]):
                _check_text(f"narrator[{label}].what_would_change_mind[{i}]",
                            str(s))
