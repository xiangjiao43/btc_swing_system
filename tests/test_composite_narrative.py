"""tests/test_composite_narrative.py — Sprint 2.5-B-rewrite

验证 inject_composite_composition 注入的纯模板叙事:
  1. current_analysis / strategy_impact 字段存在且非空
  2. 同样输入永远产出同样文字(deterministic)
  3. 数据全缺失 → fallback 文案
  4. 部分缺失 → 文本不提缺失项,只用有值
  5. 零 AI 依赖(import 检查)
"""

from __future__ import annotations

import importlib

from src.strategy.composite_composition import (
    inject_composite_composition,
    _NARRATIVE_GENERATORS,
    _FALLBACK_TEXT,
    _cycle_position_narrative,
    _truth_trend_narrative,
    _band_position_narrative,
    _crowding_narrative,
    _macro_headwind_narrative,
    _event_risk_narrative,
)


# ==================================================================
# Helpers
# ==================================================================

def _state_with_composites(**composite_overrides):
    """构造一个最小 state,只含 composite_factors + 必要 evidence_reports。
    composite 各 key 已带 score / band / composition,可被 narrator 直接消费。"""
    state = {
        "evidence_reports": {
            "layer_1": {"regime": "trend_up"},
            "layer_2": {"stance": "bullish", "phase": "mid"},
            "layer_5": {"macro_stance": "neutral"},
        },
        "composite_factors": {
            "truth_trend": {
                "score": 6,
                "composition": [
                    {"factor_id": "price_adx_14_1d", "value": 28.5},
                    {"factor_id": "price_adx_14_4h", "value": 22.1},
                    {"factor_id": "price_tf_alignment", "value": True},
                    {"factor_id": "price_ma_stack", "value": "bullish"},
                    {"factor_id": "price_ma_200_relation", "value": "above"},
                ],
            },
            "band_position": {
                "phase": "mid",
                "composition": [
                    {"factor_id": "price_swing_extension_ratio", "value": 0.65},
                    {"factor_id": "price_swing_sequence", "value": "HH+HL"},
                    {"factor_id": "price_ma_60_distance", "value": 0.05},
                    {"factor_id": "price_pullback_depth", "value": 0.3},
                ],
            },
            "cycle_position": {
                "cycle_position": "early_bull",
                "composition": [
                    {"factor_id": "onchain_mvrv_z", "value": 1.5},
                    {"factor_id": "onchain_nupl", "value": 0.18},
                    {"factor_id": "onchain_lth_supply", "value": 2.5},
                    {"factor_id": "price_drawdown_from_ath", "value": -32.0},
                ],
            },
            "crowding": {
                "score": 3,
                "composition": [
                    {"factor_id": "derivatives_funding_rate_current", "value": 0.0001},
                    {"factor_id": "derivatives_top_long_short_ratio", "value": 1.8},
                    {"factor_id": "derivatives_basis", "value": 0.05},
                    {"factor_id": "derivatives_put_call", "value": 0.7},
                ],
            },
            "macro_headwind": {
                "score": -1,
                "composition": [
                    {"factor_id": "macro_vix_current", "value": 18.5},
                    {"factor_id": "macro_dxy_20d_change", "value": 0.5},
                    {"factor_id": "macro_us10y_30d_change", "value": 10},
                    {"factor_id": "macro_nasdaq_20d", "value": 2.0},
                ],
            },
            "event_risk": {
                "score": 0,
                "composition": [
                    {"factor_id": "event_fomc_next", "value": None},
                    {"factor_id": "event_cpi_next", "value": None},
                    {"factor_id": "event_nfp_next", "value": None},
                    {"factor_id": "event_options_expiry", "value": None},
                    {"factor_id": "event_vol_extreme_bonus", "value": None},
                ],
            },
        },
    }
    for k, v in composite_overrides.items():
        state["composite_factors"][k] = v
    return state


# ==================================================================
# Acceptance: 6 narrators present + zero AI imports
# ==================================================================

class TestModuleHygiene:
    def test_six_narrators_registered(self):
        assert set(_NARRATIVE_GENERATORS.keys()) == {
            "truth_trend", "band_position", "cycle_position",
            "crowding", "macro_headwind", "event_risk",
        }

    def test_module_does_not_import_anthropic(self):
        mod = importlib.import_module("src.strategy.composite_composition")
        # 模块顶层没有 anthropic / claude / messages.create 字眼
        src = open(mod.__file__).read().lower()
        assert "anthropic" not in src
        assert "messages.create" not in src
        assert "openai" not in src


# ==================================================================
# Acceptance: 字段存在且非空
# ==================================================================

class TestFieldsPopulated:
    def test_six_composites_get_dual_segments(self):
        state = _state_with_composites()
        inject_composite_composition(state, context={})
        for key in _NARRATIVE_GENERATORS.keys():
            c = state["composite_factors"][key]
            assert "current_analysis" in c, f"{key} missing current_analysis"
            assert "strategy_impact" in c, f"{key} missing strategy_impact"
            assert isinstance(c["current_analysis"], str)
            assert isinstance(c["strategy_impact"], str)
            assert c["current_analysis"], f"{key} current_analysis empty"
            assert c["strategy_impact"], f"{key} strategy_impact empty"

    def test_missing_total_counts_present(self):
        state = _state_with_composites()
        inject_composite_composition(state, context={})
        for key in _NARRATIVE_GENERATORS.keys():
            c = state["composite_factors"][key]
            assert "missing_count" in c
            assert "total_count" in c


# ==================================================================
# Acceptance: deterministic output
# ==================================================================

class TestDeterminism:
    def test_same_input_same_output(self):
        s1 = _state_with_composites()
        s2 = _state_with_composites()
        inject_composite_composition(s1, context={})
        inject_composite_composition(s2, context={})
        for key in _NARRATIVE_GENERATORS.keys():
            assert s1["composite_factors"][key]["current_analysis"] == \
                   s2["composite_factors"][key]["current_analysis"]
            assert s1["composite_factors"][key]["strategy_impact"] == \
                   s2["composite_factors"][key]["strategy_impact"]


# ==================================================================
# Acceptance: 全缺失 → fallback
# ==================================================================

class TestFallback:
    def test_all_missing_uses_fallback(self):
        state = _state_with_composites(
            cycle_position={
                "composition": [
                    {"factor_id": "onchain_mvrv_z", "value": None},
                    {"factor_id": "onchain_nupl", "value": None},
                    {"factor_id": "onchain_lth_supply", "value": None},
                    {"factor_id": "price_drawdown_from_ath", "value": None},
                ],
            },
        )
        inject_composite_composition(state, context={})
        c = state["composite_factors"]["cycle_position"]
        assert c["current_analysis"] == _FALLBACK_TEXT
        assert c["strategy_impact"] == _FALLBACK_TEXT


# ==================================================================
# Acceptance: 部分缺失 → 不提缺失项
# 直接调 narrator(绕开 _cycle_position 会用 ctx 重建 composition 的副作用)
# ==================================================================

class TestPartialMissing:
    def test_partial_missing_does_not_mention_missing(self):
        # 直接构造 composite + 调 narrator,代表"composition 已就位"的中间态
        composite = {
            "cycle_position": "early_bull",
            "composition": [
                {"factor_id": "onchain_mvrv_z", "value": 1.5},
                {"factor_id": "onchain_nupl", "value": None},
                {"factor_id": "onchain_lth_supply", "value": None},
                {"factor_id": "price_drawdown_from_ath", "value": -30.0},
            ],
        }
        state = {"evidence_reports": {"layer_2": {"stance": "bullish"}}}
        out = _cycle_position_narrative(composite, state)
        text = out["current_analysis"]
        assert "缺失" not in text
        assert "未拿到" not in text
        assert "MVRV" in text
        assert "NUPL" not in text
        assert out["missing_count"] == 2
        assert out["total_count"] == 4


# ==================================================================
# Acceptance: strategy_impact 引用 §3.8.X 编号
# ==================================================================

class TestEmptyDataPlaceholderSuppressed:
    """Sprint 2.5-cleanup:全空 + score=0 时不能输出"合计 0/9"等占位,
    必须走 fallback。"""

    def test_truth_trend_empty_data_zero_score_falls_back(self):
        c = {"score": 0, "composition": [
            {"factor_id": "price_adx_14_1d", "value": None},
            {"factor_id": "price_adx_14_4h", "value": None},
            {"factor_id": "price_tf_alignment", "value": None},
            {"factor_id": "price_ma_stack", "value": None},
            {"factor_id": "price_ma_200_relation", "value": None},
        ]}
        out = _truth_trend_narrative(c, {})
        assert out["current_analysis"] == _FALLBACK_TEXT
        assert "合计 0/9" not in out["current_analysis"]

    def test_crowding_empty_data_zero_score_falls_back(self):
        c = {"score": 0, "composition": [
            {"factor_id": "derivatives_funding_rate_current", "value": None},
            {"factor_id": "derivatives_top_long_short_ratio", "value": None},
            {"factor_id": "derivatives_basis", "value": None},
            {"factor_id": "derivatives_put_call", "value": None},
        ]}
        out = _crowding_narrative(c, {})
        assert out["current_analysis"] == _FALLBACK_TEXT
        assert "合计 0/8" not in out["current_analysis"]

    def test_macro_headwind_empty_data_zero_score_falls_back(self):
        c = {"score": 0, "composition": [
            {"factor_id": "macro_vix_current", "value": None},
            {"factor_id": "macro_dxy_20d_change", "value": None},
            {"factor_id": "macro_us10y_30d_change", "value": None},
            {"factor_id": "macro_nasdaq_20d", "value": None},
        ]}
        out = _macro_headwind_narrative(c, {})
        assert out["current_analysis"] == _FALLBACK_TEXT
        assert "综合 0.0" not in out["current_analysis"]

    def test_event_risk_empty_data_zero_score_uses_no_event_message(self):
        # event_risk 的 0 事件 + score=0 走"未来 72 小时无登记事件"分支(非 fallback)
        c = {"score": 0, "composition": [
            {"factor_id": "event_fomc_next", "value": None},
            {"factor_id": "event_cpi_next", "value": None},
            {"factor_id": "event_nfp_next", "value": None},
            {"factor_id": "event_options_expiry", "value": None},
            {"factor_id": "event_vol_extreme_bonus", "value": None},
        ]}
        out = _event_risk_narrative(c, {})
        assert "未来 72 小时无登记事件" in out["current_analysis"]
        assert "加权 0.0" not in out["current_analysis"]

    def test_truth_trend_with_data_keeps_score_line(self):
        # 有数据时 "合计 N/9" 仍然出现(无论 score 是否 0)
        c = {"score": 0, "composition": [
            {"factor_id": "price_adx_14_1d", "value": 18.0},
            {"factor_id": "price_adx_14_4h", "value": None},
            {"factor_id": "price_tf_alignment", "value": None},
            {"factor_id": "price_ma_stack", "value": None},
            {"factor_id": "price_ma_200_relation", "value": None},
        ]}
        out = _truth_trend_narrative(c, {})
        assert "合计 0/9" in out["current_analysis"]
        assert "ADX-14(1D)=18.0" in out["current_analysis"]

    def test_macro_headwind_nonzero_score_no_data_keeps_line(self):
        # score 非 0 即使没有数据,也不走 fallback(允许 score-only 输出)
        c = {"score": -3, "composition": [
            {"factor_id": "macro_vix_current", "value": None},
            {"factor_id": "macro_dxy_20d_change", "value": None},
            {"factor_id": "macro_us10y_30d_change", "value": None},
            {"factor_id": "macro_nasdaq_20d", "value": None},
        ]}
        out = _macro_headwind_narrative(c, {})
        assert "综合 -3.0" in out["current_analysis"]


class TestStrategyImpactHumanReadable:
    """Sprint 2.7-readability:strategy_impact 必须是中文人话,不再引用 §X.Y 章节编号。"""

    def test_truth_trend_no_section_ref(self):
        c = {"score": 6, "composition": [
            {"factor_id": "price_adx_14_1d", "value": 28.5},
        ]}
        out = _truth_trend_narrative(c, {"evidence_reports": {"layer_1": {"regime": "trend_up"}}})
        assert "§" not in out["strategy_impact"]
        assert "L1." not in out["strategy_impact"]
        assert "真趋势" in out["strategy_impact"]

    def test_band_position_no_section_ref(self):
        c = {"composition": [
            {"factor_id": "price_swing_extension_ratio", "value": 0.65},
        ]}
        out = _band_position_narrative(c, {"evidence_reports": {"layer_2": {"phase": "mid"}}})
        assert "§" not in out["strategy_impact"]
        assert "L2." not in out["strategy_impact"]

    def test_crowding_no_section_ref(self):
        c = {"score": 3, "composition": [
            {"factor_id": "derivatives_funding_rate_current", "value": 0.0001},
        ]}
        out = _crowding_narrative(c, {})
        assert "§" not in out["strategy_impact"]
        assert "L4." not in out["strategy_impact"]
        assert "拥挤度" in out["strategy_impact"] or "正常" in out["strategy_impact"]

    def test_cycle_position_no_section_ref(self):
        c = {"cycle_position": "early_bull", "composition": [
            {"factor_id": "onchain_mvrv_z", "value": 1.5},
        ]}
        out = _cycle_position_narrative(c, {"evidence_reports": {"layer_2": {"stance": "bullish"}}})
        assert "§" not in out["strategy_impact"]
        assert "L2." not in out["strategy_impact"]
        # 中文枚举应被翻译,不应保留英文 early_bull
        assert "early_bull" not in out["strategy_impact"]
        assert "牛市早期" in out["strategy_impact"]

    def test_macro_headwind_no_section_ref(self):
        c = {"score": -1, "composition": [
            {"factor_id": "macro_vix_current", "value": 18.5},
        ]}
        out = _macro_headwind_narrative(c, {"evidence_reports": {"layer_5": {"macro_stance": "neutral"}}})
        assert "§" not in out["strategy_impact"]
        assert "L5." not in out["strategy_impact"]

    def test_event_risk_no_section_ref(self):
        c = {"score": 0, "composition": [
            {"factor_id": "event_fomc_next", "value": None},
        ]}
        out = _event_risk_narrative(c, {})
        assert "§" not in out["strategy_impact"]
        assert "L4." not in out["strategy_impact"]
        # ambush_only 这种英文枚举必须翻译
        assert "ambush_only" not in out["strategy_impact"]
