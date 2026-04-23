"""
permission.py — 全局权限严格度顺序 + 归并工具。

单一真相源:thresholds.yaml 顶层 `permission_strictness_order`
(Sprint 1.11 统一)。

严格度惯例:
  * 列表索引越大 → 越严
  * merge_permissions(*perms) → 返回严格度最高的那个(索引最大)
  * 未识别的 permission 被跳过;若全都未识别,返回第一个输入(兜底)

跨层使用者:
  * L3 Opportunity 的 anti_pattern permission_cap 合并
  * L4 Risk 的 L3→L4 permission merge
  * state_machine / AI adjudicator 的最终 permission 归并
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_THRESHOLDS_PATH: Path = _PROJECT_ROOT / "config" / "thresholds.yaml"

# 硬编码兜底:thresholds.yaml 读取失败或无此 key 时用
_DEFAULT_ORDER: list[str] = [
    "can_open", "cautious_open", "ambush_only",
    "no_chase", "hold_only", "watch", "protective",
]


@lru_cache(maxsize=1)
def _load_order() -> list[str]:
    """读 thresholds.yaml 顶层 permission_strictness_order。"""
    try:
        with open(_THRESHOLDS_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        order = cfg.get("permission_strictness_order")
        if isinstance(order, list) and len(order) >= 2:
            return list(order)
    except OSError:
        pass
    return list(_DEFAULT_ORDER)


def get_permission_order() -> list[str]:
    """
    返回全局 permission 严格度顺序(wide → strict)。
    索引越大 → 越严。
    """
    return list(_load_order())


def merge_permissions(*permissions: str) -> str:
    """
    返回严格度最高(最靠后 = 索引最大)的那个 permission。

    Args:
        *permissions: 任意个 permission 字符串。

    Returns:
        最严的 permission。

    Edge cases:
      * 空输入 → 返回 "watch"(安全默认)
      * 全部未识别 → 返回第一个(保留输入而非静默变 watch)
      * 混合(部分识别)→ 只在识别出的里挑最严
    """
    if not permissions:
        return "watch"
    order = _load_order()
    valid = [p for p in permissions if p in order]
    if not valid:
        return permissions[0]
    return max(valid, key=lambda p: order.index(p))


def is_permission_strict_enough(p: str, threshold: str) -> bool:
    """
    p 的严格度是否 ≥ threshold。
    用于"至少 threshold 这么严"的检查。
    """
    order = _load_order()
    if p not in order or threshold not in order:
        return False
    return order.index(p) >= order.index(threshold)
