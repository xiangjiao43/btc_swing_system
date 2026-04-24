"""
observation_classifier.py — Sprint 1.5b,建模 §4.7 Observation Classifier。

定位(§4.7.1):
  规则层产出,不由 AI 产出。位置在 L3 证据层输出之后、AI 裁决之前。
  作为独立模块 `src/strategy/observation_classifier.py::classify` 被
  StrategyStateBuilder 调用,结果写入 state['observation']。

四档(§4.7.2 + §4.7.5):
  - disciplined:证据明确不利于开仓
  - watchful:证据有正面但不足以开仓
  - possibly_suppressed:多项正面证据存在但叠加后仍无机会(需告警)
  - cold_start_warming_up:冷启动期(运行 < 7 天)的临时标签

纪律条款(§4.7.4)——本模块的所有消费方必须遵守:
  * observation_category 是系统**自我观察的产物**,不是系统自我**调节**的依据。
  * 任何让它进入决策路径的代码实现都违反建模:
    - 证据层证据判定逻辑
    - 组合因子计算
    - position_cap 合成
    - execution_permission 归并
    - 状态机迁移规则
    - L3 规则表
    - Fallback 规则
  * AI 裁决只读,不因此调整行为;possibly_suppressed 时 AI 依然按正常标准评估,
    不"因为系统疑似保守就激进一点"。
  * 只读、只展示、只告警。

告警触发(§4.7.5,本模块只标注 alert_level,实际推送留给 Sprint 1.5c+ 的 alert 系统):
  * possibly_suppressed 连续 ≥ 14 天(84 次运行)→ warning
  * possibly_suppressed 连续 ≥ 30 天(180 次运行)→ critical
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import yaml
from pathlib import Path

from ..utils.cold_start import is_cold_start, DEFAULT_COLD_START_RUNS


logger = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

_COLD_START_DEFAULT_RUNS: int = DEFAULT_COLD_START_RUNS  # 建模 §4.7.5(来自 src.utils.cold_start)
_POSSIBLY_SUPPRESSED_STREAK_RUNS: int = 42  # §4.7.3:连续 ≥ 7 天(42 次)
_WARNING_STREAK_RUNS: int = 84            # §4.7.5:≥ 14 天
_CRITICAL_STREAK_RUNS: int = 180          # §4.7.5:≥ 30 天

_DEFAULT_STANCE_CONFIDENCE_THRESHOLD: float = 0.60  # 对齐 state_machine.yaml long_min


@dataclass
class ObservationResult:
    """observation_classifier 输出。写入 state['observation']。"""

    observation_category: str                   # disciplined/watchful/possibly_suppressed/cold_start_warming_up
    suppressed_base_satisfied: bool             # 本 tick 是否满足 possibly_suppressed 基础 6 条
    streak_runs: int                            # 满足 suppressed_base 的连续运行数(含本 tick)
    alert_level: Optional[str] = None           # None / warning / critical
    reason: str = ""                            # 人类可读命中说明
    signals: dict[str, Any] = field(default_factory=dict)
    discipline_note: str = (
        "observation_category 只读:禁止进入任何决策路径(层证据判定、组合因子、"
        "position_cap、permission、状态机、L3 规则表、Fallback)。"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# Public API
# ============================================================

def classify(
    strategy_state: dict[str, Any],
    *,
    previous_records: Optional[list[dict[str, Any]]] = None,
    stance_confidence_threshold: Optional[float] = None,
) -> dict[str, Any]:
    """
    按建模 §4.7.3 判定 observation_category。

    Args:
        strategy_state:
            本轮已填好 L1-L5 + composite_factors + cold_start + state_machine 的 state。
        previous_records:
            可选。最近若干条 strategy_state_history 行(从 DAO.get_recent_states 取,
            越新越靠前),用于 possibly_suppressed 的"连续 42 次运行"计数。
        stance_confidence_threshold:
            动态门槛;默认 0.60。

    Returns:
        ObservationResult.to_dict()
    """
    l1 = _get_layer(strategy_state, "layer_1")
    l2 = _get_layer(strategy_state, "layer_2")
    l3 = _get_layer(strategy_state, "layer_3")
    l4 = _get_layer(strategy_state, "layer_4")
    l5 = _get_layer(strategy_state, "layer_5")
    cold_start = strategy_state.get("cold_start") or {}
    sm = strategy_state.get("state_machine") or {}
    composites = strategy_state.get("composite_factors") or {}

    l1_regime = l1.get("regime") or l1.get("regime_primary")
    l1_vol = l1.get("volatility_regime") or l1.get("volatility_level")
    l1_regime_confidence = _as_float(l1.get("regime_confidence"))
    l2_stance = l2.get("stance")
    l2_stance_confidence = _as_float(l2.get("stance_confidence"))
    l3_grade = l3.get("opportunity_grade") or l3.get("grade")
    l4_overall_risk = (
        l4.get("overall_risk_level") or l4.get("overall_risk")
    )
    l5_macro_stance = l5.get("macro_stance") or l5.get("macro_environment")
    sm_current = sm.get("current_state")
    cycle_position = (
        (composites.get("cycle_position") or {}).get("cycle_position")
        or (composites.get("cycle_position") or {}).get("band")
    )

    stance_conf_threshold = (
        stance_confidence_threshold
        if stance_confidence_threshold is not None
        else _DEFAULT_STANCE_CONFIDENCE_THRESHOLD
    )

    signals = {
        "l1_regime": l1_regime,
        "l1_volatility_regime": l1_vol,
        "l1_regime_confidence": l1_regime_confidence,
        "l2_stance": l2_stance,
        "l2_stance_confidence": l2_stance_confidence,
        "l3_opportunity_grade": l3_grade,
        "l4_overall_risk_level": l4_overall_risk,
        "l5_macro_stance": l5_macro_stance,
        "state_machine_current": sm_current,
        "cycle_position": cycle_position,
        "cold_start_warming_up": bool(cold_start.get("warming_up")),
        "runs_completed": int(cold_start.get("runs_completed") or 0),
    }

    # ---------- §4.7.3 disciplined 触发(任一即触发)----------
    disciplined_triggers: list[str] = []
    if l1_regime in {"chaos", "transition_up", "transition_down"}:
        disciplined_triggers.append(f"l1_regime={l1_regime}")
    if l1_vol == "extreme":
        disciplined_triggers.append("l1_volatility_regime=extreme")
    if l2_stance == "neutral":
        disciplined_triggers.append("l2_stance=neutral")
    if cycle_position == "unclear":
        disciplined_triggers.append("cycle_position=unclear")
    if l4_overall_risk in {"high", "critical"}:
        disciplined_triggers.append(f"l4_overall_risk_level={l4_overall_risk}")
    if l5_macro_stance == "extreme_risk_off":
        disciplined_triggers.append("l5_macro_stance=extreme_risk_off")
    if sm_current in {"PROTECTION", "POST_PROTECTION_REASSESS"}:
        disciplined_triggers.append(f"state_machine={sm_current}")

    # ---------- possibly_suppressed 基础 6 条(不包含 streak)----------
    # §4.7.3:同时满足 + L3.opportunity_grade = none + 不满足 disciplined
    suppressed_base_conds = {
        "not_disciplined": len(disciplined_triggers) == 0,
        "l1_regime_trend": l1_regime in {"trend_up", "trend_down"},
        "l1_regime_confidence_gte_0.7": (
            l1_regime_confidence is not None and l1_regime_confidence >= 0.7
        ),
        "l2_stance_confidence_gte_threshold": (
            l2_stance_confidence is not None
            and l2_stance_confidence >= stance_conf_threshold
        ),
        "cycle_position_not_unclear": (
            cycle_position is not None and cycle_position != "unclear"
        ),
        "l3_grade_is_none": l3_grade == "none",
    }
    suppressed_base_satisfied = all(suppressed_base_conds.values())

    # 计 streak:本 tick 满足则 streak = 前序 streak + 1,否则 0
    prior_streak = _count_prior_suppressed_streak(previous_records or [])
    streak_runs = (prior_streak + 1) if suppressed_base_satisfied else 0

    # ---------- 选分类(建模 §4.7.3 + §4.7.5 冷启动优先)----------
    if disciplined_triggers:
        category = "disciplined"
        reason = "disciplined(任一触发):" + "; ".join(disciplined_triggers)
    elif is_cold_start(strategy_state, threshold_runs=_COLD_START_DEFAULT_RUNS):
        # 冷启动期若未满足 disciplined 硬触发,用 cold_start_warming_up 临时标签
        category = "cold_start_warming_up"
        reason = (
            f"冷启动期(已运行 {signals['runs_completed']}/"
            f"{_COLD_START_DEFAULT_RUNS} 次)"
        )
    elif suppressed_base_satisfied and streak_runs >= _POSSIBLY_SUPPRESSED_STREAK_RUNS:
        category = "possibly_suppressed"
        reason = (
            f"possibly_suppressed:六条基础条件连续 {streak_runs} 次运行(≥ "
            f"{_POSSIBLY_SUPPRESSED_STREAK_RUNS})且仍未触发 A/B/C 机会"
        )
    elif _watchful_conditions_met(
        l1_regime=l1_regime,
        l2_stance=l2_stance,
        l3_grade=l3_grade,
        l4_overall_risk=l4_overall_risk,
    ):
        category = "watchful"
        reason = "watchful:L1 regime 明确 + L2 stance 有向 + L3 grade C/none + L4 风险可控"
    else:
        # 兜底归到 watchful(非 disciplined / 非 suppressed / 非冷启动)
        category = "watchful"
        reason = "watchful(兜底):不满足 disciplined / possibly_suppressed / cold_start"

    alert_level = _alert_level_for(
        category=category, streak_runs=streak_runs,
    )

    return ObservationResult(
        observation_category=category,
        suppressed_base_satisfied=suppressed_base_satisfied,
        streak_runs=streak_runs,
        alert_level=alert_level,
        reason=reason,
        signals=signals,
    ).to_dict()


# ============================================================
# 辅助
# ============================================================

def _watchful_conditions_met(
    *,
    l1_regime: Optional[str],
    l2_stance: Optional[str],
    l3_grade: Optional[str],
    l4_overall_risk: Optional[str],
) -> bool:
    """§4.7.3 watchful:同时满足(已假设非 disciplined)。"""
    regime_ok = l1_regime in {
        "trend_up", "trend_down",
        "range_high", "range_mid", "range_low",
    }
    stance_ok = l2_stance in {"bullish", "bearish"}
    grade_ok = l3_grade in {"C", "none"}
    risk_ok = l4_overall_risk in {"low", "moderate", "elevated"}
    return regime_ok and stance_ok and grade_ok and risk_ok


def _count_prior_suppressed_streak(
    previous_records: list[dict[str, Any]],
) -> int:
    """
    从 previous_records 向前数 suppressed_base_satisfied=True 的连续运行数。
    previous_records 按"越新越靠前"排序(DAO.get_recent_states 的惯例)。
    碰到 False 或缺字段就停。
    """
    count = 0
    for rec in previous_records:
        # 记录可能是 {state: {...}, run_timestamp_utc: ...}
        state = rec.get("state") if isinstance(rec.get("state"), dict) else rec
        obs = (state or {}).get("observation") or {}
        if obs.get("suppressed_base_satisfied") is True:
            count += 1
        else:
            break
    return count


def _alert_level_for(*, category: str, streak_runs: int) -> Optional[str]:
    """§4.7.5 告警级别。只有 possibly_suppressed 会出告警。"""
    if category != "possibly_suppressed":
        return None
    if streak_runs >= _CRITICAL_STREAK_RUNS:
        return "critical"
    if streak_runs >= _WARNING_STREAK_RUNS:
        return "warning"
    return None


def _get_layer(state: dict[str, Any], key: str) -> dict[str, Any]:
    if isinstance(state.get(key), dict):
        return state[key]
    er = state.get("evidence_reports") or {}
    if isinstance(er.get(key), dict):
        return er[key]
    return {}


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
