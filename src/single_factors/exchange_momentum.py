"""exchange_momentum.py — Sprint 2.6-M C2:ExchangeMomentum 单因子。

modeling §3.7.x 列了 "Exchange Net Flow 7 日均" → ExchangeMomentum,§3.8 把
ExchangeMomentum **从 composite 降级**为 L2 内部 stance_confidence 修正项。

L2(layer2_direction.py:207)期望读 `context["single_factors"]
["exchange_momentum_score"]`,但 single_factors 字典从未被任何模块写入,
导致 cold_notes 永远是 "exchange_momentum not provided in context, skipped"
(modeling §4.3 设计的修正项被永久 skip)。

本模块产出符号约定:
- 正值 = bullish(BTC 流出交易所 = 累积/惜售),范围 [+0, +1]
- 负值 = bearish(BTC 流入交易所 = 卖压),范围 [-1, +0]
- 与 L2 expects:em_score < 0 + candidate=bullish → "exchange_momentum_divergence"

normalization:
  raw = mean(last 7 days exchange_net_flow)
  scale = max(|exchange_net_flow|) over last 180 days
  em_score = -raw / scale,clamp 到 [-1, +1]
  (取负:net_flow 正 = 流入 = 卖压 = bearish → em_score 负;反之亦然)

数据不足(< 7 天)→ None(L2 走 skip 路径,不报错)。
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def compute_exchange_momentum_score(
    onchain: dict[str, Any],
    *,
    short_window: int = 7,
    norm_lookback: int = 180,
) -> Optional[float]:
    """Returns em_score ∈ [-1, +1] 或 None(数据不足)。

    取符号约定:正 = bullish(BTC 流出),负 = bearish(BTC 流入)。
    """
    if not isinstance(onchain, dict):
        return None
    series = onchain.get("exchange_net_flow")
    if not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    if len(clean) < short_window:
        return None

    raw_short = float(clean.tail(short_window).mean())
    if raw_short == 0:
        return 0.0

    # 用过去 norm_lookback 天的绝对值最大作分母,避免极端值压制小信号
    scale_window = clean.tail(norm_lookback)
    scale = float(scale_window.abs().max()) if not scale_window.empty else 0.0
    if scale <= 0:
        return 0.0

    em = -raw_short / scale  # 取负:flow IN(正)→ score 负 = bearish
    if em > 1.0:
        em = 1.0
    elif em < -1.0:
        em = -1.0
    return round(em, 4)
