"""tests/test_state_builder_pre_flight.py — Sprint 2.7-C Stage 0 数据就绪检查。

§Z 端到端:真 SQLite + 真 OnchainDAO + 真 state_builder.build,
断言不同 run_trigger / 不同数据新鲜度下 degraded_stages 的精确名单。
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import (
    BTCKlinesDAO, DerivativeMetric, DerivativesDAO,
    KlineRow, MacroDAO, MacroMetric,
    OnchainDAO, OnchainMetric,
)
from src.pipeline.state_builder import (
    _PREFLIGHT_THRESHOLDS_SEC,
    _evaluate_freshness,
    _latest_iso_for_group,
    _query_metric_inserted_at,
    _run_pre_flight_freshness_check,
)


# ============================================================
# Threshold table sanity
# ============================================================

def test_threshold_table_has_two_run_triggers():
    assert "scheduled" in _PREFLIGHT_THRESHOLDS_SEC
    assert "scheduled_8h_onchain" in _PREFLIGHT_THRESHOLDS_SEC


def test_8h_onchain_thresholds_strictly_tighter_for_onchain():
    s = _PREFLIGHT_THRESHOLDS_SEC["scheduled"]["onchain"]
    s_8h = _PREFLIGHT_THRESHOLDS_SEC["scheduled_8h_onchain"]["onchain"]
    assert s_8h < s, "8h trigger should require fresher onchain"


def test_8h_onchain_klines_1d_4h_tighter():
    assert (_PREFLIGHT_THRESHOLDS_SEC["scheduled_8h_onchain"]["klines_1d_4h"]
            < _PREFLIGHT_THRESHOLDS_SEC["scheduled"]["klines_1d_4h"])


# ============================================================
# _latest_iso_for_group
# ============================================================

def test_latest_iso_for_group_klines_1d_4h_takes_max():
    mia = {
        "klines_by_tf": {
            "1d": "2026-04-27T00:00:00Z",
            "4h": "2026-04-27T08:00:00Z",   # newer
            "1h": "2026-04-27T10:00:00Z",
        }
    }
    assert _latest_iso_for_group(mia, "klines_1d_4h") == "2026-04-27T08:00:00Z"


def test_latest_iso_for_group_onchain_takes_max():
    mia = {"onchain": {"a": "2026-04-27T00:00:00Z",
                       "b": "2026-04-27T08:00:00Z",
                       "c": None}}
    assert _latest_iso_for_group(mia, "onchain") == "2026-04-27T08:00:00Z"


def test_latest_iso_for_group_returns_none_for_empty():
    assert _latest_iso_for_group({}, "onchain") is None
    assert _latest_iso_for_group({"onchain": {"a": None}}, "onchain") is None


# ============================================================
# _evaluate_freshness with synthetic now
# ============================================================

def _now_at(iso: str) -> datetime:
    s = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def test_evaluate_freshness_all_fresh_returns_empty():
    """所有 metric 都在 1 分钟前写入 → 5 个 group 全 OK。"""
    fresh_iso = "2026-04-27T07:59:00Z"
    now_iso = "2026-04-27T08:00:00Z"  # 1 min after
    mia = {
        "klines_by_tf": {"1h": fresh_iso, "4h": fresh_iso, "1d": fresh_iso},
        "derivatives_snapshot": fresh_iso,
        "onchain": {"x": fresh_iso},
        "macro": {"y": fresh_iso},
    }
    failed = _evaluate_freshness(mia, "scheduled", now_fn=lambda: _now_at(now_iso))
    assert failed == []


def test_evaluate_freshness_klines_1h_stale_for_regular():
    """klines_1h captured_at 3h 前 → 失败(1.5j 阈值 2h,口径=open_time)。"""
    stale = "2026-04-27T05:00:00Z"  # -3h
    fresh = "2026-04-27T07:59:00Z"
    daily_fresh = "2026-04-27T00:00:00Z"
    now = "2026-04-27T08:00:00Z"
    mia = {
        "klines_by_tf": {"1h": stale, "4h": fresh, "1d": fresh},
        "klines_captured_by_tf": {"1h": stale, "4h": fresh, "1d": fresh},
        "derivatives_snapshot": fresh,
        "derivatives_snapshot_captured": daily_fresh,
        "onchain": {"x": fresh},
        "macro": {"y": fresh},
    }
    failed = _evaluate_freshness(mia, "scheduled", now_fn=lambda: _now_at(now))
    assert "klines_1h" in failed


def test_evaluate_freshness_8h_onchain_strict_kicks_in():
    """常规档下 onchain 25h 前是 OK,8h 档下不行(阈值 10 min)。"""
    onchain_25h_ago = "2026-04-26T07:00:00Z"
    fresh = "2026-04-27T07:59:00Z"
    now = "2026-04-27T08:00:00Z"
    mia = {
        "klines_by_tf": {"1h": fresh, "4h": fresh, "1d": fresh},
        "derivatives_snapshot": fresh,
        "onchain": {"x": onchain_25h_ago},
        "macro": {"y": onchain_25h_ago},
    }
    failed_regular = _evaluate_freshness(
        mia, "scheduled", now_fn=lambda: _now_at(now),
    )
    failed_8h = _evaluate_freshness(
        mia, "scheduled_8h_onchain", now_fn=lambda: _now_at(now),
    )
    assert "onchain" not in failed_regular
    assert "macro" not in failed_regular
    assert "onchain" in failed_8h


def test_evaluate_freshness_unknown_run_trigger_uses_scheduled():
    fresh = "2026-04-27T07:59:00Z"
    now = "2026-04-27T08:00:00Z"
    mia = {
        "klines_by_tf": {"1h": fresh, "4h": fresh, "1d": fresh},
        "derivatives_snapshot": fresh,
        "onchain": {"x": fresh},
        "macro": {"y": fresh},
    }
    failed = _evaluate_freshness(
        mia, "event_macro", now_fn=lambda: _now_at(now),
    )
    assert failed == []


# ============================================================
# _run_pre_flight_freshness_check (with retry)
# ============================================================

@pytest.fixture
def db_conn():
    tmp = Path(tempfile.mkdtemp()) / "preflight.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _seed_fresh_data(db_conn, ts_iso: str | None = None):
    """All 4 groups have 1 row, inserted_at = ts_iso (microsecond format).

    Sprint 1.5g:默认 ts 用真实当前 UTC,这样 derivatives captured_at_utc
    = 当天 daily bar,不会被 30h 阈值打回。
    """
    if ts_iso is None:
        ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OnchainDAO.upsert_batch(db_conn, [
        OnchainMetric(timestamp=ts_iso, metric_name="x",
                      metric_value=1.0, source="glassnode_primary"),
    ])
    MacroDAO.upsert_batch(db_conn, [
        MacroMetric(timestamp=ts_iso, metric_name="y",
                    metric_value=1.0, source="fred"),
    ])
    # Sprint 1.5f-revised:DerivativesDAO 只接受 daily ts(T00:00:00Z),
    # 把测试 fixture 的 hourly ts 截断为当天 daily(语义上 derivatives daily bar)。
    derivatives_daily_ts = ts_iso[:10] + "T00:00:00Z"
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(timestamp=derivatives_daily_ts,
                         metric_name="funding_rate", metric_value=0.0001),
    ])
    BTCKlinesDAO.upsert_klines(db_conn, [
        KlineRow(timeframe="1h", timestamp=ts_iso, open=1, high=2, low=1, close=1.5,
                 volume_btc=1.0),
        KlineRow(timeframe="4h", timestamp=ts_iso, open=1, high=2, low=1, close=1.5,
                 volume_btc=1.0),
        KlineRow(timeframe="1d", timestamp=ts_iso, open=1, high=2, low=1, close=1.5,
                 volume_btc=1.0),
    ])
    db_conn.commit()


def test_pre_flight_passes_with_fresh_data(db_conn):
    _seed_fresh_data(db_conn)
    mia = _query_metric_inserted_at(db_conn)
    sleep_calls: list = []
    failed, refreshed = _run_pre_flight_freshness_check(
        db_conn, mia, "scheduled",
        sleep_fn=lambda s: sleep_calls.append(s),
    )
    # 数据刚写入 → inserted_at_utc 为 now,通过
    assert failed == []
    assert sleep_calls == []  # 没重试


def test_pre_flight_fails_then_retries_then_still_fails(db_conn):
    """空 DB → 全 group 都 missing → 重试一次(sleep 调用)→ 仍失败 → 返回 5 个 degraded。"""
    sleep_calls: list = []
    mia_empty = _query_metric_inserted_at(db_conn)
    failed, refreshed = _run_pre_flight_freshness_check(
        db_conn, mia_empty, "scheduled",
        sleep_fn=lambda s: sleep_calls.append(s),
    )
    assert len(sleep_calls) == 1  # 重试 1 次
    assert sleep_calls[0] == 300.0  # 默认 5 min
    # 5 个 group 都失败
    assert set(failed) == {
        "klines_1h", "derivatives", "klines_1d_4h", "onchain", "macro",
    }


def test_pre_flight_fails_then_retry_succeeds_after_data_arrives(db_conn):
    """模拟:第一次评估失败,sleep 期间数据落地,重试时通过。"""
    sleep_calls: list = []
    mia_empty = _query_metric_inserted_at(db_conn)

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        # 在 sleep 期间往 DB 写真实数据
        _seed_fresh_data(db_conn)

    failed, refreshed = _run_pre_flight_freshness_check(
        db_conn, mia_empty, "scheduled",
        sleep_fn=fake_sleep,
    )
    assert len(sleep_calls) == 1
    # 重读后通过
    assert failed == []


def test_pre_flight_returns_refreshed_metric_inserted_at(db_conn):
    """重试后返回的 dict 要是新查的(让上游 emitter 用最新时间戳)。"""
    sleep_calls: list = []
    mia_empty = _query_metric_inserted_at(db_conn)

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        _seed_fresh_data(db_conn)

    failed, refreshed = _run_pre_flight_freshness_check(
        db_conn, mia_empty, "scheduled",
        sleep_fn=fake_sleep,
    )
    # refreshed 里 onchain.x 应该有值(seed 写入后)
    assert refreshed["onchain"].get("x") is not None
    assert refreshed["derivatives_snapshot"] is not None


# ============================================================
# build() integration: degraded_stages contains pre_flight.X
# ============================================================

def test_pre_flight_runs_during_build_with_8h_run_trigger(db_conn):
    """8h 档 run_trigger 路径走 8h 阈值分支(更严)。

    直接测 helper,避免完整 build() pipeline 跑出来超时。
    """
    sleep_calls: list = []
    onchain_25h_ago = "2026-04-26T07:00:00Z"
    fresh = "2026-04-27T07:59:00Z"
    mia = {
        "klines_by_tf": {"1h": fresh, "4h": fresh, "1d": fresh},
        "derivatives_snapshot": fresh,
        "onchain": {"x": onchain_25h_ago},  # 25h ago - 8h 档失败
        "macro": {"y": fresh},
    }
    failed, _ = _run_pre_flight_freshness_check(
        db_conn, mia, "scheduled_8h_onchain",
        sleep_fn=lambda s: sleep_calls.append(s),
        now_fn=lambda: _now_at("2026-04-27T08:00:00Z"),
    )
    assert "onchain" in failed
    assert len(sleep_calls) == 1  # 重试一次
