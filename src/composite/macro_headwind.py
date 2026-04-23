"""
macro_headwind.py — MacroHeadwind 组合因子(建模 §3.8.5)

5 项评分(thresholds.yaml macro_headwind_scoring.items):
  dxy_strengthening (-2) / us10y_rising (-2) / vix_elevated (-2) /
  nasdaq_falling (-2) / nasdaq_rising (+2)
BTC-纳指 60 日相关性 > 0.7 时所有项 × 1.5(btc_nasdaq_correlation_amplify)。

output(对齐 schemas.yaml macro_headwind_output):
  score, band, position_cap_multiplier, correlation_amplified, items_triggered
  + driver_breakdown / data_completeness_pct / computation_method / health_status / notes
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from ._base import CompositeFactorBase, reduce_metadata


class MacroHeadwindFactor(CompositeFactorBase):
    name = "macro_headwind"
    thresholds_key = "macro_headwind_scoring"

    def compute(self, context: dict[str, Any]) -> dict[str, Any]:
        macro = context.get("macro") or {}
        l5_cfg = self.full_thresholds.get("layer_5_macro", {})

        # ---- 各指标 20/30d 变化提取 ----
        dxy_change_pct = _pct_change_n(macro.get("dxy"), 20)
        us10y_change_bp = _bp_change_n(macro.get("us10y"), 30)
        vix_latest = _last_value(macro.get("vix"))
        nasdaq_change_pct = _pct_change_n(macro.get("nasdaq"), 20)

        # data_completeness
        indicators_available = [x for x in (
            dxy_change_pct, us10y_change_bp, vix_latest, nasdaq_change_pct
        ) if x is not None]
        completeness = len(indicators_available) / 4.0

        # 全部缺失 → 降级
        if completeness == 0:
            return self._insufficient(
                "all macro indicators missing",
                score=0.0, band="unknown",
                position_cap_multiplier=1.0,
                correlation_amplified=False,
                items_triggered=[],
                data_completeness_pct=0.0,
                driver_breakdown={},
            )

        # ---- 阈值 ----
        dxy_th = float(l5_cfg.get("dxy_20d_change_threshold_pct", 0.02))
        us10y_th = float(l5_cfg.get("us10y_30d_change_bp_threshold", 30))
        vix_elevated = float(l5_cfg.get("vix_elevated", 25))
        corr_strong = float(
            l5_cfg.get("btc_nasdaq_correlation_strong", 0.7)
        )

        items_cfg = self.scoring_config.get("items") or []
        points_map = {i["name"]: float(i["points"]) for i in items_cfg if "name" in i}

        # ---- BTC-Nasdaq 相关性 ----
        btc_nasdaq_corr = _btc_nasdaq_corr(
            context.get("klines_1d"), macro.get("nasdaq"),
        )
        amplifier_cfg = self.scoring_config.get("btc_nasdaq_correlation_amplify", {})
        amp_threshold = float(amplifier_cfg.get("threshold", corr_strong))
        amp_multiplier = float(amplifier_cfg.get("multiplier", 1.5))
        correlation_amplified = (
            btc_nasdaq_corr is not None and btc_nasdaq_corr > amp_threshold
        )
        amp_factor = amp_multiplier if correlation_amplified else 1.0

        # ---- 评分 ----
        score = 0.0
        items_triggered: list[str] = []
        driver_breakdown: dict[str, Any] = {}

        def _trigger(name: str, drive: str = "") -> None:
            nonlocal score
            if name in points_map:
                pts = points_map[name] * amp_factor
                score += pts
                items_triggered.append(name)
                driver_breakdown[name] = {
                    "base_points": points_map[name],
                    "amplifier": amp_factor,
                    "effective_points": pts,
                    "driver": drive,
                }

        # DXY 走强(> +2%)
        if dxy_change_pct is not None and dxy_change_pct > dxy_th:
            _trigger("dxy_strengthening", f"dxy_20d={dxy_change_pct:.4f}")

        # US10Y 上行(> +30bp)
        if us10y_change_bp is not None and us10y_change_bp > us10y_th:
            _trigger("us10y_rising", f"us10y_30d_bp={us10y_change_bp:.2f}")

        # VIX > 25
        if vix_latest is not None and vix_latest > vix_elevated:
            _trigger("vix_elevated", f"vix={vix_latest:.2f}")

        # 纳指下跌 > 5%
        if nasdaq_change_pct is not None and nasdaq_change_pct < -0.05:
            _trigger("nasdaq_falling", f"nasdaq_20d={nasdaq_change_pct:.4f}")
        # 纳指上涨 > 5%(正分)
        if nasdaq_change_pct is not None and nasdaq_change_pct > 0.05:
            _trigger("nasdaq_rising", f"nasdaq_20d={nasdaq_change_pct:.4f}")

        # 夹断到 [-10, 10](schemas.yaml range)
        score = max(-10.0, min(10.0, score))

        # ---- 输出 band ----
        bands = self.scoring_config.get("output_bands", {})
        strong_th = float(bands.get("strong_headwind_at_or_below", -5))
        mild_th = float(bands.get("mild_headwind_at_or_below", -2))
        if score <= strong_th:
            band = "strong_headwind"
            cap_multiplier = 0.7
        elif score <= mild_th:
            band = "mild_headwind"
            cap_multiplier = 0.85
        else:
            band = "neutral_or_tailwind"
            cap_multiplier = 1.0

        # health_status
        if completeness < 1.0:
            health = "degraded"
        else:
            health = "healthy"

        return {
            "factor": self.name,
            "score": round(score, 2),
            "band": band,
            "position_cap_multiplier": cap_multiplier,
            "correlation_amplified": correlation_amplified,
            "items_triggered": items_triggered,
            "driver_breakdown": driver_breakdown,
            "data_completeness_pct": round(completeness * 100, 1),
            **reduce_metadata(health_status=health),
            "diagnostics": {
                "dxy_20d_change": dxy_change_pct,
                "us10y_30d_change_bp": us10y_change_bp,
                "vix_latest": vix_latest,
                "nasdaq_20d_change": nasdaq_change_pct,
                "btc_nasdaq_corr": btc_nasdaq_corr,
            },
        }


# ============================================================
# 辅助
# ============================================================

def _last_value(series: Optional[pd.Series]) -> Optional[float]:
    if series is None or not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


def _pct_change_n(series: Optional[pd.Series], n: int) -> Optional[float]:
    if series is None or not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    if len(clean) < n + 1:
        return None
    past = float(clean.iloc[-n - 1])
    current = float(clean.iloc[-1])
    if past == 0:
        return None
    return (current - past) / past


def _bp_change_n(series: Optional[pd.Series], n: int) -> Optional[float]:
    """
    利率指标单位是百分比(如 3.82 即 3.82%)。
    n 日变化单位为 basis point:1% = 100bp。
    """
    if series is None or not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    if len(clean) < n + 1:
        return None
    past = float(clean.iloc[-n - 1])
    current = float(clean.iloc[-1])
    return (current - past) * 100.0   # 1 个百分点 = 100 bp


def _btc_nasdaq_corr(
    klines_1d: Optional[pd.DataFrame],
    nasdaq_series: Optional[pd.Series],
    lookback: int = 60,
) -> Optional[float]:
    """
    BTC close 与 nasdaq close 的 lookback 日滚动相关性(取最新值)。
    需至少 lookback 天重叠。不足返回 None。
    """
    if klines_1d is None or klines_1d.empty:
        return None
    if nasdaq_series is None or not isinstance(nasdaq_series, pd.Series):
        return None
    btc_close = klines_1d["close"].dropna()
    nas = nasdaq_series.dropna()
    if len(btc_close) < lookback or len(nas) < lookback:
        return None
    # 用 pct_change 序列算相关性(价格水平相关性会被双双上涨伪装高)
    btc_ret = btc_close.pct_change().dropna()
    nas_ret = nas.pct_change().dropna()
    # 对齐索引
    joined = pd.concat([btc_ret, nas_ret], axis=1, join="inner").dropna()
    if len(joined) < lookback:
        return None
    recent = joined.tail(lookback)
    corr = recent.iloc[:, 0].corr(recent.iloc[:, 1])
    if pd.isna(corr):
        return None
    return float(corr)
