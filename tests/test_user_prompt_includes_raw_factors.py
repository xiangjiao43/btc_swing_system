"""tests/test_user_prompt_includes_raw_factors.py — Sprint 1.5l Task C2。

_build_user_prompt 必须把 strategy_state 的 factor_cards / composite_factors /
events 拍平成原始因子快照,追加到 user prompt 末尾,供 AI 在 narrative 里
自由挑 3-5 个关键指标。

§Z 反退化:
- 原始因子快照存在(标题段)
- factor_cards 各 category 真值出现(funding/MVRV 等)
- composite_factors 6 个组合因子名都在
- events 写入(72h 内 + 各类下次)
"""

from __future__ import annotations

from src.ai.adjudicator import _build_user_prompt, _build_raw_factor_snapshot


def _facts_minimal() -> dict:
    return {
        "l1_regime": "trend_up", "l1_volatility": "normal",
        "l2_stance": "bullish", "l2_stance_confidence": 0.7, "l2_phase": "early",
        "l3_grade": "B", "l3_permission": "cautious_open",
        "l3_anti_pattern_flags": [],
        "l4_position_cap": 0.10, "l4_overall_risk": "moderate",
        "l4_risk_reward_ratio": 2.0, "l4_hard_invalidation_levels": [],
        "l5_macro_stance": "risk_on", "l5_headwind": "tailwind",
        "l5_data_completeness": 80.0, "l5_extreme_event_detected": False,
        "state_machine_current": "FLAT", "lifecycle_current": None,
        "observation_category": None, "available_card_ids": ["card_1"],
    }


def _state_with_full_factors() -> dict:
    return {
        "factor_cards": [
            {
                "card_id": "derivatives_funding_rate_2026-04-30",
                "category": "derivatives",
                "name": "funding_rate",
                "current_value": -0.4085,
                "value_unit": "%",
                "captured_at_bjt": "2026-04-30 09:00 (BJT)",
            },
            {
                "card_id": "derivatives_oi_2026-04-30",
                "category": "derivatives",
                "name": "open_interest",
                "current_value": 55.83,
                "value_unit": "B USD",
            },
            {
                "card_id": "onchain_mvrv_z_2026-04-30",
                "category": "onchain",
                "name": "mvrv_z_score",
                "current_value": 1.85,
                "value_unit": "",
            },
            {
                "card_id": "macro_dxy_2026-04-30",
                "category": "macro",
                "name": "DXY",
                "current_value": 104.2,
                "value_unit": "",
            },
            {
                "card_id": "price_btc_close_2026-04-30",
                "category": "price_structure",
                "name": "BTC 现价",
                "current_value": 75700.0,
                "value_unit": "USD",
            },
        ],
        "composite_factors": {
            "cycle_position": {"cycle_position": "mid_bull", "cycle_confidence": 0.62},
            "truth_trend": {"truth_trend": "neutral", "trend_score": 0.55},
            "band_position": {"band_position": "mid", "band_pct": 0.55},
            "crowding": {"crowding_level": "high", "crowding_score": 11},
            "macro_headwind": {"macro_headwind_level": "mild", "headwind_score": -2},
            "event_risk": {"event_risk_level": "high", "event_risk_score": 11.5},
        },
        "events_upcoming_48h": [
            {"event_name": "PCE", "event_type": "pce",
             "utc_trigger_time": "2026-04-30T20:00:00Z", "impact_level": 4},
        ],
        "next_events_by_type": {
            "fomc": {"event_type": "fomc",
                     "utc_trigger_time": "2026-05-15T18:00:00Z"},
            "nfp":  {"event_type": "nfp",
                     "utc_trigger_time": "2026-05-02T12:30:00Z"},
        },
    }


# ============================================================
# 标题块 + 三大类必须出现
# ============================================================

def test_prompt_has_raw_factor_snapshot_section():
    prompt = _build_user_prompt(
        _facts_minimal(), ["watch", "hold"], state=_state_with_full_factors(),
    )
    assert "原始因子快照" in prompt


def test_prompt_includes_funding_value():
    """funding_rate 当前值 -0.4085 必须出现在 prompt(供 AI 引用 30d 分位等)。"""
    prompt = _build_user_prompt(
        _facts_minimal(), ["watch", "hold"], state=_state_with_full_factors(),
    )
    assert "funding_rate" in prompt
    assert "-0.4085" in prompt


def test_prompt_includes_mvrv_value():
    prompt = _build_user_prompt(
        _facts_minimal(), ["watch", "hold"], state=_state_with_full_factors(),
    )
    assert "mvrv_z_score" in prompt
    assert "1.85" in prompt


def test_prompt_includes_btc_price():
    prompt = _build_user_prompt(
        _facts_minimal(), ["watch", "hold"], state=_state_with_full_factors(),
    )
    assert "BTC 现价" in prompt
    assert "75700" in prompt


# ============================================================
# 6 个组合因子全部出现(spec)
# ============================================================

def test_prompt_includes_all_six_composite_factors():
    prompt = _build_user_prompt(
        _facts_minimal(), ["watch", "hold"], state=_state_with_full_factors(),
    )
    for name in (
        "cycle_position", "truth_trend", "band_position",
        "crowding", "macro_headwind", "event_risk",
    ):
        assert name in prompt, f"missing composite factor: {name}"


def test_prompt_includes_composite_diagnostics():
    """组合因子值(crowding_score=11 / event_risk_score=11.5)需进入 prompt
    供 AI 引用'高拥挤档触发 cap × 0.7'。"""
    prompt = _build_user_prompt(
        _facts_minimal(), ["watch", "hold"], state=_state_with_full_factors(),
    )
    assert "11" in prompt   # crowding_score
    assert "11.5" in prompt  # event_risk_score


# ============================================================
# 事件窗口
# ============================================================

def test_prompt_includes_event_window_72h():
    prompt = _build_user_prompt(
        _facts_minimal(), ["watch", "hold"], state=_state_with_full_factors(),
    )
    # 72h 内事件
    assert "PCE" in prompt
    # 各类下次事件(next_events_by_type)
    assert "fomc" in prompt
    assert "nfp" in prompt


# ============================================================
# 向后兼容(state=None 时不破)
# ============================================================

def test_prompt_works_without_state():
    """老调用路径(无 state 参数)仍可用,不抛异常,prompt 也不含因子快照。"""
    prompt = _build_user_prompt(_facts_minimal(), ["watch", "hold"])
    assert "原始因子快照" not in prompt
    # 仍含证据链关键字段
    assert "L1 Regime" in prompt


def test_snapshot_helper_returns_empty_for_empty_state():
    assert _build_raw_factor_snapshot({}) == ""


def test_snapshot_helper_handles_partial_state():
    """只有 factor_cards 没 composite_factors → 仍输出 factor_cards 部分。"""
    state = {
        "factor_cards": [{
            "category": "derivatives", "name": "funding_rate",
            "current_value": -0.41, "value_unit": "%",
        }],
    }
    out = _build_raw_factor_snapshot(state)
    assert "funding_rate" in out
    assert "-0.41" in out


# ============================================================
# 输出规范段仍在 prompt 末尾(snapshot 不能挤掉它)
# ============================================================

def test_output_spec_section_still_at_end():
    prompt = _build_user_prompt(
        _facts_minimal(), ["watch", "hold"], state=_state_with_full_factors(),
    )
    assert "输出规范" in prompt
    # 输出规范段必须在原始因子快照之后(防止因子快照插在错的位置)
    snap_idx = prompt.find("原始因子快照")
    spec_idx = prompt.find("输出规范")
    assert snap_idx >= 0 and spec_idx > snap_idx
