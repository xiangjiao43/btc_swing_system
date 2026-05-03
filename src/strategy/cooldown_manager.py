"""src/strategy/cooldown_manager.py — Sprint 1.10-C 冷却期 + 反手通道判定。

对齐 docs/modeling.md b25cfe6(v1.4)§4.3。

职责(本 sprint 范围):
- determine_close_channel:close 时选 A/B/C(4 条件分级)
- compute_cooldown_end:按 channel 算冷却结束时间
- is_in_cooldown:查询当前是否在冷却(基于最新 closed thesis)

设计纪律:
- 不调 master AI(留 1.10-D);"维持 thesis"决策属 master AI 范畴,
  本模块只在已决定关闭后选 channel
- 不读 DB 直接(本模块纯函数,DB 查询由调用方做)
- §4.3 通道定义:
  * A 慢通道:自然结束(closed_profit / closed_loss / 60d_cap / protection)→ 72h
  * B 中通道:invalidated 默认 → 24h
  * C 快通道:invalidated + 4 条件 ≥ 3/4 → 0h
  * 2/4 + L1 完全反转 → B(降级到 24h,即默认)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional


# 冷却时长(小时)
_COOLDOWN_HOURS = {
    "A": 72.0,    # 自然结束 3 天
    "B": 24.0,    # invalidated 24h
    "C": 0.0,     # 紧急反手 0h
}

# closed reason → 默认 channel(invalidated 走 4 条件分级,其他直接定)
_REASON_TO_DEFAULT_CHANNEL = {
    "all_take_profit_filled": "A",
    "stop_loss_filled":       "A",
    "60d_cap":                "A",   # 60d 默认走慢通道(D4=b 实际 60d 不进 closed,
                                     # 但若调用方仍传 60d_cap reason,默认 A)
    "protection":             "A",   # 极端事件走 A(最保守)
    "invalidated":            "B",   # invalidated 默认 B,4/4 或 3/4 升 C
}


def _parse_iso(s: str) -> datetime:
    s = str(s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def determine_close_channel(
    close_reason: str,
    *,
    stop_loss_breached: bool = False,
    l1_regime_fully_reversed: bool = False,
    l2_stance_strong_flip: bool = False,        # confidence ≥ 0.75
    l5_extreme_event_or_risk_off: bool = False,
) -> str:
    """选反手通道 A/B/C(v1.4 §4.3.3 4 条件分级)。

    Args:
        close_reason: ThesisManager.close_thesis 的 reason
        stop_loss_breached: 价格已击穿 stop_loss(实际平仓)
        l1_regime_fully_reversed: L1 regime 完全反转(trend_up ↔ trend_down,非过渡态)
        l2_stance_strong_flip: L2 stance 强翻转(confidence ≥ 0.75)
        l5_extreme_event_or_risk_off: L5 极端事件 OR macro_stance 翻转 risk_off

    Returns:
        "A" / "B" / "C"

    分级(仅 invalidated reason 时):
        4/4 → C(立即反手 0 冷却)
        3/4 → C
        2/4 + L1 完全反转 → B(24h 冷却,即 invalidated 默认)
        其他 invalidated → B
    其他 close_reason → 走 _REASON_TO_DEFAULT_CHANNEL 表(默认 A,
    invalidated 默认 B 但可升 C)
    """
    if close_reason not in _REASON_TO_DEFAULT_CHANNEL:
        # 未知 reason 默认走 A(最保守,避免 0 冷却的快通道误用)
        return "A"

    default = _REASON_TO_DEFAULT_CHANNEL[close_reason]
    if close_reason != "invalidated":
        return default

    # invalidated 时检查 4 条件升降级
    score = sum([
        bool(stop_loss_breached),
        bool(l1_regime_fully_reversed),
        bool(l2_stance_strong_flip),
        bool(l5_extreme_event_or_risk_off),
    ])
    if score >= 3:
        return "C"
    if score == 2 and l1_regime_fully_reversed:
        return "B"   # 即默认,显式标识
    return "B"        # invalidated 默认


def compute_cooldown_end(closed_at_utc: str, close_channel: str) -> str:
    """算冷却结束时间(closed_at + 通道时长)。

    A → +72h / B → +24h / C → +0h

    Returns: ISO 8601 UTC 字符串(YYYY-MM-DDTHH:MM:SSZ)
    """
    if close_channel not in _COOLDOWN_HOURS:
        raise ValueError(f"未知 close_channel: {close_channel!r}(应是 A/B/C)")
    closed_dt = _parse_iso(closed_at_utc)
    end_dt = closed_dt + timedelta(hours=_COOLDOWN_HOURS[close_channel])
    return _format_iso(end_dt)


def is_in_cooldown(
    now_utc: str,
    latest_closed_thesis: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """判断当前是否在冷却期(基于最新 closed thesis)。

    Args:
        now_utc: 当前时间
        latest_closed_thesis: 最近一条 closed thesis dict(含 closed_at_utc + close_channel),
                              None = 从未关闭过 → 不在冷却

    Returns:
        {
          "in_cooldown":     bool,
          "remaining_hours": float,        # 0 = 不在冷却
          "channel":         str | None,   # 触发该冷却的 thesis 的 channel
          "thesis_id":       str | None,
          "cooldown_end_utc": str | None,
        }
    """
    if latest_closed_thesis is None:
        return {
            "in_cooldown": False, "remaining_hours": 0.0,
            "channel": None, "thesis_id": None, "cooldown_end_utc": None,
        }

    channel = latest_closed_thesis.get("close_channel")
    closed_at = latest_closed_thesis.get("closed_at_utc")
    if not channel or not closed_at:
        return {
            "in_cooldown": False, "remaining_hours": 0.0,
            "channel": channel, "thesis_id": latest_closed_thesis.get("thesis_id"),
            "cooldown_end_utc": None,
        }
    if channel not in _COOLDOWN_HOURS:
        return {
            "in_cooldown": False, "remaining_hours": 0.0,
            "channel": channel, "thesis_id": latest_closed_thesis.get("thesis_id"),
            "cooldown_end_utc": None,
        }

    cooldown_end_utc = compute_cooldown_end(closed_at, channel)
    end_dt = _parse_iso(cooldown_end_utc)
    now_dt = _parse_iso(now_utc)
    delta = (end_dt - now_dt).total_seconds() / 3600.0  # hours
    in_cooldown = delta > 0
    return {
        "in_cooldown": in_cooldown,
        "remaining_hours": max(0.0, round(delta, 4)),
        "channel": channel,
        "thesis_id": latest_closed_thesis.get("thesis_id"),
        "cooldown_end_utc": cooldown_end_utc,
    }
