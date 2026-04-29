"""tests/test_pre_flight_derivatives_threshold.py — Sprint 1.5g。

衍生品 pre_flight 阈值改用 captured_at_utc(数据点时间)+ 30h:
- 1.5f-revised 起 derivatives = daily cadence(jobs.py interval='1d')
- daily 数据点天然 0-24h 老,旧 10min 阈值是 hourly 残留误判,生产从未通过
- captured_at = 数据点本身时间(daily bar 永远是当天 T00:00:00Z)
- inserted_at = 系统抓取 wall clock(每小时 cron 刷新)
- pre_flight 改用 captured_at 更直观 + 30h 容忍 yesterday's bar
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.pipeline.state_builder import (
    _PREFLIGHT_THRESHOLDS_SEC,
    _evaluate_freshness,
    _latest_iso_for_group,
)


def _now_at(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


# ============================================================
# 阈值表自检
# ============================================================

def test_threshold_derivatives_bumped_to_30h_scheduled():
    assert _PREFLIGHT_THRESHOLDS_SEC["scheduled"]["derivatives"] == 30 * 3600


def test_threshold_derivatives_bumped_to_30h_8h_onchain():
    assert (
        _PREFLIGHT_THRESHOLDS_SEC["scheduled_8h_onchain"]["derivatives"]
        == 30 * 3600
    )


# ============================================================
# _latest_iso_for_group:captured 优先,inserted fallback
# ============================================================

def test_latest_iso_for_derivatives_prefers_captured_over_inserted():
    """captured 存在时取 captured(数据点时间)。"""
    mia = {
        "derivatives_snapshot": "2026-04-29T07:55:00Z",          # 抓取时刻
        "derivatives_snapshot_captured": "2026-04-29T00:00:00Z",  # daily bar
    }
    assert (
        _latest_iso_for_group(mia, "derivatives") == "2026-04-29T00:00:00Z"
    )


def test_latest_iso_for_derivatives_falls_back_to_inserted_when_captured_none():
    """captured 缺失 → 退回 inserted(兼容性路径)。"""
    mia = {
        "derivatives_snapshot": "2026-04-29T07:55:00Z",
        "derivatives_snapshot_captured": None,
    }
    assert (
        _latest_iso_for_group(mia, "derivatives") == "2026-04-29T07:55:00Z"
    )


def test_latest_iso_for_derivatives_falls_back_when_captured_field_missing():
    """旧版 mia dict 完全没有 captured 字段 → fallback。"""
    mia = {"derivatives_snapshot": "2026-04-29T07:55:00Z"}
    assert (
        _latest_iso_for_group(mia, "derivatives") == "2026-04-29T07:55:00Z"
    )


def test_latest_iso_for_derivatives_none_when_both_missing():
    mia = {
        "derivatives_snapshot": None,
        "derivatives_snapshot_captured": None,
    }
    assert _latest_iso_for_group(mia, "derivatives") is None


# ============================================================
# _evaluate_freshness:30h 阈值 + captured-first
# ============================================================

def _base_fresh_mia(captured_iso: str, inserted_iso: str) -> dict:
    """除 derivatives 外,其他 group 全填 fresh,避免干扰。"""
    fresh = "2026-04-29T07:59:00Z"
    return {
        "klines_by_tf": {"1h": fresh, "4h": fresh, "1d": fresh},
        "derivatives_snapshot": inserted_iso,
        "derivatives_snapshot_captured": captured_iso,
        "onchain": {"x": fresh},
        "macro": {"y": fresh},
    }


def test_pre_flight_passes_with_daily_captured_within_30h():
    """captured = -10h, inserted = -30min → derivatives 通过。

    (典型生产形态:每小时刷新今天的 daily bar,数据点是当天 00:00:00。)
    """
    now_iso = "2026-04-29T08:00:00Z"
    captured = "2026-04-28T22:00:00Z"   # -10h(昨天的 daily bar 还在)
    inserted = "2026-04-29T07:30:00Z"   # -30min
    mia = _base_fresh_mia(captured, inserted)
    failed = _evaluate_freshness(
        mia, "scheduled", now_fn=lambda: _now_at(now_iso),
    )
    assert "derivatives" not in failed


def test_pre_flight_fails_with_daily_captured_over_30h():
    """captured = -36h → derivatives 失败(数据点真老了)。"""
    now_iso = "2026-04-29T08:00:00Z"
    captured = "2026-04-27T20:00:00Z"   # -36h
    inserted = "2026-04-29T07:30:00Z"   # -30min(系统侧最近抓过,但抓到的是老数据点)
    mia = _base_fresh_mia(captured, inserted)
    failed = _evaluate_freshness(
        mia, "scheduled", now_fn=lambda: _now_at(now_iso),
    )
    assert "derivatives" in failed


def test_pre_flight_fails_with_inserted_over_30h_no_captured():
    """fallback 路径:无 captured 字段时,inserted -36h → 失败(系统真停了)。

    场景:迁移期或异常,captured_at 缺失,只能退回 inserted。
    """
    now_iso = "2026-04-29T08:00:00Z"
    inserted_36h_ago = "2026-04-27T20:00:00Z"  # -36h
    mia = _base_fresh_mia(captured_iso=None, inserted_iso=inserted_36h_ago)
    failed = _evaluate_freshness(
        mia, "scheduled", now_fn=lambda: _now_at(now_iso),
    )
    assert "derivatives" in failed


def test_pre_flight_passes_at_29h_boundary_inside_threshold():
    """captured = -29h(< 30h)→ 仍通过。"""
    now_iso = "2026-04-29T08:00:00Z"
    captured = "2026-04-28T03:00:00Z"  # -29h
    inserted = "2026-04-29T07:30:00Z"
    mia = _base_fresh_mia(captured, inserted)
    failed = _evaluate_freshness(
        mia, "scheduled", now_fn=lambda: _now_at(now_iso),
    )
    assert "derivatives" not in failed


def test_pre_flight_8h_onchain_derivatives_also_30h():
    """8h 档下 onchain 严格(10min),衍生品阈值仍是 30h。"""
    now_iso = "2026-04-29T08:00:00Z"
    captured = "2026-04-28T22:00:00Z"   # -10h
    inserted = "2026-04-29T07:30:00Z"
    mia = _base_fresh_mia(captured, inserted)
    failed = _evaluate_freshness(
        mia, "scheduled_8h_onchain", now_fn=lambda: _now_at(now_iso),
    )
    assert "derivatives" not in failed


# ============================================================
# 旧阈值的反退化 guard
# ============================================================

def test_old_10min_threshold_no_longer_in_table():
    """1.5g 反退化:阈值不能回到 10 分钟。"""
    assert _PREFLIGHT_THRESHOLDS_SEC["scheduled"]["derivatives"] > 10 * 60
    assert _PREFLIGHT_THRESHOLDS_SEC["scheduled_8h_onchain"]["derivatives"] > 10 * 60
