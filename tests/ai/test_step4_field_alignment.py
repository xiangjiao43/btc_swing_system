"""tests/ai/test_step4_field_alignment.py — Sprint 1.9-A.4 字段对齐测试。

验证 6 agent _build_user_prompt 在收到 ContextBuilder 构造的 per-agent
ctx 后,生成的 prompt 含 v3/v5 prompt 期望的关键字段。

+ parse_previous_layer_outputs 4 个测试。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.ai.agents import (
    L1RegimeAnalyst,
    L2DirectionAnalyst,
    L3OpportunityAnalyst,
    L4RiskAnalyst,
    L5MacroAnalyst,
    MasterAdjudicator,
)
from src.ai.context_builder import (
    ContextBuilder,
    parse_previous_layer_outputs,
)
from src.data.storage.connection import init_db


@pytest.fixture
def empty_db_ctx():
    tmp = Path(tempfile.mkdtemp()) / "f.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    return ContextBuilder(conn).build_full_context()


# ============================================================
# 6 agent _build_user_prompt 字段对齐测试
# ============================================================

def test_l1_prompt_contains_klines_30d_close_and_computed_indicators(empty_db_ctx):
    agent = L1RegimeAnalyst(client=None)
    prompt = agent._build_user_prompt(empty_db_ctx["l1"])
    assert "klines_1d_30d_close" in prompt
    assert "computed_indicators" in prompt
    # 不应含旧字段名
    assert '"indicators"' not in prompt   # 旧字段名
    assert "klines_1d_summary" not in prompt


def test_l2_prompt_contains_required_v2_fields(empty_db_ctx):
    agent = L2DirectionAnalyst(client=None)
    # 注入 l1_output(orchestrator runtime 行为)
    l2_ctx = dict(empty_db_ctx["l2"])
    l2_ctx["l1_output"] = {"regime": "trend_up"}
    prompt = agent._build_user_prompt(l2_ctx)
    assert "klines_1d_30d_close" in prompt
    assert "computed_indicators" in prompt
    assert "rule_cycle_position" in prompt
    assert "l1_output" in prompt
    # 不应含旧字段名
    assert "derivatives_snapshot" not in prompt
    assert "onchain_structure_snapshot" not in prompt
    assert "price_structure" not in prompt
    assert "previous_l1_output" not in prompt


def test_l3_prompt_contains_v3_fields_no_label_drift(empty_db_ctx):
    agent = L3OpportunityAnalyst(client=None)
    l3_ctx = dict(empty_db_ctx["l3"])
    l3_ctx["l1_output"] = {"regime": "trend_up"}
    l3_ctx["l2_output"] = {"stance": "bullish"}
    l3_ctx["anti_pattern_signals"] = {
        "is_extending_late_phase": False,
        "is_against_long_cycle": False,
        "is_chasing_breakout_no_pullback": False,
        "is_failing_at_resistance": False,
        "is_after_extreme_event_no_reset": False,
    }
    prompt = agent._build_user_prompt(l3_ctx)
    assert "risk_preview" in prompt
    assert "anti_pattern_signals" in prompt
    assert "current_state" in prompt
    assert "l1_output" in prompt
    assert "l2_output" in prompt
    # 不应含 v3 删除的标签字段
    assert '"crowding_level"' not in prompt
    assert '"event_risk_active"' not in prompt
    assert '"macro_warning_count"' not in prompt
    # 不应含旧 asopr / cdd / cycle_position_rule / funding_pressure
    assert '"asopr"' not in prompt
    assert '"cdd"' not in prompt


def test_l4_prompt_contains_required_v2_fields(empty_db_ctx):
    agent = L4RiskAnalyst(client=None)
    l4_ctx = dict(empty_db_ctx["l4"])
    l4_ctx["l1_output"] = {"regime": "trend_up"}
    l4_ctx["l2_output"] = {"stance": "bullish"}
    l4_ctx["l3_output"] = {"opportunity_grade": "A"}
    prompt = agent._build_user_prompt(l4_ctx)
    assert "computed_indicators" in prompt
    assert "current_state" in prompt
    assert "l1_output" in prompt
    assert "l2_output" in prompt
    assert "l3_output" in prompt
    # 不应含违反铁律 1 的 crowding_signals 标签
    assert "crowding_signals" not in prompt
    assert '"current_price"' not in prompt   # 旧字段名


def test_l5_prompt_contains_v3_fields(empty_db_ctx):
    agent = L5MacroAnalyst(client=None)
    prompt = agent._build_user_prompt(empty_db_ctx["l5"])
    assert "computed_macro_indicators" in prompt
    assert "events_calendar_72h" in prompt
    assert "extreme_event_flags" in prompt
    # 不应含旧字段名
    assert '"macro_factors"' not in prompt
    assert '"events_72h"' not in prompt


def test_master_prompt_contains_v2_fields(empty_db_ctx):
    agent = MasterAdjudicator(client=None)
    master_ctx = dict(empty_db_ctx["master"])
    # previous_strategy_run 默认 None,会被 _build_user_prompt 过滤;
    # 注入非 None 才能验证字段在 prompt 里
    master_ctx["previous_strategy_run"] = {"run_id": "x",
                                           "action_state": "FLAT"}
    master_ctx["l1_output"] = {"regime": "trend_up"}
    master_ctx["l2_output"] = {"stance": "bullish"}
    master_ctx["l3_output"] = {"opportunity_grade": "A"}
    master_ctx["l4_output"] = {"risk_tier": "moderate"}
    master_ctx["l5_output"] = {"macro_stance": "supportive"}
    master_ctx["_system_provided"] = {
        "crowding_multiplier": 0.85,
        "event_multiplier": 0.95,
        "current_close": 75749,
    }
    prompt = agent._build_user_prompt(master_ctx)
    assert "current_state" in prompt
    assert "previous_strategy_run" in prompt
    assert "_system_provided" in prompt
    assert "l1_output" in prompt
    assert "l2_output" in prompt
    assert "l3_output" in prompt
    assert "l4_output" in prompt
    assert "l5_output" in prompt
    # 不应含旧字段名
    assert "state_machine_current" not in prompt
    assert "allowed_transitions" not in prompt


# ============================================================
# parse_previous_layer_outputs 4 个测试
# ============================================================

def test_parse_previous_handles_none():
    out = parse_previous_layer_outputs(None)
    assert all(v is None for v in out.values())
    assert set(out.keys()) == {
        "previous_l1", "previous_l2", "previous_l3",
        "previous_l4", "previous_l5", "previous_master",
    }


def test_parse_previous_handles_empty_state():
    """state 字段是空 dict — 仍返回全 None,不抛错。"""
    sr = {"run_id": "x", "state": {}}
    out = parse_previous_layer_outputs(sr)
    assert all(v is None for v in out.values())


def test_parse_previous_extracts_layers_from_full_state_json():
    """state.layers.l1-l5 + master 各自被正确提取。"""
    sr = {
        "run_id": "test-run",
        "state": {
            "layers": {
                "l1": {"regime": "trend_up", "confidence": 0.9},
                "l2": {"stance": "bullish", "phase": "early"},
                "l3": {"opportunity_grade": "A"},
                "l4": {"risk_tier": "moderate"},
                "l5": {"macro_stance": "supportive"},
                "master": {"action": "open"},
            },
        },
    }
    out = parse_previous_layer_outputs(sr)
    assert out["previous_l1"]["regime"] == "trend_up"
    assert out["previous_l2"]["stance"] == "bullish"
    assert out["previous_l3"]["opportunity_grade"] == "A"
    assert out["previous_l4"]["risk_tier"] == "moderate"
    assert out["previous_l5"]["macro_stance"] == "supportive"
    assert out["previous_master"]["action"] == "open"


def test_parse_previous_handles_raw_full_state_json_string():
    """state 字段不存在,但 full_state_json 是 raw JSON 字符串 — 兼容旧格式。"""
    payload = {"layers": {"l1": {"regime": "trend_up"},
                          "l5": {"macro_stance": "neutral"}}}
    sr = {"run_id": "test", "full_state_json": json.dumps(payload)}
    out = parse_previous_layer_outputs(sr)
    assert out["previous_l1"]["regime"] == "trend_up"
    assert out["previous_l5"]["macro_stance"] == "neutral"
    assert out["previous_l2"] is None  # 没有 l2 → None


def test_parse_previous_handles_v12_legacy_format():
    """旧 v1.2 格式没有 layers 键 → 全 None,不抛错。"""
    sr = {
        "run_id": "old",
        "state": {
            "evidence_reports": {"layer_1": {...}},
            "composite_factors": {},
            # 没有 "layers" 键
        },
    }
    out = parse_previous_layer_outputs(sr)
    assert all(v is None for v in out.values())
