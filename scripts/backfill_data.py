"""
scripts/backfill_data.py — Sprint 1.5c C7:冷启动 180 天历史回填(建模 §8.10)。

v0.1 启动前必须运行一次,把过去 180 天的行情 / 衍生品 / 链上 / 宏观数据
拉齐入库(price_candles / derivatives_snapshots / onchain_metrics /
macro_metrics)。之后 scheduled 运行只增量拉最近一根。

用法:
    uv run python scripts/backfill_data.py              # 默认 180 天
    uv run python scripts/backfill_data.py --days 30    # 快速测试
    uv run python scripts/backfill_data.py --dry-run    # 不写库
    uv run python scripts/backfill_data.py --only price # 只回填价格

幂等:upsert 语义,已有数据会被覆盖但不重复计数。已有记录跳过则只记 count。
日志:每个数据源的 fetched / upserted / elapsed_ms。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

# 保证直接 python 运行也能 import src.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import _env_loader  # noqa: F401
from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import (
    BTCKlinesDAO, DerivativeMetric, DerivativesDAO,
    KlineRow, MacroDAO, MacroMetric, OnchainDAO, OnchainMetric,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill")


_ALL_CATEGORIES: tuple[str, ...] = (
    "price", "derivatives", "onchain", "macro",
)


# ============================================================
# Helpers
# ============================================================

def _elapsed_ms(start: float) -> int:
    return int((time.time() - start) * 1000)


def _log_stage(name: str, fetched: int, upserted: int, ms: int) -> None:
    logger.info(
        "[%s] fetched=%d upserted=%d elapsed_ms=%d",
        name, fetched, upserted, ms,
    )


def _safe(fn: Callable[[], Any], name: str) -> Any:
    """包装调用,失败只打日志不抛。"""
    try:
        return fn()
    except Exception as e:
        logger.error("[%s] failed: %s: %s", name, type(e).__name__, e)
        return None


# ============================================================
# Price candles(CoinGlass)
# ============================================================

def backfill_price(conn, *, days: int, dry_run: bool) -> None:
    from src.data.collectors.coinglass import CoinglassCollector
    try:
        coll = CoinglassCollector()
    except Exception as e:
        logger.error("[price] cannot init CoinGlass collector: %s", e)
        return

    # 每个 timeframe 拉 N 根:days → bars
    horizons: dict[str, int] = {
        "1h": min(days * 24, 2000),
        "4h": min(days * 6, 1000),
        "1d": days,
        "1w": max(1, days // 7),
    }
    for tf, limit in horizons.items():
        start = time.time()
        rows = _safe(
            lambda: coll.fetch_klines(interval=tf, limit=limit),
            f"price.{tf}",
        ) or []
        if not rows:
            _log_stage(f"price.{tf}", 0, 0, _elapsed_ms(start))
            continue
        klines = [
            KlineRow(
                timeframe=tf, timestamp=r["timestamp"],
                open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                volume_btc=r.get("volume", 0.0) or 0.0,
            )
            for r in rows
        ]
        if dry_run:
            _log_stage(f"price.{tf}", len(rows), 0, _elapsed_ms(start))
            continue
        upserted = BTCKlinesDAO.upsert_klines(conn, klines)
        conn.commit()
        _log_stage(f"price.{tf}", len(rows), upserted, _elapsed_ms(start))


# ============================================================
# Derivatives(CoinGlass)
# ============================================================

def backfill_derivatives(conn, *, days: int, dry_run: bool) -> None:
    from src.data.collectors.coinglass import CoinglassCollector
    try:
        coll = CoinglassCollector()
    except Exception as e:
        logger.error("[derivatives] cannot init CoinGlass collector: %s", e)
        return

    # 用 1d 粒度,够 180 天
    limit = min(days, 500)
    fetches: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "funding_rate": lambda: coll.fetch_funding_rate_history(
            interval="1d", limit=limit,
        ),
        "long_short_ratio": lambda: coll.fetch_long_short_ratio_history(
            interval="1d", limit=limit,
        ),
    }
    for name, fn in fetches.items():
        start = time.time()
        rows = _safe(fn, f"derivatives.{name}") or []
        if not rows:
            _log_stage(f"derivatives.{name}", 0, 0, _elapsed_ms(start))
            continue
        metrics = [
            DerivativeMetric(
                timestamp=r["timestamp"],
                metric_name=r.get("metric_name", name),
                metric_value=r.get("metric_value"),
            )
            for r in rows
        ]
        if dry_run:
            _log_stage(f"derivatives.{name}", len(rows), 0, _elapsed_ms(start))
            continue
        upserted = DerivativesDAO.upsert_batch(conn, metrics)
        conn.commit()
        _log_stage(f"derivatives.{name}", len(rows), upserted, _elapsed_ms(start))


# ============================================================
# Onchain(Glassnode)
# ============================================================

def backfill_onchain(conn, *, days: int, dry_run: bool) -> None:
    try:
        from src.data.collectors.glassnode import GlassnodeCollector
        coll = GlassnodeCollector()
    except Exception as e:
        logger.error("[onchain] cannot init Glassnode collector: %s", e)
        return

    # Sprint 2.4:GlassnodeCollector 公共方法都接受 since_days: int,
    # 不再接 since/until datetime。统一走 since_days=days。
    fetches: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "mvrv_z_score": lambda: coll.fetch_mvrv_z_score(since_days=days),
        "nupl": lambda: coll.fetch_nupl(since_days=days),
        "lth_supply": lambda: coll.fetch_lth_supply(since_days=days),
        "exchange_net_flow": lambda: coll.fetch_exchange_net_flow(since_days=days),
        "mvrv": lambda: coll.fetch_mvrv(since_days=days),
        "realized_price": lambda: coll.fetch_realized_price(since_days=days),
        "sopr": lambda: coll.fetch_sopr(since_days=days),
        "reserve_risk": lambda: coll.fetch_reserve_risk(since_days=days),
        "puell_multiple": lambda: coll.fetch_puell_multiple(since_days=days),
    }
    for name, fn in fetches.items():
        start = time.time()
        rows = _safe(fn, f"onchain.{name}") or []
        if not rows:
            _log_stage(f"onchain.{name}", 0, 0, _elapsed_ms(start))
            continue
        metrics = [
            OnchainMetric(
                timestamp=r["timestamp"],
                metric_name=r.get("metric_name", name),
                metric_value=r.get("metric_value"),
                source=r.get("source", "glassnode_primary"),
            )
            for r in rows
        ]
        if dry_run:
            _log_stage(f"onchain.{name}", len(rows), 0, _elapsed_ms(start))
            continue
        upserted = OnchainDAO.upsert_batch(conn, metrics)
        conn.commit()
        _log_stage(f"onchain.{name}", len(rows), upserted, _elapsed_ms(start))


# ============================================================
# Macro(FRED 唯一主源,Sprint 2.6-A.4 起)
# ============================================================

def backfill_macro(conn, *, days: int, dry_run: bool) -> None:
    """Sprint 2.6-A.4:Yahoo 已弃用(腾讯云 IP 被全局 429 封禁),FRED 是唯一
    macro 主源,覆盖 dxy/vix/sp500/nasdaq/dgs10/dff/cpi/unemployment_rate 共 8 个字段。
    无 key 时 `enabled=False`,优雅 skip。
    """
    # ---- FRED(无 key 优雅 skip) ----
    try:
        from src.data.collectors.fred import FredCollector
        fred_coll = FredCollector()
        if not fred_coll.enabled:
            logger.info("[macro.fred] FRED_API_KEY not set, skip")
            return
        start = time.time()
        if dry_run:
            logger.info("[macro.fred] dry_run skip")
        else:
            stats = fred_coll.collect_and_save_all(conn, since_days=days)
            conn.commit()  # Sprint 2.6-A.1:同上,显式提交否则数据丢失
            total = sum(
                v for k, v in stats.items()
                if isinstance(v, int) and not k.startswith("__")
            )
            _log_stage("macro.fred", total, total, _elapsed_ms(start))
            for metric, n in stats.items():
                if not metric.startswith("__"):
                    logger.info("  macro.fred.%s upserted=%d", metric, n)
    except Exception as e:
        logger.error("[macro.fred] failed: %s", e)


# ============================================================
# main
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill historical data")
    parser.add_argument("--days", type=int, default=180,
                        help="Number of days to back-fill (default 180)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch but don't write DB")
    parser.add_argument("--only", choices=_ALL_CATEGORIES + ("all",),
                        default="all",
                        help="Limit to a single category")
    args = parser.parse_args()

    init_db(verbose=False)
    conn = get_connection()
    try:
        total_start = time.time()
        logger.info("=== Backfill starting (days=%d, dry_run=%s, only=%s) ===",
                    args.days, args.dry_run, args.only)

        if args.only in ("all", "price"):
            backfill_price(conn, days=args.days, dry_run=args.dry_run)
        if args.only in ("all", "derivatives"):
            backfill_derivatives(conn, days=args.days, dry_run=args.dry_run)
        if args.only in ("all", "onchain"):
            backfill_onchain(conn, days=args.days, dry_run=args.dry_run)
        if args.only in ("all", "macro"):
            backfill_macro(conn, days=args.days, dry_run=args.dry_run)

        logger.info("=== Backfill done (total %d ms) ===",
                    _elapsed_ms(total_start))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
