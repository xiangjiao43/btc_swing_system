"""
collector.py — Sprint 1.16a KPI Tracker

从 strategy_state_history 和 fallback_log 直接 SQL 聚合,产出 6 大类 KPI:

  execution          总次数 / 日均次数 / 首末时间戳
  stage_success      每个 stage 的成功率 + ai_summary / adjudicator 成功率
  state_distribution state_machine / lifecycle 分布 + cold_start_progress
  decision           action / stance / grade 分布 + 平均 confidence
  data_quality       macro_completeness 均值 / data_freshness 占位
  fallback           总事件数 / 日均 / top_3_stages

空库 → 每类返回合理默认(0 / {} / None),不抛异常。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .metrics import (
    ADJUDICATOR_ACTIONS,
    DEFAULT_COLD_START_THRESHOLD,
    LIFECYCLE_STATES,
    PIPELINE_STAGES,
    STATE_MACHINE_STATES,
)


logger = logging.getLogger(__name__)


# ============================================================
# Helpers
# ============================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _pct_dict(counter: Counter, ordered: tuple[str, ...]) -> dict[str, float]:
    """Counter → {label: 0.0-1.0};ordered 保证输出 label 顺序稳定。"""
    total = sum(counter.values()) or 0
    if total == 0:
        return {k: 0.0 for k in ordered}
    out = {k: round(counter.get(k, 0) / total, 4) for k in ordered}
    # 如果 counter 里还有 ordered 里没列的 label(schema 未预期),也一并报出
    for k in counter:
        if k not in out:
            out[k] = round(counter[k] / total, 4)
    return out


def _safe_mean(values: list[float]) -> Optional[float]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


# ============================================================
# KPICollector
# ============================================================

class KPICollector:
    """对 SQLite 直接 SQL 查询,产出 KPI dict。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        now_utc: Optional[datetime] = None,
    ) -> None:
        self.conn = conn
        self._now = now_utc or _utc_now()

    # ------------------------------------------------------------------
    # Top-level
    # ------------------------------------------------------------------

    def compute_kpis(self, lookback_days: int = 7) -> dict[str, Any]:
        """入口:按 6 大类返回 KPI dict。"""
        rows = self._fetch_states_in_window(lookback_days)
        fallbacks = self._fetch_fallback_in_window(lookback_days)
        return {
            "generated_at_utc": _iso(self._now),
            "lookback_days": lookback_days,
            "execution": self._compute_execution(rows, lookback_days),
            "stage_success": self._compute_stage_success(rows),
            "state_distribution": self._compute_state_distribution(rows),
            "decision": self._compute_decision(rows),
            "data_quality": self._compute_data_quality(rows),
            "fallback": self._compute_fallback(fallbacks, lookback_days),
        }

    # ------------------------------------------------------------------
    # Individual computations
    # ------------------------------------------------------------------

    def compute_stage_success_rate(
        self, lookback_days: int = 7,
    ) -> dict[str, dict[str, Any]]:
        rows = self._fetch_states_in_window(lookback_days)
        return self._compute_stage_success(rows)

    def compute_state_distribution(
        self, lookback_days: int = 7,
    ) -> dict[str, Any]:
        rows = self._fetch_states_in_window(lookback_days)
        return self._compute_state_distribution(rows)

    def compute_adjudicator_distribution(
        self, lookback_days: int = 7,
    ) -> dict[str, Any]:
        rows = self._fetch_states_in_window(lookback_days)
        return self._compute_decision(rows)

    def compute_fallback_stats(
        self, lookback_days: int = 7,
    ) -> dict[str, Any]:
        fallbacks = self._fetch_fallback_in_window(lookback_days)
        return self._compute_fallback(fallbacks, lookback_days)

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _window_start(self, lookback_days: int) -> str:
        return _iso(self._now - timedelta(days=lookback_days))

    def _fetch_states_in_window(
        self, lookback_days: int,
    ) -> list[dict[str, Any]]:
        cutoff = self._window_start(lookback_days)
        try:
            rows = self.conn.execute(
                "SELECT run_timestamp_utc, run_id, run_trigger, "
                "rules_version, ai_model_actual, state_json "
                "FROM strategy_state_history "
                "WHERE run_timestamp_utc >= ? "
                "ORDER BY run_timestamp_utc ASC",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("strategy_state_history not readable: %s", e)
            return []
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["state"] = json.loads(d.pop("state_json"))
            except (json.JSONDecodeError, ValueError, TypeError):
                d["state"] = {}
            out.append(d)
        return out

    def _fetch_fallback_in_window(
        self, lookback_days: int,
    ) -> list[dict[str, Any]]:
        cutoff = self._window_start(lookback_days)
        try:
            rows = self.conn.execute(
                "SELECT id, run_timestamp_utc, fallback_level, "
                "triggered_by, details, created_at "
                "FROM fallback_log "
                "WHERE run_timestamp_utc >= ? "
                "ORDER BY run_timestamp_utc ASC",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("fallback_log not readable: %s", e)
            return []
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            raw = d.get("details")
            if isinstance(raw, str) and raw:
                try:
                    d["details"] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    d["details"] = {"_raw": raw}
            out.append(d)
        return out

    # ------------------------------------------------------------------
    # Category: execution
    # ------------------------------------------------------------------

    def _compute_execution(
        self,
        rows: list[dict[str, Any]],
        lookback_days: int,
    ) -> dict[str, Any]:
        if not rows:
            return {
                "runs_total": 0,
                "runs_per_day": 0.0,
                "first_run_at": None,
                "last_run_at": None,
                "next_expected_at": None,
            }
        runs_total = len(rows)
        first = rows[0]["run_timestamp_utc"]
        last = rows[-1]["run_timestamp_utc"]
        # APScheduler 默认 4 小时一次 → +4h 作为 next_expected_at 的粗估
        next_expected = None
        last_dt = _parse_iso(last)
        if last_dt is not None:
            next_expected = _iso(last_dt + timedelta(hours=4))
        return {
            "runs_total": runs_total,
            "runs_per_day": round(runs_total / max(1, lookback_days), 3),
            "first_run_at": first,
            "last_run_at": last,
            "next_expected_at": next_expected,
        }

    # ------------------------------------------------------------------
    # Category: stage_success
    # ------------------------------------------------------------------

    def _compute_stage_success(
        self, rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        total = len(rows)
        if total == 0:
            return {s: {"success_rate": None, "samples": 0,
                        "degraded_count": 0} for s in PIPELINE_STAGES}

        degraded_counts: Counter = Counter()
        ai_summary_success = 0
        ai_summary_total = 0
        adjudicator_success = 0
        adjudicator_total = 0

        for r in rows:
            state = r["state"] or {}
            meta = state.get("pipeline_meta") or {}
            degraded = meta.get("degraded_stages") or []
            for s in degraded:
                degraded_counts[s] += 1

            # ai_summary 成功率
            ctx = state.get("context_summary") or {}
            status = ctx.get("status")
            if status:
                ai_summary_total += 1
                if status == "success":
                    ai_summary_success += 1

            # adjudicator 成功率
            adj = state.get("adjudicator") or {}
            adj_status = adj.get("status")
            if adj_status:
                adjudicator_total += 1
                if adj_status == "success":
                    adjudicator_success += 1

        per_stage: dict[str, dict[str, Any]] = {}
        for stage in PIPELINE_STAGES:
            deg = int(degraded_counts.get(stage, 0))
            succ = total - deg
            per_stage[stage] = {
                "samples": total,
                "success_count": succ,
                "degraded_count": deg,
                "success_rate": round(succ / total, 4),
            }

        per_stage["_aggregate"] = {
            "ai_summary_success_rate": (
                round(ai_summary_success / ai_summary_total, 4)
                if ai_summary_total else None
            ),
            "ai_summary_samples": ai_summary_total,
            "adjudicator_success_rate": (
                round(adjudicator_success / adjudicator_total, 4)
                if adjudicator_total else None
            ),
            "adjudicator_samples": adjudicator_total,
        }
        return per_stage

    # ------------------------------------------------------------------
    # Category: state_distribution
    # ------------------------------------------------------------------

    def _compute_state_distribution(
        self, rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        sm_counter: Counter = Counter()
        life_counter: Counter = Counter()
        latest_cold_start: Optional[dict[str, Any]] = None

        for r in rows:
            state = r["state"] or {}
            sm = (state.get("state_machine") or {}).get("current_state")
            if sm:
                sm_counter[sm] += 1
            life = (state.get("lifecycle") or {}).get("current_lifecycle")
            if life:
                life_counter[life] += 1
            cs = state.get("cold_start") or {}
            if cs:
                latest_cold_start = cs

        # cold start progress
        cold_start_progress = None
        if latest_cold_start:
            runs = int(latest_cold_start.get("runs_completed") or 0)
            threshold = int(
                latest_cold_start.get("threshold")
                or DEFAULT_COLD_START_THRESHOLD
            )
            pct = min(100.0, round(100.0 * runs / max(1, threshold), 2))
            cold_start_progress = {
                "runs_completed": runs,
                "threshold": threshold,
                "percent": pct,
                "warming_up": bool(latest_cold_start.get("warming_up")),
            }

        return {
            "state_machine_distribution": _pct_dict(
                sm_counter, STATE_MACHINE_STATES,
            ),
            "lifecycle_distribution": _pct_dict(
                life_counter, LIFECYCLE_STATES,
            ),
            "cold_start_progress": cold_start_progress,
            "total_runs": len(rows),
        }

    # ------------------------------------------------------------------
    # Category: decision
    # ------------------------------------------------------------------

    def _compute_decision(
        self, rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        action_counter: Counter = Counter()
        stance_counter: Counter = Counter()
        grade_counter: Counter = Counter()
        stance_confidences: list[float] = []
        adj_confidences: list[float] = []

        for r in rows:
            state = r["state"] or {}
            adj = state.get("adjudicator") or {}
            action = adj.get("action")
            if action:
                action_counter[action] += 1
            try:
                adj_conf = adj.get("confidence")
                if adj_conf is not None:
                    adj_confidences.append(float(adj_conf))
            except (TypeError, ValueError):
                pass

            l2 = ((state.get("evidence_reports") or {}).get("layer_2") or {})
            stance = l2.get("stance")
            if stance:
                stance_counter[stance] += 1
            try:
                sc = l2.get("stance_confidence")
                if sc is not None:
                    stance_confidences.append(float(sc))
            except (TypeError, ValueError):
                pass

            l3 = ((state.get("evidence_reports") or {}).get("layer_3") or {})
            grade = l3.get("opportunity_grade") or l3.get("grade") or "none"
            grade_counter[grade] += 1

        return {
            "adjudicator_action_distribution": _pct_dict(
                action_counter, ADJUDICATOR_ACTIONS,
            ),
            "stance_distribution": _pct_dict(
                stance_counter, ("bullish", "bearish", "neutral"),
            ),
            "grade_distribution": _pct_dict(
                grade_counter, ("A", "B", "C", "none"),
            ),
            "avg_stance_confidence": _safe_mean(stance_confidences),
            "avg_adjudicator_confidence": _safe_mean(adj_confidences),
            "samples": len(rows),
        }

    # ------------------------------------------------------------------
    # Category: data_quality
    # ------------------------------------------------------------------

    def _compute_data_quality(
        self, rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        macro_completeness: list[float] = []
        data_freshness_minutes: list[float] = []

        for r in rows:
            state = r["state"] or {}
            l5 = ((state.get("evidence_reports") or {}).get("layer_5") or {})
            mc = l5.get("data_completeness_pct")
            if mc is not None:
                try:
                    macro_completeness.append(float(mc))
                except (TypeError, ValueError):
                    pass
            # 数据新鲜度:reference_timestamp_utc vs created_at 差值
            ref = _parse_iso(state.get("reference_timestamp_utc"))
            gen = _parse_iso(state.get("generated_at_utc"))
            if ref and gen:
                delta = abs((gen - ref).total_seconds()) / 60.0
                if delta < 24 * 60:  # 忽略极端值
                    data_freshness_minutes.append(delta)

        return {
            "macro_completeness_avg": _safe_mean(macro_completeness),
            "data_freshness_avg_minutes": _safe_mean(data_freshness_minutes),
            "samples": len(rows),
        }

    # ------------------------------------------------------------------
    # Category: fallback
    # ------------------------------------------------------------------

    def _compute_fallback(
        self,
        fallbacks: list[dict[str, Any]],
        lookback_days: int,
    ) -> dict[str, Any]:
        if not fallbacks:
            return {
                "events_total": 0,
                "events_per_day": 0.0,
                "top_3_stages": [],
                "level_distribution": {
                    "level_1": 0, "level_2": 0, "level_3": 0,
                },
            }

        level_counter: Counter = Counter()
        stage_counter: Counter = Counter()
        for ev in fallbacks:
            level_counter[ev.get("fallback_level") or "unknown"] += 1
            # triggered_by 形如 "pipeline.ai_summary",抽 stage
            trig = ev.get("triggered_by") or ""
            if "." in trig:
                stage = trig.split(".", 1)[1]
            else:
                stage = trig or "unknown"
            stage_counter[stage] += 1

        top_3 = [
            {"stage": stage, "count": count}
            for stage, count in stage_counter.most_common(3)
        ]
        return {
            "events_total": len(fallbacks),
            "events_per_day": round(len(fallbacks) / max(1, lookback_days), 3),
            "top_3_stages": top_3,
            "level_distribution": {
                "level_1": int(level_counter.get("level_1", 0)),
                "level_2": int(level_counter.get("level_2", 0)),
                "level_3": int(level_counter.get("level_3", 0)),
            },
        }


# ============================================================
# Convenience
# ============================================================

def compute_kpis(
    conn: sqlite3.Connection,
    *,
    lookback_days: int = 7,
    now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    return KPICollector(conn, now_utc=now_utc).compute_kpis(lookback_days)
