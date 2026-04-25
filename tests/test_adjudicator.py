"""
tests/test_adjudicator.py — Sprint 1.5b 单测(对齐建模 14 档状态机 + §6.5)

覆盖:
  * 硬约束前置:各种 permission / state / cap / extreme / fallback / cold_start
    情况下不调 AI
  * AI 路径:grade + permission + state 正常,mock AI 返回合法/非法 JSON
  * 约束覆盖:AI 返回违反硬约束的 action → override
  * evidence_gaps:L5 数据缺失应被标记
  * cold_start 优先于 L3 grade
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.ai.adjudicator import AIAdjudicator


# ==================================================================
# Helpers
# ==================================================================

def _mock_ai_response(
    action: str = "open_long",
    direction: str = "long",
    confidence: float = 0.7,
    rationale: str = "mock rationale",
    evidence_gaps: list[str] = None,
    *,
    raw_override: str = None,
    model: str = "claude-sonnet-4-5-20250929",
    tokens_in: int = 120,
    tokens_out: int = 80,
    opportunity_grade: str = None,
    trade_plan: dict = None,
    narrative: str = None,
) -> MagicMock:
    """anthropic messages.create 返回形态:
       resp.content = [TextBlock(text=...)], resp.usage.input_tokens,
       resp.usage.output_tokens, resp.model。"""
    if raw_override is not None:
        content = raw_override
    else:
        payload = {
            "action": action,
            "direction": direction,
            "confidence": confidence,
            "rationale": rationale,
            "narrative": narrative or rationale,
            "one_line_summary": rationale[:60],
            "evidence_gaps": evidence_gaps or [],
            "primary_drivers": [],
            "counter_arguments": [],
            "what_would_change_mind": ["条件 A", "条件 B", "条件 C"],
            "transition_reason": "mock transition",
        }
        if opportunity_grade is not None:
            payload["opportunity_grade"] = opportunity_grade
        if trade_plan is not None:
            payload["trade_plan"] = trade_plan
        content = json.dumps(payload, ensure_ascii=False)
    r = MagicMock()
    r.model = model
    # anthropic content block
    block = MagicMock()
    block.text = content
    r.content = [block]
    # anthropic usage
    r.usage = MagicMock(input_tokens=tokens_in, output_tokens=tokens_out)
    return r


def _attach_ai(client: MagicMock, response=None, side_effect=None) -> None:
    """把 mock response / side_effect 挂到 client.messages.create(anthropic 路径)。"""
    if side_effect is not None:
        client.messages.create.side_effect = side_effect
    else:
        client.messages.create.return_value = response


def _state(
    *,
    l1_regime: str = "trend_up",
    l1_volatility: str = "normal",
    l2_stance: str = "bullish",
    l2_confidence: float = 0.7,
    l2_phase: str = "early",
    l3_grade: str = "A",
    l3_permission: str = "can_open",
    l4_cap: float = 0.15,
    l4_risk: str = "moderate",
    l5_env: str = "risk_on",
    l5_macro_stance: str = "risk_on",
    l5_headwind: str = "tailwind",
    l5_completeness: float = 80.0,
    l5_health: str = "healthy",
    l5_extreme_event: bool = False,
    sm_state: str = "FLAT",
    cold_start: bool = False,
    fallback_level: Any = None,
    account: dict = None,
) -> dict[str, Any]:
    return {
        "evidence_reports": {
            "layer_1": {
                "regime": l1_regime,
                "volatility_regime": l1_volatility,
                "health_status": "healthy",
            },
            "layer_2": {
                "stance": l2_stance,
                "stance_confidence": l2_confidence,
                "phase": l2_phase,
                "health_status": "healthy",
            },
            "layer_3": {
                "opportunity_grade": l3_grade,
                "execution_permission": l3_permission,
                "anti_pattern_flags": [],
                "health_status": "healthy",
            },
            "layer_4": {
                "position_cap": l4_cap,
                "stop_loss_reference": {"price": 45000},
                "risk_reward_ratio": 2.2,
                "overall_risk_level": l4_risk,
                "hard_invalidation_levels": [
                    {"price": 45000, "direction": "below",
                     "basis": "structural_hl", "priority": 1,
                     "confirmation_timeframe": "4H"},
                    {"price": 44000, "direction": "below",
                     "basis": "stop_atr", "priority": 2,
                     "confirmation_timeframe": "4H"},
                ],
                "health_status": "healthy",
            },
            "layer_5": {
                "macro_environment": l5_env,
                "macro_stance": l5_macro_stance,
                "macro_headwind_vs_btc": l5_headwind,
                "data_completeness_pct": l5_completeness,
                "health_status": l5_health,
                "extreme_event_detected": l5_extreme_event,
            },
        },
        "state_machine": {
            "current_state": sm_state,
            "previous_state": None,
        },
        "cold_start": {
            "warming_up": cold_start,
            "runs_completed": 0 if cold_start else 100,
        },
        "account_state": account or {},
        "pipeline_meta": {"fallback_level": fallback_level},
    }


# ==================================================================
# 硬约束路径:不调 AI
# ==================================================================

class TestHardConstraints:
    def test_l3_watch_forces_watch(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(l3_permission="watch", l3_grade="A",
                       sm_state="FLAT")
        out = adj.decide(state)
        assert out["action"] == "watch"
        assert out["status"] == "success"
        client.messages.create.assert_not_called()

    def test_l3_protective_with_long_position_reduces(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_permission="protective",
            account={"long_position_size": 0.5},
        )
        out = adj.decide(state)
        assert out["action"] == "reduce_long"
        assert out["direction"] == "long"
        client.messages.create.assert_not_called()

    def test_l4_cap_zero_forces_watch(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(l4_cap=0.0, l3_permission="can_open",
                       l3_grade="A", sm_state="FLAT")
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.messages.create.assert_not_called()

    def test_protection_state_forces_pause(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(sm_state="PROTECTION")
        out = adj.decide(state)
        assert out["action"] == "pause"
        client.messages.create.assert_not_called()

    def test_l5_extreme_event_forces_pause(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(l5_extreme_event=True, sm_state="FLAT")
        out = adj.decide(state)
        assert out["action"] == "pause"
        client.messages.create.assert_not_called()

    def test_cold_start_forces_watch_even_with_grade_A(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="A", l3_permission="can_open",
            sm_state="FLAT", cold_start=True,
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.messages.create.assert_not_called()

    def test_hold_only_forces_hold(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(l3_permission="hold_only", l3_grade="A")
        out = adj.decide(state)
        assert out["action"] == "hold"
        client.messages.create.assert_not_called()

    def test_fallback_level_2_forces_watch(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            sm_state="FLAT", l3_grade="A", l3_permission="can_open",
            fallback_level="level_2",
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.messages.create.assert_not_called()

    def test_fallback_level_3_forces_watch(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            sm_state="FLAT", l3_grade="A", l3_permission="can_open",
            fallback_level=3,
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.messages.create.assert_not_called()

    def test_post_protection_reassess_forces_hold(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            sm_state="POST_PROTECTION_REASSESS",
            l3_grade="A", l3_permission="can_open",
        )
        out = adj.decide(state)
        assert out["action"] == "hold"
        client.messages.create.assert_not_called()


# ==================================================================
# AI 路径(新 14 档)
# ==================================================================

class TestAIPath:
    def test_flat_with_grade_A_bullish_calls_ai(self):
        """FLAT + grade A + bullish + can_open → AI 路径(建议进 LONG_PLANNED)"""
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.72,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="bullish", l3_grade="A", l3_permission="can_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["action"] == "open_long"
        assert out["status"] == "success"
        client.messages.create.assert_called_once()

    def test_flat_with_grade_B_bearish_calls_ai(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_short", direction="short", confidence=0.6,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="bearish", l3_grade="B", l3_permission="cautious_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["action"] == "open_short"

    def test_long_hold_calls_ai_for_hold_or_reduce(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="hold", direction=None, confidence=0.7,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="bullish", l3_grade="A", l3_permission="can_open",
            sm_state="LONG_HOLD",
            account={"long_position_size": 0.5},
        )
        out = adj.decide(state)
        assert out["action"] == "hold"

    def test_ai_invalid_json_retries_then_degrades(self):
        client = MagicMock()
        client.messages.create.side_effect = [
            _mock_ai_response(raw_override="this is not JSON at all"),
            _mock_ai_response(raw_override="still garbage, no braces here"),
        ]
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="A", l3_permission="can_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["status"] == "degraded_structured"
        assert out["action"] == "watch"
        assert "ai_parse_failed" in out["notes"]
        assert client.messages.create.call_count == 2

    def test_ai_violating_hard_constraint_gets_overridden(self):
        """FLAT + bullish,AI 返回 open_short → override。"""
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_short", direction="short", confidence=0.8,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="bullish", l3_grade="A", l3_permission="can_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["action"] != "open_short"
        assert "ai_action_overridden_by_constraints" in out["notes"]

    def test_evidence_gaps_include_macro_incomplete(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.65,
            evidence_gaps=[],
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="A", l3_permission="can_open",
            sm_state="FLAT",
            l5_completeness=20.0,
            l5_health="degraded",
        )
        out = adj.decide(state)
        assert "macro_data_incomplete" in out["evidence_gaps"]


# ==================================================================
# 非 AI、非硬约束:规则路径 watch
# ==================================================================

class TestRulePathNeutral:
    def test_grade_none_skips_ai(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="neutral",
            l3_grade="none",
            l3_permission="can_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        assert out["status"] == "success"
        client.messages.create.assert_not_called()

    def test_flip_watch_cooling_with_grade_none_rule_path(self):
        """FLIP_WATCH + grade=none(还没到反手门槛)→ 规则 watch。"""
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            sm_state="FLIP_WATCH", l3_grade="none", l3_permission="can_open",
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.messages.create.assert_not_called()


# ==================================================================
# Output shape
# ==================================================================

class TestOutputShape:
    def test_output_has_all_required_fields(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response()
        adj = AIAdjudicator(openai_client=client)
        state = _state()
        out = adj.decide(state)
        for field in (
            "action", "direction", "confidence", "rationale",
            "constraints", "evidence_gaps", "model_used",
            "tokens_in", "tokens_out", "latency_ms", "status", "notes",
        ):
            assert field in out, f"missing field: {field}"
        for c in (
            "max_position_size", "stop_loss_reference",
            "event_risk_warning", "execution_permission_binding",
        ):
            assert c in out["constraints"]


# ==================================================================
# Sprint 2.2:A/B/C 都产出 trade_plan + confidence_tier
# ==================================================================

class TestTradePlanAcrossGrades:
    """grade ∈ {A, B, C} → AI 产出 trade_plan + confidence_tier;
       grade = none → trade_plan = null。"""

    @staticmethod
    def _trade_plan_payload(size_pct: float = 10.0) -> dict:
        return {
            "direction": "long",
            "confidence_tier": "high",  # 会被后端按 grade 覆盖
            "max_position_size_pct": size_pct,
            "entry_zones": [
                {"price_low": 79000, "price_high": 80000, "allocation_pct": 50},
                {"price_low": 77500, "price_high": 78500, "allocation_pct": 50},
            ],
            "stop_loss": 45000,  # 必须在 hard_invalidation_levels 里
            "take_profit_plan": [
                {"price": 85000, "size_pct": 50},
                {"price": 90000, "size_pct": 50},
            ],
            "dynamic_notes": "回踩 MA20 加仓",
        }

    def test_grade_A_produces_high_tier_trade_plan(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.75,
            opportunity_grade="A",
            trade_plan=self._trade_plan_payload(size_pct=14.0),
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="A", l3_permission="can_open",
            l2_stance="bullish", sm_state="FLAT",
            l4_cap=0.15,
        )
        out = adj.decide(state)
        assert out["opportunity_grade"] == "A"
        assert out["trade_plan"] is not None
        assert out["trade_plan"]["confidence_tier"] == "high"
        # A 级 cap 上限 = 15% × 1.0 = 15%
        assert out["trade_plan"]["max_position_size_pct"] <= 15.0 + 0.01
        assert out["trade_plan"]["stop_loss"] == 45000
        assert out["confidence_breakdown"]["trade_plan_confidence_tier"] == "high"

    def test_grade_B_produces_medium_tier_trade_plan(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.6,
            opportunity_grade="B",
            trade_plan=self._trade_plan_payload(size_pct=8.0),
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="B", l3_permission="cautious_open",
            l2_stance="bullish", sm_state="FLAT",
            l4_cap=0.15,
        )
        out = adj.decide(state)
        assert out["opportunity_grade"] == "B"
        assert out["trade_plan"] is not None
        assert out["trade_plan"]["confidence_tier"] == "medium"
        # B 级 cap 上限 = 15% × 0.7 = 10.5%
        assert out["trade_plan"]["max_position_size_pct"] <= 10.5 + 0.01

    def test_grade_C_produces_low_tier_trade_plan(self):
        """Sprint 2.2 关键改动:C 也必须给 trade_plan,信心档 low。"""
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.45,
            opportunity_grade="C",
            trade_plan=self._trade_plan_payload(size_pct=5.0),
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="C", l3_permission="cautious_open",
            l2_stance="bullish", sm_state="FLAT",
            l4_cap=0.15,
        )
        out = adj.decide(state)
        assert out["opportunity_grade"] == "C"
        assert out["trade_plan"] is not None, (
            "C 级也必须有 trade_plan(Sprint 2.2 新规则)"
        )
        assert out["trade_plan"]["confidence_tier"] == "low"
        # C 级 cap 上限 = 15% × 0.4 = 6%
        assert out["trade_plan"]["max_position_size_pct"] <= 6.0 + 0.01

    def test_grade_C_exceeding_cap_gets_clamped(self):
        """AI 给 C 级但 size=14%(超 6% 上限)→ 后端强制 clamp 到 6%。"""
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.45,
            opportunity_grade="C",
            trade_plan=self._trade_plan_payload(size_pct=14.0),
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="C", l3_permission="cautious_open",
            l2_stance="bullish", sm_state="FLAT",
            l4_cap=0.15,
        )
        out = adj.decide(state)
        assert out["trade_plan"] is not None
        assert out["trade_plan"]["max_position_size_pct"] <= 6.0 + 0.01
        assert "trade_plan_size_clamped_to_grade_ceiling" in out["notes"]

    def test_grade_none_rejects_trade_plan(self):
        """grade=none 时 AI 就算给了 trade_plan,也会被 adjudicator 置为 null。
           此场景走硬约束(L3 grade none → watch rule path),AI 不调用,
           trade_plan 自然为 null。"""
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="none", l3_permission="watch",
            l2_stance="neutral", sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["opportunity_grade"] == "none"
        assert out["trade_plan"] is None
        assert out["confidence_breakdown"]["trade_plan_confidence_tier"] == "none"

    def test_trade_plan_stop_loss_snaps_to_hard_invalidation(self):
        """AI 返回的 stop_loss 若偏离 L4.hard_invalidation_levels,
           snap 到最近合法价位。"""
        client = MagicMock()
        plan = self._trade_plan_payload()
        plan["stop_loss"] = 43500  # 非法,应该 snap 到 44000(priority=2)
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.7,
            opportunity_grade="A",
            trade_plan=plan,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="A", l3_permission="can_open",
            l2_stance="bullish", sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["trade_plan"]["stop_loss"] in (44000, 45000)
        assert any("snapped_to_l4" in n or "defaulted_to_l4" in n
                   for n in out["notes"])

    def test_ai_grade_not_matching_l3_is_overridden(self):
        """§6.4 #8:opportunity_grade 必须 = L3,不一致时 override。"""
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.8,
            opportunity_grade="A",  # AI 自己说 A
            trade_plan=self._trade_plan_payload(),
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="B",  # L3 判档是 B
            l3_permission="cautious_open",
            l2_stance="bullish", sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["opportunity_grade"] == "B"
        assert "ai_grade_overridden_to_l3" in out["notes"]


# ==================================================================
# Sprint 2.5-B:composite_factors 双段分析
# ==================================================================

class TestCompositeFactorsAnalyses:
    """AI 输出 composite_factors[] 数组,验证 + fallback + 软约束 notes。"""

    _COMPOSITE_KEYS = (
        "cycle_position", "truth_trend", "band_position",
        "crowding", "macro_headwind", "event_risk",
    )

    @staticmethod
    def _state_with_composite(**kw):
        state = _state(**kw)
        # 注入 6 个 composite factor 各带一些 composition values
        state["composite_factors"] = {
            "cycle_position": {"score": 5, "composition": [
                {"name": "MVRV-Z", "value": 2.1},
                {"name": "NUPL", "value": 0.45},
                {"name": "LTH supply", "value": 0.78},
                {"name": "距 ATH", "value": -0.12},
            ]},
            "truth_trend": {"score": 6, "composition": [
                {"name": "ADX-14", "value": 28.5},
                {"name": "MA stack", "value": "bullish"},
                {"name": "TF align", "value": True},
            ]},
            "band_position": {"composition": [
                {"name": "swing ext", "value": 0.55},
            ]},
            "crowding": {"composition": [
                {"name": "funding", "value": 0.0001},
            ]},
            "macro_headwind": {"composition": [
                {"name": "DXY", "value": None},
                {"name": "VIX", "value": None},
                {"name": "US10Y", "value": None},
            ]},  # 全空 → 触发 fallback
            "event_risk": {"composition": [
                {"name": "FOMC distance", "value": 12},
                {"name": "CPI distance", "value": None},
            ]},  # 部分空 → missing_count=1
        }
        return state

    def test_ai_output_propagates_to_six_entries(self):
        ai_payload = [
            {"key": "cycle_position",
             "current_analysis": "MVRV-Z=2.1 处于早牛区间,NUPL 0.45 健康,长持仓 78%。",
             "strategy_impact": "对应 L2.动态门槛表 早牛阈值上调,L4.position_cap 不收紧。"},
            {"key": "truth_trend",
             "current_analysis": "ADX=28.5 趋势确立,MA 多头排列,多周期方向一致。",
             "strategy_impact": "L1.regime=trend_up 给 L2.stance bullish 提供依据。"},
            {"key": "band_position",
             "current_analysis": "swing ext 0.55 处于波段中段。",
             "strategy_impact": "L2.phase=mid 配合 L4.position_cap 默认值。"},
            {"key": "crowding",
             "current_analysis": "funding=0.0001 处于中性,无明显多空拥挤。",
             "strategy_impact": "L4.crowding_multiplier=1.0 不下调 position_cap。"},
            {"key": "event_risk",
             "current_analysis": "未来 12 天有 FOMC,短期无即时事件干扰。",
             "strategy_impact": "L4.event_risk_multiplier=1.0,permission 不降档。"},
            # macro_headwind 故意省略 → 期望 fallback
        ]
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", opportunity_grade="A",
            trade_plan={
                "direction": "long", "confidence_tier": "high",
                "max_position_size_pct": 50,
                "entry_zones": [{"price_low": 40000, "price_high": 41000, "allocation_pct": 100}],
                "stop_loss": 38000,
                "take_profit_plan": [{"price": 45000, "size_pct": 100}],
                "dynamic_notes": "x",
            },
        )
        # 把 composite_factors 塞进 mock 的 JSON
        # 重新构造响应:把 ai_payload 加进去
        original_text = client.messages.create.return_value.content[0].text
        parsed = json.loads(original_text)
        parsed["composite_factors"] = ai_payload
        client.messages.create.return_value.content[0].text = json.dumps(
            parsed, ensure_ascii=False,
        )

        adj = AIAdjudicator(openai_client=client)
        state = self._state_with_composite(
            l3_grade="A", l3_permission="can_open",
            l2_stance="bullish", sm_state="FLAT",
        )
        out = adj.decide(state)
        cf = out.get("composite_factors")
        assert isinstance(cf, list) and len(cf) == 6
        keys_out = [e["key"] for e in cf]
        assert keys_out == list(self._COMPOSITE_KEYS)

        by_key = {e["key"]: e for e in cf}
        # AI 提供的 5 个非空
        for k in ("cycle_position", "truth_trend", "band_position",
                  "crowding", "event_risk"):
            assert "MVRV-Z" in by_key["cycle_position"]["current_analysis"] or by_key[k]["current_analysis"]
            assert by_key[k]["strategy_impact"]
        # macro_headwind 全空 + AI 也没给 → fallback
        assert by_key["macro_headwind"]["current_analysis"] == \
               "基础数据暂未就绪,无法生成态势分析"
        # event_risk 1 项缺
        assert by_key["event_risk"]["missing_count"] == 1
        assert by_key["event_risk"]["total_count"] == 2
        # cycle_position 全有
        assert by_key["cycle_position"]["missing_count"] == 0

    def test_missing_ai_array_falls_back_to_six_entries(self):
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", opportunity_grade="A",
            trade_plan={
                "direction": "long", "confidence_tier": "high",
                "max_position_size_pct": 50,
                "entry_zones": [{"price_low": 40000, "price_high": 41000, "allocation_pct": 100}],
                "stop_loss": 38000,
                "take_profit_plan": [{"price": 45000, "size_pct": 100}],
                "dynamic_notes": "x",
            },
        )
        # AI 没给 composite_factors,期望全部 fallback
        adj = AIAdjudicator(openai_client=client)
        state = self._state_with_composite(
            l3_grade="A", l3_permission="can_open",
            l2_stance="bullish", sm_state="FLAT",
        )
        out = adj.decide(state)
        cf = out["composite_factors"]
        assert len(cf) == 6
        for e in cf:
            assert e["current_analysis"] == "基础数据暂未就绪,无法生成态势分析"
            assert e["strategy_impact"] == "基础数据暂未就绪,无法生成态势分析"

    def test_soft_constraints_logged_to_notes(self):
        # AI 给的 current_analysis 没数字,strategy_impact 没层级编号
        ai_payload = [
            {"key": "cycle_position",
             "current_analysis": "处于早牛区间,健康程度良好。",
             "strategy_impact": "对当前策略略有支撑作用。"},
        ]
        client = MagicMock()
        client.messages.create.return_value = _mock_ai_response(
            action="open_long", opportunity_grade="A",
            trade_plan={
                "direction": "long", "confidence_tier": "high",
                "max_position_size_pct": 50,
                "entry_zones": [{"price_low": 40000, "price_high": 41000, "allocation_pct": 100}],
                "stop_loss": 38000,
                "take_profit_plan": [{"price": 45000, "size_pct": 100}],
                "dynamic_notes": "x",
            },
        )
        original_text = client.messages.create.return_value.content[0].text
        parsed = json.loads(original_text)
        parsed["composite_factors"] = ai_payload
        client.messages.create.return_value.content[0].text = json.dumps(
            parsed, ensure_ascii=False,
        )
        adj = AIAdjudicator(openai_client=client)
        state = self._state_with_composite(
            l3_grade="A", l3_permission="can_open",
            l2_stance="bullish", sm_state="FLAT",
        )
        out = adj.decide(state)
        notes = out["notes"]
        assert any("composite_no_digit" in n for n in notes)
        assert any("composite_no_layer_ref" in n for n in notes)
