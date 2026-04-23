"""
binance.py — Binance **K 线专用**采集器(Sprint 1.2 修正架构)

职责(纯"抓 + 存",不做指标计算):
  - 现货 K 线 1h / 4h / 1d / 1w → btc_klines 表

架构说明:
  * 2026-04-23 验证发现美国 IP 访问 api.binance.com 返回 HTTP 451(地域封禁)。
  * 旧系统经验:走 **data.binance.vision** 公开数据镜像,美国 IP 可访问,
    但只提供 K 线和历史数据,不提供衍生品端点。
  * 衍生品(funding_rate / open_interest / long_short_ratio / basis /
    put_call_ratio)全部改由 **CoinGlass collector**(Sprint 1.4)提供。
  * 本模块不再触碰 fapi.binance.com;相关 5 个 fetch_* 方法已删除。

对应建模:§3.6.1 K 线清单 / §3.2 M29 reference_timestamp / §10.4.2 data/。
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from ..storage.dao import BTCKlinesDAO, KlineRow
from ._config_loader import load_source_config


logger = logging.getLogger(__name__)


# -------- 常量(§3.6.1 / data_catalog.yaml)---------------------------

# 支持的 K 线 timeframe
_VALID_INTERVALS: tuple[str, ...] = ("1h", "4h", "1d", "1w")

# 每次请求间的强制间隔(秒);data.binance.vision 是 CDN,限流宽松
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
    Binance 现货 K 线采集器(仅 K 线,不含衍生品)。

    数据源:data.binance.vision(默认)或通过 BINANCE_BASE_URL 覆盖。
    衍生品:见 src.data.collectors.coinglass(Sprint 1.4 实现)。
    """

    def __init__(self) -> None:
        cfg = load_source_config("binance")
        if not cfg["enabled"]:
            logger.warning(
                "Binance source is disabled in data_sources.yaml; proceeding anyway"
            )

        # 单一 base_url;旧的 futures_base_url 已去除
        # cfg["base_url"] 若 env 被设置则用 env;否则走默认 data.binance.vision
        self.base_url: str = (cfg["base_url"] or "").rstrip("/")
        if not self.base_url:
            raise BinanceCollectorError(
                "Binance base_url not resolved; check data_sources.yaml "
                "or BINANCE_BASE_URL env"
            )

        self.timeout_sec: int = cfg["timeout_sec"]
        self.retry_cfg: dict[str, Any] = cfg["retry"]
        self._last_request_at: float = 0.0

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
        非重试 4xx(如 400 参数错、451 地域限制)立即失败,不进入重试循环。
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
                    raise BinanceCollectorError(
                        f"HTTP {resp.status_code} (non-retry): {resp.text[:200]}"
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
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

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
        拉取现货 K 线。

        端点:`{base_url}/api/v3/klines`
          - 默认 base_url = https://data.binance.vision(§旧系统验证架构)
          - 若用户在 .env 设 BINANCE_BASE_URL=https://api.binance.com(走代理),
            仍兼容;接口路径不变。

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
            raise ValueError(
                f"Unsupported interval {interval!r}; expected {_VALID_INTERVALS}"
            )
        url = f"{self.base_url}/api/v3/klines"
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
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
                logger.warning(
                    "Skipping malformed kline row: %s (error: %s)", row, e
                )
                continue
        return result

    # ==================================================================
    # B) 高层方法 —— K 线四档 + 落库
    # ==================================================================

    def collect_and_save_all(
        self, conn: sqlite3.Connection, symbol: str = "BTCUSDT"
    ) -> dict[str, int]:
        """
        抓取 4 档 K 线(1h / 4h / 1d / 1w)× 500 条,写入 btc_klines。
        遇到单个 timeframe 失败记 error 并继续其他;全部失败才抛错。

        Args:
            conn:   已打开的 SQLite Connection。调用方负责 conn.commit()。
            symbol: 默认 BTCUSDT。

        Returns:
            {timeframe: rows_inserted} 统计字典,例如
            {'1h': 500, '4h': 500, '1d': 500, '1w': 370}。
            1w 可能不足 500(BTC 交易历史有限)。
        """
        stats: dict[str, int] = {}
        failures: list[str] = []

        for interval in _VALID_INTERVALS:
            try:
                raw = self.fetch_klines(symbol=symbol, interval=interval, limit=500)
                fetched = self._now_iso()
                klines: list[KlineRow] = [
                    KlineRow(
                        timeframe=interval,       # type: ignore[arg-type]
                        timestamp=k["timestamp"],
                        open=k["open"], high=k["high"], low=k["low"], close=k["close"],
                        volume_btc=k["volume_btc"],
                        volume_usdt=k["volume_usdt"],
                        fetched_at=fetched,
                    )
                    for k in raw
                ]
                n = BTCKlinesDAO.upsert_klines(conn, klines)
                stats[interval] = n
                logger.info("klines[%s]: upserted %d rows", interval, n)
            except Exception as e:
                logger.error("klines[%s] failed: %s", interval, e)
                failures.append(interval)
                stats[interval] = 0

        total = sum(stats.values())
        logger.info(
            "Binance collect_and_save_all done: total=%d rows, failures=%d/%d timeframes",
            total, len(failures), len(_VALID_INTERVALS),
        )
        if failures and len(failures) == len(_VALID_INTERVALS):
            raise BinanceCollectorError(
                f"All {len(failures)} Binance timeframes failed; check network / base_url"
            )
        return stats
