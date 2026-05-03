"""src/ai/circuit_breaker.py — Sprint 1.10-F 短路依赖管理器(v1.4 §6.3.1)。

orchestrator 失败传导规则:
- L1 fail → L2/L3/Master 短路(L4/L5 仍跑独立)
- L2 fail → L3/Master 短路(L4/L5 仍跑)
- L3 fail → Master 短路
- L4 fail → Master 短路
- L5 fail → Master 仍跑(用规则化 macro fallback,§6.4.2)
- Master fail → 由 thesis_aware_fallback 处理(无下游)

短路含义:层失败超 max_attempts → 标记该层 status=short_circuited,
下游调用方跳过(不走 AI 调用,直接 fallback)。

设计纪律:
- 纯函数:输入失败层列表,输出该短路的下游 + 是否 master 仍跑
- 不调 AI / 不写 DB
"""
from __future__ import annotations

from typing import Any


# 短路依赖图(v1.4 §6.3.1)
# key = 失败层,value = 该短路的下游列表
_SHORTCUT_RULES: dict[str, list[str]] = {
    "l1": ["l2", "l3", "master"],
    "l2": ["l3", "master"],
    "l3": ["master"],
    "l4": ["master"],
    "l5": [],   # L5 失败不短路 master(走 macro fallback,见 apply_macro_fallback)
}

_VALID_LAYERS = ("l1", "l2", "l3", "l4", "l5", "master")


# v1.4 §6.4.2 D4=a 硬编码 macro fallback(L5 失败时给 master 用)
_MACRO_FALLBACK_HARDCODED = {
    "macro_stance": "risk_neutral",
    "headwind_score": 0,
    "extreme_event_detected": False,
    "position_cap_macro_multiplier": 1.0,
    "narrative": "L5 失败,硬编码 macro fallback(risk_neutral / 无 headwind /"
                  " 无极端事件 / cap_multiplier=1.0)",
    "key_observations": ["L5 AI failed, applied conservative macro fallback"],
    "counter_arguments": ["macro 数据缺失,master 应保守判断"],
    "objective_evidence": ["l5_failed → macro_fallback applied"],
    "status": "degraded_l5_failed_macro_fallback",
}


class CircuitBreaker:
    """v1.4 §6.3.1 短路依赖图。

    用法:
        cb = CircuitBreaker()
        # L1 失败 → 短路下游
        downstream = cb.get_downstream_to_short("l1")  # ['l2', 'l3', 'master']

        # 多层失败时,整体判定 master 是否仍跑
        ok, reason = cb.should_master_run(failed_layers=["l5"])  # (True, ...)
        ok, reason = cb.should_master_run(failed_layers=["l1"])  # (False, ...)

        # L5 失败时取硬编码 macro fallback(D4=a)
        macro = cb.apply_macro_fallback()
    """

    @staticmethod
    def get_downstream_to_short(failed_layer: str) -> list[str]:
        """给定单层失败,返回需短路的下游列表。

        Args:
            failed_layer: "l1" / "l2" / "l3" / "l4" / "l5" / "master"

        Returns:
            list[str] 需短路的下游层(空 list = 该层失败不影响下游)
        """
        if failed_layer not in _VALID_LAYERS:
            return []
        return list(_SHORTCUT_RULES.get(failed_layer, []))

    @staticmethod
    def should_master_run(
        failed_layers: list[str],
    ) -> tuple[bool, str]:
        """给定已失败层列表,判定 master 是否仍跑。

        - L1/L2/L3/L4 任一失败 → master 不跑(短路)
        - L5 失败 → master 仍跑(用 macro fallback)
        - 全部成功 → master 跑

        Returns:
            (should_run, reason)
        """
        failed_set = set(failed_layers or [])
        # L5 单独失败 → master 仍跑(allowed)
        critical_failures = failed_set - {"l5"}
        if critical_failures:
            return (False, f"master_short_circuited_due_to_{sorted(critical_failures)}")
        if "l5" in failed_set:
            return (True, "master_runs_with_macro_fallback_l5_failed")
        return (True, "all_layers_success_master_runs")

    @staticmethod
    def apply_macro_fallback() -> dict[str, Any]:
        """L5 失败时,返回硬编码的 macro fallback dict(v1.4 §6.4.2 + D4=a)。

        master 接到此 fallback 后,context.l5_output = 此 dict,继续跑。
        """
        return dict(_MACRO_FALLBACK_HARDCODED)
