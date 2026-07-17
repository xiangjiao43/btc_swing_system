"""tests/test_export_route.py — GET /api/export/snapshot.md smoke test。

新工作流唯一不可删的基石端点(供外部 AI 分析的 markdown 快照),最小保护:
- 200 OK
- content-type 是 text/markdown
- body 不空、含约定章节
- 即使 DB 大部分为空也不崩(只有 BTC 1d/4h klines 最小种子)
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db


@pytest.fixture
def db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "export_route.db"
    init_db(db_path=tmp, verbose=False)
    _seed_min_klines(tmp)
    return tmp


@pytest.fixture
def client(db_path: Path) -> TestClient:
    app = create_app(conn_factory=lambda: get_connection(db_path))
    return TestClient(app)


def _seed_min_klines(db_path: Path) -> None:
    """种入最少 BTC klines(1d 30 根 + 4h 30 根 + 1w 5 根),让 builder 有 close 可计算。"""
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        for tf, delta, count in [
            ("1d", timedelta(days=1), 30),
            ("4h", timedelta(hours=4), 30),
            ("1w", timedelta(weeks=1), 5),
        ]:
            for i in range(count):
                ts = (now - delta * (count - i)).strftime("%Y-%m-%dT%H:%M:%SZ")
                close = 60000.0 + i * 100.0
                conn.execute(
                    "INSERT INTO price_candles "
                    "(symbol, timeframe, open_time_utc, open, high, low, close, "
                    "volume, inserted_at_utc) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("BTCUSDT", tf, ts, close, close + 50, close - 50, close, 1.0, ts),
                )
        conn.commit()
    finally:
        conn.close()


def test_snapshot_endpoint_returns_markdown(client: TestClient) -> None:
    resp = client.get("/api/export/snapshot.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    body = resp.text
    assert len(body) > 200
    # 顶部 + 五大章节锚点
    assert "# BTC 系统数据快照" in body
    assert "新鲜度总览" in body
    assert "## 价格技术" in body
    assert "## 链上" in body
    assert "## 衍生品" in body
    assert "## 宏观" in body
    assert "## 事件日历" in body
    # 至少 BTC 现价被种子撑起来,不是 "—"
    assert "BTC 现价" in body


def test_snapshot_endpoint_marks_missing_when_no_onchain(client: TestClient) -> None:
    """只有 klines、其余 4 张表空 → 链上/衍生品/宏观因子应大量 ❌缺失。"""
    resp = client.get("/api/export/snapshot.md")
    assert resp.status_code == 200
    body = resp.text
    # 总览必定含 ❌缺失 > 0
    assert "❌缺失" in body
    # 至少一项缺失因子出现
    assert "❌缺失" in body.split("## 链上")[1]


def test_snapshot_summary_has_structural_lag_bucket(client: TestClient) -> None:
    """当天抓取情况行必须含"结构性滞后"档(区别于真异常)。"""
    resp = client.get("/api/export/snapshot.md")
    assert "结构性滞后" in resp.text


def _leaf(*, value: object = 1.0, as_of: str | None, status: str | None = None) -> dict:
    leaf: dict = {"actual_value": value, "status": status}
    if as_of is not None:
        leaf["as_of"] = as_of
    return leaf


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def test_stale_threshold_within_window_not_anomaly() -> None:
    """T+1 链上(默认 3d 窗口)当天没出新点但数据仅 1d 旧 → 不是真异常。

    这是 2026-07-17 数据包"真异常=13"误报的回归锁:realized_price / cdd /
    ssr 等当天没写新行,但数据在窗口内,曾被错判真异常。
    """
    from src.api.routes.export import _exceeds_stale_threshold

    # 链上默认阈值 3d,1d 旧 → 未超期
    assert _exceeds_stale_threshold("realized_price", _leaf(as_of=_days_ago(1))) is False
    assert _exceeds_stale_threshold("cdd", _leaf(as_of=_days_ago(2))) is False
    # FRED 利率 8d 窗口,6d 旧 → 未超期(us10y/us2y/real_yield 曾被误报)
    assert _exceeds_stale_threshold("us10y", _leaf(as_of=_days_ago(6))) is False
    assert _exceeds_stale_threshold("real_yield", _leaf(as_of=_days_ago(6))) is False


def test_stale_threshold_beyond_window_is_anomaly() -> None:
    """数据真正超出新鲜度窗口 → 仍判真异常(健康哨兵未被削弱)。"""
    from src.api.routes.export import _exceeds_stale_threshold

    assert _exceeds_stale_threshold("realized_price", _leaf(as_of=_days_ago(5))) is True
    assert _exceeds_stale_threshold("us10y", _leaf(as_of=_days_ago(10))) is True
    # 整项缺失也算异常
    assert _exceeds_stale_threshold("cdd", _leaf(value=None, as_of=None)) is True
    assert _exceeds_stale_threshold("ssr", _leaf(as_of=_days_ago(1), status="missing")) is True
