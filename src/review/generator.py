"""
generator.py — Sprint 1.16b Review Report 生成器

流程:
  1. KPICollector.compute_kpis(lookback_days)
  2. 扫近期 strategy_state_history,挑出 regime / stance / lifecycle 切换事件
  3. 可选:调 AI 产生一段 3-5 句中性观察
  4. templates.build_report_markdown(...) 拼 Markdown
  5. generate_and_save() 写到 data/reviews/<period>_<YYYYMMDD>.md

AI 失败或不可用 → 跳过第 7 节,不拖垮整个报告。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from ..kpi import KPICollector
from .templates import build_report_markdown


logger = logging.getLogger(__name__)


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_bjt_pretty(utc_iso: str) -> Optional[str]:
    """Sprint 1.5b-C:ISO UTC → 'YYYY-MM-DD HH:MM (BJT)'。"""
    try:
        from zoneinfo import ZoneInfo
        s = utc_iso[:-1] + "+00:00" if utc_iso.endswith("Z") else utc_iso
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M (BJT)"
        )
    except Exception:
        return None


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


_PERIOD_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


class ReviewReportGenerator:
    """生成 Markdown 复盘报告。"""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        kpi_collector: Optional[KPICollector] = None,
        ai_caller: Optional[Callable[[dict[str, Any]], Optional[str]]] = None,
        now_utc: Optional[datetime] = None,
    ) -> None:
        self.conn = conn
        self._now = now_utc or datetime.now(timezone.utc)
        self._kpi = kpi_collector or KPICollector(conn, now_utc=self._now)
        self._ai_caller = ai_caller

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate(
        self,
        period: str = "weekly",
        *,
        include_ai_narrative: bool = True,
    ) -> str:
        """返回完整 Markdown(不写磁盘)。"""
        lookback = _PERIOD_DAYS.get(period, 7)
        kpi = self._kpi.compute_kpis(lookback_days=lookback)
        events = self._extract_events(lookback_days=lookback)

        ai_narrative: Optional[str] = None
        if include_ai_narrative:
            ai_narrative = self._safe_ai_narrative(kpi)

        period_start = self._now - timedelta(days=lookback)
        return build_report_markdown(
            kpi=kpi,
            period_label=period,
            period_start_utc=_iso(period_start),
            period_end_utc=_iso(self._now),
            generated_at_utc=_iso(self._now),
            events=events,
            ai_narrative=ai_narrative,
        )

    # ------------------------------------------------------------------
    # Sprint 1.5b-C:per-lifecycle 复盘(归档时触发)
    # ------------------------------------------------------------------

    def generate_for_lifecycle(
        self,
        lifecycle_id: str,
        *,
        lifecycle_dict: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """为单个 lifecycle 生成 ReviewReport(建模 §8.3 v1 简化版)。

        - lifecycle_id 必填
        - lifecycle_dict 可选(归档时由 LifecycleManager 已产出,直接传入避免再查 DB)
        """
        if lifecycle_dict is None:
            from ..data.storage.dao import LifecyclesDAO
            row = LifecyclesDAO.get_lifecycle(self.conn, lifecycle_id)
            if row is None:
                raise ValueError(f"lifecycle_id {lifecycle_id} not found")
            lifecycle_dict = row.get("full_data") or {}

        gen_at_utc = _iso(self._now)
        gen_at_bjt = _to_bjt_pretty(gen_at_utc)

        entry_utc = lifecycle_dict.get("origin_time_utc")
        exit_utc = lifecycle_dict.get("exit_time_utc")
        duration_h: Optional[float] = None
        if entry_utc and exit_utc:
            try:
                a = _parse_iso(entry_utc)
                b = _parse_iso(exit_utc)
                duration_h = round((b - a).total_seconds() / 3600.0, 2) if (a and b) else None
            except Exception:
                duration_h = None

        runs_in_lc = self._count_runs_during_lifecycle(entry_utc, exit_utc)

        # v1 简化:dimensional_assessment 4 个 dict 字段返回固定模板,
        # 留 v1.x 真实分维度评估
        dim = {
            "macro_environment": {"contribution": "neutral", "note": "v1 unevaluated"},
            "structural_truth":  {"contribution": "neutral", "note": "v1 unevaluated"},
            "decision_layer":    {"contribution": "neutral", "note": "v1 unevaluated"},
            "execution":         {"contribution": "neutral", "note": "v1 unevaluated"},
        }

        # key_moments_replay:从 position_adjustments 转换
        adjustments = lifecycle_dict.get("position_adjustments") or []
        key_moments = []
        for adj in adjustments:
            if not isinstance(adj, dict):
                continue
            key_moments.append({
                "at_bjt": adj.get("at_bjt"),
                "type": adj.get("adjustment_type"),
                "size_pct": adj.get("size_pct_of_total"),
                "price": adj.get("price"),
                "reason": adj.get("reason"),
                "related_run_id": adj.get("related_run_id"),
            })

        outcome_type = lifecycle_dict.get("final_outcome_type")
        report: dict[str, Any] = {
            "review_id": f"{lifecycle_id}_{gen_at_utc}",
            "lifecycle_id": lifecycle_id,
            "generated_at_utc": gen_at_utc,
            "generated_at_bjt": gen_at_bjt,
            "generated_by": "rule",
            "direction": lifecycle_dict.get("direction"),
            "entry_time_bjt": lifecycle_dict.get("origin_time_bjt"),
            "exit_time_bjt": lifecycle_dict.get("exit_time_bjt"),
            "duration_hours": duration_h,
            "entry_price_avg": lifecycle_dict.get("average_entry_price"),
            "exit_price_avg": lifecycle_dict.get("average_entry_price"),  # v1:同入场价占位
            "max_favorable_pct": lifecycle_dict.get("max_favorable_pct"),
            "max_adverse_pct": lifecycle_dict.get("max_adverse_pct"),
            "realized_pnl_pct": lifecycle_dict.get("realized_pnl_pct"),
            "total_runs_during_lifecycle": runs_in_lc,
            "outcome_type": outcome_type,
            "root_cause_layers": [],   # v1 simplified
            "feedback_to_system": "复盘结果不自动反哺,人工参考",
            "dimensional_assessment": dim,
            "improvements": [],
            "human_review": None,
            "key_moments_replay": key_moments,
            "ai_models_used_in_lifecycle": (
                lifecycle_dict.get("ai_models_used_in_lifecycle") or []
            ),
            "rules_versions_used": lifecycle_dict.get("rules_versions_used") or [],
        }

        # 写入 review_reports 表
        if self.conn is not None:
            try:
                from ..data.storage.dao import ReviewReportsDAO
                ReviewReportsDAO.insert_report(
                    self.conn,
                    run_timestamp_utc=gen_at_utc,
                    lifecycle_id=lifecycle_id,
                    outcome_type=outcome_type,
                    report=report,
                    review_id=report["review_id"],
                    rules_version_at_review=(
                        (lifecycle_dict.get("rules_versions_used") or [None])[-1]
                    ),
                )
                self.conn.commit()
            except Exception as e:
                logger.warning(
                    "ReviewReportsDAO.insert_report failed (non-fatal): %s", e,
                )
        return report

    def maybe_generate_for_closed_lifecycle(
        self,
        prev_lifecycle: Optional[dict[str, Any]],
        current_lifecycle: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """检测"上一次 active 这次 closed"并自动触发。

        判定:
          - prev_lifecycle.status == "active"(且有 lifecycle_id)
          - 且(current_lifecycle is None / 不同 lc / status="closed")
        """
        if not isinstance(prev_lifecycle, dict):
            return None
        if prev_lifecycle.get("status") != "active":
            return None
        prev_id = prev_lifecycle.get("lifecycle_id")
        if not prev_id:
            return None

        # 当前 lc 已 closed 且是同一 id → 用当前的(含 exit_time_utc / realized_pnl_pct)
        archived: dict[str, Any]
        if (
            isinstance(current_lifecycle, dict)
            and current_lifecycle.get("lifecycle_id") == prev_id
            and current_lifecycle.get("status") == "closed"
        ):
            archived = current_lifecycle
        elif current_lifecycle is None or current_lifecycle == {}:
            # post_sm 返回 None(LONG_EXIT 已归档但 LifecycleManager 已写库)
            # 从 DB 反查 closed lc;若查不到退回 prev_lifecycle
            archived = prev_lifecycle
            if self.conn is not None:
                try:
                    from ..data.storage.dao import LifecyclesDAO
                    row = LifecyclesDAO.get_lifecycle(self.conn, prev_id)
                    if row and row.get("full_data"):
                        archived = row["full_data"]
                except Exception:
                    pass
        else:
            # 其他场景(已切到新 lc):归档查 DB
            archived = prev_lifecycle
            if self.conn is not None:
                try:
                    from ..data.storage.dao import LifecyclesDAO
                    row = LifecyclesDAO.get_lifecycle(self.conn, prev_id)
                    if row and row.get("full_data"):
                        archived = row["full_data"]
                except Exception:
                    pass
        return self.generate_for_lifecycle(prev_id, lifecycle_dict=archived)

    def _count_runs_during_lifecycle(
        self, entry_utc: Optional[str], exit_utc: Optional[str],
    ) -> int:
        """SELECT COUNT(*) FROM strategy_runs WHERE entry <= ts <= exit。"""
        if self.conn is None or not entry_utc:
            return 0
        try:
            if exit_utc:
                row = self.conn.execute(
                    "SELECT COUNT(*) AS n FROM strategy_runs "
                    "WHERE reference_timestamp_utc BETWEEN ? AND ?",
                    (entry_utc, exit_utc),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT COUNT(*) AS n FROM strategy_runs "
                    "WHERE reference_timestamp_utc >= ?",
                    (entry_utc,),
                ).fetchone()
            return int(row["n"]) if row else 0
        except Exception:
            return 0

    def generate_and_save(
        self,
        period: str = "weekly",
        *,
        output_dir: str | Path = "data/reviews/",
        include_ai_narrative: bool = True,
    ) -> Path:
        """生成报告并保存为 Markdown 文件,返回绝对路径。"""
        md = self.generate(period=period, include_ai_narrative=include_ai_narrative)
        out_dir = Path(output_dir)
        if not out_dir.is_absolute():
            out_dir = _PROJECT_ROOT / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = self._now.strftime("%Y%m%d")
        filename = f"{period}_{date_str}.md"
        out_path = out_dir / filename
        out_path.write_text(md, encoding="utf-8")
        return out_path

    # ------------------------------------------------------------------
    # Events extraction
    # ------------------------------------------------------------------

    def _extract_events(
        self,
        *,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        """
        扫近期记录,找三类转变事件:
          * state_machine 档位切换
          * lifecycle 切换(previous_lifecycle ≠ current_lifecycle)
          * L3 grade 从 none/C 升到 B/A
        """
        cutoff = _iso(self._now - timedelta(days=lookback_days))
        try:
            rows = self.conn.execute(
                "SELECT reference_timestamp_utc AS run_timestamp_utc, "
                "full_state_json AS state_json FROM strategy_runs "
                "WHERE reference_timestamp_utc >= ? "
                "ORDER BY reference_timestamp_utc ASC",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        events: list[dict[str, Any]] = []
        prev_sm: Optional[str] = None
        prev_grade: Optional[str] = None
        for r in rows:
            ts = r["run_timestamp_utc"]
            try:
                state = json.loads(r["state_json"])
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
            sm = (state.get("state_machine") or {}).get("current_state")
            if sm and prev_sm and sm != prev_sm:
                events.append({
                    "timestamp": ts,
                    "description": f"state_machine 切换:{prev_sm} → {sm}",
                })
            prev_sm = sm or prev_sm

            life = state.get("lifecycle") or {}
            if (
                life.get("current_lifecycle")
                and life.get("previous_lifecycle")
                and life["current_lifecycle"] != life["previous_lifecycle"]
                and life.get("transition_triggered_by") != "no_op"
            ):
                events.append({
                    "timestamp": ts,
                    "description": (
                        f"lifecycle 切换:{life['previous_lifecycle']} → "
                        f"{life['current_lifecycle']}("
                        f"{life.get('transition_triggered_by') or '?'})"
                    ),
                })

            l3 = ((state.get("evidence_reports") or {}).get("layer_3") or {})
            grade = l3.get("opportunity_grade") or l3.get("grade") or "none"
            if prev_grade is not None and grade != prev_grade:
                # 仅标注 none/C → B/A 的升级
                if grade in {"A", "B"} and prev_grade in {"none", "C"}:
                    events.append({
                        "timestamp": ts,
                        "description": f"L3 grade 升级:{prev_grade} → {grade}",
                    })
            prev_grade = grade

        return events

    # ------------------------------------------------------------------
    # AI narrative
    # ------------------------------------------------------------------

    def _safe_ai_narrative(self, kpi: dict[str, Any]) -> Optional[str]:
        """注入的 ai_caller 优先;否则尝试项目默认 novaiapi 客户端。"""
        if self._ai_caller is not None:
            try:
                return self._ai_caller(kpi)
            except Exception as e:
                logger.warning("injected ai_caller failed: %s", e)
                return None
        return _default_ai_narrative(kpi)


# ============================================================
# Default AI narrative (novaiapi, same client as summary / adjudicator)
# ============================================================

def _default_ai_narrative(kpi: dict[str, Any]) -> Optional[str]:
    # Sprint 1.5c C6:切换到 anthropic SDK
    from ..ai.client import build_anthropic_client, effective_model, extract_text
    client = build_anthropic_client(timeout=30.0)
    if client is None:
        return None
    model = effective_model(os.getenv("OPENAI_REVIEW_MODEL"))

    exe = kpi.get("execution") or {}
    dec = kpi.get("decision") or {}
    sd = kpi.get("state_distribution") or {}
    fb = kpi.get("fallback") or {}
    brief = {
        "runs_total": exe.get("runs_total"),
        "runs_per_day": exe.get("runs_per_day"),
        "state_machine_top": dict(
            sorted(
                (sd.get("state_machine_distribution") or {}).items(),
                key=lambda kv: kv[1], reverse=True,
            )[:3]
        ),
        "stance_distribution": dec.get("stance_distribution"),
        "grade_distribution": dec.get("grade_distribution"),
        "avg_stance_confidence": dec.get("avg_stance_confidence"),
        "fallback_events_total": fb.get("events_total"),
        "top_3_fallback_stages": fb.get("top_3_stages"),
    }
    sys_prompt = (
        "你是加密资产策略复盘观察员。基于给定 KPI,用中文写 3-5 句中性观察。"
        "禁止提出操作建议、价格目标、买卖动作。禁止使用'建议''推荐'等词。"
        "只描述系统运行模式、判断分布、降级趋势等可观察事实。"
    )
    user_prompt = (
        "KPI JSON:\n"
        + json.dumps(brief, ensure_ascii=False, indent=2)
        + "\n请给出 3-5 句中性观察。"
    )
    try:
        resp = client.messages.create(
            model=model,
            system=sys_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=0.3,
            max_tokens=400,
        )
        return extract_text(resp).strip() or None
    except Exception as e:
        logger.warning("default ai narrative failed: %s", e)
        return None
