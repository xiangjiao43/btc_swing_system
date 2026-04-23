"""
band_position.py — BandPosition 组合因子(建模 §3.8.2,v1.2 只用价格几何)

output(对齐 schemas.yaml band_position_output):
  phase: early / mid / late / exhausted / unclear / n_a
  phase_confidence: 0-1
  impulse_extension_ratio: float
  scoring_breakdown: dict(每个 phase 的累积分)
  + 运行时元信息:computation_method / health_status / notes
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from ..indicators.trend import ema
from ..indicators.structure import swing_points
from ._base import CompositeFactorBase, reduce_metadata


class BandPositionFactor(CompositeFactorBase):
    name = "band_position"
    thresholds_key = "band_position_scoring"

    def compute(self, context: dict[str, Any]) -> dict[str, Any]:
        klines: Optional[pd.DataFrame] = context.get("klines_1d")
        if klines is None or klines.empty or len(klines) < 60:
            return self._insufficient(
                "klines_1d missing or too short (need ≥60)",
                phase="unclear", phase_confidence=0.0,
                impulse_extension_ratio=0.0, scoring_breakdown={},
            )

        # ---- 核心度量 ----
        close = klines["close"]
        high = klines["high"]
        low = klines["low"]

        # 最近一轮 impulse 的扩展比率:
        # 以最近一个 swing low 为起点,最近 swing high 为终点;当前价格
        # 相对 (high - low) 的比例反映 impulse 是否已扩展。
        impulse_ratio = _impulse_extension_ratio(high, low, close)

        # MA-60 贴近度 / 偏离度
        ma60 = ema(close, 60)
        last_close = float(close.iloc[-1])
        ma60_last = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else last_close
        near_ma60 = abs(last_close - ma60_last) / ma60_last < 0.03
        far_above = (last_close > ma60_last * 1.10)

        # Swing 序列:近 30 根的 HH+HL 还是 LH+LL
        recent = klines.tail(30)
        events = swing_points(recent["high"], recent["low"], lookback=3)
        hh_hl = _has_hh_hl(events)
        lh_ll = _has_lh_or_ll(events)

        # 最近回撤相对 impulse 的比例
        retracement_ratio = _retracement_ratio(high, low, close)

        # ---- 按 yaml items 评分 ----
        phase_scores: dict[str, float] = {
            "early": 0.0, "mid": 0.0, "late": 0.0, "exhausted": 0.0,
        }
        items_cfg = self.scoring_config.get("items") or []

        def _add(name: str, phases: list[str] | str) -> float | None:
            """按 yaml 项 name 加对应 phases 的分;若 yaml 未定义,返回 None 不加。"""
            item = next((i for i in items_cfg if i.get("name") == name), None)
            if item is None:
                return None
            pts = float(item.get("points", 0))
            target = item.get("assigns_to_phase", phases)
            if isinstance(target, str):
                target = [target]
            for p in target:
                if p in phase_scores:
                    phase_scores[p] += pts
            return pts

        # Impulse extension 分 4 档
        if impulse_ratio < 0.50:
            _add("impulse_extension_early", "early")
        elif impulse_ratio < 1.00:
            _add("impulse_extension_mid", "mid")
        elif impulse_ratio < 1.38:
            _add("impulse_extension_late", "late")
        else:
            _add("impulse_extension_exhausted", "exhausted")

        # Swing 序列
        if hh_hl:
            _add("hh_hl_pronounced", ["early", "mid"])
        if lh_ll:
            _add("lh_or_ll_recent", ["late", "exhausted"])

        # 均线距离
        if near_ma60:
            _add("near_ma60", ["early", "mid"])
        if far_above:
            _add("far_above_ma60", ["late", "exhausted"])

        # 回撤深度
        if retracement_ratio > 0.5:
            _add("recent_retracement_deep", ["early"])
        if retracement_ratio < 0.2:
            _add("recent_retracement_shallow", ["late", "exhausted"])

        # ---- 决策 ----
        top_phase = max(phase_scores, key=phase_scores.get)
        top_score = phase_scores[top_phase]
        # 理论最大:impulse(3) + hh_hl(2) + near_ma60(1) + retracement(1) = 7 / 档
        theoretical_max = 7.0
        confidence = round(min(top_score / theoretical_max, 1.0), 4) if theoretical_max > 0 else 0.0

        # 若 top 分 = 0(无任何触发)或并列多档,返回 unclear
        sorted_scores = sorted(phase_scores.values(), reverse=True)
        if top_score == 0:
            phase = "unclear"
            confidence = 0.0
        elif len(sorted_scores) >= 2 and sorted_scores[0] == sorted_scores[1]:
            phase = "unclear"
            confidence = round(top_score / theoretical_max * 0.5, 4)
        else:
            phase = top_phase

        return {
            "factor": self.name,
            "phase": phase,
            "phase_confidence": confidence,
            "impulse_extension_ratio": round(impulse_ratio, 4),
            "scoring_breakdown": {k: round(v, 2) for k, v in phase_scores.items()},
            **reduce_metadata(),
            "diagnostics": {
                "near_ma60": near_ma60, "far_above_ma60": far_above,
                "hh_hl": hh_hl, "lh_ll": lh_ll,
                "retracement_ratio": round(retracement_ratio, 4),
            },
        }


# ============================================================
# 辅助
# ============================================================

def _impulse_extension_ratio(
    high: pd.Series, low: pd.Series, close: pd.Series
) -> float:
    """
    以近 60 根数据为窗口。取最近 swing low → swing high 作 impulse 起止;
    返回 (current_price - swing_low) / impulse_range。

    若数据不足或无 swing 对,返回 0.0(被 compute 映射成 early 档)。
    """
    if len(high) < 20:
        return 0.0
    window_h = high.tail(60)
    window_l = low.tail(60)
    events = swing_points(window_h, window_l, lookback=3)
    if len(events) < 2:
        return 0.0
    # 找最近一个 swing low 和它之后的第一个 swing high
    swing_low_price = None
    swing_high_price = None
    for ev in events:
        if ev["type"] == "low" and swing_low_price is None:
            swing_low_price = ev["price"]
        elif ev["type"] == "high" and swing_low_price is not None and swing_high_price is None:
            swing_high_price = ev["price"]
            break
    if swing_low_price is None or swing_high_price is None:
        return 0.0
    rng = swing_high_price - swing_low_price
    if rng <= 0:
        return 0.0
    current = float(close.iloc[-1])
    return (current - swing_low_price) / rng


def _has_hh_hl(events: list[dict]) -> bool:
    """近期最近两个 high 递增 且 最近两个 low 递增 → HH+HL。"""
    highs = [e for e in events if e["type"] == "high"]
    lows = [e for e in events if e["type"] == "low"]
    hh = len(highs) >= 2 and highs[-1]["price"] > highs[-2]["price"]
    hl = len(lows) >= 2 and lows[-1]["price"] > lows[-2]["price"]
    return hh and hl


def _has_lh_or_ll(events: list[dict]) -> bool:
    """最近两个 high 或 low 中至少一对形成 LH 或 LL。"""
    highs = [e for e in events if e["type"] == "high"]
    lows = [e for e in events if e["type"] == "low"]
    lh = len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"]
    ll = len(lows) >= 2 and lows[-1]["price"] < lows[-2]["price"]
    return lh or ll


def _retracement_ratio(high: pd.Series, low: pd.Series, close: pd.Series) -> float:
    """
    最近一个 impulse 的 retracement 深度 ÷ impulse 总长度。
    若数据不足返回 0.0。
    """
    if len(high) < 30:
        return 0.0
    events = swing_points(high.tail(60), low.tail(60), lookback=3)
    if len(events) < 3:
        return 0.0
    # 找最新的 high → 其后的最低 close
    last_high = None
    for ev in reversed(events):
        if ev["type"] == "high":
            last_high = ev
            break
    if last_high is None:
        return 0.0
    # 取 last_high 之前的最近 low 作为 impulse 起点
    before_high_lows = [
        e for e in events
        if e["type"] == "low" and e["index"] < last_high["index"]
    ]
    if not before_high_lows:
        return 0.0
    impulse_low = before_high_lows[-1]
    impulse_len = last_high["price"] - impulse_low["price"]
    if impulse_len <= 0:
        return 0.0
    # 从 last_high 之后的最低价
    idx_of_last_high = list(high.index).index(last_high["index"]) \
        if last_high["index"] in list(high.index) else None
    if idx_of_last_high is None:
        return 0.0
    tail_low = low.iloc[idx_of_last_high:].min()
    drawdown = last_high["price"] - float(tail_low)
    return drawdown / impulse_len
