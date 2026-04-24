"""
cold_start.py — Sprint 1.5c C3:统一的冷启动判定。

建模 §8.10:
  * 冷启动前 7 天(42 次运行)StrategyState 标记 cold_start: true
  * 观察分类器跳过 possibly_suppressed 持续性检查
  * KPI 不累计
  * Fallback 阈值宽松一档

本模块是冷启动判定的唯一事实源;observation_classifier 和 adjudicator 都 import
这个函数,避免两份重复检查漂移。
"""

from __future__ import annotations

from typing import Any


DEFAULT_COLD_START_RUNS: int = 42


def is_cold_start(
    strategy_state: dict[str, Any],
    *,
    threshold_runs: int = DEFAULT_COLD_START_RUNS,
) -> bool:
    """
    判断当前 strategy_state 是否处于冷启动期。

    口径(二选一即为 True,二者等价但写法不同):
      1. state['cold_start']['warming_up'] == True
      2. state['cold_start']['runs_completed'] < threshold_runs

    任一来源标 True 即视为冷启动(保守)。

    Args:
        strategy_state:   已填入 cold_start 块的 state dict
        threshold_runs:   冷启动运行阈值(默认 42,对应建模 §8.10 "前 7 天")

    Returns:
        True 表示冷启动期;建议不开仓、不累计 KPI、放宽 Fallback 阈值。
    """
    cs = strategy_state.get("cold_start") or {}
    if bool(cs.get("warming_up")) is True:
        return True
    runs = cs.get("runs_completed")
    if runs is None:
        return False
    try:
        return int(runs) < int(threshold_runs)
    except (TypeError, ValueError):
        return False
