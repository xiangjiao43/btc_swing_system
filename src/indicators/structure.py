"""
structure.py — 价格结构类指标(Swing Highs / Lows / 振幅)

建模 §4.2.5:swing 识别窗口 = 5。
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd


SwingType = Literal["high", "low"]


def swing_points(
    high: pd.Series,
    low: pd.Series,
    lookback: int = 5,
) -> list[dict[str, Any]]:
    """
    检测 Swing High / Swing Low。

    定义(左右对称 lookback 窗口):
      Swing High at i iff high[i] == max(high[i-lookback : i+lookback+1])
      Swing Low  at i iff low[i]  == min(low[i-lookback : i+lookback+1])

    Args:
        high:      最高价序列
        low:       最低价序列
        lookback:  左右各 N 根 K 线(建模默认 5)

    Returns:
        list[{type: 'high'|'low', index, price}]
        index = 原 Series 的 index(timestamp 或 int 位置);price = 对应高/低价。
        事件按 index 升序排列。
    """
    if not isinstance(high, pd.Series) or not isinstance(low, pd.Series):
        raise TypeError("high / low must be pd.Series")
    if len(high) != len(low):
        raise ValueError(f"length mismatch: high={len(high)}, low={len(low)}")
    if lookback <= 0:
        raise ValueError(f"lookback must be > 0, got {lookback}")

    n = len(high)
    if n < 2 * lookback + 1:
        return []

    events: list[dict[str, Any]] = []
    # 从位置 lookback 扫到 n-lookback-1,保证两侧各有 lookback 根
    # 用数组式访问更快
    highs_arr = high.values
    lows_arr = low.values
    idx_arr = high.index

    for i in range(lookback, n - lookback):
        window_h = highs_arr[i - lookback : i + lookback + 1]
        window_l = lows_arr[i - lookback : i + lookback + 1]
        if highs_arr[i] == window_h.max() and (window_h == highs_arr[i]).sum() == 1:
            events.append({
                "type":  "high",
                "index": idx_arr[i],
                "price": float(highs_arr[i]),
            })
        if lows_arr[i] == window_l.min() and (window_l == lows_arr[i]).sum() == 1:
            events.append({
                "type":  "low",
                "index": idx_arr[i],
                "price": float(lows_arr[i]),
            })

    # 保序:按 index 升序
    events.sort(key=lambda e: e["index"])
    return events


def latest_swing_amplitude(
    high: pd.Series,
    low: pd.Series,
    lookback: int = 5,
) -> float:
    """
    最近一次 swing 的振幅(最近 swing high 与最近 swing low 的绝对差)。

    当最近一个 swing 是 high → 返回 high - 最近一个前面的 low(或反之)。
    如果数据不够产出至少一对 swing(< 2 个事件),返回 0.0。
    """
    events = swing_points(high, low, lookback)
    if len(events) < 2:
        return 0.0
    # 找最近的 high 和最近的 low
    last_high: dict[str, Any] | None = None
    last_low: dict[str, Any] | None = None
    for ev in reversed(events):
        if ev["type"] == "high" and last_high is None:
            last_high = ev
        elif ev["type"] == "low" and last_low is None:
            last_low = ev
        if last_high is not None and last_low is not None:
            break
    if last_high is None or last_low is None:
        return 0.0
    return float(abs(last_high["price"] - last_low["price"]))
