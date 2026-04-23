"""
coinglass.py — CoinGlass 统一数据采集器(K 线 + 所有衍生品)

架构(Sprint 1.2 v2,2026-04-23):
  - **BTC K 线**:此 collector 是主数据源(因美国 IP 下 Binance 全线不可用)
  - **所有衍生品**:funding rate / open interest / long-short / liquidation / net_position
  - 共享中转站:https://api.alphanode.work(与 Glassnode 同域名)
  - 鉴权:HTTP header "x-key"(小写连字符)
  - 限速:15 req/min(旧系统 RateLimiter 参数)
  - 路径前缀:/v4/api/(旧格式,中转站自动映射到 CoinGlass 新 API)

对应建模:§3.6.1 K 线 + §3.6.2 衍生品;§3.2 M29 reference_timestamp;
           §10.4.2 data/ 模块职责。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests

from ..storage.dao import (
    BTCKlinesDAO,
    DerivativeMetric,
    DerivativesDAO,
    KlineRow,
)
from ._config_loader import load_source_config


logger = logging.getLogger(__name__)


# -------- 常量 -------------------------------------------------------

_VALID_INTERVALS: tuple[str, ...] = ("1h", "4h", "1d", "1w")
_USER_AGENT: str = "btc_swing_system/0.1"


class CoinglassCollectorError(RuntimeError):
    """CoinGlass 采集器的统一异常类型(对外最终抛出)。"""


class _RetryableHTTPError(Exception):
    """内部异常:HTTP 状态码落在 retry_on_status 列表,应走重试。"""


# ====================================================================
# 响应解析辅助(兼容字段名变体;参考旧系统 utils_common.py)
# ====================================================================

def _normalize_timestamp(value: Any) -> str:
    """
    时间戳规范化为 ISO 8601 UTC 字符串('Z' 后缀)。

    支持:
      - int/float 毫秒时间戳(> 1e12)或秒时间戳(< 1e12)
      - ISO 8601 字符串('2024-01-01T00:00:00Z' / '+00:00' 等变体)
      - 数字字符串('1704067200000')

    Raises:
        ValueError: 无法解析的输入。
    """
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e12 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    if isinstance(value, str):
        s = value.strip()
        # 先试数字字符串(ms 或 s)
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return _normalize_timestamp(int(s))
        try:
            float(s)
            return _normalize_timestamp(float(s))
        except ValueError:
            pass
        # ISO 解析
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError as e:
            raise ValueError(f"Cannot parse timestamp {value!r}") from e
    raise ValueError(f"Unsupported timestamp type: {type(value).__name__}={value!r}")


def _guess_timestamp(row: dict[str, Any]) -> str:
    """从 row 中找时间戳字段(候选:t / time / timestamp / ts / createTime)。"""
    for key in ("t", "time", "timestamp", "ts", "createTime", "create_time"):
        if key in row and row[key] is not None:
            return _normalize_timestamp(row[key])
    raise KeyError(f"No timestamp field in row: {list(row.keys())}")


def _normalize_ohlc_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    兼容 CoinGlass 不同版本的 OHLC 字段命名(o/h/l/c/v vs open/high/low/close/volume)。
    """

    def pick(*keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in row and row[k] is not None:
                return row[k]
        return default

    return {
        "timestamp": _guess_timestamp(row),
        "open":      float(pick("open", "o", default=0)),
        "high":      float(pick("high", "h", default=0)),
        "low":       float(pick("low", "l", default=0)),
        "close":     float(pick("close", "c", "value", default=0)),
        "volume":    float(pick("volume", "v", "vol", default=0)),
    }


def _extract_numeric(row: dict[str, Any], *candidates: str) -> Optional[float]:
    """按 candidates 顺序取第一个非 None 的字段,转 float。全都没有返回 None。"""
    for k in candidates:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return None


# ====================================================================
# CoinglassCollector
# ====================================================================

class CoinglassCollector:
    """
    CoinGlass 数据采集器 —— BTC K 线主数据源 + 所有衍生品。

    构造时从 config/data_sources.yaml 加载配置;COINGLASS_API_KEY 若未设置
    会 warning 但不抛错(允许部分端点降级,但大多端点需要 key)。
    """

    # 所有端点路径(旧格式前缀 /v4/api/,中转站自动映射)
    _PATH_KLINES        = "/v4/api/futures/price/history"
    _PATH_FUNDING       = "/v4/api/futures/funding-rate/history"
    _PATH_OI            = "/v4/api/futures/open-interest/aggregated-history"
    _PATH_LONG_SHORT    = "/v4/api/futures/global-long-short-account-ratio/history"
    _PATH_LIQUIDATION   = "/v4/api/futures/liquidation/history"
    _PATH_NET_POSITION  = "/v4/api/futures/net-position/history"

    def __init__(self) -> None:
        cfg = load_source_config("coinglass")
        if not cfg["enabled"]:
            logger.warning(
                "CoinGlass source is disabled in data_sources.yaml; proceeding anyway"
            )

        self.base_url: str = (cfg["base_url"] or "").rstrip("/")
        if not self.base_url:
            raise CoinglassCollectorError(
                "CoinGlass base_url not resolved; check data_sources.yaml "
                "or COINGLASS_BASE_URL env"
            )

        self.timeout_sec: int = int(cfg["timeout_sec"])
        self.retry_cfg: dict[str, Any] = cfg["retry"]

        # 限速:滑动窗口,1 分钟内最多 N 次请求
        self._rpm: int = int(
            (cfg.get("rate_limit") or {}).get("requests_per_minute") or 15
        )
        self._request_times: deque[float] = deque(maxlen=self._rpm)

        # API key 校验
        api_key: str = cfg.get("api_key") or ""
        if not api_key:
            logger.warning(
                "COINGLASS_API_KEY is empty; CoinGlass endpoints will likely 401. "
                "Set it in .env(same alphanode key as GLASSNODE_API_KEY)."
            )
        header_name: str = cfg.get("api_key_header_name") or "x-key"

        self._session: requests.Session = requests.Session()
        headers: dict[str, str] = {
            "accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if api_key:
            headers[header_name] = api_key
        self._session.headers.update(headers)

    # ------------------------------------------------------------------
    # 限速
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """
        滑动窗口限速(1 分钟内最多 self._rpm 次)。
        若达到上限,sleep 到窗口内最老请求超过 60s 为止。
        """
        now = time.monotonic()
        # 清除窗口外的记录
        cutoff = now - 60.0
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.popleft()
        if len(self._request_times) >= self._rpm:
            sleep_until = self._request_times[0] + 60.0 + 0.1
            wait = max(0.0, sleep_until - now)
            if wait > 0:
                logger.info(
                    "CoinGlass rate limit reached (%d/min), sleeping %.1fs",
                    self._rpm, wait,
                )
                time.sleep(wait)
                now = time.monotonic()
        self._request_times.append(now)

    # ------------------------------------------------------------------
    # HTTP 请求(重试 + 固定/指数退避)
    # ------------------------------------------------------------------

    def _request(
        self, method: str, path: str, *, params: Optional[dict[str, Any]] = None
    ) -> Any:
        """
        HTTP 请求 + 重试。
        成功返回 JSON body;失败抛 CoinglassCollectorError。
        """
        url = f"{self.base_url}{path}"
        max_attempts: int = int(self.retry_cfg.get("max_attempts", 3))
        backoff: float = float(self.retry_cfg.get("backoff_sec", 8))
        strategy: str = str(self.retry_cfg.get("backoff_strategy", "fixed"))
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
                    raise CoinglassCollectorError(
                        f"HTTP {resp.status_code} (non-retry) on {path}: "
                        f"{resp.text[:200]}"
                    )
                return resp.json()
            except (requests.RequestException, _RetryableHTTPError, ValueError) as e:
                last_exc = e
                if attempt >= max_attempts:
                    break
                if strategy == "exponential":
                    delay = backoff * (2 ** (attempt - 1))
                elif strategy == "linear":
                    delay = backoff * attempt
                else:  # fixed
                    delay = backoff
                logger.warning(
                    "CoinGlass request failed (attempt %d/%d) %s: %s. Retrying in %.1fs",
                    attempt, max_attempts, path, e, delay,
                )
                time.sleep(delay)

        raise CoinglassCollectorError(
            f"CoinGlass request failed after {max_attempts} attempts: {url} "
            f"params={params}; last error: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # 响应 envelope 解析
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap_data(body: Any) -> list[dict[str, Any]]:
        """
        CoinGlass 响应通常是 {code, msg, data: [...]}(有时是 {success, data})。
        返回 data 数组;非预期结构抛错。
        """
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            # 常见容错字段
            if "data" in body:
                data = body["data"]
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "list" in data and isinstance(data["list"], list):
                    return data["list"]
                if isinstance(data, dict):
                    # 单对象,包装成单元素 list
                    return [data]
            if "list" in body and isinstance(body["list"], list):
                return body["list"]
        raise CoinglassCollectorError(
            f"Unexpected CoinGlass response shape: {type(body).__name__} / "
            f"keys={list(body)[:8] if isinstance(body, dict) else 'n/a'}"
        )

    # ==================================================================
    # A) K 线
    # ==================================================================

    def fetch_klines(
        self,
        interval: str = "1d",
        limit: int = 500,
        symbol: str = "BTCUSDT",
        exchange: str = "Binance",
    ) -> list[dict[str, Any]]:
        """
        GET /v4/api/futures/price/history

        Returns:
            list[{timestamp, open, high, low, close, volume}]
            timestamp 为 ISO 8601 UTC 字符串。
        """
        if interval not in _VALID_INTERVALS:
            raise ValueError(
                f"Unsupported interval {interval!r}; expected {_VALID_INTERVALS}"
            )
        body = self._request(
            "GET", self._PATH_KLINES,
            params={"symbol": symbol, "exchange": exchange,
                    "interval": interval, "limit": limit},
        )
        rows = self._unwrap_data(body)
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                result.append(_normalize_ohlc_row(row))
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    "Skipping malformed kline row on %s: %s (error: %s)",
                    interval, list(row)[:5], e,
                )
                continue
        return result

    # ==================================================================
    # B) 衍生品
    # ==================================================================

    def _fetch_derivative_history(
        self,
        path: str,
        metric_name: str,
        *,
        interval: str,
        limit: int,
        symbol: str,
        exchange: Optional[str],
        value_keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        """
        通用"带时间序列的衍生品历史"抓取。
        返回 list[{timestamp, metric_name, metric_value}],缺值的行跳过。
        """
        params: dict[str, Any] = {
            "symbol": symbol, "interval": interval, "limit": limit,
        }
        if exchange:
            params["exchange"] = exchange
        body = self._request("GET", path, params=params)
        rows = self._unwrap_data(body)

        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = _guess_timestamp(row)
            except (KeyError, ValueError) as e:
                logger.warning("Skipping %s row without timestamp: %s", metric_name, e)
                continue
            value = _extract_numeric(row, *value_keys)
            if value is None:
                logger.warning(
                    "Skipping %s row without numeric value (%s) at %s",
                    metric_name, value_keys, ts,
                )
                continue
            result.append({
                "timestamp": ts,
                "metric_name": metric_name,
                "metric_value": value,
            })
        return result

    def fetch_funding_rate_history(
        self, interval: str = "1d", limit: int = 500,
        symbol: str = "BTCUSDT", exchange: str = "Binance",
    ) -> list[dict[str, Any]]:
        """GET /v4/api/futures/funding-rate/history"""
        return self._fetch_derivative_history(
            self._PATH_FUNDING, metric_name="funding_rate",
            interval=interval, limit=limit, symbol=symbol, exchange=exchange,
            value_keys=("fundingRate", "funding_rate", "rate", "value", "close", "c"),
        )

    def fetch_open_interest_history(
        self, interval: str = "1d", limit: int = 500, symbol: str = "BTC",
    ) -> list[dict[str, Any]]:
        """
        GET /v4/api/futures/open-interest/aggregated-history
        聚合跨交易所 OI,所以不传 exchange 参数。symbol 用 "BTC"(CoinGlass
        聚合端点约定)。
        """
        return self._fetch_derivative_history(
            self._PATH_OI, metric_name="open_interest",
            interval=interval, limit=limit, symbol=symbol, exchange=None,
            value_keys=("openInterest", "open_interest", "oi", "value",
                        "close", "c", "sumOpenInterest"),
        )

    def fetch_long_short_ratio_history(
        self, interval: str = "1d", limit: int = 500,
        symbol: str = "BTCUSDT", exchange: str = "Binance",
    ) -> list[dict[str, Any]]:
        """GET /v4/api/futures/global-long-short-account-ratio/history"""
        return self._fetch_derivative_history(
            self._PATH_LONG_SHORT, metric_name="long_short_ratio",
            interval=interval, limit=limit, symbol=symbol, exchange=exchange,
            value_keys=("longShortRatio", "long_short_ratio", "ratio", "value"),
        )

    def fetch_liquidation_history(
        self, interval: str = "1d", limit: int = 500, symbol: str = "BTC",
    ) -> list[dict[str, Any]]:
        """
        GET /v4/api/futures/liquidation/history
        多数响应会分 longLiquidation / shortLiquidation;这里取总和作单值,
        细分见后续 Sprint 扩展。
        """
        path = self._PATH_LIQUIDATION
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        body = self._request("GET", path, params=params)
        rows = self._unwrap_data(body)

        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = _guess_timestamp(row)
            except (KeyError, ValueError):
                continue
            long_liq = _extract_numeric(row, "longLiquidation", "long_liquidation",
                                         "longLiq", "long", "buyLiq")
            short_liq = _extract_numeric(row, "shortLiquidation", "short_liquidation",
                                          "shortLiq", "short", "sellLiq")
            total = _extract_numeric(row, "liquidation", "total", "value")
            if total is None:
                if long_liq is not None or short_liq is not None:
                    total = (long_liq or 0) + (short_liq or 0)
                else:
                    logger.warning("Skipping liquidation row without value at %s", ts)
                    continue
            result.append({
                "timestamp": ts, "metric_name": "liquidation", "metric_value": total,
            })
            # 拆分字段也保留,便于后续细分分析
            if long_liq is not None:
                result.append({
                    "timestamp": ts, "metric_name": "liquidation_long",
                    "metric_value": long_liq,
                })
            if short_liq is not None:
                result.append({
                    "timestamp": ts, "metric_name": "liquidation_short",
                    "metric_value": short_liq,
                })
        return result

    def fetch_net_position_history(
        self, interval: str = "1d", limit: int = 500,
        symbol: str = "BTCUSDT", exchange: str = "Binance",
    ) -> list[dict[str, Any]]:
        """GET /v4/api/futures/net-position/history"""
        return self._fetch_derivative_history(
            self._PATH_NET_POSITION, metric_name="net_position",
            interval=interval, limit=limit, symbol=symbol, exchange=exchange,
            value_keys=("netPosition", "net_position", "value", "close", "c"),
        )

    # ==================================================================
    # C) 高层组合抓取
    # ==================================================================

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def collect_and_save_all(
        self, conn: sqlite3.Connection,
    ) -> dict[str, int]:
        """
        一次跑完 K 线 4 档 + 5 个衍生品端点,全部 upsert 入库。
        单个端点失败记 error 并继续其他;**全部失败**才抛错。

        Returns:
            {label: rows_upserted} 统计字典。
        """
        stats: dict[str, int] = {}
        failures: list[str] = []

        fetched_at = self._now_iso()

        # -------- K 线 4 档 --------
        for interval in _VALID_INTERVALS:
            label = f"klines_{interval}"
            try:
                raw = self.fetch_klines(interval=interval, limit=500)
                klines = [
                    KlineRow(
                        timeframe=interval,                     # type: ignore[arg-type]
                        timestamp=r["timestamp"],
                        open=r["open"], high=r["high"],
                        low=r["low"], close=r["close"],
                        volume_btc=r["volume"],
                        volume_usdt=None,
                        fetched_at=fetched_at,
                    )
                    for r in raw
                ]
                n = BTCKlinesDAO.upsert_klines(conn, klines)
                stats[label] = n
                logger.info("%s: upserted %d rows", label, n)
            except Exception as e:
                logger.error("%s failed: %s", label, e)
                failures.append(label)
                stats[label] = 0

        # -------- 衍生品 5 端点 --------
        derivatives_tasks: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
            ("funding_rate",      lambda: self.fetch_funding_rate_history()),
            ("open_interest",     lambda: self.fetch_open_interest_history()),
            ("long_short_ratio",  lambda: self.fetch_long_short_ratio_history()),
            ("liquidation",       lambda: self.fetch_liquidation_history()),
            ("net_position",      lambda: self.fetch_net_position_history()),
        ]

        for label, fetcher in derivatives_tasks:
            try:
                raw = fetcher()
                metrics = [
                    DerivativeMetric(
                        timestamp=r["timestamp"],
                        metric_name=r["metric_name"],
                        metric_value=r["metric_value"],
                        fetched_at=fetched_at,
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

        total = sum(stats.values())
        logger.info(
            "CoinGlass collect_and_save_all done: total=%d rows, failures=%d/%d",
            total, len(failures), len(stats),
        )
        if failures and len(failures) == len(stats):
            raise CoinglassCollectorError(
                f"All {len(failures)} CoinGlass endpoints failed; check network / base_url / key"
            )
        return stats
