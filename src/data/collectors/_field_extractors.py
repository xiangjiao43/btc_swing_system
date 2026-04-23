"""
_field_extractors.py — CoinGlass 响应字段名的优先级清单 + 统一提取工具

这些优先级清单来自**旧系统 `utils_common.py` 验证过的契约**(2026-04-23)。
不要随意改动顺序或增删字段 —— 顺序反映了"实际遇到过的字段命名变体出现频率"。

如果新端点遇到未覆盖的字段名,在日志里会看到
"Skipping row without numeric value: keys=[...]",把那行 keys 列表追加到对应
清单末尾即可(保持旧的优先级不变)。
"""

from __future__ import annotations

from typing import Any, Optional


# ============================================================
# 资金费率(/funding-rate/history)
# 响应是 OHLC 形式;close 即为该时段末资金费率
# ============================================================
FUNDING_RATE_VALUE_KEYS: list[str] = [
    "close", "c",
    "fundingRate", "funding_rate",
    "rate", "value",
]


# ============================================================
# 聚合持仓量(/open-interest/aggregated-history)
# 响应也是 OHLC 形式;close 即为该时段末 OI
# ============================================================
OPEN_INTEREST_VALUE_KEYS: list[str] = [
    "close", "c",
    "openInterest", "open_interest",
    "sumOpenInterest", "oi",
    "value",
]


# ============================================================
# 全局账户多空比(/global-long-short-account-ratio/history)
# 主路径:直接取比值;若无,再用 long_pct / short_pct 计算
# ============================================================
LONG_SHORT_RATIO_VALUE_KEYS: list[str] = [
    "global_account_long_short_ratio",
    "globalLongShortAccountRatio",
    "global_account_longShort_ratio",
    "global_account_long_shortRatio",
    "longShortRatio",
    "longShortRadio",               # 旧 API 的拼写错误(Radio vs Ratio),兼容保留
    "longShortAccountRatio",
    "ratio",
    "value",
    "close",
]

LONG_SHORT_RATIO_LONG_PCT_KEYS: list[str] = [
    "global_account_long_percent",
    "globalLongPercent",
    "long_percent",
    "longPercent",
    "longAccount",
]

LONG_SHORT_RATIO_SHORT_PCT_KEYS: list[str] = [
    "global_account_short_percent",
    "globalShortPercent",
    "short_percent",
    "shortPercent",
    "shortAccount",
]


# ============================================================
# 清算(/liquidation/history)—— 分 long / short 两侧
# ============================================================
LIQUIDATION_LONG_KEYS: list[str] = [
    "longLiquidationUsd", "long_liquidation_usd",
    "longLiquidation", "long_liquidation",
    "longs", "long",
    "buy",
    "longVol", "long_volume_usd",
]

LIQUIDATION_SHORT_KEYS: list[str] = [
    "shortLiquidationUsd", "short_liquidation_usd",
    "shortLiquidation", "short_liquidation",
    "shorts", "short",
    "sell",
    "shortVol", "short_volume_usd",
]


# ============================================================
# 净持仓变化(/net-position/history)—— 分 long / short 两侧
# ============================================================
NET_POSITION_LONG_KEYS: list[str] = [
    "net_long_change", "netLongChange",
    "longChange", "long_change",
    "long",
    "net_long_position", "netLongPosition",
]

NET_POSITION_SHORT_KEYS: list[str] = [
    "net_short_change", "netShortChange",
    "shortChange", "short_change",
    "short",
    "net_short_position", "netShortPosition",
]


# ============================================================
# 时间戳字段(所有 CoinGlass 端点共用)
# ============================================================
TIMESTAMP_KEYS: list[str] = ["t", "time", "timestamp", "ts", "createTime", "create_time"]


# ============================================================
# 提取工具
# ============================================================

def extract_value(row: dict[str, Any], keys: list[str]) -> Optional[float]:
    """
    按 keys 顺序尝试提取 row 中的数值字段,返回第一个非 None 且可转 float 的值。
    如果都取不到,返回 None(调用方自行决定是 warning 还是跳过)。
    """
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return None


def extract_raw(row: dict[str, Any], keys: list[str]) -> Any:
    """
    extract_value 的"不转 float"版本,用于 string / dict 等非数值字段。
    """
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None
