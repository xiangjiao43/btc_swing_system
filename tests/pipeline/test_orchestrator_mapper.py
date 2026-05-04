"""tests/pipeline/test_orchestrator_mapper.py — Sprint 1.9-A.5.1。

_map_orchestrator_result_to_state 19 列每列至少 1 个断言。
全 mock,不调真 anthropic API。§Z 端到端字段值断言。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.data.storage.connection import init_db
from src.pipeline._orchestrator_mapper import (
    # Sprint 1.10-J commit 5 §X:_build_classifier_state 已删
    # Sprint 1.10-J commit 6 §X:_build_cold_start_state 已删
    _build_full_state_json,
    _build_summary_v13,
    _derive_ai_model,
    _derive_fallback_level,
    _map_orchestrator_result_to_state,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "m.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _make_result(
    *,
    status: str = "ok",
    to_state: str = "LONG_PLANNED",
    stance: str = "bullish",
    grade: str = "A",
    risk_tier: str = "moderate",
    macro_stance: str = "supportive",
    model_used: str = "claude-sonnet-4-5-20250929",
) -> dict:
    return {
        "layers": {
            "l1": {"regime": "trend_up", "confidence": 0.9,
                   "model_used": model_used},
            "l2": {"stance": stance, "phase": "early"},
            "l3": {"opportunity_grade": grade, "execution_permission": "active_open"},
            "l4": {"risk_tier": risk_tier,
                   "hard_invalidation_levels": [{"price": 73200,
                                                 "type": "swing_low"}],
                   "position_cap_multiplier": 0.78},
            "l5": {"macro_stance": macro_stance,
                   "extreme_event_detected": False},
            "master": {
                "state_transition": {"from_state": "FLAT",
                                     "to_state": to_state,
                                     "transition_reasoning": "..."},
                "trade_plan": {"action": "open"},
                "position_cap_final": {"value": 0.4409},
            },
        },
        "validator": {"violations": [], "passed": True},
        "status": status,
        "latency_ms": {"l1": 100, "l2": 110, "master": 200},
        "_system_provided": {"crowding_multiplier": 0.85, "event_multiplier": 0.95},
    }


def _make_context() -> dict:
    return {
        "_shared": {
            "current_close": 75749.5,
            "events_count_72h": 2,
            "btc_macro_corr_60d": 0.45,
            "reference_timestamp_utc": "2026-05-01T08:00:00Z",
        },
        "l5": {"extreme_event_flags": {"flash_crash_detected_24h": False}},
        "l2": {"rule_cycle_position": {"label": "early_bull",
                                       "confidence": 0.74}},
    }


# ============================================================
# 19 列映射 — 每列至少 1 测试
# ============================================================

def test_col_1_run_id_is_uuid_hex(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert isinstance(out["run_id"], str)
    assert len(out["run_id"]) == 32  # uuid hex


def test_col_2_3_timestamps_format(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert out["generated_at_utc"].endswith("Z")
    assert "T" in out["generated_at_utc"]
    assert "+08:00" in out["generated_at_bjt"]


def test_col_4_reference_timestamp_from_shared(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert out["reference_timestamp_utc"] == "2026-05-01T08:00:00Z"


def test_col_4_reference_timestamp_falls_back_when_missing(conn):
    ctx = _make_context()
    del ctx["_shared"]["reference_timestamp_utc"]
    out = _map_orchestrator_result_to_state(_make_result(), ctx, conn)
    # fallback 到 generated_at_utc
    assert out["reference_timestamp_utc"] == out["generated_at_utc"]


def test_col_5_previous_run_id_when_provided(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(), _make_context(), conn,
        previous_run={"run_id": "abc123", "action_state": "FLAT"},
    )
    assert out["previous_run_id"] == "abc123"


def test_col_5_previous_run_id_none_when_no_previous(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert out["previous_run_id"] is None


def test_col_6_action_state_from_master_state_transition(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(to_state="LONG_PLANNED"), _make_context(), conn,
    )
    assert out["action_state"] == "LONG_PLANNED"


def test_col_6_action_state_fallback_flat_when_master_missing(conn):
    result = _make_result()
    result["layers"]["master"] = {}
    out = _map_orchestrator_result_to_state(result, _make_context(), conn)
    assert out["action_state"] == "FLAT"


def test_col_7_stance_from_l2(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(stance="bearish"), _make_context(), conn,
    )
    assert out["stance"] == "bearish"


def test_col_8_btc_price_from_shared_current_close(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert out["btc_price_usd"] == 75749.5


def test_col_9_state_transitioned_1_when_changed(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(to_state="LONG_PLANNED"), _make_context(), conn,
        previous_run={"run_id": "x", "action_state": "FLAT"},
    )
    assert out["state_transitioned"] == 1


def test_col_9_state_transitioned_0_when_same(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(to_state="FLAT"), _make_context(), conn,
        previous_run={"run_id": "x", "action_state": "FLAT"},
    )
    assert out["state_transitioned"] == 0


def test_col_9_state_transitioned_0_when_no_previous(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert out["state_transitioned"] == 0


def test_col_10_run_trigger_from_param(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(), _make_context(), conn, run_trigger="manual",
    )
    assert out["run_trigger"] == "manual"


def test_col_11_run_mode_is_ai_orchestrator(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert out["run_mode"] == "ai_orchestrator"


def test_col_12_fallback_level_none_when_ok(conn):
    out = _map_orchestrator_result_to_state(_make_result(status="ok"), _make_context(), conn)
    assert out["fallback_level"] is None


def test_col_12_fallback_level_l1_failed(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(status="degraded_l1_failed"), _make_context(), conn,
    )
    assert out["fallback_level"] == "level_1"


def test_col_12_fallback_level_master_failed(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(status="degraded_master_failed"), _make_context(), conn,
    )
    assert out["fallback_level"] == "level_2"


def test_col_13_system_version_from_param(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(), _make_context(), conn, system_version="1.9-B-test",
    )
    assert out["system_version"] == "1.9-B-test"


def test_col_14_rules_version_default(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert out["rules_version"] == "v1.3.0"


def test_col_15_strategy_flavor_v13_ai_majority(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert out["strategy_flavor"] == "v1.3_ai_majority"


# Sprint 1.10-K-A commit 2 §X(v1.4 §11.2):
# observation_category / cold_start mapped 字段整删(配合 schema.sql / dao.py /
# state_builder.py / migration 015 真跑)。原 1.10-J graceful NULL/0 测试改为"字段不存在"。
def test_col_observation_category_not_in_mapped_output(conn):
    """1.10-K-A commit 2 后:mapped 字典不再含 observation_category key。"""
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert "observation_category" not in out


def test_col_cold_start_not_in_mapped_output(conn):
    """1.10-K-A commit 2 后:mapped 字典不再含 cold_start key。"""
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    assert "cold_start" not in out


def test_col_18_ai_model_actual_from_first_layer_with_model(conn):
    out = _map_orchestrator_result_to_state(
        _make_result(model_used="claude-opus-4-7"), _make_context(), conn,
    )
    assert out["ai_model_actual"] == "claude-opus-4-7"


def test_col_18_ai_model_actual_none_when_no_layer_has_model(conn):
    result = _make_result()
    for layer_name in ("l1", "l2", "l3", "l4", "l5", "master"):
        layer = result["layers"][layer_name]
        layer.pop("model_used", None)
    out = _map_orchestrator_result_to_state(result, _make_context(), conn)
    assert out["ai_model_actual"] is None


def test_col_19_full_state_json_contains_layers(conn):
    """full_state_json 必须含 layers 子键(parse_previous 依赖)。"""
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    parsed = json.loads(out["full_state_json"])
    assert "layers" in parsed
    assert set(parsed["layers"].keys()) == {"l1", "l2", "l3", "l4", "l5", "master"}
    # 每层有内容
    assert parsed["layers"]["l1"]["regime"] == "trend_up"
    assert parsed["layers"]["master"]["state_transition"]["to_state"] == "LONG_PLANNED"


def test_col_19_full_state_json_contains_validator_and_status(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    parsed = json.loads(out["full_state_json"])
    assert parsed["validator"]["passed"] is True
    assert parsed["status"] == "ok"


def test_col_19_full_state_json_contains_context_summary(conn):
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    parsed = json.loads(out["full_state_json"])
    cs = parsed["context_summary"]
    assert cs["current_close"] == 75749.5
    assert cs["events_count_72h"] == 2
    assert cs["btc_macro_corr_60d"] == 0.45
    assert "extreme_event_flags" in cs
    assert "rule_cycle_position" in cs


def test_col_19_full_state_json_does_not_contain_pandas_objects(conn):
    """ensure pandas Series / DataFrame 不被 dump 进 JSON(默认 default=str)。"""
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    # 单纯能 json.loads 就证明没有 unserializable 对象漏出
    parsed = json.loads(out["full_state_json"])
    assert isinstance(parsed, dict)


# ============================================================
# 完整 19 列 schema 断言
# ============================================================

def test_returns_all_17_strategy_runs_columns(conn):
    """1.10-K-A commit 2 §X:从 19 列降到 17 列(删 observation_category / cold_start)。"""
    out = _map_orchestrator_result_to_state(_make_result(), _make_context(), conn)
    expected_keys = {
        "run_id", "generated_at_utc", "generated_at_bjt",
        "reference_timestamp_utc", "previous_run_id",
        "action_state", "stance", "btc_price_usd",
        "state_transitioned", "run_trigger", "run_mode",
        "fallback_level", "system_version", "rules_version",
        "strategy_flavor", "ai_model_actual", "full_state_json",
    }
    assert set(out.keys()) == expected_keys


# ============================================================
# 辅助函数测试
# ============================================================

def test_derive_fallback_level_buckets():
    assert _derive_fallback_level("ok") is None
    assert _derive_fallback_level("degraded_l1_failed") == "level_1"
    assert _derive_fallback_level("degraded_l2_xxx") == "level_1"
    assert _derive_fallback_level("degraded_l3_yyy") == "level_2"
    assert _derive_fallback_level("degraded_l4_yyy") == "level_2"
    assert _derive_fallback_level("degraded_l5_zzz") == "level_2"
    assert _derive_fallback_level("degraded_master_anything") == "level_2"
    assert _derive_fallback_level("unknown_status") == "level_3"


# Sprint 1.10-J commit 6 §X:test_build_cold_start_state_returns_dict_with_3_keys
# 整删(_build_cold_start_state 函数已删,cold_start 整套机制删)

# Sprint 1.10-J commit 5 §X:test_build_classifier_state_shape 整删
# (_build_classifier_state 函数已删,observation_classifier 整删)


def test_derive_ai_model_skips_layers_without_model_used():
    layers = {
        "l1": {},  # 无 model_used
        "l2": {},
        "l3": {"model_used": "claude-haiku-4-5"},
        "l4": {"model_used": "claude-sonnet-4-5"},
        "l5": {}, "master": {},
    }
    # 取第一个有 model_used 的(l3)
    assert _derive_ai_model(layers) == "claude-haiku-4-5"


def test_build_full_state_json_handles_missing_keys():
    """result/context 缺关键字段 → 不抛错,JSON 仍可解析。"""
    json_str = _build_full_state_json({}, {})
    parsed = json.loads(json_str)
    assert "layers" in parsed
    assert parsed["layers"] == {}


# ============================================================
# _build_summary_v13(Sprint 1.9-A.5.3)
# ============================================================

def test_build_summary_v13_extracts_real_fields():
    """完整 result + mapped → summary 所有 22+ 字段都不是 null,值与 mock 对应。"""
    result = {
        "layers": {
            "l1": {"regime": "transition_up", "volatility_regime": "normal",
                   "tokens_in": 8500, "tokens_out": 1200,
                   "status": "success"},
            "l2": {"stance": "bullish", "phase": "early",
                   "stance_confidence_tier": "high",
                   "tokens_in": 12000, "tokens_out": 1500,
                   "status": "success"},
            "l3": {"opportunity_grade": "C",
                   "execution_permission": "watch",
                   "anti_pattern_flags": [],
                   "tokens_in": 4500, "tokens_out": 800,
                   "status": "success"},
            "l4": {"risk_tier": "moderate",
                   "position_cap_multiplier": 0.78,
                   "tokens_in": 15000, "tokens_out": 1700,
                   "status": "success"},
            "l5": {"macro_stance": "neutral", "headwind_score": 28,
                   "tokens_in": 6000, "tokens_out": 1100,
                   "status": "success"},
            "master": {
                "state_transition": {"from_state": "FLAT",
                                     "to_state": "FLAT",
                                     "transition_reasoning": "L3=C 等待"},
                "trade_plan": {"action": "watch", "direction": None},
                "narrative": "BTC 处于过渡上升,等待更好机会窗口...",
                "confidence": 0.65,
                "status": "success",
                "tokens_in": 22000, "tokens_out": 3000,
            },
        },
        "status": "ok",
    }
    mapped = {
        "run_id": "abc123",
        "reference_timestamp_utc": "2026-05-01T08:00:00Z",
        "cold_start": 0,
    }
    summary = _build_summary_v13(result, mapped)

    # metadata
    assert summary["run_id"] == "abc123"
    assert summary["reference_ts"] == "2026-05-01T08:00:00Z"
    # Sprint 1.10-J commit 6 §X:删 cold_start 字段断言(_build_summary_v13 已删此 key)

    # L1
    assert summary["L1.regime"] == "transition_up"
    assert summary["L1.volatility"] == "normal"
    # L2
    assert summary["L2.stance"] == "bullish"
    assert summary["L2.phase"] == "early"
    assert summary["L2.stance_confidence"] == "high"
    # L3
    assert summary["L3.opportunity_grade"] == "C"
    assert summary["L3.execution_permission"] == "watch"
    assert summary["L3.anti_pattern_flags"] == []
    # L4
    assert summary["L4.position_cap"] == 0.78
    # L5
    assert summary["L5.macro_environment"] == "neutral"
    assert summary["L5.macro_headwind_vs_btc"] == 28

    # AI ops
    assert summary["ai.status"] == "ok"
    assert summary["ai.tokens_in"] == 8500 + 12000 + 4500 + 15000 + 6000 + 22000
    assert summary["ai.tokens_out"] == 1200 + 1500 + 800 + 1700 + 1100 + 3000
    assert "BTC 处于过渡上升" in summary["ai.summary_preview"]

    # state machine
    assert summary["state_machine.previous"] == "FLAT"
    assert summary["state_machine.current"] == "FLAT"
    assert summary["state_machine.transition_reason"] == "L3=C 等待"
    assert summary["state_machine.stable_in_state"] is True
    # Sprint 1.10-K-A commit 7 方案 C 镜像:thesis dict + system_state
    # FLAT → thesis=None, system_state='normal'
    assert summary["state_machine.thesis"] is None
    assert summary["state_machine.system_state"] == "normal"

    # adjudicator
    assert summary["adjudicator.action"] == "watch"
    assert summary["adjudicator.direction"] is None
    assert summary["adjudicator.confidence"] == 0.65
    assert summary["adjudicator.status"] == "success"
    assert "BTC 处于过渡上升" in summary["adjudicator.rationale_preview"]

    # pipeline meta(全 success → degraded_stages 空)
    assert summary["pipeline.degraded_stages"] == []
    assert summary["pipeline.failure_count"] == 0


def test_build_summary_v13_marks_degraded_layers():
    """L1+L4 status=degraded → pipeline.degraded_stages 含 l1+l4。"""
    result = {
        "layers": {
            "l1": {"status": "degraded_l1_failed", "regime": None},
            "l2": {"status": "success", "stance": "bullish"},
            "l3": {"status": "success"},
            "l4": {"status": "degraded_l4_failed"},
            "l5": {"status": "success"},
            "master": {"status": "success",
                       "state_transition": {"from_state": "FLAT",
                                            "to_state": "FLAT"},
                       "trade_plan": {"action": "watch"}},
        },
        "status": "degraded_l1_failed",
    }
    mapped = {"run_id": "x", "reference_timestamp_utc": "2026-05-01T00:00:00Z",
              "cold_start": 1}
    summary = _build_summary_v13(result, mapped)
    assert "l1" in summary["pipeline.degraded_stages"]
    assert "l4" in summary["pipeline.degraded_stages"]
    assert "l2" not in summary["pipeline.degraded_stages"]
    assert summary["pipeline.failure_count"] == 2


def test_build_summary_v13_handles_empty_result():
    """空 result → 所有字段 None / 0,不抛异常。"""
    summary = _build_summary_v13({}, {})
    assert summary["L1.regime"] is None
    assert summary["L2.stance"] is None
    assert summary["adjudicator.action"] is None
    assert summary["ai.tokens_in"] == 0
    assert summary["pipeline.failure_count"] == 0
