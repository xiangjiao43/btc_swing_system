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
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Optional


# ============================================================
# Helpers
# ============================================================

def _utc_now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 字符串(Z 后缀)。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


TimeFrame = Literal["1h", "4h", "1d", "1w"]
OnchainSource = Literal["glassnode_primary", "glassnode_display", "glassnode_delayed"]
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
    fetched_at: str = field(default_factory=_utc_now_iso)


@dataclass(slots=True)
class DerivativeMetric:
    timestamp: str
    metric_name: str
    metric_value: Optional[float]
    fetched_at: str = field(default_factory=_utc_now_iso)


@dataclass(slots=True)
class OnchainMetric:
    timestamp: str
    metric_name: str
    metric_value: Optional[float]
    source: OnchainSource
    fetched_at: str = field(default_factory=_utc_now_iso)


@dataclass(slots=True)
class MacroMetric:
    timestamp: str
    metric_name: str
    metric_value: Optional[float]
    source: MacroSource
    fetched_at: str = field(default_factory=_utc_now_iso)


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
        sql = """
            INSERT INTO price_candles
                (symbol, timeframe, open_time_utc, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timeframe, open_time_utc) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume
        """
        rows = [
            (_DEFAULT_SYMBOL, k.timeframe, k.timestamp,
             k.open, k.high, k.low, k.close, k.volume_btc)
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
    def get_latest_kline(
        conn: sqlite3.Connection, timeframe: TimeFrame
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM price_candles "
            "WHERE symbol = ? AND timeframe = ? "
            "ORDER BY open_time_utc DESC LIMIT 1",
            (_DEFAULT_SYMBOL, timeframe),
        ).fetchone()
        if row is None:
            return None
        return BTCKlinesDAO._map_row(dict(row))

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
        # 新 schema:(metric_name, captured_at_utc, value, source)
        if cls._has_source:
            sql = f"""
                INSERT INTO {cls._table}
                    (metric_name, captured_at_utc, value, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(metric_name, captured_at_utc) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source
            """
            values = [
                (r.metric_name, r.timestamp, r.metric_value,
                 getattr(r, "source", cls._default_source))
                for r in rows
            ]
        else:
            sql = f"""
                INSERT INTO {cls._table}
                    (metric_name, captured_at_utc, value)
                VALUES (?, ?, ?)
                ON CONFLICT(metric_name, captured_at_utc) DO UPDATE SET
                    value = excluded.value
            """
            values = [
                (r.metric_name, r.timestamp, r.metric_value)
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
    def get_at(
        cls, conn: sqlite3.Connection, timestamp: str
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            f"SELECT * FROM {cls._table} WHERE captured_at_utc = ? ORDER BY metric_name",
            (timestamp,),
        ).fetchall()
        return [cls._map_row(dict(r)) for r in rows]

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
)

_DERIVATIVES_LSR_ALIASES: tuple[str, ...] = (
    "long_short_ratio", "long_short_ratio_top", "long_short_ratio_global",
)


class DerivativesDAO:
    """derivatives_snapshots 表 DAO(建模 §10.4 宽表)。"""

    @staticmethod
    def upsert_batch(conn: sqlite3.Connection, rows: list[Any]) -> int:
        """把 DerivativeMetric 长式行聚合成宽表 upsert。"""
        # 按 timestamp 分桶
        buckets: dict[str, dict[str, Any]] = {}
        for r in rows:
            ts = r.timestamp
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

        sql = """
            INSERT INTO derivatives_snapshots
                (captured_at_utc, funding_rate, open_interest,
                 long_short_ratio, full_data_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(captured_at_utc) DO UPDATE SET
                funding_rate = COALESCE(excluded.funding_rate, derivatives_snapshots.funding_rate),
                open_interest = COALESCE(excluded.open_interest, derivatives_snapshots.open_interest),
                long_short_ratio = COALESCE(excluded.long_short_ratio, derivatives_snapshots.long_short_ratio),
                full_data_json = COALESCE(excluded.full_data_json, derivatives_snapshots.full_data_json)
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
                full_data,
            ))
        cur = conn.executemany(sql, values)
        return cur.rowcount

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
    def get_at(
        conn: sqlite3.Connection, timestamp: str,
    ) -> list[dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM derivatives_snapshots WHERE captured_at_utc = ?",
            (timestamp,),
        ).fetchone()
        if row is None:
            return []
        return DerivativesDAO._explode_row(dict(row))

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
    def get_next_event(
        conn: sqlite3.Connection, reference_utc: str
    ) -> Optional[dict[str, Any]]:
        """返回距 reference_utc 之后最近一个事件;无则 None。"""
        row = conn.execute(
            "SELECT * FROM events_calendar "
            "WHERE utc_trigger_time IS NOT NULL "
            "AND utc_trigger_time > ? "
            "ORDER BY utc_trigger_time ASC LIMIT 1",
            (reference_utc,),
        ).fetchone()
        return _row_to_dict(row)

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
        return rows


# ============================================================
# StrategyState 历史归档
# ============================================================

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

    API 保持不变(insert_state / get_state / get_latest_state / ...),
    但 SQL 内部操作的是 strategy_runs 表;v1.2 新字段从 state dict 抽取。
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

        sql = """
            INSERT INTO strategy_runs
                (run_id, generated_at_utc, generated_at_bjt,
                 reference_timestamp_utc, previous_run_id,
                 action_state, stance, btc_price_usd,
                 state_transitioned, run_trigger, run_mode,
                 fallback_level, system_version, rules_version,
                 strategy_flavor, observation_category,
                 cold_start, ai_model_actual, full_state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                full_state_json = excluded.full_state_json
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
            ),
        )
        return cur.rowcount

    @staticmethod
    def get_state(
        conn: sqlite3.Connection, run_timestamp_utc: str
    ) -> Optional[dict[str, Any]]:
        """根据 reference_timestamp_utc(或 run_id)获取一条 strategy_run。"""
        row = conn.execute(
            "SELECT * FROM strategy_runs WHERE reference_timestamp_utc = ? "
            "ORDER BY generated_at_utc DESC LIMIT 1",
            (run_timestamp_utc,),
        ).fetchone()
        if row is None:
            return None
        return _map_strategy_run_to_legacy(dict(row))

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
    def get_latest_with_state_in(
        conn: sqlite3.Connection,
        state_names: list[str],
    ) -> Optional[dict[str, Any]]:
        """返回最近一条 action_state ∈ state_names 的 run。"""
        if not state_names:
            return None
        placeholders = ",".join(["?"] * len(state_names))
        sql = (
            f"SELECT * FROM strategy_runs WHERE action_state IN ({placeholders}) "
            f"ORDER BY reference_timestamp_utc DESC LIMIT 1"
        )
        row = conn.execute(sql, tuple(state_names)).fetchone()
        if row is None:
            return None
        return _map_strategy_run_to_legacy(dict(row))

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
    def count_recent_at_level(
        conn: sqlite3.Connection,
        fallback_level: FallbackLevel,
        since_utc: str,
    ) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM fallback_events "
            "WHERE fallback_level = ? AND triggered_at_utc >= ?",
            (fallback_level, since_utc),
        ).fetchone()
        return int(row["n"])

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

    @staticmethod
    def count_consecutive_level_1_ending_at(
        conn: sqlite3.Connection,
        run_timestamp_utc: str,
    ) -> int:
        count = 0
        rows = conn.execute(
            "SELECT fallback_level FROM fallback_events "
            "WHERE triggered_at_utc <= ? "
            "ORDER BY triggered_at_utc DESC",
            (run_timestamp_utc,),
        ).fetchall()
        for r in rows:
            if r["fallback_level"] == "level_1":
                count += 1
            else:
                break
        return count

    # ------------------------------------------------------------------
    # Auto-escalation (Sprint 1.16c)
    # ------------------------------------------------------------------

    @staticmethod
    def get_by_stage_frequency(
        conn: sqlite3.Connection,
        since_utc: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT reason AS triggered_by,
                   COUNT(*) AS cnt,
                   SUM(CASE WHEN fallback_level='level_1' THEN 1 ELSE 0 END) AS c1,
                   SUM(CASE WHEN fallback_level='level_2' THEN 1 ELSE 0 END) AS c2,
                   SUM(CASE WHEN fallback_level='level_3' THEN 1 ELSE 0 END) AS c3,
                   MIN(triggered_at_utc) AS first_seen,
                   MAX(triggered_at_utc) AS last_seen
              FROM fallback_events
             WHERE triggered_at_utc >= ?
          GROUP BY reason
          ORDER BY cnt DESC
             LIMIT ?
            """,
            (since_utc, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            trig = r["triggered_by"] or ""
            stage = trig.split(".", 1)[1] if "." in trig else trig
            out.append({
                "stage": stage,
                "triggered_by": trig,
                "count": int(r["cnt"]),
                "level_1": int(r["c1"] or 0),
                "level_2": int(r["c2"] or 0),
                "level_3": int(r["c3"] or 0),
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
            })
        return out

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

    @staticmethod
    def get_run(
        conn: sqlite3.Connection, run_id: str
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM strategy_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return _row_to_dict(row)

    @staticmethod
    def get_recent_runs(
        conn: sqlite3.Connection, limit: int = 10
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM strategy_runs "
            "ORDER BY generated_at_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return _rows_to_dicts(rows)
