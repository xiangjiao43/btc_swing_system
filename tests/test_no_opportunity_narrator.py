"""tests/test_no_opportunity_narrator.py — Sprint 2.7-no-opp 专用测试。

覆盖:
  - 8 个 detect_scenario 优先级正确(对照 _check_hard_constraints)
  - 8 种场景输出 4 段都非空、长度合理
  - 字段名和 AI 真触发路径一致
  - 输出字符串遵循人读风格指南(主要靠 test_human_readable_style.py 守门员)
"""

from __future__ import annotations

import pytest

from src.strategy.no_opportunity_narrator import (
    SCENARIO_COLD_START,
    SCENARIO_EXTREME_EVENT,
    SCENARIO_FALLBACK_DEGRADED,
    SCENARIO_GRADE_NONE,
    SCENARIO_PERMISSION_RESTRICTED,
    SCENARIO_POSITION_CAP_ZERO,
    SCENARIO_POST_PROTECTION,
    SCENARIO_PROTECTION,
    detect_scenario,
    generate_no_opportunity_narrative,
)


# ============================================================
# 场景识别优先级
# ============================================================

class TestScenarioDetection:
    def test_extreme_event_highest_priority(self):
        # extreme_event 优先于 protection / cold_start
        facts = {
            "l5_extreme_event_detected": True,
            "state_machine_current": "PROTECTION",
            "cold_start_warming_up": True,
        }
        assert detect_scenario(facts, {}) == SCENARIO_EXTREME_EVENT

    def test_protection_above_cold_start(self):
        facts = {
            "state_machine_current": "PROTECTION",
            "cold_start_warming_up": True,
        }
        assert detect_scenario(facts, {}) == SCENARIO_PROTECTION

    def test_cold_start_above_fallback(self):
        facts = {
            "cold_start_warming_up": True,
            "fallback_level": "level_2",
        }
        assert detect_scenario(facts, {}) == SCENARIO_COLD_START

    def test_fallback_above_post_protection(self):
        facts = {
            "fallback_level": "level_3",
            "state_machine_current": "POST_PROTECTION_REASSESS",
        }
        assert detect_scenario(facts, {}) == SCENARIO_FALLBACK_DEGRADED

    def test_post_protection_above_permission(self):
        facts = {
            "state_machine_current": "POST_PROTECTION_REASSESS",
            "l3_permission": "watch",
        }
        assert detect_scenario(facts, {}) == SCENARIO_POST_PROTECTION

    def test_permission_above_cap_zero(self):
        facts = {
            "l3_permission": "hold_only",
            "l4_position_cap": 0.0,
        }
        assert detect_scenario(facts, {}) == SCENARIO_PERMISSION_RESTRICTED

    def test_cap_zero_above_grade_none(self):
        facts = {
            "l4_position_cap": 0.0,
            "l3_grade": "none",
        }
        assert detect_scenario(facts, {}) == SCENARIO_POSITION_CAP_ZERO

    def test_default_grade_none(self):
        facts = {"l3_grade": "none"}
        assert detect_scenario(facts, {}) == SCENARIO_GRADE_NONE


# ============================================================
# 8 种场景输出结构 + 长度
# ============================================================

@pytest.fixture
def all_scenarios():
    """8 种场景的 (facts, state) 样本。"""
    return [
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
        ("post_protection_reassess",
         {"state_machine_current": "POST_PROTECTION_REASSESS"},
         {}),
        ("permission_restricted",
         {"l3_permission": "watch"},
         {"evidence_reports": {"layer_4": {"permission_chain": {
             "suggestions": {"l4_risk_level": "ambush_only"}}}}}),
        ("position_cap_zero",
         {"l4_position_cap": 0.0},
         {}),
        ("grade_none",
         {"l3_grade": "none", "l3_permission": "no_chase"},
         {"evidence_reports": {
             "layer_1": {"regime": "transition_up"},
             "layer_2": {"stance": "neutral"},
             "layer_3": {"rule_trace": {"upgrade_conditions": [
                 "做多信心达到 55% 以上",
                 "趋势状态稳定",
                 "波段位置出现初段或中段",
             ]}},
             "layer_5": {"macro_stance": "neutral"},
         }}),
    ]


class TestNarrativeStructure:
    """每个场景的输出 4 段都非空且长度合理。"""

    def test_all_scenarios_produce_non_empty_narrative(self, all_scenarios):
        for label, facts, state in all_scenarios:
            out = generate_no_opportunity_narrative(facts, state)
            n = out["narrative"]
            assert isinstance(n, str), f"[{label}] narrative not str"
            assert 50 <= len(n) <= 400, \
                f"[{label}] narrative length {len(n)} 不在 50-400:{n}"

    def test_all_scenarios_have_three_or_more_drivers(self, all_scenarios):
        for label, facts, state in all_scenarios:
            out = generate_no_opportunity_narrative(facts, state)
            drivers = out["primary_drivers"]
            assert isinstance(drivers, list), f"[{label}] drivers not list"
            assert len(drivers) >= 3, \
                f"[{label}] primary_drivers 仅 {len(drivers)} 条 (要 ≥3)"
            for d in drivers:
                assert "text" in d and isinstance(d["text"], str) and d["text"]
                assert "evidence_ref" in d

    def test_all_scenarios_have_two_or_more_counter_args(self, all_scenarios):
        for label, facts, state in all_scenarios:
            out = generate_no_opportunity_narrative(facts, state)
            counters = out["counter_arguments"]
            assert isinstance(counters, list), f"[{label}] counters not list"
            assert len(counters) >= 2, \
                f"[{label}] counter_arguments 仅 {len(counters)} 条 (要 ≥2)"
            for c in counters:
                assert "text" in c and isinstance(c["text"], str) and c["text"]

    def test_all_scenarios_have_three_or_more_change_conditions(
        self, all_scenarios,
    ):
        for label, facts, state in all_scenarios:
            out = generate_no_opportunity_narrative(facts, state)
            changes = out["what_would_change_mind"]
            assert isinstance(changes, list), f"[{label}] changes not list"
            assert len(changes) >= 3, \
                f"[{label}] what_would_change_mind 仅 {len(changes)} 条 (要 ≥3)"
            for c in changes:
                assert isinstance(c, str) and c


# ============================================================
# 字段兼容性(与 AI 真触发路径输出一致)
# ============================================================

class TestSchemaCompat:
    """narrator 输出的字段必须能被 _build_rule_output 直接采纳。"""

    def test_required_keys_present(self):
        out = generate_no_opportunity_narrative({}, {})
        for k in ("narrative", "primary_drivers", "counter_arguments",
                  "what_would_change_mind"):
            assert k in out, f"missing key: {k}"

    def test_grade_none_uses_l3_upgrade_conditions(self):
        # grade_none 场景有 L3 upgrade_conditions 时应优先使用
        state = {"evidence_reports": {
            "layer_3": {"rule_trace": {"upgrade_conditions": [
                "条件 A 人话",
                "条件 B 人话",
                "条件 C 人话",
                "条件 D 人话",
            ]}},
        }}
        out = generate_no_opportunity_narrative({}, state)
        changes = out["what_would_change_mind"]
        assert "条件 A 人话" in changes
        assert len(changes) <= 5

    def test_grade_none_falls_back_when_no_upgrade_conditions(self):
        # 没有 L3 upgrade_conditions 时使用通用兜底文案
        out = generate_no_opportunity_narrative({}, {})
        changes = out["what_would_change_mind"]
        assert len(changes) >= 3
        # 应包含通用兜底文案的特征字符串(任一)
        joined = " ".join(changes)
        assert "信心" in joined or "趋势" in joined or "波段" in joined
