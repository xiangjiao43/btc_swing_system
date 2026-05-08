"""tests/test_sprint_1_6_new_factors.py — Sprint 1.6 §Z 反退化锁。

Sprint 1.6 新增 9 个因子(建模 v1.3):
- Glassnode 4 端点:sth_supply / ssr / cdd / hodl_waves(11+ bucket)
- 本地派生 2:lth_mvrv / sth_mvrv(price/realized_price 比率)
- CoinGlass 2 端点:btc_dominance / etf_flow

§Z 真实 DB + 真实 emit 流水断言:
- collector mock fetch → DB upsert → 真实 SELECT 验证
- emit_factor_cards 真跑 → 9 张新卡都在
- aSOPR 在 catalog 中 role_in_v1='primary'(1.6 升级)
- OnchainSource Literal 含 'computed'

§X 反退化:
- _GLASSNODE_FETCHERS 含 4 个新 fetcher 名
- collect_klines_daily 调用 fetch_btc_dominance / fetch_etf_flow_history
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
import yaml

from src.data.collectors.derived_onchain import compute_and_save_derived_mvrv
from src.data.collectors.glassnode import GlassnodeCollector
from src.data.collectors.coinglass import CoinglassCollector
from src.data.storage.connection import init_db
from src.data.storage.dao import OnchainDAO, OnchainMetric


# ============================================================
# A.1 — Glassnode 4 个新 fetch 方法存在
# ============================================================

def test_glassnode_has_new_fetchers():
    """Sprint 1.6:GlassnodeCollector 必须暴露 4 个新 fetch 方法。"""
    cg = GlassnodeCollector.__new__(GlassnodeCollector)
    for name in ("fetch_sth_supply", "fetch_ssr", "fetch_cdd",
                 "fetch_hodl_waves"):
        assert hasattr(cg, name), f"GlassnodeCollector 缺 {name}"


def test_glassnode_fetcher_paths_correct():
    """端点常量必须命中 alphanode 真路径(spec 验证过的)。"""
    assert GlassnodeCollector._PATH_STH_SUPPLY.endswith("/supply/sth_sum")
    assert GlassnodeCollector._PATH_SSR.endswith("/indicators/ssr")
    assert GlassnodeCollector._PATH_CDD.endswith("/indicators/cdd")
    assert GlassnodeCollector._PATH_HODL_WAVES.endswith("/supply/hodl_waves")


# ============================================================
# A.2 — HODL Waves 入库方案 a(11+ bucket 拆独立 metric)
# ============================================================

def test_hodl_waves_expands_to_11_plus_buckets():
    """方案 a:1 行响应(含 11+ bucket dict)→ 11+ 行入库,metric_name=hodl_waves_<bucket>。"""
    cg = GlassnodeCollector.__new__(GlassnodeCollector)
    cg._request = MagicMock(return_value={"data": [{
        "t": 1745991240,
        "o": {
            "24h": 0.009229, "1d_1w": 0.019926, "1w_1m": 0.031669,
            "1m_3m": 0.060648, "3m_6m": 0.152254, "6m_12m": 0.128907,
            "1y_2y": 0.112445, "2y_3y": 0.058098, "3y_5y": 0.105526,
            "5y_7y": 0.063720, "7y_10y": 0.083057, "more_10y": 0.174521,
        },
    }]})
    cg._unwrap_data = lambda body: body.get("data") or []
    cg._log_response_shape = lambda *a, **k: None
    rows = cg.fetch_hodl_waves(since_days=7)
    metric_names = sorted({r["metric_name"] for r in rows})
    expected = sorted([f"hodl_waves_{b}" for b in (
        "24h", "1d_1w", "1w_1m", "1m_3m", "3m_6m", "6m_12m",
        "1y_2y", "2y_3y", "3y_5y", "5y_7y", "7y_10y", "more_10y",
    )])
    assert metric_names == expected
    assert len(rows) == 12


def test_hodl_waves_skips_missing_buckets_gracefully():
    """早期数据某些 bucket 不存在时跳过,不抛错。"""
    cg = GlassnodeCollector.__new__(GlassnodeCollector)
    cg._request = MagicMock(return_value={"data": [{
        "t": 1745991240,
        "o": {"24h": 0.009229, "1d_1w": 0.019926},  # 仅 2 bucket
    }]})
    cg._unwrap_data = lambda body: body.get("data") or []
    cg._log_response_shape = lambda *a, **k: None
    rows = cg.fetch_hodl_waves(since_days=7)
    assert len(rows) == 2


# ============================================================
# A.4 — 本地派生 LTH-MVRV / STH-MVRV
# ============================================================

@pytest.fixture
def db_with_seed_metrics(tmp_path: Path) -> sqlite3.Connection:
    """Sprint 1.6.1:种入
       - price_candles 表(timeframe='1d', symbol='BTCUSDT')7 天 close
       - onchain_metrics 表 lth_realized_price + sth_realized_price 7 天
    Sprint C(2026-05-08):timestamps 改为 now() 相对值,避免 hardcode
    日期超过 derived stale 守卫的 48h 阈值。最新日是 yesterday(=now-1d),
    保证 < 48h。
    """
    from datetime import datetime, timedelta, timezone
    db = tmp_path / "derived.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    today_utc = datetime.now(timezone.utc).date()
    # 7 天回溯,最新 = yesterday(< 48h 老,通过 stale 守卫)
    days = [today_utc - timedelta(days=offset) for offset in range(1, 8)]
    days.sort()  # asc
    for idx, day in enumerate(days):
        ts = day.strftime("%Y-%m-%dT00:00:00Z")
        close = 70000.0 + (idx + 24) * 100  # 保留老测试的数值结构
        conn.execute(
            "INSERT INTO price_candles "
            "(symbol, timeframe, open_time_utc, open, high, low, close, "
            "volume, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("BTCUSDT", "1d", ts, close, close, close, close, 1.0, ts),
        )
    # onchain realized prices(同 7 天)
    onchain_metrics = []
    for idx, day in enumerate(days):
        ts = day.strftime("%Y-%m-%dT00:00:00Z")
        onchain_metrics.extend([
            OnchainMetric(timestamp=ts, metric_name="lth_realized_price",
                          metric_value=35000.0,
                          source="glassnode_primary"),
            OnchainMetric(timestamp=ts, metric_name="sth_realized_price",
                          metric_value=60000.0,
                          source="glassnode_primary"),
        ])
    OnchainDAO.upsert_batch(conn, onchain_metrics)
    conn.commit()
    yield conn
    conn.close()


def test_local_computed_mvrv_writes_at_least_7_rows(
    db_with_seed_metrics: sqlite3.Connection,
):
    """compute_and_save_derived_mvrv 必须写入 ≥ 7 行 lth_mvrv 和 sth_mvrv。"""
    stats = compute_and_save_derived_mvrv(db_with_seed_metrics)
    assert stats["lth_mvrv"] >= 7
    assert stats["sth_mvrv"] >= 7


def test_local_computed_mvrv_source_is_computed(
    db_with_seed_metrics: sqlite3.Connection,
):
    """source 必须为 'computed'(区别 Glassnode 来源)。"""
    compute_and_save_derived_mvrv(db_with_seed_metrics)
    for metric in ("lth_mvrv", "sth_mvrv"):
        row = db_with_seed_metrics.execute(
            "SELECT DISTINCT source FROM onchain_metrics "
            "WHERE metric_name = ?",
            (metric,),
        ).fetchone()
        assert row is not None
        assert row["source"] == "computed"


def test_local_computed_mvrv_value_correct(
    db_with_seed_metrics: sqlite3.Connection,
):
    """关键反退化:数学正确性 — lth_mvrv = price / lth_rp。"""
    from datetime import datetime, timedelta, timezone
    compute_and_save_derived_mvrv(db_with_seed_metrics)
    # Sprint C:fixture 改用 now()-相对 ts,这里取最新一天(yesterday)对应行。
    yesterday_iso = (datetime.now(timezone.utc).date()
                     - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    row = db_with_seed_metrics.execute(
        "SELECT value FROM onchain_metrics "
        "WHERE metric_name='lth_mvrv' AND captured_at_utc=?",
        (yesterday_iso,),
    ).fetchone()
    assert row is not None
    # fixture 最新日(idx=6)的 close = 70000 + (6+24)*100 = 73000;
    # lth_rp = 35000;lth_mvrv = 73000/35000 ≈ 2.0857
    assert abs(row["value"] - (73000.0 / 35000.0)) < 0.001


def test_local_computed_mvrv_skips_when_realized_price_missing(
    tmp_path: Path,
):
    """1.6.1:price_candles 有 close 但缺 lth_realized_price 时不抛错,
    只返回 0 行(派生计算依赖 inner join,缺一个直接跳过)。"""
    db = tmp_path / "missing.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        ts = "2026-04-30T00:00:00Z"
        conn.execute(
            "INSERT INTO price_candles "
            "(symbol, timeframe, open_time_utc, open, high, low, close, "
            "volume, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("BTCUSDT", "1d", ts, 70000.0, 70000.0, 70000.0, 70000.0, 1.0, ts),
        )
        conn.commit()
        stats = compute_and_save_derived_mvrv(conn)
        assert stats["lth_mvrv"] == 0
        assert stats["sth_mvrv"] == 0
    finally:
        conn.close()


def test_local_computed_mvrv_skips_when_price_candles_empty(
    tmp_path: Path,
):
    """1.6.1 反退化:price_candles 1d 表空时跳过整批(老 1.6 找
    onchain_metrics.btc_price_close 找不到也是这个分支,但数据源错了)。"""
    db = tmp_path / "no_price.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        # 仅有 lth_realized_price,无 price_candles 1d
        OnchainDAO.upsert_batch(conn, [OnchainMetric(
            timestamp="2026-04-30T00:00:00Z",
            metric_name="lth_realized_price",
            metric_value=35000.0, source="glassnode_primary",
        )])
        conn.commit()
        stats = compute_and_save_derived_mvrv(conn)
        assert stats["lth_mvrv"] == 0
        assert stats["sth_mvrv"] == 0
    finally:
        conn.close()


# ============================================================
# B — CoinGlass btc_dominance / etf_flow
# ============================================================

def test_coinglass_btc_dominance_parses_response():
    cg = CoinglassCollector.__new__(CoinglassCollector)
    cg._request = MagicMock(return_value={"code": "0", "data": [
        {"timestamp": 1745991240000, "bitcoin_dominance": 60.36,
         "price": 75000.0, "market_cap": 1.5e12},
        {"timestamp": 1745991300000, "bitcoin_dominance": 60.40,
         "price": 75500.0, "market_cap": 1.51e12},
    ]})
    rows = cg.fetch_btc_dominance(interval="1d", limit=2)
    assert len(rows) == 2
    assert rows[0]["metric_name"] == "btc_dominance"
    assert rows[0]["metric_value"] == 60.36
    assert rows[0]["timestamp"].endswith("Z")


def test_coinglass_etf_flow_parses_response():
    cg = CoinglassCollector.__new__(CoinglassCollector)
    cg._request = MagicMock(return_value={"code": "0", "data": [
        {"timestamp": 1745991240000, "flow_usd": 12345678.9,
         "price_usd": 75000.0, "etf_flows": [{"a": 1}]},
    ]})
    rows = cg.fetch_etf_flow_history(interval="1d", limit=1)
    assert len(rows) == 1
    assert rows[0]["metric_name"] == "etf_flow"
    assert rows[0]["metric_value"] == 12345678.9
    # 不应包含 etf_flows 子数组
    assert "etf_flows" not in rows[0]


def test_coinglass_etf_flow_path_etf_before_bitcoin():
    """1.6 spec:alphanode 真路径是 /api/etf/bitcoin/...(etf 在 bitcoin 之前)"""
    assert "/etf/bitcoin/flow-history" in CoinglassCollector._PATH_ETF_FLOW
    assert "/index/bitcoin-dominance" in CoinglassCollector._PATH_BTC_DOMINANCE


# ============================================================
# C — aSOPR 角色升级到 primary
# ============================================================

def test_asopr_role_upgraded_to_primary():
    """1.6 catalog:asopr.role_in_v1 = 'primary'(1.6 之前是 'display')。"""
    catalog_path = Path(__file__).resolve().parent.parent / "config" / "data_catalog.yaml"
    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    factors = catalog.get("single_factors") or []
    asopr = next((f for f in factors if f.get("name") == "asopr"), None)
    assert asopr is not None, "data_catalog.yaml 缺 asopr 因子"
    assert asopr["role_in_v1"] == "primary", (
        f"1.6 升级:asopr.role_in_v1 应为 primary,实际 {asopr['role_in_v1']}"
    )


def test_asopr_layer_l3():
    """1.6 升级:asopr 进 L3 机会执行层(替代 SOPR 在 cycle_position)。"""
    catalog_path = Path(__file__).resolve().parent.parent / "config" / "data_catalog.yaml"
    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    asopr = next(f for f in catalog["single_factors"] if f["name"] == "asopr")
    assert asopr["layer"] == "L3"


# ============================================================
# E — factor_card_emitter 9 张新卡
# ============================================================

def _series(value: float, ts: str = "2026-04-30T00:00:00Z") -> pd.Series:
    return pd.Series([value], index=pd.to_datetime([ts], utc=True))


def test_emit_v13_new_factors_returns_9_cards():
    from src.strategy.factor_card_emitter import _emit_v13_new_factors
    onchain = {
        "sth_supply": _series(2_500_000.0),
        "lth_mvrv": _series(2.0),
        "sth_mvrv": _series(1.05),
        "ssr": _series(8.5),
        "cdd": _series(1_500_000.0),
        "sopr_adjusted": _series(1.012),
        "hodl_waves_1y_2y": _series(0.11),
        "hodl_waves_more_10y": _series(0.08),
    }
    derivatives = {
        "etf_flow": _series(123_456_789.0),
        "btc_dominance": _series(60.36),
    }
    cards = _emit_v13_new_factors(onchain, derivatives, "20260430")
    assert len(cards) == 9
    names = {c["name"] for c in cards}
    expected = {
        "STH Supply", "LTH-MVRV", "STH-MVRV", "SSR",
        "HODL Waves (>1y)", "CDD", "aSOPR",
        "ETF Flows", "Bitcoin Dominance",
    }
    assert names == expected


def test_emit_v13_lth_mvrv_card_uses_computed_source():
    from src.strategy.factor_card_emitter import _emit_v13_new_factors
    cards = _emit_v13_new_factors(
        onchain={"lth_mvrv": _series(2.0)}, derivatives={}, today="20260430",
    )
    lth_card = next(c for c in cards if c["name"] == "LTH-MVRV")
    assert lth_card["source"] == "computed"


def test_emit_v13_etf_flow_l5_layer():
    from src.strategy.factor_card_emitter import _emit_v13_new_factors
    cards = _emit_v13_new_factors(
        onchain={}, derivatives={"etf_flow": _series(1e8)}, today="20260430",
    )
    etf_card = next(c for c in cards if c["name"] == "ETF Flows")
    assert etf_card["linked_layer"] == "L5"


def test_emit_v13_hodl_waves_aggregates_long_buckets():
    from src.strategy.factor_card_emitter import _emit_v13_new_factors
    onchain = {
        "hodl_waves_1y_2y": _series(0.10),
        "hodl_waves_2y_3y": _series(0.05),
        "hodl_waves_3y_5y": _series(0.10),
        "hodl_waves_5y_7y": _series(0.06),
        "hodl_waves_7y_10y": _series(0.08),
        "hodl_waves_more_10y": _series(0.15),
    }
    cards = _emit_v13_new_factors(onchain, {}, "20260430")
    hodl = next(c for c in cards if c["name"] == "HODL Waves (>1y)")
    # 求和 0.10+0.05+0.10+0.06+0.08+0.15 = 0.54 → 54%
    assert abs(hodl["current_value"] - 54.0) < 0.5


# ============================================================
# F — scheduler/jobs.py 注册新 fetcher
# ============================================================

def test_glassnode_fetchers_registered_in_jobs():
    from src.scheduler.jobs import _GLASSNODE_FETCHERS
    new_fetchers = ("fetch_sth_supply", "fetch_ssr",
                    "fetch_cdd", "fetch_hodl_waves")
    for fn in new_fetchers:
        assert fn in _GLASSNODE_FETCHERS, (
            f"src/scheduler/jobs.py:_GLASSNODE_FETCHERS 缺 {fn}"
        )


def test_jobs_module_imports_clean():
    """1.6 改动后 jobs.py 必须能 import 不报错。"""
    import importlib
    import src.scheduler.jobs as j
    importlib.reload(j)
    assert hasattr(j, "job_collect_onchain")
    assert hasattr(j, "job_collect_klines_daily")


# ============================================================
# OnchainSource Literal 含 'computed'(支持本地派生写入)
# ============================================================

def test_onchain_source_literal_includes_computed():
    """1.6:OnchainSource Literal 必须扩展 'computed' 否则 dataclass 验证拒。"""
    import typing
    from src.data.storage import dao as dao_mod
    args = typing.get_args(dao_mod.OnchainSource)
    assert "computed" in args, (
        f"OnchainSource 应含 'computed',实际 {args}"
    )


# ============================================================
# Sprint 1.6.1 任务 B:细粒度今日门 — Sprint C 已废弃为 ≥ 1 一手 Glassnode 行
#   原 4 个测试覆盖的"全 13 metric 都写过才 skip"语义已过时,
#   新逻辑测试在 tests/test_jobs_fetch_attempts_integration.py。
# ============================================================


def test_has_today_btc_dominance_or_etf_flow_detects_extras(tmp_path: Path):
    """derivatives_snapshots full_data_json 含 btc_dominance/etf_flow → True。"""
    import json
    from src.scheduler.jobs import _has_today_btc_dominance_or_etf_flow
    from datetime import datetime, timezone
    db = tmp_path / "deriv.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ts = today + "T00:00:00Z"
        # 写一行带 btc_dominance 的 snapshot
        conn.execute(
            "INSERT INTO derivatives_snapshots "
            "(captured_at_utc, full_data_json, inserted_at_utc) "
            "VALUES (?, ?, ?)",
            (ts, json.dumps({"btc_dominance": 60.36}), ts),
        )
        conn.commit()
        assert _has_today_btc_dominance_or_etf_flow(conn) is True
    finally:
        conn.close()


def test_has_today_btc_dominance_or_etf_flow_false_when_missing(tmp_path: Path):
    """空 derivatives_snapshots → False(继续 fetch)。"""
    from src.scheduler.jobs import _has_today_btc_dominance_or_etf_flow
    db = tmp_path / "deriv_empty.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        assert _has_today_btc_dominance_or_etf_flow(conn) is False
    finally:
        conn.close()


# ============================================================
# Sprint 1.6.1 任务 C:CoinGlass 新 metric e2e 入 DB 验证
# ============================================================

def test_coinglass_btc_dominance_writes_to_derivatives_snapshots(tmp_path: Path):
    """端到端:CoinGlass btc_dominance fetch 后通过 DerivativesDAO.upsert_batch
    入 derivatives_snapshots 表 full_data_json extras。

    daily timestamp guard 1.5f-revised:metric_value 仍写入但 timestamp
    必须 endswith 'T00:00:00Z'。CoinGlass 1d bar 天然落 UTC 00:00。
    """
    from src.data.storage.dao import DerivativeMetric, DerivativesDAO
    db = tmp_path / "cg_e2e.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        # 模拟 fetch_btc_dominance 返回 daily 行
        metrics = [
            DerivativeMetric(
                timestamp="2026-04-30T00:00:00Z",  # daily,通过 guard
                metric_name="btc_dominance",
                metric_value=60.36,
            ),
        ]
        n = DerivativesDAO.upsert_batch(conn, metrics)
        conn.commit()
        assert n >= 1, f"upsert 应 ≥1,实际 {n}"

        # 验证 full_data_json extras 含 btc_dominance(因为不是 wide column)
        row = conn.execute(
            "SELECT full_data_json FROM derivatives_snapshots "
            "WHERE captured_at_utc = '2026-04-30T00:00:00Z'"
        ).fetchone()
        assert row is not None
        assert "btc_dominance" in (row["full_data_json"] or "")
        # 数值正确(JSON 解析)
        import json
        extras = json.loads(row["full_data_json"])
        assert abs(extras["btc_dominance"] - 60.36) < 0.01
    finally:
        conn.close()


def test_coinglass_etf_flow_writes_to_derivatives_snapshots(tmp_path: Path):
    """同上,etf_flow 写入。"""
    from src.data.storage.dao import DerivativeMetric, DerivativesDAO
    db = tmp_path / "etf_e2e.db"
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        metrics = [
            DerivativeMetric(
                timestamp="2026-04-30T00:00:00Z",
                metric_name="etf_flow",
                metric_value=12345678.9,
            ),
        ]
        DerivativesDAO.upsert_batch(conn, metrics)
        conn.commit()

        row = conn.execute(
            "SELECT full_data_json FROM derivatives_snapshots "
            "WHERE captured_at_utc = '2026-04-30T00:00:00Z'"
        ).fetchone()
        assert row is not None
        import json
        extras = json.loads(row["full_data_json"])
        assert abs(extras["etf_flow"] - 12345678.9) < 1.0
    finally:
        conn.close()


def test_job_collect_klines_daily_calls_btc_dominance_and_etf_flow():
    """1.6.1 §X 反退化:job_collect_klines_daily 必须调 fetch_btc_dominance
    + fetch_etf_flow_history(被 1.6 commit f6cc795 加进来,确保未来不被回退)。"""
    src = (
        Path(__file__).resolve().parent.parent / "src" / "scheduler" / "jobs.py"
    ).read_text(encoding="utf-8")
    # 在 job_collect_klines_daily 函数体内必须 reference 这两个 fetcher 名
    # (静态字符串检查比 mock 更稳)
    daily_section_start = src.find("def job_collect_klines_daily(")
    assert daily_section_start > 0
    daily_section_end = src.find("def job_collect_klines_weekly(", daily_section_start)
    assert daily_section_end > daily_section_start
    daily_body = src[daily_section_start:daily_section_end]
    assert "fetch_btc_dominance" in daily_body, (
        "1.6.1:job_collect_klines_daily 必须调 fetch_btc_dominance"
    )
    assert "fetch_etf_flow_history" in daily_body, (
        "1.6.1:job_collect_klines_daily 必须调 fetch_etf_flow_history"
    )
