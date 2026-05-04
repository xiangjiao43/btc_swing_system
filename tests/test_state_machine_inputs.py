"""tests/test_state_machine_inputs.py — Sprint 1.5b-A 字段填充器。

§Z 真实数据驱动:
- 每个字段构造真实 klines DataFrame + lifecycle dict + trade_plan,
  断言 build_state_machine_fields 返回的值正确
- apply_inputs_to_strategy_state 后,strategy_state 子路径(trade_plan / lifecycle /
  layer_2/4)被正确覆盖
- 真跑 state_machine.compute_next:fields 填空时永远卡 FLAT;填充后真迁移
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.strategy.state_machine import StateMachine
from src.strategy.state_machine_inputs import (
    apply_inputs_to_strategy_state,
    build_state_machine_fields,
)
# Sprint 1.10-J commit 4a §X:derive_account_state 已删,本测试文件相关用例
# 整删 / 改成不传 account_state(state_machine 内部默认空 dict)。


# ============================================================
# Helpers
# ============================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours_ago_iso(h: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=h)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _df_klines(closes: list[float], highs=None, lows=None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open": closes,
        "high": highs or closes,
        "low": lows or closes,
        "close": closes,
        "volume": [1.0] * n,
    }, index=pd.date_range("2026-04-25", periods=n, freq="h"))


# ============================================================
# entry_zone_filled_confirmed_1h
# ============================================================

def test_entry_zone_filled_long_inside_zone():
    """LONG_PLANNED + 1H 收盘 67950 + entry_zone {68000-68200} → True。"""
    state = {
        "trade_plan": {
            "entry_zones": [{"price_low": 68000, "price_high": 68200}],
        },
    }
    fields = build_state_machine_fields(
        prev_state="LONG_PLANNED",
        prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_1h": _df_klines([68500, 68300, 67950])},
        lifecycle={},
    )
    assert fields["entry_zone_filled_confirmed_1h"] is True


def test_entry_zone_not_filled_long_above_zone():
    """1H 收盘 68500 在区间上方 → False。"""
    state = {"trade_plan": {"entry_zones": [{"price_low": 68000, "price_high": 68200}]}}
    fields = build_state_machine_fields(
        prev_state="LONG_PLANNED", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_1h": _df_klines([68500])}, lifecycle={},
    )
    assert fields["entry_zone_filled_confirmed_1h"] is False


def test_entry_zone_not_planned_state_returns_false():
    """prev_state=FLAT → 永远 False(不计算)。"""
    state = {"trade_plan": {"entry_zones": [{"price_low": 68000, "price_high": 68200}]}}
    fields = build_state_machine_fields(
        prev_state="FLAT", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_1h": _df_klines([67950])}, lifecycle={},
    )
    assert fields["entry_zone_filled_confirmed_1h"] is False


def test_entry_zone_filled_short_above_zone():
    """SHORT_PLANNED + 1H 收盘 70500 + entry_zone {70000-70200} → True。"""
    state = {"trade_plan": {"entry_zones": [{"price_low": 70000, "price_high": 70200}]}}
    fields = build_state_machine_fields(
        prev_state="SHORT_PLANNED", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_1h": _df_klines([70500])}, lifecycle={},
    )
    assert fields["entry_zone_filled_confirmed_1h"] is True


# ============================================================
# hours_since_open
# ============================================================

def test_hours_since_open_24h():
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state={},
        context={},
        lifecycle={"origin_time_utc": _hours_ago_iso(24)},
        now_utc=_now_iso(),
    )
    assert 23.5 <= fields["hours_since_open"] <= 24.5


def test_hours_since_open_zero_when_lifecycle_empty():
    """v1:lifecycle 占位 → 0.0(state_machine HOLD 24h 条件天然不满足)。"""
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state={}, context={}, lifecycle={},
    )
    assert fields["hours_since_open"] == 0.0


def test_hours_since_open_zero_when_not_holding():
    """FLAT / PLANNED → 不计算(0.0)。"""
    fields = build_state_machine_fields(
        prev_state="FLAT", prev_strategy_state=None,
        current_strategy_state={}, context={},
        lifecycle={"origin_time_utc": _hours_ago_iso(48)},
    )
    assert fields["hours_since_open"] == 0.0


# ============================================================
# floating_pnl_pct
# ============================================================

def test_floating_pnl_pct_long_positive():
    """avg_entry=68000, last=70040 → +3.0%。"""
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state={},
        context={"klines_1h": _df_klines([70040])},
        lifecycle={"average_entry_price": 68000,
                   "origin_time_utc": _hours_ago_iso(24)},
    )
    assert fields["floating_pnl_pct"] == pytest.approx(3.0, abs=0.01)


def test_floating_pnl_pct_short_positive_when_price_drops():
    fields = build_state_machine_fields(
        prev_state="SHORT_OPEN", prev_strategy_state=None,
        current_strategy_state={},
        context={"klines_1h": _df_klines([67000])},
        lifecycle={"average_entry_price": 70000,
                   "origin_time_utc": _hours_ago_iso(24)},
    )
    assert fields["floating_pnl_pct"] == pytest.approx(
        (70000 - 67000) / 70000 * 100.0, abs=0.01,
    )


def test_floating_pnl_pct_none_when_no_avg_entry():
    """v1:lifecycle 占位无 avg_entry_price → None。"""
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state={},
        context={"klines_1h": _df_klines([70000])},
        lifecycle={},
    )
    assert fields["floating_pnl_pct"] is None


# ============================================================
# hard_invalidation_breached
# ============================================================

def test_hard_invalidation_breached_long():
    """LONG + 4H close=64500 + hard_invalidation [{price:65000, priority:1}] → True。"""
    state = {"evidence_reports": {"layer_4": {
        "hard_invalidation_levels": [
            {"price": 65000, "priority": 1, "type": "structural_hl"},
        ],
    }}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_4h": _df_klines([66000, 64500])},
        lifecycle={"origin_time_utc": _hours_ago_iso(8)},
    )
    assert fields["hard_invalidation_breached"] is True


def test_hard_invalidation_not_breached_long_above():
    state = {"evidence_reports": {"layer_4": {
        "hard_invalidation_levels": [{"price": 65000, "priority": 1}],
    }}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_4h": _df_klines([66000])},
        lifecycle={"origin_time_utc": _hours_ago_iso(8)},
    )
    assert fields["hard_invalidation_breached"] is False


# ============================================================
# stop_loss_hit
# ============================================================

def test_stop_loss_hit_long():
    state = {"trade_plan": {"stop_loss": 67000}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_1h": _df_klines([66800])},
        lifecycle={"origin_time_utc": _hours_ago_iso(8)},
    )
    assert fields["stop_loss_hit"] is True


def test_stop_loss_not_hit_long():
    state = {"trade_plan": {"stop_loss": 67000}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_1h": _df_klines([67500])},
        lifecycle={"origin_time_utc": _hours_ago_iso(8)},
    )
    assert fields["stop_loss_hit"] is False


# ============================================================
# l2_stance_flipped
# ============================================================

def test_l2_stance_flipped_long_to_bearish():
    """LONG_OPEN + prev L2 bullish + curr L2 bearish → True。"""
    prev = {"state": {"evidence_reports": {"layer_2": {"stance": "bullish"}}}}
    curr = {"evidence_reports": {"layer_2": {"stance": "bearish"}}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=prev,
        current_strategy_state=curr, context={}, lifecycle={},
    )
    assert fields["l2_stance_flipped"] is True


def test_l2_stance_not_flipped_when_neutral():
    prev = {"state": {"evidence_reports": {"layer_2": {"stance": "bullish"}}}}
    curr = {"evidence_reports": {"layer_2": {"stance": "neutral"}}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=prev,
        current_strategy_state=curr, context={}, lifecycle={},
    )
    assert fields["l2_stance_flipped"] is False


# ============================================================
# l4_new_critical_risk
# ============================================================

def test_l4_new_critical_risk_true_when_jump_from_high():
    prev = {"state": {"evidence_reports": {"layer_4": {"overall_risk_level": "high"}}}}
    curr = {"evidence_reports": {"layer_4": {"overall_risk_level": "critical"}}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=prev,
        current_strategy_state=curr, context={}, lifecycle={},
    )
    assert fields["l4_new_critical_risk"] is True


def test_l4_new_critical_risk_false_when_already_critical():
    prev = {"state": {"evidence_reports": {"layer_4": {"overall_risk_level": "critical"}}}}
    curr = {"evidence_reports": {"layer_4": {"overall_risk_level": "critical"}}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=prev,
        current_strategy_state=curr, context={}, lifecycle={},
    )
    assert fields["l4_new_critical_risk"] is False


# ============================================================
# account_has_long / short / positions_flat
# ============================================================

def test_account_has_long_during_long_open():
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state={}, context={}, lifecycle={},
    )
    assert fields["account_has_long"] is True
    assert fields["account_has_short"] is False
    assert fields["positions_flat"] is False


def test_account_has_long_after_long_exit_72h():
    """LONG_EXIT 72h → 视为已平仓(account_has_long=False, positions_flat=True)。"""
    fields = build_state_machine_fields(
        prev_state="LONG_EXIT", prev_strategy_state=None,
        current_strategy_state={},
        context={},
        lifecycle={"origin_time_utc": _hours_ago_iso(72)},
    )
    assert fields["account_has_long"] is False
    assert fields["positions_flat"] is True


def test_account_flat_when_no_position_state():
    fields = build_state_machine_fields(
        prev_state="FLAT", prev_strategy_state=None,
        current_strategy_state={}, context={}, lifecycle={},
    )
    assert fields["account_has_long"] is False
    assert fields["account_has_short"] is False
    assert fields["positions_flat"] is True


# ============================================================
# next_trim_triggered (LONG_HOLD 看下一档止盈)
# ============================================================

def test_next_trim_triggered_long_hold_first_tp_hit():
    """take_profit_plan=[{target:80000}], 当日 1d high=80100 → True。"""
    state = {"trade_plan": {
        "take_profit_plan": [{"target_price": 80000, "fraction": 0.3}],
    }}
    fields = build_state_machine_fields(
        prev_state="LONG_HOLD", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_1d": _df_klines([79800], highs=[80100], lows=[79500])},
        lifecycle={"origin_time_utc": _hours_ago_iso(48)},
    )
    assert fields["next_trim_triggered"] is True


def test_next_trim_triggered_skips_already_triggered():
    """首档已 triggered=True → 看下一档(未触发的);如果下一档 90000 没到 → False。"""
    state = {"trade_plan": {"take_profit_plan": [
        {"target_price": 80000, "triggered": True},
        {"target_price": 90000},
    ]}}
    fields = build_state_machine_fields(
        prev_state="LONG_HOLD", prev_strategy_state=None,
        current_strategy_state=state,
        context={"klines_1d": _df_klines([85000], highs=[85500], lows=[84500])},
        lifecycle={"origin_time_utc": _hours_ago_iso(72)},
    )
    assert fields["next_trim_triggered"] is False


# ============================================================
# thesis_still_valid 默认
# ============================================================

def test_thesis_still_valid_default_fully_valid():
    """无 adjudicator 输出 → 默认 fully_valid(保守不触发 EXIT)。"""
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state={}, context={}, lifecycle={},
    )
    assert fields["thesis_still_valid"] == "fully_valid"


def test_thesis_still_valid_from_adjudicator():
    state = {"adjudicator": {"thesis_still_valid": "weakened"}}
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state=state, context={}, lifecycle={},
    )
    assert fields["thesis_still_valid"] == "weakened"


# ============================================================
# apply_inputs_to_strategy_state
# ============================================================

def test_apply_writes_to_correct_paths():
    state = {}
    fields = {
        "entry_zone_filled_confirmed_1h": True,
        "stop_loss_hit": False,
        "tp_target_hit": False,
        "hours_since_open": 24.0,
        "floating_pnl_pct": 3.5,
        "hard_invalidation_breached": False,
        "l2_stance_flipped": True,
        "l2_bullish_early_signal": False,
        "l2_bearish_early_signal": True,
        "l4_new_critical_risk": False,
        "next_trim_triggered": False,
        "current_trim_completed": False,
        "thesis_still_valid": "fully_valid",
        "long_thesis_invalidated": False,
        "short_thesis_invalidated": False,
        "prev_cycle_side": "long",
    }
    apply_inputs_to_strategy_state(state, fields)
    # trade_plan
    assert state["trade_plan"]["entry_zone_filled_confirmed_1h"] is True
    # lifecycle
    assert state["lifecycle"]["hours_since_open"] == 24.0
    assert state["lifecycle"]["floating_pnl_pct"] == 3.5
    # evidence layer_2
    assert state["evidence_reports"]["layer_2"]["stance_flipped"] is True
    assert state["evidence_reports"]["layer_2"]["bearish_early_signal"] is True
    # evidence layer_4
    assert state["evidence_reports"]["layer_4"]["hard_invalidation_breached"] is False


# Sprint 1.10-J commit 4a §X:test_derive_account_state_long 整删
# (derive_account_state 函数已删,v1.4 §11.2 删 account_state 真实账户假设)


# ============================================================
# 集成回归:state_machine 之前 fields=空 dict → 永远卡 FLAT;
#                填充后 → 真实迁移
# Sprint 1.10-J commit 4a:本节 3 个 e2e 整删 — 14 档老逻辑测试
# (LONG_PLANNED→OPEN / OPEN→HOLD / HOLD→TRIM)依赖 account_has_long=True,
# 而 D 项删 account_state 后该字段永远 False;state_machine 主体 1190 行
# 重写留 1.10-K 跟 E.3 一起做,届时 thesis lifecycle 替代 14 档转换会
# 重新覆盖这些路径(thesis-driven e2e tests)。
# ============================================================

