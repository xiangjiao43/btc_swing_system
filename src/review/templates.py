"""
templates.py — Markdown 模板构造(Sprint 1.16b)

build_report_markdown(...) 返回完整 Markdown。任何字段缺失都回退为 "无数据",
不抛异常。
"""

from __future__ import annotations

from typing import Any, Optional


_N_A = "无数据"


def _fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return _N_A
    return f"{x * 100:.1f}%"


def _fmt_num(x: Optional[float], digits: int = 2) -> str:
    if x is None:
        return _N_A
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return _N_A


def _fmt_minutes(x: Optional[float]) -> str:
    if x is None:
        return _N_A
    return f"{x:.1f} 分钟"


def _top_n_distribution(
    dist: dict[str, float],
    n: int = 4,
    exclude_zero: bool = True,
) -> str:
    if not dist:
        return _N_A
    items = [(k, v) for k, v in dist.items() if (not exclude_zero or v > 0)]
    items.sort(key=lambda kv: kv[1], reverse=True)
    if not items:
        return _N_A
    top = items[:n]
    return " / ".join(f"{k} {v * 100:.0f}%" for k, v in top)


# ============================================================
# Sections
# ============================================================

def _section_overview(kpi: dict[str, Any], period_label: str) -> str:
    exe = kpi.get("execution") or {}
    sd = kpi.get("state_distribution") or {}
    cs = sd.get("cold_start_progress") or {}
    runs_total = exe.get("runs_total") or 0
    runs_per_day = exe.get("runs_per_day") or 0
    if cs:
        cs_line = (
            f"- 冷启动进度:{cs.get('runs_completed', 0)}/"
            f"{cs.get('threshold', 42)}({cs.get('percent', 0):.1f}%)"
        )
    else:
        cs_line = "- 冷启动进度:无数据"

    return (
        "## 一、总览\n\n"
        f"- 本周期执行 {runs_total} 次(平均每日 {runs_per_day} 次)\n"
        f"{cs_line}\n"
        f"- 最近一次运行:{exe.get('last_run_at') or _N_A}\n"
        f"- 下次预计运行:{exe.get('next_expected_at') or _N_A}\n"
    )


def _section_market(kpi: dict[str, Any]) -> str:
    # L1 regime 暂未直接聚合,这里显示 state_machine 分布(最接近整体形态)
    sd = kpi.get("state_distribution") or {}
    dec = kpi.get("decision") or {}
    sm_dist = sd.get("state_machine_distribution") or {}
    stance_dist = dec.get("stance_distribution") or {}
    grade_dist = dec.get("grade_distribution") or {}
    return (
        "## 二、市场判断分布\n\n"
        f"- 系统档位(state_machine):{_top_n_distribution(sm_dist)}\n"
        f"- L2 方向(stance):"
        f"bullish {_fmt_pct(stance_dist.get('bullish'))} / "
        f"bearish {_fmt_pct(stance_dist.get('bearish'))} / "
        f"neutral {_fmt_pct(stance_dist.get('neutral'))}\n"
        f"- L3 机会评级(grade):"
        f"A {_fmt_pct(grade_dist.get('A'))} / "
        f"B {_fmt_pct(grade_dist.get('B'))} / "
        f"C {_fmt_pct(grade_dist.get('C'))} / "
        f"none {_fmt_pct(grade_dist.get('none'))}\n"
        f"- 平均 L2 stance_confidence:"
        f"{_fmt_num(dec.get('avg_stance_confidence'))}\n"
    )


def _section_decision(kpi: dict[str, Any]) -> str:
    dec = kpi.get("decision") or {}
    sd = kpi.get("state_distribution") or {}
    ss = kpi.get("stage_success") or {}
    agg = ss.get("_aggregate") or {}
    action_dist = dec.get("adjudicator_action_distribution") or {}
    life_dist = sd.get("lifecycle_distribution") or {}

    ai_rate = agg.get("ai_summary_success_rate")
    adj_rate = agg.get("adjudicator_success_rate")
    ai_line = (
        f"AI 摘要成功率:{_fmt_pct(ai_rate)} "
        f"({agg.get('ai_summary_samples', 0)} 次)"
        if ai_rate is not None else "AI 摘要成功率:无数据"
    )
    adj_line = (
        f"Adjudicator 成功率:{_fmt_pct(adj_rate)} "
        f"({agg.get('adjudicator_samples', 0)} 次)"
        if adj_rate is not None else "Adjudicator 成功率:无数据"
    )

    return (
        "## 三、决策行为\n\n"
        f"- Adjudicator action:{_top_n_distribution(action_dist, n=5)}\n"
        f"- Lifecycle state:{_top_n_distribution(life_dist, n=5)}\n"
        f"- 平均 adjudicator 置信度:"
        f"{_fmt_num(dec.get('avg_adjudicator_confidence'))}\n"
        f"- {ai_line}\n"
        f"- {adj_line}\n"
    )


def _section_data_quality(kpi: dict[str, Any]) -> str:
    dq = kpi.get("data_quality") or {}
    return (
        "## 四、数据质量\n\n"
        f"- Macro 数据完整度(L5):"
        f"{_fmt_num(dq.get('macro_completeness_avg'), 1)}%\n"
        f"- 数据新鲜度(平均 generate-ref 滞后):"
        f"{_fmt_minutes(dq.get('data_freshness_avg_minutes'))}\n"
    )


def _section_fallback(kpi: dict[str, Any]) -> str:
    fb = kpi.get("fallback") or {}
    top = fb.get("top_3_stages") or []
    if top:
        top_lines = "\n".join(
            f"  {i + 1}. {t['stage']}({t['count']} 次)"
            for i, t in enumerate(top)
        )
    else:
        top_lines = f"  {_N_A}"
    level_dist = fb.get("level_distribution") or {}
    return (
        "## 五、降级统计\n\n"
        f"- 总降级事件:{fb.get('events_total', 0)}(平均每日 "
        f"{fb.get('events_per_day', 0.0)} 次)\n"
        "- 级别分布:"
        f"level_1={level_dist.get('level_1', 0)}, "
        f"level_2={level_dist.get('level_2', 0)}, "
        f"level_3={level_dist.get('level_3', 0)}\n"
        f"- Top 3 降级来源:\n{top_lines}\n"
    )


def _section_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return (
            "## 六、关键事件\n\n"
            f"- {_N_A}(本周期未检测到 regime / lifecycle 切换)\n"
        )
    lines = []
    for e in events:
        lines.append(
            f"- {e.get('timestamp', '?')}:{e.get('description', '?')}"
        )
    return "## 六、关键事件\n\n" + "\n".join(lines) + "\n"


def _section_ai_narrative(narrative: Optional[str]) -> str:
    if narrative:
        return (
            "## 七、AI 观察\n\n"
            f"{narrative.strip()}\n"
        )
    return (
        "## 七、AI 观察\n\n"
        "- AI 分析暂不可用(降级跳过本节)\n"
    )


# ============================================================
# Top level
# ============================================================

def build_report_markdown(
    *,
    kpi: dict[str, Any],
    period_label: str,
    period_start_utc: str,
    period_end_utc: str,
    generated_at_utc: str,
    events: Optional[list[dict[str, Any]]] = None,
    ai_narrative: Optional[str] = None,
) -> str:
    head = (
        "# BTC 策略系统复盘报告\n\n"
        f"周期:{period_start_utc} ~ {period_end_utc}({period_label})\n\n"
        f"生成时间:{generated_at_utc}\n\n"
    )
    return (
        head
        + _section_overview(kpi, period_label) + "\n"
        + _section_market(kpi) + "\n"
        + _section_decision(kpi) + "\n"
        + _section_data_quality(kpi) + "\n"
        + _section_fallback(kpi) + "\n"
        + _section_events(events or []) + "\n"
        + _section_ai_narrative(ai_narrative)
    )
