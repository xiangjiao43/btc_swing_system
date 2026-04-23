"""
trend.py — 趋势类技术指标(EMA / ADX / MACD)

所有函数纯 pandas + numpy;输入 pd.Series(或 DataFrame),返回 pd.Series
或 dict[str, pd.Series]。长度与输入相同,早期值为 NaN。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """
    指数移动平均(Exponential Moving Average)。
    使用 pandas 内置 .ewm(span=period, adjust=False).mean()。

    Args:
        series: 输入时间序列(收盘价等)
        period: EMA 周期

    Returns:
        与输入等长的 pd.Series。
    """
    if not isinstance(series, pd.Series):
        raise TypeError(f"ema expects pd.Series, got {type(series).__name__}")
    if period <= 0:
        raise ValueError(f"period must be > 0, got {period}")
    return series.ewm(span=period, adjust=False).mean()


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """
    Wilder 平滑(用在 ADX / RSI / ATR):等价于 alpha = 1/period 的 EMA。
    """
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range = max(H-L, |H-C_prev|, |L-C_prev|)。"""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def plus_di(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """+DI(Directional Indicator 上升分量)。"""
    _validate_hlc(high, low, close)
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0),
        index=high.index,
    )
    tr = _true_range(high, low, close)
    smooth_plus_dm = _wilder_smooth(plus_dm, period)
    smooth_tr = _wilder_smooth(tr, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        di = 100.0 * smooth_plus_dm / smooth_tr
    return di


def minus_di(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """-DI(Directional Indicator 下降分量)。"""
    _validate_hlc(high, low, close)
    up = high.diff()
    down = -low.diff()
    minus_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0),
        index=high.index,
    )
    tr = _true_range(high, low, close)
    smooth_minus_dm = _wilder_smooth(minus_dm, period)
    smooth_tr = _wilder_smooth(tr, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        di = 100.0 * smooth_minus_dm / smooth_tr
    return di


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """
    平均趋向指数 ADX(Wilder 原版)。

    步骤:
      1) TR = max(H-L, |H-Cprev|, |L-Cprev|),Wilder 平滑
      2) +DM / -DM,Wilder 平滑
      3) +DI / -DI = 100 * smoothed / TR_smoothed
      4) DX = 100 * |+DI - -DI| / (+DI + -DI)
      5) ADX = DX 的 Wilder 平滑

    建模 §4.2.5:ADX 强趋势阈值 25,弱趋势阈值 20。
    """
    _validate_hlc(high, low, close)
    p_di = plus_di(high, low, close, period)
    m_di = minus_di(high, low, close, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = 100.0 * (p_di - m_di).abs() / (p_di + m_di)
    dx = dx.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return _wilder_smooth(dx, period)


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, pd.Series]:
    """
    MACD 指标。

    Returns:
        {"macd": <fast EMA - slow EMA>,
         "signal": <signal EMA of macd>,
         "hist": <macd - signal>}
    """
    if not isinstance(close, pd.Series):
        raise TypeError(f"macd expects pd.Series, got {type(close).__name__}")
    if not (fast < slow):
        raise ValueError(f"fast ({fast}) must be < slow ({slow})")
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "hist": hist}


# -------- 辅助 ------------------------------------------------------

def _validate_hlc(high: Any, low: Any, close: Any) -> None:
    for name, s in (("high", high), ("low", low), ("close", close)):
        if not isinstance(s, pd.Series):
            raise TypeError(f"{name} must be pd.Series, got {type(s).__name__}")
    if not (len(high) == len(low) == len(close)):
        raise ValueError(
            f"high/low/close length mismatch: {len(high)}/{len(low)}/{len(close)}"
        )
