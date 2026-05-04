"""tests/test_protection_handler.py — Sprint 1.10-L commit 2 protection_handler 单测。

覆盖 §4.2.8/9 双向接通(方案 P1A):
- on_protection_entered: 0 active thesis / 1 active thesis / 已在 review_pending 幂等
- check_protection_exit_conditions: 各条件单独 / 全部 / 全部不满足 / VIX 缺失 / 边界
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from src.strategy.protection_handler import (
    REASON_EXTREME_EVENT_PROTECTION,
    check_protection_exit_conditions,
    on_protection_entered,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    # apply v14 migrations(theses + system_states 表)
    from scripts.init_v14_tables import apply_migration
    apply_migration(c)
    c.commit()
    yield c
    c.close()


def _seed_active_thesis(conn, thesis_id: str = "t_active_1") -> None:
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (thesis_id, "r_seed", "2026-05-04T08:00:00Z", "long",
         "test thesis", 70, json.dumps(["1D 跌破 70000"]),
         "opened", "active"),
    )
    conn.commit()


# ============================================================
# on_protection_entered
# ============================================================

def test_on_protection_entered_no_active_thesis(conn):
    """0 active thesis → thesis_processed=0,不写 review_pending。"""
    out = on_protection_entered(conn, run_id="r_test", now_utc="2026-05-04T16:00:00Z")
    assert out["thesis_processed"] == 0
    assert out["review_pending_state_id"] is None
    assert out["was_already_active"] is False
    assert out["related_thesis_id"] is None
    # system_states 不写
    n = conn.execute("SELECT COUNT(*) FROM system_states").fetchone()[0]
    assert n == 0


def test_on_protection_entered_with_active_thesis(conn):
    """1 active thesis → enter_review_pending 写入,reason='extreme_event_protection'。"""
    _seed_active_thesis(conn, "t_active_xyz")
    out = on_protection_entered(conn, run_id="r_test", now_utc="2026-05-04T16:00:00Z")
    assert out["thesis_processed"] == 1
    assert out["review_pending_state_id"] is not None
    assert out["related_thesis_id"] == "t_active_xyz"
    assert out["was_already_active"] is False
    # system_states 写一行 active(state_type='review_pending')
    rows = conn.execute(
        "SELECT * FROM system_states WHERE state_type='review_pending'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["reason"] == REASON_EXTREME_EVENT_PROTECTION
    assert rows[0]["related_thesis_id"] == "t_active_xyz"
    assert rows[0]["exit_at_utc"] is None  # active


def test_on_protection_entered_idempotent(conn):
    """已在 review_pending(active 行存在)→ 不重复 INSERT,was_already_active=True。"""
    _seed_active_thesis(conn, "t_active_a")
    # 第一次进:写入
    r1 = on_protection_entered(conn, run_id="r_a", now_utc="2026-05-04T16:00:00Z")
    assert r1["was_already_active"] is False
    # 第二次进(同 active thesis,同 PROTECTION):enter_review_pending 内部幂等
    r2 = on_protection_entered(conn, run_id="r_b", now_utc="2026-05-04T16:30:00Z")
    assert r2["was_already_active"] is True
    assert r2["review_pending_state_id"] == r1["review_pending_state_id"]
    # system_states 仍只 1 行 active
    n = conn.execute(
        "SELECT COUNT(*) FROM system_states "
        "WHERE state_type='review_pending' AND exit_at_utc IS NULL"
    ).fetchone()[0]
    assert n == 1


# ============================================================
# check_protection_exit_conditions
# ============================================================

def test_exit_conditions_all_unmet():
    """0 条件满足 → can_exit=False。"""
    out = check_protection_exit_conditions(
        current_btc_price=70000.0,
        btc_price_at_entry=80000.0,           # |70k-80k|/80k = 12.5% > 10% → 未结束
        vix=30.0,                              # 30 > 25 → 未结束
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:10:00Z",        # 10 min < 30 min
        user_manual_confirmation=False,
    )
    assert out["can_exit"] is False
    assert out["conditions_met"] == []
    assert out["extreme_event_resolved"] is False
    assert out["cooling_period_passed"] is False
    assert out["user_manual_confirmation"] is False


def test_exit_conditions_extreme_event_resolved_only():
    """仅极端事件结束(BTC ±5% + VIX 20)→ can_exit=True。"""
    out = check_protection_exit_conditions(
        current_btc_price=78000.0,             # |78k-80k|/80k = 2.5% ≤ 10%
        btc_price_at_entry=80000.0,
        vix=20.0,                              # 20 ≤ 25
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:10:00Z",        # 10 min < 30 min
        user_manual_confirmation=False,
    )
    assert out["can_exit"] is True
    assert "extreme_event_resolved" in out["conditions_met"]
    assert out["cooling_period_passed"] is False


def test_exit_conditions_cooling_period_passed_only():
    """仅 30 min 冷静期过 → can_exit=True。"""
    out = check_protection_exit_conditions(
        current_btc_price=70000.0,
        btc_price_at_entry=80000.0,            # 12.5% > 10% → 未结束
        vix=35.0,                              # > 25 → 未结束
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:35:00Z",        # 35 min ≥ 30 min
        user_manual_confirmation=False,
    )
    assert out["can_exit"] is True
    assert "cooling_period_passed" in out["conditions_met"]
    assert out["extreme_event_resolved"] is False
    assert out["minutes_elapsed"] == 35.0


def test_exit_conditions_user_manual_only():
    """仅用户手动确认 → can_exit=True。"""
    out = check_protection_exit_conditions(
        current_btc_price=70000.0,
        btc_price_at_entry=80000.0,
        vix=35.0,
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:10:00Z",
        user_manual_confirmation=True,
    )
    assert out["can_exit"] is True
    assert "user_manual_confirmation" in out["conditions_met"]


def test_exit_conditions_all_three_met():
    """3 条件全满足 → can_exit=True,conditions_met 含 3 项。"""
    out = check_protection_exit_conditions(
        current_btc_price=78000.0,
        btc_price_at_entry=80000.0,
        vix=20.0,
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:35:00Z",
        user_manual_confirmation=True,
    )
    assert out["can_exit"] is True
    assert len(out["conditions_met"]) == 3


def test_exit_conditions_vix_missing_treated_as_ok():
    """VIX 缺失(None)→ 不阻止极端事件结束判定(BTC 满足即可)。"""
    out = check_protection_exit_conditions(
        current_btc_price=78000.0,
        btc_price_at_entry=80000.0,
        vix=None,
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:10:00Z",
        user_manual_confirmation=False,
    )
    assert out["extreme_event_resolved"] is True
    assert out["can_exit"] is True


def test_exit_conditions_btc_price_missing():
    """BTC 价缺失 → 极端事件结束条件无法判定,该条件 False。"""
    out = check_protection_exit_conditions(
        current_btc_price=None,
        btc_price_at_entry=80000.0,
        vix=20.0,
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:10:00Z",
        user_manual_confirmation=False,
    )
    assert out["extreme_event_resolved"] is False
    assert out["can_exit"] is False


def test_exit_conditions_btc_pct_at_boundary():
    """BTC 跌幅恰好 10%(边界)→ extreme_event_resolved=True(包含)。"""
    out = check_protection_exit_conditions(
        current_btc_price=72000.0,             # |72k-80k|/80k = 10.0% (≤ 10%)
        btc_price_at_entry=80000.0,
        vix=20.0,
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:10:00Z",
    )
    assert out["extreme_event_resolved"] is True


def test_exit_conditions_btc_pct_just_over_boundary():
    """BTC 跌幅 10.01%(刚过边界)→ extreme_event_resolved=False。"""
    out = check_protection_exit_conditions(
        current_btc_price=71992.0,             # |71992-80000|/80000 = 10.01%
        btc_price_at_entry=80000.0,
        vix=20.0,
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:10:00Z",
    )
    assert out["extreme_event_resolved"] is False


def test_exit_conditions_cooling_at_boundary():
    """30 分钟整(边界)→ cooling_period_passed=True(≥)。"""
    out = check_protection_exit_conditions(
        current_btc_price=70000.0,
        btc_price_at_entry=80000.0,
        vix=35.0,
        protection_entered_at_utc="2026-05-04T16:00:00Z",
        now_utc="2026-05-04T16:30:00Z",        # 30.0 min ≥ 30
    )
    assert out["cooling_period_passed"] is True


def test_exit_conditions_invalid_iso_strings_graceful():
    """无效 ISO 字符串 → cooling_period_passed=False 不抛。"""
    out = check_protection_exit_conditions(
        current_btc_price=70000.0,
        btc_price_at_entry=80000.0,
        vix=35.0,
        protection_entered_at_utc="not-a-date",
        now_utc="not-a-date",
    )
    assert out["cooling_period_passed"] is False
    assert out["can_exit"] is False
