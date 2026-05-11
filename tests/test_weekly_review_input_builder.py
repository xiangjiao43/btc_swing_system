"""tests/test_weekly_review_input_builder.py — Sprint 1.10-H commit 2 单测。

覆盖 v1.4 §3.3.9 7 类输入聚合 + 23 V 激活率 + meta 4 字段。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.ai.weekly_review_input_builder import (
    VALIDATOR_KEYS,
    build_weekly_review_input,
)


_NOW = datetime(2026, 5, 10, 14, 0, 0, tzinfo=timezone.utc)  # 周日 14:00 UTC = 22:00 BJT


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    from scripts.init_v14_tables import apply_migration
    apply_migration(c)
    yield c
    c.close()


# ============================================================
# 工具:写测试数据
# ============================================================

def _seed_strategy_run(
    conn, *, run_id, generated_at_utc,
    fallback_level=None, ca_json=None, retry_log_json=None,
    btc_price_usd=75000.0, action_state="FLAT",
    run_trigger="scheduled", full_state_json=None,
):
    # Sprint 1.10-K-A commit 2 §X(v1.4 §11.2):删 observation_category INSERT 列引用
    # (列已从 schema.sql 删除,配合 dao.py + state_builder.py + migration 015 真跑)
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, btc_price_usd, "
        "fallback_level, full_state_json, "
        "constraint_activations_json, retry_log_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, generated_at_utc, generated_at_utc,
         generated_at_utc, action_state, run_trigger, btc_price_usd,
         fallback_level,
         json.dumps(full_state_json) if full_state_json is not None else "{}",
         json.dumps(ca_json) if ca_json else None,
         json.dumps(retry_log_json) if retry_log_json else None),
    )


def _seed_thesis(
    conn, *, thesis_id, direction, status="active",
    created_at_utc=None, closed_at_utc=None, close_channel=None,
    final_outcome=None, final_realized_pnl_pct=None,
):
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status, closed_at_utc, close_channel, "
        "final_outcome, final_realized_pnl_pct) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (thesis_id, "r_test", created_at_utc or "2026-05-04T12:00:00Z",
         direction, "test", 70, "[]",
         "closed" if status != "active" else "planned", status,
         closed_at_utc, close_channel, final_outcome,
         final_realized_pnl_pct),
    )


def _seed_va_snapshot(conn, *, snapshot_id, snapshot_at_utc, total_equity):
    # run_id 用 snapshot_id 兜底唯一(virtual_account.run_id 是 UNIQUE)
    conn.execute(
        "INSERT INTO virtual_account (snapshot_id, run_id, snapshot_at_utc, "
        "btc_price_at_snapshot, initial_capital, available_cash, total_equity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (snapshot_id, snapshot_id, snapshot_at_utc, 75000.0,
         100000.0, 50000.0, total_equity),
    )


def _seed_fuse_event(conn, *, event_type, triggered_at_utc):
    conn.execute(
        "INSERT INTO fuse_events (event_type, triggered_at_utc) VALUES (?, ?)",
        (event_type, triggered_at_utc),
    )


def _seed_review_pending(conn, *, reason, entered_at_utc):
    conn.execute(
        "INSERT INTO system_states (state_type, entered_at_utc, reason) "
        "VALUES (?, ?, ?)",
        ("review_pending", entered_at_utc, reason),
    )


def _seed_weekly_review(conn, *, week_start_utc, output):
    conn.execute(
        "INSERT INTO weekly_reviews "
        "(week_start_utc, triggered_at_utc, output_json, critical_count, notification_sent) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            week_start_utc,
            week_start_utc + "T14:00:00Z",
            json.dumps(output, ensure_ascii=False),
            0,
            0,
        ),
    )


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# 1. 23 条 Validator key 完整性
# ============================================================

def test_validator_keys_count_is_23():
    assert len(VALIDATOR_KEYS) == 23


def test_validator_keys_all_v_prefix():
    for k in VALIDATOR_KEYS:
        assert k.startswith("validator_")


# ============================================================
# 2. 冷启动:无任何数据
# ============================================================

def test_cold_start_returns_empty_aggregates(conn):
    result = build_weekly_review_input(conn, now_utc=_NOW)
    assert result["window"]["days"] == 7
    assert result["performance_summary_raw"]["total_runs"] == 0
    assert result["performance_summary_raw"]["thesis_created"] == 0
    assert result["performance_summary_raw"]["weekly_pnl_pct"] == 0.0
    # 23 V 全 0
    v_acts = result["hard_constraint_activation_raw"]["v_activations"]
    assert len(v_acts) == 23
    for k in VALIDATOR_KEYS:
        assert v_acts[k]["activations"] == 0
        assert v_acts[k]["rate"] == "0/0 valid_runs"
    assert result["sample_base"] == {
        "total_strategy_runs": 0,
        "valid_constraint_runs": 0,
        "missing_constraint_runs": 0,
        "window_days": 7,
    }
    assert result["l3_diagnostics"]["phase_distribution"] == {}
    assert result["l4_diagnostics"]["risk_tier_distribution"] == {}
    assert result["validator_diagnostics"]["top_triggered_validators"] == []


# ============================================================
# 3. strategy_runs 聚合
# ============================================================

def test_aggregates_strategy_runs(conn):
    # 5 runs:3 success + 2 fallback
    for i in range(5):
        ts = _iso(_NOW - timedelta(days=6) + timedelta(hours=i))
        fb = "level_2" if i >= 3 else None
        _seed_strategy_run(
            conn, run_id=f"r_{i}", generated_at_utc=ts, fallback_level=fb,
        )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    assert r["performance_summary_raw"]["total_runs"] == 5
    assert r["performance_summary_raw"]["successful_runs"] == 3
    assert r["performance_summary_raw"]["ai_failures"] == 2


def test_runs_outside_window_excluded(conn):
    # 1 run in window + 1 outside
    _seed_strategy_run(
        conn, run_id="r_in",
        generated_at_utc=_iso(_NOW - timedelta(days=2)),
    )
    _seed_strategy_run(
        conn, run_id="r_out",
        generated_at_utc=_iso(_NOW - timedelta(days=10)),
    )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    assert r["performance_summary_raw"]["total_runs"] == 1


# ============================================================
# 4. theses 聚合
# ============================================================

def test_aggregates_theses_created_closed(conn):
    # 1 created in window + 1 closed_profit + 1 closed_loss
    _seed_thesis(
        conn, thesis_id="t_created", direction="long",
        status="active",
        created_at_utc=_iso(_NOW - timedelta(days=3)),
    )
    _seed_thesis(
        conn, thesis_id="t_profit", direction="long",
        status="closed_profit",
        created_at_utc=_iso(_NOW - timedelta(days=20)),
        closed_at_utc=_iso(_NOW - timedelta(days=2)),
        close_channel="A",
        final_outcome="profit", final_realized_pnl_pct=2.5,
    )
    _seed_thesis(
        conn, thesis_id="t_loss", direction="short",
        status="closed_loss",
        created_at_utc=_iso(_NOW - timedelta(days=15)),
        closed_at_utc=_iso(_NOW - timedelta(days=1)),
        close_channel="A",
        final_outcome="loss", final_realized_pnl_pct=-1.2,
    )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    perf = r["performance_summary_raw"]
    assert perf["thesis_created"] == 1
    assert perf["thesis_closed_profit"] == 1
    assert perf["thesis_closed_loss"] == 1
    th = r["thesis_lifecycle"]
    assert th["channel_a_uses"] == 2
    assert len(th["created_list"]) == 1
    assert len(th["closed_list"]) == 2


def test_aggregates_thesis_channels(conn):
    """channel B/C 计数。"""
    for i, ch in enumerate(["A", "B", "C"]):
        _seed_thesis(
            conn, thesis_id=f"t_ch_{ch}", direction="long",
            status="invalidated",
            created_at_utc=_iso(_NOW - timedelta(days=10)),
            closed_at_utc=_iso(_NOW - timedelta(days=3 - i)),
            close_channel=ch,
            final_outcome="loss",
        )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    th = r["thesis_lifecycle"]
    assert th["channel_a_uses"] == 1
    assert th["channel_b_uses"] == 1
    assert th["channel_c_uses"] == 1


# ============================================================
# 5. constraint_activations 聚合(23 V 激活次数 + meta)
# ============================================================

def test_aggregates_constraint_activations_23_v(conn):
    """3 个 run,各 V1/V6/V21 激活 → counts {V1:3, V6:3, V21:3, 其他 0}。"""
    ca_payload = {
        "validator_1_stop_loss_overridden": True,
        "validator_6_thesis_lock": True,
        "validator_21_soft_resistance": True,
        "position_cap_compressed": 0.45,
        "thesis_lock_active": True,
    }
    for i in range(3):
        _seed_strategy_run(
            conn, run_id=f"r_ca_{i}",
            generated_at_utc=_iso(_NOW - timedelta(days=i + 1)),
            ca_json=ca_payload,
        )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    v_acts = r["hard_constraint_activation_raw"]["v_activations"]
    assert v_acts["validator_1_stop_loss_overridden"]["activations"] == 3
    assert v_acts["validator_6_thesis_lock"]["activations"] == 3
    assert v_acts["validator_21_soft_resistance"]["activations"] == 3
    assert v_acts["validator_2_position_capped"]["activations"] == 0
    # rate 字段
    assert v_acts["validator_1_stop_loss_overridden"]["rate"] == "3/3 valid_runs"
    assert r["sample_base"]["total_strategy_runs"] == 3
    assert r["sample_base"]["valid_constraint_runs"] == 3
    assert r["sample_base"]["missing_constraint_runs"] == 0


def test_aggregates_weekly_review_evidence_diagnostics(conn):
    """L3/L4/Validator 诊断只读聚合,用于解释异常原因。"""
    state_1 = {
        "layers": {
            "l2": {"phase": "late"},
            "l3": {
                "opportunity_grade": "C",
                "execution_permission": "watch",
                "anti_pattern_flags": [
                    "extending_late_phase",
                    "failing_at_resistance",
                ],
            },
            "l4": {
                "risk_tier": "elevated",
                "risk_score": 72,
                "position_cap_multiplier": 0.55,
                "risk_breakdown": {
                    "volatility_risk": 80,
                    "crowding_risk": 65,
                },
            },
            "master": {
                "trade_plan": {"action": "watch"},
                "what_would_change_mind": ["1D 收盘重新站上阻力"],
                "notes": [
                    "what_would_change_mind_insufficient_1_objective",
                    "conflict_resolution_missing",
                ],
            },
        },
    }
    state_2 = {
        "layers": {
            "l2": {"phase": "early"},
            "l3": {
                "opportunity_grade": "B",
                "execution_permission": "cautious_open",
                "anti_pattern_flags": [],
            },
            "l4": {
                "risk_tier": "moderate",
                "risk_score": 31,
                "position_cap_multiplier": 0.85,
                "risk_breakdown": {"crowding_risk": 20},
            },
            "master": {"mode": "new_thesis"},
        },
    }
    _seed_strategy_run(
        conn,
        run_id="r_diag_1",
        generated_at_utc=_iso(_NOW - timedelta(days=1)),
        btc_price_usd=80000.0,
        full_state_json=state_1,
        ca_json={
            "validator_16_change_mind": True,
            "validator_23_conflict_missing": True,
        },
    )
    _seed_strategy_run(
        conn,
        run_id="r_diag_2",
        generated_at_utc=_iso(_NOW - timedelta(days=2)),
        btc_price_usd=79000.0,
        full_state_json=state_2,
        ca_json={"validator_16_change_mind": False},
    )
    conn.commit()

    r = build_weekly_review_input(conn, now_utc=_NOW)

    l3 = r["l3_diagnostics"]
    assert l3["phase_distribution"] == {"early": 1, "late": 1}
    assert l3["opportunity_grade_distribution"] == {"B": 1, "C": 1}
    assert l3["execution_permission_distribution"] == {
        "cautious_open": 1,
        "watch": 1,
    }
    assert l3["anti_pattern_signal_distribution"]["extending_late_phase"] == 1
    assert l3["anti_pattern_by_grade"]["C"]["failing_at_resistance"] == 1
    assert len(l3["extending_late_phase_samples"]) == 1
    assert l3["extending_late_phase_samples"][0]["master_action"] == "watch"

    l4 = r["l4_diagnostics"]
    assert l4["risk_tier_distribution"] == {"elevated": 1, "moderate": 1}
    assert l4["risk_score_summary"]["avg"] == 51.5
    assert l4["position_cap_multiplier_summary"]["min"] == 0.55
    assert l4["risk_breakdown_top_reasons"][0]["reason"] == "volatility_risk"
    assert len(l4["elevated_samples"]) == 1
    assert l4["elevated_samples"][0]["risk_breakdown"]["crowding_risk"] == 65

    vd = r["validator_diagnostics"]
    assert vd["validator_sample_base"]["valid_constraint_runs"] == 2
    assert vd["top_triggered_validators"][0]["activations"] == 1
    assert len(vd["v16_samples"]) == 1
    assert "what_would_change_mind" in vd["v16_samples"][0]["activation_reason"]
    assert len(vd["v23_samples"]) == 1
    assert "conflict_resolution" in vd["v23_samples"][0]["activation_reason"]


def test_aggregates_temporal_consistency_diagnostics(conn):
    """从本周 strategy_runs + 历史 weekly_reviews 只读聚合时间连续性。"""
    for i in range(2):
        _seed_strategy_run(
            conn,
            run_id=f"r_temporal_{i}",
            generated_at_utc=_iso(_NOW - timedelta(days=i + 1)),
            full_state_json={
                "layers": {
                    "l2": {"phase": "late"},
                    "l3": {
                        "opportunity_grade": "C",
                        "anti_pattern_flags": ["extending_late_phase"],
                    },
                    "l4": {"risk_tier": "elevated"},
                },
            },
            ca_json={
                "validator_16_change_mind": True,
                "validator_23_conflict_missing": True,
            },
        )
    _seed_weekly_review(
        conn,
        week_start_utc="2026-04-27",
        output={
            "performance_summary": {
                "thesis_created": 0,
                "orders_filled": 0,
            },
            "l3_diagnostics": {
                "anti_pattern_signal_distribution": {
                    "extending_late_phase": 3,
                },
                "opportunity_grade_distribution": {"C": 3},
            },
            "l4_diagnostics": {
                "risk_tier_distribution": {
                    "elevated": 4,
                    "moderate": 1,
                },
            },
            "hard_constraint_activation_review": {
                "validator_16_change_mind": {
                    "activations": 3,
                    "rate": "3/5 valid_runs",
                },
                "validator_23_conflict_missing": {
                    "activations": 3,
                    "rate": "3/5 valid_runs",
                },
            },
            "adjustment_recommendations": [
                {
                    "目标": "审计 elevated",
                    "具体调整路径": "连续观察 elevated",
                    "优先级": "medium",
                    "evidence_confidence": "low",
                },
            ],
        },
    )
    _seed_weekly_review(
        conn,
        week_start_utc="2026-04-20",
        output={
            "performance_summary": {
                "thesis_created": 0,
                "orders_filled": 0,
            },
            "l4_diagnostics": {
                "risk_tier_distribution": {
                    "elevated": 5,
                    "moderate": 0,
                },
            },
            "adjustment_recommendations": [
                {
                    "目标": "审计 elevated",
                    "具体调整路径": "连续观察 elevated",
                    "优先级": "medium",
                    "evidence_confidence": "low",
                },
            ],
        },
    )
    conn.commit()

    r = build_weekly_review_input(conn, now_utc=_NOW)
    td = r["temporal_consistency_diagnostics"]

    assert td["l3_extending_late_phase_trend"][0]["rate"] == 1.0
    assert td["l4_elevated_trend"][0]["count"] == 2
    assert td["validator_v16_trend"][0]["rate"] == 1.0
    assert td["validator_v23_trend"][0]["rate"] == 1.0
    assert td["anomaly_streaks"]["l4_elevated_weeks"] == 3
    assert td["anomaly_streaks"]["zero_thesis_weeks"] == 3
    assert td["anomaly_streaks"]["zero_trade_weeks"] == 3
    assert td["recommendation_recurrence"][0]["weeks_seen"] == 2


def test_aggregates_position_cap_compressed_avg(conn):
    """3 个 run,position_cap_compressed = 0.40 / 0.50 / 0.60 → avg=0.50。"""
    for i, cap in enumerate([0.40, 0.50, 0.60]):
        _seed_strategy_run(
            conn, run_id=f"r_cap_{i}",
            generated_at_utc=_iso(_NOW - timedelta(days=i + 1)),
            ca_json={"position_cap_compressed": cap},
        )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    cap_avg = r["hard_constraint_activation_raw"]["position_cap_compressed_avg"]
    assert abs(cap_avg - 0.50) < 1e-9


def test_aggregates_thesis_lock_blocks_count(conn):
    """thesis_lock_active=True 出现 2 次 → thesis_lock_blocks_count=2。"""
    _seed_strategy_run(
        conn, run_id="r_lock_1",
        generated_at_utc=_iso(_NOW - timedelta(days=2)),
        ca_json={"thesis_lock_active": True},
    )
    _seed_strategy_run(
        conn, run_id="r_lock_2",
        generated_at_utc=_iso(_NOW - timedelta(days=1)),
        ca_json={"thesis_lock_active": True},
    )
    _seed_strategy_run(
        conn, run_id="r_no_lock",
        generated_at_utc=_iso(_NOW - timedelta(days=3)),
        ca_json={"thesis_lock_active": False},
    )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    assert r["hard_constraint_activation_raw"]["thesis_lock_blocks_count"] == 2


# ============================================================
# 6. retry_log 聚合
# ============================================================

def test_aggregates_retry_log_fallback_counts(conn):
    """3 runs:1 macro_fallback + 1 thesis_aware + 1 event_invalidation → 各 1。"""
    _seed_strategy_run(
        conn, run_id="r_macro",
        generated_at_utc=_iso(_NOW - timedelta(days=1)),
        retry_log_json={"macro_fallback_applied": True,
                         "failed_layers": ["l5"]},
    )
    _seed_strategy_run(
        conn, run_id="r_thesis",
        generated_at_utc=_iso(_NOW - timedelta(days=2)),
        retry_log_json={"thesis_aware_fallback_applied": True,
                         "failed_layers": ["master"]},
    )
    _seed_strategy_run(
        conn, run_id="r_inv",
        generated_at_utc=_iso(_NOW - timedelta(days=3)),
        retry_log_json={"event_invalidation_triggered": True},
    )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    rl = r["retry_log_aggregate"]
    assert rl["macro_fallback_count"] == 1
    assert rl["thesis_aware_fallback_count"] == 1
    assert rl["event_invalidation_count"] == 1
    assert rl["failed_layers_distribution"]["l5"] == 1
    assert rl["failed_layers_distribution"]["master"] == 1


# ============================================================
# 7. virtual_account 7 天 PnL + drawdown
# ============================================================

def test_aggregates_virtual_account_pnl(conn):
    """7 个 daily snapshot 全在窗口内,equity 100k → 102k = +2%。

    snapshot 时间用 (_NOW - 6d - 1h) → (_NOW - 1h),保证全部 < _NOW(window_end)。
    """
    for i in range(7):
        ts = _iso(_NOW - timedelta(days=6 - i, hours=1))
        eq = 100000.0 + i * 333.33
        _seed_va_snapshot(
            conn, snapshot_id=f"s_{i}", snapshot_at_utc=ts, total_equity=eq,
        )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    va = r["virtual_account_window"]
    assert va["snapshots_count"] == 7
    # (102000 - 100000) / 100000 = 2%
    assert abs(va["weekly_pnl_pct"] - 2.0) < 0.01
    # 单调递增,无回撤
    assert va["max_drawdown_pct"] == 0.0


def test_aggregates_virtual_account_drawdown(conn):
    """先涨到 105k 再跌到 98k → drawdown = (98 - 105) / 105 = -6.67%。"""
    equities = [100000, 102000, 105000, 100000, 98000]
    for i, eq in enumerate(equities):
        ts = _iso(_NOW - timedelta(days=4 - i, hours=1))
        _seed_va_snapshot(
            conn, snapshot_id=f"s_dd_{i}", snapshot_at_utc=ts, total_equity=eq,
        )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    va = r["virtual_account_window"]
    assert abs(va["weekly_pnl_pct"] - (-2.0)) < 0.01  # 100k → 98k = -2%
    # 105k peak → 98k = -6.67%
    assert va["max_drawdown_pct"] < -6.5
    assert va["max_drawdown_pct"] > -7.0


# ============================================================
# 8. fuse_events + system_states
# ============================================================

def test_aggregates_fuse_events_and_review_pending(conn):
    """2 个 14d_fuse + 1 个 channel_c + 1 个 review_pending。"""
    for i in range(2):
        _seed_fuse_event(
            conn, event_type="14d_fuse_triggered",
            triggered_at_utc=_iso(_NOW - timedelta(days=i + 1)),
        )
    _seed_fuse_event(
        conn, event_type="channel_c_used",
        triggered_at_utc=_iso(_NOW - timedelta(days=2)),
    )
    _seed_review_pending(
        conn, reason="overly_conservative",
        entered_at_utc=_iso(_NOW - timedelta(days=1)),
    )
    conn.commit()
    r = build_weekly_review_input(conn, now_utc=_NOW)
    fs = r["fuse_and_states"]
    assert fs["fuse_14d_triggered_count"] == 2
    assert fs["channel_c_used_count"] == 1
    assert fs["review_pending_triggers"] == 1
    # 也写入 hard_constraint_activation_raw 元字段
    hc = r["hard_constraint_activation_raw"]
    assert hc["channel_c_uses_count"] == 1
    assert hc["review_pending_triggers"] == 1


# ============================================================
# 9. window 字段 + context.now_utc 透传
# ============================================================

def test_window_fields_correct(conn):
    r = build_weekly_review_input(conn, now_utc=_NOW, window_days=7)
    assert r["window"]["days"] == 7
    assert r["window"]["end_utc"] == _iso(_NOW)
    assert r["window"]["start_utc"] == _iso(_NOW - timedelta(days=7))
    assert r["context"]["now_utc"] == _iso(_NOW)
