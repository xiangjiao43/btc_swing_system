"""tests/test_state_machine_e2e.py — Sprint 1.5b-A 端到端推进 + 1.10-K-A commit 10 重写。

验证多步 state_machine 推进:FLAT → LONG_PLANNED → LONG_OPEN → LONG_HOLD →
LONG_TRIM。每步用 build_state_machine_fields + apply + state_machine.compute_next
完整跑一次,prev_state 真实从上一步的 result 拿(模拟生产 state_builder 的循环)。

§Z:不 mock fields,每步用真实数据 + 真 state_machine.compute_next。

Sprint 1.10-J commit 4a 历史:整模块 SKIP — D 项 account_state 删除后接口
变化(`account_state=` 参数 + `derive_account_state` helper 全删),旧测试无法
import。

Sprint 1.10-K-A commit 10 重写(方案 5A + 方案 C 落地):
- 删 `derive_account_state` 引用 + `account_state=` 参数(已不存在)
- 14 档 transition 仍可发生(方案 C 保留 14 档枚举字符串)
- 每步加 thesis dict + system_state 断言(commit 7 镜像字段)
- FLIP_WATCH 反手测试不在本 e2e 范围(stub 后业务移到 thesis_manager,future)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.strategy.state_machine import StateMachine
from src.strategy.state_machine_inputs import (
    apply_inputs_to_strategy_state,
    build_state_machine_fields,
)


def _hours_ago_iso(h: float, base: datetime | None = None) -> str:
    base = base or datetime.now(timezone.utc)
    return (base - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _df(closes, highs=None, lows=None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open": closes,
        "high": highs or closes,
        "low": lows or closes,
        "close": closes,
        "volume": [1.0] * n,
    }, index=pd.date_range("2026-04-25", periods=n, freq="h"))


def _l1l5_bullish() -> dict:
    return {
        "layer_1": {"regime": "trend_up"},
        "layer_2": {"stance": "bullish", "stance_confidence": 0.7},
        "layer_3": {"opportunity_grade": "B", "execution_permission": "can_open"},
        "layer_4": {"overall_risk_level": "moderate", "hard_invalidation_levels": []},
        "layer_5": {"macro_stance": "risk_neutral"},
    }


def _step_compute(
    sm: StateMachine,
    *,
    prev_state: str,
    prev_strategy_state: dict | None,
    state_input: dict,
    context: dict,
    lifecycle: dict,
    prev_entered_at: str,
    now_iso: str,
) -> dict:
    """单步推进 helper。返回 state_machine 的 result dict。
    Sprint 1.10-K-A commit 10:删 derive_account_state + account_state= 参数(已不存在)。"""
    fields = build_state_machine_fields(
        prev_state=prev_state,
        prev_strategy_state=prev_strategy_state,
        current_strategy_state=state_input,
        context=context,
        lifecycle=lifecycle,
        now_utc=now_iso,
    )
    apply_inputs_to_strategy_state(state_input, fields)

    prev_record = {
        "state": {
            "state_machine": {
                "current_state": prev_state,
                "state_entered_at_utc": prev_entered_at,
            },
        },
    }
    return sm.compute_next(
        state_input,
        previous_record=prev_record,
        now_utc=now_iso,
    )


# ============================================================
# 多步推进:FLAT → PLANNED → OPEN → HOLD → TRIM
# ============================================================

def test_full_progression_flat_to_long_trim():
    """1.10-K-A commit 10 重写:模拟 4 个 tick 真实推进。
    Tick 1: FLAT,bullish 全部条件成立 → LONG_PLANNED + thesis(long, planned, active)
    Tick 2: LONG_PLANNED + 1H 收盘进入 entry_zone → LONG_OPEN + thesis(long, opened, active)
    Tick 3: LONG_OPEN + 25h + 3% 浮盈 → LONG_HOLD + thesis(long, holding, active)
    Tick 4: LONG_HOLD + 1D 高点触达 TP1 → LONG_TRIM + thesis(long, trim, active)
    每步验证 14 档 current_state(向后兼容)+ thesis dict + system_state(commit 7 方案 C 镜像)。
    """
    sm = StateMachine()
    now0 = datetime.now(timezone.utc)
    now1 = now0 + timedelta(hours=1)
    now2 = now1 + timedelta(hours=24)
    now3 = now2 + timedelta(hours=24)

    # ---- Tick 1: FLAT → LONG_PLANNED ----
    state1 = {"evidence_reports": _l1l5_bullish()}
    r1 = _step_compute(
        sm, prev_state="FLAT", prev_strategy_state=None,
        state_input=state1,
        context={"klines_1h": _df([69500])},
        lifecycle={},
        prev_entered_at=_hours_ago_iso(48, base=now0),
        now_iso=now0.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert r1["current_state"] == "LONG_PLANNED", (
        f"Tick1 应到 LONG_PLANNED,实际 {r1['current_state']}"
    )
    # 1.10-K-A commit 7 方案 C 镜像
    assert r1["thesis"] == {
        "direction": "long", "lifecycle_stage": "planned", "status": "active",
    }
    assert r1["system_state"] == "normal"

    # ---- Tick 2: LONG_PLANNED → LONG_OPEN ----
    state2 = {
        "evidence_reports": _l1l5_bullish(),
        "trade_plan": {
            "entry_zones": [{"price_low": 68000, "price_high": 68200}],
            "stop_loss": 65000,
        },
    }
    r2 = _step_compute(
        sm, prev_state="LONG_PLANNED",
        prev_strategy_state={"state": state1},
        state_input=state2,
        context={"klines_1h": _df([68500, 68100])},  # 1H 收盘 68100 进入区间
        lifecycle={},
        prev_entered_at=now0.strftime("%Y-%m-%dT%H:%M:%SZ"),
        now_iso=now1.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert r2["current_state"] == "LONG_OPEN", (
        f"Tick2 应到 LONG_OPEN,实际 {r2['current_state']}; "
        f"matched={r2.get('matched_conditions')}"
    )
    assert r2["thesis"] == {
        "direction": "long", "lifecycle_stage": "opened", "status": "active",
    }
    assert r2["system_state"] == "normal"

    # ---- Tick 3: LONG_OPEN → LONG_HOLD ----
    state3 = {
        "evidence_reports": _l1l5_bullish(),
        "trade_plan": {"stop_loss": 65000},
    }
    open_entry_iso = now1.strftime("%Y-%m-%dT%H:%M:%SZ")
    r3 = _step_compute(
        sm, prev_state="LONG_OPEN",
        prev_strategy_state={"state": state2},
        state_input=state3,
        context={"klines_1h": _df([70040])},  # +3% 浮盈
        lifecycle={
            "average_entry_price": 68000,
            "origin_time_utc": open_entry_iso,
        },
        prev_entered_at=open_entry_iso,
        now_iso=now2.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert r3["current_state"] == "LONG_HOLD", (
        f"Tick3 应到 LONG_HOLD,实际 {r3['current_state']}; "
        f"matched={r3.get('matched_conditions')}"
    )
    assert r3["thesis"] == {
        "direction": "long", "lifecycle_stage": "holding", "status": "active",
    }
    assert r3["system_state"] == "normal"

    # ---- Tick 4: LONG_HOLD → LONG_TRIM ----
    state4 = {
        "evidence_reports": _l1l5_bullish(),
        "trade_plan": {
            "take_profit_plan": [{"target_price": 80000, "fraction": 0.3}],
        },
        "adjudicator": {"thesis_still_valid": "fully_valid"},
    }
    # 模拟 next_trim_triggered → 写到 trade_plan.tp_target_hit(state_machine 字段)
    fields4 = build_state_machine_fields(
        prev_state="LONG_HOLD",
        prev_strategy_state={"state": state3},
        current_strategy_state=state4,
        context={"klines_1d": _df([79800], highs=[80100], lows=[79500])},
        lifecycle={
            "origin_time_utc": open_entry_iso,
            "average_entry_price": 68000,
        },
        now_utc=now3.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    fields4["tp_target_hit"] = fields4["next_trim_triggered"]
    apply_inputs_to_strategy_state(state4, fields4)

    prev_record4 = {
        "state": {
            "state_machine": {
                "current_state": "LONG_HOLD",
                "state_entered_at_utc": now2.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        },
    }
    r4 = sm.compute_next(state4, previous_record=prev_record4,
                         now_utc=now3.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert r4["current_state"] == "LONG_TRIM", (
        f"Tick4 应到 LONG_TRIM,实际 {r4['current_state']}; "
        f"matched={r4.get('matched_conditions')}"
    )
    assert r4["thesis"] == {
        "direction": "long", "lifecycle_stage": "trim", "status": "active",
    }
    assert r4["system_state"] == "normal"


# ============================================================
# 反退化 guard:不调 build_state_machine_fields 时,state_machine 仍卡 FLAT
# ============================================================

def test_state_machine_stuck_at_flat_without_fields_filler():
    """显式制造老 bug 场景:不调 build_state_machine_fields → trade_plan 空 →
    LONG_PLANNED 永远等不到 entry_zone_filled_confirmed_1h=True → 卡 PLANNED。
    Sprint 1.10-K-A commit 10:删 account_state= 参数(已不存在)。"""
    sm = StateMachine()
    state = {
        "evidence_reports": _l1l5_bullish(),
        "trade_plan": {},  # 空 trade_plan(模拟旧路径)
    }
    prev_record = {
        "state": {
            "state_machine": {
                "current_state": "LONG_PLANNED",
                "state_entered_at_utc": _hours_ago_iso(2),
            },
        },
    }
    result = sm.compute_next(
        state, previous_record=prev_record,
        now_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # 没有 fields 填充 → entry_zone_filled_confirmed_1h=False → 永远停留 PLANNED
    assert result["current_state"] == "LONG_PLANNED"
    # 1.10-K-A commit 7 方案 C:LONG_PLANNED → thesis(long, planned, active)
    assert result["thesis"] == {
        "direction": "long", "lifecycle_stage": "planned", "status": "active",
    }
    assert result["system_state"] == "normal"
