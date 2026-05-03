"""
dao.py — Data Access Objects

Sprint 1.5c 对齐建模 §10.4 的 11 张表:
  strategy_runs, lifecycles, evidence_card_history, review_reports, alerts,
  fallback_events, kpi_snapshots, price_candles, derivatives_snapshots,
  onchain_metrics, macro_metrics(+ events_calendar 仍保留)

DAO 类名保持 Sprint 1 的命名(BTCKlinesDAO / StrategyStateDAO / 等),
但内部 SQL 已切到新表名 + 新列名;dataclass 字段名暂时保留做向后兼容。

所有 DAO 方法:
  - 第一个位置参数都是 sqlite3.Connection
  - 只执行单个逻辑操作,不隐式 commit;调用方决定 commit 时机
  - 新增数据用 upsert 语义
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Optional


logger = logging.getLogger(__name__)


# ============================================================
# Helpers
# ============================================================

def _utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串(Z 后缀,秒级)。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now_iso_ms() -> str:
    """Sprint 2.6-J:微秒精度的当前 UTC 时间字符串。

    用于 dataclass.fetched_at 默认值,持久化到 *_metrics 表的 inserted_at_utc 列。
    同一个 collector 一秒内 fetch 多个 metric 时,微秒能区分写入次序。
    格式:'2026-04-27T14:06:23.456789Z'
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


TimeFrame = Literal["1h", "4h", "1d", "1w"]
# Sprint 1.6:加 'computed' — LTH/STH-MVRV 本地计算(price/realized_price 比率)
OnchainSource = Literal[
    "glassnode_primary", "glassnode_display", "glassnode_delayed", "computed",
]
# Sprint 2.6-A.4:Yahoo 已弃用,FRED 是当前唯一可用 macro 主源。
# 历史 DB 中可能仍有 source='yahoo_finance' 的旧行(Sprint 2.4 backfill 残留),
# 不影响读取;新写入只会用 'fred'。
MacroSource = Literal["fred", "yahoo_finance"]
FallbackLevel = Literal["level_1", "level_2", "level_3"]
RunStatus = Literal["started", "completed", "failed", "fallback"]
EventTimezone = Literal["America/New_York", "UTC"]


# ============================================================
# Row dataclasses(便于类型化的批量插入)
# ============================================================

@dataclass(slots=True)
class KlineRow:
    timeframe: TimeFrame
    timestamp: str               # ISO 8601 UTC
    open: float
    high: float
    low: float
    close: float
    volume_btc: float
    volume_usdt: Optional[float] = None
    fetched_at: str = field(default_factory=_utc_now_iso_ms)


@dataclass(slots=True)
class DerivativeMetric:
    timestamp: str
    metric_name: str
    metric_value: Optional[float]
    fetched_at: str = field(default_factory=_utc_now_iso_ms)


@dataclass(slots=True)
class OnchainMetric:
    timestamp: str
    metric_name: str
    metric_value: Optional[float]
    source: OnchainSource
    fetched_at: str = field(default_factory=_utc_now_iso_ms)


@dataclass(slots=True)
class MacroMetric:
    timestamp: str
    metric_name: str
    metric_value: Optional[float]
    source: MacroSource
    fetched_at: str = field(default_factory=_utc_now_iso_ms)


@dataclass(slots=True)
class EventRow:
    event_id: str
    date: str                             # YYYY-MM-DD
    timezone: EventTimezone
    local_time: Optional[str]
    utc_trigger_time: Optional[str]
    event_type: str
    event_name: str
    impact_level: Optional[int]
    notes: Optional[str] = None


# ============================================================
# BTC K 线
# ============================================================

_DEFAULT_SYMBOL: str = "BTCUSDT"


class BTCKlinesDAO:
    """price_candles 表的 DAO(建模 §10.4,替代 Sprint 1 的 btc_klines)。

    Sprint 1.5c:symbol 固定 'BTCUSDT',timestamp → open_time_utc,
    volume_btc → volume;为了保持 Sprint 1 的 KlineRow 字段兼容,
    upsert 时忽略 volume_usdt / fetched_at;读取时 volume 同时映射到
    timestamp + volume_btc 别名供老代码沿用。
    """

    @staticmethod
    def upsert_klines(conn: sqlite3.Connection, klines: list[KlineRow]) -> int:
        # Sprint 2.6-J:把 dataclass.fetched_at(微秒精度系统侧 wall clock)
        # 写入 inserted_at_utc 列。ON CONFLICT 也更新,反映"最近一次 upsert"。
        sql = """
            INSERT INTO price_candles
                (symbol, timeframe, open_time_utc, open, high, low, close, volume,
                 inserted_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timeframe, open_time_utc) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                inserted_at_utc = excluded.inserted_at_utc
        """
        rows = [
            (_DEFAULT_SYMBOL, k.timeframe, k.timestamp,
             k.open, k.high, k.low, k.close, k.volume_btc,
             k.fetched_at)
            for k in klines
        ]
        cur = conn.executemany(sql, rows)
        return cur.rowcount

    @staticmethod
    def _map_row(r: dict[str, Any]) -> dict[str, Any]:
        """把 price_candles 行映射回 Sprint 1 字段名,使老代码无感。"""
        out = dict(r)
        if "open_time_utc" in out and "timestamp" not in out:
            out["timestamp"] = out["open_time_utc"]
        if "volume" in out and "volume_btc" not in out:
            out["volume_btc"] = out["volume"]
        return out

    @staticmethod
    def get_klines(
        conn: sqlite3.Connection,
        timeframe: TimeFrame,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        clauses = ["symbol = ?", "timeframe = ?"]
        params: list[Any] = [_DEFAULT_SYMBOL, timeframe]
        if start is not None:
            clauses.append("open_time_utc >= ?")
            params.append(start)
        if end is not None:
            clauses.append("open_time_utc <= ?")
            params.append(end)
        sql = f"""
            SELECT * FROM price_candles
            WHERE {' AND '.join(clauses)}
            ORDER BY open_time_utc ASC
        """
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [BTCKlinesDAO._map_row(dict(r)) for r in rows]

    @staticmethod
    def count(conn: sqlite3.Connection, timeframe: Optional[TimeFrame] = None) -> int:
        if timeframe is None:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM price_candles WHERE symbol = ?",
                (_DEFAULT_SYMBOL,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM price_candles "
                "WHERE symbol = ? AND timeframe = ?",
                (_DEFAULT_SYMBOL, timeframe),
            ).fetchone()
        return int(row["n"])

    @staticmethod
    def get_latest_inserted_at_by_timeframe(
        conn: sqlite3.Connection,
    ) -> dict[str, Optional[str]]:
        """Sprint 2.6-J:每个 timeframe 最新 bar 的 inserted_at_utc。

        Returns {timeframe: inserted_at_utc | None}。
        """
        rows = conn.execute(
            """
            SELECT pc.timeframe, pc.inserted_at_utc
              FROM price_candles pc
             INNER JOIN (
                SELECT timeframe, MAX(open_time_utc) AS max_t
                  FROM price_candles
                 WHERE symbol = ?
                 GROUP BY timeframe
             ) latest
                ON latest.timeframe = pc.timeframe
               AND latest.max_t     = pc.open_time_utc
             WHERE pc.symbol = ?
            """,
            (_DEFAULT_SYMBOL, _DEFAULT_SYMBOL),
        ).fetchall()
        return {r["timeframe"]: r["inserted_at_utc"] for r in rows}

    @staticmethod
    def get_latest_captured_at_by_timeframe(
        conn: sqlite3.Connection,
    ) -> dict[str, Optional[str]]:
        """Sprint 1.5j:每个 timeframe 最新 bar 的 open_time_utc(数据点时间)。

        与 inserted_at(系统抓取时间)区别:open_time_utc 是 K 线 bar 自身
        的开盘时间。1h K 线建模 cadence = 每小时一根新 bar,所以 open_time
        距 now 通常 < 1h,2h 阈值容忍 1 个 cron 抖动。
        pre_flight 用 captured_at 跟 1.5g derivatives 口径对齐(数据点而非
        系统侧),简化心智模型。
        """
        rows = conn.execute(
            """
            SELECT timeframe, MAX(open_time_utc) AS max_t
              FROM price_candles
             WHERE symbol = ?
             GROUP BY timeframe
            """,
            (_DEFAULT_SYMBOL,),
        ).fetchall()
        return {r["timeframe"]: r["max_t"] for r in rows}

    @staticmethod
    def get_recent_as_df(
        conn: sqlite3.Connection,
        timeframe: TimeFrame,
        limit: int = 500,
    ) -> Any:
        """取最近 limit 根,返回 DataFrame(index=DatetimeIndex UTC,
        columns=open/high/low/close/volume_btc)。Pipeline 专用。"""
        import pandas as pd
        rows = conn.execute(
            "SELECT * FROM price_candles "
            "WHERE symbol = ? AND timeframe = ? "
            "ORDER BY open_time_utc DESC LIMIT ?",
            (_DEFAULT_SYMBOL, timeframe, limit),
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        data = [BTCKlinesDAO._map_row(dict(r)) for r in rows][::-1]
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        cols = ["open", "high", "low", "close", "volume_btc"]
        return df[[c for c in cols if c in df.columns]]


# ============================================================
# 链上 / 宏观(§10.4 长表):onchain_metrics / macro_metrics
# ============================================================
# 统一字段:(metric_name, captured_at_utc, value, source)
# 为了保持老代码无感,读取时把这些映射回 (timestamp, metric_value, source)。


class _MetricLongTableDAO:
    """onchain_metrics / macro_metrics 共用逻辑(§10.4 长表)。"""

    _table: str = ""
    _has_source: bool = False
    _default_source: Optional[str] = None

    @classmethod
    def upsert_batch(cls, conn: sqlite3.Connection, rows: list[Any]) -> int:
        # 新 schema:(metric_name, captured_at_utc, value, source, inserted_at_utc)
        # Sprint 2.6-J:写 inserted_at_utc(从 dataclass.fetched_at 取);
        # ON CONFLICT 时 UPDATE 也覆盖,反映最近一次系统侧写入时刻。
        if cls._has_source:
            sql = f"""
                INSERT INTO {cls._table}
                    (metric_name, captured_at_utc, value, source, inserted_at_utc)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(metric_name, captured_at_utc) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    inserted_at_utc = excluded.inserted_at_utc
            """
            values = [
                (r.metric_name, r.timestamp, r.metric_value,
                 getattr(r, "source", cls._default_source),
                 getattr(r, "fetched_at", None))
                for r in rows
            ]
        else:
            sql = f"""
                INSERT INTO {cls._table}
                    (metric_name, captured_at_utc, value, inserted_at_utc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(metric_name, captured_at_utc) DO UPDATE SET
                    value = excluded.value,
                    inserted_at_utc = excluded.inserted_at_utc
            """
            values = [
                (r.metric_name, r.timestamp, r.metric_value,
                 getattr(r, "fetched_at", None))
                for r in rows
            ]
        cur = conn.executemany(sql, values)
        return cur.rowcount

    @classmethod
    def _map_row(cls, r: dict[str, Any]) -> dict[str, Any]:
        """把新字段映射回老代码期待的 timestamp / metric_value。"""
        out = dict(r)
        if "captured_at_utc" in out and "timestamp" not in out:
            out["timestamp"] = out["captured_at_utc"]
        if "value" in out and "metric_value" not in out:
            out["metric_value"] = out["value"]
        return out

    @classmethod
    def get_latest(
        cls, conn: sqlite3.Connection, metric_name: str
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            f"SELECT * FROM {cls._table} WHERE metric_name = ? "
            f"ORDER BY captured_at_utc DESC LIMIT 1",
            (metric_name,),
        ).fetchone()
        return cls._map_row(dict(row)) if row else None

    @classmethod
    def get_series(
        cls,
        conn: sqlite3.Connection,
        metric_name: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        clauses = ["metric_name = ?"]
        params: list[Any] = [metric_name]
        if start is not None:
            clauses.append("captured_at_utc >= ?")
            params.append(start)
        if end is not None:
            clauses.append("captured_at_utc <= ?")
            params.append(end)
        sql = (
            f"SELECT * FROM {cls._table} WHERE {' AND '.join(clauses)} "
            f"ORDER BY captured_at_utc ASC"
        )
        rows = conn.execute(sql, params).fetchall()
        return [cls._map_row(dict(r)) for r in rows]

    @classmethod
    def get_metric_inserted_at_map(
        cls, conn: sqlite3.Connection,
    ) -> dict[str, Optional[str]]:
        """Sprint 2.6-J:每个 metric_name 最近一行的 inserted_at_utc。

        Returns {metric_name: inserted_at_utc | None},legacy NULL 行返回 None。
        """
        rows = conn.execute(
            f"""
            SELECT m.metric_name, m.inserted_at_utc
              FROM {cls._table} m
             INNER JOIN (
                SELECT metric_name, MAX(captured_at_utc) AS max_ts
                  FROM {cls._table}
                 GROUP BY metric_name
             ) latest
                ON latest.metric_name = m.metric_name
               AND latest.max_ts      = m.captured_at_utc
            """
        ).fetchall()
        return {r["metric_name"]: r["inserted_at_utc"] for r in rows}

    @classmethod
    def get_distinct_metric_names(
        cls, conn: sqlite3.Connection,
    ) -> list[str]:
        rows = conn.execute(
            f"SELECT DISTINCT metric_name FROM {cls._table} ORDER BY metric_name"
        ).fetchall()
        return [r["metric_name"] for r in rows]

    @classmethod
    def get_all_metrics(
        cls,
        conn: sqlite3.Connection,
        lookback_days: int = 180,
    ) -> dict[str, Any]:
        import pandas as pd
        from datetime import datetime, timedelta, timezone
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        out: dict[str, Any] = {}
        for name in cls.get_distinct_metric_names(conn):
            rows = cls.get_series(conn, metric_name=name, start=cutoff)
            if not rows:
                continue
            df = pd.DataFrame(rows)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.set_index("timestamp").sort_index()
            out[name] = df["metric_value"].astype(float)
        return out


class OnchainDAO(_MetricLongTableDAO):
    _table = "onchain_metrics"
    _has_source = True
    _default_source = "glassnode"


class MacroDAO(_MetricLongTableDAO):
    _table = "macro_metrics"
    _has_source = True
    _default_source = "fred"  # Sprint 2.6-A.4:Yahoo 弃用,FRED 是默认


# ============================================================
# 衍生品(§10.4 宽表 derivatives_snapshots)
# ============================================================
# §10.4 规定宽表:每个 captured_at_utc 一行,主字段 funding_rate /
# open_interest / long_short_ratio 为独立列,其他 metrics 入 full_data_json。
# 为了保持 Sprint 1 的 DerivativeMetric 长式 API 可继续使用,我们:
#  * upsert_batch:把同 timestamp 的多条 metric 聚合成 1 行宽表
#  * get_series / get_latest / get_at:把宽表反向展开为长式 dict
_DERIVATIVES_WIDE_COLUMNS: tuple[str, ...] = (
    "funding_rate", "open_interest", "long_short_ratio",
    # Sprint 2.6-B:三个 liquidation 列(配 migrations/002_add_liquidation_columns.sql)
    "liquidation_long", "liquidation_short", "liquidation_total",
)

_DERIVATIVES_LSR_ALIASES: tuple[str, ...] = (
    "long_short_ratio", "long_short_ratio_top", "long_short_ratio_global",
)


class DerivativesDAO:
    """derivatives_snapshots 表 DAO(建模 §10.4 宽表)。"""

    @staticmethod
    def upsert_batch(conn: sqlite3.Connection, rows: list[Any]) -> int:
        """把 DerivativeMetric 长式行聚合成宽表 upsert。

        Sprint 2.6-J:wide 表共享 1 个 inserted_at_utc(snapshot 级精度),
        取每个 ts 桶内 max(fetched_at) — 该 ts 最近一次写入时刻。

        Sprint 1.5f-revised §X 防再污染:**只接受 daily timestamp**
        ('YYYY-MM-DDT00:00:00Z')。生产 jobs.py 已用 interval='1d',hourly
        timestamp 一律 logger.warning + 跳过(避免 SSH 调试遗留再次混存到表)。
        """
        # 按 timestamp 分桶
        buckets: dict[str, dict[str, Any]] = {}
        rejected_hourly = 0
        for r in rows:
            ts = r.timestamp
            # Sprint 1.5f-revised:hourly timestamp 拒绝
            if not isinstance(ts, str) or not ts.endswith("T00:00:00Z"):
                logger.warning(
                    "DerivativesDAO.upsert_batch: rejecting non-daily ts=%s "
                    "(metric=%s value=%s) — only daily ts allowed for "
                    "derivatives_snapshots; check caller's interval=",
                    ts, r.metric_name, r.metric_value,
                )
                rejected_hourly += 1
                continue
            name = r.metric_name
            val = r.metric_value
            b = buckets.setdefault(ts, {})
            # 主字段名归一:long_short_ratio_*  →  long_short_ratio
            if name in _DERIVATIVES_LSR_ALIASES:
                b.setdefault("long_short_ratio", val)
                b.setdefault("_extras", {})[name] = val
            elif name in _DERIVATIVES_WIDE_COLUMNS:
                b[name] = val
            else:
                b.setdefault("_extras", {})[name] = val
            # snapshot 级 inserted_at_utc:取桶内最新 fetched_at
            existing_fa = b.get("_inserted_at_utc")
            cand = getattr(r, "fetched_at", None)
            if cand and (existing_fa is None or cand > existing_fa):
                b["_inserted_at_utc"] = cand

        # Sprint 2.6-F.4:full_data_json 必须 MERGE 而非 COALESCE。
        # Sprint 2.6-J:inserted_at_utc 同样 MERGE — ON CONFLICT 时取 max。
        sql = """
            INSERT INTO derivatives_snapshots
                (captured_at_utc, funding_rate, open_interest,
                 long_short_ratio,
                 liquidation_long, liquidation_short, liquidation_total,
                 full_data_json, inserted_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(captured_at_utc) DO UPDATE SET
                funding_rate = COALESCE(excluded.funding_rate, derivatives_snapshots.funding_rate),
                open_interest = COALESCE(excluded.open_interest, derivatives_snapshots.open_interest),
                long_short_ratio = COALESCE(excluded.long_short_ratio, derivatives_snapshots.long_short_ratio),
                liquidation_long = COALESCE(excluded.liquidation_long, derivatives_snapshots.liquidation_long),
                liquidation_short = COALESCE(excluded.liquidation_short, derivatives_snapshots.liquidation_short),
                liquidation_total = COALESCE(excluded.liquidation_total, derivatives_snapshots.liquidation_total),
                full_data_json = json_patch(
                    COALESCE(derivatives_snapshots.full_data_json, '{}'),
                    COALESCE(excluded.full_data_json, '{}')
                ),
                inserted_at_utc = MAX(
                    COALESCE(excluded.inserted_at_utc, ''),
                    COALESCE(derivatives_snapshots.inserted_at_utc, '')
                )
        """
        values = []
        for ts, b in buckets.items():
            extras = b.get("_extras") or {}
            full_data = json.dumps(extras, ensure_ascii=False) if extras else None
            values.append((
                ts,
                b.get("funding_rate"),
                b.get("open_interest"),
                b.get("long_short_ratio"),
                b.get("liquidation_long"),
                b.get("liquidation_short"),
                b.get("liquidation_total"),
                full_data,
                b.get("_inserted_at_utc"),
            ))
        cur = conn.executemany(sql, values)
        # Sprint 1.5h.1:加 summary log 让计数变成可观测信号
        if rejected_hourly > 0:
            logger.warning(
                "DerivativesDAO.upsert_batch: rejected %d hourly rows in batch",
                rejected_hourly,
            )
        return cur.rowcount

    @staticmethod
    def get_latest_snapshot_inserted_at(
        conn: sqlite3.Connection,
    ) -> Optional[str]:
        """Sprint 2.6-J:最近 snapshot 的 inserted_at_utc(wide 表 snapshot 级精度)。

        emitter 渲染 derivatives 卡时统一用这一个时间戳(funding/OI/LSR
        因 wide 表共享 1 行,无法 per-metric 区分,这是 schema 固有限制)。
        """
        row = conn.execute(
            "SELECT inserted_at_utc FROM derivatives_snapshots "
            "ORDER BY captured_at_utc DESC LIMIT 1"
        ).fetchone()
        return row["inserted_at_utc"] if row else None

    @staticmethod
    def get_latest_snapshot_captured_at(
        conn: sqlite3.Connection,
    ) -> Optional[str]:
        """Sprint 1.5g:最近 snapshot 的 captured_at_utc(数据点本身的时间)。

        与 inserted_at(系统抓取 wall clock)不同:captured_at 是数据点
        语义时间,daily bar 的 captured_at 永远是当天 00:00:00Z,即便系统
        每小时重抓也不变。pre_flight 用这个判 daily 数据点新鲜度更直观
        (建模 §3.2.3 "数据点 vs 系统侧"区分)。
        """
        row = conn.execute(
            "SELECT captured_at_utc FROM derivatives_snapshots "
            "ORDER BY captured_at_utc DESC LIMIT 1"
        ).fetchone()
        return row["captured_at_utc"] if row else None

    @staticmethod
    def _explode_row(row: dict[str, Any]) -> list[dict[str, Any]]:
        """把宽表一行反向展开为长式 dict 列表(供 get_* 老调用)。"""
        ts = row.get("captured_at_utc")
        out: list[dict[str, Any]] = []
        for col in _DERIVATIVES_WIDE_COLUMNS:
            v = row.get(col)
            if v is not None:
                out.append({
                    "timestamp": ts,
                    "captured_at_utc": ts,
                    "metric_name": col,
                    "metric_value": v,
                    "value": v,
                })
        extras_json = row.get("full_data_json")
        if extras_json:
            try:
                extras = json.loads(extras_json)
                for k, v in (extras or {}).items():
                    if v is None:
                        continue
                    out.append({
                        "timestamp": ts,
                        "captured_at_utc": ts,
                        "metric_name": k,
                        "metric_value": v,
                        "value": v,
                    })
            except (TypeError, ValueError):
                pass
        return out

    @staticmethod
    def get_latest(
        conn: sqlite3.Connection, metric_name: str,
    ) -> Optional[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM derivatives_snapshots "
            "ORDER BY captured_at_utc DESC LIMIT 200",
        ).fetchall()
        for raw in rows:
            exploded = DerivativesDAO._explode_row(dict(raw))
            for e in exploded:
                if e["metric_name"] == metric_name:
                    return e
        return None

    @staticmethod
    def get_series(
        conn: sqlite3.Connection,
        metric_name: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if start is not None:
            clauses.append("captured_at_utc >= ?")
            params.append(start)
        if end is not None:
            clauses.append("captured_at_utc <= ?")
            params.append(end)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT * FROM derivatives_snapshots {where_clause} "
            "ORDER BY captured_at_utc ASC"
        )
        rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for raw in rows:
            for e in DerivativesDAO._explode_row(dict(raw)):
                if e["metric_name"] == metric_name:
                    out.append(e)
        return out

    @staticmethod
    def get_distinct_metric_names(
        conn: sqlite3.Connection,
    ) -> list[str]:
        names: set[str] = set()
        rows = conn.execute(
            "SELECT funding_rate, open_interest, long_short_ratio, full_data_json "
            "FROM derivatives_snapshots"
        ).fetchall()
        for raw in rows:
            d = dict(raw)
            for col in _DERIVATIVES_WIDE_COLUMNS:
                if d.get(col) is not None:
                    names.add(col)
            if d.get("full_data_json"):
                try:
                    extras = json.loads(d["full_data_json"])
                    for k in (extras or {}).keys():
                        names.add(k)
                except (TypeError, ValueError):
                    pass
        return sorted(names)

    @staticmethod
    def get_all_metrics(
        conn: sqlite3.Connection,
        lookback_days: int = 180,
    ) -> dict[str, Any]:
        import pandas as pd
        from datetime import datetime, timedelta, timezone
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            "SELECT * FROM derivatives_snapshots "
            "WHERE captured_at_utc >= ? ORDER BY captured_at_utc ASC",
            (cutoff,),
        ).fetchall()
        series_map: dict[str, list[tuple[str, float]]] = {}
        for raw in rows:
            for e in DerivativesDAO._explode_row(dict(raw)):
                val = e.get("value")
                if val is None:
                    continue
                series_map.setdefault(e["metric_name"], []).append(
                    (e["timestamp"], float(val)),
                )
        out: dict[str, Any] = {}
        for name, pairs in series_map.items():
            if not pairs:
                continue
            df = pd.DataFrame(pairs, columns=["timestamp", "metric_value"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.set_index("timestamp").sort_index()
            # Sprint 1.5j Bug 1:同一 captured_at 上 alias 双写(主列 + extras
            # 同名)会让 _explode_row emit 两次,导致 _pct_change(series, 1)
            # 取末两行 = 同 daily bar → 0% 假信号(LSR、OI 都受影响)。
            # 通用兜底:取每个 ts 的最后一次值(假设后写更准),避免重复行。
            df = df[~df.index.duplicated(keep="last")]
            out[name] = df["metric_value"].astype(float)
        return out


# ============================================================
# 事件日历
# ============================================================

class EventsCalendarDAO:
    """events_calendar 表 DAO。"""

    @staticmethod
    def upsert_event(conn: sqlite3.Connection, row: EventRow) -> int:
        sql = """
            INSERT INTO events_calendar
                (event_id, date, timezone, local_time, utc_trigger_time,
                 event_type, event_name, impact_level, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                date = excluded.date,
                timezone = excluded.timezone,
                local_time = excluded.local_time,
                utc_trigger_time = excluded.utc_trigger_time,
                event_type = excluded.event_type,
                event_name = excluded.event_name,
                impact_level = excluded.impact_level,
                notes = excluded.notes
        """
        cur = conn.execute(
            sql,
            (row.event_id, row.date, row.timezone, row.local_time,
             row.utc_trigger_time, row.event_type, row.event_name,
             row.impact_level, row.notes),
        )
        return cur.rowcount

    @staticmethod
    def upsert_events(conn: sqlite3.Connection, rows: list[EventRow]) -> int:
        total = 0
        for r in rows:
            total += EventsCalendarDAO.upsert_event(conn, r)
        return total

    @staticmethod
    def get_events_in_window(
        conn: sqlite3.Connection,
        start_utc: str,
        end_utc: str,
    ) -> list[dict[str, Any]]:
        """返回 utc_trigger_time 落在 [start, end] 的事件(升序)。"""
        rows = conn.execute(
            "SELECT * FROM events_calendar "
            "WHERE utc_trigger_time IS NOT NULL "
            "AND utc_trigger_time >= ? AND utc_trigger_time <= ? "
            "ORDER BY utc_trigger_time ASC",
            (start_utc, end_utc),
        ).fetchall()
        return _rows_to_dicts(rows)

    @staticmethod
    def get_next_events_by_type(
        conn: sqlite3.Connection,
        event_types: list[str],
        now_utc: Optional[str] = None,
    ) -> dict[str, Optional[dict[str, Any]]]:
        """Sprint 2.6-M B2:返回每个 event_type 之后最近的 1 个事件,**不限距离**。

        与 get_upcoming_within_hours 区别:那个只取 N 小时内,本方法不做时间窗口
        过滤,用于"下次 X 卡"展示(用户想看下一个 FOMC,即便 30 天后也要显示)。

        每条结果附加 'hours_to' 字段(相对 now 的小时数)。
        Returns {event_type: row_dict | None}。
        """
        from datetime import datetime, timezone
        if now_utc is None:
            now_dt = datetime.now(timezone.utc)
        else:
            s = now_utc.replace("Z", "+00:00")
            now_dt = datetime.fromisoformat(s)
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
        now_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        out: dict[str, Optional[dict[str, Any]]] = {t: None for t in event_types}
        for t in event_types:
            row = conn.execute(
                "SELECT * FROM events_calendar "
                "WHERE event_type = ? "
                "  AND utc_trigger_time IS NOT NULL "
                "  AND utc_trigger_time > ? "
                "ORDER BY utc_trigger_time ASC LIMIT 1",
                (t, now_str),
            ).fetchone()
            if row is None:
                continue
            d = dict(row)
            try:
                trig = d.get("utc_trigger_time")
                if trig:
                    s2 = trig.replace("Z", "+00:00")
                    t_dt = datetime.fromisoformat(s2)
                    if t_dt.tzinfo is None:
                        t_dt = t_dt.replace(tzinfo=timezone.utc)
                    d["hours_to"] = (t_dt - now_dt).total_seconds() / 3600.0
                else:
                    d["hours_to"] = None
            except Exception:
                d["hours_to"] = None
            # event_risk.py 期待 'name' 字段(同 Sprint 2.6-D fix)
            if "name" not in d and "event_name" in d:
                d["name"] = d["event_name"]
            out[t] = d
        return out

    @staticmethod
    def get_upcoming_within_hours(
        conn: sqlite3.Connection,
        hours: float = 48,
        now_utc: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        返回 now → now+hours 窗口内的事件,按时间升序。
        每条附加 'hours_to' 字段(相对 now 的小时数)。
        Pipeline 专用。
        """
        from datetime import datetime, timedelta, timezone
        if now_utc is None:
            now_dt = datetime.now(timezone.utc)
        else:
            s = now_utc.replace("Z", "+00:00")
            now_dt = datetime.fromisoformat(s) if s else datetime.now(timezone.utc)
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=timezone.utc)
        end_dt = now_dt + timedelta(hours=hours)
        start_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = EventsCalendarDAO.get_events_in_window(conn, start_str, end_str)
        for r in rows:
            try:
                trig = r.get("utc_trigger_time")
                if trig:
                    s2 = trig.replace("Z", "+00:00")
                    t_dt = datetime.fromisoformat(s2)
                    if t_dt.tzinfo is None:
                        t_dt = t_dt.replace(tzinfo=timezone.utc)
                    r["hours_to"] = (
                        (t_dt - now_dt).total_seconds() / 3600.0
                    )
                else:
                    r["hours_to"] = None
            except Exception:
                r["hours_to"] = None
            # Sprint 2.6-D fix:event_risk.py 期待 'name' 字段,DAO 列叫 'event_name'
            if "name" not in r and "event_name" in r:
                r["name"] = r["event_name"]
        return rows


# ============================================================
# Sprint 2.6-G:DataFetchLogDAO(group 级抓取时间)→ Sprint 2.6-J 已废弃
#   (替代:per-metric inserted_at_utc 列 + 三个 helper 方法。
#    data_fetch_log 表本身保留在 DB,代码层不再读不再写。)
# ============================================================


# ============================================================
# StrategyState 历史归档
# ============================================================

# ============================================================
# Sprint 2.8-A:latest_factor_cards 单行覆盖表
# ============================================================

class LatestFactorCardsDAO:
    """latest_factor_cards 表 DAO(单行 PK=1,每个 collector 跑完后 upsert 覆盖)。"""

    @staticmethod
    def upsert(
        conn: sqlite3.Connection,
        cards: list[dict[str, Any]],
        refreshed_at_utc: Optional[str] = None,
    ) -> None:
        ts = refreshed_at_utc or _utc_now_iso()
        cards_json = json.dumps(cards, ensure_ascii=False, default=str)
        conn.execute(
            "INSERT INTO latest_factor_cards (id, cards_json, refreshed_at_utc) "
            "VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  cards_json = excluded.cards_json, "
            "  refreshed_at_utc = excluded.refreshed_at_utc",
            (cards_json, ts),
        )

    @staticmethod
    def get_latest(
        conn: sqlite3.Connection,
    ) -> Optional[dict[str, Any]]:
        """返回 {cards: list, refreshed_at_utc: str} 或 None(空表)。"""
        row = conn.execute(
            "SELECT cards_json, refreshed_at_utc FROM latest_factor_cards WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        cards_json = row[0] if not hasattr(row, "keys") else row["cards_json"]
        refreshed = row[1] if not hasattr(row, "keys") else row["refreshed_at_utc"]
        try:
            cards = json.loads(cards_json)
        except (TypeError, ValueError):
            cards = []
        return {"cards": cards, "refreshed_at_utc": refreshed}


def _map_strategy_run_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    """把 strategy_runs 新 schema 映射回 Sprint 1 老 schema 字段,避免调用方大改。

    老字段                       ← 新 schema 字段
    run_timestamp_utc            ← reference_timestamp_utc(失败回退 generated_at_utc)
    state_json(已解析为 state)  ← full_state_json
    created_at                   ← generated_at_utc
    其他 run_id / run_trigger / rules_version / ai_model_actual 直接沿用。
    """
    d = dict(row)
    raw_json = d.pop("full_state_json", None) or d.pop("state_json", None)
    d["state"] = json.loads(raw_json) if raw_json else {}
    if "run_timestamp_utc" not in d:
        d["run_timestamp_utc"] = (
            d.get("reference_timestamp_utc") or d.get("generated_at_utc")
        )
    d.setdefault("created_at", d.get("generated_at_utc"))
    return d


class StrategyStateDAO:
    """strategy_runs 表 DAO(建模 §10.4,替代 Sprint 1 的 strategy_state_history)。

    API: insert_state / get_latest_state / ...,SQL 内部操作 strategy_runs 表;
    v1.2 新字段从 state dict 抽取。
    """

    @staticmethod
    def insert_state(
        conn: sqlite3.Connection,
        run_timestamp_utc: str,
        run_id: str,
        run_trigger: str,
        rules_version: str,
        ai_model_actual: Optional[str],
        state: dict[str, Any],
    ) -> int:
        """插入一条 strategy_run。run_timestamp_utc 保留为参数名
        (对齐老调用);内部写入 reference_timestamp_utc + generated_at_utc。"""
        evidence = state.get("evidence_reports") or {}
        composite = state.get("composite_factors") or {}
        sm = state.get("state_machine") or {}
        observation = state.get("observation") or {}
        cold_start = state.get("cold_start") or {}
        pipeline_meta = state.get("pipeline_meta") or {}
        adjudicator = state.get("adjudicator") or {}

        l2 = evidence.get("layer_2") or {}
        market_snapshot = state.get("market_snapshot") or {}

        action_state = sm.get("current_state") or "FLAT"
        stance = l2.get("stance")
        btc_price_usd = market_snapshot.get("btc_price_usd")
        state_transitioned = 0 if sm.get("stable_in_state") else 1
        fallback_level = pipeline_meta.get("fallback_level")
        strategy_flavor = (state.get("meta") or {}).get("strategy_flavor", "swing")
        observation_category = observation.get("observation_category")
        cold_start_flag = 1 if cold_start.get("warming_up") else 0

        generated_at_utc = state.get("generated_at_utc") or _utc_now_iso()
        generated_at_bjt = state.get("generated_at_bjt") or generated_at_utc

        # Sprint 1.10-E:V24 meta — 从 state 提取 constraint_activations
        # (orchestrator 装入 state["constraint_activations"]),写入新列。
        # 兼容旧 caller(无此 key 时存 NULL)。
        ca = state.get("constraint_activations")
        ca_json = json.dumps(ca, ensure_ascii=False) if ca else None

        sql = """
            INSERT INTO strategy_runs
                (run_id, generated_at_utc, generated_at_bjt,
                 reference_timestamp_utc, previous_run_id,
                 action_state, stance, btc_price_usd,
                 state_transitioned, run_trigger, run_mode,
                 fallback_level, system_version, rules_version,
                 strategy_flavor, observation_category,
                 cold_start, ai_model_actual, full_state_json,
                 constraint_activations_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                generated_at_utc = excluded.generated_at_utc,
                generated_at_bjt = excluded.generated_at_bjt,
                reference_timestamp_utc = excluded.reference_timestamp_utc,
                action_state = excluded.action_state,
                stance = excluded.stance,
                btc_price_usd = excluded.btc_price_usd,
                state_transitioned = excluded.state_transitioned,
                run_trigger = excluded.run_trigger,
                fallback_level = excluded.fallback_level,
                rules_version = excluded.rules_version,
                strategy_flavor = excluded.strategy_flavor,
                observation_category = excluded.observation_category,
                cold_start = excluded.cold_start,
                ai_model_actual = excluded.ai_model_actual,
                full_state_json = excluded.full_state_json,
                constraint_activations_json = excluded.constraint_activations_json
        """
        cur = conn.execute(
            sql,
            (
                run_id, generated_at_utc, generated_at_bjt,
                run_timestamp_utc, None,
                action_state, stance, btc_price_usd,
                state_transitioned, run_trigger, None,
                fallback_level, None, rules_version,
                strategy_flavor, observation_category,
                cold_start_flag, ai_model_actual,
                json.dumps(state, ensure_ascii=False),
                ca_json,
            ),
        )
        return cur.rowcount

    @staticmethod
    def get_latest_state(
        conn: sqlite3.Connection,
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM strategy_runs "
            "ORDER BY reference_timestamp_utc DESC, generated_at_utc DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return _map_strategy_run_to_legacy(dict(row))

    @staticmethod
    def get_recent_states(
        conn: sqlite3.Connection, limit: int = 5
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM strategy_runs "
            "ORDER BY reference_timestamp_utc DESC, generated_at_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_map_strategy_run_to_legacy(dict(r)) for r in rows]

    @staticmethod
    def get_count(conn: sqlite3.Connection) -> int:
        """历史 run 条数,用于 cold_start 判定。"""
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_runs"
        ).fetchone()
        return int(row["n"])

    @staticmethod
    def get_latest_non_unclear_cycle(
        conn: sqlite3.Connection,
    ) -> Optional[str]:
        """倒序扫 strategy_runs,从 full_state_json 提取 cycle_position。"""
        sql = """
            SELECT COALESCE(
                json_extract(full_state_json, '$.composite_factors.cycle_position.cycle_position'),
                json_extract(full_state_json, '$.composite_factors.cycle_position.band')
            ) AS cp
            FROM strategy_runs
            WHERE COALESCE(
                json_extract(full_state_json, '$.composite_factors.cycle_position.cycle_position'),
                json_extract(full_state_json, '$.composite_factors.cycle_position.band')
            ) IS NOT NULL
              AND COALESCE(
                json_extract(full_state_json, '$.composite_factors.cycle_position.cycle_position'),
                json_extract(full_state_json, '$.composite_factors.cycle_position.band')
            ) != 'unclear'
            ORDER BY reference_timestamp_utc DESC
            LIMIT 1
        """
        try:
            row = conn.execute(sql).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        return row["cp"]


# ============================================================
# ReviewReport
# ============================================================

class LifecyclesDAO:
    """Sprint 1.5b-C:lifecycles 表 DAO(§10.4 / §8.2)。

    每次 LifecycleManager.compute_post_sm 产出非 None lifecycle 时 upsert,
    active 中的 lifecycle 也会实时反映;归档(status=closed)时 exit_time_utc
    自动写入。
    """

    @staticmethod
    def upsert_lifecycle(
        conn: sqlite3.Connection, lifecycle_dict: dict[str, Any],
    ) -> int:
        """从 lifecycle_manager 输出的 dict 写入 lifecycles 表。

        字段映射:
          lifecycle_id        → PRIMARY KEY
          direction           → direction
          origin_time_utc     → entry_time_utc(active 之前为 None)
          exit_time_utc       → exit_time_utc(active 时为 None)
          status              → status
          origin_thesis(<=500)→ origin_thesis
          ai_models_used_in_lifecycle → ai_models_used(逗号分隔)
          rules_versions_used → rules_versions_used(逗号分隔)
          整个 dict          → full_data_json
        """
        if not isinstance(lifecycle_dict, dict):
            return 0
        lid = lifecycle_dict.get("lifecycle_id")
        if not lid:
            return 0
        thesis = (lifecycle_dict.get("origin_thesis") or "")[:500]
        ai_models = lifecycle_dict.get("ai_models_used_in_lifecycle") or []
        rules_used = lifecycle_dict.get("rules_versions_used") or []
        sql = """
            INSERT INTO lifecycles
                (lifecycle_id, direction, entry_time_utc, exit_time_utc,
                 status, origin_thesis, ai_models_used, rules_versions_used,
                 full_data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lifecycle_id) DO UPDATE SET
                direction = excluded.direction,
                entry_time_utc = excluded.entry_time_utc,
                exit_time_utc = excluded.exit_time_utc,
                status = excluded.status,
                origin_thesis = excluded.origin_thesis,
                ai_models_used = excluded.ai_models_used,
                rules_versions_used = excluded.rules_versions_used,
                full_data_json = excluded.full_data_json
        """
        cur = conn.execute(
            sql,
            (
                lid,
                lifecycle_dict.get("direction"),
                lifecycle_dict.get("origin_time_utc"),
                lifecycle_dict.get("exit_time_utc"),
                lifecycle_dict.get("status"),
                thesis,
                ",".join(str(m) for m in ai_models if m),
                ",".join(str(r) for r in rules_used if r),
                json.dumps(lifecycle_dict, ensure_ascii=False, default=str),
            ),
        )
        return cur.rowcount

    @staticmethod
    def get_lifecycle(
        conn: sqlite3.Connection, lifecycle_id: str,
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM lifecycles WHERE lifecycle_id = ?",
            (lifecycle_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        raw = d.pop("full_data_json", None)
        d["full_data"] = json.loads(raw) if raw else {}
        return d

    @staticmethod
    def list_lifecycles(
        conn: sqlite3.Connection,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if status:
            rows = conn.execute(
                "SELECT * FROM lifecycles WHERE status = ? "
                "ORDER BY entry_time_utc DESC NULLS LAST LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM lifecycles "
                "ORDER BY entry_time_utc DESC NULLS LAST LIMIT ?",
                (limit,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            raw = d.pop("full_data_json", None)
            d["full_data"] = json.loads(raw) if raw else {}
            items.append(d)
        return items


class ReviewReportsDAO:
    """review_reports 表 DAO(§10.4:PK=review_id,v1.2 新增 rules_version_at_review)。"""

    @staticmethod
    def insert_report(
        conn: sqlite3.Connection,
        run_timestamp_utc: str,
        lifecycle_id: str,
        outcome_type: Optional[str],
        report: dict[str, Any],
        *,
        review_id: Optional[str] = None,
        rules_version_at_review: Optional[str] = None,
    ) -> int:
        """插入一条复盘。review_id 可选(缺省用 lifecycle_id + reference 时间戳拼)。
        run_timestamp_utc 保留为参数名,写入 generated_at_utc。
        """
        if review_id is None:
            review_id = f"{lifecycle_id}_{run_timestamp_utc}"
        sql = """
            INSERT INTO review_reports
                (review_id, lifecycle_id, generated_at_utc, outcome_type,
                 rules_version_at_review, full_report_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id) DO UPDATE SET
                lifecycle_id = excluded.lifecycle_id,
                generated_at_utc = excluded.generated_at_utc,
                outcome_type = excluded.outcome_type,
                rules_version_at_review = excluded.rules_version_at_review,
                full_report_json = excluded.full_report_json
        """
        cur = conn.execute(
            sql,
            (review_id, lifecycle_id, run_timestamp_utc, outcome_type,
             rules_version_at_review,
             json.dumps(report, ensure_ascii=False)),
        )
        return cur.rowcount

    @staticmethod
    def get_reports_for_lifecycle(
        conn: sqlite3.Connection, lifecycle_id: str
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM review_reports WHERE lifecycle_id = ? "
            "ORDER BY generated_at_utc ASC",
            (lifecycle_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            raw = d.pop("full_report_json", None)
            d["report"] = json.loads(raw) if raw else {}
            # 向后兼容:老代码读 run_timestamp_utc
            d["run_timestamp_utc"] = d.get("generated_at_utc")
            result.append(d)
        return result


# ============================================================
# Fallback 日志
# ============================================================

class FallbackLogDAO:
    """fallback_events 表 DAO(§10.4,替代 fallback_log)。

    字段映射(对老调用保持 API 兼容):
      run_timestamp_utc  →  triggered_at_utc
      triggered_by       →  reason(字符串,形如 'pipeline.<stage>')
      details(JSON)     →  resolution_note(JSON 字符串)
    """

    @staticmethod
    def insert_event(
        conn: sqlite3.Connection,
        run_timestamp_utc: str,
        fallback_level: FallbackLevel,
        triggered_by: str,
        details: Optional[dict[str, Any]] = None,
    ) -> int:
        details_json = json.dumps(details, ensure_ascii=False) if details else None
        cur = conn.execute(
            "INSERT INTO fallback_events "
            "(triggered_at_utc, fallback_level, reason, resolution_note) "
            "VALUES (?, ?, ?, ?)",
            (run_timestamp_utc, fallback_level, triggered_by, details_json),
        )
        return cur.rowcount

    @staticmethod
    def log_stage_error(
        conn: sqlite3.Connection,
        run_timestamp_utc: str,
        stage: str,
        error: BaseException | str,
        fallback_applied: str,
        fallback_level: FallbackLevel = "level_1",
    ) -> int:
        """
        Pipeline 阶段出错时的便捷封装:把 stage / error / fallback_applied 写入
        details。默认 fallback_level='level_1'(单阶段降级),调用方可覆盖。
        """
        if isinstance(error, BaseException):
            error_type = type(error).__name__
            error_msg = str(error)[:500]
        else:
            error_type = "str"
            error_msg = str(error)[:500]
        details = {
            "stage": stage,
            "error_type": error_type,
            "error_message": error_msg,
            "fallback_applied": fallback_applied,
        }
        return FallbackLogDAO.insert_event(
            conn,
            run_timestamp_utc=run_timestamp_utc,
            fallback_level=fallback_level,
            triggered_by=f"pipeline.{stage}",
            details=details,
        )

    # ------------------------------------------------------------------
    # Auto-escalation (Sprint 1.16c)
    # ------------------------------------------------------------------

    @staticmethod
    def count_for_triggered_by_since(
        conn: sqlite3.Connection,
        triggered_by: str,
        since_utc: str,
        fallback_level: Optional[FallbackLevel] = None,
    ) -> int:
        if fallback_level is None:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM fallback_events "
                "WHERE reason = ? AND triggered_at_utc >= ?",
                (triggered_by, since_utc),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM fallback_events "
                "WHERE reason = ? AND fallback_level = ? "
                "AND triggered_at_utc >= ?",
                (triggered_by, fallback_level, since_utc),
            ).fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def log_with_escalation(
        conn: sqlite3.Connection,
        run_timestamp_utc: str,
        stage: str,
        error: BaseException | str,
        fallback_applied: str,
        *,
        base_level: FallbackLevel = "level_1",
        escalate_to_l2_after: int = 3,
        escalate_to_l3_after: int = 3,
        l1_window_minutes: int = 60,
        l2_window_minutes: int = 240,
    ) -> tuple[int, FallbackLevel]:
        """
        在 log_stage_error 基础上加自动升级:
          * 同一 stage 在 l1_window_minutes 内已有 ≥ escalate_to_l2_after
            条 level_1 → 本条升级为 level_2
          * 同一 stage 在 l2_window_minutes 内已有 ≥ escalate_to_l3_after
            条 level_2 → 本条升级为 level_3

        返回 (rowcount, actual_level)。
        """
        triggered_by = f"pipeline.{stage}"
        # 时间窗口起点
        try:
            ref_dt = datetime.fromisoformat(
                run_timestamp_utc.replace("Z", "+00:00")
            )
        except ValueError:
            ref_dt = datetime.now(timezone.utc)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)

        def _since(delta_min: int) -> str:
            return (
                ref_dt - timedelta(minutes=delta_min)
            ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        actual_level: FallbackLevel = base_level

        # 先看 l2 升级
        if base_level == "level_1":
            l1_count = FallbackLogDAO.count_for_triggered_by_since(
                conn, triggered_by=triggered_by,
                since_utc=_since(l1_window_minutes),
                fallback_level="level_1",
            )
            if l1_count >= escalate_to_l2_after:
                actual_level = "level_2"

        # 再看 l3 升级(可能从 l1 直接跳到 l3 经过 l2;也可能 base_level 本身是 level_2)
        if actual_level == "level_2":
            l2_count = FallbackLogDAO.count_for_triggered_by_since(
                conn, triggered_by=triggered_by,
                since_utc=_since(l2_window_minutes),
                fallback_level="level_2",
            )
            if l2_count >= escalate_to_l3_after:
                actual_level = "level_3"

        # 写入(带 escalation 标记)
        if isinstance(error, BaseException):
            error_type = type(error).__name__
            error_msg = str(error)[:500]
        else:
            error_type = "str"
            error_msg = str(error)[:500]
        details = {
            "stage": stage,
            "error_type": error_type,
            "error_message": error_msg,
            "fallback_applied": fallback_applied,
            "escalated_from": base_level if actual_level != base_level else None,
        }
        rowcount = FallbackLogDAO.insert_event(
            conn,
            run_timestamp_utc=run_timestamp_utc,
            fallback_level=actual_level,
            triggered_by=triggered_by,
            details=details,
        )
        return rowcount, actual_level


# ============================================================
# 运行元数据(Sprint 1.5c:run_metadata 表已删除,信息折入 strategy_runs)
# ============================================================
# RunMetadataDAO 保留为空壳(兼容老调用),start_run / finish_run 变成 no-op。
# 真正的运行元数据通过 strategy_runs 的 run_trigger / fallback_level / stance
# 等字段表达。pipeline 失败还会写一条 fallback_events。


class RunMetadataDAO:
    """已废弃(Sprint 1.5c 对齐建模 §10.4)。保留 no-op 方法以兼容老调用。"""

    @staticmethod
    def start_run(
        conn: sqlite3.Connection,
        run_id: str,
        run_timestamp_utc: str,
        run_trigger: str,
    ) -> int:
        return 0

    @staticmethod
    def finish_run(
        conn: sqlite3.Connection,
        run_id: str,
        status: RunStatus,
        notes: Optional[str] = None,
    ) -> int:
        return 0


# ============================================================
# Sprint 1.10-A:v1.4 三表 DAO(virtual_account / virtual_orders / theses)
# ============================================================
# 对齐 docs/modeling.md b25cfe6(v1.4 修订版)§5.1-§5.3
# 纪律:DAO 不做业务逻辑,只 CRUD;业务逻辑留 1.10-B/C/D 的 manager 模块。


class VirtualAccountDAO:
    """virtual_account 表 DAO(v1.4 §5.1.2)。

    每次 strategy_run 完成后写一行 1:1 快照(§5.1.4)。
    收益指标计算(日/周/月)留给 1.10-B 的 virtual_account_manager。
    """

    @staticmethod
    def insert_snapshot(
        conn: sqlite3.Connection,
        snapshot_id: str,
        run_id: str,
        snapshot_at_utc: str,
        btc_price_at_snapshot: float,
        initial_capital: float,
        available_cash: float,
        total_equity: float,
        long_position_usdt: float = 0.0,
        long_avg_price: Optional[float] = None,
        long_btc_amount: float = 0.0,
        short_position_usdt: float = 0.0,
        short_avg_price: Optional[float] = None,
        short_btc_amount: float = 0.0,
        realized_pnl_total: float = 0.0,
        unrealized_pnl: float = 0.0,
        total_return_pct: float = 0.0,
    ) -> None:
        """写入一条 virtual_account 快照(v1.4 §5.1.4)。

        run_id 是 UNIQUE,重复 run_id 会触发 IntegrityError(由调用方处理)。
        不隐式 commit,调用方决定 commit 时机。
        """
        sql = """
            INSERT INTO virtual_account (
                snapshot_id, run_id, snapshot_at_utc, btc_price_at_snapshot,
                initial_capital, available_cash,
                long_position_usdt, long_avg_price, long_btc_amount,
                short_position_usdt, short_avg_price, short_btc_amount,
                total_equity, realized_pnl_total, unrealized_pnl, total_return_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        conn.execute(sql, (
            snapshot_id, run_id, snapshot_at_utc, btc_price_at_snapshot,
            initial_capital, available_cash,
            long_position_usdt, long_avg_price, long_btc_amount,
            short_position_usdt, short_avg_price, short_btc_amount,
            total_equity, realized_pnl_total, unrealized_pnl, total_return_pct,
        ))

    @staticmethod
    def get_latest(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
        """取最新一条快照(按 snapshot_at_utc DESC)。无记录返 None(v1.4 §5.1.4)。"""
        row = conn.execute(
            "SELECT * FROM virtual_account "
            "ORDER BY snapshot_at_utc DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def get_history(
        conn: sqlite3.Connection,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """按时间降序返回历史快照,默认 100 条(v1.4 §5.1.5 收益率计算用)。"""
        rows = conn.execute(
            "SELECT * FROM virtual_account "
            "ORDER BY snapshot_at_utc DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


class VirtualOrdersDAO:
    """virtual_orders 表 DAO(v1.4 §5.2)。

    精确管理"挂单 → 触发 → 持仓"全流程(§5.2.1)。
    所有挂单都是精确价格(不是区间,§5.2.4)。
    DAO 不做触发判定 / 价格穿越逻辑(留 1.10-B 的 orders_engine)。

    设计要点(用户 v2 补充 C):
      expires_at_utc 由调用方传入(读 base.yaml::virtual_orders.default_expiry_days
      算 created_at + N * 86400)。SQL 不写 DEFAULT,因为 N 是配置项可调。
    """

    @staticmethod
    def create_order(
        conn: sqlite3.Connection,
        order_id: str,
        thesis_id: str,
        direction: str,            # long / short
        order_type: str,           # entry / stop_loss / take_profit
        price: float,              # 精确挂单价
        size_pct: float,
        size_usdt: float,          # = initial_capital × size_pct
        created_at_utc: str,
        expires_at_utc: str,       # 调用方算(§5.2.6 默认 7 天,见 base.yaml)
        status: str = "pending",
    ) -> None:
        """创建一条挂单(v1.4 §5.2.2)。

        order_id 是 PK,重复抛 IntegrityError。
        不隐式 commit。
        """
        sql = """
            INSERT INTO virtual_orders (
                order_id, thesis_id, direction, order_type,
                price, size_pct, size_usdt,
                status, created_at_utc, expires_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        conn.execute(sql, (
            order_id, thesis_id, direction, order_type,
            price, size_pct, size_usdt,
            status, created_at_utc, expires_at_utc,
        ))

    @staticmethod
    def fill_order(
        conn: sqlite3.Connection,
        order_id: str,
        filled_at_utc: str,
        filled_price: float,        # = price(等于挂单价,§5.2.4)
        filled_btc_amount: float,   # = size_usdt / filled_price
    ) -> int:
        """挂单触发:status=pending → filled,写入成交字段(v1.4 §5.2.3)。

        返回受影响行数(0 = order_id 不存在或非 pending)。
        """
        sql = """
            UPDATE virtual_orders
            SET status='filled', filled_at_utc=?, filled_price=?, filled_btc_amount=?
            WHERE order_id=? AND status='pending'
        """
        cur = conn.execute(sql, (
            filled_at_utc, filled_price, filled_btc_amount, order_id,
        ))
        return cur.rowcount

    @staticmethod
    def cancel_order(
        conn: sqlite3.Connection,
        order_id: str,
        cancelled_reason: str,      # thesis_invalidated / superseded / expired / manual
    ) -> int:
        """取消挂单:status=pending → cancelled(v1.4 §5.2.6)。

        返回受影响行数(0 = order_id 不存在或非 pending)。
        """
        sql = """
            UPDATE virtual_orders
            SET status='cancelled', cancelled_reason=?
            WHERE order_id=? AND status='pending'
        """
        cur = conn.execute(sql, (cancelled_reason, order_id))
        return cur.rowcount

    @staticmethod
    def mark_expired(
        conn: sqlite3.Connection,
        now_utc: str,
    ) -> int:
        """批量把过期挂单标记 expired(v1.4 §5.2.6)。

        条件:status=pending 且 expires_at_utc < now_utc。
        返回受影响行数。
        """
        sql = """
            UPDATE virtual_orders
            SET status='expired', cancelled_reason='expired'
            WHERE status='pending' AND expires_at_utc < ?
        """
        cur = conn.execute(sql, (now_utc,))
        return cur.rowcount

    @staticmethod
    def get_pending(
        conn: sqlite3.Connection,
        thesis_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """取所有 pending 挂单(可选按 thesis_id 过滤)。

        触发判定调用此方法拿候选(v1.4 §5.2.3)。
        """
        if thesis_id is None:
            rows = conn.execute(
                "SELECT * FROM virtual_orders WHERE status='pending' "
                "ORDER BY created_at_utc ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM virtual_orders "
                "WHERE status='pending' AND thesis_id=? "
                "ORDER BY created_at_utc ASC",
                (thesis_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_filled(
        conn: sqlite3.Connection,
        thesis_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """取所有 filled 挂单(可选按 thesis_id 过滤)。

        持仓金额 / 均价计算调用此方法(§5.2.5 同 1H 多挂单全触发)。
        """
        if thesis_id is None:
            rows = conn.execute(
                "SELECT * FROM virtual_orders WHERE status='filled' "
                "ORDER BY filled_at_utc ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM virtual_orders "
                "WHERE status='filled' AND thesis_id=? "
                "ORDER BY filled_at_utc ASC",
                (thesis_id,),
            ).fetchall()
        return [dict(r) for r in rows]


class ThesesDAO:
    """theses 表 DAO(v1.4 §5.3)。

    把所有挂单/持仓/止盈止损绑到同一个 thesis(§5.3.1)。
    DAO 不做创建条件判定 / 失效判定 / 反手通道选择(留 1.10-C 的 thesis_manager)。

    设计要点(用户 v2 补充 B):
      break_conditions 是 list[str],DAO 内 json.dumps 写 TEXT,
      读时 json.loads 还原。JSON 反序列化合法性校验留 1.10-D。
    """

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        thesis_id: str,
        created_at_run_id: str,
        created_at_utc: str,
        direction: str,                  # long / short
        core_logic: str,
        confidence_score: int,           # 0-100
        break_conditions: list[str],     # ≥ 3 条客观条件(Validator 8/9 强制)
        lifecycle_stage: str = "planned",
        status: str = "active",
    ) -> None:
        """创建一条 thesis(v1.4 §5.3.2 + §5.3.3 创建条件由调用方把守)。

        break_conditions 序列化为 JSON 字符串存入 TEXT 列。
        thesis_id 是 PK,重复抛 IntegrityError。
        不隐式 commit。
        """
        sql = """
            INSERT INTO theses (
                thesis_id, created_at_run_id, created_at_utc, direction,
                core_logic, confidence_score, break_conditions,
                lifecycle_stage, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        conn.execute(sql, (
            thesis_id, created_at_run_id, created_at_utc, direction,
            core_logic, int(confidence_score), json.dumps(break_conditions, ensure_ascii=False),
            lifecycle_stage, status,
        ))

    @staticmethod
    def update_assessment(
        conn: sqlite3.Connection,
        thesis_id: str,
        last_assessment: str,            # fully / mostly / partially / weakened / invalidated
        last_assessment_note: str,
        last_assessment_at_run: str,
    ) -> int:
        """更新评估快照(v1.4 §5.3.4 — 每天 16:00 master AI mode=evaluate_existing 写)。

        返回受影响行数。
        """
        sql = """
            UPDATE theses
            SET last_assessment=?, last_assessment_note=?, last_assessment_at_run=?
            WHERE thesis_id=?
        """
        cur = conn.execute(sql, (
            last_assessment, last_assessment_note, last_assessment_at_run, thesis_id,
        ))
        return cur.rowcount

    @staticmethod
    def close(
        conn: sqlite3.Connection,
        thesis_id: str,
        status: str,                     # closed_profit / closed_loss / closed_60d_cap / closed_protection / invalidated
        closed_at_utc: str,
        invalidated_reason: Optional[str] = None,
        close_channel: Optional[str] = None,   # A / B / C(§5.4 反手 3 档)
        final_realized_pnl: Optional[float] = None,
        final_realized_pnl_pct: Optional[float] = None,
        final_outcome: Optional[str] = None,   # profit / loss / breakeven / 60d_cap / protection
        lifecycle_stage: str = "closed",
    ) -> int:
        """关闭 thesis,写入终态字段(v1.4 §5.3.5 / §5.3.7 / §5.4)。

        返回受影响行数。
        """
        sql = """
            UPDATE theses SET
                status=?,
                closed_at_utc=?,
                invalidated_reason=?,
                close_channel=?,
                final_realized_pnl=?,
                final_realized_pnl_pct=?,
                final_outcome=?,
                lifecycle_stage=?
            WHERE thesis_id=?
        """
        cur = conn.execute(sql, (
            status, closed_at_utc, invalidated_reason, close_channel,
            final_realized_pnl, final_realized_pnl_pct, final_outcome,
            lifecycle_stage, thesis_id,
        ))
        return cur.rowcount

    @staticmethod
    def get_active(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
        """取当前唯一 active thesis(v1.4 §5.3.1 主线锁;Validator 6 强制单 active)。

        返回 dict(break_conditions 已 json.loads 还原 list)或 None。
        """
        row = conn.execute(
            "SELECT * FROM theses WHERE status='active' "
            "ORDER BY created_at_utc DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["break_conditions"] = _safe_json_loads(d.get("break_conditions"))
        return d

    @staticmethod
    def get_history(
        conn: sqlite3.Connection,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """按 created_at_utc DESC 返历史 thesis,默认 100 条(v1.4 §9.2.4 时间线用)。

        每条 dict 的 break_conditions 已 json.loads 还原 list。
        """
        rows = conn.execute(
            "SELECT * FROM theses ORDER BY created_at_utc DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["break_conditions"] = _safe_json_loads(d.get("break_conditions"))
            out.append(d)
        return out


def _safe_json_loads(raw: Any) -> Any:
    """容错 JSON loads:None / 空 / 非法 → 返 [](避免 1.10-D 之前老数据 crash)。

    1.10-D 的 validator 会校验 break_conditions ≥ 3 条客观条件;
    本 DAO 层只做容错反序列化,不验内容。
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

