"""
state_machine.py — Sprint 1.5a,建模 §5 唯一权威 14 档状态机。

职责:
  * 14 档状态的迁移判定(§5.2)
  * FLIP_WATCH 动态冷却(§5.3)
  * 三条核心纪律(§5.4)强制校验
  * 状态进入副作用(§5.5)v1:只记录到 on_enter_effects,不写 lifecycle 表

配置:config/state_machine.yaml(只存阈值与乘数等"可调参数")
迁移逻辑:本文件的 Python 实现,不放 YAML(§5.2 有时间+走势组合这类
          复杂条件,YAML DSL 表达力不够)。

输入契约(strategy_state):
  * evidence_reports.layer_1/2/3/4/5(同 Sprint 1.12 形状)
  * composite_factors.cycle_position(用于 FLIP_WATCH 冷却乘数)
  * trade_plan(由 AI 裁决产出 / Sprint 1.5b 起链式注入)
  * lifecycle(由 Sprint 1.5b 的 lifecycle_manager 产出;v1 可缺省)
  * macro_events.extreme_event_detected(由 L5 产出)

previous_record:DAO 查到的上一条 strategy_state 行(含 state_machine 子块)
account_state:{long_position_size, short_position_size, stop_triggered, ...}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml


logger = logging.getLogger(__name__)


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH: Path = _PROJECT_ROOT / "config" / "state_machine.yaml"


# ============================================================
# 14 档权威状态(§5.1)
# ============================================================

VALID_STATES: tuple[str, ...] = (
    "FLAT",
    "LONG_PLANNED", "LONG_OPEN", "LONG_HOLD", "LONG_TRIM", "LONG_EXIT",
    "SHORT_PLANNED", "SHORT_OPEN", "SHORT_HOLD", "SHORT_TRIM", "SHORT_EXIT",
    "FLIP_WATCH", "PROTECTION", "POST_PROTECTION_REASSESS",
)

_LONG_SIDE: frozenset[str] = frozenset({
    "LONG_PLANNED", "LONG_OPEN", "LONG_HOLD", "LONG_TRIM", "LONG_EXIT",
})
_SHORT_SIDE: frozenset[str] = frozenset({
    "SHORT_PLANNED", "SHORT_OPEN", "SHORT_HOLD", "SHORT_TRIM", "SHORT_EXIT",
})
_HOLD_STATES: frozenset[str] = frozenset({"LONG_HOLD", "SHORT_HOLD"})
_PLANNED_STATES: frozenset[str] = frozenset({
    "LONG_PLANNED", "SHORT_PLANNED",
})


# POST_PROTECTION_REASSESS 允许迁出的白名单(§5.2)
_PPR_ALLOWED_TARGETS: frozenset[str] = frozenset({
    "LONG_HOLD", "SHORT_HOLD",
    "LONG_EXIT", "SHORT_EXIT",
    "FLAT", "FLIP_WATCH",
})


# ============================================================
# 数据类
# ============================================================

@dataclass
class StateMachineResult:
    """StateMachine.compute_next 返回结构。"""

    previous_state: Optional[str]
    current_state: str
    transition_reason: str
    matched_conditions: list[str] = field(default_factory=list)
    state_entered_at_utc: str = ""
    minutes_since_entered: Optional[float] = None
    stable_in_state: bool = False
    flip_watch_bounds: Optional[dict[str, Any]] = None
    on_enter_effects: dict[str, Any] = field(default_factory=dict)
    disciplines_violated: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# StateMachine
# ============================================================

class StateMachine:
    """
    建模 §5 的 14 档状态机。

    主入口 compute_next:
      * 读取 previous_record 的 state_machine 子块做"当前状态"起点
      * 先检查 PROTECTION 触发(§5.2 任何状态 → PROTECTION)
      * 再按 source state 分派到对应的 _transition_from_<STATE> 方法
      * 最后调 _on_enter_effects 记录 §5.5 副作用
      * 纪律违反 → 抛异常(三条核心纪律 §5.4)
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
    ) -> None:
        self.config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self.config = _load_yaml(self.config_path)
        sc = self.config.get("stance_confidence_thresholds") or {}
        self._long_min = float(sc.get("long_min", 0.60))
        self._short_min = float(sc.get("short_min", 0.65))

        fw = self.config.get("flip_watch") or {}
        self._fw_base_min = float(fw.get("base_min_hours", 18))
        self._fw_base_max = float(fw.get("base_max_hours", 96))
        self._fw_floor = float(fw.get("hard_floor_min_hours", 8))
        self._fw_ceil = float(fw.get("hard_ceil_max_hours", 168))
        self._fw_cycle_mult = dict(fw.get("cycle_position_multipliers") or {})
        self._fw_vol_mult = dict(fw.get("volatility_multipliers") or {})

        op = self.config.get("open_phase") or {}
        self._open_min_hours = float(op.get("min_hours_to_hold", 24))
        self._open_pnl_threshold = float(
            op.get("pnl_confirmed_threshold_pct", 2.0)
        )
        self._open_tp1_distance = float(op.get("tp1_distance_pct", 50.0))
        self._stance_flip_window = float(op.get("stance_flip_window_hours", 12))
        self._stance_flip_conf_min = float(
            op.get("stance_flip_confidence_min", 0.7)
        )

        ppr = self.config.get("post_protection_reassess") or {}
        self._ppr_min_hold_hours = float(ppr.get("min_hold_hours", 4))

        tt = self.config.get("trim_triggers") or {}
        self._phase_late_conf_min = float(tt.get("phase_late_confidence_min", 0.65))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_next(
        self,
        strategy_state: dict[str, Any],
        *,
        previous_record: Optional[dict[str, Any]] = None,
        account_state: Optional[dict[str, Any]] = None,
        now_utc: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Args:
          strategy_state:   本轮已填好的 state(evidence_reports + composite_factors
                            + trade_plan + lifecycle + macro_events 等)
          previous_record:  DAO 查到的上一条 strategy_state_history 行
          account_state:    账户状态(hold、持仓等)
          now_utc:          本次 tick 时间,ISO UTC。默认 strategy_state.reference_timestamp_utc
        Returns:
          StateMachineResult.to_dict()
        """
        now = now_utc or strategy_state.get("reference_timestamp_utc") or _utc_now_iso()

        prev_state, prev_entered_at, prev_flip_bounds = _extract_prev(previous_record)
        if prev_state is None or prev_state not in VALID_STATES:
            # 冷启动 / 历史含旧名:归零到 FLAT
            prev_state = "FLAT"
            prev_entered_at = now
            prev_flip_bounds = None

        fields = _build_field_snapshot(
            strategy_state=strategy_state,
            account_state=account_state or {},
            prev_state=prev_state,
            prev_entered_at=prev_entered_at,
            prev_flip_bounds=prev_flip_bounds,
            now_utc=now,
        )

        # ---- PROTECTION 全局入口(§5.2)----
        # POST_PROTECTION_REASSESS 除外(§5.4 纪律 3:不允许直接回 PROTECTION)
        if prev_state != "POST_PROTECTION_REASSESS" and _protection_triggered(fields):
            return self._build_result(
                prev_state=prev_state,
                target="PROTECTION",
                reason="极端事件/Fallback Level 3 触发,进入 PROTECTION",
                matched=["protection_trigger_detected"],
                fields=fields,
                prev_entered_at=prev_entered_at,
                now=now,
            )

        # ---- 按 source state 分派 ----
        dispatcher = {
            "FLAT": self._from_FLAT,
            "LONG_PLANNED": self._from_LONG_PLANNED,
            "LONG_OPEN": self._from_LONG_OPEN,
            "LONG_HOLD": self._from_LONG_HOLD,
            "LONG_TRIM": self._from_LONG_TRIM,
            "LONG_EXIT": self._from_LONG_EXIT,
            "SHORT_PLANNED": self._from_SHORT_PLANNED,
            "SHORT_OPEN": self._from_SHORT_OPEN,
            "SHORT_HOLD": self._from_SHORT_HOLD,
            "SHORT_TRIM": self._from_SHORT_TRIM,
            "SHORT_EXIT": self._from_SHORT_EXIT,
            "FLIP_WATCH": self._from_FLIP_WATCH,
            "PROTECTION": self._from_PROTECTION,
            "POST_PROTECTION_REASSESS": self._from_POST_PROTECTION_REASSESS,
        }
        handler = dispatcher[prev_state]
        target, reason, matched = handler(fields)

        if target is None:
            target, reason, matched = prev_state, "保持当前状态", ["no_transition_matched"]

        return self._build_result(
            prev_state=prev_state,
            target=target,
            reason=reason,
            matched=matched,
            fields=fields,
            prev_entered_at=prev_entered_at,
            now=now,
        )

    # ------------------------------------------------------------------
    # 结果封装 + 纪律校验 + FLIP_WATCH bounds + on_enter 副作用
    # ------------------------------------------------------------------

    def _build_result(
        self,
        *,
        prev_state: str,
        target: str,
        reason: str,
        matched: list[str],
        fields: dict[str, Any],
        prev_entered_at: Optional[str],
        now: str,
    ) -> dict[str, Any]:
        if target not in VALID_STATES:
            raise ValueError(
                f"State machine produced invalid target {target!r}; "
                f"must be one of {VALID_STATES}"
            )

        disciplines_violated = _verify_disciplines(prev_state, target)
        if disciplines_violated:
            raise DisciplineViolation(
                f"{prev_state} → {target} 违反核心纪律:{disciplines_violated}"
            )

        is_transition = target != prev_state
        state_entered_at = now if is_transition else (prev_entered_at or now)
        minutes_since = _minutes_between(state_entered_at, now)

        # 进入 FLIP_WATCH 时计算 effective bounds 并锁定
        flip_bounds: Optional[dict[str, Any]] = None
        if target == "FLIP_WATCH":
            if is_transition:
                flip_bounds = self._calc_flip_watch_bounds(fields)
            else:
                flip_bounds = fields.get("prev_flip_bounds")

        on_enter = self._on_enter_effects(
            target=target,
            is_transition=is_transition,
            prev_state=prev_state,
            fields=fields,
            now=now,
            flip_bounds=flip_bounds,
        )

        return StateMachineResult(
            previous_state=prev_state,
            current_state=target,
            transition_reason=reason,
            matched_conditions=list(matched),
            state_entered_at_utc=state_entered_at,
            minutes_since_entered=minutes_since,
            stable_in_state=not is_transition,
            flip_watch_bounds=flip_bounds,
            on_enter_effects=on_enter,
            disciplines_violated=[],
        ).to_dict()

    # ------------------------------------------------------------------
    # FLIP_WATCH 动态冷却(§5.3)
    # ------------------------------------------------------------------

    def _calc_flip_watch_bounds(
        self, fields: dict[str, Any],
    ) -> dict[str, Any]:
        """进入 FLIP_WATCH 时计算 effective_min/max_hours 并锁定。"""
        mult = 1.0
        chain: list[tuple[str, float]] = []

        cp = fields.get("cycle_position")
        if cp and cp in self._fw_cycle_mult:
            m = float(self._fw_cycle_mult[cp])
            mult *= m
            chain.append((f"cycle_position={cp}", m))

        vol = fields.get("volatility_regime")
        if vol and vol in self._fw_vol_mult:
            m = float(self._fw_vol_mult[vol])
            mult *= m
            chain.append((f"volatility_regime={vol}", m))

        eff_min = max(self._fw_floor, self._fw_base_min * mult)
        eff_max = min(self._fw_ceil, self._fw_base_max * mult)
        return {
            "effective_min_hours": round(eff_min, 2),
            "effective_max_hours": round(eff_max, 2),
            "base_min_hours": self._fw_base_min,
            "base_max_hours": self._fw_base_max,
            "multiplier_product": round(mult, 4),
            "multiplier_chain": [
                {"source": src, "multiplier": m} for src, m in chain
            ],
        }

    # ------------------------------------------------------------------
    # on_enter 副作用(§5.5)v1:只记录,不写 lifecycle 表
    # ------------------------------------------------------------------

    def _on_enter_effects(
        self,
        *,
        target: str,
        is_transition: bool,
        prev_state: str,
        fields: dict[str, Any],
        now: str,
        flip_bounds: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        建模 §5.5 规定的副作用。Sprint 1.5a v1 只落到 result.on_enter_effects
        字段,不实际写 lifecycle 表(Sprint 1.5b 由 lifecycle_manager 完成)。
        """
        if not is_transition:
            return {"applied": False, "reason": "stable_in_state"}

        effects: dict[str, Any] = {
            "applied": True,
            "target": target,
            "previous_state": prev_state,
            "entered_at_utc": now,
            "actions": [],
            "lifecycle_delegate": "pending_lifecycle_manager",
        }
        if target == "FLAT":
            effects["actions"] = [
                "archive_current_lifecycle",
                "reset_position_cap",
                "clear_all_pending_orders",
                "log_transition",
            ]
        elif target in _PLANNED_STATES:
            effects["actions"] = [
                "create_lifecycle_draft",
                "record_origin_thesis",
                "set_planned_expiry",
                "push_notification",
            ]
        elif target in ("LONG_OPEN", "SHORT_OPEN"):
            effects["actions"] = [
                "lifecycle_pending_to_active",
                "record_origin_time",
                "enable_open_phase_protection",
                "push_notification",
            ]
        elif target in ("LONG_HOLD", "SHORT_HOLD"):
            effects["actions"] = [
                "disable_open_phase_protection",
                "enable_standard_monitoring",
                "init_max_favorable_pct",
                "init_max_adverse_pct",
            ]
        elif target in ("LONG_TRIM", "SHORT_TRIM"):
            effects["actions"] = [
                "record_position_adjustment",
                "stage_partial_trimmed",
                "update_remaining_stops_and_tps",
            ]
        elif target in ("LONG_EXIT", "SHORT_EXIT"):
            effects["actions"] = [
                "record_position_adjustment",
                "prepare_lifecycle_archive",
                "record_exit_reason",
            ]
        elif target == "FLIP_WATCH":
            effects["actions"] = [
                "archive_previous_lifecycle",
                "record_flip_watch_start_time",
                "lock_flip_watch_effective_bounds",
                "reset_position",
            ]
            effects["flip_watch_bounds"] = flip_bounds
        elif target == "PROTECTION":
            effects["actions"] = [
                "record_protection_entry_time_and_reason",
                "freeze_new_openings",
                "ai_handles_residual_positions",
                "push_urgent_notification",
                "require_manual_confirmation",
            ]
        elif target == "POST_PROTECTION_REASSESS":
            effects["actions"] = [
                "record_reassess_entry_time",
                "preserve_lifecycle_no_archive",
                "force_execution_permission_hold_only",
            ]
        return effects

    # ==================================================================
    # §5.2 逐状态迁移判定
    # ==================================================================

    # ------ FLAT ------
    def _from_FLAT(self, fields: dict[str, Any]) -> tuple[Optional[str], str, list[str]]:
        # FLAT → LONG_PLANNED(全部满足)
        long_checks = [
            ("l1_regime_in", fields.get("l1_regime") in {"trend_up", "transition_up", "range_low"},
             f"l1_regime={fields.get('l1_regime')}"),
            ("l2_stance_eq_bullish", fields.get("l2_stance") == "bullish",
             f"l2_stance={fields.get('l2_stance')}"),
            ("l2_stance_confidence_gte_long_min",
             _as_float(fields.get("l2_stance_confidence")) is not None
             and _as_float(fields.get("l2_stance_confidence")) >= self._long_min,
             f"l2_stance_confidence={fields.get('l2_stance_confidence')} vs {self._long_min}"),
            ("l3_grade_in_AB", fields.get("l3_grade") in {"A", "B"},
             f"l3_grade={fields.get('l3_grade')}"),
            ("l3_permission_allows_open",
             fields.get("l3_permission") in {"can_open", "cautious_open", "ambush_only"},
             f"l3_permission={fields.get('l3_permission')}"),
            ("l4_overall_risk_not_critical",
             fields.get("l4_overall_risk") != "critical",
             f"l4_overall_risk={fields.get('l4_overall_risk')}"),
            ("l5_macro_stance_not_extreme",
             fields.get("l5_macro_stance") != "extreme_risk_off",
             f"l5_macro_stance={fields.get('l5_macro_stance')}"),
            ("not_protection_mode", not fields.get("protection_mode", False),
             f"protection_mode={fields.get('protection_mode', False)}"),
        ]
        if all(ok for _, ok, _ in long_checks):
            matched = [f"{name}: {detail}" for name, _, detail in long_checks]
            return "LONG_PLANNED", "FLAT → LONG_PLANNED:全部多头条件满足", matched

        # FLAT → SHORT_PLANNED(镜像,动态门槛,v1.2 简化:A/B)
        short_checks = [
            ("l1_regime_in_down",
             fields.get("l1_regime") in {"trend_down", "transition_down", "range_high"},
             f"l1_regime={fields.get('l1_regime')}"),
            ("l2_stance_eq_bearish", fields.get("l2_stance") == "bearish",
             f"l2_stance={fields.get('l2_stance')}"),
            ("l2_stance_confidence_gte_short_min",
             _as_float(fields.get("l2_stance_confidence")) is not None
             and _as_float(fields.get("l2_stance_confidence")) >= self._short_min,
             f"l2_stance_confidence={fields.get('l2_stance_confidence')} vs {self._short_min}"),
            ("l3_grade_in_AB", fields.get("l3_grade") in {"A", "B"},
             f"l3_grade={fields.get('l3_grade')}"),
            ("l3_permission_allows_open",
             fields.get("l3_permission") in {"can_open", "cautious_open", "ambush_only"},
             f"l3_permission={fields.get('l3_permission')}"),
            ("l4_overall_risk_not_critical",
             fields.get("l4_overall_risk") != "critical",
             f"l4_overall_risk={fields.get('l4_overall_risk')}"),
            ("l5_macro_stance_not_extreme",
             fields.get("l5_macro_stance") != "extreme_risk_off",
             f"l5_macro_stance={fields.get('l5_macro_stance')}"),
            ("not_protection_mode", not fields.get("protection_mode", False),
             f"protection_mode={fields.get('protection_mode', False)}"),
        ]
        if all(ok for _, ok, _ in short_checks):
            matched = [f"{name}: {detail}" for name, _, detail in short_checks]
            return "SHORT_PLANNED", "FLAT → SHORT_PLANNED:全部空头条件满足", matched

        return None, "保持 FLAT:无迁移条件成立", []

    # ------ LONG_PLANNED ------
    def _from_LONG_PLANNED(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        # → LONG_OPEN:trade_plan 至少一个 entry_zone 经 1H 收盘确认成交
        if fields.get("entry_zone_filled_confirmed_1h", False):
            return ("LONG_OPEN",
                    "LONG_PLANNED → LONG_OPEN:entry_zone 1H 收盘确认成交",
                    ["entry_zone_filled_confirmed_1h=true"])
        # 未成交 → 留守
        return None, "保持 LONG_PLANNED:trade_plan 未确认成交", []

    # ------ SHORT_PLANNED ------
    def _from_SHORT_PLANNED(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        if fields.get("entry_zone_filled_confirmed_1h", False):
            return ("SHORT_OPEN",
                    "SHORT_PLANNED → SHORT_OPEN:entry_zone 1H 收盘确认成交",
                    ["entry_zone_filled_confirmed_1h=true"])
        return None, "保持 SHORT_PLANNED:trade_plan 未确认成交", []

    # ------ LONG_OPEN ------
    def _from_LONG_OPEN(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        # 早期失败保护 → LONG_EXIT(任一触发)
        exit_matches: list[str] = []
        hours_since = _as_float(fields.get("hours_since_open")) or 0.0
        if fields.get("hard_invalidation_breached", False):
            exit_matches.append("hard_invalidation_breached=true")
        if fields.get("stop_loss_hit", False):
            exit_matches.append("stop_loss_hit=true")
        # 开仓后 12 小时内 L2 stance 翻转且 confidence ≥ 0.7
        stance_flipped = fields.get("l2_stance_flipped", False)
        stance_conf = _as_float(fields.get("l2_stance_confidence"))
        if (
            hours_since <= self._stance_flip_window
            and stance_flipped
            and stance_conf is not None
            and stance_conf >= self._stance_flip_conf_min
        ):
            exit_matches.append(
                f"stance_flip_within_{self._stance_flip_window}h "
                f"(stance_confidence={stance_conf})"
            )
        if fields.get("l4_new_critical_risk", False):
            exit_matches.append("l4_new_critical_risk=true")
        if fields.get("thesis_still_valid") == "invalidated":
            exit_matches.append("thesis_still_valid=invalidated")
        if exit_matches:
            return ("LONG_EXIT",
                    "LONG_OPEN → LONG_EXIT:早期失败保护触发",
                    exit_matches)

        # → LONG_HOLD:时间 ≥ 24h 且走势至少一条 / 或 tp1 50% 距离
        time_ok = hours_since >= self._open_min_hours
        pnl = _as_float(fields.get("floating_pnl_pct"))
        pnl_ok = pnl is not None and pnl >= self._open_pnl_threshold
        struct_ok = fields.get("crossed_first_4h_close_no_reverse", False)
        pullback_ok = fields.get("survived_pullback_rebound_cycle", False)
        structure_any = pnl_ok or struct_ok or pullback_ok

        tp1_pct = _as_float(fields.get("tp1_distance_progress_pct"))
        tp1_half = tp1_pct is not None and tp1_pct >= self._open_tp1_distance

        if (time_ok and structure_any) or tp1_half:
            matched = []
            if time_ok:
                matched.append(
                    f"hours_since_open={hours_since} ≥ {self._open_min_hours}"
                )
            if pnl_ok:
                matched.append(f"floating_pnl_pct={pnl} ≥ {self._open_pnl_threshold}")
            if struct_ok:
                matched.append("crossed_first_4h_close_no_reverse=true")
            if pullback_ok:
                matched.append("survived_pullback_rebound_cycle=true")
            if tp1_half:
                matched.append(
                    f"tp1_distance_progress_pct={tp1_pct} ≥ {self._open_tp1_distance}"
                )
            return "LONG_HOLD", "LONG_OPEN → LONG_HOLD:时间+走势条件满足", matched

        return None, "保持 LONG_OPEN:未满足 HOLD 或 EXIT 条件", []

    # ------ SHORT_OPEN ------
    def _from_SHORT_OPEN(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        # 早期失败保护(对称实现)
        exit_matches: list[str] = []
        hours_since = _as_float(fields.get("hours_since_open")) or 0.0
        if fields.get("hard_invalidation_breached", False):
            exit_matches.append("hard_invalidation_breached=true")
        if fields.get("stop_loss_hit", False):
            exit_matches.append("stop_loss_hit=true")
        stance_flipped = fields.get("l2_stance_flipped", False)
        stance_conf = _as_float(fields.get("l2_stance_confidence"))
        if (
            hours_since <= self._stance_flip_window
            and stance_flipped
            and stance_conf is not None
            and stance_conf >= self._stance_flip_conf_min
        ):
            exit_matches.append(
                f"stance_flip_within_{self._stance_flip_window}h "
                f"(stance_confidence={stance_conf})"
            )
        if fields.get("l4_new_critical_risk", False):
            exit_matches.append("l4_new_critical_risk=true")
        if fields.get("thesis_still_valid") == "invalidated":
            exit_matches.append("thesis_still_valid=invalidated")
        if exit_matches:
            return ("SHORT_EXIT",
                    "SHORT_OPEN → SHORT_EXIT:早期失败保护触发",
                    exit_matches)

        # → SHORT_HOLD(镜像)
        time_ok = hours_since >= self._open_min_hours
        pnl = _as_float(fields.get("floating_pnl_pct"))
        pnl_ok = pnl is not None and pnl >= self._open_pnl_threshold
        struct_ok = fields.get("crossed_first_4h_close_no_reverse", False)
        pullback_ok = fields.get("survived_pullback_rebound_cycle", False)
        structure_any = pnl_ok or struct_ok or pullback_ok
        tp1_pct = _as_float(fields.get("tp1_distance_progress_pct"))
        tp1_half = tp1_pct is not None and tp1_pct >= self._open_tp1_distance

        if (time_ok and structure_any) or tp1_half:
            matched = []
            if time_ok:
                matched.append(
                    f"hours_since_open={hours_since} ≥ {self._open_min_hours}"
                )
            if pnl_ok:
                matched.append(f"floating_pnl_pct={pnl} ≥ {self._open_pnl_threshold}")
            if struct_ok:
                matched.append("crossed_first_4h_close_no_reverse=true")
            if pullback_ok:
                matched.append("survived_pullback_rebound_cycle=true")
            if tp1_half:
                matched.append(
                    f"tp1_distance_progress_pct={tp1_pct} ≥ {self._open_tp1_distance}"
                )
            return "SHORT_HOLD", "SHORT_OPEN → SHORT_HOLD:时间+走势条件满足", matched

        return None, "保持 SHORT_OPEN:未满足 HOLD 或 EXIT 条件", []

    # ------ LONG_HOLD ------
    def _from_LONG_HOLD(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        # → LONG_TRIM(任一触发)
        matches: list[str] = []
        if fields.get("tp_target_hit", False):
            matches.append("tp_target_hit=true")
        phase = fields.get("ai_phase")
        phase_conf = _as_float(fields.get("ai_phase_confidence"))
        if phase == "late" and phase_conf is not None and phase_conf >= self._phase_late_conf_min:
            matches.append(
                f"ai_phase=late ∧ confidence={phase_conf} ≥ {self._phase_late_conf_min}"
            )
        if (
            fields.get("l1_regime_transitioned_from_trend_up", False)
            and fields.get("l1_regime") in {"transition_down", "range_high"}
        ):
            matches.append(
                f"l1_regime_transitioned_to {fields.get('l1_regime')}"
            )
        if fields.get("thesis_still_valid") in {"partially_valid", "weakened"}:
            matches.append(f"thesis_still_valid={fields.get('thesis_still_valid')}")
        if fields.get("l5_macro_stance") in {"risk_off", "extreme_risk_off"}:
            matches.append(f"l5_macro_stance={fields.get('l5_macro_stance')}")
        if matches:
            return "LONG_TRIM", "LONG_HOLD → LONG_TRIM:任一触发条件成立", matches
        return None, "保持 LONG_HOLD", []

    # ------ SHORT_HOLD(镜像)------
    def _from_SHORT_HOLD(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        matches: list[str] = []
        if fields.get("tp_target_hit", False):
            matches.append("tp_target_hit=true")
        phase = fields.get("ai_phase")
        phase_conf = _as_float(fields.get("ai_phase_confidence"))
        if phase == "late" and phase_conf is not None and phase_conf >= self._phase_late_conf_min:
            matches.append(
                f"ai_phase=late ∧ confidence={phase_conf} ≥ {self._phase_late_conf_min}"
            )
        if (
            fields.get("l1_regime_transitioned_from_trend_down", False)
            and fields.get("l1_regime") in {"transition_up", "range_low"}
        ):
            matches.append(
                f"l1_regime_transitioned_to {fields.get('l1_regime')}"
            )
        if fields.get("thesis_still_valid") in {"partially_valid", "weakened"}:
            matches.append(f"thesis_still_valid={fields.get('thesis_still_valid')}")
        if fields.get("l5_macro_stance") in {"risk_on", "extreme_risk_on"}:
            matches.append(f"l5_macro_stance={fields.get('l5_macro_stance')}")
        if matches:
            return "SHORT_TRIM", "SHORT_HOLD → SHORT_TRIM:任一触发条件成立", matches
        return None, "保持 SHORT_HOLD", []

    # ------ LONG_TRIM ------
    def _from_LONG_TRIM(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        # 后续三选一
        if fields.get("is_final_trim_or_exhausted", False):
            return ("LONG_EXIT",
                    "LONG_TRIM → LONG_EXIT:最后一档或衰竭",
                    ["is_final_trim_or_exhausted=true"])
        if fields.get("next_trim_triggered", False):
            return ("LONG_TRIM",
                    "LONG_TRIM → LONG_TRIM:下一档止盈",
                    ["next_trim_triggered=true"])
        if fields.get("current_trim_completed", False):
            return ("LONG_HOLD",
                    "LONG_TRIM → LONG_HOLD:完成当前减仓,剩余继续",
                    ["current_trim_completed=true"])
        return None, "保持 LONG_TRIM", []

    # ------ SHORT_TRIM ------
    def _from_SHORT_TRIM(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        if fields.get("is_final_trim_or_exhausted", False):
            return ("SHORT_EXIT",
                    "SHORT_TRIM → SHORT_EXIT:最后一档或衰竭",
                    ["is_final_trim_or_exhausted=true"])
        if fields.get("next_trim_triggered", False):
            return ("SHORT_TRIM",
                    "SHORT_TRIM → SHORT_TRIM:下一档止盈",
                    ["next_trim_triggered=true"])
        if fields.get("current_trim_completed", False):
            return ("SHORT_HOLD",
                    "SHORT_TRIM → SHORT_HOLD:完成当前减仓,剩余继续",
                    ["current_trim_completed=true"])
        return None, "保持 SHORT_TRIM", []

    # ------ LONG_EXIT ------
    def _from_LONG_EXIT(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        # → FLIP_WATCH(全部满足)
        positions_flat = not fields.get("account_has_long", False)
        l2_bearish_hint = (
            fields.get("l2_stance") == "bearish"
            or fields.get("l2_bearish_early_signal", False)
        )
        l1_regime_flip = fields.get("l1_regime") in {
            "transition_down", "trend_down", "range_high",
        }
        if positions_flat and l2_bearish_hint and l1_regime_flip:
            return ("FLIP_WATCH",
                    "LONG_EXIT → FLIP_WATCH:所有仓位已平 + L2 偏空迹象 + L1 regime 向下",
                    [
                        "positions_flat=true",
                        f"l2_stance_or_bearish_hint={fields.get('l2_stance')}",
                        f"l1_regime={fields.get('l1_regime')}",
                    ])
        # → FLAT:平仓完毕但无反手条件
        if positions_flat:
            return ("FLAT",
                    "LONG_EXIT → FLAT:仓位已清,无反手条件",
                    ["positions_flat=true", "no_flip_conditions_met"])
        return None, "保持 LONG_EXIT:仓位未清", []

    # ------ SHORT_EXIT ------
    def _from_SHORT_EXIT(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        positions_flat = not fields.get("account_has_short", False)
        l2_bullish_hint = (
            fields.get("l2_stance") == "bullish"
            or fields.get("l2_bullish_early_signal", False)
        )
        l1_regime_flip = fields.get("l1_regime") in {
            "transition_up", "trend_up", "range_low",
        }
        if positions_flat and l2_bullish_hint and l1_regime_flip:
            return ("FLIP_WATCH",
                    "SHORT_EXIT → FLIP_WATCH:所有仓位已平 + L2 偏多迹象 + L1 regime 向上",
                    [
                        "positions_flat=true",
                        f"l2_stance_or_bullish_hint={fields.get('l2_stance')}",
                        f"l1_regime={fields.get('l1_regime')}",
                    ])
        if positions_flat:
            return ("FLAT",
                    "SHORT_EXIT → FLAT:仓位已清,无反手条件",
                    ["positions_flat=true", "no_flip_conditions_met"])
        return None, "保持 SHORT_EXIT:仓位未清", []

    # ------ FLIP_WATCH ------
    def _from_FLIP_WATCH(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        hours_in = _as_float(fields.get("hours_in_flip_watch")) or 0.0
        bounds = fields.get("prev_flip_bounds") or {}
        eff_min = _as_float(bounds.get("effective_min_hours")) or self._fw_base_min
        eff_max = _as_float(bounds.get("effective_max_hours")) or self._fw_base_max

        # → FLAT(任一触发)
        flat_matches: list[str] = []
        if hours_in > eff_max:
            flat_matches.append(f"hours_in_flip_watch={hours_in} > effective_max={eff_max}")
        # L2 stance 回到 bullish 或明确 neutral(取决于前一段方向,v1:通用)
        if fields.get("l2_stance") in {"bullish", "neutral"} and (
            fields.get("prev_cycle_side", "long") == "long"
        ):
            flat_matches.append(f"l2_stance={fields.get('l2_stance')} (prev long cycle)")
        if fields.get("l1_regime") == "trend_up" and (
            fields.get("prev_cycle_side", "long") == "long"
        ):
            flat_matches.append("l1_regime_back_to_trend_up")
        if flat_matches:
            return ("FLAT", "FLIP_WATCH → FLAT:反手条件未成立/超 effective_max",
                    flat_matches)

        # → SHORT_PLANNED / LONG_PLANNED(高门槛,超过 effective_min 后)
        if hours_in < eff_min:
            return None, (
                f"保持 FLIP_WATCH:冷却中({hours_in}h < "
                f"effective_min={eff_min}h)"
            ), [f"flip_watch_cooling hours_in={hours_in} < min={eff_min}"]

        stance_conf = _as_float(fields.get("l2_stance_confidence"))
        if (
            fields.get("prev_cycle_side") == "long"
            and fields.get("l2_stance") == "bearish"
            and stance_conf is not None
            and stance_conf >= self._short_min
            and fields.get("long_thesis_invalidated", False)
            and fields.get("l3_grade") in {"A", "B"}
        ):
            return ("SHORT_PLANNED",
                    "FLIP_WATCH → SHORT_PLANNED:已过冷却,原多头论点失效,空头高门槛满足",
                    [
                        f"hours_in={hours_in} ≥ effective_min={eff_min}",
                        f"l2_stance=bearish,confidence={stance_conf}",
                        "long_thesis_invalidated=true",
                        f"l3_grade={fields.get('l3_grade')}",
                    ])
        if (
            fields.get("prev_cycle_side") == "short"
            and fields.get("l2_stance") == "bullish"
            and stance_conf is not None
            and stance_conf >= self._long_min
            and fields.get("short_thesis_invalidated", False)
            and fields.get("l3_grade") in {"A", "B"}
        ):
            return ("LONG_PLANNED",
                    "FLIP_WATCH → LONG_PLANNED:已过冷却,原空头论点失效,多头高门槛满足",
                    [
                        f"hours_in={hours_in} ≥ effective_min={eff_min}",
                        f"l2_stance=bullish,confidence={stance_conf}",
                        "short_thesis_invalidated=true",
                        f"l3_grade={fields.get('l3_grade')}",
                    ])
        return None, "保持 FLIP_WATCH:已过冷却但反手条件不全", []

    # ------ PROTECTION ------
    def _from_PROTECTION(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        # → POST_PROTECTION_REASSESS:事件结束 + 数据健康 + 无新极端风险
        event_over = fields.get("extreme_event_ended", False)
        data_healthy = fields.get("data_health_ok", True)
        no_new_extreme = not _protection_triggered(fields)
        if event_over and data_healthy and no_new_extreme:
            return ("POST_PROTECTION_REASSESS",
                    "PROTECTION → POST_PROTECTION_REASSESS:事件结束 + 数据健康 + 无新极端风险",
                    [
                        "extreme_event_ended=true",
                        "data_health_ok=true",
                        "no_new_extreme_event",
                    ])
        return None, "保持 PROTECTION:仍在极端事件中", []

    # ------ POST_PROTECTION_REASSESS ------
    def _from_POST_PROTECTION_REASSESS(
        self, fields: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        # 强制持续至少一个 4H 周期
        hours_in = _as_float(fields.get("hours_in_post_protection_reassess")) or 0.0
        if hours_in < self._ppr_min_hold_hours:
            return (None,
                    f"保持 POST_PROTECTION_REASSESS:强制持续至少 "
                    f"{self._ppr_min_hold_hours}h(当前 {hours_in}h)",
                    [f"min_hold_hours={self._ppr_min_hold_hours}"])

        # 允许白名单:{LONG_HOLD, SHORT_HOLD, LONG_EXIT, SHORT_EXIT, FLAT, FLIP_WATCH}
        target = fields.get("post_protection_next_target")
        if target in _PPR_ALLOWED_TARGETS:
            return (target,
                    f"POST_PROTECTION_REASSESS → {target}:外部调度指定",
                    [f"post_protection_next_target={target}"])
        # 不允许 PLANNED(§5.2)— 外部指定被拒时保持本态
        if target in _PLANNED_STATES:
            return (None,
                    f"拒绝迁移到 {target}:POST_PROTECTION_REASSESS 禁止进入 PLANNED",
                    ["refused_planned_target"])
        return None, "保持 POST_PROTECTION_REASSESS:未指定合法 next_target", []


# ============================================================
# 辅助函数
# ============================================================

class DisciplineViolation(Exception):
    """三条核心纪律违反 → 抛此异常(§5.4)。"""
    pass


def _verify_disciplines(prev_state: str, target: str) -> list[str]:
    """
    §5.4 三条核心纪律:
      1. 不允许从 *_HOLD 直接跳到反向 PLANNED(必须经 EXIT → FLIP_WATCH)
      2. FLIP_WATCH 冷却期强制(由 _from_FLIP_WATCH 内部 eff_min 校验)
      3. PROTECTION 唯一出口经 POST_PROTECTION_REASSESS(本函数校验)

    注:纪律 2 是内部 hours_in 校验,落在 _from_FLIP_WATCH 不会产出违纪路径;
    纪律 1/3 在此用白名单统一拦截。
    """
    violations: list[str] = []

    # 纪律 1:HOLD 不能直跳反向 PLANNED
    if prev_state == "LONG_HOLD" and target == "SHORT_PLANNED":
        violations.append(
            "discipline_1_violated: LONG_HOLD → SHORT_PLANNED "
            "(必须经 LONG_EXIT → FLIP_WATCH)"
        )
    if prev_state == "SHORT_HOLD" and target == "LONG_PLANNED":
        violations.append(
            "discipline_1_violated: SHORT_HOLD → LONG_PLANNED "
            "(必须经 SHORT_EXIT → FLIP_WATCH)"
        )

    # 纪律 3:PROTECTION 只能出到 POST_PROTECTION_REASSESS
    if prev_state == "PROTECTION" and target not in {
        "PROTECTION", "POST_PROTECTION_REASSESS",
    }:
        violations.append(
            f"discipline_3_violated: PROTECTION → {target} "
            "(唯一出口经 POST_PROTECTION_REASSESS)"
        )

    # 纪律 3 推论:POST_PROTECTION_REASSESS 不得回 PROTECTION
    if prev_state == "POST_PROTECTION_REASSESS" and target == "PROTECTION":
        violations.append(
            "discipline_3_violated: POST_PROTECTION_REASSESS → PROTECTION "
            "(禁止直接回 PROTECTION,复发走正常流程)"
        )

    # 纪律 3 推论:POST_PROTECTION_REASSESS 不得进入任何 PLANNED
    if prev_state == "POST_PROTECTION_REASSESS" and target in _PLANNED_STATES:
        violations.append(
            f"discipline_3_violated: POST_PROTECTION_REASSESS → {target} "
            "(禁止迁移到 PLANNED,必须先 FLAT 重新规划)"
        )

    return violations


def _protection_triggered(fields: dict[str, Any]) -> bool:
    """§5.2 PROTECTION 进入:极端事件 / Fallback L3 / 其他 protection_trigger。"""
    if fields.get("l5_extreme_event_detected", False):
        return True
    fl = fields.get("fallback_level")
    if fl is not None:
        try:
            if int(fl) >= 3:
                return True
        except (TypeError, ValueError):
            pass
    if fields.get("protection_trigger_external", False):
        return True
    return False


def _build_field_snapshot(
    *,
    strategy_state: dict[str, Any],
    account_state: dict[str, Any],
    prev_state: str,
    prev_entered_at: Optional[str],
    prev_flip_bounds: Optional[dict[str, Any]],
    now_utc: str,
) -> dict[str, Any]:
    """
    把 strategy_state / account_state 扁平化成迁移逻辑消费的字段字典。
    字段缺失 → None,迁移逻辑保守为 False。
    """
    l1 = _get_layer(strategy_state, "layer_1")
    l2 = _get_layer(strategy_state, "layer_2")
    l3 = _get_layer(strategy_state, "layer_3")
    l4 = _get_layer(strategy_state, "layer_4")
    l5 = _get_layer(strategy_state, "layer_5")
    cp = ((strategy_state.get("composite_factors") or {}).get("cycle_position") or {})
    trade_plan = strategy_state.get("trade_plan") or {}
    lifecycle = strategy_state.get("lifecycle") or {}
    macro_events = strategy_state.get("macro_events") or {}

    mins_since_entered = _minutes_between(prev_entered_at, now_utc)
    hours_since_entered = (
        mins_since_entered / 60.0 if mins_since_entered is not None else None
    )

    fields = {
        # ---- L1 ----
        "l1_regime": l1.get("regime") or l1.get("regime_primary"),
        "volatility_regime": (
            l1.get("volatility_regime") or l1.get("volatility_level")
        ),
        "l1_regime_transitioned_from_trend_up": bool(
            l1.get("regime_transitioned_from_trend_up", False)
        ),
        "l1_regime_transitioned_from_trend_down": bool(
            l1.get("regime_transitioned_from_trend_down", False)
        ),

        # ---- L2 ----
        "l2_stance": l2.get("stance"),
        "l2_stance_confidence": l2.get("stance_confidence"),
        "l2_stance_flipped": bool(l2.get("stance_flipped", False)),
        "l2_bearish_early_signal": bool(l2.get("bearish_early_signal", False)),
        "l2_bullish_early_signal": bool(l2.get("bullish_early_signal", False)),

        # ---- L3 ----
        "l3_grade": l3.get("opportunity_grade") or l3.get("grade"),
        "l3_permission": l3.get("execution_permission"),

        # ---- L4 ----
        "l4_overall_risk": (
            l4.get("overall_risk_level") or l4.get("overall_risk")
        ),
        "l4_new_critical_risk": bool(l4.get("new_critical_risk", False)),
        "hard_invalidation_breached": bool(
            l4.get("hard_invalidation_breached", False)
        ),

        # ---- L5 ----
        "l5_macro_stance": l5.get("macro_stance") or l5.get("macro_environment"),
        "l5_extreme_event_detected": bool(
            l5.get("extreme_event_detected", False)
        ),

        # ---- 组合因子 ----
        "cycle_position": (
            cp.get("cycle_position") or cp.get("band")
        ),

        # ---- trade_plan / lifecycle / AI verdict ----
        "entry_zone_filled_confirmed_1h": bool(
            trade_plan.get("entry_zone_filled_confirmed_1h", False)
            or lifecycle.get("entry_zone_filled_confirmed_1h", False)
        ),
        "stop_loss_hit": bool(
            trade_plan.get("stop_loss_hit", False)
            or lifecycle.get("stop_loss_hit", False)
        ),
        "tp_target_hit": bool(
            trade_plan.get("tp_target_hit", False)
            or lifecycle.get("tp_target_hit", False)
        ),
        "floating_pnl_pct": lifecycle.get("floating_pnl_pct"),
        "tp1_distance_progress_pct": lifecycle.get("tp1_distance_progress_pct"),
        "crossed_first_4h_close_no_reverse": bool(
            lifecycle.get("crossed_first_4h_close_no_reverse", False)
        ),
        "survived_pullback_rebound_cycle": bool(
            lifecycle.get("survived_pullback_rebound_cycle", False)
        ),
        "hours_since_open": lifecycle.get("hours_since_open"),
        "thesis_still_valid": lifecycle.get("thesis_still_valid")
        or (strategy_state.get("adjudicator") or {}).get("thesis_still_valid"),
        "ai_phase": lifecycle.get("ai_phase")
        or (strategy_state.get("adjudicator") or {}).get("phase"),
        "ai_phase_confidence": lifecycle.get("ai_phase_confidence")
        or (strategy_state.get("adjudicator") or {}).get("phase_confidence"),
        "current_trim_completed": bool(
            lifecycle.get("current_trim_completed", False)
        ),
        "next_trim_triggered": bool(
            lifecycle.get("next_trim_triggered", False)
        ),
        "is_final_trim_or_exhausted": bool(
            lifecycle.get("is_final_trim_or_exhausted", False)
        ),
        "long_thesis_invalidated": bool(
            lifecycle.get("long_thesis_invalidated", False)
        ),
        "short_thesis_invalidated": bool(
            lifecycle.get("short_thesis_invalidated", False)
        ),
        "prev_cycle_side": lifecycle.get("prev_cycle_side"),

        # ---- 极端事件 / PROTECTION / Fallback ----
        "fallback_level": (
            (strategy_state.get("pipeline_meta") or {}).get("fallback_level")
        ),
        "protection_trigger_external": bool(
            macro_events.get("protection_trigger", False)
        ),
        "extreme_event_ended": bool(
            macro_events.get("extreme_event_ended", False)
        ),
        "data_health_ok": bool(
            (strategy_state.get("pipeline_meta") or {}).get("data_health_ok", True)
        ),

        # ---- POST_PROTECTION_REASSESS ----
        "post_protection_next_target": lifecycle.get("post_protection_next_target"),

        # ---- 账户 ----
        "account_has_long": bool(
            (account_state.get("long_position_size") or 0) > 0
        ),
        "account_has_short": bool(
            (account_state.get("short_position_size") or 0) > 0
        ),

        # ---- Protection mode ----
        "protection_mode": bool(strategy_state.get("protection_mode", False)),
    }

    # 持续时间相关
    if prev_state == "FLIP_WATCH":
        fields["hours_in_flip_watch"] = hours_since_entered
        fields["prev_flip_bounds"] = prev_flip_bounds
    if prev_state == "POST_PROTECTION_REASSESS":
        fields["hours_in_post_protection_reassess"] = hours_since_entered

    return fields


def _extract_prev(
    record: Optional[dict[str, Any]],
) -> tuple[Optional[str], Optional[str], Optional[dict[str, Any]]]:
    """从上一条 strategy_state_history 行抽出 state_machine 子块。"""
    if not record:
        return None, None, None
    state = record.get("state") if isinstance(record.get("state"), dict) else record
    sm = (state or {}).get("state_machine") or {}
    return (
        sm.get("current_state"),
        sm.get("state_entered_at_utc"),
        sm.get("flip_watch_bounds"),
    )


def _get_layer(state: dict[str, Any], key: str) -> dict[str, Any]:
    """优先顶层 state[key],次 state.evidence_reports[key]。"""
    if isinstance(state.get(key), dict):
        return state[key]
    er = state.get("evidence_reports") or {}
    if isinstance(er.get(key), dict):
        return er[key]
    return {}


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@lru_cache(maxsize=4)
def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
