"""
yahoo_finance.py — Yahoo Finance 宏观数据采集器

对应建模 §3.6.4。直连 Yahoo,不走中转站,不需要 API key。
使用 yfinance 库(封装了 yahoo_fin / finance API)。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import yfinance as yf

from ..storage.dao import MacroDAO, MacroMetric
from ._field_extractors import safe_float
from ._timestamp import to_iso_utc


logger = logging.getLogger(__name__)


class YahooCollectorError(RuntimeError):
    """Yahoo Finance 采集器的统一异常。"""


# symbol → metric_name 映射(建模规范)
SYMBOL_TO_METRIC: dict[str, str] = {
    "DX-Y.NYB": "dxy",
    "^TNX":     "us10y",
    "^VIX":     "vix",
    "^GSPC":    "sp500",
    "^IXIC":    "nasdaq",
    "GC=F":     "gold_price",
}


class YahooFinanceCollector:
    """
    Yahoo 宏观数据(DXY / US10Y / VIX / SP500 / Nasdaq / Gold)采集器。
    """

    def __init__(self) -> None:
        self.symbol_map = dict(SYMBOL_TO_METRIC)  # 可实例化后修改

    # ------------------------------------------------------------------
    # 单 symbol 抓取
    # ------------------------------------------------------------------

    def fetch_symbol(
        self, symbol: str, since_days: int = 365
    ) -> list[dict[str, Any]]:
        """
        抓单 symbol 的日线收盘价历史。

        Args:
            symbol: Yahoo 的 ticker(如 "^VIX", "DX-Y.NYB")
            since_days: 回看天数

        Returns:
            list[{timestamp, metric_name, metric_value}] —— metric_name 由
            self.symbol_map 推导,timestamp 为 ISO 8601 UTC。
        """
        metric_name = self.symbol_map.get(symbol)
        if metric_name is None:
            raise ValueError(f"Symbol {symbol!r} not in SYMBOL_TO_METRIC mapping")

        logger.info("Yahoo fetch %s (period=%dd)", symbol, since_days)
        ticker = yf.Ticker(symbol)
        # period 支持 "1d" / "1mo" / "365d" / "1y" 等;用 "Nd" 最灵活
        df = ticker.history(period=f"{since_days}d", interval="1d", auto_adjust=False)

        if df is None or df.empty:
            logger.warning("Yahoo %s returned empty DataFrame", symbol)
            return []

        logger.info(
            "  %s (symbol=%s): %d rows; columns=%s",
            metric_name, symbol, len(df), list(df.columns)[:10],
        )

        result: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            try:
                ts = to_iso_utc(idx)   # DatetimeIndex → ISO
            except (ValueError, TypeError) as e:
                logger.warning("Skipping %s row with bad index %r: %s",
                               symbol, idx, e)
                continue
            close = safe_float(row.get("Close"))
            if close is None:
                continue
            result.append({
                "timestamp": ts,
                "metric_name": metric_name,
                "metric_value": close,
            })
        return result

    # ------------------------------------------------------------------
    # 高层组合抓取
    # ------------------------------------------------------------------

    def collect_and_save_all(
        self, conn: sqlite3.Connection, since_days: int = 365
    ) -> dict[str, int]:
        """
        抓所有 6 个 symbol,写入 macro_snapshot,source='yahoo_finance'。
        单 symbol 失败继续其他;全部失败才抛错。

        Returns:
            {metric_name: rows_upserted}
        """
        stats: dict[str, int] = {}
        failures: list[str] = []

        for symbol, metric in self.symbol_map.items():
            try:
                raw = self.fetch_symbol(symbol, since_days=since_days)
                metrics = [
                    MacroMetric(
                        timestamp=r["timestamp"],
                        metric_name=r["metric_name"],
                        metric_value=r["metric_value"],
                        source="yahoo_finance",
                    )
                    for r in raw
                ]
                n = MacroDAO.upsert_batch(conn, metrics)
                stats[metric] = n
                logger.info("%s: upserted %d rows", metric, n)
            except Exception as e:
                logger.error("%s (symbol=%s) failed: %s", metric, symbol, e)
                failures.append(metric)
                stats[metric] = 0

        total = sum(stats.values())
        logger.info(
            "Yahoo Finance collect done: total=%d rows, failures=%d/%d",
            total, len(failures), len(self.symbol_map),
        )
        if failures and len(failures) == len(self.symbol_map):
            raise YahooCollectorError(
                f"All {len(failures)} Yahoo symbols failed; check network"
            )
        return stats
