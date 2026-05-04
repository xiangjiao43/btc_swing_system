"""tests/test_lifecycle_e2e_reversal.py — Sprint 1.5b-C 反向交易完整路径
+ 1.10-K-A commit 10 重写。

验证 LONG_HOLD → LONG_TRIM → LONG_EXIT → FLIP_WATCH 完整推进:
- 每步真跑 build_state_machine_fields + LifecycleManager.compute_post_sm +
  state_machine.compute_next
- lifecycles 表行数 + review_reports 表行数 都正确反映
- LONG_EXIT → FLIP_WATCH 后 stay(_from_FLIP_WATCH stub,5A)

§Z:不 mock 字段,用真 dict + 真 DAO。

历史 + 重写注:
- Sprint 1.10-J commit 4a §X:整模块 SKIP — D 项 account_state 删除 +
  E.1.b state_machine FLIP_WATCH 主体留 1.10-K
- Sprint 1.10-K-A commit 10 重写:
  - 删 `derive_account_state` 引用 + `account_state=` 参数(已不存在)
  - 14 档 transition Tick 1-6 仍可发生(方案 C 保留 14 档枚举)
  - 加 thesis dict + system_state 断言(commit 7 镜像)
  - **Tick 7 FLIP_WATCH → SHORT_PLANNED 反手测试已删**:
    _from_FLIP_WATCH stub(commit 5,方案 5A)后 FLIP_WATCH 是叶状态(stay),
    反手出口由 thesis_manager 接管 — **留 1.10-L 真接通后重新覆盖**。
    本 e2e 验证到 LONG_EXIT → FLIP_WATCH stub stay 即止。
"""

from __future__ import annotations

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
    now_iso: str,
    run_id: str,
) -> tuple[dict, dict | None, str]:
    """单步推进:pre_sm → state_machine → post_sm。返回 (sm_result, lifecycle, current_state)。
    Sprint 1.10-K-A commit 10:删 derive_account_state + account_state= 参数(已不存在)+
    prev_flip_bounds 参数(_calc_flip_watch_bounds 整删)。"""
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

    prev_record = {
        "state": {
            "state_machine": {
                "current_state": prev_state,
                "state_entered_at_utc": prev_entered_at,
            },
        },
    }
    sm_result = sm.compute_next(
        state_input, previous_record=prev_record,
        now_utc=now_iso,
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


def test_full_long_lifecycle_to_flip_watch_stay():
    """1.10-K-A commit 10 重写:LONG 完整生命周期 + LONG_EXIT → FLIP_WATCH stub stay。

    Tick 1-5: FLAT → LONG_PLANNED → LONG_OPEN → LONG_HOLD → LONG_TRIM → LONG_EXIT
    Tick 6:   LONG_EXIT → FLIP_WATCH(_from_LONG_EXIT 不动)
    Tick 7:   FLIP_WATCH → FLIP_WATCH stub stay(原反手测试已删,留 1.10-L)
    """
    tmp = Path(tempfile.mkdtemp()) / "rev.db"
    init_db(db_path=tmp, verbose=False)
    conn = _row_conn(tmp)
    try:
        sm = StateMachine()
        lc_mgr = LifecycleManager(conn=conn)
        review_gen = ReviewReportGenerator(conn=conn)

        T0 = datetime.now(timezone.utc) - timedelta(hours=200)

        def t(h: float) -> str:
            return (T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # ---- Tick 1: FLAT → LONG_PLANNED ----
        state1 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {"entry_zones": [{"price_low": 67000, "price_high": 68000}],
                                 "stop_loss": 65000},
                  "adjudicator": {"narrative": "BTC 趋势 up,L2 bullish"}}
        sm1, lc1, st1 = _step(
            sm, lc_mgr,
            prev_state="FLAT", prev_strategy_state=None,
            prev_lifecycle=None,
            state_input=state1,
            context={"klines_1h": _df([69500])},
            prev_entered_at=t(-1),
            now_iso=t(0), run_id="r1",
        )
        assert st1 == "LONG_PLANNED", f"Tick1 expected LONG_PLANNED, got {st1}"
        assert lc1["status"] == "pending_open"
        assert conn.execute("SELECT COUNT(*) FROM lifecycles").fetchone()[0] == 1
        # 1.10-K-A commit 7 方案 C 镜像
        assert sm1["thesis"] == {
            "direction": "long", "lifecycle_stage": "planned", "status": "active",
        }
        assert sm1["system_state"] == "normal"

        # ---- Tick 2: LONG_PLANNED → LONG_OPEN ----
        state2 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {"entry_zones": [{"price_low": 67000, "price_high": 68000}],
                                 "stop_loss": 65000}}
        sm2, lc2, st2 = _step(
            sm, lc_mgr,
            prev_state="LONG_PLANNED",
            prev_strategy_state={"state": state1},
            prev_lifecycle=lc1,
            state_input=state2,
            context={"klines_1h": _df([68500, 67500])},
            prev_entered_at=t(0),
            now_iso=t(2), run_id="r2",
        )
        assert st2 == "LONG_OPEN", f"Tick2 expected LONG_OPEN, got {st2}"
        assert lc2["status"] == "active"
        assert lc2["average_entry_price"] == 67500
        assert sm2["thesis"]["lifecycle_stage"] == "opened"

        # ---- Tick 3: LONG_OPEN → LONG_HOLD ----
        state3 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {"stop_loss": 65000}}
        sm3, lc3, st3 = _step(
            sm, lc_mgr,
            prev_state="LONG_OPEN",
            prev_strategy_state={"state": state2},
            prev_lifecycle=lc2,
            state_input=state3,
            context={"klines_1h": _df([69525])},  # 67500 * 1.03
            prev_entered_at=t(2),
            now_iso=t(28), run_id="r3",
        )
        assert st3 == "LONG_HOLD", f"Tick3 expected LONG_HOLD, got {st3}"
        assert lc3["stage"] == "holding"
        assert sm3["thesis"]["lifecycle_stage"] == "holding"

        # ---- Tick 4: LONG_HOLD → LONG_TRIM ----
        state4 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {"take_profit_plan": [
                      {"tp_id": "tp1", "target_price": 80000, "size_pct": 0.3},
                  ]}}
        sm4, lc4, st4 = _step(
            sm, lc_mgr,
            prev_state="LONG_HOLD",
            prev_strategy_state={"state": state3},
            prev_lifecycle=lc3,
            state_input=state4,
            context={
                "klines_1h": _df([79900]),
                "klines_1d": _df([79800], highs=[80100], lows=[79500]),
            },
            prev_entered_at=t(28),
            now_iso=t(72), run_id="r4",
        )
        assert st4 == "LONG_TRIM", f"Tick4 expected LONG_TRIM, got {st4}"
        assert any(
            a["adjustment_type"] == "trim"
            for a in lc4.get("position_adjustments", [])
        )
        assert sm4["thesis"]["lifecycle_stage"] == "trim"

        # ---- Tick 5: LONG_TRIM → LONG_EXIT ----
        prev_lc_with_final = dict(lc4)
        prev_lc_with_final["is_final_trim_or_exhausted"] = True
        state5 = {"evidence_reports": _bullish_evidence(),
                  "trade_plan": {}}
        state5["lifecycle"] = prev_lc_with_final
        sm5, lc5, st5 = _step(
            sm, lc_mgr,
            prev_state="LONG_TRIM",
            prev_strategy_state={"state": state4},
            prev_lifecycle=prev_lc_with_final,
            state_input=state5,
            context={"klines_1h": _df([79000])},
            prev_entered_at=t(72),
            now_iso=t(96), run_id="r5",
        )
        assert st5 == "LONG_EXIT", f"Tick5 expected LONG_EXIT, got {st5}"
        # 1.10-K-A commit 7:LONG_EXIT → thesis(long, closed, closed_pending)
        assert sm5["thesis"] == {
            "direction": "long", "lifecycle_stage": "closed", "status": "closed_pending",
        }

        # ---- Tick 6: LONG_EXIT → FLIP_WATCH(_from_LONG_EXIT 不动)----
        state6 = {"evidence_reports": _bearish_evidence(),
                  "trade_plan": {}}
        sm6, lc6, st6 = _step(
            sm, lc_mgr,
            prev_state="LONG_EXIT",
            prev_strategy_state={"state": state5},
            prev_lifecycle=lc5,
            state_input=state6,
            context={"klines_1h": _df([78000])},
            prev_entered_at=t(96),
            now_iso=t(150), run_id="r6",
        )
        assert st6 == "FLIP_WATCH", f"Tick6 expected FLIP_WATCH, got {st6}"
        assert lc6 is not None
        assert lc6["status"] == "closed"
        old_lc_id = lc1["lifecycle_id"]
        archived = LifecyclesDAO.get_lifecycle(conn, old_lc_id)
        assert archived["status"] == "closed"
        assert archived["exit_time_utc"]
        # 1.10-K-A commit 7 方案 C:FLIP_WATCH 是冷却态(thesis=None,system='normal',
        # 不是系统态;由 thesis.closed_at 隐式驱动出口)
        assert sm6["thesis"] is None
        assert sm6["system_state"] == "normal"
        # 1.10-K-A commit 5 §X:_calc_flip_watch_bounds 整删,bounds 永远 None
        assert sm6["flip_watch_bounds"] is None

        # 自动复盘触发(prev=lc5 active → curr=lc6 closed)
        review = review_gen.maybe_generate_for_closed_lifecycle(lc5, lc6)
        assert review is not None
        assert review["lifecycle_id"] == old_lc_id
        n_reviews = conn.execute(
            "SELECT COUNT(*) FROM review_reports WHERE lifecycle_id=?",
            (old_lc_id,),
        ).fetchone()[0]
        assert n_reviews == 1

        # ---- Tick 7: FLIP_WATCH → FLIP_WATCH stub stay(原反手测试已删)----
        # Sprint 1.10-K-A commit 10 重写:_from_FLIP_WATCH stub(方案 5A)后
        # FLIP_WATCH 是叶状态(stay),反手出口由 thesis_manager 接管 —
        # 留 1.10-L 真接通后重新覆盖 FLIP_WATCH → SHORT_PLANNED 反手路径。
        # 本 e2e 验证到 stub stay 即止。
        state7 = {"evidence_reports": _bearish_evidence(),
                  "trade_plan": {},
                  # 即使给"反手条件齐全"的 fields,stub 也忽略
                  "adjudicator": {
                      "narrative": "原多头论点失效,转空头",
                      "thesis_still_valid": "invalidated",
                  }}
        sm7, lc7, st7 = _step(
            sm, lc_mgr,
            prev_state="FLIP_WATCH",
            prev_strategy_state={"state": state6},
            prev_lifecycle=None,
            state_input=state7,
            context={"klines_1h": _df([78000])},
            prev_entered_at=t(150),
            now_iso=t(180),  # +30h,即使过原 effective_min 18h 也 stay
            run_id="r7",
        )
        # 1.10-K-A commit 5/8:stub stay,thesis=None,system='normal'
        assert st7 == "FLIP_WATCH", (
            f"Tick7 expected FLIP_WATCH stub stay, got {st7}"
            f"(_from_FLIP_WATCH 业务已 stub,反手路径留 1.10-L thesis_manager 接管)"
        )
        assert sm7["thesis"] is None
        assert sm7["system_state"] == "normal"
        assert sm7["stable_in_state"] is True

        # lifecycles 表此时仍只有 1 条:closed long(无新 SHORT pending,反手未实现)
        all_lc = LifecyclesDAO.list_lifecycles(conn)
        assert len(all_lc) == 1
        assert all_lc[0]["status"] == "closed"
    finally:
        conn.close()


# ============================================================
# Sprint 1.10-L commit 7(P0 #3 反手闭环重新覆盖)— 替代 K-A commit 10 删除的 Tick 7
# ============================================================
#
# K-A commit 10 删除原 Tick 7 "FLIP_WATCH → SHORT_PLANNED 反手" 测试,理由:
# _from_FLIP_WATCH stub stay(方案 5A),反手出口由 thesis_manager 接管。
#
# 1.10-L commit 5/6 完成后,**反手通道分级真接通**:
# - lifecycle_manager._archive_lifecycle 调 close_thesis(commit 5)
# - 4 条件分级用 cooldown_manager.determine_close_channel(commit 6)
# - close_thesis 写入 thesis.close_channel='C' / 'B' / 'A'
# - cooldown_manager.is_in_cooldown 据 channel 算 cooldown_end(C=0h / B=24h / A=72h)
#
# 但 — **反手 thesis 创建仍需 master AI 在 cooldown 结束后跑 mode='new_thesis'**
# (Validator 6 主线锁 + master_input_builder 已消费 cooldown_state),mock master AI
# 复杂 + 跨多模块,不在 1.10-L scope。本测试覆盖到 cooldown 真触发即止
# (反手 thesis 创建留 future sprint 真 master AI 接通后端到端)。

def test_lifecycle_archive_channel_c_zero_cooldown_e2e():
    """端到端:LONG_HOLD → LONG_EXIT(stop_loss filled + 4 条件 3/4)→
    _archive_lifecycle 触发 close_thesis(channel='C')→
    cooldown_manager.is_in_cooldown 返 in_cooldown=False(C 是 0h cooldown)。

    对应 v1.4 §4.3.3 4 条件分级 + §4.3.5 纪律 1(必经 thesis 关闭走通道)。
    """
    import json
    from src.data.storage.dao import (
        LifecyclesDAO, ThesesDAO, VirtualAccountDAO,
    )
    from src.strategy.cooldown_manager import is_in_cooldown
    from src.strategy.lifecycle_manager import LifecycleManager
    from scripts.init_v14_tables import apply_migration

    # In-memory schema + v14 migrations
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        conn.executescript(f.read())
    apply_migration(conn)
    conn.commit()

    # Seed long active thesis(K-B/K-A 后路径,简化 setup)
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("th_rev_c", "r_seed", "2026-05-01T00:00:00Z", "long",
         "test long thesis", 75, json.dumps(["1D 跌破 70k"]),
         "holding", "active"),
    )
    conn.execute(
        "INSERT INTO virtual_account (snapshot_id, run_id, snapshot_at_utc, "
        "btc_price_at_snapshot, initial_capital, available_cash, total_equity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("snap_init", "r_seed", "2026-05-01T00:00:00Z", 75000.0,
         100000.0, 100000.0, 100000.0),
    )
    conn.commit()

    # 模拟 LONG_HOLD → LONG_EXIT,bearish + L1 trend_down + L2 bearish 0.85 +
    # L5 极端事件 → 4 条件 3/4 → channel C
    mgr = LifecycleManager(conn=conn)
    lc_to_archive = {
        "lifecycle_id": "lc_rev_c",
        "status": "active", "direction": "long",
        "current_floating_pnl_pct": -3.0,
    }
    state = {
        "market_snapshot": {"btc_price_usd": 67000.0},
        "evidence_reports": {
            "layer_1": {"regime": "trend_down"},        # ✓ long 完全反转
            "layer_2": {"stance": "bearish", "stance_confidence": 0.85},  # ✓ 强翻
            "layer_5": {                                  # ✓ 极端事件 + risk_off
                "extreme_event_detected": True,
                "macro_stance": "risk_off",
            },
        },
    }
    out = mgr.compute_post_sm(
        prev_state="LONG_EXIT", current_state="FLIP_WATCH",  # archive 触发条件之一
        lifecycle=lc_to_archive,
        strategy_state=state,
        context={},
        run_id="r_archive_c", now_utc="2026-05-04T16:00:00Z",
    )
    conn.commit()

    # 验证 1:lifecycle 归档生效
    assert out["status"] == "closed"

    # 验证 2:thesis close_channel='C'(4 条件 3/4 满足)
    th = conn.execute(
        "SELECT close_channel, status, closed_at_utc FROM theses WHERE thesis_id=?",
        ("th_rev_c",),
    ).fetchone()
    assert th["status"] == "invalidated"
    assert th["close_channel"] == "C", (
        f"4 条件 3/4 满足应是 channel C,实际 {th['close_channel']}"
    )

    # 验证 3:is_in_cooldown 返 in_cooldown=False(channel C 是 0h cooldown)
    closed_thesis_dict = {
        "thesis_id": "th_rev_c",
        "close_channel": th["close_channel"],
        "closed_at_utc": th["closed_at_utc"],
    }
    cooldown_status = is_in_cooldown(
        now_utc="2026-05-04T16:00:01Z",  # 1 秒后
        latest_closed_thesis=closed_thesis_dict,
    )
    assert cooldown_status["in_cooldown"] is False, (
        f"channel C 是 0h cooldown,1 秒后应已退出冷却,实际 {cooldown_status}"
    )
    assert cooldown_status["channel"] == "C"
    assert cooldown_status["remaining_hours"] == 0.0

    # 验证 4:**反手 thesis 创建留 future sprint**(master AI mock 复杂 + 跨模块)
    # 本测试只验证 cooldown 真触发 → master AI 看到 in_cooldown=False 后理论可创建反手
    n_active = conn.execute(
        "SELECT COUNT(*) FROM theses WHERE status='active'"
    ).fetchone()[0]
    assert n_active == 0, "channel C close 后无 active(反手由 master AI 在下次 run 创建)"

    conn.close()


def test_lifecycle_archive_channel_b_24h_cooldown_e2e():
    """端到端:invalidated 但 4 条件仅 1/4 满足 → channel B(默认)→ 24h cooldown。

    验证 commit 6 改造在不同条件组合下行为正确(cooldown_manager 默认路径)。
    """
    import json
    from src.data.storage.dao import VirtualAccountDAO
    from src.strategy.cooldown_manager import is_in_cooldown
    from src.strategy.lifecycle_manager import LifecycleManager
    from scripts.init_v14_tables import apply_migration

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        conn.executescript(f.read())
    apply_migration(conn)
    conn.commit()

    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("th_rev_b", "r_seed", "2026-05-01T00:00:00Z", "long",
         "test long thesis", 75, json.dumps(["1D 跌破 70k"]),
         "holding", "active"),
    )
    conn.execute(
        "INSERT INTO virtual_account (snapshot_id, run_id, snapshot_at_utc, "
        "btc_price_at_snapshot, initial_capital, available_cash, total_equity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("snap_init_b", "r_seed", "2026-05-01T00:00:00Z", 75000.0,
         100000.0, 100000.0, 100000.0),
    )
    conn.commit()

    mgr = LifecycleManager(conn=conn)
    lc_to_archive = {
        "lifecycle_id": "lc_rev_b",
        "status": "active", "direction": "long",
        "current_floating_pnl_pct": -1.5,
    }
    state = {
        "market_snapshot": {"btc_price_usd": 71000.0},
        "evidence_reports": {
            "layer_1": {"regime": "transition_down"},  # 不算完全反转
            "layer_2": {"stance": "neutral", "stance_confidence": 0.6},  # 不强翻
            "layer_5": {"macro_stance": "risk_neutral", "extreme_event_detected": False},
        },
    }
    out = mgr.compute_post_sm(
        prev_state="LONG_EXIT", current_state="FLAT",
        lifecycle=lc_to_archive,
        strategy_state=state,
        context={},
        run_id="r_archive_b", now_utc="2026-05-04T16:00:00Z",
    )
    conn.commit()
    assert out["status"] == "closed"

    th = conn.execute(
        "SELECT close_channel FROM theses WHERE thesis_id='th_rev_b'",
    ).fetchone()
    # 0/4 满足 → invalidated 默认 channel B
    assert th["close_channel"] == "B"

    # is_in_cooldown:1 小时后仍在 cooldown(B = 24h)
    closed_dict = {
        "thesis_id": "th_rev_b",
        "close_channel": "B",
        "closed_at_utc": "2026-05-04T16:00:00Z",
    }
    cooldown_1h = is_in_cooldown(
        now_utc="2026-05-04T17:00:00Z",  # +1h
        latest_closed_thesis=closed_dict,
    )
    assert cooldown_1h["in_cooldown"] is True
    assert 22.9 < cooldown_1h["remaining_hours"] < 23.1   # ~23h 剩

    # 25h 后已退出 cooldown
    cooldown_25h = is_in_cooldown(
        now_utc="2026-05-05T17:00:00Z",  # +25h
        latest_closed_thesis=closed_dict,
    )
    assert cooldown_25h["in_cooldown"] is False
    conn.close()
