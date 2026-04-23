"""
binance.py — Binance 现货 + U 本位永续数据采集器

职责(纯"抓 + 存",不做指标计算):
  - 现货 K 线(1h / 4h / 1d / 1w) → btc_klines 表
  - 资金费率 → derivatives_snapshot(metric_name='funding_rate')
  - 未平仓量(当前 + 历史) → derivatives_snapshot
  - 多空账户比(散户/大户) → derivatives_snapshot
  - 基差(premium)→ derivatives_snapshot(metric_name='basis_premium_pct')

对应建模:§3.6.1 Binance 数据清单 / §3.2 M29 reference_timestamp /
           §10.4.2 data/ 模块职责。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from ..storage.dao import (
    BTCKlinesDAO,
    DerivativeMetric,
    DerivativesDAO,
    KlineRow,
    TimeFrame,
)
from ._config_loader import load_source_config


logger = logging.getLogger(__name__)


# -------- 常量(来自 §3.6.1 / data_catalog.yaml) -------------------

# 支持的 K 线 timeframe 与对应的 Binance interval 参数
_VALID_INTERVALS: tuple[str, ...] = ("1h", "4h", "1d", "1w")

# 每次请求间的强制间隔(秒);IP 级限流很宽,0.1s 足够保守
# (§data_catalog binance rate_limit.requests_per_minute=600 → 100ms/req)
_REQUEST_MIN_SPACING_SEC: float = 0.1

# 默认 User-Agent(§task 技术约束)
_USER_AGENT: str = "btc_swing_system/0.1"


class BinanceCollectorError(RuntimeError):
    """Binance 采集器的统一异常类型(对外最终抛出)。"""


class _RetryableHTTPError(Exception):
    """内部异常:HTTP 状态码落在 retry_on_status 列表,应走重试。"""


# =====================================================================
# BinanceCollector
# =====================================================================

class BinanceCollector:
    """
    Binance 公共行情采集器。
    构造时从 config/data_sources.yaml 加载配置;方法内按需调用端点。
    """

    def __init__(self) -> None:
        cfg = load_source_config("binance")
        if not cfg["enabled"]:
            logger.warning("Binance source is disabled in data_sources.yaml; proceeding anyway")

        # 两个 base_url:现货与 U 本位永续
        # cfg["base_url"] 若 env 被设置则用 env(中转站场景);否则走默认 api.binance.com
        self.base_url: str = (cfg["base_url"] or "").rstrip("/")
        self.futures_base_url: str = (cfg["futures_base_url"] or "").rstrip("/")
        if not self.base_url:
            raise BinanceCollectorError(
                "Binance base_url not resolved; check data_sources.yaml or BINANCE_BASE_URL env"
            )
        if not self.futures_base_url:
            raise BinanceCollectorError(
                "Binance futures_base_url not resolved; check data_sources.yaml "
                "or BINANCE_FUTURES_BASE_URL env"
            )

        self.timeout_sec: int = cfg["timeout_sec"]
        self.retry_cfg: dict[str, Any] = cfg["retry"]
        self._last_request_at: float = 0.0    # 单调时钟,用于 0.1s 节流

        # requests.Session 复用连接 + 共用 headers
        self._session: requests.Session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ------------------------------------------------------------------
    # HTTP 请求封装(重试 + 退避)
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """最小请求间隔节流。"""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _REQUEST_MIN_SPACING_SEC:
            time.sleep(_REQUEST_MIN_SPACING_SEC - elapsed)
        self._last_request_at = time.monotonic()

    def _request(
        self, method: str, url: str, *, params: Optional[dict[str, Any]] = None
    ) -> Any:
        """
        HTTP 请求 + 重试 + 指数退避。
        成功返回 JSON body;失败抛 BinanceCollectorError。

        重试条件:
          - requests 网络异常(Timeout / ConnectionError / ...)
          - HTTP 状态码落在 retry.retry_on_status 列表里
          - JSON 解析失败
        """
        max_attempts: int = int(self.retry_cfg.get("max_attempts", 3))
        backoff: float = float(self.retry_cfg.get("backoff_sec", 2))
        strategy: str = str(self.retry_cfg.get("backoff_strategy", "exponential"))
        retry_on_status: list[int] = list(
            self.retry_cfg.get("retry_on_status") or [408, 429, 500, 502, 503, 504]
        )

        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            self._throttle()
            try:
                resp = self._session.request(
                    method, url, params=params, timeout=self.timeout_sec
                )
                if resp.status_code in retry_on_status:
                    raise _RetryableHTTPError(
                        f"HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                if not resp.ok:
                    # 非重试类 HTTP 错误(如 400 参数错、451 地域限制)
                    # 立刻抛出,不进入重试循环。
                    raise BinanceCollectorError(
                        f"HTTP {resp.status_code} (non-retry): {resp.text[:200]}"
                    )
                return resp.json()
            except (requests.RequestException, _RetryableHTTPError, ValueError) as e:
                last_exc = e
                if attempt >= max_attempts:
                    break
                # 指数 / 线性 / 固定退避
                if strategy == "exponential":
                    delay = backoff * (2 ** (attempt - 1))
                elif strategy == "linear":
                    delay = backoff * attempt
                else:  # fixed
                    delay = backoff
                logger.warning(
                    "Binance request failed (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt, max_attempts, e, delay,
                )
                time.sleep(delay)

        raise BinanceCollectorError(
            f"Binance request failed after {max_attempts} attempts: {url} "
            f"params={params}; last error: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # 时间戳辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _ms_to_iso(ms: int) -> str:
        """Binance 毫秒时间戳 → ISO 8601 UTC 字符串('Z' 后缀)。"""
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ==================================================================
    # A) K 线抓取
    # ==================================================================

    def fetch_klines(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1d",
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        GET /api/v3/klines (现货)。

        Args:
            symbol:    交易对,默认 BTCUSDT。
            interval:  1h / 4h / 1d / 1w(§3.6.1 支持四档)。
            limit:     最多 1000;默认 500。
            start_time: 可选,毫秒时间戳(inclusive)。
            end_time:  可选,毫秒时间戳(inclusive)。

        Returns:
            list[{timestamp, open, high, low, close, volume_btc, volume_usdt, close_time}]
            timestamp / close_time 都是 ISO 8601 UTC 字符串。
        """
        if interval not in _VALID_INTERVALS:
            raise ValueError(f"Unsupported interval {interval!r}; expected {_VALID_INTERVALS}")
        url = f"{self.base_url}/api/v3/klines"
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        raw = self._request("GET", url, params=params)
        if not isinstance(raw, list):
            raise BinanceCollectorError(f"Unexpected klines response type: {type(raw)}")

        result: list[dict[str, Any]] = []
        for row in raw:
            # Binance klines array layout:
            # [openTime, open, high, low, close, volume, closeTime, quoteAssetVolume, ...]
            try:
                result.append({
                    "timestamp":     self._ms_to_iso(int(row[0])),
                    "open":          float(row[1]),
                    "high":          float(row[2]),
                    "low":           float(row[3]),
                    "close":         float(row[4]),
                    "volume_btc":    float(row[5]),   # base asset = BTC
                    "volume_usdt":   float(row[7]),   # quote asset = USDT
                    "close_time":    self._ms_to_iso(int(row[6])),
                })
            except (IndexError, ValueError, TypeError) as e:
                logger.warning("Skipping malformed kline row: %s (error: %s)", row, e)
                continue
        return result

    # ==================================================================
    # B) 衍生品抓取(U 本位永续 fapi)
    # ==================================================================

    def fetch_funding_rate(
        self, symbol: str = "BTCUSDT", limit: int = 500
    ) -> list[dict[str, Any]]:
        """
        GET /fapi/v1/fundingRate 历史资金费率(最多 1000)。
        每次结算 8h,limit=500 → 回看约 167 天。

        Returns:
            list[{timestamp, funding_rate, mark_price}]
        """
        url = f"{self.futures_base_url}/fapi/v1/fundingRate"
        params = {"symbol": symbol, "limit": limit}
        raw = self._request("GET", url, params=params)
        if not isinstance(raw, list):
            raise BinanceCollectorError(f"Unexpected fundingRate response: {type(raw)}")

        result: list[dict[str, Any]] = []
        for row in raw:
            try:
                result.append({
                    "timestamp":     self._ms_to_iso(int(row["fundingTime"])),
                    "funding_rate":  float(row["fundingRate"]),
                    "mark_price":    float(row["markPrice"]) if "markPrice" in row else None,
                })
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("Skipping malformed funding rate row: %s (error: %s)", row, e)
                continue
        return result

    def fetch_open_interest(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        """
        GET /fapi/v1/openInterest 当前未平仓(永续合约,BTC 计价)。

        Returns:
            {timestamp, open_interest_btc, symbol}
        """
        url = f"{self.futures_base_url}/fapi/v1/openInterest"
        raw = self._request("GET", url, params={"symbol": symbol})
        return {
            "timestamp":         self._ms_to_iso(int(raw["time"])),
            "open_interest_btc": float(raw["openInterest"]),
            "symbol":            raw.get("symbol", symbol),
        }

    def fetch_open_interest_hist(
        self,
        symbol: str = "BTCUSDT",
        period: str = "1d",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        GET /futures/data/openInterestHist 历史未平仓(按 period 聚合)。
        period ∈ {5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d};limit ≤ 500。

        Returns:
            list[{timestamp, sum_open_interest_btc, sum_open_interest_usdt}]
        """
        url = f"{self.futures_base_url}/futures/data/openInterestHist"
        params = {"symbol": symbol, "period": period, "limit": limit}
        raw = self._request("GET", url, params=params)
        if not isinstance(raw, list):
            raise BinanceCollectorError(f"Unexpected openInterestHist response: {type(raw)}")

        result: list[dict[str, Any]] = []
        for row in raw:
            try:
                result.append({
                    "timestamp":                self._ms_to_iso(int(row["timestamp"])),
                    "sum_open_interest_btc":    float(row["sumOpenInterest"]),
                    "sum_open_interest_usdt":   float(row["sumOpenInterestValue"]),
                })
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("Skipping malformed OI hist row: %s (error: %s)", row, e)
                continue
        return result

    def fetch_long_short_ratio(
        self,
        symbol: str = "BTCUSDT",
        period: str = "1d",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        GET /futures/data/globalLongShortAccountRatio 全账户多空比(散户 + 大户合计)。

        Returns:
            list[{timestamp, long_short_ratio, long_account_pct, short_account_pct}]
        """
        url = f"{self.futures_base_url}/futures/data/globalLongShortAccountRatio"
        params = {"symbol": symbol, "period": period, "limit": limit}
        raw = self._request("GET", url, params=params)
        if not isinstance(raw, list):
            raise BinanceCollectorError(f"Unexpected longShortRatio response: {type(raw)}")

        result: list[dict[str, Any]] = []
        for row in raw:
            try:
                result.append({
                    "timestamp":          self._ms_to_iso(int(row["timestamp"])),
                    "long_short_ratio":   float(row["longShortRatio"]),
                    "long_account_pct":   float(row["longAccount"]),
                    "short_account_pct":  float(row["shortAccount"]),
                })
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("Skipping malformed long/short row: %s (error: %s)", row, e)
                continue
        return result

    def fetch_basis(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        """
        GET /fapi/v1/premiumIndex 即时溢价指数(永续合约与指数价的偏离)。

        **注意**:这是**瞬时溢价**,不是建模 §3.7.2 所称的"基差年化"。
        年化基差需要用季度合约与永续合约差价 × (365 / days_to_expiry),
        本 Sprint 不实现季度合约价抓取。basis_premium_pct 可作为粗替代,
        编码期需评估与真实 basis 的相关性。

        Returns:
            {timestamp, mark_price, index_price, basis_premium_pct,
             last_funding_rate, next_funding_time}
        """
        url = f"{self.futures_base_url}/fapi/v1/premiumIndex"
        raw = self._request("GET", url, params={"symbol": symbol})
        mark = float(raw["markPrice"])
        index = float(raw["indexPrice"])
        premium = (mark - index) / index if index > 0 else 0.0
        return {
            "timestamp":          self._ms_to_iso(int(raw["time"])),
            "mark_price":         mark,
            "index_price":        index,
            "basis_premium_pct":  premium,
            "last_funding_rate":  float(raw.get("lastFundingRate", 0) or 0),
            "next_funding_time":  self._ms_to_iso(int(raw["nextFundingTime"]))
                                  if raw.get("nextFundingTime") else None,
        }

    # ==================================================================
    # C) 高层方法 —— 组合抓取 + 落库
    # ==================================================================

    def collect_and_save_all(
        self, conn: sqlite3.Connection, symbol: str = "BTCUSDT"
    ) -> dict[str, int]:
        """
        一次跑通全部 Binance 数据抓取 + 落 SQLite。
        遇到单个端点失败记 warning 并继续其他;全部失败才抛错。

        参数:
            conn:   已打开的 SQLite Connection。调用方负责 conn.commit()。
            symbol: 默认 BTCUSDT。

        Returns:
            {source_label: rows_inserted} 统计字典。
        """
        stats: dict[str, int] = {}
        failures: list[str] = []

        # --- 1. 现货 K 线(4 个 timeframe 各 500 条)---
        for interval in _VALID_INTERVALS:
            label = f"binance_klines_{interval}"
            try:
                raw = self.fetch_klines(symbol=symbol, interval=interval, limit=500)
                klines: list[KlineRow] = []
                fetched = self._now_iso()
                for k in raw:
                    klines.append(KlineRow(
                        timeframe=interval,       # type: ignore[arg-type]
                        timestamp=k["timestamp"],
                        open=k["open"], high=k["high"], low=k["low"], close=k["close"],
                        volume_btc=k["volume_btc"],
                        volume_usdt=k["volume_usdt"],
                        fetched_at=fetched,
                    ))
                n = BTCKlinesDAO.upsert_klines(conn, klines)
                stats[label] = n
                logger.info("%s: upserted %d rows", label, n)
            except Exception as e:
                logger.error("%s failed: %s", label, e)
                failures.append(label)
                stats[label] = 0

        # --- 2. 资金费率历史(最新 500 条)---
        label = "funding_rate_history"
        try:
            raw = self.fetch_funding_rate(symbol=symbol, limit=500)
            metrics = [
                DerivativeMetric(
                    timestamp=r["timestamp"],
                    metric_name="funding_rate",
                    metric_value=r["funding_rate"],
                )
                for r in raw
            ]
            n = DerivativesDAO.upsert_batch(conn, metrics)
            stats[label] = n
            logger.info("%s: upserted %d rows", label, n)
        except Exception as e:
            logger.error("%s failed: %s", label, e)
            failures.append(label)
            stats[label] = 0

        # --- 3. 当前未平仓(单点)---
        label = "open_interest_current"
        try:
            oi = self.fetch_open_interest(symbol=symbol)
            n = DerivativesDAO.upsert_batch(conn, [
                DerivativeMetric(
                    timestamp=oi["timestamp"],
                    metric_name="open_interest_btc",
                    metric_value=oi["open_interest_btc"],
                ),
            ])
            stats[label] = n
            logger.info("%s: upserted %d rows", label, n)
        except Exception as e:
            logger.error("%s failed: %s", label, e)
            failures.append(label)
            stats[label] = 0

        # --- 4. 历史未平仓(日级 500 条)---
        label = "open_interest_hist_daily"
        try:
            raw = self.fetch_open_interest_hist(symbol=symbol, period="1d", limit=500)
            metrics = []
            for r in raw:
                metrics.append(DerivativeMetric(
                    timestamp=r["timestamp"],
                    metric_name="open_interest_sum_btc",
                    metric_value=r["sum_open_interest_btc"],
                ))
                metrics.append(DerivativeMetric(
                    timestamp=r["timestamp"],
                    metric_name="open_interest_sum_usdt",
                    metric_value=r["sum_open_interest_usdt"],
                ))
            n = DerivativesDAO.upsert_batch(conn, metrics)
            stats[label] = n
            logger.info("%s: upserted %d rows", label, n)
        except Exception as e:
            logger.error("%s failed: %s", label, e)
            failures.append(label)
            stats[label] = 0

        # --- 5. 多空比(日级 500 条)---
        label = "long_short_ratio_daily"
        try:
            raw = self.fetch_long_short_ratio(symbol=symbol, period="1d", limit=500)
            metrics = []
            for r in raw:
                metrics.append(DerivativeMetric(
                    timestamp=r["timestamp"],
                    metric_name="long_short_ratio_global",
                    metric_value=r["long_short_ratio"],
                ))
            n = DerivativesDAO.upsert_batch(conn, metrics)
            stats[label] = n
            logger.info("%s: upserted %d rows", label, n)
        except Exception as e:
            logger.error("%s failed: %s", label, e)
            failures.append(label)
            stats[label] = 0

        # --- 6. 基差溢价(单点)---
        label = "basis_premium_current"
        try:
            b = self.fetch_basis(symbol=symbol)
            n = DerivativesDAO.upsert_batch(conn, [
                DerivativeMetric(
                    timestamp=b["timestamp"],
                    metric_name="basis_premium_pct",
                    metric_value=b["basis_premium_pct"],
                ),
                DerivativeMetric(
                    timestamp=b["timestamp"],
                    metric_name="mark_price_perp",
                    metric_value=b["mark_price"],
                ),
                DerivativeMetric(
                    timestamp=b["timestamp"],
                    metric_name="index_price",
                    metric_value=b["index_price"],
                ),
            ])
            stats[label] = n
            logger.info("%s: upserted %d rows", label, n)
        except Exception as e:
            logger.error("%s failed: %s", label, e)
            failures.append(label)
            stats[label] = 0

        # --- 汇总 ---
        total = sum(stats.values())
        logger.info(
            "Binance collect_and_save_all done: total=%d rows, failures=%d/%d endpoints",
            total, len(failures), len(stats),
        )
        if failures and len(failures) == len(stats):
            raise BinanceCollectorError(
                f"All {len(failures)} Binance endpoints failed; check network / base_url"
            )
        return stats
