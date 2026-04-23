"""
coinglass.py — CoinGlass 统一数据采集器(K 线 + 所有衍生品)

架构(Sprint 1.2 v2,2026-04-23):
  - **BTC K 线**:此 collector 是主数据源(因美国 IP 下 Binance 全线不可用)
  - **所有衍生品**:funding rate / open interest / long-short / liquidation / net_position
  - 共享中转站:https://api.alphanode.work(与 Glassnode 同域名)
  - 鉴权:HTTP header "x-key"(小写连字符)
  - 限速:15 req/min(旧系统 RateLimiter 参数)
  - 路径前缀:/v4/api/(旧格式,中转站自动映射到 CoinGlass 新 API)

字段名契约:见 `_field_extractors.py`,**来自旧系统 utils_common.py 实际验证过**。
每个 fetch 方法请求前记录 URL+params,响应后记录行数+首行 keys,便于 debug。
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
from ._field_extractors import (
    FUNDING_RATE_VALUE_KEYS,
    LIQUIDATION_LONG_KEYS,
    LIQUIDATION_SHORT_KEYS,
    LONG_SHORT_RATIO_LONG_PCT_KEYS,
    LONG_SHORT_RATIO_SHORT_PCT_KEYS,
    LONG_SHORT_RATIO_VALUE_KEYS,
    NET_POSITION_LONG_KEYS,
    NET_POSITION_SHORT_KEYS,
    OPEN_INTEREST_VALUE_KEYS,
    TIMESTAMP_KEYS,
    extract_value,
)


logger = logging.getLogger(__name__)


# -------- 常量 -------------------------------------------------------

_VALID_INTERVALS: tuple[str, ...] = ("1h", "4h", "1d", "1w")
_USER_AGENT: str = "btc_swing_system/0.1"

# 日志里展示首行 keys 时的截断长度
_KEYS_PREVIEW_LIMIT: int = 20


class CoinglassCollectorError(RuntimeError):
    """CoinGlass 采集器的统一异常类型(对外最终抛出)。"""


class _RetryableHTTPError(Exception):
    """内部异常:HTTP 状态码落在 retry_on_status 列表,应走重试。"""


# ====================================================================
# 时间戳 & OHLC 规范化(通用)
# ====================================================================

def _normalize_timestamp(value: Any) -> str:
    """ms int / 秒 int / ISO string / 数字字符串 → ISO 8601 UTC('Z' 后缀)。"""
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e12 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return _normalize_timestamp(int(s))
        try:
            float(s)
            return _normalize_timestamp(float(s))
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError as e:
            raise ValueError(f"Cannot parse timestamp {value!r}") from e
    raise ValueError(f"Unsupported timestamp type: {type(value).__name__}={value!r}")


def _guess_timestamp(row: dict[str, Any]) -> str:
    """从 row 中找时间戳字段,返回 ISO 8601 UTC。"""
    for key in TIMESTAMP_KEYS:
        if key in row and row[key] is not None:
            return _normalize_timestamp(row[key])
    raise KeyError(f"No timestamp field in row: {list(row.keys())}")


def _normalize_ohlc_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    把一行 OHLC 响应统一化成 {timestamp, open, high, low, close, volume}。
    字段名变体:open/o、high/h、low/l、close/c/value、volume/v/vol。
    """

    def pick(*keys: str, default: Any = 0) -> Any:
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


# ====================================================================
# CoinglassCollector
# ====================================================================

class CoinglassCollector:
    """
    CoinGlass 数据采集器 —— BTC K 线主数据源 + 所有衍生品。

    字段名严格对齐 `_field_extractors.py`(来自旧系统 utils_common.py 验证过)。
    params 按 Sprint 1.2 v2 fieldfix 的契约构造;liquidation 端点有 4 组
    param 变体兜底(旧系统见过的 400 行为)。
    """

    # 所有端点路径
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

        self._rpm: int = int(
            (cfg.get("rate_limit") or {}).get("requests_per_minute") or 15
        )
        self._request_times: deque[float] = deque(maxlen=self._rpm)

        api_key: str = cfg.get("api_key") or ""
        if not api_key:
            logger.warning(
                "COINGLASS_API_KEY is empty; CoinGlass endpoints will likely 401. "
                "Set it in .env (same alphanode key as GLASSNODE_API_KEY)."
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
        """滑动窗口限速(1 分钟内最多 self._rpm 次)。"""
        now = time.monotonic()
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
        """HTTP 请求 + 重试;成功返回 JSON body,失败抛 CoinglassCollectorError。"""
        url = f"{self.base_url}{path}"
        max_attempts: int = int(self.retry_cfg.get("max_attempts", 3))
        backoff: float = float(self.retry_cfg.get("backoff_sec", 8))
        strategy: str = str(self.retry_cfg.get("backoff_strategy", "fixed"))
        retry_on_status: list[int] = list(
            self.retry_cfg.get("retry_on_status") or [408, 429, 500, 502, 503, 504]
        )

        logger.info("CoinGlass GET %s params=%s", url, params)

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

    def _try_request_variants(
        self, path: str, variants: list[dict[str, Any]]
    ) -> tuple[Any, dict[str, Any]]:
        """
        依次尝试多组 params,直到某组**非重试错误**(4xx)被消除。
        每组 params 都有完整的重试链。全部 variants 用尽抛最后一次错。

        Returns:
            (response_body, successful_params)
        """
        last_exc: Exception | None = None
        for i, params in enumerate(variants, start=1):
            try:
                body = self._request("GET", path, params=params)
                return body, params
            except CoinglassCollectorError as e:
                last_exc = e
                logger.warning(
                    "CoinGlass variant %d/%d failed on %s (params=%s): %s",
                    i, len(variants), path, params, e,
                )
                continue
        raise CoinglassCollectorError(
            f"All {len(variants)} CoinGlass variants failed on {path}; "
            f"last error: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # 响应 envelope 解析 + debug 日志
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap_data(body: Any) -> list[dict[str, Any]]:
        """CoinGlass 响应通常是 {code, msg, data: [...]};兜底多种形态。"""
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            if "data" in body:
                data = body["data"]
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    if "list" in data and isinstance(data["list"], list):
                        return data["list"]
                    return [data]
            if "list" in body and isinstance(body["list"], list):
                return body["list"]
        raise CoinglassCollectorError(
            f"Unexpected CoinGlass response shape: {type(body).__name__} / "
            f"keys={list(body)[:8] if isinstance(body, dict) else 'n/a'}"
        )

    def _log_response_shape(self, label: str, rows: list[dict[str, Any]]) -> None:
        """打印行数 + 首行 keys(方便发现新字段名变体)。"""
        n = len(rows)
        if n == 0:
            logger.info("  %s: 0 rows (empty data)", label)
            return
        first = rows[0] if isinstance(rows[0], dict) else {}
        keys = list(first.keys())[:_KEYS_PREVIEW_LIMIT]
        logger.info("  %s: %d rows; first-row keys=%s", label, n, keys)

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
        GET /v4/api/futures/price/history (params: symbol=BTCUSDT, exchange=Binance)

        Returns:
            list[{timestamp, open, high, low, close, volume}],timestamp 为 ISO UTC。
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
        self._log_response_shape(f"klines[{interval}]", rows)

        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                result.append(_normalize_ohlc_row(row))
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    "Skipping malformed kline row on %s: keys=%s (error: %s)",
                    interval, list(row)[:10] if isinstance(row, dict) else type(row), e,
                )
                continue
        return result

    # ==================================================================
    # B) 衍生品 —— 每个按旧系统真实契约单独实现
    # ==================================================================

    # ---- B.1 资金费率(响应 OHLC,取 close) --------------------------
    def fetch_funding_rate_history(
        self,
        interval: str = "1d",
        limit: int = 500,
        symbol: str = "BTCUSDT",
        exchange: str = "Binance",
    ) -> list[dict[str, Any]]:
        """
        GET /v4/api/futures/funding-rate/history
        响应是 OHLC 格式;取 close 作为 metric_value(该时段末 funding rate)。

        Returns:
            list[{timestamp, metric_name='funding_rate', metric_value}]
        """
        body = self._request(
            "GET", self._PATH_FUNDING,
            params={"symbol": symbol, "exchange": exchange,
                    "interval": interval, "limit": limit},
        )
        rows = self._unwrap_data(body)
        self._log_response_shape("funding_rate", rows)

        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = _guess_timestamp(row)
            except (KeyError, ValueError):
                continue
            value = extract_value(row, FUNDING_RATE_VALUE_KEYS)
            if value is None:
                logger.warning(
                    "Skipping funding_rate row at %s: no numeric value "
                    "(tried %s; keys=%s)", ts, FUNDING_RATE_VALUE_KEYS,
                    list(row)[:10],
                )
                continue
            result.append({
                "timestamp": ts,
                "metric_name": "funding_rate",
                "metric_value": value,
            })
        return result

    # ---- B.2 聚合 OI(响应 OHLC,取 close;symbol=BTC 不传 exchange)----
    def fetch_open_interest_history(
        self,
        interval: str = "1d",
        limit: int = 500,
        symbol: str = "BTC",        # 注意是 BTC 不是 BTCUSDT(聚合端点约定)
    ) -> list[dict[str, Any]]:
        """
        GET /v4/api/futures/open-interest/aggregated-history
        聚合跨交易所 OI,所以只传 symbol=BTC,不传 exchange。

        Returns:
            list[{timestamp, metric_name='open_interest', metric_value}]
        """
        body = self._request(
            "GET", self._PATH_OI,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        rows = self._unwrap_data(body)
        self._log_response_shape("open_interest", rows)

        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = _guess_timestamp(row)
            except (KeyError, ValueError):
                continue
            value = extract_value(row, OPEN_INTEREST_VALUE_KEYS)
            if value is None:
                logger.warning(
                    "Skipping open_interest row at %s: no numeric value "
                    "(tried %s; keys=%s)", ts, OPEN_INTEREST_VALUE_KEYS,
                    list(row)[:10],
                )
                continue
            result.append({
                "timestamp": ts,
                "metric_name": "open_interest",
                "metric_value": value,
            })
        return result

    # ---- B.3 多空比(主路径直接取比值,备用路径用 long_pct/short_pct 算)--
    def fetch_long_short_ratio_history(
        self,
        interval: str = "1d",
        limit: int = 500,
        symbol: str = "BTCUSDT",
        exchange: str = "Binance",
    ) -> list[dict[str, Any]]:
        """
        GET /v4/api/futures/global-long-short-account-ratio/history

        按旧系统验证过的优先级:先 10 个 ratio 字段名;都没有时再从
        long_pct / short_pct 计算(短边非零才算)。

        Returns:
            list[{timestamp, metric_name='long_short_ratio', metric_value}]
        """
        body = self._request(
            "GET", self._PATH_LONG_SHORT,
            params={"symbol": symbol, "exchange": exchange,
                    "interval": interval, "limit": limit},
        )
        rows = self._unwrap_data(body)
        self._log_response_shape("long_short_ratio", rows)

        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = _guess_timestamp(row)
            except (KeyError, ValueError):
                continue

            # 主路径:直接取 ratio
            ratio = extract_value(row, LONG_SHORT_RATIO_VALUE_KEYS)

            # 备用路径:long_pct / short_pct
            if ratio is None:
                long_pct = extract_value(row, LONG_SHORT_RATIO_LONG_PCT_KEYS)
                short_pct = extract_value(row, LONG_SHORT_RATIO_SHORT_PCT_KEYS)
                if long_pct is not None and short_pct is not None and short_pct > 0:
                    ratio = long_pct / short_pct

            if ratio is None:
                logger.warning(
                    "Skipping long_short_ratio row at %s: no ratio or pct pair "
                    "(keys=%s)", ts, list(row)[:10],
                )
                continue
            result.append({
                "timestamp": ts,
                "metric_name": "long_short_ratio",
                "metric_value": ratio,
            })
        return result

    # ---- B.4 清算(param variants 兜底) ----------------------------
    def fetch_liquidation_history(
        self,
        interval: str = "1d",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        GET /v4/api/futures/liquidation/history

        Params 变体(按旧系统验证过的兜底顺序):
          1. symbol=BTCUSDT, exchange=Binance, interval, limit
          2. pair=BTCUSDT,   exchange=Binance, interval, limit
          3. symbol=BTCUSDT,                    interval, limit
          4. pair=BTCUSDT,                      interval, limit

        Returns:
            每个时间戳最多 3 行(long / short / total):
            list[{timestamp, metric_name=liquidation_long|liquidation_short|liquidation_total,
                  metric_value}]
        """
        variants: list[dict[str, Any]] = [
            {"symbol": "BTCUSDT", "exchange": "Binance",
             "interval": interval, "limit": limit},
            {"pair": "BTCUSDT", "exchange": "Binance",
             "interval": interval, "limit": limit},
            {"symbol": "BTCUSDT", "interval": interval, "limit": limit},
            {"pair": "BTCUSDT", "interval": interval, "limit": limit},
        ]
        body, used_params = self._try_request_variants(self._PATH_LIQUIDATION, variants)
        rows = self._unwrap_data(body)
        logger.info("  liquidation: used params=%s", used_params)
        self._log_response_shape("liquidation", rows)

        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = _guess_timestamp(row)
            except (KeyError, ValueError):
                continue

            long_val = extract_value(row, LIQUIDATION_LONG_KEYS)
            short_val = extract_value(row, LIQUIDATION_SHORT_KEYS)

            if long_val is None and short_val is None:
                logger.warning(
                    "Skipping liquidation row at %s: no long/short value (keys=%s)",
                    ts, list(row)[:10],
                )
                continue

            if long_val is not None:
                result.append({
                    "timestamp": ts,
                    "metric_name": "liquidation_long",
                    "metric_value": long_val,
                })
            if short_val is not None:
                result.append({
                    "timestamp": ts,
                    "metric_name": "liquidation_short",
                    "metric_value": short_val,
                })
            # total = long + short(都 None 的上面已跳过;单边 None 算 0 进入总)
            total = (long_val or 0.0) + (short_val or 0.0)
            result.append({
                "timestamp": ts,
                "metric_name": "liquidation_total",
                "metric_value": total,
            })
        return result

    # ---- B.5 净持仓变化(long / short 两个 metric) -----------------
    def fetch_net_position_history(
        self,
        interval: str = "1d",
        limit: int = 500,
        symbol: str = "BTCUSDT",
        exchange: str = "Binance",
    ) -> list[dict[str, Any]]:
        """
        GET /v4/api/futures/net-position/history

        Returns:
            每个时间戳最多 2 行:
            list[{timestamp, metric_name=net_position_long|net_position_short,
                  metric_value}]
        """
        body = self._request(
            "GET", self._PATH_NET_POSITION,
            params={"symbol": symbol, "exchange": exchange,
                    "interval": interval, "limit": limit},
        )
        rows = self._unwrap_data(body)
        self._log_response_shape("net_position", rows)

        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = _guess_timestamp(row)
            except (KeyError, ValueError):
                continue

            long_val = extract_value(row, NET_POSITION_LONG_KEYS)
            short_val = extract_value(row, NET_POSITION_SHORT_KEYS)

            if long_val is None and short_val is None:
                logger.warning(
                    "Skipping net_position row at %s: no long/short value (keys=%s)",
                    ts, list(row)[:10],
                )
                continue

            if long_val is not None:
                result.append({
                    "timestamp": ts,
                    "metric_name": "net_position_long",
                    "metric_value": long_val,
                })
            if short_val is not None:
                result.append({
                    "timestamp": ts,
                    "metric_name": "net_position_short",
                    "metric_value": short_val,
                })
        return result

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
            {label: rows_upserted} 统计字典。其中衍生品端点的 rows_upserted 可能
            大于端点返回行数(liquidation 每个 ts 产生 3 行;net_position 产生 2 行)。
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
            ("funding_rate",     lambda: self.fetch_funding_rate_history()),
            ("open_interest",    lambda: self.fetch_open_interest_history()),
            ("long_short_ratio", lambda: self.fetch_long_short_ratio_history()),
            ("liquidation",      lambda: self.fetch_liquidation_history()),
            ("net_position",     lambda: self.fetch_net_position_history()),
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
                f"All {len(failures)} CoinGlass endpoints failed; "
                f"check network / base_url / key"
            )
        return stats
