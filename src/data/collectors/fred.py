"""
fred.py — FRED(美联储经济数据)采集器

对应建模 §3.6.4。直连 FRED 官方 API,需要免费注册拿 API key。

Sprint 2.6-A.4:覆盖 layer5_macro.py 全部 8 个核心字段,包括
dxy / vix / sp500 / nasdaq(FRED 是这些指数的官方权威数据源)。
原 Yahoo Finance 路径已弃用 — 腾讯云 IP 被 Yahoo 全局 429 封禁,
FRED 是当前唯一可用的 macro 主源。

如果 FRED_API_KEY 为空,collect_and_save_all 返回 {} 并 warning,**不报错**。
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from ..storage.dao import MacroDAO, MacroMetric
from ._field_extractors import safe_float


logger = logging.getLogger(__name__)


class FredCollectorError(RuntimeError):
    """FRED 采集器的统一异常。"""


# series_id → metric_name 映射
# Sprint 2.6-A.4:扩展覆盖 layer5_macro.py 全部 8 个核心字段(原 Yahoo 字段
# 全部由 FRED 接管,因为 Yahoo Finance 在腾讯云 IP 被全局 429 封禁)
SERIES_TO_METRIC: dict[str, str] = {
    # 利率类
    "DGS10":    "dgs10",              # 10-year Treasury yield(daily)
    "DFF":      "dff",                # Federal funds rate(daily)
    # 通胀 / 就业
    "CPIAUCSL": "cpi",                # CPI all urban consumers(monthly)
    "UNRATE":   "unemployment_rate",  # Unemployment rate(monthly)
    # 股指(Sprint 2.6-A.4 新增,FRED 是 SP500 / NASDAQ 的官方数据源)
    "SP500":    "sp500",              # S&P 500(daily,~10 年历史)
    "NASDAQCOM": "nasdaq",            # NASDAQ Composite(daily,1971-至今)
    # 波动率与美元(Sprint 2.6-A.4 新增)
    "VIXCLS":   "vix",                # CBOE VIX(daily,1990-至今)
    "DTWEXBGS": "dxy",                # Trade Weighted USD Index(Fed 官方版,语义等同 ICE DXY)
}

# Sprint 2.6-A.4:metric 别名 — 同一份 series 数据写多个 metric_name。
# layer5_macro.py 同时期望 us10y 和 dgs10(都是 10 年期国债收益率,语义等同),
# 这里把 DGS10 的 fetched rows 也复制一份为 us10y 写入。
_METRIC_ALIASES: dict[str, list[str]] = {
    "dgs10": ["us10y"],
}


class FredCollector:
    """
    FRED 采集器。关键设计:**API key 未设置时优雅 skip**,不抛错。
    """

    _DEFAULT_BASE_URL = "https://api.stlouisfed.org/fred"
    _USER_AGENT = "btc_swing_system/0.1-fred"

    def __init__(self) -> None:
        self.api_key: str = os.getenv("FRED_API_KEY", "").strip()
        self.base_url: str = (
            os.getenv("FRED_BASE_URL") or self._DEFAULT_BASE_URL
        ).rstrip("/")
        self.enabled: bool = bool(self.api_key)

        if not self.enabled:
            logger.warning(
                "FRED_API_KEY not set; FredCollector will skip all fetches. "
                "Register free key at https://fred.stlouisfed.org/docs/api/api_key.html"
            )

        self._session: requests.Session = requests.Session()
        self._session.headers.update({
            "accept": "application/json",
            "User-Agent": self._USER_AGENT,
        })

    # ------------------------------------------------------------------
    # 单 series 抓取
    # ------------------------------------------------------------------

    def fetch_series(
        self, series_id: str, since_days: int = 365
    ) -> list[dict[str, Any]]:
        """
        GET /series/observations?series_id=<id>&api_key=<key>&file_type=json
            &observation_start=<YYYY-MM-DD>

        Returns:
            list[{timestamp, metric_name, metric_value}]
            FRED 用 "." 表示缺失,会被跳过。
        """
        if not self.enabled:
            logger.info("Skipping FRED %s (no API key)", series_id)
            return []

        metric_name = SERIES_TO_METRIC.get(series_id, series_id.lower())
        start_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime(
            "%Y-%m-%d"
        )
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start_date,
        }
        url = f"{self.base_url}/series/observations"
        logger.info("FRED GET %s series_id=%s start=%s", url, series_id, start_date)

        resp = self._session.get(url, params=params, timeout=20)
        if not resp.ok:
            raise FredCollectorError(
                f"FRED HTTP {resp.status_code} on {series_id}: {resp.text[:200]}"
            )
        body = resp.json()
        obs = body.get("observations") or []
        logger.info("  %s: %d observations; first keys=%s",
                    metric_name, len(obs), list(obs[0].keys())[:6] if obs else "empty")

        result: list[dict[str, Any]] = []
        for o in obs:
            raw_val = o.get("value")
            if raw_val is None or raw_val == "." or raw_val == "":
                continue
            value = safe_float(raw_val)
            if value is None:
                continue
            date = o.get("date")
            if not date:
                continue
            result.append({
                "timestamp": f"{date}T00:00:00Z",
                "metric_name": metric_name,
                "metric_value": value,
            })
        return result

    # ------------------------------------------------------------------
    # 高层组合抓取
    # ------------------------------------------------------------------

    def collect_and_save_all(
        self, conn: sqlite3.Connection, since_days: int = 365
    ) -> dict[str, int]:
        """
        抓 4 个 series。无 API key 时返回 {} 不报错(__skipped 占位)。

        Returns:
            {metric_name: rows_upserted} 或 {"__skipped": 0}
        """
        if not self.enabled:
            return {"__skipped": 0}

        stats: dict[str, int] = {}
        failures: list[str] = []

        for series_id, metric in SERIES_TO_METRIC.items():
            try:
                raw = self.fetch_series(series_id, since_days=since_days)
                metrics = [
                    MacroMetric(
                        timestamp=r["timestamp"],
                        metric_name=r["metric_name"],
                        metric_value=r["metric_value"],
                        source="fred",
                    )
                    for r in raw
                ]
                n = MacroDAO.upsert_batch(conn, metrics)
                stats[metric] = n
                logger.info("%s: upserted %d rows", metric, n)
                # Sprint 2.6-A.4:同份 series 写多个 metric_name 别名
                # (例如 DGS10 → 同时写 dgs10 和 us10y)
                for alias in _METRIC_ALIASES.get(metric, []):
                    alias_metrics = [
                        MacroMetric(
                            timestamp=r["timestamp"],
                            metric_name=alias,
                            metric_value=r["metric_value"],
                            source="fred",
                        )
                        for r in raw
                    ]
                    n_alias = MacroDAO.upsert_batch(conn, alias_metrics)
                    stats[alias] = n_alias
                    logger.info("%s (alias of %s): upserted %d rows",
                                alias, metric, n_alias)
            except Exception as e:
                logger.error("%s (series=%s) failed: %s", metric, series_id, e)
                failures.append(metric)
                stats[metric] = 0

        total = sum(stats.values())
        logger.info(
            "FRED collect done: total=%d rows, failures=%d/%d",
            total, len(failures), len(SERIES_TO_METRIC),
        )
        if failures and len(failures) == len(SERIES_TO_METRIC):
            raise FredCollectorError(
                f"All {len(failures)} FRED series failed; check API key or network"
            )
        return stats
