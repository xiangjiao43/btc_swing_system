"""src/ai/anti_pattern_signals.py — Sprint 1.9-A.3 v1.3 §3.3.3 反模式 5 类 bool。

L3 prompt 期望输入 `anti_pattern_signals` 5 类 bool:
  - is_extending_late_phase            — L2 phase ∈ {late, exhausted}
  - is_against_long_cycle              — stance vs cycle_position 反向
  - is_chasing_breakout_no_pullback    — 突破 nearest_resistance 后无回踩
  - is_failing_at_resistance           — 反复测试 resistance 失败
  - is_after_extreme_event_no_reset    — 极端事件后未充分整理

铁律对齐:
- v1.3 §3.3.3 显式定义"系统计算给 5 类 bool 给 L3 用"(类型 B)。
- 这 5 类是基于 L1 + L2 输出 + 价格 K 线的客观判断,不是给 AI 的"标签",
  AI 看到 bool 后还要综合判断 grade(铁律 3)。

调用时机:Orchestrator 在 L3 之前 / L2 之后调用本模块。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd


logger = logging.getLogger(__name__)


# ============================================================
# 5 个独立检测器
# ============================================================

def is_extending_late_phase(l2_output: dict[str, Any]) -> bool:
    """L2 phase ∈ {late, exhausted} → True。"""
    if not isinstance(l2_output, dict):
        return False
    phase = l2_output.get("phase")
    return phase in ("late", "exhausted")


def is_against_long_cycle(l2_output: dict[str, Any]) -> bool:
    """L2 stance 与 long_cycle_context.ai_assessment 反向 → True。

    判据:
      - stance=bullish + cycle 处于 distribution / late_bull / mid_bear /
        late_bear / early_bear → True
      - stance=bearish + cycle 处于 accumulation / early_bull / mid_bull → True
    """
    if not isinstance(l2_output, dict):
        return False
    stance = l2_output.get("stance")
    long_ctx = l2_output.get("long_cycle_context") or {}
    if not isinstance(long_ctx, dict):
        return False
    cycle_label = (long_ctx.get("rule_cycle_position")
                   or long_ctx.get("ai_alternative") or "")

    bearish_cycles = {
        "distribution", "late_bull", "early_bear",
        "mid_bear", "late_bear",
    }
    bullish_cycles = {"accumulation", "early_bull", "mid_bull"}

    if stance == "bullish" and cycle_label in bearish_cycles:
        return True
    if stance == "bearish" and cycle_label in bullish_cycles:
        return True
    return False


def is_chasing_breakout_no_pullback(
    l2_output: dict[str, Any], current_close: Optional[float],
) -> bool:
    """价格突破 nearest_resistance 后无回踩(突破 < 1% 内,且 stance=bullish)。

    判据(bullish 方向):
      - stance=bullish
      - current_close > nearest_resistance × 1.0
      - 突破幅度 < 1%(还没回踩 + 还很激进)
      - 且 phase ∈ {early, mid}(在突破方向追)
    bearish 镜像。
    """
    if not isinstance(l2_output, dict) or current_close is None:
        return False
    stance = l2_output.get("stance")
    phase = l2_output.get("phase")
    key_levels = l2_output.get("key_levels") or {}
    if not isinstance(key_levels, dict):
        return False
    if phase not in ("early", "mid"):
        return False

    if stance == "bullish":
        nr = key_levels.get("nearest_resistance")
        if nr is None or nr <= 0:
            return False
        try:
            ratio = (current_close - nr) / nr
            return 0 < ratio < 0.01
        except (TypeError, ValueError):
            return False
    if stance == "bearish":
        ns = key_levels.get("nearest_support")
        if ns is None or ns <= 0:
            return False
        try:
            ratio = (ns - current_close) / ns
            return 0 < ratio < 0.01
        except (TypeError, ValueError):
            return False
    return False


def is_failing_at_resistance(
    l2_output: dict[str, Any], current_close: Optional[float],
) -> bool:
    """价格在 nearest_resistance 反复测试失败(stance=bullish + 距阻力 < 0.5% 但未突破)。

    bearish 镜像(测试 nearest_support 失败,价格反弹未跌破)。
    """
    if not isinstance(l2_output, dict) or current_close is None:
        return False
    stance = l2_output.get("stance")
    key_levels = l2_output.get("key_levels") or {}
    if not isinstance(key_levels, dict):
        return False

    if stance == "bullish":
        nr = key_levels.get("nearest_resistance")
        if nr is None or nr <= 0:
            return False
        try:
            ratio = (nr - current_close) / nr
            # 价格在阻力下方 0-0.5% 区间(刚测试)→ True
            return 0 <= ratio < 0.005
        except (TypeError, ValueError):
            return False
    if stance == "bearish":
        ns = key_levels.get("nearest_support")
        if ns is None or ns <= 0:
            return False
        try:
            ratio = (current_close - ns) / ns
            return 0 <= ratio < 0.005
        except (TypeError, ValueError):
            return False
    return False


def is_after_extreme_event_no_reset(
    extreme_event_flags: dict[str, Any],
    klines_1d: Optional[pd.DataFrame] = None,
) -> bool:
    """极端事件激活中 + 价格未走出 reset 形态 → True。

    判据(简化):extreme_event_flags 中任一为 True → True。
    (理想:加 K 线 reset 形态判断;1.10 细化)
    """
    if not isinstance(extreme_event_flags, dict):
        return False
    return any(bool(v) for v in extreme_event_flags.values())


# ============================================================
# 主入口
# ============================================================

def compute_anti_pattern_signals(
    l1_output: dict[str, Any],
    l2_output: dict[str, Any],
    *,
    current_close: Optional[float] = None,
    extreme_event_flags: Optional[dict[str, Any]] = None,
    klines_1d: Optional[pd.DataFrame] = None,
) -> dict[str, bool]:
    """主入口:返回 L3 prompt 期望的 5 类 bool dict。

    Args:
        l1_output: L1 AI 已跑出的 dict
        l2_output: L2 AI 已跑出的 dict(必有 stance/phase/key_levels/long_cycle_context)
        current_close: 现价(L4 也用,通常在 context 里)
        extreme_event_flags: 5 类极端事件 bool dict(从 detect_extreme_events 取)
        klines_1d: 备用(本 sprint 不强制使用)
    Returns:
        dict[str, bool],5 个 key,顺序与 L3 prompt 一致。
    """
    return {
        "is_extending_late_phase":
            is_extending_late_phase(l2_output),
        "is_against_long_cycle":
            is_against_long_cycle(l2_output),
        "is_chasing_breakout_no_pullback":
            is_chasing_breakout_no_pullback(l2_output, current_close),
        "is_failing_at_resistance":
            is_failing_at_resistance(l2_output, current_close),
        "is_after_extreme_event_no_reset":
            is_after_extreme_event_no_reset(
                extreme_event_flags or {}, klines_1d,
            ),
    }
