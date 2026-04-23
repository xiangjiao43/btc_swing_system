"""
ichimoku.py — 一目均衡表(云图)

建模 §3.8.1 TruthTrend 的多 TF 方向一致性可以用 Ichimoku 趋势判断做补强。
"""

from __future__ import annotations

import pandas as pd


def ichimoku_cloud(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    shift: int = 26,
) -> dict[str, pd.Series]:
    """
    Ichimoku Kinko Hyo(一目均衡表)五条线。

    - tenkan(转换线):(HH_9 + LL_9) / 2
    - kijun(基准线):(HH_26 + LL_26) / 2
    - senkou_a(先行带 A):(tenkan + kijun) / 2,向前 shift 26
    - senkou_b(先行带 B):(HH_52 + LL_52) / 2,向前 shift 26
    - chikou(滞后线):close 向后 shift 26

    向前 shift = 把"当前时间的未来预测"写到未来 index(向前推进时间)。
    pandas 里 `.shift(-n)` = 把值向上移 n 行(index 不变,值对齐到更早行)。
    Ichimoku 的 senkou 是"当前计算值显示在未来位置",相当于 `.shift(n)` 正移。

    Returns:
        {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou"}
    """
    _validate_hlc(high, low, close)

    def _mid_channel(high_s: pd.Series, low_s: pd.Series, period: int) -> pd.Series:
        hh = high_s.rolling(window=period, min_periods=period).max()
        ll = low_s.rolling(window=period, min_periods=period).min()
        return (hh + ll) / 2.0

    tenkan = _mid_channel(high, low, tenkan_period)
    kijun = _mid_channel(high, low, kijun_period)
    senkou_a = ((tenkan + kijun) / 2.0).shift(shift)
    senkou_b = _mid_channel(high, low, senkou_b_period).shift(shift)
    chikou = close.shift(-shift)

    return {
        "tenkan":   tenkan,
        "kijun":    kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "chikou":   chikou,
    }


def _validate_hlc(high, low, close) -> None:
    for name, s in (("high", high), ("low", low), ("close", close)):
        if not isinstance(s, pd.Series):
            raise TypeError(f"{name} must be pd.Series, got {type(s).__name__}")
    if not (len(high) == len(low) == len(close)):
        raise ValueError(
            f"high/low/close length mismatch: {len(high)}/{len(low)}/{len(close)}"
        )
