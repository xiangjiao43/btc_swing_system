"""
yahoo_finance.py — Yahoo Finance 宏观数据采集器

对应建模 §3.6.4。直连 Yahoo,不走中转站,不需要 API key。
使用 yfinance 库。

Sprint 2.6-A.3:重构为"批量主路径 + per-symbol fallback"。
单次 yf.download(tickers_list, ...) 拉所有 6 symbol → 走 yfinance 内部批量
节流路径,绕开 per-symbol 循环连发触发的 429 限速。
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import pandas as pd
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
    # 主路径:批量调用(yf.download)
    # ------------------------------------------------------------------

    def fetch_all_symbols_batch(
        self, since_days: int = 365,
    ) -> dict[str, list[dict[str, Any]]]:
        """Sprint 2.6-A.3:批量拉所有 symbol,避开 per-symbol 429。

        单次 yf.download(tickers_list, ...) 让 yfinance 内部走批量节流路径,
        绕开 per-symbol HTTP 循环引发的 IP 级速率限制。

        Returns:
            {metric_name: [{timestamp, metric_name, metric_value}, ...]}
            未拿到数据的 metric 不出现在 dict 中(由调用方决定 fallback)

        Raises:
            YahooCollectorError: yf.download 完全失败 / 全部空
        """
        symbols = list(self.symbol_map.keys())
        if not symbols:
            return {}

        logger.info(
            "Yahoo BATCH download: %d symbols, period=%dd",
            len(symbols), since_days,
        )

        try:
            df = yf.download(
                tickers=symbols,
                period=f"{since_days}d",
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=False,
            )
        except Exception as e:
            raise YahooCollectorError(f"yf.download batch failed: {e}")

        if df is None or df.empty:
            raise YahooCollectorError("yf.download returned empty DataFrame")

        result: dict[str, list[dict[str, Any]]] = {}
        is_multi = isinstance(df.columns, pd.MultiIndex)
        for symbol in symbols:
            metric_name = self.symbol_map[symbol]
            try:
                sub_df = df[symbol] if is_multi else df
                close_series = sub_df.get("Close")
                if close_series is None or close_series.dropna().empty:
                    logger.warning(
                        "Yahoo batch: %s (%s) no Close data",
                        metric_name, symbol,
                    )
                    continue

                rows: list[dict[str, Any]] = []
                for idx, val in close_series.items():
                    try:
                        ts = to_iso_utc(idx)
                    except (ValueError, TypeError) as ex:
                        logger.warning(
                            "skipping %s row idx=%r: %s", symbol, idx, ex,
                        )
                        continue
                    close = safe_float(val)
                    if close is None:
                        continue
                    rows.append({
                        "timestamp": ts,
                        "metric_name": metric_name,
                        "metric_value": close,
                    })

                if rows:
                    result[metric_name] = rows
                    logger.info(
                        "  %s (%s): %d rows", metric_name, symbol, len(rows),
                    )
                else:
                    logger.warning(
                        "Yahoo batch: %s (%s) no valid rows after parse",
                        metric_name, symbol,
                    )
            except KeyError:
                logger.warning(
                    "Yahoo batch: %s (%s) not in result columns",
                    metric_name, symbol,
                )
            except Exception as e:
                logger.warning(
                    "Yahoo batch: %s (%s) parse failed: %s",
                    metric_name, symbol, e,
                )

        if not result:
            raise YahooCollectorError("Yahoo batch returned 0 valid metrics")
        return result

    # ------------------------------------------------------------------
    # 高层组合抓取(批量主 + per-symbol fallback)
    # ------------------------------------------------------------------

    def collect_and_save_all(
        self, conn: sqlite3.Connection, since_days: int = 365
    ) -> dict[str, int]:
        """Sprint 2.6-A.3:批量主路径 + per-symbol fallback。

        策略:
          1. 先 fetch_all_symbols_batch(单次 yf.download)
          2. batch 整体失败 → 对每个 symbol fallback fetch_symbol
          3. batch 部分成功 → 对未拿到的 symbol 单独 fetch_symbol

        Returns:
            {metric_name: rows_upserted}

        Raises:
            YahooCollectorError: batch + fallback 都全失败
        """
        stats: dict[str, int] = {}

        # ===== 主路径:批量 =====
        batch_result: dict[str, list[dict[str, Any]]] = {}
        try:
            batch_result = self.fetch_all_symbols_batch(since_days=since_days)
            logger.info(
                "Yahoo batch path succeeded for %d/%d metrics",
                len(batch_result), len(self.symbol_map),
            )
        except YahooCollectorError as e:
            logger.warning(
                "Yahoo batch path failed (%s); falling back to per-symbol", e,
            )

        # 写入 batch 成功的部分
        for metric_name, raw_rows in batch_result.items():
            try:
                metrics = [
                    MacroMetric(
                        timestamp=r["timestamp"],
                        metric_name=r["metric_name"],
                        metric_value=r["metric_value"],
                        source="yahoo_finance",
                    )
                    for r in raw_rows
                ]
                n = MacroDAO.upsert_batch(conn, metrics)
                stats[metric_name] = n
                logger.info("%s: upserted %d rows (batch path)",
                            metric_name, n)
            except Exception as e:
                logger.error("%s: write failed (batch path): %s",
                             metric_name, e)
                stats[metric_name] = 0

        # ===== Fallback:对未成功的 metric 单独 per-symbol 尝试 =====
        missing_symbols = [
            sym for sym, metric in self.symbol_map.items()
            if metric not in batch_result
        ]
        if missing_symbols:
            logger.info(
                "Yahoo per-symbol fallback for %d missing: %s",
                len(missing_symbols), missing_symbols,
            )
            for symbol in missing_symbols:
                metric = self.symbol_map[symbol]
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
                    logger.info("%s: upserted %d rows (fallback path)",
                                metric, n)
                except Exception as e:
                    logger.error("%s (symbol=%s) fallback failed: %s",
                                 metric, symbol, e)
                    stats[metric] = 0

        total = sum(stats.values())
        successes = sum(1 for v in stats.values() if v > 0)
        logger.info(
            "Yahoo Finance collect done: total=%d rows, %d/%d metrics succeeded",
            total, successes, len(self.symbol_map),
        )
        if successes == 0:
            raise YahooCollectorError(
                f"All {len(self.symbol_map)} Yahoo metrics failed "
                "(batch + fallback both)"
            )
        return stats
