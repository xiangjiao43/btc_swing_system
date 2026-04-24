"""
lifecycle_fsm.py — Sprint 1.14b 交易生命周期 FSM

读 config/lifecycle_fsm.yaml,按声明式规则计算下一个 lifecycle 状态。

主入口 LifecycleFSM.compute_next(...)。
  * 优先级:_auto_after_minutes 到期 > action 表查询 > _default
  * 方向冲突(LONG_* + open_short / SHORT_* + open_long)时:保持原状态 +
    conflict_detected=true。
  * 未定义状态(不在 config 中)→ 视为 FLAT 兜底,conflict_detected=true。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml


logger = logging.getLogger(__name__)


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH: Path = _PROJECT_ROOT / "config" / "lifecycle_fsm.yaml"


_LONG_STATES: frozenset[str] = frozenset({
    "LONG_PLANNED", "LONG_OPEN", "LONG_SCALING", "LONG_REDUCING",
})
_SHORT_STATES: frozenset[str] = frozenset({
    "SHORT_PLANNED", "SHORT_OPEN", "SHORT_SCALING", "SHORT_REDUCING",
})
_CROSS_DIRECTION_OPENERS_LONG = frozenset({"open_long", "scale_in_long"})
_CROSS_DIRECTION_OPENERS_SHORT = frozenset({"open_short", "scale_in_short"})


class LifecycleFSM:
    """声明式 FSM,单次调用 compute_next 即完成一次状态推进。"""

    def __init__(
        self,
        config_path: Optional[str | Path] = None,
    ) -> None:
        self.config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self.config = _load_yaml(self.config_path)
        self.transitions: dict[str, Any] = dict(self.config.get("transitions") or {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_next(
        self,
        current_lifecycle: str,
        adjudicator_action: str,
        current_timestamp: str,
        previous_transition_timestamp: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Args:
            current_lifecycle:              如 'FLAT', 'LONG_OPEN' ...
            adjudicator_action:             如 'open_long', 'hold' ...
            current_timestamp:              本次 tick 时间,ISO UTC
            previous_transition_timestamp:  上一次进入 current_lifecycle 的时间;None
                                            = 未知(当作刚进入,auto 永远不触发)

        Returns:
            {
              previous_lifecycle, current_lifecycle, transition_triggered_by,
              transition_rule, minutes_since_previous, conflict_detected,
            }
        """
        previous = current_lifecycle
        minutes_since = _minutes_between(
            previous_transition_timestamp, current_timestamp,
        )

        rule_def = self.transitions.get(current_lifecycle)
        if not isinstance(rule_def, dict):
            # 未知状态 → 兜底到 FLAT
            return {
                "previous_lifecycle": previous,
                "current_lifecycle": "FLAT",
                "transition_triggered_by": "fallback_unknown_state",
                "transition_rule": f"{current_lifecycle} 未在 lifecycle_fsm.yaml 中定义,兜底 FLAT",
                "minutes_since_previous": minutes_since,
                "conflict_detected": True,
            }

        # 1. 先看 auto timeout
        auto_target = rule_def.get("_auto_target")
        auto_minutes = rule_def.get("_auto_after_minutes")
        if (
            auto_target is not None
            and auto_minutes is not None
            and minutes_since is not None
            and minutes_since >= float(auto_minutes)
        ):
            return {
                "previous_lifecycle": previous,
                "current_lifecycle": auto_target,
                "transition_triggered_by": "auto_timeout",
                "transition_rule": (
                    f"{previous} → {auto_target} "
                    f"(满 {auto_minutes} 分钟自动迁移)"
                ),
                "minutes_since_previous": minutes_since,
                "conflict_detected": False,
            }

        # 2. 方向冲突检测(持多仓时出现 open_short 之类)
        conflict = _direction_conflict(current_lifecycle, adjudicator_action)
        if conflict:
            return {
                "previous_lifecycle": previous,
                "current_lifecycle": previous,
                "transition_triggered_by": "direction_conflict_blocked",
                "transition_rule": (
                    f"{previous} 阻止反向 action={adjudicator_action},保持原状态"
                ),
                "minutes_since_previous": minutes_since,
                "conflict_detected": True,
            }

        # 3. action 查表
        action = (adjudicator_action or "").strip()
        target: Optional[str] = None
        rule_desc: str = ""
        if action and action in rule_def and not action.startswith("_"):
            target = rule_def[action]
            rule_desc = f"action={action} → {target}"
            triggered_by = "action"
        else:
            default = rule_def.get("_default")
            if default is not None:
                target = default
                rule_desc = (
                    f"action={action or 'none'} 未在表中,走 _default → {default}"
                )
                triggered_by = "default"
            else:
                # 没有 _default,且该状态只靠 auto(如 LONG_CLOSED):保持
                target = current_lifecycle
                rule_desc = (
                    f"{current_lifecycle} 无 action 分支(仅 auto),保持原状态"
                )
                triggered_by = "no_op"

        return {
            "previous_lifecycle": previous,
            "current_lifecycle": target,
            "transition_triggered_by": triggered_by,
            "transition_rule": rule_desc,
            "minutes_since_previous": minutes_since,
            "conflict_detected": False,
        }


# ============================================================
# Helpers
# ============================================================

def _direction_conflict(current: str, action: str) -> bool:
    """持多仓 + open_short / 持空仓 + open_long 视为冲突。"""
    if current in _LONG_STATES and action in _CROSS_DIRECTION_OPENERS_SHORT:
        return True
    if current in _SHORT_STATES and action in _CROSS_DIRECTION_OPENERS_LONG:
        return True
    return False


def _minutes_between(a_iso: Optional[str], b_iso: Optional[str]) -> Optional[float]:
    if not a_iso or not b_iso:
        return None
    try:
        a = _parse_iso(a_iso)
        b = _parse_iso(b_iso)
    except Exception:
        return None
    return (b - a).total_seconds() / 60.0


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@lru_cache(maxsize=8)
def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
