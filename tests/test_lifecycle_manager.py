"""tests/test_lifecycle_manager.py — Sprint 1.5b-B LifecycleManager 本体。

§Z 真实数据驱动:
- 真 pandas DataFrame klines + 真 strategy_state(adjudicator + trade_plan)
- 断言 compute_pre_sm / compute_post_sm 返回的 lifecycle dict 字段值正确
- 端到端:多步推进 FLAT → PLANNED → OPEN → HOLD → TRIM → EXIT → FLAT,
  验证 lifecycle 自然演进 + state_machine fields 读到真实 PnL 触发迁移
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.strategy.lifecycle_manager import LifecycleManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


# ============================================================
# pre_sm:无活跃 lc
# ============================================================

def test_pre_sm_returns_none_when_no_lifecycle():
    """FLAT(stable):prev_lifecycle=None → pre_sm 返回 None。"""
    mgr = LifecycleManager()
    out = mgr.compute_pre_sm(
        prev_state="FLAT", prev_lifecycle=None,
        strategy_state={}, context={}, now_utc=_now_iso(),
    )
    assert out is None


def test_pre_sm_returns_none_when_lifecycle_closed():
    mgr = LifecycleManager()
    out = mgr.compute_pre_sm(
        prev_state="FLAT",
        prev_lifecycle={"status": "closed", "lifecycle_id": "x"},
        strategy_state={}, context={}, now_utc=_now_iso(),
    )
    assert out is None


# ============================================================
# pre_sm:活跃 lc 度量更新
# ============================================================

def test_pre_sm_updates_pnl_and_hours_held():
    mgr = LifecycleManager()
    origin = _hours_ago_iso(24)
    lc = {
        "lifecycle_id": "lc1", "status": "active", "direction": "long",
        "average_entry_price": 68000, "origin_time_utc": origin,
        "max_favorable_pct": 1.0, "max_adverse_pct": -0.5,
    }
    out = mgr.compute_pre_sm(
        prev_state="LONG_OPEN", prev_lifecycle=lc,
        strategy_state={},
        context={"klines_1h": _df([70040])},  # +3% 浮盈
        now_utc=_now_iso(),
    )
    assert 23.5 <= out["hours_held"] <= 24.5
    assert out["current_floating_pnl_pct"] == pytest.approx(3.0, abs=0.01)
    # max_favorable 单调更新(从 1.0 → 3.0)
    assert out["max_favorable_pct"] == pytest.approx(3.0, abs=0.01)
    # max_adverse 单调:不变(-0.5 仍是更负)
    assert out["max_adverse_pct"] == pytest.approx(-0.5, abs=0.01)


def test_pre_sm_max_favorable_only_increases():
    """已有 max_favorable=3.0,本次 PnL=2.0 → 保持 3.0。"""
    mgr = LifecycleManager()
    lc = {
        "status": "active", "direction": "long",
        "average_entry_price": 68000,
        "origin_time_utc": _hours_ago_iso(48),
        "max_favorable_pct": 3.0, "max_adverse_pct": -0.5,
    }
    out = mgr.compute_pre_sm(
        prev_state="LONG_HOLD", prev_lifecycle=lc,
        strategy_state={},
        context={"klines_1h": _df([69360])},  # 68000 * 1.02 = 69360 (+2%)
        now_utc=_now_iso(),
    )
    assert out["max_favorable_pct"] == pytest.approx(3.0, abs=0.01)
    assert out["current_floating_pnl_pct"] == pytest.approx(2.0, abs=0.01)


def test_pre_sm_tp_hit_detection_long():
    """LONG_HOLD + tp1=80000 + 1d high=80100 → tp_history 追加,tp_target_hit_this_run=True。"""
    mgr = LifecycleManager()
    lc = {
        "status": "active", "direction": "long",
        "average_entry_price": 68000,
        "origin_time_utc": _hours_ago_iso(72),
        "tp_history": [],
    }
    state = {
        "trade_plan": {
            "take_profit_plan": [
                {"tp_id": "tp1", "target_price": 80000, "size_pct": 0.3},
            ],
        },
        "run_id": "r1",
    }
    out = mgr.compute_pre_sm(
        prev_state="LONG_HOLD", prev_lifecycle=lc,
        strategy_state=state,
        context={
            "klines_1h": _df([79900]),
            "klines_1d": _df([79800], highs=[80100], lows=[79500]),
        },
        now_utc=_now_iso(),
    )
    assert out["tp_target_hit_this_run"] is True
    assert len(out["tp_history"]) == 1
    assert out["tp_history"][0]["tp_id"] == "tp1"
    assert out["tp_history"][0]["target_price"] == 80000


def test_pre_sm_tp_hit_skips_already_in_history():
    """tp1 已在 history → 不重复追加;tp2 未触发 → tp_target_hit_this_run=False。"""
    mgr = LifecycleManager()
    lc = {
        "status": "active", "direction": "long",
        "average_entry_price": 68000,
        "origin_time_utc": _hours_ago_iso(72),
        "tp_history": [
            {"tp_id": "tp1", "target_price": 80000,
             "hit_at_utc": _hours_ago_iso(2)},
        ],
    }
    state = {"trade_plan": {"take_profit_plan": [
        {"tp_id": "tp1", "target_price": 80000},
        {"tp_id": "tp2", "target_price": 90000},
    ]}, "run_id": "r2"}
    out = mgr.compute_pre_sm(
        prev_state="LONG_HOLD", prev_lifecycle=lc,
        strategy_state=state,
        context={
            "klines_1h": _df([85000]),
            "klines_1d": _df([85500], highs=[85800], lows=[84500]),
        },
        now_utc=_now_iso(),
    )
    assert len(out["tp_history"]) == 1  # 没追加
    assert out["tp_target_hit_this_run"] is False


# ============================================================
# post_sm:状态过渡
# ============================================================

def test_post_sm_creates_pending_on_planned():
    """FLAT → LONG_PLANNED:创建 pending_open 草稿。"""
    mgr = LifecycleManager()
    state = {
        "adjudicator": {"narrative": "BTC 进入趋势上行,L2 bullish,L3 grade B"},
    }
    out = mgr.compute_post_sm(
        prev_state="FLAT", current_state="LONG_PLANNED",
        lifecycle=None,
        strategy_state=state, context={}, run_id="r1",
        now_utc=_now_iso(),
    )
    assert out is not None
    assert out["status"] == "pending_open"
    assert out["direction"] == "long"
    assert out["lifecycle_id"]  # uuid 不空
    assert "趋势上行" in out["origin_thesis"]
    assert out["origin_run_id"] == "r1"


def test_post_sm_activate_on_open():
    """LONG_PLANNED + lc.pending_open + 1H close 67500 + entry_zone {67000-68000} →
    average_entry_price=67500, status=active, stage=just_opened。"""
    mgr = LifecycleManager()
    pending = {
        "lifecycle_id": "lc1", "status": "pending_open", "direction": "long",
        "stage": "planned", "origin_thesis": "test thesis",
    }
    state = {
        "trade_plan": {"entry_zones": [{"price_low": 67000, "price_high": 68000}]},
    }
    out = mgr.compute_post_sm(
        prev_state="LONG_PLANNED", current_state="LONG_OPEN",
        lifecycle=pending,
        strategy_state=state,
        context={"klines_1h": _df([67500])},
        run_id="r2", now_utc=_now_iso(),
    )
    assert out["status"] == "active"
    assert out["stage"] == "just_opened"
    assert out["average_entry_price"] == 67500.0  # 区间中点 = (67000+68000)/2
    # position_adjustments 追加 open
    adj = out["position_adjustments"]
    assert len(adj) == 1
    assert adj[0]["adjustment_type"] == "open"
    assert adj[0]["size_pct_of_total"] == 100.0


def test_post_sm_open_to_hold_sets_holding_stage():
    mgr = LifecycleManager()
    lc = {
        "status": "active", "direction": "long", "stage": "just_opened",
        "average_entry_price": 68000,
    }
    out = mgr.compute_post_sm(
        prev_state="LONG_OPEN", current_state="LONG_HOLD",
        lifecycle=lc, strategy_state={}, context={},
        run_id="r3", now_utc=_now_iso(),
    )
    assert out["stage"] == "holding"


def test_post_sm_hold_to_trim_appends_position_adjustment():
    mgr = LifecycleManager()
    lc = {
        "status": "active", "direction": "long", "stage": "holding",
        "average_entry_price": 68000,
        "position_adjustments": [
            {"adjustment_type": "open", "size_pct_of_total": 100.0,
             "price": 68000, "reason": "open", "related_run_id": "r1"},
        ],
        "cumulative_trim_pct": 0.0,
    }
    state = {"trade_plan": {"take_profit_plan": [
        {"target_price": 80000, "size_pct": 0.3},
    ]}}
    out = mgr.compute_post_sm(
        prev_state="LONG_HOLD", current_state="LONG_TRIM",
        lifecycle=lc, strategy_state=state, context={},
        run_id="r4", now_utc=_now_iso(),
    )
    assert out["stage"] == "partial_trimmed"
    assert len(out["position_adjustments"]) == 2
    trim = out["position_adjustments"][-1]
    assert trim["adjustment_type"] == "trim"
    assert trim["price"] == 80000
    assert out["cumulative_trim_pct"] > 0


def test_post_sm_archives_on_exit_to_flat():
    """LONG_EXIT → FLAT:status=closed, exit_time_utc=now,
    final_outcome_type 推断。"""
    mgr = LifecycleManager()
    lc = {
        "status": "active", "direction": "long", "stage": "preparing_exit",
        "average_entry_price": 68000,
        "current_floating_pnl_pct": 6.5,  # 正 PnL → A_perfect
    }
    out = mgr.compute_post_sm(
        prev_state="LONG_EXIT", current_state="FLAT",
        lifecycle=lc, strategy_state={}, context={},
        run_id="r5", now_utc=_now_iso(),
    )
    assert out["status"] == "closed"
    assert out["stage"] == "closed"
    assert out["exit_time_utc"]
    assert out["realized_pnl_pct"] == 6.5
    assert out["final_outcome_type"] == "A_perfect"


def test_post_sm_outcome_classification_b_good():
    mgr = LifecycleManager()
    lc = {"status": "active", "direction": "long", "current_floating_pnl_pct": 2.5}
    out = mgr.compute_post_sm(
        prev_state="LONG_EXIT", current_state="FLAT",
        lifecycle=lc, strategy_state={}, context={},
        run_id="r6", now_utc=_now_iso(),
    )
    assert out["final_outcome_type"] == "B_good_suboptimal"


def test_post_sm_outcome_classification_f_wrong_stopped():
    mgr = LifecycleManager()
    lc = {"status": "active", "direction": "long", "current_floating_pnl_pct": -2.0}
    out = mgr.compute_post_sm(
        prev_state="LONG_EXIT", current_state="FLAT",
        lifecycle=lc, strategy_state={}, context={},
        run_id="r7", now_utc=_now_iso(),
    )
    assert out["final_outcome_type"] == "F_wrong_but_stopped"


def test_post_sm_outcome_classification_g_late_stop():
    mgr = LifecycleManager()
    lc = {"status": "active", "direction": "long", "current_floating_pnl_pct": -5.5}
    out = mgr.compute_post_sm(
        prev_state="LONG_EXIT", current_state="FLAT",
        lifecycle=lc, strategy_state={}, context={},
        run_id="r8", now_utc=_now_iso(),
    )
    assert out["final_outcome_type"] == "G_wrong_late_stop"


def test_post_sm_planned_to_flat_drops_draft():
    """LONG_PLANNED → FLAT(条件失效):草稿丢弃。"""
    mgr = LifecycleManager()
    pending = {"status": "pending_open", "direction": "long"}
    out = mgr.compute_post_sm(
        prev_state="LONG_PLANNED", current_state="FLAT",
        lifecycle=pending, strategy_state={}, context={},
        run_id="r9", now_utc=_now_iso(),
    )
    assert out is None


def test_post_sm_protection_marks_lc_active():
    mgr = LifecycleManager()
    lc = {"status": "active", "direction": "long", "stage": "holding"}
    out = mgr.compute_post_sm(
        prev_state="LONG_HOLD", current_state="PROTECTION",
        lifecycle=lc, strategy_state={}, context={},
        run_id="rA", now_utc=_now_iso(),
    )
    assert out["protection_active"] is True
    # 不归档,status 仍 active
    assert out["status"] == "active"


def test_post_sm_post_protection_reassess():
    mgr = LifecycleManager()
    lc = {"status": "active", "direction": "long", "stage": "holding",
          "protection_active": True}
    out = mgr.compute_post_sm(
        prev_state="PROTECTION", current_state="POST_PROTECTION_REASSESS",
        lifecycle=lc, strategy_state={}, context={},
        run_id="rB", now_utc=_now_iso(),
    )
    assert out["stage"] == "reassess"
    assert out["protection_active"] is False


# ============================================================
# 端到端:多步推进 + state_builder 集成
# ============================================================

def test_state_builder_replaces_placeholder_with_real_lifecycle(tmp_path):
    """部署后 strategy_runs.full_state_json.lifecycle 不再是
    {"current_lifecycle": "pending_lifecycle_manager"} 占位。"""
    import sqlite3
    from unittest.mock import MagicMock

    from src.data.storage.connection import init_db
    from src.pipeline import StrategyStateBuilder

    db = tmp_path / "lc.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    # mock ai_caller 让 pipeline 跑得通,即便没有 evidence 数据也能结束
    def _ai_ok(*a, **kw):
        return {"status": "ok", "summary_text": "ok",
                "model_used": "test", "tokens_in": 10, "tokens_out": 10,
                "latency_ms": 1}

    builder = StrategyStateBuilder(
        conn, ai_caller=_ai_ok,
        preflight_sleep_fn=lambda s: None,
        preflight_retry_after_sec=0.0,
    )
    result = builder.run(run_trigger="manual")
    assert result.persisted is True

    # 检查 DB 持久化的 lifecycle 不是占位
    row = conn.execute(
        "SELECT full_state_json FROM strategy_runs ORDER BY generated_at_utc DESC LIMIT 1"
    ).fetchone()
    import json
    state = json.loads(row["full_state_json"])
    lc = state.get("lifecycle")
    # FLAT(stable)→ lc = {} 空 dict;不是老的 {current_lifecycle: pending_lifecycle_manager}
    assert "managed_by" not in lc, (
        f"期望 lifecycle 不再是 1.5b 占位,实际 {lc}"
    )
    conn.close()


def test_state_machine_inputs_reads_lifecycle_pnl():
    """LifecycleManager.compute_pre_sm 写的 PnL → state_machine_inputs 读到。"""
    from src.strategy.state_machine_inputs import build_state_machine_fields

    lc_after_pre_sm = {
        "status": "active", "direction": "long",
        "current_floating_pnl_pct": 3.5,
        "hours_held": 25.0,
        "tp_target_hit_this_run": False,
        "current_trim_completed": False,
    }
    fields = build_state_machine_fields(
        prev_state="LONG_OPEN", prev_strategy_state=None,
        current_strategy_state={"lifecycle": lc_after_pre_sm},
        context={}, lifecycle=lc_after_pre_sm,
    )
    assert fields["floating_pnl_pct"] == 3.5
    assert fields["hours_since_open"] == 25.0
    assert fields["tp_target_hit"] is False
