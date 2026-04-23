"""
_timestamp.py — 时间戳规范化工具(跨 collectors 共享)

CoinGlass 用毫秒(13 位),Glassnode 用秒(10 位),Yahoo/FRED 返回 pandas
DatetimeIndex 或字符串。统一把所有输入转成 ISO 8601 UTC 字符串 'YYYY-MM-DDTHH:MM:SSZ',
对齐 `src/data/storage/schema.sql` 的 TEXT 列格式。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal


TimestampUnit = Literal["ms", "s", "auto"]


def to_iso_utc(value: Any, unit: TimestampUnit = "auto") -> str:
    """
    把任意时间戳输入转成 ISO 8601 UTC 字符串('Z' 后缀)。

    支持:
      - int/float:若 unit=ms 按毫秒;若 unit=s 按秒;若 unit=auto 则 >1e12 视为 ms
      - ISO 字符串('2024-01-01T00:00:00Z' / '+00:00' 变体)
      - 纯数字字符串('1704067200' 或 '1704067200000')
      - datetime.datetime 对象

    Args:
        value: 输入值
        unit: ms / s / auto

    Raises:
        ValueError: 无法解析。
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if isinstance(value, (int, float)):
        if unit == "ms":
            seconds = value / 1000
        elif unit == "s":
            seconds = float(value)
        else:  # auto
            seconds = value / 1000 if value > 1e12 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    if isinstance(value, str):
        s = value.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return to_iso_utc(int(s), unit=unit)
        try:
            return to_iso_utc(float(s), unit=unit)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError as e:
            raise ValueError(f"Cannot parse timestamp {value!r}") from e

    raise ValueError(
        f"Unsupported timestamp type: {type(value).__name__}={value!r}"
    )


def since_days_ago_unix(days: int, unit: TimestampUnit = "s") -> int:
    """
    返回 N 天前的 unix 时间戳(整数)。
    unit=s(默认,对应 Glassnode);unit=ms(对应 CoinGlass 的某些端点)。
    """
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    epoch = dt.timestamp()
    if unit == "ms":
        return int(epoch * 1000)
    return int(epoch)
