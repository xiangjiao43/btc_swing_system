"""
tests/test_cold_start_util.py — Sprint 1.5c C3:is_cold_start 单测。

唯一事实源,observation_classifier 和 adjudicator 都依赖。
"""

from __future__ import annotations

from src.utils.cold_start import is_cold_start, DEFAULT_COLD_START_RUNS


def test_warming_up_flag_true_is_cold():
    assert is_cold_start({"cold_start": {"warming_up": True, "runs_completed": 50}})


def test_runs_completed_below_threshold_is_cold():
    assert is_cold_start({"cold_start": {"warming_up": False, "runs_completed": 5}})


def test_runs_completed_at_threshold_is_not_cold():
    assert not is_cold_start(
        {"cold_start": {"warming_up": False, "runs_completed": 42}},
    )


def test_runs_completed_above_threshold_is_not_cold():
    assert not is_cold_start(
        {"cold_start": {"warming_up": False, "runs_completed": 100}},
    )


def test_missing_cold_start_block_is_not_cold():
    assert not is_cold_start({})


def test_custom_threshold():
    assert is_cold_start(
        {"cold_start": {"warming_up": False, "runs_completed": 20}},
        threshold_runs=25,
    )


def test_default_constant_matches_modeling_42():
    assert DEFAULT_COLD_START_RUNS == 42
