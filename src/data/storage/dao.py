"""
dao.py — Data Access Objects

对 9 张表的 CRUD 统一封装。所有 DAO 方法:
  - 第一个位置参数都是 sqlite3.Connection(便于事务 / 测试注入)
  - 只执行单个逻辑操作,不隐式 commit;调用方决定 commit 时机
  - 所有参数与返回值带类型标注(Python 3.12 风格)
  - 新增数据用 upsert 语义(INSERT … ON CONFLICT DO UPDATE)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
MacroSource = Literal["yahoo_finance", "fred"]
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

class BTCKlinesDAO:
    """btc_klines 表的 DAO。"""

    @staticmethod
    def upsert_klines(conn: sqlite3.Connection, klines: list[KlineRow]) -> int:
        """
        批量 upsert K 线。重复 (timeframe, timestamp) 时覆盖 OHLCV + volume + fetched_at。

        Returns:
            受影响行数(insert + update 合计,由 sqlite3 rowcount 给出)。
        """
        sql = """
            INSERT INTO btc_klines
                (timeframe, timestamp, open, high, low, close, volume_btc, volume_usdt, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(timeframe, timestamp) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume_btc = excluded.volume_btc,
                volume_usdt = excluded.volume_usdt,
                fetched_at = excluded.fetched_at
        """
        rows = [
            (k.timeframe, k.timestamp, k.open, k.high, k.low, k.close,
             k.volume_btc, k.volume_usdt, k.fetched_at)
            for k in klines
        ]
        cur = conn.executemany(sql, rows)
        return cur.rowcount

    @staticmethod
    def get_klines(
        conn: sqlite3.Connection,
        timeframe: TimeFrame,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        按 timeframe + 时间区间查 K 线。
        start / end 为 ISO 8601 UTC 字符串(闭区间);None 表示不限。
        返回按 timestamp 升序。
        """
        clauses = ["timeframe = ?"]
        params: list[Any] = [timeframe]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        sql = f"""
            SELECT * FROM btc_klines
            WHERE {' AND '.join(clauses)}
            ORDER BY timestamp ASC
        """
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return _rows_to_dicts(conn.execute(sql, params).fetchall())

    @staticmethod
    def get_latest_kline(
        conn: sqlite3.Connection, timeframe: TimeFrame
    ) -> Optional[dict[str, Any]]:
        """返回最新一根 K 线,无数据时返回 None。"""
        row = conn.execute(
            "SELECT * FROM btc_klines WHERE timeframe = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (timeframe,),
        ).fetchone()
        return _row_to_dict(row)

    @staticmethod
    def count(conn: sqlite3.Connection, timeframe: Optional[TimeFrame] = None) -> int:
        if timeframe is None:
            row = conn.execute("SELECT COUNT(*) AS n FROM btc_klines").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM btc_klines WHERE timeframe = ?",
                (timeframe,),
            ).fetchone()
        return int(row["n"])

    @staticmethod
    def get_recent_as_df(
        conn: sqlite3.Connection,
        timeframe: TimeFrame,
        limit: int = 500,
    ) -> Any:
        """
        取最近 limit 根 K 线,返回 pd.DataFrame(index=DatetimeIndex UTC,
        columns=open/high/low/close/volume_btc/volume_usdt)。Pipeline 专用。
        """
        import pandas as pd
        rows = conn.execute(
            "SELECT * FROM btc_klines WHERE timeframe = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (timeframe, limit),
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        # 升序返回
        data = [dict(r) for r in rows][::-1]
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        # 只保留需要的列,order 稳定
        cols = ["open", "high", "low", "close", "volume_btc", "volume_usdt"]
        return df[[c for c in cols if c in df.columns]]


# ============================================================
# 衍生品 / 链上 / 宏观(长表共用模式)
# ============================================================

class _MetricLongTableDAO:
    """
    三个长表(derivatives_snapshot / onchain_snapshot / macro_snapshot)的共用逻辑。
    子类指定 _table、_has_source。
    """

    _table: str = ""
    _has_source: bool = False

    @classmethod
    def _cols(cls) -> list[str]:
        cols = ["timestamp", "metric_name", "metric_value"]
        if cls._has_source:
            cols.append("source")
        cols.append("fetched_at")
        return cols

    @classmethod
    def upsert_batch(cls, conn: sqlite3.Connection, rows: list[Any]) -> int:
        cols = cls._cols()
        placeholders = ", ".join(["?"] * len(cols))
        col_list = ", ".join(cols)
        updates = ", ".join(
            f"{c} = excluded.{c}" for c in cols if c not in ("timestamp", "metric_name")
        )
        sql = f"""
            INSERT INTO {cls._table} ({col_list})
            VALUES ({placeholders})
            ON CONFLICT(timestamp, metric_name) DO UPDATE SET {updates}
        """
        values = []
        for r in rows:
            d = asdict(r)
            values.append(tuple(d[c] for c in cols))
        cur = conn.executemany(sql, values)
        return cur.rowcount

    @classmethod
    def get_at(
        cls, conn: sqlite3.Connection, timestamp: str
    ) -> list[dict[str, Any]]:
        """返回某时刻的所有指标。"""
        rows = conn.execute(
            f"SELECT * FROM {cls._table} WHERE timestamp = ? ORDER BY metric_name",
            (timestamp,),
        ).fetchall()
        return _rows_to_dicts(rows)

    @classmethod
    def get_latest(
        cls, conn: sqlite3.Connection, metric_name: str
    ) -> Optional[dict[str, Any]]:
        """返回指定指标的最新值。"""
        row = conn.execute(
            f"SELECT * FROM {cls._table} WHERE metric_name = ? "
            f"ORDER BY timestamp DESC LIMIT 1",
            (metric_name,),
        ).fetchone()
        return _row_to_dict(row)

    @classmethod
    def get_series(
        cls,
        conn: sqlite3.Connection,
        metric_name: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """返回指标的时间序列(升序)。"""
        clauses = ["metric_name = ?"]
        params: list[Any] = [metric_name]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        sql = (
            f"SELECT * FROM {cls._table} WHERE {' AND '.join(clauses)} "
            f"ORDER BY timestamp ASC"
        )
        return _rows_to_dicts(conn.execute(sql, params).fetchall())

    @classmethod
    def get_distinct_metric_names(
        cls, conn: sqlite3.Connection,
    ) -> list[str]:
        """返回该表里出现过的所有 metric_name。"""
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
        """
        返回 {metric_name: pd.Series}(index=DatetimeIndex UTC,升序)。
        只包含最近 `lookback_days` 天的数据。Pipeline 专用。
        """
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


class DerivativesDAO(_MetricLongTableDAO):
    """derivatives_snapshot 表。"""
    _table = "derivatives_snapshot"
    _has_source = False


class OnchainDAO(_MetricLongTableDAO):
    """onchain_snapshot 表。"""
    _table = "onchain_snapshot"
    _has_source = True


class MacroDAO(_MetricLongTableDAO):
    """macro_snapshot 表。"""
    _table = "macro_snapshot"
    _has_source = True


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

class StrategyStateDAO:
    """strategy_state_history 表 DAO。"""

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
        """插入一条 StrategyState。state 是 12 业务块 dict,会被 json.dumps。"""
        sql = """
            INSERT INTO strategy_state_history
                (run_timestamp_utc, run_id, run_trigger, rules_version,
                 ai_model_actual, state_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_timestamp_utc) DO UPDATE SET
                run_id = excluded.run_id,
                run_trigger = excluded.run_trigger,
                rules_version = excluded.rules_version,
                ai_model_actual = excluded.ai_model_actual,
                state_json = excluded.state_json,
                created_at = excluded.created_at
        """
        cur = conn.execute(
            sql,
            (run_timestamp_utc, run_id, run_trigger, rules_version,
             ai_model_actual, json.dumps(state, ensure_ascii=False),
             _utc_now_iso()),
        )
        return cur.rowcount

    @staticmethod
    def get_state(
        conn: sqlite3.Connection, run_timestamp_utc: str
    ) -> Optional[dict[str, Any]]:
        """获取一次运行的 StrategyState(state_json 自动解析为 dict)。"""
        row = conn.execute(
            "SELECT * FROM strategy_state_history WHERE run_timestamp_utc = ?",
            (run_timestamp_utc,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["state"] = json.loads(d.pop("state_json"))
        return d

    @staticmethod
    def get_latest_state(
        conn: sqlite3.Connection,
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM strategy_state_history "
            "ORDER BY run_timestamp_utc DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["state"] = json.loads(d.pop("state_json"))
        return d

    @staticmethod
    def get_recent_states(
        conn: sqlite3.Connection, limit: int = 5
    ) -> list[dict[str, Any]]:
        """获取最近 N 次运行的 StrategyState;用于 AI 输入的 recent_runs 浓缩。"""
        rows = conn.execute(
            "SELECT * FROM strategy_state_history "
            "ORDER BY run_timestamp_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["state"] = json.loads(d.pop("state_json"))
            result.append(d)
        return result

    @staticmethod
    def get_count(conn: sqlite3.Connection) -> int:
        """历史 StrategyState 条数,用于 cold_start 判定。"""
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_state_history"
        ).fetchone()
        return int(row["n"])

    @staticmethod
    def get_latest_non_unclear_cycle(
        conn: sqlite3.Connection,
    ) -> Optional[str]:
        """
        倒序扫描 strategy_state_history,找到最近一条 cycle_position.band ≠ 'unclear'
        的 band 值(例如 'accumulation' / 'distribution' / 'peak' / 'bottom' 等)。
        无命中时返回 None。Pipeline 用来给 CyclePosition 提供"上次稳定判定"。
        """
        sql = """
            SELECT json_extract(state_json, '$.composite_factors.cycle_position.band') AS band
            FROM strategy_state_history
            WHERE json_extract(state_json, '$.composite_factors.cycle_position.band')
                  IS NOT NULL
              AND json_extract(state_json, '$.composite_factors.cycle_position.band')
                  != 'unclear'
            ORDER BY run_timestamp_utc DESC
            LIMIT 1
        """
        try:
            row = conn.execute(sql).fetchone()
        except sqlite3.OperationalError:
            # 兼容 json_extract 不可用的极端场景(理论上 SQLite 3.38+ 均支持)
            return None
        if row is None:
            return None
        return row["band"]


# ============================================================
# ReviewReport
# ============================================================

class ReviewReportsDAO:
    """review_reports 表 DAO。"""

    @staticmethod
    def insert_report(
        conn: sqlite3.Connection,
        run_timestamp_utc: str,
        lifecycle_id: str,
        outcome_type: Optional[str],
        report: dict[str, Any],
    ) -> int:
        sql = """
            INSERT INTO review_reports
                (run_timestamp_utc, lifecycle_id, outcome_type, report_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_timestamp_utc) DO UPDATE SET
                lifecycle_id = excluded.lifecycle_id,
                outcome_type = excluded.outcome_type,
                report_json = excluded.report_json,
                created_at = excluded.created_at
        """
        cur = conn.execute(
            sql,
            (run_timestamp_utc, lifecycle_id, outcome_type,
             json.dumps(report, ensure_ascii=False), _utc_now_iso()),
        )
        return cur.rowcount

    @staticmethod
    def get_reports_for_lifecycle(
        conn: sqlite3.Connection, lifecycle_id: str
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM review_reports WHERE lifecycle_id = ? "
            "ORDER BY run_timestamp_utc ASC",
            (lifecycle_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["report"] = json.loads(d.pop("report_json"))
            result.append(d)
        return result


# ============================================================
# Fallback 日志
# ============================================================

class FallbackLogDAO:
    """fallback_log 表 DAO。"""

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
            "INSERT INTO fallback_log "
            "(run_timestamp_utc, fallback_level, triggered_by, details, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_timestamp_utc, fallback_level, triggered_by, details_json,
             _utc_now_iso()),
        )
        return cur.rowcount

    @staticmethod
    def count_recent_at_level(
        conn: sqlite3.Connection,
        fallback_level: FallbackLevel,
        since_utc: str,
    ) -> int:
        """自 since_utc 起,某档 Fallback 触发次数;M33 auto_upgrade 判定用。"""
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM fallback_log "
            "WHERE fallback_level = ? AND run_timestamp_utc >= ?",
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
        """
        从 run_timestamp_utc 倒序扫 fallback_log,统计连续 level_1 的次数。
        碰到非 level_1 或无记录即停止。用于 "Level 1 连续触发 ≥ 5 次升级"。
        """
        count = 0
        rows = conn.execute(
            "SELECT fallback_level FROM fallback_log "
            "WHERE run_timestamp_utc <= ? "
            "ORDER BY run_timestamp_utc DESC",
            (run_timestamp_utc,),
        ).fetchall()
        for r in rows:
            if r["fallback_level"] == "level_1":
                count += 1
            else:
                break
        return count


# ============================================================
# 运行元数据
# ============================================================

class RunMetadataDAO:
    """run_metadata 表 DAO。"""

    @staticmethod
    def start_run(
        conn: sqlite3.Connection,
        run_id: str,
        run_timestamp_utc: str,
        run_trigger: str,
    ) -> int:
        cur = conn.execute(
            "INSERT INTO run_metadata "
            "(run_id, run_timestamp_utc, run_trigger, status, started_at) "
            "VALUES (?, ?, ?, 'started', ?)",
            (run_id, run_timestamp_utc, run_trigger, _utc_now_iso()),
        )
        return cur.rowcount

    @staticmethod
    def finish_run(
        conn: sqlite3.Connection,
        run_id: str,
        status: RunStatus,
        notes: Optional[str] = None,
    ) -> int:
        cur = conn.execute(
            "UPDATE run_metadata SET "
            "status = ?, finished_at = ?, notes = COALESCE(?, notes) "
            "WHERE run_id = ?",
            (status, _utc_now_iso(), notes, run_id),
        )
        return cur.rowcount

    @staticmethod
    def get_run(
        conn: sqlite3.Connection, run_id: str
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM run_metadata WHERE run_id = ?", (run_id,)
        ).fetchone()
        return _row_to_dict(row)

    @staticmethod
    def get_recent_runs(
        conn: sqlite3.Connection, limit: int = 10
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM run_metadata "
            "ORDER BY run_timestamp_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return _rows_to_dicts(rows)
