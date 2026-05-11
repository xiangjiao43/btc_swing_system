"""tests/test_lsr_alias_dedup.py — Sprint 1.5j Task A 反退化。

Bug 1:LSR alias 双写(主列 + extras 同名)使 _explode_row emit 两次同 ts
行,导致 _pct_change(series, 1) 取末两行 = 同 daily bar → 0% 假信号。

修复:DerivativesDAO.get_all_metrics 末尾去重 (drop_duplicates on index)。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import DerivativesDAO
from src.strategy.factor_card_emitter import _pct_change


@pytest.fixture
def db_conn():
    tmp = Path(tempfile.mkdtemp()) / "lsr_dedup.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _seed_alias_double_write(
    conn: sqlite3.Connection,
    ts: str,
    lsr: float,
) -> None:
    """模拟 1.5f-revised 之前生产 DB 上 alias 双写遗留:
    主列 long_short_ratio + extras['long_short_ratio']=同值。
    """
    conn.execute(
        "INSERT INTO derivatives_snapshots "
        "(captured_at_utc, long_short_ratio, full_data_json, inserted_at_utc) "
        "VALUES (?, ?, ?, ?)",
        (ts, lsr, json.dumps({"long_short_ratio": lsr}), ts),
    )
    conn.commit()


# ============================================================
# 任务 A.1:no duplicate ts
# ============================================================

def _two_recent_days() -> tuple[str, str]:
    """Sprint D fix:相对 now() 的两个紧邻日(yesterday-1 + yesterday),
    避免 hardcode 日期遇到 lookback 滚动边界丢行。"""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    d1 = (today - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
    d2 = (today - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    return d1, d2


def test_get_all_metrics_lsr_no_duplicate_ts(db_conn):
    """生产 DB 上每个 daily ts 都被 alias 双写过 → get_all_metrics 返回的
    long_short_ratio Series 必须每 ts 仅 1 行。"""
    d1, d2 = _two_recent_days()
    _seed_alias_double_write(db_conn, d1, 0.92)
    _seed_alias_double_write(db_conn, d2, 0.80)

    metrics = DerivativesDAO.get_all_metrics(db_conn, lookback_days=10)
    s = metrics["long_short_ratio"].dropna()

    assert len(s) == 2, f"expected 2 rows after dedup, got {len(s)}"
    assert len(set(s.index)) == 2, "all timestamps unique after dedup"


# ============================================================
# 任务 A.2:_pct_change 用真 daily 差(关键反退化)
# ============================================================

def test_lsr_24h_pct_change_uses_distinct_days(db_conn):
    """关键 Bug 1 反退化:bug 之前末两行都是同日 (0.80) → 0/0 - 1 = 0%。
    去重后末两行变成 d1 (0.92) + d2 (0.80) → -13.04%。"""
    d1, d2 = _two_recent_days()
    _seed_alias_double_write(db_conn, d1, 0.92)
    _seed_alias_double_write(db_conn, d2, 0.80)

    metrics = DerivativesDAO.get_all_metrics(db_conn, lookback_days=10)
    s = metrics["long_short_ratio"]

    pct = _pct_change(s, 1)  # daily 1 行 lookback
    assert pct is not None
    expected = (0.80 / 0.92 - 1.0) * 100.0  # ≈ -13.0435%
    assert abs(pct - expected) < 0.05, (
        f"expected ~{expected:.3f}%, got {pct:.3f}% — bug 没修?"
    )


# ============================================================
# 任务 A.3:dedup 不影响正常单写场景
# ============================================================

def test_get_all_metrics_no_alias_no_change(db_conn):
    """如果生产 DB 没有 alias 双写,dedup 是 no-op,各 ts 1 行不变。"""
    d1, d2 = _two_recent_days()
    db_conn.execute(
        "INSERT INTO derivatives_snapshots "
        "(captured_at_utc, long_short_ratio, inserted_at_utc) "
        "VALUES (?, ?, ?)",
        (d1, 0.92, d1),
    )
    db_conn.execute(
        "INSERT INTO derivatives_snapshots "
        "(captured_at_utc, long_short_ratio, inserted_at_utc) "
        "VALUES (?, ?, ?)",
        (d2, 0.80, d2),
    )
    db_conn.commit()

    metrics = DerivativesDAO.get_all_metrics(db_conn, lookback_days=10)
    s = metrics["long_short_ratio"]

    assert len(s) == 2
    assert len(set(s.index)) == 2


# ============================================================
# 任务 A.4:dedup keep='last'(后写优先)
# ============================================================

def test_dedup_keeps_last_value_per_ts(db_conn):
    """同 ts 双写值不同时,dedup 取 last(后写覆盖)。"""
    _, ts = _two_recent_days()
    # 主列 0.92,extras 0.80(模拟 collector 升级期间值漂移)
    db_conn.execute(
        "INSERT INTO derivatives_snapshots "
        "(captured_at_utc, long_short_ratio, full_data_json, inserted_at_utc) "
        "VALUES (?, ?, ?, ?)",
        (
            ts, 0.92,
            json.dumps({"long_short_ratio": 0.80}),
            ts,
        ),
    )
    db_conn.commit()

    metrics = DerivativesDAO.get_all_metrics(db_conn, lookback_days=10)
    s = metrics["long_short_ratio"]
    assert len(s) == 1
    # _explode_row 先 emit 主列 (0.92),再 emit extras (0.80) → keep last = 0.80
    assert s.iloc[0] == 0.80
