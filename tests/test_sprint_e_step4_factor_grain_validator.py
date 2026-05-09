"""Sprint E Step 4 — VFactorGrain 验证 + master 整合规则反退化测试。

§Z 端到端:mock 不同 sub-agent _factor_grain 状态,断言 master 输出
execution_permission 与 layer health 一致;违反 → validator_needs_retry。
"""
from __future__ import annotations

from src.ai.validator import (
    validate_master_output,
    validator_factor_grain,
)


def _layer_data_missing_output(layer_id: int) -> dict:
    return {
        "agent": f"l{layer_id}",
        "status": "degraded_data_missing",
        "confidence": 0.0,
        "_factor_grain": {
            "fresh_ratio": 0.0,
            "data_missing": True,
            "ai_skipped": True,
            "layer_id": layer_id,
        },
    }


def _layer_degraded_output(layer_id: int, ratio: float = 0.6) -> dict:
    return {
        "agent": f"l{layer_id}",
        "status": "degraded_factor_grain",
        "confidence": 0.42,
        "_factor_grain": {
            "fresh_ratio": ratio,
            "data_missing": False,
            "ai_skipped": False,
            "layer_id": layer_id,
            "confidence_multiplier": 0.6,
        },
    }


def _layer_healthy_output(layer_id: int) -> dict:
    return {
        "agent": f"l{layer_id}",
        "status": "success",
        "confidence": 0.7,
    }


# ============================================================
# 1. 关键层 data_missing + master 仍 new_thesis → 拒绝
# ============================================================

def test_validator_rejects_new_thesis_when_l2_data_missing():
    master_out = {
        "mode": "new_thesis",
        "narrative": "做多",
        "new_thesis": {
            "direction": "long",
            "execution_permission": "can_open",
        },
    }
    ctx = {
        "l1_output": _layer_healthy_output(1),
        "l2_output": _layer_data_missing_output(2),  # 关键层 stale
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_healthy_output(4),
        "l5_output": _layer_healthy_output(5),
        "active_thesis": None,
    }
    out, act = validator_factor_grain(master_out, ctx)
    assert act["validator_factor_grain_violation"] is True
    assert act["validator_factor_grain_needs_retry"] is True
    assert "L2" in act["validator_factor_grain_reason"] or "2" in str(
        act["validator_factor_grain_reason"]
    )
    assert "factor_grain_master_violation_needs_retry" in (out.get("notes") or [])


def test_validator_rejects_can_open_when_l1_data_missing():
    master_out = {
        "mode": "new_thesis",
        "new_thesis": {"execution_permission": "can_open"},
    }
    ctx = {
        "l1_output": _layer_data_missing_output(1),
        "l2_output": _layer_healthy_output(2),
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_healthy_output(4),
        "l5_output": _layer_healthy_output(5),
        "active_thesis": None,
    }
    out, act = validator_factor_grain(master_out, ctx)
    assert act["validator_factor_grain_violation"] is True


# ============================================================
# 2. 关键层 data_missing + master 给 watch → 通过
# ============================================================

def test_validator_passes_when_master_gives_watch_for_data_missing():
    master_out = {
        "mode": "silent_cooldown",
        "silent_reason": "L4 risk 数据全过期,空仓不开仓",
        "narrative": "L4 stale,关键层降级,silent",
        "execution_permission": "watch",
    }
    ctx = {
        "l1_output": _layer_healthy_output(1),
        "l2_output": _layer_healthy_output(2),
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_data_missing_output(4),
        "l5_output": _layer_healthy_output(5),
        "active_thesis": None,
    }
    out, act = validator_factor_grain(master_out, ctx)
    assert act["validator_factor_grain_violation"] is False


# ============================================================
# 3. 关键层 degraded + master 给 can_open → 拒绝
# ============================================================

def test_validator_rejects_can_open_when_key_layer_degraded():
    master_out = {
        "mode": "new_thesis",
        "new_thesis": {"execution_permission": "can_open"},
    }
    ctx = {
        "l1_output": _layer_healthy_output(1),
        "l2_output": _layer_degraded_output(2, ratio=0.6),
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_healthy_output(4),
        "l5_output": _layer_healthy_output(5),
        "active_thesis": None,
    }
    out, act = validator_factor_grain(master_out, ctx)
    assert act["validator_factor_grain_violation"] is True


def test_validator_passes_cautious_open_when_key_layer_degraded():
    master_out = {
        "mode": "new_thesis",
        "new_thesis": {"execution_permission": "cautious_open"},
    }
    ctx = {
        "l1_output": _layer_healthy_output(1),
        "l2_output": _layer_degraded_output(2, ratio=0.6),
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_healthy_output(4),
        "l5_output": _layer_healthy_output(5),
        "active_thesis": None,
    }
    out, act = validator_factor_grain(master_out, ctx)
    assert act["validator_factor_grain_violation"] is False


# ============================================================
# 4. L5 degraded(非关键层)→ 不强制
# ============================================================

def test_validator_passes_when_only_l5_degraded():
    master_out = {
        "mode": "new_thesis",
        "new_thesis": {"execution_permission": "can_open"},
    }
    ctx = {
        "l1_output": _layer_healthy_output(1),
        "l2_output": _layer_healthy_output(2),
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_healthy_output(4),
        "l5_output": _layer_data_missing_output(5),  # 非关键层 stale
        "active_thesis": None,
    }
    out, act = validator_factor_grain(master_out, ctx)
    assert act["validator_factor_grain_violation"] is False


# ============================================================
# 5. 全部 healthy → 不触发
# ============================================================

def test_validator_no_op_when_all_healthy():
    master_out = {
        "mode": "new_thesis",
        "new_thesis": {"execution_permission": "can_open"},
    }
    ctx = {
        "l1_output": _layer_healthy_output(1),
        "l2_output": _layer_healthy_output(2),
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_healthy_output(4),
        "l5_output": _layer_healthy_output(5),
    }
    out, act = validator_factor_grain(master_out, ctx)
    assert act["validator_factor_grain_violation"] is False


# ============================================================
# 6. 持仓时 + 关键层 data_missing + master evaluate_existing 不动仓位
#    → 通过(允许 evaluate_existing,不强制 silent_cooldown)
# ============================================================

def test_validator_allows_evaluate_existing_when_holding_with_data_missing():
    """持仓 + L1 data_missing + mode=evaluate_existing → V allows
    (因为不开新仓);但仍要求 execution_permission ≤ watch。"""
    master_out = {
        "mode": "evaluate_existing",
        "narrative": "L1 stale,保持现仓 hold_only",
        "execution_permission": "hold_only",
        "thesis_assessment": {"still_valid": "mostly"},
    }
    ctx = {
        "l1_output": _layer_data_missing_output(1),
        "l2_output": _layer_healthy_output(2),
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_healthy_output(4),
        "l5_output": _layer_healthy_output(5),
        "active_thesis": {"thesis_id": "th_test", "direction": "long"},
    }
    out, act = validator_factor_grain(master_out, ctx)
    assert act["validator_factor_grain_violation"] is False


# ============================================================
# 7. 集成测试:validate_master_output 全 pipeline 聚合 needs_retry
# ============================================================

def test_full_pipeline_aggregates_factor_grain_needs_retry():
    master_out = {
        "mode": "new_thesis",
        "narrative": "做多 70%",
        "new_thesis": {
            "direction": "long",
            "entry_orders": [{"price": 50000, "size_pct": 50}],
            "break_conditions": ["a", "b", "c"],
            "stop_loss": {"price": 45000},
            "execution_permission": "can_open",  # 违规
        },
    }
    ctx = {
        "l1_output": _layer_data_missing_output(1),  # 关键层 stale
        "l2_output": _layer_healthy_output(2),
        "l3_output": _layer_healthy_output(3),
        "l4_output": _layer_healthy_output(4),
        "l5_output": _layer_healthy_output(5),
        "l3_grade": "B",
    }
    _, activations = validate_master_output(master_out, ctx)
    assert activations["validator_factor_grain_violation"] is True
    assert activations["validator_needs_retry"] is True
    # retry hints 含 factor_grain 提示
    hints = " ".join(activations.get("validator_retry_hints") or [])
    assert "因子粒度保险" in hints


# ============================================================
# 8. validator 默认字段全持久化(周复盘 SQL 期望)
# ============================================================

def test_validator_default_activations_have_factor_grain_keys():
    from src.ai.validator import _DEFAULT_ACTIVATIONS_V24
    assert "validator_factor_grain_violation" in _DEFAULT_ACTIVATIONS_V24
    assert "validator_factor_grain_reason" in _DEFAULT_ACTIVATIONS_V24
    # _needs_retry 是临时聚合,不在持久化字段(已剥离到 validator_needs_retry 总开关)
    assert "validator_factor_grain_needs_retry" not in _DEFAULT_ACTIVATIONS_V24


# ============================================================
# 9. master prompt .txt 含 Step 4 整合规则
# ============================================================

def test_master_prompt_contains_step4_integration_rules():
    from pathlib import Path
    text = (
        Path(__file__).parent.parent
        / "src" / "ai" / "agents" / "prompts" / "master_adjudicator.txt"
    ).read_text(encoding="utf-8")
    assert "Sprint E" in text
    assert "因子粒度" in text or "_factor_grain" in text
    assert "data_missing" in text
    assert "关键层" in text
    assert "watch" in text or "cautious_open" in text
