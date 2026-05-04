"""lifecycle_manager.py — Sprint 1.5b-B Lifecycle 本体。

建模 §5.5 状态进入副作用 + §7.2 Block 6 lifecycle + §8.2 StrategyLifecycle。

两阶段 API(对齐 state_builder 在 state_machine 之前 / 之后两次调用):
  compute_pre_sm   — 在 state_machine.compute_next 之前跑;只更新"度量"字段
                     (PnL / 持仓时长 / TP hit 等),不做状态过渡相关动作。
                     这样 state_machine_inputs.build_state_machine_fields 能从
                     lifecycle 读到真实 floating_pnl_pct / hours_held / tp_target_hit /
                     current_trim_completed。
  compute_post_sm  — 在 state_machine.compute_next 之后跑;按 prev → current 过渡
                     做"状态过渡副作用"(创建草稿 / 转 active / 追加 trim 记录 /
                     归档等)。

返回 dict 写入 strategy_state["lifecycle"]。FLAT(stable) / FLIP_WATCH(stable)
等"无活跃 lifecycle"场景返回 None / 空 dict。

v1 简化(留给后续 sprint 改进):
  - position_adjustments 只追加,不做加仓加权(v1 假定一次性按 average_entry_price 入场)
  - final_outcome_type 简化 4 类(A_perfect / B_good_suboptimal / F_wrong_but_stopped /
    G_wrong_late_stop),建模 §8.3 的 10+ 类留 v1.x 复盘工具细化
  - lifecycles 表落库:本 sprint 只写 strategy_runs.full_state_json.lifecycle;
    /api/lifecycle/* 改造留 1.5b-C
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd


logger = logging.getLogger(__name__)


_BJT = ZoneInfo("Asia/Shanghai")


_LONG_STATES: frozenset[str] = frozenset({
    "LONG_PLANNED", "LONG_OPEN", "LONG_HOLD", "LONG_TRIM", "LONG_EXIT",
})
_SHORT_STATES: frozenset[str] = frozenset({
    "SHORT_PLANNED", "SHORT_OPEN", "SHORT_HOLD", "SHORT_TRIM", "SHORT_EXIT",
})
_PLANNED_STATES: frozenset[str] = frozenset({"LONG_PLANNED", "SHORT_PLANNED"})
_OPEN_STATES: frozenset[str] = frozenset({"LONG_OPEN", "SHORT_OPEN"})
_HOLD_STATES: frozenset[str] = frozenset({"LONG_HOLD", "SHORT_HOLD"})
_TRIM_STATES: frozenset[str] = frozenset({"LONG_TRIM", "SHORT_TRIM"})
_EXIT_STATES: frozenset[str] = frozenset({"LONG_EXIT", "SHORT_EXIT"})
_HOLDING_STATES: frozenset[str] = (
    _OPEN_STATES | _HOLD_STATES | _TRIM_STATES | _EXIT_STATES
)


class LifecycleManager:
    """建模 §5.5 + §7.2 Block 6 + §8.2 lifecycle 本体。"""

    def __init__(
        self,
        conn: Optional[Any] = None,
        *,
        planned_expiry_hours: float = 72.0,
    ) -> None:
        # Sprint 1.5b-C:conn 用于 LifecyclesDAO upsert。conn=None 时(单测 / dry-run)
        # 不写表,仅返回 in-memory dict
        self.conn = conn
        self._planned_expiry_hours = planned_expiry_hours

    # ------------------------------------------------------------------
    # Public:两阶段入口
    # ------------------------------------------------------------------

    def compute_pre_sm(
        self,
        *,
        prev_state: Optional[str],
        prev_lifecycle: Optional[dict[str, Any]],
        strategy_state: dict[str, Any],
        context: dict[str, Any],
        now_utc: str,
    ) -> Optional[dict[str, Any]]:
        """在 state_machine.compute_next 之前跑。

        只更新 hours_held / current_floating_pnl_pct / max_favorable_pct /
        max_adverse_pct / tp_history(仅追加新命中)/ tp_target_hit_this_run /
        current_trim_completed 等度量字段。

        prev_lifecycle is None / 占位 / status="closed" → 返回 None(无活跃 lc)。
        """
        if not _is_active_lifecycle(prev_lifecycle):
            return None

        lc = dict(prev_lifecycle)  # 浅 copy
        direction = lc.get("direction")
        klines_1h = context.get("klines_1h")
        klines_1d = context.get("klines_1d")

        # ---- 持仓时长 ----
        origin_iso = lc.get("origin_time_utc")
        if origin_iso:
            lc["hours_held"] = _hours_between(origin_iso, now_utc)

        # ---- 浮盈 ----
        avg_entry = _as_float(lc.get("average_entry_price"))
        last_price = _last_close(klines_1h)
        if avg_entry and last_price and direction:
            pnl = (
                (last_price - avg_entry) / avg_entry * 100.0
                if direction == "long"
                else (avg_entry - last_price) / avg_entry * 100.0
            )
            lc["current_floating_pnl_pct"] = pnl
            # 极值只单调更新
            mfav = _as_float(lc.get("max_favorable_pct"))
            lc["max_favorable_pct"] = max(mfav, pnl) if mfav is not None else pnl
            madv = _as_float(lc.get("max_adverse_pct"))
            lc["max_adverse_pct"] = min(madv, pnl) if madv is not None else min(0.0, pnl)

        # ---- TP hit 检测(*_HOLD/*_TRIM 阶段都查;命中追加 tp_history)----
        if prev_state in (_HOLD_STATES | _TRIM_STATES):
            new_hits = self._detect_tp_hits(
                trade_plan=strategy_state.get("trade_plan") or {},
                klines_1d=klines_1d,
                direction=direction,
                tp_history=lc.get("tp_history") or [],
                now_utc=now_utc,
                run_id=strategy_state.get("run_id"),
            )
            if new_hits:
                history = list(lc.get("tp_history") or [])
                history.extend(new_hits)
                lc["tp_history"] = history
            lc["tp_target_hit_this_run"] = bool(new_hits)
        else:
            lc["tp_target_hit_this_run"] = False

        # ---- open_phase 4 个 bool(LONG_OPEN/SHORT_OPEN 阶段稳定积累)----
        hours_held = _as_float(lc.get("hours_held")) or 0.0
        mfav = _as_float(lc.get("max_favorable_pct"))
        madv = _as_float(lc.get("max_adverse_pct"))
        lc["open_phase_min_time_reached"] = hours_held >= 24.0
        lc["open_phase_pnl_confirmed"] = bool(mfav is not None and mfav >= 2.0)
        # v1 简化:hours_held >= 4 视为 structure_confirmed
        structure_ok = hours_held >= 4.0
        lc["open_phase_structure_confirmed"] = structure_ok
        # state_machine.py 读 lifecycle.crossed_first_4h_close_no_reverse(同义别名)
        lc["crossed_first_4h_close_no_reverse"] = structure_ok
        # v1 简化:经历过 -1% 以下回撤后回正 +2%
        pullback_ok = bool(
            madv is not None and madv <= -1.0
            and mfav is not None and mfav >= 2.0
        )
        lc["open_phase_pullback_survived"] = pullback_ok
        lc["survived_pullback_rebound_cycle"] = pullback_ok

        # ---- current_trim_completed:本次 run 进入 *_TRIM 算"未完成";
        #      *_TRIM 持有 24h 后 + position_adjustments 有 trim 记录 → 完成 ----
        if prev_state in _TRIM_STATES:
            adjustments = lc.get("position_adjustments") or []
            has_trim = any(
                a.get("adjustment_type") == "trim" for a in adjustments
            )
            lc["current_trim_completed"] = has_trim and hours_held >= 24.0
        else:
            lc["current_trim_completed"] = False

        # ---- thesis 透传(adjudicator 实时输出,lc 镜像)----
        adj = strategy_state.get("adjudicator") or {}
        thesis_assess = adj.get("thesis_assessment") or {}
        thesis = (
            adj.get("thesis_still_valid")
            or thesis_assess.get("thesis_still_valid")
        )
        if thesis:
            lc["thesis_still_valid"] = thesis
        note = thesis_assess.get("validity_note") or thesis_assess.get("note")
        if note:
            lc["thesis_validity_note"] = note

        return lc

    def compute_post_sm(
        self,
        *,
        prev_state: Optional[str],
        current_state: str,
        lifecycle: Optional[dict[str, Any]],
        strategy_state: dict[str, Any],
        context: dict[str, Any],
        run_id: str,
        now_utc: str,
    ) -> Optional[dict[str, Any]]:
        """在 state_machine.compute_next 之后跑;按 prev → current 过渡做副作用。

        Sprint 1.5b-C:产出非 None 时,自动 upsert 到 lifecycles 表(conn 可用时)。

        Returns:
          - dict — 当前活跃 lifecycle(包含本次 run 完成的过渡)
          - None — FLAT(stable / 归档完成)/ FLIP_WATCH(stable)无活跃 lc 期
        """
        result = self._dispatch_post_sm(
            prev_state=prev_state, current_state=current_state,
            lifecycle=lifecycle, strategy_state=strategy_state,
            context=context, run_id=run_id, now_utc=now_utc,
        )
        if result is not None and self.conn is not None:
            try:
                from ..data.storage.dao import LifecyclesDAO
                LifecyclesDAO.upsert_lifecycle(self.conn, result)
            except Exception as e:
                logger.warning(
                    "LifecyclesDAO.upsert_lifecycle failed (non-fatal): %s", e,
                )
        return result

    def _dispatch_post_sm(
        self,
        *,
        prev_state: Optional[str],
        current_state: str,
        lifecycle: Optional[dict[str, Any]],
        strategy_state: dict[str, Any],
        context: dict[str, Any],
        run_id: str,
        now_utc: str,
    ) -> Optional[dict[str, Any]]:
        """compute_post_sm 的内部分派(纯逻辑,不触 DB)。"""
        # FLAT(无任何过渡):没有活跃 lc
        if current_state == "FLAT" and prev_state in (None, "FLAT"):
            return None

        # FLAT → *_PLANNED 或 FLIP_WATCH → *_PLANNED(反向切换):创建 pending_open 草稿
        if (
            prev_state in (None, "FLAT", "FLIP_WATCH", "POST_PROTECTION_REASSESS")
            and current_state in _PLANNED_STATES
        ):
            return self._create_pending_lifecycle(
                current_state=current_state,
                strategy_state=strategy_state,
                run_id=run_id,
                now_utc=now_utc,
            )

        # *_PLANNED(stable):保留 pending_open(只更 status_age 度量)
        if prev_state == current_state and current_state in _PLANNED_STATES:
            return lifecycle  # pre_sm 不会进这里(_is_active_lifecycle 里 pending_open 判 active),
                              # 走 pre_sm 已经 mutate 过的 dict

        # *_PLANNED → *_OPEN:激活
        if prev_state in _PLANNED_STATES and current_state in _OPEN_STATES:
            return self._activate_lifecycle(
                lifecycle=lifecycle,
                current_state=current_state,
                strategy_state=strategy_state,
                context=context,
                run_id=run_id,
                now_utc=now_utc,
            )

        # *_OPEN → *_HOLD / *_HOLD → *_TRIM / *_TRIM → *_HOLD / 等持仓内部过渡
        if prev_state in _HOLDING_STATES and current_state in _HOLDING_STATES:
            return self._update_holding_transition(
                lifecycle=lifecycle,
                prev_state=prev_state,
                current_state=current_state,
                strategy_state=strategy_state,
                run_id=run_id,
                now_utc=now_utc,
            )

        # 持仓 → FLAT / FLIP_WATCH:归档(close)
        if prev_state in _HOLDING_STATES and current_state in {"FLAT", "FLIP_WATCH"}:
            return self._archive_lifecycle(
                lifecycle=lifecycle,
                prev_state=prev_state,
                current_state=current_state,
                strategy_state=strategy_state,
                run_id=run_id,
                now_utc=now_utc,
            )

        # *_PLANNED → FLAT(planned 但条件失效):草稿丢弃
        if prev_state in _PLANNED_STATES and current_state == "FLAT":
            return None

        # FLIP_WATCH(stable):无活跃 lc
        if current_state == "FLIP_WATCH":
            return None

        # PROTECTION:保留上一个 lc,标记 protection_active
        if current_state == "PROTECTION":
            if not _is_active_lifecycle(lifecycle):
                return None
            lc = dict(lifecycle)
            lc["protection_active"] = True
            return lc

        # POST_PROTECTION_REASSESS:lc 保留,stage=reassess
        if current_state == "POST_PROTECTION_REASSESS":
            if not _is_active_lifecycle(lifecycle):
                return None
            lc = dict(lifecycle)
            lc["stage"] = "reassess"
            lc["protection_active"] = False
            return lc

        # 其他场景(POST_PROTECTION_REASSESS → FLAT 等):归档
        if prev_state == "POST_PROTECTION_REASSESS" and current_state == "FLAT":
            if _is_active_lifecycle(lifecycle):
                return self._archive_lifecycle(
                    lifecycle=lifecycle, prev_state=prev_state,
                    current_state=current_state,
                    strategy_state=strategy_state, run_id=run_id,
                    now_utc=now_utc,
                )
            return None

        # 默认:保留传入 lifecycle(degraded path)
        return lifecycle

    # ------------------------------------------------------------------
    # 内部:状态过渡 helper
    # ------------------------------------------------------------------

    def _create_pending_lifecycle(
        self, *, current_state: str, strategy_state: dict[str, Any],
        run_id: str, now_utc: str,
    ) -> dict[str, Any]:
        direction = "long" if current_state in _LONG_STATES else "short"
        adj = strategy_state.get("adjudicator") or {}
        narrative = adj.get("narrative") or ""
        rationale = adj.get("rationale") or (
            adj.get("trade_plan") or {}
        ).get("rationale") or ""
        # 取前 500 字符作为 origin_thesis(不可变)
        origin_thesis = (narrative or rationale or "")[:500]

        try:
            expiry = (
                _parse_iso(now_utc)
                + timedelta(hours=self._planned_expiry_hours)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            expiry = None

        return {
            "lifecycle_id": str(uuid.uuid4()),
            "status": "pending_open",
            "direction": direction,
            "stage": "planned",
            "origin_run_id": run_id,
            "origin_thesis": origin_thesis,
            "origin_thesis_run_id": run_id,
            "planned_at_utc": now_utc,
            "planned_at_bjt": _to_bjt(now_utc),
            "planned_expiry_utc": expiry,
            "origin_time_utc": None,
            "origin_time_bjt": None,
            "average_entry_price": None,
            "current_floating_pnl_pct": None,
            "max_favorable_pct": None,
            "max_adverse_pct": None,
            "hours_held": 0.0,
            "thesis_still_valid": "fully_valid",
            "thesis_validity_note": None,
            "position_adjustments": [],
            "cumulative_trim_pct": 0.0,
            "tp_history": [],
            "tp_target_hit_this_run": False,
            "open_phase_min_time_reached": False,
            "open_phase_pnl_confirmed": False,
            "open_phase_structure_confirmed": False,
            "open_phase_pullback_survived": False,
            "current_trim_completed": False,
            "ai_models_used_in_lifecycle": _initial_ai_models(strategy_state),
            "rules_versions_used": _initial_rules_versions(strategy_state),
            "protection_active": False,
            "protection_event_summary": None,
        }

    def _activate_lifecycle(
        self, *, lifecycle: Optional[dict[str, Any]],
        current_state: str, strategy_state: dict[str, Any],
        context: dict[str, Any], run_id: str, now_utc: str,
    ) -> dict[str, Any]:
        """*_PLANNED → *_OPEN:计算 average_entry_price,标记 active。"""
        lc = dict(lifecycle) if lifecycle else self._create_pending_lifecycle(
            current_state=current_state, strategy_state=strategy_state,
            run_id=run_id, now_utc=now_utc,
        )
        direction = "long" if current_state in _LONG_STATES else "short"
        avg_entry = _compute_average_entry_price(
            trade_plan=strategy_state.get("trade_plan") or {},
            klines_1h=context.get("klines_1h"),
            direction=direction,
        )

        lc["status"] = "active"
        lc["stage"] = "just_opened"
        lc["direction"] = direction
        lc["origin_time_utc"] = now_utc
        lc["origin_time_bjt"] = _to_bjt(now_utc)
        lc["average_entry_price"] = avg_entry
        lc["hours_held"] = 0.0
        lc["current_floating_pnl_pct"] = 0.0
        lc["max_favorable_pct"] = 0.0
        lc["max_adverse_pct"] = 0.0
        # position_adjustments 追加 open
        adjustments = list(lc.get("position_adjustments") or [])
        adjustments.append({
            "at_utc": now_utc,
            "at_bjt": _to_bjt(now_utc),
            "adjustment_type": "open",
            "size_pct_of_total": 100.0,
            "price": avg_entry,
            "reason": f"{current_state} 入场:trade_plan.entry_zones 1H 收盘确认",
            "related_run_id": run_id,
        })
        lc["position_adjustments"] = adjustments
        lc["cumulative_trim_pct"] = 0.0
        return lc

    def _update_holding_transition(
        self, *, lifecycle: Optional[dict[str, Any]],
        prev_state: str, current_state: str,
        strategy_state: dict[str, Any], run_id: str, now_utc: str,
    ) -> dict[str, Any]:
        """*_OPEN → *_HOLD / *_HOLD → *_TRIM / *_TRIM → *_HOLD / *_HOLD → *_EXIT。"""
        lc = dict(lifecycle) if lifecycle else {}

        # *_OPEN → *_HOLD:stage="holding",锁定 open_phase 4 bool 不再变
        if prev_state in _OPEN_STATES and current_state in _HOLD_STATES:
            lc["stage"] = "holding"
            return lc

        # *_HOLD → *_TRIM:追加 trim 记录
        if prev_state in _HOLD_STATES and current_state in _TRIM_STATES:
            lc["stage"] = "partial_trimmed"
            adjustments = list(lc.get("position_adjustments") or [])
            tp_idx = len([a for a in adjustments if a.get("adjustment_type") == "trim"])
            trim_size = _next_trim_size_pct(
                strategy_state.get("trade_plan") or {}, tp_idx,
            )
            tp_price = _next_tp_target_price(
                strategy_state.get("trade_plan") or {}, tp_idx,
            )
            adjustments.append({
                "at_utc": now_utc,
                "at_bjt": _to_bjt(now_utc),
                "adjustment_type": "trim",
                "size_pct_of_total": trim_size,
                "price": tp_price,
                "reason": f"{prev_state} → {current_state}:TP{tp_idx + 1} 触发减仓",
                "related_run_id": run_id,
            })
            lc["position_adjustments"] = adjustments
            lc["cumulative_trim_pct"] = (
                _as_float(lc.get("cumulative_trim_pct")) or 0.0
            ) + trim_size
            return lc

        # *_TRIM → *_HOLD:trim 执行完毕回 hold
        if prev_state in _TRIM_STATES and current_state in _HOLD_STATES:
            lc["stage"] = "holding"
            lc["current_trim_completed"] = False  # reset for next round
            return lc

        # *_HOLD/_TRIM/_OPEN → *_EXIT:进入退出准备
        if current_state in _EXIT_STATES:
            lc["stage"] = "preparing_exit"
            adjustments = list(lc.get("position_adjustments") or [])
            adjustments.append({
                "at_utc": now_utc,
                "at_bjt": _to_bjt(now_utc),
                "adjustment_type": "exit",
                "size_pct_of_total": max(
                    0.0,
                    100.0 - (_as_float(lc.get("cumulative_trim_pct")) or 0.0),
                ),
                "price": _last_close(strategy_state.get("market_snapshot")) or None,
                "reason": f"{prev_state} → {current_state}:进入退出",
                "related_run_id": run_id,
            })
            lc["position_adjustments"] = adjustments
            return lc

        # 其他持仓内部 stable:lc 不变
        return lc

    def _archive_lifecycle(
        self, *, lifecycle: dict[str, Any], prev_state: Optional[str],
        current_state: str, strategy_state: dict[str, Any],
        run_id: str, now_utc: str,
    ) -> dict[str, Any]:
        """*_EXIT → FLAT / FLIP_WATCH:归档 lifecycle,推 final_outcome_type。

        Sprint 1.10-L commit 5(P0 #2 方案 5A):同时调 thesis_manager.close_thesis
        关闭对应 active thesis(若仍在 active);commit 6 改 channel 为函数计算。
        """
        lc = dict(lifecycle)
        lc["status"] = "closed"
        lc["stage"] = "closed"
        lc["exit_time_utc"] = now_utc
        lc["exit_time_bjt"] = _to_bjt(now_utc)
        lc["exit_run_id"] = run_id
        # Sprint 1.5b-C:archive 时把 direction 镜像到 prev_cycle_side,
        # 让 state_machine FLIP_WATCH → *_PLANNED 路径能读到
        if lc.get("direction") in {"long", "short"}:
            lc["prev_cycle_side"] = lc["direction"]

        # realized_pnl_pct:用 max_favorable / max_adverse 简化推断
        # v1:用 current_floating_pnl_pct(归档时的最新值)作为兑现 PnL
        realized = _as_float(lc.get("current_floating_pnl_pct")) or 0.0
        lc["realized_pnl_pct"] = realized
        lc["final_outcome_type"] = _classify_outcome(realized)

        # Sprint 1.10-L commit 5(P0 #2 方案 5A):接通 thesis_manager.close_thesis
        self._close_active_thesis_for_archive(
            strategy_state=strategy_state, run_id=run_id, now_utc=now_utc,
        )
        return lc

    def _close_active_thesis_for_archive(
        self, *, strategy_state: dict[str, Any], run_id: str, now_utc: str,
    ) -> Optional[dict[str, Any]]:
        """Sprint 1.10-L commit 5 §X(P0 #2 方案 5A):
        lifecycle 归档时同时关闭对应 active thesis(若仍 active)。

        - self.conn 必须存在(ThesesDAO 调用)
        - ThesesDAO.get_active 返 None → noop(已被先 close,thesis_manager 幂等也兜底)
        - close_thesis 默认 reason='invalidated' + channel='B'(commit 6 改函数调用)
        - 静默捕获异常(归档主路径不能因 thesis close 失败崩溃)

        Returns: close_thesis 的返回 dict,或 None(noop / 失败)。
        """
        if self.conn is None:
            return None
        try:
            import uuid
            from src.data.storage.dao import (
                ThesesDAO, VirtualAccountDAO,
            )
            from src.strategy import thesis_manager

            active = ThesesDAO.get_active(self.conn)
            if active is None:
                return None  # 已被先 close,自然 noop

            # current_btc 从 strategy_state.market_snapshot 取
            market_snapshot = (strategy_state or {}).get("market_snapshot") or {}
            current_btc = _as_float(market_snapshot.get("btc_price_usd")) or 0.0
            if current_btc <= 0:
                return None  # 极边界:无价 → 跳过(留 hard_invalidation 主路径)

            # initial_capital 从 first virtual_account snapshot 读
            first_snap = VirtualAccountDAO.get_latest(self.conn)
            initial_capital = float(
                (first_snap or {}).get("initial_capital") or 100000.0
            )

            # Sprint 1.10-L commit 6:close_channel 改 determine_close_channel
            # 4 条件分级(§4.3.3)— 从 strategy_state 提取 L1/L2/L5 信号
            from src.strategy.cooldown_manager import determine_close_channel
            channel = determine_close_channel(
                close_reason="invalidated",
                **_extract_4_conditions(strategy_state, active.get("direction")),
            )

            snapshot_id = f"lc_archive_{uuid.uuid4().hex[:12]}"
            return thesis_manager.close_thesis(
                self.conn,
                thesis_id=active["thesis_id"],
                reason="invalidated",
                close_channel=channel,       # commit 6:函数计算(原写死 'B')
                closed_at_utc=now_utc,
                fills_for_close=[],          # 归档无新 fill
                current_btc_price=current_btc,
                initial_capital=initial_capital,
                snapshot_id=snapshot_id,
                run_id=run_id,
                snapshot_at_utc=now_utc,
                invalidated_reason=(
                    "lifecycle_archive_via_state_machine_*_HOLDING_to_FLAT_or_FLIP_WATCH"
                ),
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "lifecycle_archive close_active_thesis 失败(noop): %s", e,
            )
            return None

    def _detect_tp_hits(
        self, *, trade_plan: dict[str, Any], klines_1d: Any,
        direction: Optional[str], tp_history: list[dict[str, Any]],
        now_utc: str, run_id: Optional[str],
    ) -> list[dict[str, Any]]:
        if direction is None:
            return []
        plan = trade_plan.get("take_profit_plan") or trade_plan.get("take_profits")
        if not isinstance(plan, list):
            return []
        last_high, last_low = _last_high_low(klines_1d)
        if last_high is None or last_low is None:
            return []
        already_hit_ids = {
            h.get("tp_id") for h in tp_history if isinstance(h, dict)
        }
        new_hits: list[dict[str, Any]] = []
        for idx, level in enumerate(plan):
            if not isinstance(level, dict):
                continue
            tp_id = level.get("tp_id") or f"tp{idx + 1}"
            if tp_id in already_hit_ids:
                continue
            target = _as_float(level.get("target_price") or level.get("price"))
            if target is None:
                continue
            hit = (
                last_high >= target if direction == "long"
                else last_low <= target
            )
            if hit:
                new_hits.append({
                    "tp_id": tp_id,
                    "target_price": target,
                    "hit_at_utc": now_utc,
                    "hit_at_bjt": _to_bjt(now_utc),
                    "hit_run_id": run_id,
                })
        return new_hits


# ============================================================
# 工具
# ============================================================

# Sprint 1.10-L commit 6(P0 #3 改造):提取 4 条件给 determine_close_channel
# (§4.3.3 反手通道 4 条件分级,仅 invalidated reason 时升降级)
def _extract_4_conditions(
    strategy_state: Optional[dict[str, Any]],
    thesis_direction: Optional[str],
) -> dict[str, bool]:
    """从 strategy_state 提取 4 个反手通道分级条件(v1.4 §4.3.3)。

    Args:
        strategy_state: 含 evidence_reports.layer_1/2/5 的 state dict
        thesis_direction: 'long' / 'short' / None — 用于判定反向条件

    Returns:
        4 条件 dict(stop_loss_breached / l1_regime_fully_reversed /
        l2_stance_strong_flip / l5_extreme_event_or_risk_off)
    """
    result = {
        "stop_loss_breached": False,
        "l1_regime_fully_reversed": False,
        "l2_stance_strong_flip": False,
        "l5_extreme_event_or_risk_off": False,
    }
    if not strategy_state or not thesis_direction:
        return result
    ev = (strategy_state.get("evidence_reports") or {})
    l1 = ev.get("layer_1") or {}
    l2 = ev.get("layer_2") or {}
    l5 = ev.get("layer_5") or {}

    # L1 完全反转(非过渡态)
    regime = l1.get("regime")
    if thesis_direction == "long" and regime == "trend_down":
        result["l1_regime_fully_reversed"] = True
    elif thesis_direction == "short" and regime == "trend_up":
        result["l1_regime_fully_reversed"] = True

    # L2 stance 强翻转(opposite + confidence ≥ 0.75)
    stance = l2.get("stance")
    confidence = l2.get("stance_confidence") or l2.get("confidence")
    try:
        conf_f = float(confidence) if confidence is not None else 0.0
    except (ValueError, TypeError):
        conf_f = 0.0
    opposite = (
        (thesis_direction == "long" and stance == "bearish")
        or (thesis_direction == "short" and stance == "bullish")
    )
    if opposite and conf_f >= 0.75:
        result["l2_stance_strong_flip"] = True

    # L5 极端事件 OR macro_stance='risk_off'
    if l5.get("extreme_event_detected") or l5.get("macro_stance") == "risk_off":
        result["l5_extreme_event_or_risk_off"] = True

    return result


def _is_active_lifecycle(lc: Optional[dict[str, Any]]) -> bool:
    """lifecycle 是否处于活跃状态(pending_open 或 active)。"""
    if not isinstance(lc, dict):
        return False
    status = lc.get("status")
    return status in {"pending_open", "active"}


def _compute_average_entry_price(
    *, trade_plan: dict[str, Any], klines_1h: Any,
    direction: Optional[str],
) -> Optional[float]:
    """v1:取 trade_plan.entry_zones[0] 的中点;若无 zone 则用 1H 收盘价。"""
    zones = trade_plan.get("entry_zones") or trade_plan.get("entry_zone")
    if isinstance(zones, dict):
        zones = [zones]
    if isinstance(zones, list) and zones:
        z = zones[0]
        if isinstance(z, dict):
            lo = _as_float(z.get("price_low") or z.get("low"))
            hi = _as_float(z.get("price_high") or z.get("high"))
            if lo is not None and hi is not None:
                return (lo + hi) / 2.0
            if lo is not None:
                return lo
            if hi is not None:
                return hi
    return _last_close(klines_1h)


def _next_tp_target_price(
    trade_plan: dict[str, Any], idx: int,
) -> Optional[float]:
    plan = trade_plan.get("take_profit_plan") or trade_plan.get("take_profits") or []
    if 0 <= idx < len(plan) and isinstance(plan[idx], dict):
        return _as_float(plan[idx].get("target_price") or plan[idx].get("price"))
    return None


def _next_trim_size_pct(
    trade_plan: dict[str, Any], idx: int,
) -> float:
    plan = trade_plan.get("take_profit_plan") or trade_plan.get("take_profits") or []
    if 0 <= idx < len(plan) and isinstance(plan[idx], dict):
        frac = _as_float(plan[idx].get("size_pct") or plan[idx].get("fraction"))
        if frac is not None:
            return frac * 100.0 if frac <= 1.0 else frac  # 容忍 0.3 / 30 两种写法
    # 默认每档 33%
    return 33.0


def _classify_outcome(realized_pnl_pct: float) -> str:
    """v1 简化 4 类(建模 §8.3 完整 10+ 类留 v1.x 复盘细化)。"""
    if realized_pnl_pct >= 5.0:
        return "A_perfect"
    if realized_pnl_pct >= 1.0:
        return "B_good_suboptimal"
    if realized_pnl_pct >= -3.0:
        return "F_wrong_but_stopped"
    return "G_wrong_late_stop"


def _initial_ai_models(strategy_state: dict[str, Any]) -> list[str]:
    adj = strategy_state.get("adjudicator") or {}
    model = adj.get("model_used") or strategy_state.get("ai_model_actual")
    return [model] if model else []


def _initial_rules_versions(strategy_state: dict[str, Any]) -> list[str]:
    rv = strategy_state.get("rules_version")
    return [rv] if rv else []


# ---- pandas / iso helpers ----

def _last_close(klines_df_or_dict: Any) -> Optional[float]:
    if klines_df_or_dict is None:
        return None
    if isinstance(klines_df_or_dict, pd.DataFrame):
        if len(klines_df_or_dict) == 0:
            return None
        try:
            return float(klines_df_or_dict["close"].iloc[-1])
        except (KeyError, ValueError, TypeError):
            return None
    # market_snapshot dict {price: ...}
    if isinstance(klines_df_or_dict, dict):
        return _as_float(
            klines_df_or_dict.get("price")
            or klines_df_or_dict.get("close")
        )
    return None


def _last_high_low(
    klines_df: Any,
) -> tuple[Optional[float], Optional[float]]:
    if not isinstance(klines_df, pd.DataFrame) or len(klines_df) == 0:
        return None, None
    try:
        return float(klines_df["high"].iloc[-1]), float(klines_df["low"].iloc[-1])
    except (KeyError, ValueError, TypeError):
        return None, None


def _hours_between(a_iso: str, b_iso: str) -> float:
    try:
        a = _parse_iso(a_iso)
        b = _parse_iso(b_iso)
        return max(0.0, (b - a).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_bjt(utc_iso: str) -> Optional[str]:
    try:
        dt = _parse_iso(utc_iso).astimezone(_BJT)
        return dt.strftime("%Y-%m-%d %H:%M (BJT)")
    except Exception:
        return None


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
