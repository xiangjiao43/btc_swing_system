"""
layer5_macro.py — L5 宏观层(建模 §4.6)

输出:
  * macro_environment ∈ {risk_on, risk_off, neutral, unclear}
  * macro_headwind_vs_btc ∈ {strong_headwind, mild_headwind, neutral,
                              tailwind, independent, unknown}
  * dxy_trend / yields_trend / vix_regime / btc_nasdaq_correlation
  * data_completeness_pct(因 Yahoo 限速,部分 metric 常缺)
  * metrics_available / metrics_missing

降级策略:
  * 任何 metric 缺失 → 对应字段为 None,**不抛错**
  * 全部缺失 → macro_environment='unclear', health='insufficient_data'
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..indicators.trend import ema
from ._base import EvidenceLayerBase, confidence_tier_from_value


logger = logging.getLogger(__name__)


# 完整 metric 清单(全部可能出现的 macro fields)
_ALL_MACRO_METRICS: list[str] = [
    "dxy", "us10y", "vix", "sp500", "nasdaq", "gold_price",  # Yahoo
    "dgs10", "dff", "cpi", "unemployment_rate",              # FRED
]


# ============================================================
# Layer5Macro
# ============================================================

class Layer5Macro(EvidenceLayerBase):
    layer_id = 5
    layer_name = "macro"
    thresholds_key = "layer_5_macro"

    def _compute_specific(self, context: dict[str, Any]) -> dict[str, Any]:
        macro: dict[str, Any] = context.get("macro") or {}
        klines_1d = context.get("klines_1d")

        # ---- 可用性统计 ----
        available: list[str] = []
        missing: list[str] = []
        for m in _ALL_MACRO_METRICS:
            s = macro.get(m)
            if isinstance(s, pd.Series) and not s.dropna().empty:
                available.append(m)
            else:
                missing.append(m)

        completeness = round(100.0 * len(available) / len(_ALL_MACRO_METRICS), 1)

        # 全部缺 → unclear
        if not available:
            return self._insufficient(
                "no macro data available",
                macro_environment="unclear",
                macro_headwind_vs_btc="unknown",
                dxy_trend=None, yields_trend=None,
                vix_regime=None, btc_nasdaq_correlation=None,
                data_completeness_pct=0.0,
                metrics_available=[], metrics_missing=list(_ALL_MACRO_METRICS),
                diagnostics={"reason": "macro dict empty or all series empty"},
            )

        # ---- 子项计算 ----
        dxy_trend = _compute_trend(macro.get("dxy"), name="dxy")
        # US10Y 优先用 Yahoo us10y,FRED dgs10 备用
        yields_series = macro.get("us10y") \
            if isinstance(macro.get("us10y"), pd.Series) else macro.get("dgs10")
        yields_trend = _compute_trend(yields_series, name="us10y")

        vix_regime = _compute_vix_regime(macro.get("vix"))

        btc_nasdaq_corr = _compute_btc_nasdaq_correlation(
            klines_1d, macro.get("nasdaq"),
        )

        # ---- 综合判定 ----
        macro_environment = _derive_macro_environment(
            dxy_trend, yields_trend, vix_regime,
            stock_trend=_compute_trend(macro.get("nasdaq"), name="nasdaq"),
        )
        headwind = _derive_headwind_vs_btc(
            macro_environment, btc_nasdaq_corr,
        )

        # ---- 诊断 / 置信度 ----
        # 置信度基于完整度:100% → high;>=50% → medium;>=25% → low;<25% → very_low
        if completeness >= 80:
            conf_value = 0.80
        elif completeness >= 50:
            conf_value = 0.60
        elif completeness >= 25:
            conf_value = 0.40
        else:
            conf_value = 0.20
        confidence_tier = confidence_tier_from_value(conf_value)

        health = "healthy" if completeness >= 50 else "degraded"

        notes: list[str] = []
        if missing:
            notes.append(f"macro metrics missing: {missing}")
        if macro_environment == "unclear":
            notes.append("macro_environment unclear (mixed/insufficient signals)")
        if btc_nasdaq_corr is None:
            notes.append("btc-nasdaq correlation unavailable (need both 30+ days)")

        diagnostics = {
            "data_completeness_pct": completeness,
            "metrics_available": available,
            "metrics_missing": missing,
            "trend_details": {
                "dxy": dxy_trend,
                "yields": yields_trend,
            },
            "vix_details": vix_regime,
            "correlation_details": btc_nasdaq_corr,
            "confidence_raw": conf_value,
        }

        return {
            "macro_environment": macro_environment,
            "macro_headwind_vs_btc": headwind,
            "dxy_trend": dxy_trend,
            "yields_trend": yields_trend,
            "vix_regime": vix_regime,
            "btc_nasdaq_correlation": btc_nasdaq_corr,
            "data_completeness_pct": completeness,
            "metrics_available": available,
            "metrics_missing": missing,
            "diagnostics": diagnostics,
            "notes": notes,
            "health_status": health,
            "confidence_tier": confidence_tier,
            "computation_method": "rule_based",
        }


# ============================================================
# 辅助:trend 计算
# ============================================================

def _compute_trend(
    series: Optional[pd.Series], name: str = "",
) -> Optional[dict[str, Any]]:
    """
    返回 {direction, magnitude_30d_pct, ema_alignment}。
    数据不足返回 None。
    """
    if series is None or not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    if len(clean) < 60:
        return None

    latest = float(clean.iloc[-1])
    if latest <= 0:
        return None

    # 30 日涨跌幅
    if len(clean) >= 31:
        past = float(clean.iloc[-31])
        if past > 0:
            mag_30d = (latest - past) / past
        else:
            mag_30d = 0.0
    else:
        mag_30d = 0.0

    # 方向分档
    if mag_30d > 0.03:
        direction = "strong_rising"
    elif mag_30d > 0.01:
        direction = "rising"
    elif mag_30d < -0.03:
        direction = "strong_falling"
    elif mag_30d < -0.01:
        direction = "falling"
    else:
        direction = "neutral"

    # EMA 排列
    ema20 = _last_valid(ema(clean, 20))
    ema50 = _last_valid(ema(clean, 50))
    ema200 = _last_valid(ema(clean, 200)) if len(clean) >= 200 else None

    alignment: str
    if ema20 is None or ema50 is None:
        alignment = "unknown"
    elif ema200 is not None:
        if ema20 > ema50 > ema200:
            alignment = "up"
        elif ema20 < ema50 < ema200:
            alignment = "down"
        else:
            alignment = "mixed"
    else:
        # 200 不够,用 20/50
        if ema20 > ema50:
            alignment = "up"
        elif ema20 < ema50:
            alignment = "down"
        else:
            alignment = "flat"

    return {
        "direction": direction,
        "magnitude_30d_pct": round(mag_30d, 5),
        "ema_alignment": alignment,
    }


# ============================================================
# VIX regime
# ============================================================

def _compute_vix_regime(
    vix_series: Optional[pd.Series],
) -> Optional[dict[str, Any]]:
    """返回 {level, latest_value, recent_change_pct}。"""
    if vix_series is None or not isinstance(vix_series, pd.Series):
        return None
    clean = vix_series.dropna()
    if len(clean) < 8:
        return None

    latest = float(clean.iloc[-1])

    if latest < 15:
        level = "low_fear"
    elif latest < 20:
        level = "normal"
    elif latest < 30:
        level = "elevated"
    else:
        level = "extreme_fear"

    # 7 日变化
    if len(clean) >= 8:
        past = float(clean.iloc[-8])
        change_pct = (latest - past) / past if past > 0 else 0.0
    else:
        change_pct = 0.0

    spike = bool(change_pct > 0.20)

    return {
        "level": level,
        "latest_value": round(latest, 3),
        "recent_change_pct": round(change_pct, 4),
        "is_spike": spike,
    }


# ============================================================
# BTC-Nasdaq 相关性
# ============================================================

def _compute_btc_nasdaq_correlation(
    klines_1d: Optional[pd.DataFrame],
    nasdaq_series: Optional[pd.Series],
    lookback_days: int = 30,
) -> Optional[dict[str, Any]]:
    """
    30 日相关性。两者都 >= 30 天数据才算。
    用 pandas.corr(Pearson),对齐日期后的 pct_change。
    """
    if klines_1d is None or not isinstance(klines_1d, pd.DataFrame):
        return None
    if nasdaq_series is None or not isinstance(nasdaq_series, pd.Series):
        return None

    btc_close = klines_1d["close"].dropna()
    nas = nasdaq_series.dropna()
    if len(btc_close) < lookback_days + 1 or len(nas) < lookback_days + 1:
        return None

    # 用收益率(pct_change)计算相关性
    btc_ret = btc_close.pct_change().dropna()
    nas_ret = nas.pct_change().dropna()
    joined = pd.concat([btc_ret, nas_ret], axis=1, join="inner").dropna()
    if len(joined) < lookback_days:
        return None

    recent = joined.tail(lookback_days)
    try:
        corr = float(recent.iloc[:, 0].corr(recent.iloc[:, 1]))
    except Exception as e:
        logger.warning("btc-nasdaq corr failed: %s", e)
        return None
    if pd.isna(corr):
        return None

    if corr > 0.7:
        strength = "strongly_correlated"
    elif corr > 0.4:
        strength = "moderately_correlated"
    elif corr > -0.4:
        strength = "uncorrelated"
    elif corr > -0.7:
        strength = "moderately_inverse"
    else:
        strength = "inversely_correlated"

    return {
        "coefficient": round(corr, 4),
        "strength_label": strength,
        "lookback_days": lookback_days,
        "n_samples": len(recent),
    }


# ============================================================
# 综合判定
# ============================================================

def _derive_macro_environment(
    dxy_trend: Optional[dict],
    yields_trend: Optional[dict],
    vix_regime: Optional[dict],
    stock_trend: Optional[dict],
) -> str:
    """
    综合判定 macro_environment。信号收集:
      * dxy 走强 → +1 risk_off
      * dxy 走弱 → +1 risk_on
      * yields 急升 → +1 risk_off
      * VIX elevated/extreme_fear → +1 risk_off
      * VIX low_fear → +1 risk_on
      * 股指上涨 → +1 risk_on
      * 股指下跌 → +1 risk_off

    净分:> +1 → risk_on,< -1 → risk_off,[-1, 1] → neutral。
    全部 None → unclear。
    """
    score = 0
    signals_used = 0

    if dxy_trend:
        signals_used += 1
        d = dxy_trend["direction"]
        if d in ("rising", "strong_rising"):
            score -= 1
        elif d in ("falling", "strong_falling"):
            score += 1

    if yields_trend:
        signals_used += 1
        d = yields_trend["direction"]
        if d in ("rising", "strong_rising"):
            score -= 1
        elif d in ("falling", "strong_falling"):
            score += 0  # yields 下降不直接 risk_on(可能衰退预期)

    if vix_regime:
        signals_used += 1
        lv = vix_regime["level"]
        if lv in ("elevated", "extreme_fear"):
            score -= 1
        elif lv == "low_fear":
            score += 1

    if stock_trend:
        signals_used += 1
        d = stock_trend["direction"]
        if d in ("rising", "strong_rising"):
            score += 1
        elif d in ("falling", "strong_falling"):
            score -= 1

    if signals_used == 0:
        return "unclear"

    if score >= 2:
        return "risk_on"
    if score <= -2:
        return "risk_off"
    return "neutral"


def _derive_headwind_vs_btc(
    macro_env: str,
    btc_nasdaq_corr: Optional[dict],
) -> str:
    """
    * risk_off + 强相关 → strong_headwind
    * risk_off + 中等相关 → mild_headwind
    * risk_on + 强相关 → tailwind
    * uncorrelated / inversely_correlated → independent
    * unclear env → unknown
    * 其他 → neutral
    """
    if macro_env == "unclear":
        return "unknown"

    if btc_nasdaq_corr is None:
        # 没有相关性数据,但宏观环境已知 → 只能给"环境提示"
        if macro_env == "risk_off":
            return "mild_headwind"
        if macro_env == "risk_on":
            return "tailwind"
        return "neutral"

    strength = btc_nasdaq_corr.get("strength_label")

    if strength in ("uncorrelated", "moderately_inverse", "inversely_correlated"):
        return "independent"

    if macro_env == "risk_off":
        if strength == "strongly_correlated":
            return "strong_headwind"
        if strength == "moderately_correlated":
            return "mild_headwind"
        return "neutral"

    if macro_env == "risk_on":
        if strength == "strongly_correlated":
            return "tailwind"
        if strength == "moderately_correlated":
            return "mild_tailwind"
        return "neutral"

    return "neutral"


# ============================================================
# 通用小工具
# ============================================================

def _last_valid(series: pd.Series) -> Optional[float]:
    clean = series.dropna()
    return float(clean.iloc[-1]) if not clean.empty else None
