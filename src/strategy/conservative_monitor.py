"""src/strategy/conservative_monitor.py — Sprint 1.10-H S3 过度保守监控。

对齐 docs/modeling.md b25cfe6(v1.4)§8.2:
- 连续 30 天无 thesis 创建 → warning 告警(写 alerts 表)
- 连续 60 天无 thesis 创建 → critical 告警 + 进 review_pending(reason='overly_conservative')
- 由 jobs.py::job_pipeline_run 入口同步调一次(D3=a)

D4=b2 联动:任一新 thesis 创建 → 自动调 exit_d_thesis_resumed 退出过度保守
review_pending(本模块只负责"进",jobs.py 在 thesis 创建后调 exit_d)。

设计纪律:
- 纯规则(查 theses + alerts + system_states),不调 AI
- check_recent_thesis_count 是 stateless 判定(返 dict),raise_alert 单独
- 幂等:30 天阈值同一天多次跑只写一次 alerts(查最近 24h 内是否已写)
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.strategy.review_pending import enter_review_pending


logger = logging.getLogger(__name__)


# v1.4 §8.2 阈值
WARNING_THRESHOLD_DAYS = 30
CRITICAL_THRESHOLD_DAYS = 60

# alerts 表 alert_type
ALERT_TYPE = "overly_conservative"

# review_pending reason(D4=b2 与 exit_d_thesis_resumed 配对)
REVIEW_PENDING_REASON = "overly_conservative"


def _to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class ConservativeMonitor:
    """v1.4 §8.2 过度保守监控。

    用法(在 jobs.py::job_pipeline_run 顶部):
        result = ConservativeMonitor.check_and_alert(
            conn, now_utc=datetime.now(timezone.utc),
        )
        # result 含 days_no_thesis / severity / alert_written / review_pending_entered
        # 调用方 commit
    """

    @staticmethod
    def check_recent_thesis_count(
        conn: sqlite3.Connection,
        *,
        now_utc: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """查最近一次 thesis 创建至今天数 → 判 severity。

        Returns:
          {
            days_no_thesis: int,        # 距最近 thesis 创建天数(若无任何 thesis,= None)
            severity: 'none' | 'warning' | 'critical',
            last_thesis_created_at_utc: str | None,
            threshold_breached: bool,
          }
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        try:
            row = conn.execute(
                "SELECT MAX(created_at_utc) as last_at FROM theses"
            ).fetchone()
        except sqlite3.OperationalError:
            return {
                "days_no_thesis": None,
                "severity": "none",
                "last_thesis_created_at_utc": None,
                "threshold_breached": False,
            }
        last_str = row["last_at"] if hasattr(row, "keys") else (row[0] if row else None)
        if not last_str:
            # 系统从未创建过 thesis → 不触发(冷启动期 30 天内可正常)
            # 只在系统首次创建后才计算"距离上次"
            return {
                "days_no_thesis": None,
                "severity": "none",
                "last_thesis_created_at_utc": None,
                "threshold_breached": False,
            }
        last_dt = _parse_iso(last_str)
        if last_dt is None:
            return {
                "days_no_thesis": None,
                "severity": "none",
                "last_thesis_created_at_utc": last_str,
                "threshold_breached": False,
            }
        days = (now_utc - last_dt).total_seconds() / 86400.0
        if days >= CRITICAL_THRESHOLD_DAYS:
            sev = "critical"
            breached = True
        elif days >= WARNING_THRESHOLD_DAYS:
            sev = "warning"
            breached = True
        else:
            sev = "none"
            breached = False
        return {
            "days_no_thesis": days,
            "severity": sev,
            "last_thesis_created_at_utc": last_str,
            "threshold_breached": breached,
        }

    @staticmethod
    def _has_recent_alert(
        conn: sqlite3.Connection,
        severity: str,
        *,
        now_utc: datetime,
        within_hours: int = 24,
    ) -> bool:
        """检测最近 24h 内是否已写过同 severity 的 overly_conservative 告警(幂等)。"""
        cutoff = (now_utc - timedelta(hours=within_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        try:
            row = conn.execute(
                "SELECT id FROM alerts "
                "WHERE alert_type = ? AND severity = ? "
                "  AND raised_at_utc >= ? "
                "LIMIT 1",
                (ALERT_TYPE, severity, cutoff),
            ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False

    @staticmethod
    def _write_alert(
        conn: sqlite3.Connection,
        *,
        severity: str, message: str, now_iso: str,
        related_run_id: Optional[str] = None,
    ) -> int:
        """裸 INSERT 写 alerts(沿用 state_builder.py 模式;留 1.10-J 重构成 DAO)。"""
        cur = conn.execute(
            "INSERT INTO alerts "
            "(alert_type, severity, message, raised_at_utc, related_run_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (ALERT_TYPE, severity, message, now_iso, related_run_id),
        )
        return cur.lastrowid or 0

    @staticmethod
    def check_and_alert(
        conn: sqlite3.Connection,
        *,
        now_utc: Optional[datetime] = None,
        related_run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """主入口(jobs.py 调):查 + 写 alerts + 触发 review_pending。

        - severity='none' → 不动
        - severity='warning'(30d ≤ days < 60d)→ 写 alerts(若 24h 内未写)
        - severity='critical'(days ≥ 60d)→ 写 alerts + 进 review_pending
          (reason='overly_conservative',exit 由 D4=b2 thesis 创建时调 exit_d)

        幂等:同 severity 24h 内只写一次 alerts;review_pending 已 active 则不重复进。

        Returns:
          {
            days_no_thesis, severity, threshold_breached,
            alert_written: bool,
            review_pending_entered: bool,
          }
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        check = ConservativeMonitor.check_recent_thesis_count(
            conn, now_utc=now_utc,
        )
        result: dict[str, Any] = {
            **check,
            "alert_written": False,
            "review_pending_entered": False,
        }
        if not check["threshold_breached"]:
            return result

        sev = check["severity"]
        days = check["days_no_thesis"]
        now_iso = _to_iso(now_utc)
        msg_prefix = f"S3 过度保守:连续 {int(days)} 天无新 thesis 创建"
        if sev == "warning":
            msg = (
                f"{msg_prefix}(>= {WARNING_THRESHOLD_DAYS} 天阈值)。"
                f"系统可能阈值过严,建议人工审视 L3 grade 阈值。"
            )
        else:
            msg = (
                f"{msg_prefix}(>= {CRITICAL_THRESHOLD_DAYS} 天阈值)。"
                f"系统过度保守,已进 review_pending,请人工介入"
                f"(调阈值 / 续期 thesis / reset 熔断)。"
            )

        # 幂等检查
        if not ConservativeMonitor._has_recent_alert(conn, sev, now_utc=now_utc):
            ConservativeMonitor._write_alert(
                conn, severity=sev, message=msg, now_iso=now_iso,
                related_run_id=related_run_id,
            )
            result["alert_written"] = True
            logger.warning("CONSERVATIVE_MONITOR alert: %s", msg)

        # critical 进 review_pending
        if sev == "critical":
            rp = enter_review_pending(
                conn,
                reason=REVIEW_PENDING_REASON,
                related_thesis_id=None,
                entered_at_utc=now_iso,
            )
            result["review_pending_entered"] = not rp.get("was_already_active", False)
            result["review_pending_state_id"] = rp.get("state_id")

        return result
