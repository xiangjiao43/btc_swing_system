"""
glassnode.py — Glassnode 链上数据采集器(走 api.alphanode.work 中转)

架构(Sprint 1.3,2026-04-23):
  - 走 CoinGlass 同一中转站 https://api.alphanode.work
  - 鉴权 HTTP header "x-key"(小写连字符),GLASSNODE_API_KEY 常与
    COINGLASS_API_KEY 共用同一个 alphanode 中转 key
  - 路径前缀 /v1/metrics/...(Glassnode 原生路径,**与 CoinGlass 路径不同**)
  - 通用参数:{a: "BTC", i: "<interval>", s: <since_unix_sec>}
  - 响应:**裸 JSON 数组**(无 envelope),每行 {t, v}(t 是**秒**不是毫秒)
  - 限速 15 req/min(与 CoinGlass 一致)

覆盖建模 §3.6.3:
  - 第一类(primary 5):mvrv_z_score / nupl / lth_supply / exchange_net_flow /
    btc_price_close(后三者 + price 用于 indicators 层算 LTH 90d 变化 / ATH 跌幅)
  - 第二类(display,Sprint 1.7 后):mvrv / realized_price / sopr_adjusted
    (Sprint 1.7 删除 sopr / reserve_risk / puell_multiple:噪音因子,无 L 层引用)
  - Sprint 2.6-F.3:lth_realized_price / sth_realized_price 已删
    (Glassnode 不开放独立 endpoint,/v1/metrics/supply/{lth,sth}_realized_price
     皆 404,见 docs/cc_reports/sprint_2_6_chain_verify.md backlog)
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import deque
from typing import Any, Callable, Optional

import requests

from ..storage.dao import OnchainDAO, OnchainMetric
from ._config_loader import load_source_config
from ._field_extractors import safe_float
from ._timestamp import since_days_ago_unix, to_iso_utc


logger = logging.getLogger(__name__)


_USER_AGENT: str = "btc_swing_system/0.1-glassnode"
_KEYS_PREVIEW_LIMIT: int = 10


class GlassnodeCollectorError(RuntimeError):
    """Glassnode 采集器的统一异常类型。"""


class _RetryableHTTPError(Exception):
    """内部:可重试的 HTTP 错误。"""


# =====================================================================
# GlassnodeCollector
# =====================================================================

class GlassnodeCollector:
    """
    Glassnode 链上数据采集器。
    每个 metric 一个 fetch 方法;通过 `_fetch_series` 公共方法聚合逻辑。
    """

    _BASE_PATH = "/v1/metrics"

    # ---- Primary 5(主裁决)----
    _PATH_MVRV_Z             = f"{_BASE_PATH}/market/mvrv_z_score"
    _PATH_NUPL               = f"{_BASE_PATH}/indicators/net_unrealized_profit_loss"
    _PATH_LTH_SUPPLY         = f"{_BASE_PATH}/supply/lth_sum"
    _PATH_EXCHANGE_NET_FLOW  = f"{_BASE_PATH}/transactions/transfers_volume_exchanges_net"
    _PATH_PRICE_CLOSE        = f"{_BASE_PATH}/market/price_usd_close"

    # ---- Display 7(辅助)----
    _PATH_MVRV               = f"{_BASE_PATH}/market/mvrv"
    _PATH_REALIZED_PRICE     = f"{_BASE_PATH}/market/price_realized_usd"
    _PATH_SOPR               = f"{_BASE_PATH}/indicators/sopr"
    _PATH_SOPR_ADJUSTED      = f"{_BASE_PATH}/indicators/sopr_adjusted"

    # Sprint 2.6-I:LTH/STH realized price 通过 breakdowns 客户端聚合得出
    # (Glassnode 不开放独立的 lth_realized_price / sth_realized_price endpoint,
    #  但 alphanode 中转支持 Tier 3 的 /breakdowns/* 系列,我们用按年龄分桶的
    #  realized_price + supply 做加权平均)
    _PATH_PRICE_REALIZED_BY_AGE  = f"{_BASE_PATH}/breakdowns/price_realized_usd_by_age"
    _PATH_SUPPLY_BY_AGE          = f"{_BASE_PATH}/breakdowns/supply_by_age"

    # Sprint 1.6 (建模 v1.3 §2.4):新增 4 个链上端点
    _PATH_STH_SUPPLY             = f"{_BASE_PATH}/supply/sth_sum"
    _PATH_SSR                    = f"{_BASE_PATH}/indicators/ssr"
    _PATH_CDD                    = f"{_BASE_PATH}/indicators/cdd"
    _PATH_HODL_WAVES             = f"{_BASE_PATH}/supply/hodl_waves"

    # 155 天切分(行业惯例 LTH/STH 阈值)。
    # 3m_6m 桶包含 90-180 天,桶中点 135 天 < 155 天 → 归 STH(简化处理)
    _STH_BUCKETS: tuple[str, ...] = ("24h", "1d_1w", "1w_1m", "1m_3m", "3m_6m")
    _LTH_BUCKETS: tuple[str, ...] = (
        "6m_12m", "1y_2y", "2y_3y", "3y_5y", "5y_7y", "7y_10y", "more_10y",
    )

    def __init__(self) -> None:
        cfg = load_source_config("glassnode")
        if not cfg["enabled"]:
            logger.warning(
                "Glassnode source is disabled in data_sources.yaml; proceeding anyway"
            )

        self.base_url: str = (cfg["base_url"] or "").rstrip("/")
        if not self.base_url:
            raise GlassnodeCollectorError(
                "Glassnode base_url not resolved; check data_sources.yaml "
                "or GLASSNODE_BASE_URL env"
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
                "GLASSNODE_API_KEY is empty; Glassnode endpoints will likely 401. "
                "Set it in .env (may share value with COINGLASS_API_KEY)."
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
    # 限速 + 重试(与 CoinglassCollector 同款)
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        now = time.monotonic()
        cutoff = now - 60.0
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.popleft()
        if len(self._request_times) >= self._rpm:
            sleep_until = self._request_times[0] + 60.0 + 0.1
            wait = max(0.0, sleep_until - now)
            if wait > 0:
                logger.info(
                    "Glassnode rate limit reached (%d/min), sleeping %.1fs",
                    self._rpm, wait,
                )
                time.sleep(wait)
                now = time.monotonic()
        self._request_times.append(now)

    def _request(
        self, method: str, path: str, *, params: Optional[dict[str, Any]] = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        max_attempts: int = int(self.retry_cfg.get("max_attempts", 3))
        backoff: float = float(self.retry_cfg.get("backoff_sec", 3))
        strategy: str = str(self.retry_cfg.get("backoff_strategy", "exponential"))
        retry_on_status: list[int] = list(
            self.retry_cfg.get("retry_on_status") or [408, 429, 500, 502, 503, 504]
        )

        logger.info("Glassnode GET %s params=%s", url, params)

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
                    raise GlassnodeCollectorError(
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
                else:
                    delay = backoff
                logger.warning(
                    "Glassnode request failed (attempt %d/%d) %s: %s. Retrying in %.1fs",
                    attempt, max_attempts, path, e, delay,
                )
                time.sleep(delay)

        raise GlassnodeCollectorError(
            f"Glassnode request failed after {max_attempts} attempts: {url} "
            f"params={params}; last error: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # 响应解析
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap_data(body: Any) -> list[dict[str, Any]]:
        """
        Glassnode 原生响应是**裸 JSON 数组**。
        中转站有时会包一层 {data: [...]};兜底支持。
        """
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            if "data" in body and isinstance(body["data"], list):
                return body["data"]
            if "data" in body and body["data"] is None:
                return []
        raise GlassnodeCollectorError(
            f"Unexpected Glassnode response shape: {type(body).__name__}"
        )

    def _log_response_shape(self, label: str, rows: list[Any]) -> None:
        n = len(rows)
        if n == 0:
            logger.info("  %s: 0 rows (empty)", label)
            return
        first = rows[0] if isinstance(rows[0], dict) else {}
        keys = list(first.keys())[:_KEYS_PREVIEW_LIMIT]
        logger.info("  %s: %d rows; first-row keys=%s", label, n, keys)

    # ==================================================================
    # 公共 fetch 方法
    # ==================================================================

    def _fetch_series(
        self,
        path: str,
        metric_name: str,
        *,
        interval: str = "24h",
        since_days: Optional[int] = 180,
        source: str = "glassnode_primary",
    ) -> list[dict[str, Any]]:
        """
        通用"按 metric 抓时间序列"。
        每行映射到 `{timestamp, metric_name, metric_value, source}`,
        供 OnchainDAO.upsert_batch 写入。
        """
        params: dict[str, Any] = {"a": "BTC", "i": interval}
        if since_days and since_days > 0:
            params["s"] = since_days_ago_unix(since_days, unit="s")

        body = self._request("GET", path, params=params)
        rows = self._unwrap_data(body)
        self._log_response_shape(metric_name, rows)

        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            t_raw = row.get("t")
            if t_raw is None:
                logger.warning("Skipping %s row without 't': %s", metric_name, row)
                continue
            # Glassnode t 是**秒**
            try:
                ts = to_iso_utc(t_raw, unit="s")
            except ValueError as e:
                logger.warning("Skipping %s row with bad t=%r: %s", metric_name, t_raw, e)
                continue
            value = safe_float(row.get("v"))
            if value is None:
                # 有些端点 v 可能是 dict(多字段聚合);本 Sprint 只处理 scalar v
                logger.warning(
                    "Skipping %s row at %s: v is not numeric (v=%r)",
                    metric_name, ts, row.get("v"),
                )
                continue
            result.append({
                "timestamp": ts,
                "metric_name": metric_name,
                "metric_value": value,
                "source": source,
            })
        return result

    # ==================================================================
    # Sprint 2.6-I:LTH/STH realized price 客户端聚合
    # ==================================================================

    def _fetch_breakdown_by_age(
        self,
        path: str,
        label: str,
        *,
        interval: str = "24h",
        since_days: Optional[int] = 180,
    ) -> list[dict[str, Any]]:
        """抓 /breakdowns/* 端点(返回 row.o = {bucket: value} dict)。

        Returns list[{timestamp, buckets: dict[bucket→float]}]。
        """
        params: dict[str, Any] = {"a": "BTC", "i": interval}
        if since_days and since_days > 0:
            params["s"] = since_days_ago_unix(since_days, unit="s")
        body = self._request("GET", path, params=params)
        rows = self._unwrap_data(body)
        self._log_response_shape(label, rows)

        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            t_raw = row.get("t")
            if t_raw is None:
                continue
            try:
                ts = to_iso_utc(t_raw, unit="s")
            except (TypeError, ValueError):
                continue
            buckets = row.get("o")
            if not isinstance(buckets, dict):
                continue
            out.append({"timestamp": ts, "buckets": buckets})
        return out

    @classmethod
    def _aggregate_lth_sth_realized_price(
        cls,
        price_by_age: list[dict[str, Any]],
        supply_by_age: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """按 supply 加权聚合 → (lth_rows, sth_rows)。

        每个时间点公式:
            X_realized_price = Σ(price_bucket × supply_bucket) / Σ(supply_bucket)
            X ∈ {LTH, STH}, bucket ∈ 各自定义的桶集合

        缺数据(任一 bucket 的 price 或 supply 缺)→ 该 bucket 跳过,不影响其他 bucket。
        denom 为 0(全 bucket 缺数据)→ 该时间点跳过。
        """
        price_by_ts = {r["timestamp"]: r["buckets"] for r in price_by_age}
        supply_by_ts = {r["timestamp"]: r["buckets"] for r in supply_by_age}
        common_ts = sorted(set(price_by_ts) & set(supply_by_ts))

        lth_rows: list[dict[str, Any]] = []
        sth_rows: list[dict[str, Any]] = []
        for ts in common_ts:
            prices = price_by_ts[ts]
            supplies = supply_by_ts[ts]
            for label, bucket_set, out in (
                ("lth_realized_price", cls._LTH_BUCKETS, lth_rows),
                ("sth_realized_price", cls._STH_BUCKETS, sth_rows),
            ):
                num = 0.0
                denom = 0.0
                for b in bucket_set:
                    p = safe_float(prices.get(b))
                    s = safe_float(supplies.get(b))
                    if p is None or s is None or s <= 0:
                        continue
                    num += p * s
                    denom += s
                if denom > 0:
                    out.append({
                        "timestamp": ts,
                        "metric_name": label,
                        "metric_value": num / denom,
                        "source": "glassnode_derived_breakdown_by_age",
                    })
        return lth_rows, sth_rows

    def _fetch_lth_sth_realized_price(
        self, since_days: int = 180,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """单次拉两个 breakdown + 聚合。供 fetch_lth_realized_price /
        fetch_sth_realized_price 共用,避免重复 HTTP。

        实例级缓存键 (since_days,) — 同一次 collect_and_save_all 内两次调用只 1 组 HTTP。
        """
        cache = getattr(self, "_lth_sth_cache", None)
        if cache is None:
            cache = {}
            self._lth_sth_cache = cache  # type: ignore[attr-defined]
        key = ("lth_sth", int(since_days))
        if key in cache:
            return cache[key]
        price_data = self._fetch_breakdown_by_age(
            self._PATH_PRICE_REALIZED_BY_AGE,
            "price_realized_usd_by_age",
            since_days=since_days,
        )
        supply_data = self._fetch_breakdown_by_age(
            self._PATH_SUPPLY_BY_AGE,
            "supply_by_age",
            since_days=since_days,
        )
        result = self._aggregate_lth_sth_realized_price(price_data, supply_data)
        cache[key] = result
        return result

    def fetch_lth_realized_price(
        self, interval: str = "24h", since_days: int = 180,
    ) -> list[dict[str, Any]]:
        """LTH realized price(supply 加权聚合 ≥ 6m 桶)。"""
        lth, _ = self._fetch_lth_sth_realized_price(since_days=since_days)
        return lth

    def fetch_sth_realized_price(
        self, interval: str = "24h", since_days: int = 180,
    ) -> list[dict[str, Any]]:
        """STH realized price(supply 加权聚合 < 6m 桶,含 3m_6m)。"""
        _, sth = self._fetch_lth_sth_realized_price(since_days=since_days)
        return sth

    # ==================================================================
    # Primary 5(主裁决)
    # ==================================================================

    def fetch_mvrv_z_score(
        self, interval: str = "24h", since_days: int = 180
    ) -> list[dict[str, Any]]:
        return self._fetch_series(
            self._PATH_MVRV_Z, "mvrv_z_score",
            interval=interval, since_days=since_days,
            source="glassnode_primary",
        )

    def fetch_nupl(
        self, interval: str = "24h", since_days: int = 180
    ) -> list[dict[str, Any]]:
        return self._fetch_series(
            self._PATH_NUPL, "nupl",
            interval=interval, since_days=since_days,
            source="glassnode_primary",
        )

    def fetch_lth_supply(
        self, interval: str = "24h", since_days: int = 180
    ) -> list[dict[str, Any]]:
        return self._fetch_series(
            self._PATH_LTH_SUPPLY, "lth_supply",
            interval=interval, since_days=since_days,
            source="glassnode_primary",
        )

    def fetch_exchange_net_flow(
        self, interval: str = "24h", since_days: int = 180
    ) -> list[dict[str, Any]]:
        return self._fetch_series(
            self._PATH_EXCHANGE_NET_FLOW, "exchange_net_flow",
            interval=interval, since_days=since_days,
            source="glassnode_primary",
        )

    # ==================================================================
    # Sprint 1.6:链上 4 个新端点(建模 v1.3 §2.4)
    # ==================================================================

    def fetch_sth_supply(
        self, interval: str = "24h", since_days: int = 720,
    ) -> list[dict[str, Any]]:
        """STH(短持有者)总持仓 BTC,scalar v 单值。"""
        return self._fetch_series(
            self._PATH_STH_SUPPLY, "sth_supply",
            interval=interval, since_days=since_days,
            source="glassnode_primary",
        )

    def fetch_ssr(
        self, interval: str = "24h", since_days: int = 720,
    ) -> list[dict[str, Any]]:
        """Stablecoin Supply Ratio,OHLC 取 close。

        响应:row.o = {"o": open, "h": high, "l": low, "c": close} 或 row.o = scalar。
        实测 alphanode 返回 row.o 是 dict {"v": close} — 取 v;若为 scalar 直接返回。
        """
        body = self._request(
            "GET", self._PATH_SSR,
            params={"a": "BTC", "i": interval,
                    **({"s": since_days_ago_unix(since_days, unit="s")}
                       if since_days else {})},
        )
        rows = self._unwrap_data(body)
        self._log_response_shape("ssr", rows)
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            t_raw = row.get("t")
            if t_raw is None:
                continue
            try:
                ts = to_iso_utc(t_raw, unit="s")
            except (TypeError, ValueError):
                continue
            o = row.get("o")
            if isinstance(o, dict):
                # OHLC 字典:优先取 'c'(close),若无再取 'v'
                value = safe_float(o.get("c") if "c" in o else o.get("v"))
            else:
                value = safe_float(o if o is not None else row.get("v"))
            if value is None:
                continue
            out.append({
                "timestamp": ts, "metric_name": "ssr",
                "metric_value": value, "source": "glassnode_primary",
            })
        return out

    def fetch_cdd(
        self, interval: str = "24h", since_days: int = 720,
    ) -> list[dict[str, Any]]:
        """Coin Days Destroyed,scalar v。"""
        return self._fetch_series(
            self._PATH_CDD, "cdd",
            interval=interval, since_days=since_days,
            source="glassnode_primary",
        )

    # Sprint 1.6 任务 A.2:HODL Waves 入库方案 a — 拆 11+ 个独立 metric。
    # 理由:查询简单,不改 schema;1 行 / bucket / 时间戳,跟其他链上 metric
    # 同形态,前端 / picker / L 层都不需要特殊处理。
    _HODL_WAVES_BUCKETS: tuple[str, ...] = (
        "24h", "1d_1w", "1w_1m", "1m_3m", "3m_6m", "6m_12m",
        "1y_2y", "2y_3y", "3y_5y", "5y_7y", "7y_10y", "more_10y",
    )

    def fetch_hodl_waves(
        self, interval: str = "24h", since_days: int = 720,
    ) -> list[dict[str, Any]]:
        """HODL Waves:row.o 是 11+ bucket 的 dict。展开为多 metric。

        每个 bucket → metric_name=hodl_waves_<bucket>。response 中可能没有
        "more_10y"(早期数据),缺失时跳过该 bucket。
        """
        body = self._request(
            "GET", self._PATH_HODL_WAVES,
            params={"a": "BTC", "i": interval,
                    **({"s": since_days_ago_unix(since_days, unit="s")}
                       if since_days else {})},
        )
        rows = self._unwrap_data(body)
        self._log_response_shape("hodl_waves", rows)
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            t_raw = row.get("t")
            if t_raw is None:
                continue
            try:
                ts = to_iso_utc(t_raw, unit="s")
            except (TypeError, ValueError):
                continue
            buckets = row.get("o")
            if not isinstance(buckets, dict):
                continue
            for bucket in self._HODL_WAVES_BUCKETS:
                v = safe_float(buckets.get(bucket))
                if v is None:
                    continue  # 早期数据某些 bucket 可能不存在
                out.append({
                    "timestamp": ts,
                    "metric_name": f"hodl_waves_{bucket}",
                    "metric_value": v,
                    "source": "glassnode_primary",
                })
        return out

    def fetch_btc_price_and_ath(
        self, interval: str = "24h", since_days: int = 720
    ) -> list[dict[str, Any]]:
        """
        抓 720 天(约 2 年)BTC 收盘价;足够让 indicators 层计算 ATH 跌幅。
        ATH 本身的"历史最高价"由消费方在历史数据上计算,collector 只负责抓原始数据。
        """
        return self._fetch_series(
            self._PATH_PRICE_CLOSE, "btc_price_close",
            interval=interval, since_days=since_days,
            source="glassnode_primary",
        )

    # ==================================================================
    # Display 7(辅助)
    # ==================================================================

    def fetch_mvrv(
        self, interval: str = "24h", since_days: int = 180
    ) -> list[dict[str, Any]]:
        return self._fetch_series(
            self._PATH_MVRV, "mvrv",
            interval=interval, since_days=since_days,
            source="glassnode_display",
        )

    def fetch_realized_price(
        self, interval: str = "24h", since_days: int = 180
    ) -> list[dict[str, Any]]:
        return self._fetch_series(
            self._PATH_REALIZED_PRICE, "realized_price",
            interval=interval, since_days=since_days,
            source="glassnode_display",
        )

    def fetch_sopr(
        self, interval: str = "24h", since_days: int = 180
    ) -> list[dict[str, Any]]:
        return self._fetch_series(
            self._PATH_SOPR, "sopr",
            interval=interval, since_days=since_days,
            source="glassnode_display",
        )

    def fetch_sopr_adjusted(
        self, interval: str = "24h", since_days: int = 180
    ) -> list[dict[str, Any]]:
        return self._fetch_series(
            self._PATH_SOPR_ADJUSTED, "sopr_adjusted",
            interval=interval, since_days=since_days,
            source="glassnode_display",
        )

    # Sprint 1.7:fetch_reserve_risk / fetch_puell_multiple 已删除
    # (噪音因子,无 L 层引用)。

    # ==================================================================
    # 高层组合抓取
    # ==================================================================

    def collect_and_save_all(
        self, conn: sqlite3.Connection
    ) -> dict[str, int]:
        """
        抓 primary 5 + display 7 + btc_price_close(720d) = 13 个 metric。
        每个 metric 单独 try/except,失败的记录 error 但不中断。

        Returns:
            {metric_name: rows_upserted}
        """
        tasks: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
            # Primary 5
            ("mvrv_z_score",       self.fetch_mvrv_z_score),
            ("nupl",               self.fetch_nupl),
            ("lth_supply",         self.fetch_lth_supply),
            ("exchange_net_flow",  self.fetch_exchange_net_flow),
            ("btc_price_close",    self.fetch_btc_price_and_ath),
            # Display 7
            ("mvrv",               self.fetch_mvrv),
            ("realized_price",     self.fetch_realized_price),
            # Sprint 2.6-I:LTH/STH realized price 通过 breakdowns 聚合,
            # 共享 HTTP(实例缓存),所以两个注册项实际只产生 2 次 HTTP
            ("lth_realized_price", self.fetch_lth_realized_price),
            ("sth_realized_price", self.fetch_sth_realized_price),
            ("sopr",               self.fetch_sopr),
            ("sopr_adjusted",      self.fetch_sopr_adjusted),
            # Sprint 1.6(建模 v1.3 §2.4):4 个新链上端点
            ("sth_supply",         self.fetch_sth_supply),
            ("ssr",                self.fetch_ssr),
            ("cdd",                self.fetch_cdd),
            ("hodl_waves",         self.fetch_hodl_waves),
        ]

        stats: dict[str, int] = {}
        failures: list[str] = []

        for label, fetcher in tasks:
            try:
                raw = fetcher()
                metrics = [
                    OnchainMetric(
                        timestamp=r["timestamp"],
                        metric_name=r["metric_name"],
                        metric_value=r["metric_value"],
                        source=r["source"],      # type: ignore[arg-type]
                    )
                    for r in raw
                ]
                n = OnchainDAO.upsert_batch(conn, metrics)
                stats[label] = n
                logger.info("%s: upserted %d rows", label, n)
            except Exception as e:
                logger.error("%s failed: %s", label, e)
                failures.append(label)
                stats[label] = 0

        total = sum(stats.values())
        logger.info(
            "Glassnode collect_and_save_all done: total=%d rows, failures=%d/%d",
            total, len(failures), len(tasks),
        )
        if failures and len(failures) == len(tasks):
            raise GlassnodeCollectorError(
                f"All {len(failures)} Glassnode endpoints failed; "
                f"check network / base_url / key"
            )
        return stats
