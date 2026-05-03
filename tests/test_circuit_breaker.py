"""Sprint 1.10-F 单测:CircuitBreaker(v1.4 §6.3.1 + §6.4.2)。"""
from __future__ import annotations

import pytest

from src.ai.circuit_breaker import CircuitBreaker


# ============================================================
# get_downstream_to_short
# ============================================================

def test_l1_fail_shorts_l2_l3_master():
    assert CircuitBreaker.get_downstream_to_short("l1") == ["l2", "l3", "master"]


def test_l2_fail_shorts_l3_master():
    assert CircuitBreaker.get_downstream_to_short("l2") == ["l3", "master"]


def test_l3_fail_shorts_master_only():
    assert CircuitBreaker.get_downstream_to_short("l3") == ["master"]


def test_l4_fail_shorts_master_only():
    assert CircuitBreaker.get_downstream_to_short("l4") == ["master"]


def test_l5_fail_shorts_nothing():
    """L5 失败不短路 master(走 macro fallback)。"""
    assert CircuitBreaker.get_downstream_to_short("l5") == []


def test_master_fail_shorts_nothing():
    """master 失败无下游可短路。"""
    assert CircuitBreaker.get_downstream_to_short("master") == []


def test_invalid_layer_returns_empty():
    assert CircuitBreaker.get_downstream_to_short("invalid_layer") == []


# ============================================================
# should_master_run
# ============================================================

def test_no_failures_master_runs():
    ok, reason = CircuitBreaker.should_master_run([])
    assert ok
    assert "all_layers_success" in reason


def test_l5_fail_only_master_still_runs():
    """L5 单独失败 → master 仍跑 + macro fallback(§6.4.2)。"""
    ok, reason = CircuitBreaker.should_master_run(["l5"])
    assert ok
    assert "macro_fallback" in reason


def test_l1_fail_master_blocked():
    ok, reason = CircuitBreaker.should_master_run(["l1"])
    assert not ok
    assert "short_circuited" in reason
    assert "l1" in reason


def test_l2_fail_master_blocked():
    ok, reason = CircuitBreaker.should_master_run(["l2"])
    assert not ok
    assert "l2" in reason


def test_l3_fail_master_blocked():
    ok, _ = CircuitBreaker.should_master_run(["l3"])
    assert not ok


def test_l4_fail_master_blocked():
    ok, _ = CircuitBreaker.should_master_run(["l4"])
    assert not ok


def test_l5_plus_l3_blocked():
    """L3 + L5 同时失败 → master 不跑(L3 critical)。"""
    ok, reason = CircuitBreaker.should_master_run(["l3", "l5"])
    assert not ok
    assert "l3" in reason


def test_multiple_critical_failures_blocked():
    ok, reason = CircuitBreaker.should_master_run(["l1", "l4"])
    assert not ok
    # both should be in reason
    assert "l1" in reason and "l4" in reason


# ============================================================
# apply_macro_fallback(D4=a 硬编码)
# ============================================================

def test_macro_fallback_hardcoded_values():
    """v1.4 §6.4.2 + D4=a 硬编码 4 字段。"""
    m = CircuitBreaker.apply_macro_fallback()
    assert m["macro_stance"] == "risk_neutral"
    assert m["headwind_score"] == 0
    assert m["extreme_event_detected"] is False
    assert m["position_cap_macro_multiplier"] == 1.0
    assert m["status"] == "degraded_l5_failed_macro_fallback"


def test_macro_fallback_includes_narrative():
    """fallback 含 narrative + objective_evidence(供 master 引用)。"""
    m = CircuitBreaker.apply_macro_fallback()
    assert isinstance(m.get("narrative"), str) and len(m["narrative"]) > 0
    assert isinstance(m.get("objective_evidence"), list)
    assert len(m["objective_evidence"]) >= 1


def test_macro_fallback_returns_copy():
    """每次调用返回新 dict,避免共享 mutation。"""
    m1 = CircuitBreaker.apply_macro_fallback()
    m1["modified"] = True
    m2 = CircuitBreaker.apply_macro_fallback()
    assert "modified" not in m2
