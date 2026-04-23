"""
momentum.py — 动量类指标(RSI / Stochastic RSI)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .trend import _wilder_smooth


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI(Wilder 原版平滑)。
    公式:
        gain = positive deltas(负值归 0)
        loss = |negative deltas|(正值归 0)
        RS = Wilder(gain) / Wilder(loss)
        RSI = 100 - 100 / (1 + RS)
    """
    if not isinstance(close, pd.Series):
        raise TypeError(f"rsi expects pd.Series, got {type(close).__name__}")
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = _wilder_smooth(gain, period)
    avg_loss = _wilder_smooth(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
    rsi_val = 100.0 - 100.0 / (1.0 + rs)
    # 当 avg_loss 为 0 → RS 为 inf → RSI 为 100
    rsi_val = rsi_val.where(avg_loss != 0, 100.0)
    return rsi_val


def stoch_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    随机 RSI(Stochastic RSI)。
    公式:
        rsi_s = rsi(close, period)
        hh = rsi_s 在 period 内最大
        ll = rsi_s 在 period 内最小
        stoch_rsi = (rsi_s - ll) / (hh - ll)

    Returns:
        [0, 1] 归一化序列(常见表示)。
    """
    rsi_s = rsi(close, period)
    rolling_min = rsi_s.rolling(window=period, min_periods=period).min()
    rolling_max = rsi_s.rolling(window=period, min_periods=period).max()
    denom = rolling_max - rolling_min
    with np.errstate(divide="ignore", invalid="ignore"):
        sr = (rsi_s - rolling_min) / denom
    sr = sr.where(denom != 0, 0.0)
    return sr.clip(0.0, 1.0)
