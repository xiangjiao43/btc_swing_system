"""tests/test_lifecycle_e2e_reversal.py — Sprint 1.5b-C 反向交易完整路径。

验证 LONG_HOLD → LONG_TRIM → LONG_EXIT → FLIP_WATCH → SHORT_PLANNED 完整推进:
- 每步真跑 build_state_machine_fields + LifecycleManager.compute_post_sm +
  state_machine.compute_next
- lifecycles 表行数 + review_reports 表行数 都正确反映
- 最终 lifecycle_id 切换到新的(SHORT_PLANNED 是新 lc,不复用旧的)

§Z:不 mock 字段,用真 dict + 真 DAO。

Sprint 1.10-J commit 4a §X:整模块 SKIP — D 项 account_state 删除 +
E.1.b state_machine FLIP_WATCH 主体留 1.10-K,本 e2e 测试涉及
LONG_HOLD/TRIM/EXIT/FLIP_WATCH 全 14 档转换;留 1.10-K 重写后 thesis
lifecycle e2e 重新覆盖。
"""

from __future__ import annotations

import pytest

# Sprint 1.10-J commit 4a §X:整模块 SKIP
pytestmark = pytest.mark.skip(
    reason="1.10-J commit 4a:account_state 删 + FLIP_WATCH 主体留 1.10-K;"
           "1.10-K 重写后 thesis-driven e2e 重新覆盖"
)

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.data.storage.connection import init_db
from src.data.storage.dao import LifecyclesDAO
from src.review.generator import ReviewReportGenerator
from src.strategy.lifecycle_manager import LifecycleManager
from src.strategy.state_machine import StateMachine
from src.strategy.state_machine_inputs import (
    apply_inputs_to_strategy_state,
    build_state_machine_fields,
)


def _row_conn(p: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


def _df(closes, highs=None, lows=None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open": closes,
        "high": highs or closes,
        "low": lows or closes,
        "close": closes,
        "volume": [1.0] * n,
    }, index=pd.date_range("2026-04-25", periods=n, freq="h"))


def _bullish_evidence() -> dict:
    return {
        "layer_1": {"regime": "trend_up"},
        "layer_2": {"stance": "bullish", "stance_confidence": 0.7},
        "layer_3": {"opportunity_grade": "B", "execution_permission": "can_open"},
        "layer_4": {"overall_risk_level": "moderate", "hard_invalidation_levels": []},
        "layer_5": {"macro_stance": "risk_neutral"},
    }


def _bearish_evidence() -> dict:
    return {
        "layer_1": {"regime": "trend_down"},
        "layer_2": {"stance": "bearish", "stance_confidence": 0.75},
        "layer_3": {"opportunity_grade": "A", "execution_permission": "can_open"},
        "layer_4": {"overall_risk_level": "moderate", "hard_invalidation_levels": []},
        "layer_5": {"macro_stance": "risk_off"},
    }


def _step(
    sm: StateMachine, lc_mgr: LifecycleManager,
    *,
    prev_state: str,
    prev_strategy_state: dict | None,
    prev_lifecycle: dict | None,
    state_input: dict,
    context: dict,
    prev_entered_at: str,
    prev_flip_bounds: dict | None,
    now_iso: str,
    run_id: str,
) -> tuple[dict, dict | None, str]:
    """单步推进:pre_sm → state_machine → post_sm。返回 (sm_result, lifecycle, current_state)。"""
    # pre_sm
    lifecycle_pre = lc_mgr.compute_pre_sm(
        prev_state=prev_state, prev_lifecycle=prev_lifecycle,
        strategy_state=state_input, context=context, now_utc=now_iso,
    )
    state_input["lifecycle"] = lifecycle_pre or {}

    # state_machine fields
    fields = build_state_machine_fields(
        prev_state=prev_state,
        prev_strategy_state=prev_strategy_state,
        current_strategy_state=state_input,
        context=context,
        lifecycle=lifecycle_pre or {},
        now_utc=now_iso,
    )
    apply_inputs_to_strategy_state(state_input, fields)
    account = derive_account_state(fields)

    prev_record = {
        "state": {
            "state_machine": {
                "current_state": prev_state,
                "state_entered_at_utc": prev_entered_at,
                "flip_watch_bounds": prev_flip_bounds,
            },
        },
    }
    sm_result = sm.compute_next(
        state_input, previous_record=prev_record,
        account_state=account, now_utc=now_iso,
    )
    state_input["state_machine"] = sm_result

    # post_sm
    lifecycle_post = lc_mgr.compute_post_sm(
        prev_state=prev_state,
        current_state=sm_result["current_state"],
        lifecycle=lifecycle_pre,
        strategy_state=state_input,
        context=context,
        run_id=run_id, now_utc=now_iso,
    )
    state_input["lifecycle"] = lifecycle_post or {}
    return sm_result, lifecycle_post, sm_result["current_state"]


def test_full_long_to_short_reversal():
    tmp = Path(tempfile.mkdtemp()) / "rev.db"
    init_db(db_path=tmp, verbose=False)
    conn = _row_conn(tmp)
    try:
        sm = StateMachine()
        lc_mgr = LifecycleManager(conn=conn)
        review_gen = ReviewReportGenerator(conn=conn)

        # 用相对时间避免 flip_watch hours_in 计算依赖 wall clock
        T0 = datetime.now(timezone.utc) - timedelta(hours=200)
        # 给 flip_watch eff_min 足够余量(默认 18h),Tick 7 设 30h 后

        def t(h: float) -> str:
            return (T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # ---- Tick 1: FLAT → LONG_PLANNED ----
        state1 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {"entry_zones": [{"price_low": 67000, "price_high": 68000}],
                                 "stop_loss": 65000},
                  "adjudicator": {"narrative": "BTC 趋势 up,L2 bullish"}}
        _, lc1, st1 = _step(
            sm, lc_mgr,
            prev_state="FLAT", prev_strategy_state=None,
            prev_lifecycle=None,
            state_input=state1,
            context={"klines_1h": _df([69500])},
            prev_entered_at=t(-1), prev_flip_bounds=None,
            now_iso=t(0), run_id="r1",
        )
        assert st1 == "LONG_PLANNED", f"Tick1 expected LONG_PLANNED, got {st1}"
        assert lc1["status"] == "pending_open"
        # lifecycles 表有 1 行
        assert conn.execute("SELECT COUNT(*) FROM lifecycles").fetchone()[0] == 1

        # ---- Tick 2: LONG_PLANNED → LONG_OPEN(1H 收盘 67500 入区间)----
        state2 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {"entry_zones": [{"price_low": 67000, "price_high": 68000}],
                                 "stop_loss": 65000}}
        _, lc2, st2 = _step(
            sm, lc_mgr,
            prev_state="LONG_PLANNED",
            prev_strategy_state={"state": state1},
            prev_lifecycle=lc1,
            state_input=state2,
            context={"klines_1h": _df([68500, 67500])},
            prev_entered_at=t(0), prev_flip_bounds=None,
            now_iso=t(2), run_id="r2",
        )
        assert st2 == "LONG_OPEN", f"Tick2 expected LONG_OPEN, got {st2}"
        assert lc2["status"] == "active"
        assert lc2["average_entry_price"] == 67500

        # ---- Tick 3: LONG_OPEN → LONG_HOLD(25h + 3% PnL)----
        state3 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {"stop_loss": 65000}}
        _, lc3, st3 = _step(
            sm, lc_mgr,
            prev_state="LONG_OPEN",
            prev_strategy_state={"state": state2},
            prev_lifecycle=lc2,
            state_input=state3,
            context={"klines_1h": _df([69525])},  # 67500 * 1.03
            prev_entered_at=t(2), prev_flip_bounds=None,
            now_iso=t(28), run_id="r3",
        )
        assert st3 == "LONG_HOLD", f"Tick3 expected LONG_HOLD, got {st3}"
        assert lc3["stage"] == "holding"

        # ---- Tick 4: LONG_HOLD → LONG_TRIM(TP1 = 80000 触达)----
        state4 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {"take_profit_plan": [
                      {"tp_id": "tp1", "target_price": 80000, "size_pct": 0.3},
                  ]}}
        _, lc4, st4 = _step(
            sm, lc_mgr,
            prev_state="LONG_HOLD",
            prev_strategy_state={"state": state3},
            prev_lifecycle=lc3,
            state_input=state4,
            context={
                "klines_1h": _df([79900]),
                "klines_1d": _df([79800], highs=[80100], lows=[79500]),
            },
            prev_entered_at=t(28), prev_flip_bounds=None,
            now_iso=t(72), run_id="r4",
        )
        assert st4 == "LONG_TRIM", f"Tick4 expected LONG_TRIM, got {st4}"
        # position_adjustments 已含 trim
        assert any(
            a["adjustment_type"] == "trim"
            for a in lc4.get("position_adjustments", [])
        )

        # ---- Tick 5: LONG_TRIM → LONG_EXIT(stop_loss 触发)----
        # 我们用 stop_loss_hit 触发 EXIT(state_machine 在 _from_LONG_TRIM 没有
        # 直接 EXIT 路径,但 _from_LONG_TRIM is_final_trim_or_exhausted=True 进 EXIT)
        # 简化:模拟 "is_final_trim_or_exhausted=True" via lifecycle 字段
        prev_lc_with_final = dict(lc4)
        prev_lc_with_final["is_final_trim_or_exhausted"] = True

        state5 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {}}
        # state_machine 读 lifecycle.is_final_trim_or_exhausted via _build_field_snapshot
        state5["lifecycle"] = prev_lc_with_final
        _, lc5, st5 = _step(
            sm, lc_mgr,
            prev_state="LONG_TRIM",
            prev_strategy_state={"state": state4},
            prev_lifecycle=prev_lc_with_final,
            state_input=state5,
            context={"klines_1h": _df([79000])},
            prev_entered_at=t(72), prev_flip_bounds=None,
            now_iso=t(96), run_id="r5",
        )
        assert st5 == "LONG_EXIT", f"Tick5 expected LONG_EXIT, got {st5}"

        # ---- Tick 6: LONG_EXIT → FLIP_WATCH(positions_flat + L1 down + L2 hint bearish)----
        # account_has_long=False 需要 hours_since_open > 48h(state_machine_inputs 简化)
        # 我们 origin_time_utc 是 t(2),now=t(150),hours = 148h > 48 → flat
        state6 = {"evidence_reports": _bearish_evidence(),
                  "trade_plan": {}}
        # 模拟 lc 已归档(state_machine 也认 positions_flat)
        # LONG_EXIT 状态下 _infer_account_status 看 hours_since_open 决定平仓
        sm6, lc6, st6 = _step(
            sm, lc_mgr,
            prev_state="LONG_EXIT",
            prev_strategy_state={"state": state5},
            prev_lifecycle=lc5,
            state_input=state6,
            context={"klines_1h": _df([78000])},
            prev_entered_at=t(96), prev_flip_bounds=None,
            now_iso=t(150), run_id="r6",
        )
        assert st6 == "FLIP_WATCH", f"Tick6 expected FLIP_WATCH, got {st6}"
        # lifecycle 已归档:post_sm 返回 closed 字典(让 DAO 写库 + review 触发用)
        assert lc6 is not None
        assert lc6["status"] == "closed"
        # lifecycles 表里这条 lc status='closed'
        old_lc_id = lc1["lifecycle_id"]
        archived = LifecyclesDAO.get_lifecycle(conn, old_lc_id)
        assert archived["status"] == "closed"
        assert archived["exit_time_utc"]

        # 自动复盘触发(prev=lc5 active → curr=lc6 closed,触发 review)
        review = review_gen.maybe_generate_for_closed_lifecycle(lc5, lc6)
        assert review is not None
        assert review["lifecycle_id"] == old_lc_id
        # review_reports 表 +1
        n_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_reports WHERE lifecycle_id=?",
            (old_lc_id,),
        ).fetchone()[0]
        assert n_reviews == 1

        # ---- Tick 7: FLIP_WATCH → SHORT_PLANNED(冷却 30h,L2 bearish 0.75,
        #             long_thesis_invalidated=true,L3 grade=A)----
        state7 = {"evidence_reports": _bearish_evidence(),
                  "trade_plan": {},
                  # AI 输出 thesis_still_valid=invalidated,filler 从而推 long_thesis_invalidated=True
                  "adjudicator": {
                      "narrative": "原多头论点失效,转空头",
                      "thesis_still_valid": "invalidated",
                  }}
        # state6 的 lifecycle = lc6 closed dict,direction=long,
        # _prev_cycle_side 兜底用 direction → "long"
        prev_flip = sm6["flip_watch_bounds"]
        _, lc7, st7 = _step(
            sm, lc_mgr,
            prev_state="FLIP_WATCH",
            prev_strategy_state={"state": state6},
            prev_lifecycle=None,
            state_input=state7,
            context={"klines_1h": _df([78000])},
            prev_entered_at=t(150),  # FLIP_WATCH 进入时
            prev_flip_bounds=prev_flip,
            now_iso=t(180),  # +30h,过 effective_min(默认 18h)
            run_id="r7",
        )
        assert st7 == "SHORT_PLANNED", f"Tick7 expected SHORT_PLANNED, got {st7}"
        assert lc7 is not None
        assert lc7["status"] == "pending_open"
        assert lc7["direction"] == "short"
        # 新 lifecycle_id != 旧的
        assert lc7["lifecycle_id"] != old_lc_id

        # lifecycles 表此时应有 2 条:closed long + pending short
        all_lc = LifecyclesDAO.list_lifecycles(conn)
        assert len(all_lc) == 2
        statuses = {l["status"] for l in all_lc}
        assert "closed" in statuses
        assert "pending_open" in statuses
    finally:
        conn.close()
