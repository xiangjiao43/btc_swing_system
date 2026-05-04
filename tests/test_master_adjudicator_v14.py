"""Sprint 1.10-D 单测:MasterAdjudicator v1.4 改造(v1.4 §3.3.6 + §6.4)。

D2=a 锁定:全部 mock 不调真 API。
D4=a 锁定:只验证 mode 字段(其他字段留 1.10-E Validator 24 条)。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.ai.agents.master_adjudicator import (
    MasterAdjudicator, VALID_MODES,
)


# ============================================================
# _build_user_prompt v1.4 thesis-aware
# ============================================================

def test_build_user_prompt_includes_v14_thesis_fields():
    """user prompt 应包含 v1.4 新加的 thesis-aware 7 字段。"""
    agent = MasterAdjudicator()
    context = {
        "l1_output": {"regime": "trend_up"},
        "l2_output": {"stance": "bullish"},
        "l3_output": {"opportunity_grade": "A"},
        "l4_output": {"risk_level": "elevated"},
        "l5_output": {"macro_stance": "neutral"},
        "active_thesis": {"thesis_id": "th_x", "direction": "long"},
        "current_position": {"long_btc_amount": 0.25},
        "pending_orders": [{"order_id": "o1", "type": "entry"}],
        "cooldown_state": {"in_cooldown": False},
        "fuse_state": {"in_14d_fuse": False},
        "last_5_assessments": [{"thesis_id": "th_old"}],
    }
    p = agent._build_user_prompt(context)
    assert "Master AI v1.4 输入" in p
    assert "active_thesis" in p
    assert "current_position" in p
    assert "pending_orders" in p
    assert "cooldown_state" in p
    assert "fuse_state" in p
    assert "last_5_assessments" in p
    # L1-5 也在
    assert "l1_output" in p
    assert "l5_output" in p


def test_build_user_prompt_omits_none_fields():
    """None 字段应从 prompt 删除(不出现 'key': null 噪音)。"""
    agent = MasterAdjudicator()
    context = {
        "l1_output": {"regime": "trend_up"},
        "l3_output": {"opportunity_grade": "A"},
        "active_thesis": None,           # ← None,应被删
        "current_position": None,        # ← None,应被删
        "cooldown_state": {"in_cooldown": False},
        "fuse_state": None,              # ← None,应被删
    }
    p = agent._build_user_prompt(context)
    # 顶层 None 字段不应出现
    assert "active_thesis" not in p or '"active_thesis": null' not in p
    assert '"current_position": null' not in p
    # 非 None 字段在
    assert "l1_output" in p
    assert "cooldown_state" in p


def test_build_user_prompt_handles_empty_lists():
    """空 list(pending_orders/last_5_assessments)应保留为 [],不删。"""
    agent = MasterAdjudicator()
    context = {
        "l1_output": {"regime": "trend_up"},
        "active_thesis": None,
        "pending_orders": [],            # 空 list
        "last_5_assessments": [],
    }
    p = agent._build_user_prompt(context)
    assert "pending_orders" in p
    assert "last_5_assessments" in p


# ============================================================
# _fallback_output v1.4 mode 字段
# ============================================================

def test_fallback_output_has_mode_silent_cooldown():
    """基础 fallback 应是 mode=silent_cooldown(最保守)。"""
    agent = MasterAdjudicator()
    out = agent._fallback_output()
    assert out["mode"] == "silent_cooldown"
    assert "silent_reason" in out
    assert out["status"] == "degraded"
    assert out["agent"] == "master_adjudicator"


def test_fallback_output_has_required_fields():
    """fallback 仍含 narrative / counter_arguments / what_would_change_mind。"""
    agent = MasterAdjudicator()
    out = agent._fallback_output()
    assert "narrative" in out
    assert isinstance(out["counter_arguments"], list)
    assert len(out["counter_arguments"]) >= 1
    assert isinstance(out["what_would_change_mind"], list)
    assert len(out["what_would_change_mind"]) >= 3


# ============================================================
# thesis_aware_fallback(v1.4 §6.4 真表)
# ============================================================

def test_thesis_aware_fallback_with_active_thesis():
    """有 active_thesis + master 失败 → mode=evaluate_existing 保留 thesis。"""
    out = MasterAdjudicator.thesis_aware_fallback(has_active_thesis=True)
    assert out["mode"] == "evaluate_existing"
    assert out["status"] == "degraded_master_failed_keep_thesis"
    # thesis_assessment 子字段
    ta = out["thesis_assessment"]
    assert ta["still_valid"] == "mostly"
    assert ta["which_break_triggered"] is None
    assert ta["stop_loss_adjustment"] is None
    assert "master_ai_failed" in ta["objective_evidence"]
    assert "master AI 失败" in ta["reasoning"]


def test_thesis_aware_fallback_without_active_thesis():
    """无 active_thesis + master 失败 → mode=silent_cooldown。"""
    out = MasterAdjudicator.thesis_aware_fallback(has_active_thesis=False)
    assert out["mode"] == "silent_cooldown"
    assert out["status"] == "degraded_master_failed_silent"
    assert "silent_reason" in out
    assert "master AI 失败" in out["silent_reason"]


def test_thesis_aware_fallback_never_creates_or_closes_thesis():
    """v1.4 §6.4 关键约束:fallback 不能创建 / 关闭 thesis。"""
    # 无 thesis → silent (NOT new_thesis)
    out_none = MasterAdjudicator.thesis_aware_fallback(has_active_thesis=False)
    assert out_none["mode"] != "new_thesis"
    assert "new_thesis" not in out_none

    # 有 thesis → evaluate_existing 但 invalidated 不允许(只能 mostly)
    out_active = MasterAdjudicator.thesis_aware_fallback(has_active_thesis=True)
    assert out_active["thesis_assessment"]["still_valid"] != "invalidated"


# ============================================================
# validate_mode(D4=a 轻量验证)
# ============================================================

def test_validate_mode_evaluate_existing_with_active_thesis():
    ok, err = MasterAdjudicator.validate_mode(
        {"mode": "evaluate_existing"}, has_active_thesis=True,
    )
    assert ok and err is None


def test_validate_mode_new_thesis_without_active_thesis():
    ok, err = MasterAdjudicator.validate_mode(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        has_active_thesis=False,
    )
    assert ok and err is None


def test_validate_mode_silent_cooldown_always_ok():
    """silent_cooldown 不论 active_thesis 状态都允许(冷却期 / 数据降级)。"""
    ok1, _ = MasterAdjudicator.validate_mode(
        {"mode": "silent_cooldown"}, has_active_thesis=True,
    )
    ok2, _ = MasterAdjudicator.validate_mode(
        {"mode": "silent_cooldown"}, has_active_thesis=False,
    )
    assert ok1 and ok2


def test_validate_mode_missing_field():
    ok, err = MasterAdjudicator.validate_mode(
        {"narrative": "x"}, has_active_thesis=False,
    )
    assert not ok
    assert "missing or invalid mode" in err


def test_validate_mode_invalid_enum():
    ok, err = MasterAdjudicator.validate_mode(
        {"mode": "hallucinated_mode"}, has_active_thesis=False,
    )
    assert not ok
    assert "missing or invalid mode" in err


def test_validate_mode_new_thesis_when_active_thesis_exists():
    """有 active_thesis 但 master 输 new_thesis → Validator 6 拦截。"""
    ok, err = MasterAdjudicator.validate_mode(
        {"mode": "new_thesis"}, has_active_thesis=True,
    )
    assert not ok
    assert "Validator 6" in err or "new_thesis" in err


def test_validate_mode_non_dict_result():
    ok, err = MasterAdjudicator.validate_mode(
        "not a dict", has_active_thesis=False,
    )
    assert not ok
    assert "not a dict" in err


# ============================================================
# 集成:mock client → analyze 完整链路
# ============================================================

def _make_mock_client_returning_json(json_response: dict):
    """构造 mock anthropic client,返回固定 JSON 响应。"""
    client = MagicMock()
    # anthropic client.messages.create return mock
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(json_response, ensure_ascii=False))]
    mock_response.stop_reason = "end_turn"
    # tokens
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=200)
    mock_response.model = "claude-sonnet-4-5-20250929"
    client.messages.create.return_value = mock_response
    return client


def test_analyze_with_mock_returns_evaluate_existing():
    """mock AI 返 mode=evaluate_existing → analyze 返 same。"""
    fake_response = {
        "mode": "evaluate_existing",
        "thesis_assessment": {
            "still_valid": "mostly",
            "which_break_triggered": None,
            "reasoning": "DXY 105 < 108 trigger",
            "stop_loss_adjustment": None,
            "objective_evidence": ["DXY 当前 105 < 108"],
        },
        "narrative": "x x x x x",
        "one_line_summary": "持有 thesis 不变",
        "counter_arguments": ["funding z 偏高"],
        "what_would_change_mind": ["A", "B", "C"],
        "evidence_ref": [],
    }
    client = _make_mock_client_returning_json(fake_response)
    agent = MasterAdjudicator(client=client)

    context = {
        "l1_output": {"regime": "trend_up"},
        "l2_output": {"stance": "bullish"},
        "l3_output": {"opportunity_grade": "A"},
        "l4_output": {"risk_level": "elevated"},
        "l5_output": {"macro_stance": "neutral"},
        "active_thesis": {"thesis_id": "th_x", "direction": "long"},
    }
    result = agent.analyze(context, client=client)
    assert result.get("mode") == "evaluate_existing"
    assert result.get("thesis_assessment", {}).get("still_valid") == "mostly"


def test_analyze_with_mock_returns_new_thesis():
    """mock AI 返 mode=new_thesis(无 active_thesis 场景)。"""
    fake_response = {
        "mode": "new_thesis",
        "new_thesis": {
            "direction": "long",
            "confidence_score": 75,
            "core_logic": "L1+L2+L3 五层一致看多",
            "execution_permission": "active_open",
            "entry_orders": [{"price": 74568, "size_pct": 20}],
            "stop_loss": {"price": 67000, "size_pct": 100},
            "take_profit": [{"price": 85000, "size_pct": 50}],
            "break_conditions": [
                "1D 收盘跌破 70000",
                "DXY 突破 108 持续 3 天",
                "L5 极端事件触发",
            ],
            "objective_evidence": ["L3 grade=A"],
        },
        "narrative": "5 段推演...",
        "one_line_summary": "开多 75%",
        "counter_arguments": ["funding 偏拥挤"],
        "what_would_change_mind": ["A", "B", "C"],
        "evidence_ref": [],
    }
    client = _make_mock_client_returning_json(fake_response)
    agent = MasterAdjudicator(client=client)
    context = {
        "l1_output": {"regime": "trend_up"},
        "l3_output": {"opportunity_grade": "A"},
        "active_thesis": None,
    }
    result = agent.analyze(context, client=client)
    assert result.get("mode") == "new_thesis"
    assert result.get("new_thesis", {}).get("direction") == "long"


def test_analyze_with_mock_returns_silent_cooldown():
    """mock AI 返 mode=silent_cooldown(冷却期场景)。"""
    fake_response = {
        "mode": "silent_cooldown",
        "silent_reason": "在 24h 冷却期(剩余 12h)",
        "narrative": "上次 thesis 关闭,在 24h 冷却中",
        "one_line_summary": "冷却中,不出新方向",
        "counter_arguments": ["市场短期有反弹信号"],
        "what_would_change_mind": ["冷却期结束", "L3 升 B/C", "无 active thesis"],
        "evidence_ref": [],
    }
    client = _make_mock_client_returning_json(fake_response)
    agent = MasterAdjudicator(client=client)
    result = agent.analyze({"l1_output": {"regime": "range"}}, client=client)
    assert result.get("mode") == "silent_cooldown"


def test_analyze_unparseable_ai_response_returns_fallback():
    """mock AI 返非 JSON → BaseAgent fallback,mode=silent_cooldown(基础)。"""
    client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="this is not JSON {")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
    mock_response.model = "claude-sonnet-4-5-20250929"
    client.messages.create.return_value = mock_response
    agent = MasterAdjudicator(client=client)
    result = agent.analyze({"l1_output": {"regime": "trend_up"}}, client=client)
    # BaseAgent 兜底 _fallback_output,我们把它改成了 silent_cooldown
    assert result.get("mode") == "silent_cooldown"
    assert result.get("status", "").startswith("degraded")


def test_valid_modes_const_matches_v14_spec():
    assert set(VALID_MODES) == {"evaluate_existing", "new_thesis", "silent_cooldown"}


# ============================================================
# Sprint 1.10-K-B commit 2:prompt 含 V3 / V9 / V21 / V23 hard constraints
# ============================================================

def test_master_prompt_includes_v3_v9_v21_v23_hard_constraints():
    """1.10-K-B:master_adjudicator.txt §三 应含 V3 / V9 / V21 / V23 显式条款。

    覆盖 commit 2 prompt 增量(基于 1.10-K-B 调研选的 4 条 V):
    - V3: entry_orders 总 size_pct ≤ 100%
    - V9: break_conditions 距当前 ≤ 20%(价格类)
    - V21: 不能在该出 new_thesis 时 silent_cooldown(软抗拒)
    - V23: narrative 必须含层间一致性表达
    """
    agent = MasterAdjudicator()
    prompt = agent._load_system_prompt()

    # V3
    assert "Validator 3" in prompt
    assert "size_pct" in prompt and "100" in prompt
    # V9
    assert "Validator 9" in prompt
    assert "20%" in prompt or "≤ 20" in prompt
    # V21 软抗拒
    assert "Validator 21" in prompt
    assert "软抗拒" in prompt
    # V23 narrative 一致性
    assert "Validator 23" in prompt
    assert "层间" in prompt or "矛盾" in prompt
