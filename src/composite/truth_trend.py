"""
truth_trend.py — TruthTrend 组合因子(建模 §3.8.1)

5 个评分项(按 thresholds.yaml truth_trend_scoring.items):
  1. adx_14_1d_strong       → +2  (1D ADX ≥ strong_threshold)
  2. adx_14_4h_weak_or_above → +1  (4H ADX ≥ weak_threshold)
  3. multi_tf_aligned        → +3  (4H/1D/1W 方向一致)
  4. ma_alignment            → +2  (MA-20/60/120 正确排列)
  5. price_vs_ma200          → +1  (价格与 MA-200 位置符合趋势)
理论最大 9 分;输出 band 按 output_bands 判。

output(对齐 schemas.yaml truth_trend_output + 运行时元信息):
  score, band, items_triggered, regime_switch_first_week, confidence,
  direction, computation_method, health_status, notes
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from ..indicators.trend import adx, ema
from ._base import (
    CompositeFactorBase,
    confidence_tier_from_value,
    reduce_metadata,
)


class TruthTrendFactor(CompositeFactorBase):
    name = "truth_trend"
    thresholds_key = "truth_trend_scoring"

    def compute(self, context: dict[str, Any]) -> dict[str, Any]:
        klines_1d: Optional[pd.DataFrame] = context.get("klines_1d")
        klines_4h: Optional[pd.DataFrame] = context.get("klines_4h")
        klines_1w: Optional[pd.DataFrame] = context.get("klines_1w")

        if klines_1d is None or klines_1d.empty or len(klines_1d) < 30:
            return self._insufficient(
                "klines_1d missing or too short (need ≥30)",
                score=0, band="no_trend", items_triggered=[],
                confidence=0.0, confidence_tier="very_low",
                direction="unknown",
            )

        strong_th = float(self._threshold(
            ["layer_1_regime", "adx", "strong_threshold"], 25.0
        ))
        weak_th = float(self._threshold(
            ["layer_1_regime", "adx", "weak_threshold"], 20.0
        ))

        # ---- 指标计算 ----
        adx_1d_series = adx(
            klines_1d["high"], klines_1d["low"], klines_1d["close"], period=14
        )
        adx_1d_latest = _last_valid(adx_1d_series)
        adx_4h_latest = None
        if klines_4h is not None and not klines_4h.empty and len(klines_4h) >= 30:
            adx_4h_series = adx(
                klines_4h["high"], klines_4h["low"], klines_4h["close"], period=14
            )
            adx_4h_latest = _last_valid(adx_4h_series)

        # MA 排列(SMA 简化用 EMA 效果接近;保持纯指标化)
        ma20 = _last_valid(ema(klines_1d["close"], 20))
        ma60 = _last_valid(ema(klines_1d["close"], 60))
        ma120 = _last_valid(ema(klines_1d["close"], 120))
        ma200 = _last_valid(ema(klines_1d["close"], 200))
        last_close = float(klines_1d["close"].iloc[-1])

        # 方向一致性:每 TF 取"最新 close 是否在 EMA-20 之上"作为方向代理
        dir_1d = _direction_simple(klines_1d)
        dir_4h = _direction_simple(klines_4h) if klines_4h is not None else None
        dir_1w = _direction_simple(klines_1w) if klines_1w is not None else None

        multi_tf_aligned = (
            dir_1d is not None and dir_4h is not None and dir_1w is not None
            and dir_1d == dir_4h == dir_1w and dir_1d != "flat"
        )

        # MA 排列方向
        ma_dir: Optional[str] = None
        if ma20 and ma60 and ma120:
            if ma20 > ma60 > ma120:
                ma_dir = "up"
            elif ma20 < ma60 < ma120:
                ma_dir = "down"

        # ---- 评分 ----
        items_triggered: list[str] = []
        score = 0.0
        items_cfg = self.scoring_config.get("items") or []
        # 用字典按 name 查点数;若 yaml 里没有某 item,其 handler 不会执行
        points_map = {i["name"]: float(i["points"]) for i in items_cfg if "name" in i}

        def _trigger(name: str) -> None:
            nonlocal score
            if name in points_map:
                score += points_map[name]
                items_triggered.append(name)

        # Item 1: adx_14_1d_strong
        if adx_1d_latest is not None and adx_1d_latest >= strong_th:
            _trigger("adx_14_1d_strong")

        # Item 2: adx_14_4h_weak_or_above
        if adx_4h_latest is not None and adx_4h_latest >= weak_th:
            _trigger("adx_14_4h_weak_or_above")

        # Item 3: multi_tf_aligned
        if multi_tf_aligned:
            _trigger("multi_tf_aligned")

        # Item 4: ma_alignment(需要 ma_dir 明确且与 multi_tf 方向对齐若可比)
        if ma_dir is not None:
            if dir_1d is None or ma_dir == dir_1d:
                _trigger("ma_alignment")

        # Item 5: price_vs_ma200(上方 + 上升趋势,或下方 + 下降趋势)
        if ma200 is not None:
            if (ma_dir == "up" and last_close > ma200) or (
                ma_dir == "down" and last_close < ma200
            ):
                _trigger("price_vs_ma200")

        # ---- 输出 band ----
        bands = self.scoring_config.get("output_bands", {})
        true_th = float(bands.get("true_trend_at_or_above", 6))
        weak_band_th = float(bands.get("weak_trend_at_or_above", 4))
        if score >= true_th:
            band = "true_trend"
        elif score >= weak_band_th:
            band = "weak_trend"
        else:
            band = "no_trend"

        # Direction 简化:MA 方向或多 TF 方向
        direction: str = ma_dir or dir_1d or "flat"

        # Confidence:score / 9(理论最大)
        confidence = round(score / 9.0, 4)

        return {
            "factor": self.name,
            "score": score,
            "band": band,
            "items_triggered": items_triggered,
            "regime_switch_first_week": False,   # Sprint 1.7+ 由状态机补充真值
            "confidence": confidence,
            "confidence_tier": confidence_tier_from_value(confidence),
            "direction": direction,
            **reduce_metadata(),
            # debug 辅助
            "diagnostics": {
                "adx_1d": None if adx_1d_latest is None else round(adx_1d_latest, 3),
                "adx_4h": None if adx_4h_latest is None else round(adx_4h_latest, 3),
                "ma20": ma20, "ma60": ma60, "ma120": ma120, "ma200": ma200,
                "ma_dir": ma_dir, "tf_dirs": [dir_4h, dir_1d, dir_1w],
                "strong_th": strong_th, "weak_th": weak_th,
            },
        }


# ============================================================
# 辅助
# ============================================================

def _last_valid(series: pd.Series) -> Optional[float]:
    """取 series 最后一个非 NaN 值。"""
    clean = series.dropna()
    if clean.empty:
        return None
    return float(clean.iloc[-1])


def _direction_simple(klines: Optional[pd.DataFrame]) -> Optional[str]:
    """
    简化方向判断:最新 close 相对 EMA-20 的位置。
    数据不足返回 None。
    """
    if klines is None or klines.empty or len(klines) < 20:
        return None
    close = klines["close"]
    ema20 = _last_valid(ema(close, 20))
    if ema20 is None:
        return None
    last = float(close.iloc[-1])
    if last > ema20 * 1.002:   # 0.2% 死区避免平头误判
        return "up"
    if last < ema20 * 0.998:
        return "down"
    return "flat"
