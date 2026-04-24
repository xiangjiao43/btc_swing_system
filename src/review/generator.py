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
