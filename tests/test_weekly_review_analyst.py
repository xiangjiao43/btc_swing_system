"""tests/test_weekly_review_analyst.py — Sprint 1.10-H commit 3 单测。

覆盖 v1.4 §3.3.9 WeeklyReviewAnalyst(全 mock,真 API 留 1.10-L)。
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.ai.agents.weekly_review_analyst import (
    VALID_CONFIDENCE_ACCURACY, VALID_EVIDENCE_CONFIDENCE,
    VALID_OBSERVED_OUTCOMES, VALID_PRIORITIES,
    VALID_RECOMMENDATION_ACTION_TYPES, VALID_RECOMMENDATION_CATEGORIES,
    VALID_SEVERITIES,
    WeeklyReviewAnalyst,
)
from src.ai.weekly_review_input_builder import VALIDATOR_KEYS


def _make_full_output(
    *, perf_pnl: float = 1.5,
    high_recs: int = 0,
    extra_recs_count: int = 1,
) -> dict[str, Any]:
    """构造完整 5 段 JSON(含 23 V)给 mock client 返。"""
    v_review = {
        k: {"activations": 1, "rate": "1/7 days", "evaluation": "适中"}
        for k in VALIDATOR_KEYS
    }
    recs = []
    for i in range(high_recs):
        recs.append({
            "目标": f"high_{i}",
            "建议": f"high suggestion {i}",
            "优先级": "high",
            "影响": "test",
        })
    for i in range(extra_recs_count):
        recs.append({
            "目标": f"medium_{i}",
            "建议": f"medium suggestion {i}",
            "优先级": "medium",
            "影响": "test",
        })
    return {
        "performance_summary": {
            "total_runs": 7, "successful_runs": 5, "ai_failures": 2,
            "thesis_created": 1, "thesis_closed_profit": 0,
            "thesis_closed_loss": 0,
            "weekly_pnl_pct": perf_pnl, "max_drawdown_pct": -2.5,
        },
        "system_health_diagnosis": [{
            "issue": "L3 失败率偏高", "evidence": "run_001/004",
            "severity": "warning",
            "suggested_action": "缩 L3 prompt",
        }],
        "strategy_quality": {
            "thesis_quality": "acceptable",
            "break_conditions_calibration": "适中",
            "false_signals": [], "missed_opportunities": [],
            "ai_vs_actual_comparison": [],
        },
        "hard_constraint_activation_review": {
            **v_review,
            "position_cap_compressed_avg": 0.42,
            "thesis_lock_blocks_count": 1,
            "channel_c_uses_count": 0,
            "review_pending_triggers": 0,
            "overall_evaluation": "硬约束体系合理",
            "suggested_actions": ["无"],
        },
        "adjustment_recommendations": recs,
        "temporal_consistency_diagnostics": {
            "recommendation_recurrence": [],
            "anomaly_streaks": {},
        },
    }


def _mock_client_returning_json(payload: dict) -> Any:
    client = MagicMock()
    response = MagicMock()
    block = MagicMock()
    block.text = json.dumps(payload, ensure_ascii=False)
    block.type = "text"
    response.content = [block]
    response.model = "claude-test"
    response.usage = MagicMock(input_tokens=5000, output_tokens=3000)
    response.stop_reason = "end_turn"
    client.messages.create.return_value = response
    return client


# ============================================================
# 1. 基础元数据
# ============================================================

def test_agent_name_and_prompt_file():
    assert WeeklyReviewAnalyst.AGENT_NAME == "weekly_review_analyst"
    assert WeeklyReviewAnalyst.PROMPT_FILE == "weekly_review_analyst.txt"


def test_prompt_file_exists_and_lists_23_v():
    """system prompt 必须列全 23 条 V key。"""
    from pathlib import Path
    p = (
        Path(__file__).resolve().parent.parent
        / "src" / "ai" / "agents" / "prompts"
        / WeeklyReviewAnalyst.PROMPT_FILE
    )
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    for k in VALIDATOR_KEYS:
        assert k in txt, f"prompt 缺 V key: {k}"


# ============================================================
# 2. happy path:完整 5 段 JSON 解析
# ============================================================

def test_happy_path_full_5_segments():
    payload = _make_full_output(perf_pnl=2.5)
    client = _mock_client_returning_json(payload)
    agent = WeeklyReviewAnalyst()
    out = agent.analyze({
        "window": {"start_utc": "2026-05-03T14:00:00Z",
                    "end_utc": "2026-05-10T14:00:00Z", "days": 7},
        "performance_summary_raw": {"total_runs": 7},
        "thesis_lifecycle": {},
        "virtual_orders_aggregate": {},
        "retry_log_aggregate": {},
        "virtual_account_window": {},
        "fuse_and_states": {},
        "hard_constraint_activation_raw": {"v_activations": {}},
        "context": {},
    }, client=client)
    assert out["status"] == "success"
    assert "performance_summary" in out
    assert "system_health_diagnosis" in out
    assert "strategy_quality" in out
    assert "hard_constraint_activation_review" in out
    assert "adjustment_recommendations" in out


def test_hard_constraint_review_lists_all_23_v():
    """v1.4 §3.3.9 硬约束:必须 23 条 V 都在。"""
    payload = _make_full_output()
    client = _mock_client_returning_json(payload)
    agent = WeeklyReviewAnalyst()
    out = agent.analyze({}, client=client)
    hc = out["hard_constraint_activation_review"]
    for k in VALIDATOR_KEYS:
        assert k in hc, f"missing V: {k}"
        assert "activations" in hc[k]
        assert "rate" in hc[k]
        assert "evaluation" in hc[k]


# ============================================================
# 3. fallback:AI 失败
# ============================================================

def test_api_failure_returns_fallback():
    """AI 抛 → fallback 5 段 JSON 完整(空 review)。"""
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("simulated")
    agent = WeeklyReviewAnalyst()
    out = agent.analyze({}, client=client)
    assert "degraded" in out["status"]
    assert "performance_summary" in out
    assert "hard_constraint_activation_review" in out
    assert "l3_diagnostics" in out
    assert "l4_diagnostics" in out
    assert "validator_diagnostics" in out
    assert "temporal_consistency_diagnostics" in out
    hc = out["hard_constraint_activation_review"]
    # fallback 也含 23 V
    for k in VALIDATOR_KEYS:
        assert k in hc


def test_fallback_has_high_priority_warning_recommendation():
    """fallback 可有 high priority,但不自动等于 critical。"""
    agent = WeeklyReviewAnalyst()
    fb = agent._fallback_output()
    recs = fb["adjustment_recommendations"]
    assert any(r["优先级"] == "high" for r in recs)
    assert WeeklyReviewAnalyst.count_critical_recommendations(fb) == 0


# ============================================================
# 4. normalize_output:23 V 漏字段自动补
# ============================================================

def test_normalize_output_fills_missing_v():
    """AI 输出漏 5 条 V → normalize 自动补 + notes 标记。"""
    payload = _make_full_output()
    # 删除 5 条 V
    hc = payload["hard_constraint_activation_review"]
    for k in list(VALIDATOR_KEYS)[:5]:
        del hc[k]
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    hc_normed = normed["hard_constraint_activation_review"]
    for k in VALIDATOR_KEYS:
        assert k in hc_normed
    notes = normed.get("notes") or []
    assert any("hard_constraint_review_missing_5_V" in n for n in notes)


def test_normalize_output_pass_through_when_complete():
    """完整 23 V → normalize 无变化(无 notes 标记)。"""
    payload = _make_full_output()
    notes_before = payload.get("notes")
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    assert normed.get("notes") == notes_before  # 不动


def test_normalize_output_adds_concrete_action_compatibility():
    payload = _make_full_output(high_recs=1, extra_recs_count=0)
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    rec = normed["adjustment_recommendations"][0]
    assert rec["具体调整路径"] == rec["建议"]
    assert rec["severity"] == "warning"


def test_normalize_output_adds_evidence_confidence_compatibility():
    payload = _make_full_output(high_recs=0, extra_recs_count=1)
    rec = payload["adjustment_recommendations"][0]
    rec["confidence_level"] = "medium"
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    rec = normed["adjustment_recommendations"][0]
    assert rec["evidence_confidence"] == "medium"
    assert "confidence_reason" in rec


def test_normalize_output_adds_canonical_recommendation_fields():
    payload = _make_full_output(high_recs=0, extra_recs_count=1)
    rec = payload["adjustment_recommendations"][0]
    rec["目标"] = "审计 L4 elevated risk_breakdown"
    rec["具体调整路径"] = "建议先审计 L4 elevated 的 risk_breakdown 来源"
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    rec = normed["adjustment_recommendations"][0]
    assert rec["recommendation_id"] == "audit_l4_elevated_risk_breakdown"
    assert rec["normalized_recommendation_id"] == rec["recommendation_id"]
    assert rec["recommendation_category"] == "l4_risk"
    assert rec["recommendation_target"] == "l4_elevated_risk_breakdown"
    assert rec["recommendation_action_type"] == "audit"
    assert rec["outcome_tracking"] == {
        "recommendation_id": "audit_l4_elevated_risk_breakdown",
        "implemented": False,
        "observed_outcome": "unknown",
        "confidence_accuracy": "low",
        "evaluation_notes": "",
        "week_of_outcome": "",
    }


def test_normalize_output_preserves_outcome_tracking():
    payload = _make_full_output(high_recs=0, extra_recs_count=1)
    rec = payload["adjustment_recommendations"][0]
    rec["recommendation_id"] = "audit_l4_elevated_risk_breakdown"
    rec["outcome_tracking"] = {
        "implemented": True,
        "observed_outcome": "positive",
        "confidence_accuracy": "high",
        "evaluation_notes": "连续两周 elevated 降低",
        "week_of_outcome": "2026-W20",
    }
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    outcome = normed["adjustment_recommendations"][0]["outcome_tracking"]
    assert outcome["recommendation_id"] == "audit_l4_elevated_risk_breakdown"
    assert outcome["implemented"] is True
    assert outcome["observed_outcome"] == "positive"
    assert outcome["confidence_accuracy"] == "high"
    assert outcome["week_of_outcome"] == "2026-W20"


def test_normalize_output_accepts_recommendation_id_aliases():
    payload = _make_full_output(high_recs=0, extra_recs_count=1)
    rec = payload["adjustment_recommendations"][0]
    rec["canonical_id"] = "improve_v16_change_mind_structure"
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    rec = normed["adjustment_recommendations"][0]
    assert rec["recommendation_id"] == "improve_v16_change_mind_structure"
    assert rec["normalized_recommendation_id"] == "improve_v16_change_mind_structure"


def test_normalize_output_marks_unstable_recommendation_id():
    payload = _make_full_output(high_recs=0, extra_recs_count=1)
    rec = payload["adjustment_recommendations"][0]
    rec["recommendation_id"] = "audit_l4_elevated_2026_05_10_75pct"
    rec["目标"] = "审计 L4 elevated risk_breakdown"
    rec["具体调整路径"] = "审计 L4 elevated risk_breakdown"
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    rec = normed["adjustment_recommendations"][0]
    assert rec["unstable_recommendation_id"] is True
    assert rec["recommendation_id"] == "audit_l4_elevated_2026_05_10_75pct"
    assert rec["normalized_recommendation_id"] == "audit_l4_elevated_risk_breakdown"


def test_normalize_output_marks_duplicate_recommendation_id():
    payload = _make_full_output(high_recs=0, extra_recs_count=2)
    for rec in payload["adjustment_recommendations"]:
        rec["recommendation_id"] = "audit_l3_extending_late_phase"
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    assert all(
        rec["duplicate_recommendation_id"]
        for rec in normed["adjustment_recommendations"]
    )


def test_normalize_output_caps_observation_confidence():
    payload = _make_full_output(high_recs=0, extra_recs_count=1)
    rec = payload["adjustment_recommendations"][0]
    rec["具体调整路径"] = "建议先观察 4 周,不在本周做参数调整"
    rec["evidence_confidence"] = "high"
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    assert normed["adjustment_recommendations"][0]["evidence_confidence"] == "medium"


def test_normalize_output_marks_repetition_without_confirmation():
    payload = _make_full_output(high_recs=0, extra_recs_count=1)
    rec = payload["adjustment_recommendations"][0]
    rec["目标"] = "审计 elevated"
    rec["具体调整路径"] = "连续观察 elevated"
    rec["evidence_confidence"] = "low"
    payload["temporal_consistency_diagnostics"] = {
        "recommendation_recurrence": [
            {
                "target": "审计 elevated",
                "action": "连续观察 elevated",
                "weeks_seen": 3,
            },
        ],
    }
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    assert (
        normed["adjustment_recommendations"][0]
        ["possible_repetition_without_confirmation"]
        is True
    )


def test_normalize_output_converts_days_rate_to_valid_runs():
    payload = _make_full_output()
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    hc = normed["hard_constraint_activation_review"]
    assert hc[VALIDATOR_KEYS[0]]["rate"] == "1/7 valid_runs"


def test_normalize_output_repairs_invalid_valid_runs_rate_text():
    payload = _make_full_output()
    payload["hard_constraint_activation_review"][VALIDATOR_KEYS[0]]["rate"] = (
        "1/" + "valid_runs " + "valid_runs"
    )
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    hc = normed["hard_constraint_activation_review"]
    assert hc[VALIDATOR_KEYS[0]]["rate"] == "1/0 valid_runs"


def test_normalize_output_handles_missing_review_section():
    """整段 hard_constraint_activation_review 缺失 → 不动(caller fallback 路径)。"""
    payload = _make_full_output()
    del payload["hard_constraint_activation_review"]
    normed = WeeklyReviewAnalyst.normalize_output(payload)
    assert "hard_constraint_activation_review" not in normed


# ============================================================
# 5. count_critical_recommendations(D1=a alerts severity 用)
# ============================================================

def test_count_critical_zero():
    payload = _make_full_output(high_recs=0, extra_recs_count=2)
    assert WeeklyReviewAnalyst.count_critical_recommendations(payload) == 0


def test_count_high_only_is_not_critical():
    payload = _make_full_output(high_recs=2, extra_recs_count=1)
    assert WeeklyReviewAnalyst.count_critical_recommendations(payload) == 0
    assert WeeklyReviewAnalyst.count_high_priority_recommendations(payload) == 2


def test_count_explicit_recommendation_critical():
    payload = _make_full_output(high_recs=0, extra_recs_count=0)
    payload["adjustment_recommendations"].append({
        "目标": "x",
        "具体调整路径": "y",
        "优先级": "medium",
        "severity": "critical",
        "影响": "z",
    })
    assert WeeklyReviewAnalyst.count_critical_recommendations(payload) == 1


def test_count_explicit_system_health_critical():
    payload = _make_full_output(high_recs=0, extra_recs_count=0)
    payload["system_health_diagnosis"][0]["severity"] = "critical"
    assert WeeklyReviewAnalyst.count_critical_recommendations(payload) == 1


def test_count_critical_handles_non_dict():
    assert WeeklyReviewAnalyst.count_critical_recommendations(None) == 0
    assert WeeklyReviewAnalyst.count_critical_recommendations({}) == 0
    assert WeeklyReviewAnalyst.count_critical_recommendations(
        {"adjustment_recommendations": "not_a_list"}
    ) == 0


# ============================================================
# 6. _build_user_prompt 字段透传
# ============================================================

def test_build_user_prompt_includes_window_and_perf_raw():
    agent = WeeklyReviewAnalyst()
    prompt = agent._build_user_prompt({
        "window": {"start_utc": "2026-05-03T14:00:00Z",
                    "end_utc": "2026-05-10T14:00:00Z", "days": 7},
        "performance_summary_raw": {"total_runs": 7, "ai_failures": 2},
        "hard_constraint_activation_raw": {
            "v_activations": {"validator_1_stop_loss_overridden": {"activations": 0}},
        },
        "l3_diagnostics": {"phase_distribution": {"late": 2}},
        "l4_diagnostics": {"risk_score_summary": {"avg": 72}},
        "validator_diagnostics": {"v16_samples": [{"run_at": "x"}]},
        "temporal_consistency_diagnostics": {
            "l4_elevated_trend": [{"week_start_utc": "2026-05-04"}],
        },
    })
    assert "2026-05-03T14:00:00Z" in prompt
    assert "2026-05-10T14:00:00Z" in prompt
    assert "total_runs" in prompt
    assert "ai_failures" in prompt
    assert "23 条 V Validator" in prompt
    assert "L3 诊断证据" in prompt
    assert "L4 诊断证据" in prompt
    assert "Validator 诊断证据" in prompt
    assert "时间连续性诊断" in prompt
    assert "evidence_confidence" in prompt
    assert "recommendation_id" in prompt
    assert "recommendation_category" in prompt
    assert "证据不足,建议补诊断" in prompt


# ============================================================
# 7. 枚举常量
# ============================================================

def test_valid_enums():
    assert VALID_PRIORITIES == ("high", "medium", "low")
    assert VALID_SEVERITIES == ("critical", "warning", "info")
    assert VALID_EVIDENCE_CONFIDENCE == ("low", "medium", "high")
    assert VALID_OBSERVED_OUTCOMES == ("positive", "neutral", "negative", "unknown")
    assert VALID_CONFIDENCE_ACCURACY == ("low", "medium", "high")
    assert "l3_behavior" in VALID_RECOMMENDATION_CATEGORIES
    assert "change_threshold" in VALID_RECOMMENDATION_ACTION_TYPES
