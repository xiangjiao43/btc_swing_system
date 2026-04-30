"""tests/test_pre_flight_klines_1h_threshold.py — Sprint 1.5j Task B。

Bug 2:1.5g 修了 derivatives pre_flight(captured_at + 30h),漏 klines_1h
仍按旧 inserted_at + 10min 判,cron 抖动直接判 stale → 长期 alerts 噪音。

修复:
- klines_1h 阈值 10min → 2h(1h cadence + 1 cron 抖动容忍)
- 用 open_time_utc(数据点时间)替代 inserted_at(系统侧),口径与 1.5g 对齐
- BTCKlinesDAO.get_latest_captured_at_by_timeframe 新增
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

def test_klines_1h_threshold_bumped_to_2h_scheduled():
    assert _PREFLIGHT_THRESHOLDS_SEC["scheduled"]["klines_1h"] == 2 * 3600


def test_klines_1h_threshold_bumped_to_2h_8h_onchain():
    assert (
        _PREFLIGHT_THRESHOLDS_SEC["scheduled_8h_onchain"]["klines_1h"]
        == 2 * 3600
    )


def test_old_10min_threshold_no_longer_in_table():
    """1.5j 反退化:阈值不能回到 10 分钟。"""
    assert _PREFLIGHT_THRESHOLDS_SEC["scheduled"]["klines_1h"] > 10 * 60


# ============================================================
# _latest_iso_for_group:captured 优先,inserted fallback
# ============================================================

def test_latest_iso_for_klines_1h_prefers_captured():
    mia = {
        "klines_by_tf": {"1h": "2026-04-29T07:55:00Z"},          # inserted
        "klines_captured_by_tf": {"1h": "2026-04-29T07:00:00Z"},  # bar open
    }
    assert (
        _latest_iso_for_group(mia, "klines_1h") == "2026-04-29T07:00:00Z"
    )


def test_latest_iso_for_klines_1h_falls_back_when_captured_missing():
    """captured 缺失 → 退回 inserted(兼容性路径)。"""
    mia = {
        "klines_by_tf": {"1h": "2026-04-29T07:55:00Z"},
        "klines_captured_by_tf": {},
    }
    assert (
        _latest_iso_for_group(mia, "klines_1h") == "2026-04-29T07:55:00Z"
    )


def test_latest_iso_for_klines_1h_none_when_both_missing():
    mia = {"klines_by_tf": {}, "klines_captured_by_tf": {}}
    assert _latest_iso_for_group(mia, "klines_1h") is None


# ============================================================
# _evaluate_freshness:2h 阈值
# ============================================================

def _base_mia(captured_iso: str, inserted_iso: str) -> dict:
    """除 klines_1h 外其他 group 全填 fresh,避免干扰。"""
    fresh = "2026-04-29T07:59:00Z"
    daily_fresh = "2026-04-29T00:00:00Z"
    return {
        "klines_by_tf": {"1h": inserted_iso, "4h": fresh, "1d": fresh},
        "klines_captured_by_tf": {"1h": captured_iso, "4h": fresh, "1d": fresh},
        "derivatives_snapshot": fresh,
        "derivatives_snapshot_captured": daily_fresh,
        "onchain": {"x": fresh},
        "macro": {"y": fresh},
    }


def test_klines_1h_passes_within_2h():
    """captured = -1.5h, inserted = -45min → 通过(captured < 2h)。"""
    now_iso = "2026-04-29T08:00:00Z"
    captured = "2026-04-29T06:30:00Z"  # -1.5h
    inserted = "2026-04-29T07:15:00Z"  # -45min
    mia = _base_mia(captured, inserted)
    failed = _evaluate_freshness(
        mia, "scheduled", now_fn=lambda: _now_at(now_iso),
    )
    assert "klines_1h" not in failed


def test_klines_1h_fails_over_2h():
    """captured = -3h → 失败(超 2h)。"""
    now_iso = "2026-04-29T08:00:00Z"
    captured = "2026-04-29T05:00:00Z"  # -3h
    inserted = "2026-04-29T07:45:00Z"  # -15min(系统刚抓过,但抓到的是老 bar)
    mia = _base_mia(captured, inserted)
    failed = _evaluate_freshness(
        mia, "scheduled", now_fn=lambda: _now_at(now_iso),
    )
    assert "klines_1h" in failed


def test_klines_1h_passes_just_under_2h_boundary():
    """captured = -119min → 通过(< 2h)。"""
    now_iso = "2026-04-29T08:00:00Z"
    captured = "2026-04-29T06:01:00Z"  # -1h59min
    inserted = "2026-04-29T07:30:00Z"
    mia = _base_mia(captured, inserted)
    failed = _evaluate_freshness(
        mia, "scheduled", now_fn=lambda: _now_at(now_iso),
    )
    assert "klines_1h" not in failed


def test_klines_1h_8h_onchain_also_2h():
    """8h 档下其他 group 严格,但 klines_1h cadence 不变 → 2h。"""
    now_iso = "2026-04-29T08:00:00Z"
    captured = "2026-04-29T06:30:00Z"  # -1.5h
    inserted = "2026-04-29T07:30:00Z"
    mia = _base_mia(captured, inserted)
    failed = _evaluate_freshness(
        mia, "scheduled_8h_onchain", now_fn=lambda: _now_at(now_iso),
    )
    assert "klines_1h" not in failed


# ============================================================
# DAO method 端到端
# ============================================================

def test_get_latest_captured_at_by_timeframe_returns_open_time():
    """新加的 BTCKlinesDAO.get_latest_captured_at_by_timeframe 返回 max(open_time)。"""
    import sqlite3
    import tempfile
    from pathlib import Path

    from src.data.storage.connection import init_db
    from src.data.storage.dao import BTCKlinesDAO, KlineRow

    tmp = Path(tempfile.mkdtemp()) / "klines_captured.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    try:
        BTCKlinesDAO.upsert_klines(conn, [
            KlineRow(timeframe="1h", timestamp="2026-04-29T05:00:00Z",
                     open=1, high=2, low=1, close=1.5, volume_btc=1.0),
            KlineRow(timeframe="1h", timestamp="2026-04-29T06:00:00Z",
                     open=1, high=2, low=1, close=1.5, volume_btc=1.0),
            KlineRow(timeframe="1h", timestamp="2026-04-29T07:00:00Z",
                     open=1, high=2, low=1, close=1.5, volume_btc=1.0),
            KlineRow(timeframe="1d", timestamp="2026-04-29T00:00:00Z",
                     open=1, high=2, low=1, close=1.5, volume_btc=1.0),
        ])
        conn.commit()
        m = BTCKlinesDAO.get_latest_captured_at_by_timeframe(conn)
        assert m["1h"] == "2026-04-29T07:00:00Z"
        assert m["1d"] == "2026-04-29T00:00:00Z"
    finally:
        conn.close()
