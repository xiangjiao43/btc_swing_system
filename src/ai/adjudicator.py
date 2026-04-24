"""
adjudicator.py — Sprint 1.14a:AI Adjudicator

职责:
  * 读完整 StrategyState(L1-L5 + composite + state_machine + ai summary),
    产出结构化决策建议:{action, direction, confidence, rationale, constraints,
    evidence_gaps, model_used, ...}。
  * **不**实际开仓/平仓,交由下游 Lifecycle FSM 更新状态、Sprint 2+ 的执行层落单。

设计要点:
  1. 硬约束(Execution Permission + position_cap + State Machine)在 AI 调用之前
     检查。不满足 → 直接走规则分支,不调 AI,节省成本。
  2. AI 路径只在 L3=A/B/C + permission∈{can_open, cautious_open, ambush_only,
     no_chase} + State∈{active_long_execution, active_short_execution,
     disciplined_bull_watch, disciplined_bear_watch} 时触发。
  3. AI 输出 JSON 解析失败 → 重试一次(temperature=0.0)→ 仍失败回退 action=watch,
     status='degraded_structured'。
  4. AI 返回 action 违反硬约束 → 覆盖为约束允许的最接近值,
     notes 追加 'ai_action_overridden_by_constraints'。

所有失败都返回 dict,不抛异常。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


_DEFAULT_MODEL: str = "claude-sonnet-4-5-20250929"
_DEFAULT_TIMEOUT_SEC: float = 45.0
_MAX_TOKENS: int = 600
_TEMPERATURE: float = 0.2
_RETRY_TEMPERATURE: float = 0.0


_ALL_ACTIONS: tuple[str, ...] = (
    "open_long", "open_short",
    "scale_in_long", "scale_in_short",
    "reduce_long", "reduce_short",
    "close_long", "close_short",
    "hold", "watch", "pause",
)

_OPEN_SCALE_ACTIONS = {"open_long", "open_short", "scale_in_long", "scale_in_short"}
_LONG_DIRECTION_ACTIONS = {"open_long", "scale_in_long", "reduce_long", "close_long"}
_SHORT_DIRECTION_ACTIONS = {"open_short", "scale_in_short", "reduce_short", "close_short"}
_REDUCE_CLOSE_ACTIONS = {"reduce_long", "reduce_short", "close_long", "close_short"}


_SYSTEM_PROMPT: str = """你是专业加密资产策略裁决者,只基于证据链做判断,不编造数据。
必须输出严格 JSON 格式。confidence 要如实反映不确定性。rationale 用中文 2-3 句话。
禁止给出具体价格目标。禁止使用"建议""推荐"这类强力度词汇。"""


# ============================================================
# AIAdjudicator
# ============================================================

class AIAdjudicator:
    """主裁决:读 StrategyState → 输出结构化 action。"""

    def __init__(
        self,
        openai_client: Any = None,
        *,
        rules_version: str = "v1.2.0",
        model: Optional[str] = None,
    ) -> None:
        self._openai_client = openai_client
        self.rules_version = rules_version
        self._model_override = model

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def decide(self, strategy_state: dict[str, Any]) -> dict[str, Any]:
        """
        入口。根据 state 决定 action。绝不抛异常。
        """
        # 1. 抽字段(cold_start 判定统一走 src.utils.cold_start)
        facts = _extract_facts(strategy_state)
        constraints = _build_constraints(facts)

        # 2. 硬约束前置
        forced = self._check_hard_constraints(facts)
        if forced is not None:
            return _build_rule_output(
                action=forced["action"],
                direction=_infer_direction(forced["action"]),
                confidence=forced.get("confidence", 0.5),
                rationale=forced["rationale"],
                constraints=constraints,
                evidence_gaps=_collect_evidence_gaps(facts),
                model_name=self._effective_model(),
                status="success",
                notes=forced.get("notes"),
            )

        # 3. 是否进入 AI 路径
        if not _should_call_ai(facts):
            return _build_rule_output(
                action="watch",
                direction=None,
                confidence=0.5,
                rationale="规则路径:当前证据未达 AI 调用门槛,保持观察。",
                constraints=constraints,
                evidence_gaps=_collect_evidence_gaps(facts),
                model_name=self._effective_model(),
                status="success",
            )

        # 4. AI 路径
        return self._call_ai_decide(facts, constraints, strategy_state)

    # ------------------------------------------------------------------
    # Hard constraints
    # ------------------------------------------------------------------

    def _check_hard_constraints(
        self,
        facts: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """
        返回 None = 未触发硬约束;否则返回 {action, rationale, ...}。

        建模 §6.5 硬约束对齐 Sprint 1.5a 的 14 档状态机。

        优先级(顺序命中第一个):
          1. L5 extreme_event_detected 或 state=PROTECTION → pause
          2. cold_start 期 → watch
          3. fallback_level ∈ {level_2, level_3} → watch
          4. state=POST_PROTECTION_REASSESS → hold(不允许新开)
          5. L3.execution_permission = watch → watch
          6. L3.execution_permission = protective → reduce_*/close_*/hold
          7. L3.execution_permission = hold_only → hold
          8. L4.position_cap = 0 → watch
        """
        sm_state = facts.get("state_machine_current")
        l5_extreme = facts.get("l5_extreme_event_detected")
        fallback_level = facts.get("fallback_level")
        cold_start = facts.get("cold_start_warming_up")

        # ---- 1. 极端事件 / PROTECTION:强制 pause ----
        if l5_extreme is True:
            return {
                "action": "pause",
                "rationale": "硬约束:L5 extreme_event_detected=true,强制暂停。",
                "confidence": 0.9,
            }
        if sm_state == "PROTECTION":
            return {
                "action": "pause",
                "rationale": "硬约束:状态机=PROTECTION,暂停所有新开仓。",
                "confidence": 0.9,
            }

        # ---- 2. 冷启动:强制 watch ----
        if cold_start is True:
            return {
                "action": "watch",
                "rationale": "硬约束:冷启动未完成,暂不参与开仓。",
                "confidence": 0.7,
            }

        # ---- 3. Fallback 降级:强制 watch ----
        if _is_fallback_level_degraded(fallback_level):
            return {
                "action": "watch",
                "rationale": (
                    f"硬约束:fallback_level={fallback_level},"
                    "数据降级中保守观察。"
                ),
                "confidence": 0.6,
            }

        # ---- 4. POST_PROTECTION_REASSESS:不允许新开 ----
        if sm_state == "POST_PROTECTION_REASSESS":
            return {
                "action": "hold",
                "rationale": (
                    "硬约束:POST_PROTECTION_REASSESS 期间不允许新开仓,"
                    "仅允许 hold / reduce_* / close_*。"
                ),
                "confidence": 0.7,
            }

        perm = facts.get("l3_permission")
        if perm == "watch":
            return {
                "action": "watch",
                "rationale": "硬约束:L3 execution_permission=watch,不允许新开仓。",
                "confidence": 0.6,
            }
        if perm == "protective":
            # 有多仓优先 reduce_long;有空仓优先 reduce_short;都没有 → hold
            has_long = facts.get("account_has_long")
            has_short = facts.get("account_has_short")
            if has_long:
                return {
                    "action": "reduce_long",
                    "rationale": "硬约束:L3=protective + 持有多仓,执行减仓。",
                    "confidence": 0.7,
                }
            if has_short:
                return {
                    "action": "reduce_short",
                    "rationale": "硬约束:L3=protective + 持有空仓,执行减仓。",
                    "confidence": 0.7,
                }
            return {
                "action": "hold",
                "rationale": "硬约束:L3=protective 但无持仓,保持。",
                "confidence": 0.6,
            }
        if perm == "hold_only":
            return {
                "action": "hold",
                "rationale": "硬约束:L3 execution_permission=hold_only,仅持有不新开。",
                "confidence": 0.6,
            }

        cap = facts.get("l4_position_cap")
        if cap is not None and float(cap) <= 0.0:
            return {
                "action": "watch",
                "rationale": "硬约束:L4 position_cap=0,不允许开仓。",
                "confidence": 0.7,
            }

        return None

    # ------------------------------------------------------------------
    # AI call
    # ------------------------------------------------------------------

    def _call_ai_decide(
        self,
        facts: dict[str, Any],
        constraints: dict[str, Any],
        strategy_state: dict[str, Any],
    ) -> dict[str, Any]:
        client = self._get_client()
        if client is None:
            return _build_rule_output(
                action="watch",
                direction=None,
                confidence=0.4,
                rationale="AI 客户端不可用,降级为规则判定:观察。",
                constraints=constraints,
                evidence_gaps=_collect_evidence_gaps(facts) + ["ai_client_unavailable"],
                model_name=self._effective_model(),
                status="degraded_error",
                notes=["ai_client_unavailable"],
            )

        allowed_actions = _allowed_actions_for_facts(facts)
        user_prompt = _build_user_prompt(facts, allowed_actions)
        model = self._effective_model()

        total_tokens_in = 0
        total_tokens_out = 0
        total_latency_ms = 0
        last_error: Optional[str] = None

        for attempt, temperature in enumerate(
            (_TEMPERATURE, _RETRY_TEMPERATURE), start=1,
        ):
            start_ts = time.time()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=_MAX_TOKENS,
                    temperature=temperature,
                )
            except Exception as e:  # 网络 / SDK 异常
                last_error = str(e)[:200]
                logger.warning(
                    "adjudicator AI call attempt %d failed: %s", attempt, e,
                )
                total_latency_ms += int((time.time() - start_ts) * 1000)
                continue

            latency_ms = int((time.time() - start_ts) * 1000)
            total_latency_ms += latency_ms
            total_tokens_in += _usage(resp, "prompt_tokens")
            total_tokens_out += _usage(resp, "completion_tokens")
            raw_text = _extract_text(resp)
            parsed = _parse_json_loose(raw_text)
            if parsed is None:
                last_error = "json_parse_failed"
                logger.warning(
                    "adjudicator AI attempt %d JSON parse failed: %r",
                    attempt, raw_text[:160] if raw_text else None,
                )
                continue

            # 成功解析,进入约束校验
            return self._validate_and_enforce_constraints(
                ai_output=parsed,
                facts=facts,
                constraints=constraints,
                model_used=getattr(resp, "model", model),
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                latency_ms=total_latency_ms,
            )

        # 两次都失败
        return _build_rule_output(
            action="watch",
            direction=None,
            confidence=0.4,
            rationale="AI 输出 JSON 解析失败,降级为规则判定。",
            constraints=constraints,
            evidence_gaps=_collect_evidence_gaps(facts),
            model_name=model,
            status="degraded_structured",
            notes=["ai_parse_failed", last_error or "unknown"],
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            latency_ms=total_latency_ms,
        )

    # ------------------------------------------------------------------
    # Constraint enforcement
    # ------------------------------------------------------------------

    def _validate_and_enforce_constraints(
        self,
        *,
        ai_output: dict[str, Any],
        facts: dict[str, Any],
        constraints: dict[str, Any],
        model_used: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
    ) -> dict[str, Any]:
        """
        AI 返回的 action 违反硬约束 → override。
        """
        ai_action = (ai_output.get("action") or "").strip().lower()
        allowed = set(_allowed_actions_for_facts(facts))
        notes: list[str] = []

        if ai_action not in _ALL_ACTIONS or ai_action not in allowed:
            overridden = _fallback_closest(ai_action, allowed)
            notes.append("ai_action_overridden_by_constraints")
            action = overridden
        else:
            action = ai_action

        # 方向
        direction = ai_output.get("direction")
        if direction not in {"long", "short", None}:
            direction = None
        inferred = _infer_direction(action)
        if inferred is not None and direction != inferred:
            direction = inferred

        # confidence
        try:
            confidence = float(ai_output.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        rationale = str(ai_output.get("rationale") or "")[:600]
        if notes and "ai_action_overridden_by_constraints" in notes:
            rationale = (
                f"(原始 AI 建议 {ai_action or '?'} 被约束覆盖为 {action}){rationale}"
            )

        ai_gaps = ai_output.get("evidence_gaps") or []
        if not isinstance(ai_gaps, list):
            ai_gaps = []
        merged_gaps = list(dict.fromkeys(
            _collect_evidence_gaps(facts) + [str(x) for x in ai_gaps][:8]
        ))

        return {
            "action": action,
            "direction": direction,
            "confidence": confidence,
            "rationale": rationale,
            "constraints": constraints,
            "evidence_gaps": merged_gaps,
            "model_used": model_used,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            "status": "success",
            "notes": notes,
            "rules_version": self.rules_version,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _effective_model(self) -> str:
        return (
            self._model_override
            or os.getenv("OPENAI_MODEL")
            or _DEFAULT_MODEL
        )

    def _get_client(self) -> Any:
        if self._openai_client is not None:
            return self._openai_client
        if OpenAI is None:
            return None
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        base_url = os.getenv("OPENAI_API_BASE")
        try:
            return OpenAI(
                base_url=base_url, api_key=api_key, timeout=_DEFAULT_TIMEOUT_SEC,
            )
        except Exception as e:  # pragma: no cover
            logger.warning("build OpenAI client failed: %s", e)
            return None


# ============================================================
# Fact extraction
# ============================================================

def _get_layer(state: dict[str, Any], name: str) -> dict[str, Any]:
    if isinstance(state.get(name), dict):
        return state[name]
    er = state.get("evidence_reports") or {}
    if isinstance(er.get(name), dict):
        return er[name]
    return {}


def _extract_facts(strategy_state: dict[str, Any]) -> dict[str, Any]:
    """把 state 中 adjudicator 需要的字段拍平成一个 dict。"""
    l1 = _get_layer(strategy_state, "layer_1")
    l2 = _get_layer(strategy_state, "layer_2")
    l3 = _get_layer(strategy_state, "layer_3")
    l4 = _get_layer(strategy_state, "layer_4")
    l5 = _get_layer(strategy_state, "layer_5")

    from ..utils.cold_start import is_cold_start

    sm = strategy_state.get("state_machine") or {}
    account = strategy_state.get("account_state") or {}
    lifecycle = strategy_state.get("lifecycle") or {}
    pipeline_meta = strategy_state.get("pipeline_meta") or {}

    return {
        "l1_regime": l1.get("regime") or l1.get("regime_primary"),
        "l1_regime_stability": l1.get("regime_stability"),
        "l1_volatility": l1.get("volatility_regime") or l1.get("volatility_level"),
        "l2_stance": l2.get("stance"),
        "l2_stance_confidence": l2.get("stance_confidence"),
        "l2_phase": l2.get("phase"),
        "l3_grade": l3.get("opportunity_grade") or l3.get("grade"),
        "l3_permission": l3.get("execution_permission"),
        "l3_anti_pattern_flags": l3.get("anti_pattern_flags") or [],
        "l4_position_cap": l4.get("position_cap"),
        "l4_stop_loss_reference": l4.get("stop_loss_reference"),
        "l4_risk_reward_ratio": l4.get("risk_reward_ratio"),
        "l4_overall_risk": (
            l4.get("overall_risk_level") or l4.get("overall_risk")
        ),
        "l4_hard_invalidation_levels": l4.get("hard_invalidation_levels") or [],
        "l5_env": l5.get("macro_environment"),
        "l5_macro_stance": l5.get("macro_stance") or l5.get("macro_environment"),
        "l5_headwind": l5.get("macro_headwind_vs_btc"),
        "l5_data_completeness": l5.get("data_completeness_pct"),
        "l5_health": l5.get("health_status"),
        "l5_extreme_event_detected": bool(l5.get("extreme_event_detected", False)),
        "state_machine_current": sm.get("current_state"),
        "state_machine_previous": sm.get("previous_state"),
        "cold_start_warming_up": is_cold_start(strategy_state),
        "account_has_long": bool((account.get("long_position_size") or 0) > 0),
        "account_has_short": bool((account.get("short_position_size") or 0) > 0),
        "lifecycle_current": lifecycle.get("current_lifecycle"),
        "context_summary_status": (
            (strategy_state.get("context_summary") or {}).get("status")
        ),
        "fallback_level": pipeline_meta.get("fallback_level"),
    }


def _is_fallback_level_degraded(level: Any) -> bool:
    """fallback_level ∈ {level_2, level_3, 2, 3} 都视作"数据降级"。"""
    if level is None:
        return False
    if isinstance(level, str):
        return level.lower() in {"level_2", "level_3", "l2", "l3"}
    try:
        return int(level) >= 2
    except (TypeError, ValueError):
        return False


def _collect_evidence_gaps(facts: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not facts.get("l1_regime"):
        gaps.append("l1_regime_missing")
    if not facts.get("l2_stance"):
        gaps.append("l2_stance_missing")
    if not facts.get("l3_grade"):
        gaps.append("l3_grade_missing")
    if facts.get("l4_position_cap") is None:
        gaps.append("l4_position_cap_missing")
    l5_completeness = facts.get("l5_data_completeness")
    l5_health = facts.get("l5_health")
    if (l5_completeness is not None and l5_completeness < 50.0) or (
        l5_health in {"error", "degraded"}
    ):
        gaps.append("macro_data_incomplete")
    return gaps


def _build_constraints(facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_position_size": facts.get("l4_position_cap"),
        "stop_loss_reference": facts.get("l4_stop_loss_reference"),
        "event_risk_warning": None,
        "execution_permission_binding": facts.get("l3_permission"),
    }


# ============================================================
# Allowed action computation
# ============================================================

def _allowed_actions_for_facts(facts: dict[str, Any]) -> list[str]:
    """
    根据 hard-constraint 规则推演当前允许的 action 集合(对齐建模 §5.1 14 档)。
    用于 AI 路径时把允许集合注入 prompt,也用于 AI 输出校验。
    """
    sm = facts.get("state_machine_current")
    perm = facts.get("l3_permission")
    cap = facts.get("l4_position_cap")

    # ---- 硬路径 ----
    if facts.get("l5_extreme_event_detected") or sm == "PROTECTION":
        return ["pause"]
    if facts.get("cold_start_warming_up"):
        return ["watch"]
    if _is_fallback_level_degraded(facts.get("fallback_level")):
        return ["watch", "pause"]
    if sm == "POST_PROTECTION_REASSESS":
        # §5.2:允许 HOLD / EXIT / FLAT / FLIP_WATCH,禁止 PLANNED
        base = ["hold", "watch"]
        if facts.get("account_has_long"):
            base.extend(["reduce_long", "close_long"])
        if facts.get("account_has_short"):
            base.extend(["reduce_short", "close_short"])
        return base
    if perm == "watch":
        return ["watch", "pause"]
    if perm == "hold_only":
        base = ["hold", "watch"]
        if facts.get("account_has_long"):
            base.extend(["reduce_long", "close_long"])
        if facts.get("account_has_short"):
            base.extend(["reduce_short", "close_short"])
        return base
    if perm == "protective":
        return ["reduce_long", "reduce_short", "close_long", "close_short", "hold"]
    if cap is not None and float(cap) <= 0.0:
        return ["watch", "hold"]

    # ---- State Machine 主导(14 档新名)----
    stance = facts.get("l2_stance")
    grade = facts.get("l3_grade")

    if sm == "FLAT":
        # 在 FLAT,裁决官主要是决定是否进入 PLANNED;但 action 层面
        # open_* 视为"建议开仓触发进入 PLANNED",和 watch/hold 一起暴露
        if stance == "bullish" and grade in {"A", "B"} and perm in {
            "can_open", "cautious_open", "ambush_only",
        }:
            base = ["open_long", "hold", "watch"]
        elif stance == "bearish" and grade in {"A", "B"} and perm in {
            "can_open", "cautious_open", "ambush_only",
        }:
            base = ["open_short", "hold", "watch"]
        else:
            base = ["watch", "hold"]
    elif sm in {"LONG_PLANNED"}:
        base = ["open_long", "scale_in_long", "hold", "watch", "close_long"]
    elif sm in {"SHORT_PLANNED"}:
        base = ["open_short", "scale_in_short", "hold", "watch", "close_short"]
    elif sm == "LONG_OPEN":
        base = ["hold", "watch", "scale_in_long", "reduce_long", "close_long"]
    elif sm == "SHORT_OPEN":
        base = ["hold", "watch", "scale_in_short", "reduce_short", "close_short"]
    elif sm == "LONG_HOLD":
        base = ["hold", "reduce_long", "close_long", "watch"]
    elif sm == "SHORT_HOLD":
        base = ["hold", "reduce_short", "close_short", "watch"]
    elif sm == "LONG_TRIM":
        base = ["reduce_long", "close_long", "hold", "watch"]
    elif sm == "SHORT_TRIM":
        base = ["reduce_short", "close_short", "hold", "watch"]
    elif sm in {"LONG_EXIT", "SHORT_EXIT"}:
        base = ["close_long", "close_short", "hold", "watch"]
    elif sm == "FLIP_WATCH":
        # 冷却期不能单独决定方向切换;允许 hold / watch,持仓已平应为 0
        base = ["hold", "watch"]
    else:
        base = ["hold", "watch"]

    # 有持仓时加上 reduce/close(防御性)
    if facts.get("account_has_long"):
        for a in ("reduce_long", "close_long"):
            if a not in base:
                base.append(a)
    if facts.get("account_has_short"):
        for a in ("reduce_short", "close_short"):
            if a not in base:
                base.append(a)

    return base


def _should_call_ai(facts: dict[str, Any]) -> bool:
    """
    AI 路径的触发条件(对齐建模 §5.1 14 档 + §6.5)。所有同时满足:
      * L3.grade ∈ {A, B, C}
      * L3.execution_permission ∈ {can_open, cautious_open, ambush_only, no_chase}
      * State Machine ∈ {FLAT, LONG_PLANNED, LONG_OPEN, LONG_HOLD, LONG_TRIM,
                         SHORT_PLANNED, SHORT_OPEN, SHORT_HOLD, SHORT_TRIM,
                         FLIP_WATCH}
      * 非硬约束命中(PROTECTION / POST_PROTECTION_REASSESS / cold_start /
        fallback_degraded / extreme_event 均由硬约束前置拦截)
    """
    grade = facts.get("l3_grade")
    perm = facts.get("l3_permission")
    sm = facts.get("state_machine_current")
    return (
        grade in {"A", "B", "C"}
        and perm in {"can_open", "cautious_open", "ambush_only", "no_chase"}
        and sm in {
            "FLAT",
            "LONG_PLANNED", "LONG_OPEN", "LONG_HOLD", "LONG_TRIM",
            "SHORT_PLANNED", "SHORT_OPEN", "SHORT_HOLD", "SHORT_TRIM",
            "FLIP_WATCH",
        }
    )


# ============================================================
# Prompt / response helpers
# ============================================================

def _build_user_prompt(
    facts: dict[str, Any],
    allowed_actions: list[str],
) -> str:
    lines = [
        "=== 证据链关键字段 ===",
        f"L1 Regime: regime={facts.get('l1_regime')}, vol={facts.get('l1_volatility')}",
        (
            f"L2 Direction: stance={facts.get('l2_stance')}, "
            f"confidence={facts.get('l2_stance_confidence')}, "
            f"phase={facts.get('l2_phase')}"
        ),
        (
            f"L3 Opportunity: grade={facts.get('l3_grade')}, "
            f"permission={facts.get('l3_permission')}, "
            f"anti_patterns={facts.get('l3_anti_pattern_flags') or []}"
        ),
        (
            f"L4 Risk: position_cap={facts.get('l4_position_cap')}, "
            f"overall_risk={facts.get('l4_overall_risk')}, "
            f"rr={facts.get('l4_risk_reward_ratio')}"
        ),
        (
            f"L5 Macro: env={facts.get('l5_env')}, "
            f"headwind={facts.get('l5_headwind')}, "
            f"data_completeness={facts.get('l5_data_completeness')}%, "
            f"health={facts.get('l5_health')}"
        ),
        f"State Machine: {facts.get('state_machine_current')}",
        f"Lifecycle: {facts.get('lifecycle_current')}",
        "",
        "=== 允许的 action(chosen_action_state 必须在此集合内)===",
        json.dumps(allowed_actions, ensure_ascii=False),
        "",
        "=== 输出 JSON 格式(严格)===",
        "{",
        '  "action": "<上面允许集合中的一个>",',
        '  "direction": "long|short|null",',
        '  "confidence": 0.0-1.0,',
        '  "rationale": "中文 1-2 段描述",',
        '  "evidence_gaps": ["缺失或低质量的证据点"]',
        "}",
        "只输出 JSON,无其他文本。",
    ]
    return "\n".join(lines)


def _parse_json_loose(text: Optional[str]) -> Optional[dict[str, Any]]:
    """尝试从 AI 响应里提取 JSON。"""
    if not text:
        return None
    t = text.strip()
    # 去掉 ``` 代码块包裹
    if t.startswith("```"):
        # 去第一行 ```xxx 和结尾 ```
        lines = t.splitlines()
        if len(lines) >= 2:
            t = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        obj = json.loads(t)
    except (json.JSONDecodeError, ValueError):
        # 退而求其次:找最外层 { ... }
        first = t.find("{")
        last = t.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None
        try:
            obj = json.loads(t[first : last + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return obj if isinstance(obj, dict) else None


def _extract_text(resp: Any) -> Optional[str]:
    try:
        return str(resp.choices[0].message.content)
    except (AttributeError, IndexError):
        return None


def _usage(resp: Any, key: str) -> int:
    try:
        return int(getattr(resp.usage, key, 0))
    except Exception:
        return 0


# ============================================================
# Rule-path output
# ============================================================

def _build_rule_output(
    *,
    action: str,
    direction: Optional[str],
    confidence: float,
    rationale: str,
    constraints: dict[str, Any],
    evidence_gaps: list[str],
    model_name: str,
    status: str,
    notes: Optional[list[str]] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
) -> dict[str, Any]:
    return {
        "action": action,
        "direction": direction if direction is not None else _infer_direction(action),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "rationale": rationale,
        "constraints": constraints,
        "evidence_gaps": list(evidence_gaps),
        "model_used": model_name,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "latency_ms": int(latency_ms),
        "status": status,
        "notes": list(notes or []),
    }


def _infer_direction(action: Optional[str]) -> Optional[str]:
    if action in _LONG_DIRECTION_ACTIONS:
        return "long"
    if action in _SHORT_DIRECTION_ACTIONS:
        return "short"
    return None


def _fallback_closest(ai_action: str, allowed: set[str]) -> str:
    """把违规 action 映射到最接近的允许项。"""
    if not allowed:
        return "watch"
    if ai_action in _OPEN_SCALE_ACTIONS:
        if "watch" in allowed:
            return "watch"
        if "hold" in allowed:
            return "hold"
    if ai_action in _REDUCE_CLOSE_ACTIONS:
        if "hold" in allowed:
            return "hold"
    # 保守退化
    for candidate in ("watch", "hold", "pause"):
        if candidate in allowed:
            return candidate
    return sorted(allowed)[0]
