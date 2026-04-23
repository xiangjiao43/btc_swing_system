"""
volatility.py — 波动率类指标(ATR / ATR 分位 / 布林带)

建模 §4.2.5:ATR 分位 low=30 / elevated=60 / extreme=85(近 180 天)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .trend import _true_range, _wilder_smooth


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """
    Average True Range(Wilder 原版平滑)。
    """
    _validate_hlc(high, low, close)
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")
    tr = _true_range(high, low, close)
    return _wilder_smooth(tr, period)


def atr_percentile(
    atr_series: pd.Series, lookback: int = 180
) -> pd.Series:
    """
    ATR 在滚动窗口内的分位数(0-100)。
    第 i 行 = ATR[i] 在 [i-lookback+1, i] 区间内的百分位(0-100)。

    Args:
        atr_series: ATR 时间序列
        lookback: 滚动窗口长度(默认 180,建模 §4.2.5 推荐)

    Returns:
        pd.Series[0-100],早期(少于 lookback 个值)为 NaN。
    """
    if not isinstance(atr_series, pd.Series):
        raise TypeError("atr_percentile expects pd.Series")
    if lookback <= 1:
        raise ValueError(f"lookback must be > 1, got {lookback}")

    def _pct(arr: np.ndarray) -> float:
        # arr[-1] = 当前值;计算它在 arr 中的分位(包含自己,排名法)
        current = arr[-1]
        if np.isnan(current):
            return np.nan
        valid = arr[~np.isnan(arr)]
        if len(valid) == 0:
            return np.nan
        rank = (valid < current).sum() + (valid == current).sum() / 2.0
        return 100.0 * rank / len(valid)

    return atr_series.rolling(window=lookback, min_periods=lookback).apply(
        _pct, raw=True
    )


def bollinger_bands(
    close: pd.Series, period: int = 20, std_dev: float = 2.0
) -> dict[str, pd.Series]:
    """
    布林带。

    Returns:
        {"upper": middle + k·std,
         "middle": SMA(close, period),
         "lower": middle - k·std}
    """
    if not isinstance(close, pd.Series):
        raise TypeError(f"bollinger_bands expects pd.Series, got {type(close).__name__}")
    if period <= 1:
        raise ValueError(f"period must be > 1, got {period}")

    middle = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    return {
        "upper":  middle + std_dev * std,
        "middle": middle,
        "lower":  middle - std_dev * std,
    }


# -------- 私有辅助 -----------------------------------------------------

def _validate_hlc(high, low, close) -> None:
    for name, s in (("high", high), ("low", low), ("close", close)):
        if not isinstance(s, pd.Series):
            raise TypeError(f"{name} must be pd.Series, got {type(s).__name__}")
    if not (len(high) == len(low) == len(close)):
        raise ValueError(
            f"high/low/close length mismatch: {len(high)}/{len(low)}/{len(close)}"
        )
