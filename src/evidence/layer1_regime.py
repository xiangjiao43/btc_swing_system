"""
layer1_regime.py — L1 市场状态层(建模 §4.2)

输出 EvidenceReport 的核心字段:
  * regime ∈ {trend_up, trend_down, range_high, range_mid, range_low,
             transition_up, transition_down, chaos}(8 档,对齐 schemas.yaml)
  * volatility_regime ∈ {low, normal, elevated, extreme}(4 档)
  * swing_amplitude(最近一波 swing 幅度百分比)
  * swing_stability ∈ {more_higher_highs, more_lower_lows, mixed, insufficient}
  * transition_indicators(ADX 斜率 / 波动加速 / EMA20 斜率)

优先级(§4.2.3 末段):chaos > transition_* > trend_* > range_*

字段名兼容:schemas.yaml 用 `regime_primary` / `volatility_level`,用户
任务描述用 `regime` / `volatility_regime`;两套字段都在输出里(同值),
下游按需取。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..indicators.structure import swing_points
from ..indicators.trend import adx, ema
from ..indicators.volatility import atr, atr_percentile
from ._base import EvidenceLayerBase, confidence_tier_from_value


logger = logging.getLogger(__name__)


class Layer1Regime(EvidenceLayerBase):
    layer_id = 1
    layer_name = "regime"
    thresholds_key = "layer_1_regime"

    # 最少 K 线根数(不足则 insufficient_data)
    _MIN_1D_BARS: int = 100

    def _compute_specific(self, context: dict[str, Any]) -> dict[str, Any]:
        klines_1d: Optional[pd.DataFrame] = context.get("klines_1d")
        klines_1w: Optional[pd.DataFrame] = context.get("klines_1w")

        # ---- 数据完整度检查 ----
        if klines_1d is None or not isinstance(klines_1d, pd.DataFrame) \
                or len(klines_1d) < self._MIN_1D_BARS:
            return self._insufficient(
                f"klines_1d insufficient (need ≥{self._MIN_1D_BARS}, "
                f"got {0 if klines_1d is None else len(klines_1d)})",
                regime="unclear_insufficient",
                regime_primary="unclear_insufficient",
                volatility_regime="unknown",
                volatility_level="unknown",
                swing_amplitude=0.0,
                swing_stability="insufficient",
                transition_indicators={},
                diagnostics={},
                # Sprint 2.6-C:数据不足时也保持 schema 一致(下游不报 KeyError)
                adx_14_1d=None,
                atr_14_1d=None,
                atr_percentile_180d=None,
                tf_alignment={"aligned": False, "direction": "unknown",
                              "score": None},
            )

        # ---- 阈值读取 ----
        adx_strong = float(self._threshold(
            ["layer_1_regime", "adx", "strong_threshold"], 25.0
        ))
        adx_weak = float(self._threshold(
            ["layer_1_regime", "adx", "weak_threshold"], 20.0
        ))
        atr_lookback = int(self._threshold(
            ["layer_1_regime", "atr_lookback_days"], 180
        ))
        atr_low = float(self._threshold(
            ["layer_1_regime", "atr_percentile", "low"], 30.0
        ))
        atr_elevated = float(self._threshold(
            ["layer_1_regime", "atr_percentile", "elevated"], 60.0
        ))
        atr_extreme = float(self._threshold(
            ["layer_1_regime", "atr_percentile", "extreme"], 85.0
        ))
        swing_window = int(self._threshold(
            ["layer_1_regime", "swing_window"], 5
        ))

        # ---- 核心指标 ----
        high = klines_1d["high"]
        low = klines_1d["low"]
        close = klines_1d["close"]

        adx_series = adx(high, low, close, period=14)
        atr_series = atr(high, low, close, period=14)
        # 关键:对 ATR/close 比率求百分位(跨时间可比,避免价格水平自身
        # 影响 ATR 绝对值);与 data_catalog 的 atr_to_price_ratio 一致。
        atr_ratio_series = atr_series / close
        atr_pct_series = atr_percentile(atr_ratio_series, lookback=atr_lookback)

        adx_latest = _last_valid(adx_series)
        atr_pct_latest = _last_valid(atr_pct_series)
        atr_latest = _last_valid(atr_series)

        ema20_series = ema(close, 20)
        ema50_series = ema(close, 50)
        ema200_series = ema(close, 200)
        ema20 = _last_valid(ema20_series)
        ema50 = _last_valid(ema50_series)
        ema200 = _last_valid(ema200_series)
        last_close = float(close.iloc[-1])

        # EMA 斜率(近 10 根 EMA20)
        ema20_slope = _linreg_slope(ema20_series.tail(10))

        # ADX 斜率(近 10 根)
        adx_slope = _linreg_slope(adx_series.tail(10))

        # 波动加速(ATR 近 20 均值 / 近 60 均值)
        vol_acceleration = _vol_acceleration(atr_series)

        # ---- 周线 MACD 方向 ----
        weekly_macd_direction: Optional[str] = _weekly_macd_direction(klines_1w)

        # ---- Swing 分析 ----
        swing_events = swing_points(high, low, lookback=swing_window)
        swing_stability, hh, hl, lh, ll = _analyze_swing(swing_events)
        swing_amp_pct = _latest_swing_amplitude_pct(swing_events)

        # ---- 价格三分位(range 判定用)----
        price_partition = _price_partition(close.tail(100))

        # ---- Volatility regime 判定 ----
        volatility_regime = _volatility_regime(
            atr_pct_latest, atr_low, atr_elevated, atr_extreme
        )

        # ---- EMA 排列 ----
        ema_arrangement = _ema_arrangement(ema20, ema50, ema200)

        # ---- 各档判定(打分)----
        # chaos 硬前置:volatility_regime 必须 ∈ {elevated, extreme}。
        # 否则强趋势里 ADX 快速上升的 std 会误判为 oscillating → 误入 chaos。
        vol_is_elevated_plus = volatility_regime in ("extreme", "elevated")
        chaos_signals = {
            # atr_extreme = volatility_regime == "extreme"(真正极端)
            "atr_extreme": volatility_regime == "extreme",
            # adx_oscillating 仅当 ADX 均值偏低(< 25)时才有效:
            # 强趋势的 ADX 上升本身会有高 std,但均值高,不是真震荡
            "adx_oscillating": (
                _is_adx_oscillating(adx_series.tail(20))
                and (adx_latest is None or adx_latest < adx_strong)
            ),
            "no_swing_pattern": swing_stability == "mixed",
        }
        chaos_hits = sum(chaos_signals.values())

        # trend_up 硬前置 = ADX ≥ strong_threshold;再看其他 3 个支撑信号
        adx_is_strong = adx_latest is not None and adx_latest >= adx_strong
        trend_up_signals = {
            "adx_strong": adx_is_strong,
            "ema_up": ema_arrangement == "up",
            "weekly_macd_up": weekly_macd_direction == "up",
            "hh_hl": swing_stability == "more_higher_highs",
        }
        trend_up_hits = sum(trend_up_signals.values())

        trend_down_signals = {
            "adx_strong": adx_is_strong,
            "ema_down": ema_arrangement == "down",
            "weekly_macd_down": weekly_macd_direction == "down",
            "ll_lh": swing_stability == "more_lower_lows",
        }
        trend_down_hits = sum(trend_down_signals.values())

        # transition_up 硬前置:ADX 上升中 + 尚未达到 strong(否则已是 trend_up)
        adx_below_strong = adx_latest is not None and adx_latest < adx_strong
        transition_up_signals = {
            "adx_rising": adx_slope is not None and adx_slope > 0,
            "adx_below_strong": adx_below_strong,
            "adx_crossed_up": _adx_crossed(
                adx_series, threshold=adx_weak + 2.0, direction="up"
            ),
            "recent_green_majority": _recent_green_majority(klines_1d, n=5),
        }
        transition_up_hits = sum(transition_up_signals.values())

        transition_down_signals = {
            "adx_rising": adx_slope is not None and adx_slope > 0,
            "adx_below_strong": adx_below_strong,
            "adx_crossed_up": _adx_crossed(
                adx_series, threshold=adx_weak + 2.0, direction="up"
            ),
            "recent_red_majority": _recent_red_majority(klines_1d, n=5),
        }
        transition_down_hits = sum(transition_down_signals.values())

        # range:ADX 低 + |EMA20 slope| 小
        is_range = (
            adx_latest is not None and adx_latest < adx_weak
            and ema20_slope is not None and abs(ema20_slope) < last_close * 0.0005
        )

        # ---- 判档:chaos > transition > trend > range ----
        regime: str
        regime_confidence_raw: float
        decision_note = ""

        # 判档优先级(§4.2.3 末段 + 自主决策):
        #   chaos > trend_*(有硬 ADX 前置) > transition_*(ADX 未到 strong) > range_*
        # chaos 需要 ≥2 条件 AND volatility_regime ∈ {elevated, extreme}
        if chaos_hits >= 2 and vol_is_elevated_plus:
            regime = "chaos"
            regime_confidence_raw = 0.85 if chaos_hits == 3 else 0.55
            decision_note = f"chaos_hits={chaos_hits}/3 (vol={volatility_regime})"
        elif adx_is_strong and trend_up_hits >= 3:
            regime = "trend_up"
            regime_confidence_raw = 0.85 if trend_up_hits == 4 else 0.70
            decision_note = f"trend_up_hits={trend_up_hits}/4"
        elif adx_is_strong and trend_down_hits >= 3:
            regime = "trend_down"
            regime_confidence_raw = 0.85 if trend_down_hits == 4 else 0.70
            decision_note = f"trend_down_hits={trend_down_hits}/4"
        elif transition_up_hits >= 3:
            regime = "transition_up"
            regime_confidence_raw = 0.70 if transition_up_hits == 4 else 0.50
            decision_note = f"transition_up_hits={transition_up_hits}/4"
        elif transition_down_hits >= 3:
            regime = "transition_down"
            regime_confidence_raw = 0.70 if transition_down_hits == 4 else 0.50
            decision_note = f"transition_down_hits={transition_down_hits}/4"
        elif is_range:
            # 按价格三分位细分
            if price_partition == "upper":
                regime = "range_high"
            elif price_partition == "lower":
                regime = "range_low"
            else:
                regime = "range_mid"
            regime_confidence_raw = 0.60
            decision_note = f"range via partition={price_partition}"
        else:
            # 所有条件都不满足;弱趋势 2/4 → 倾向 transition_*
            if trend_up_hits == 2:
                regime = "transition_up"
                regime_confidence_raw = 0.40
                decision_note = "weak trend_up 2/4 → transition_up"
            elif trend_down_hits == 2:
                regime = "transition_down"
                regime_confidence_raw = 0.40
                decision_note = "weak trend_down 2/4 → transition_down"
            else:
                regime = "range_mid"
                regime_confidence_raw = 0.35
                decision_note = "fallback to range_mid(low confidence)"

        confidence_tier = confidence_tier_from_value(regime_confidence_raw)

        # ---- 输出 ----
        diagnostics = {
            "adx_latest": _round_or_none(adx_latest, 3),
            "adx_slope_10bar": _round_or_none(adx_slope, 5),
            "atr_latest": _round_or_none(atr_latest, 3),
            "atr_percentile_latest": _round_or_none(atr_pct_latest, 2),
            "ema20": _round_or_none(ema20, 2),
            "ema50": _round_or_none(ema50, 2),
            "ema200": _round_or_none(ema200, 2),
            "ema20_slope": _round_or_none(ema20_slope, 4),
            "ema_arrangement": ema_arrangement,
            "last_close": _round_or_none(last_close, 2),
            "weekly_macd_direction": weekly_macd_direction,
            "price_partition": price_partition,
            "swing_counts": {"HH": hh, "HL": hl, "LH": lh, "LL": ll},
            "scoring": {
                "chaos_hits": chaos_hits,
                "trend_up_hits": trend_up_hits,
                "trend_down_hits": trend_down_hits,
                "transition_up_hits": transition_up_hits,
                "transition_down_hits": transition_down_hits,
                "is_range": is_range,
            },
            "signals": {
                "chaos": chaos_signals,
                "trend_up": trend_up_signals,
                "trend_down": trend_down_signals,
                "transition_up": transition_up_signals,
                "transition_down": transition_down_signals,
            },
            "thresholds_used": {
                "adx_strong": adx_strong, "adx_weak": adx_weak,
                "atr_low": atr_low, "atr_elevated": atr_elevated, "atr_extreme": atr_extreme,
                "atr_lookback": atr_lookback, "swing_window": swing_window,
            },
        }

        transition_indicators = {
            "adx_slope": _round_or_none(adx_slope, 5),
            "adx_direction": _slope_to_direction(adx_slope),
            "volatility_acceleration": _round_or_none(vol_acceleration, 4),
            "ema20_slope": _round_or_none(ema20_slope, 4),
            "ema20_direction": _slope_to_direction(ema20_slope),
        }

        notes: list[str] = [decision_note]
        if klines_1w is None or klines_1w.empty or len(klines_1w) < 30:
            notes.append("klines_1w missing or short — weekly MACD may be None")

        return {
            # schemas.yaml 主字段
            "regime_primary": regime,
            "volatility_level": volatility_regime,
            # 用户任务描述字段(同值别名)
            "regime": regime,
            "volatility_regime": volatility_regime,
            "trend_direction": _regime_to_direction(regime),
            # 共同字段
            "swing_amplitude": _round_or_none(swing_amp_pct, 5) or 0.0,
            "swing_stability": swing_stability,
            "transition_indicators": transition_indicators,
            "truth_trend_score": None,  # 等 composite 层注入(现在 L1 不直接跑 composite)
            "regime_stability": _infer_regime_stability(
                regime, regime_confidence_raw, swing_stability
            ),
            "diagnostics": diagnostics,
            # Sprint 2.6-C:把 ADX / ATR / 多周期一致性提到顶层,
            # 让 factor_card_emitter 不再依赖已删的 _compute_adx_latest 函数。
            "adx_14_1d": _round_or_none(adx_latest, 2),
            "atr_14_1d": _round_or_none(atr_latest, 2),
            "atr_percentile_180d": _round_or_none(atr_pct_latest, 1),
            "tf_alignment": _build_tf_alignment(
                ema_arrangement, weekly_macd_direction
            ),
            "confidence_tier": confidence_tier,
            "health_status": "healthy",
            "computation_method": "rule_based",
            "notes": notes,
        }


# ============================================================
# 辅助函数
# ============================================================

def _last_valid(series: pd.Series) -> Optional[float]:
    clean = series.dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


def _round_or_none(v: Optional[float], n: int = 3) -> Optional[float]:
    return None if v is None else round(float(v), n)


def _linreg_slope(series: pd.Series) -> Optional[float]:
    """用线性回归求斜率。数据不足返回 None。"""
    if series is None:
        return None
    clean = series.dropna()
    if len(clean) < 3:
        return None
    x = np.arange(len(clean), dtype=float)
    y = clean.values.astype(float)
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def _vol_acceleration(atr_series: pd.Series) -> Optional[float]:
    """ATR 近 20 均值 / 近 60 均值。>1 表示波动加速。数据不足返回 None。"""
    clean = atr_series.dropna()
    if len(clean) < 60:
        return None
    recent20 = clean.tail(20).mean()
    recent60 = clean.tail(60).mean()
    if recent60 <= 0:
        return None
    return float(recent20 / recent60)


def _slope_to_direction(slope: Optional[float]) -> str:
    if slope is None:
        return "unknown"
    if slope > 0:
        return "rising"
    if slope < 0:
        return "falling"
    return "flat"


def _weekly_macd_direction(klines_1w: Optional[pd.DataFrame]) -> Optional[str]:
    """
    周线 MACD 方向判断:
      * MACD(=EMA12-EMA26)绝对值 > 长期中线(用 close 的 1%)的 0.5% → 有效信号
      * 正值 → up(长周期多头占优)
      * 负值 → down(长周期空头占优)
      * 接近 0 → neutral
    这样避免强趋势的小幅反弹让 macd>signal 误判为 up。
    数据不足返回 None。
    """
    if klines_1w is None or klines_1w.empty or len(klines_1w) < 30:
        return None
    close = klines_1w["close"]
    macd_line = ema(close, 12) - ema(close, 26)
    macd_v = _last_valid(macd_line)
    last_close = _last_valid(close)
    if macd_v is None or last_close is None or last_close <= 0:
        return None
    # 死区:绝对值小于 close 的 0.005(0.5%)视为中性
    deadzone = last_close * 0.005
    if macd_v > deadzone:
        return "up"
    if macd_v < -deadzone:
        return "down"
    return "neutral"


def _ema_arrangement(
    ema20: Optional[float],
    ema50: Optional[float],
    ema200: Optional[float],
) -> Optional[str]:
    """20 > 50 > 200 → up;20 < 50 < 200 → down;其他 → mixed;缺失 → None。"""
    if ema20 is None or ema50 is None or ema200 is None:
        return None
    if ema20 > ema50 > ema200:
        return "up"
    if ema20 < ema50 < ema200:
        return "down"
    return "mixed"


def _build_tf_alignment(
    ema_arrangement: Optional[str],
    weekly_macd_direction: Optional[str],
) -> dict[str, Any]:
    """Sprint 2.6-C:简化的多周期一致性结构,供 factor_card_emitter 用。

    - 4H/1D 用 ema_arrangement(up/down/mixed)
    - 1W 用 weekly_macd_direction(up/down/neutral)
    - 都 up → aligned up;都 down → aligned down;其它 → mixed
    """
    if ema_arrangement is None or weekly_macd_direction is None:
        return {"aligned": False, "direction": "unknown", "score": None}
    if ema_arrangement == "up" and weekly_macd_direction == "up":
        return {"aligned": True, "direction": "up", "score": 3}
    if ema_arrangement == "down" and weekly_macd_direction == "down":
        return {"aligned": True, "direction": "down", "score": 3}
    return {"aligned": False, "direction": "mixed", "score": 1}


def _analyze_swing(
    events: list[dict[str, Any]],
) -> tuple[str, int, int, int, int]:
    """
    分析 swing 稳定性。返回 (stability, HH, HL, LH, LL)。
    stability ∈ {more_higher_highs, more_lower_lows, mixed, insufficient}。
    """
    highs = [e for e in events if e["type"] == "high"]
    lows = [e for e in events if e["type"] == "low"]
    hh = sum(1 for i in range(1, len(highs)) if highs[i]["price"] > highs[i - 1]["price"])
    lh = (len(highs) - 1) - hh if len(highs) > 1 else 0
    hl = sum(1 for i in range(1, len(lows)) if lows[i]["price"] > lows[i - 1]["price"])
    ll = (len(lows) - 1) - hl if len(lows) > 1 else 0

    # 用最近 10 个 swing 事件作评估
    recent = events[-10:]
    if len(recent) < 4:
        return "insufficient", hh, hl, lh, ll

    if hh > lh and hl > ll:
        return "more_higher_highs", hh, hl, lh, ll
    if lh > hh and ll > hl:
        return "more_lower_lows", hh, hl, lh, ll
    return "mixed", hh, hl, lh, ll


def _latest_swing_amplitude_pct(events: list[dict[str, Any]]) -> float:
    """
    最近一波 swing 的幅度百分比 = |last_swing_price - prev_swing_price| / prev_swing_price。
    事件 < 2 个 → 0.0。
    """
    if len(events) < 2:
        return 0.0
    last = events[-1]
    prev = events[-2]
    prev_price = prev["price"]
    if prev_price <= 0:
        return 0.0
    return abs(last["price"] - prev_price) / prev_price


def _price_partition(close_tail: pd.Series) -> str:
    """根据价格在近 N 天范围里的位置划三等分。"""
    if close_tail.empty:
        return "middle"
    hi = float(close_tail.max())
    lo = float(close_tail.min())
    current = float(close_tail.iloc[-1])
    rng = hi - lo
    if rng <= 0:
        return "middle"
    pos = (current - lo) / rng  # 0-1
    if pos > 2 / 3:
        return "upper"
    if pos < 1 / 3:
        return "lower"
    return "middle"


def _volatility_regime(
    atr_pct: Optional[float],
    low_th: float, elevated_th: float, extreme_th: float,
) -> str:
    """
    thresholds.yaml:low=30, elevated=60, extreme=85。
    < low → low;[low, elevated) → normal;[elevated, extreme) → elevated;
    ≥ extreme → extreme。atr_pct 为 None → 'unknown'。
    """
    if atr_pct is None:
        return "unknown"
    if atr_pct < low_th:
        return "low"
    if atr_pct < elevated_th:
        return "normal"
    if atr_pct < extreme_th:
        return "elevated"
    return "extreme"


def _is_adx_oscillating(adx_tail: pd.Series, threshold: float = 5.0) -> bool:
    """ADX 波动(std > threshold)→ 无趋势/震荡。"""
    clean = adx_tail.dropna()
    if len(clean) < 10:
        return False
    return float(clean.std(ddof=0)) > threshold


def _adx_crossed(adx_series: pd.Series, threshold: float, direction: str) -> bool:
    """近 10 根中 ADX 是否上穿 / 下穿 threshold。"""
    clean = adx_series.dropna().tail(10)
    if len(clean) < 3:
        return False
    first = float(clean.iloc[0])
    last = float(clean.iloc[-1])
    if direction == "up":
        return first < threshold and last >= threshold
    if direction == "down":
        return first > threshold and last <= threshold
    return False


def _recent_green_majority(klines: pd.DataFrame, n: int = 5) -> bool:
    """近 n 根阳线占多数(close > open)。强制 Python bool,避免 np.bool_。"""
    tail = klines.tail(n)
    greens = int((tail["close"] > tail["open"]).sum())
    return bool(greens > n // 2)


def _recent_red_majority(klines: pd.DataFrame, n: int = 5) -> bool:
    tail = klines.tail(n)
    reds = int((tail["close"] < tail["open"]).sum())
    return bool(reds > n // 2)


def _regime_to_direction(regime: str) -> str:
    if regime in ("trend_up", "transition_up", "range_high"):
        return "up"
    if regime in ("trend_down", "transition_down", "range_low"):
        return "down"
    return "flat"


def _infer_regime_stability(
    regime: str, confidence: float, swing_stability: str
) -> str:
    """
    schemas.yaml regime_stability ∈ {stable, slightly_shifting, actively_shifting, unstable}。
    简化启发:
      * chaos → unstable
      * transition_* → actively_shifting
      * trend_* + high confidence → stable
      * trend_* + lower confidence → slightly_shifting
      * range_* → stable(若 swing_stability=mixed)或 slightly_shifting
    """
    if regime == "chaos":
        return "unstable"
    if regime.startswith("transition_"):
        return "actively_shifting"
    if regime.startswith("trend_"):
        return "stable" if confidence >= 0.70 else "slightly_shifting"
    # range_*
    if swing_stability == "mixed":
        return "slightly_shifting"
    return "stable"
