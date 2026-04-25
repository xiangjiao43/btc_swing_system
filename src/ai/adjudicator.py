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

# Sprint 1.5c C6:改用 anthropic SDK(建模 §10.1)
from .client import (
    build_anthropic_client, extract_text as _client_extract_text,
    extract_usage as _client_extract_usage,
    extract_model as _client_extract_model,
)


logger = logging.getLogger(__name__)


_DEFAULT_MODEL: str = "claude-sonnet-4-5-20250929"
_DEFAULT_TIMEOUT_SEC: float = 45.0
# Sprint 2.5-B:从 600 → 2000,容纳 6 组合因子双段分析(每段 50-70 字中文)
_MAX_TOKENS: int = 2000
_TEMPERATURE: float = 0.2
_RETRY_TEMPERATURE: float = 0.0


# Sprint 2.5-B:6 个组合因子的固定 key(顺序 = 前端 compositeCards() 排序)
_COMPOSITE_KEYS: tuple[str, ...] = (
    "cycle_position", "truth_trend", "band_position",
    "crowding", "macro_headwind", "event_risk",
)
_COMPOSITE_FALLBACK_TEXT: str = "基础数据暂未就绪,无法生成态势分析"


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


_SYSTEM_PROMPT: str = """你是 BTC 中长线低频双向波段交易系统的"裁决官"(严格对齐建模 §6.5)。
读程序给的五层证据,在合法 action 集合里决策,输出严格 JSON。

====== 机会评级与交易计划(Sprint 2.2 关键升级)======

L3.opportunity_grade 已经由规则层判档(A/B/C/none),你**必须原样引用不可修改**。

当 grade ∈ {A, B, C} 时,你必须同时产出完整的 trade_plan,仅信心档位不同:

  grade=A  → trade_plan.confidence_tier = "high"
            position_cap 可用到 constraints.max_position_cap_pct 的 100%
            narrative 明确点出 "A 级机会,高信心建仓"

  grade=B  → trade_plan.confidence_tier = "medium"
            position_cap 建议 ≤ constraints.max_position_cap_pct × 0.7
            narrative 明确点出 "B 级机会,中等信心,分批入场"

  grade=C  → trade_plan.confidence_tier = "low"
            position_cap 建议 ≤ constraints.max_position_cap_pct × 0.4
            入场区间更保守(深回撤才进)
            narrative 明确点出 "C 级机会,低信心参考,不建议重仓"
            what_would_change_mind 至少 1 条是"什么条件会把 C 升到 B"

  grade=none → trade_plan = null
              narrative 解释为什么不给策略(例如证据不足/时机不对/冷启动期)

====== 十条纪律 ======

1. action 必须在 allowed_transitions 列表里。
2. primary_drivers 的 evidence_ref 必须在 evidence_cards 里真实存在。
3. trade_plan 总仓位 ≤ constraints.max_position_cap_pct。
4. 做多 stop_loss < 入场下沿,做空反之;stop_loss 必须选自 constraints.hard_invalidation_levels。
5. 持仓中必须对 thesis_still_valid 明确评估(无持仓时可为 null)。
6. what_would_change_mind 至少 3 条,必须可客观判断(不要"市场变化"这类模糊词)。
7. 证据冲突或不足时保守(保持当前或 FLAT),不得强行给高置信度。
8. 输出严格 JSON,首字符 `{`,尾字符 `}`。不要 markdown code block,不要说明文字。
9. 前面各层已经收紧过 permission 和 position_cap,你不要在此基础上再独立降档(会双重收紧)。
   过度保守和过度激进同样不可接受,严格按证据走。
10. observation_category 和 opportunity_grade 是只读上下文,不是你自我调节的依据。
    A/B/C/none 严格按 L3 判档,信心档也严格按 A=high / B=medium / C=low。

====== 输出 JSON 形态(严格)======

{
  "action": "<allowed_transitions 中的一个>",
  "direction": "long" | "short" | null,
  "confidence": 0.0-1.0,
  "rationale": "中文 2-3 句话",
  "narrative": "中文 3-5 句,主叙事",
  "one_line_summary": "中文一句话结论",
  "opportunity_grade": "<必须等于 L3 输出>",
  "trade_plan": null 或 {
    "direction": "long" | "short",
    "confidence_tier": "high" | "medium" | "low",
    "max_position_size_pct": <数值>,
    "entry_zones": [{"price_low": <数值>, "price_high": <数值>, "allocation_pct": <数值>}, ...],
    "stop_loss": <数值,必须在 hard_invalidation_levels 价位中>,
    "take_profit_plan": [{"price": <数值>, "size_pct": <数值>}, ...],
    "dynamic_notes": "中文"
  },
  "primary_drivers": [{"evidence_ref": "<card_id>", "text": "<中文>"}, ...],
  "counter_arguments": [{"text": "<中文>"}, ...],
  "what_would_change_mind": ["<客观条件 1>", "<客观条件 2>", "<客观条件 3>", ...],
  "confidence_breakdown": {
    "overall": 0.0-1.0,
    "evidence_agreement": 0.0-1.0,
    "historical_precedent": 0.0-1.0,
    "data_quality": 0.0-1.0,
    "trade_plan_confidence_tier": "high" | "medium" | "low" | "none"
  },
  "transition_reason": "<中文,说明状态迁移原因>",
  "evidence_gaps": ["<缺失或低质量证据点>", ...],
  "composite_factors": [<见下方 Sprint 2.5-B 段>]
}

====== 组合因子双段分析(Sprint 2.5-B 新增 — 必须输出)======

除主决策外,你必须在输出 JSON 顶层加一个 composite_factors 数组,
为以下 6 个组合因子各产出两段中文短文(每段 50-70 字):

  cycle_position   长周期位置(MVRV-Z / NUPL / LTH supply / 距 ATH)
  truth_trend      趋势真实性(ADX / 多周期一致 / MA 排列 / MA-200 关系)
  band_position    波段位置(swing extension / 结构 / MA-60 距离 / 回撤深度)
  crowding         拥挤度(funding / OI / 多空比 / basis / Put/Call)
  macro_headwind   宏观逆风(DXY / US10Y / VIX / NASDAQ / 相关性)
  event_risk       事件风险(FOMC / CPI / NFP / 期权到期窗口)

每个数组元素严格按下面形态:
{
  "key":              "<上面 6 个 key 之一,英文小写下划线>",
  "current_analysis": "<50-70 字中文,基于实时因子值的态势解读>",
  "strategy_impact":  "<50-70 字中文,对当前 stance/regime/phase 的具体作用>"
}

5 条硬约束(违反就是错的输出):
1. ❌ 禁止预测具体价格(不要写"预计涨到 X"或"跌破 Y 即转空")
2. ❌ 禁止情绪化措辞(不写"恐慌""强烈看多""暴涨""崩盘""血洗")
3. ✅ current_analysis 必须出现至少 1 个原始因子的具体数值(如 MVRV-Z=2.1,ADX=18,
   funding=0.012%,DXY=104.3 等)
4. ✅ strategy_impact 必须引用建模规则编号,从 {L1.regime, L2.动态门槛表, L2.stance,
   L3.opportunity_grade, L3.execution_permission, L4.position_cap,
   L4.risk_multiplier, L4.crowding_multiplier, L4.event_risk_multiplier,
   L5.macro_headwind_multiplier} 中选一到两个
5. ✅ strategy_impact 必须落到当前 stance / regime / phase 的具体取值(避免"将影响策略"
   这类空话)

数据缺失处理:
  - 某组合因子的所有原始数据都为 null → 该 key 可以省略,程序会填
    "基础数据暂未就绪,无法生成态势分析"
  - 部分缺失 → 在文本中只用有值的写,不要提"缺失""未拿到"等字样
  - 6 个 key 全部输出最理想;最少必须输出当前可用数据 ≥ 50% 的那几个"""


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
                # Sprint 1.5c C6:anthropic messages.create 是唯一路径
                resp = client.messages.create(
                    model=model,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
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
                model_used=_client_extract_model(resp, model),
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

        # Sprint 2.2:把 trade_plan 和相关 §6.3 字段透传到输出
        trade_plan = _validate_trade_plan(
            ai_output.get("trade_plan"), facts, notes,
        )
        l3_grade = facts.get("l3_grade") or "none"
        # 程序校验规则 §6.4 #8:opportunity_grade 必须等于 L3
        ai_grade = ai_output.get("opportunity_grade")
        if ai_grade and ai_grade != l3_grade:
            notes.append("ai_grade_overridden_to_l3")
        final_grade = l3_grade

        # Grade 与 trade_plan 自洽检查(Sprint 2.2 硬约束)
        if final_grade in {"A", "B", "C"} and trade_plan is None:
            notes.append("trade_plan_missing_for_actionable_grade")
        if final_grade == "none" and trade_plan is not None:
            trade_plan = None
            notes.append("trade_plan_dropped_for_none_grade")

        confidence_breakdown = ai_output.get("confidence_breakdown") or {}
        if not isinstance(confidence_breakdown, dict):
            confidence_breakdown = {}
        # 无论 AI 报什么,我们按 grade 钉死 trade_plan_confidence_tier
        confidence_breakdown["trade_plan_confidence_tier"] = _tier_for_grade(final_grade)

        what_would_change = ai_output.get("what_would_change_mind") or []
        if not isinstance(what_would_change, list):
            what_would_change = []

        primary_drivers = ai_output.get("primary_drivers") or []
        if not isinstance(primary_drivers, list):
            primary_drivers = []

        counter_arguments = ai_output.get("counter_arguments") or []
        if not isinstance(counter_arguments, list):
            counter_arguments = []

        # Sprint 2.5-B:验证 + 补齐 composite_factors 双段分析
        composite_factors_out = _validate_composite_factors(
            ai_output.get("composite_factors"),
            facts.get("composite_factors_raw") or {},
            notes,
        )

        return {
            "action": action,
            "direction": direction,
            "confidence": confidence,
            "rationale": rationale,
            "narrative": str(ai_output.get("narrative") or rationale)[:1200],
            "one_line_summary": str(ai_output.get("one_line_summary") or "")[:200],
            "opportunity_grade": final_grade,
            "trade_plan": trade_plan,
            "primary_drivers": primary_drivers[:6],
            "counter_arguments": counter_arguments[:6],
            "what_would_change_mind": [str(w) for w in what_would_change][:6],
            "confidence_breakdown": confidence_breakdown,
            "transition_reason": str(ai_output.get("transition_reason") or "")[:400],
            "constraints": constraints,
            "evidence_gaps": merged_gaps,
            "composite_factors": composite_factors_out,
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
        """Sprint 1.5c C6:统一走 anthropic SDK;测试注入的 mock 依然支持。"""
        if self._openai_client is not None:
            return self._openai_client
        return build_anthropic_client(timeout=_DEFAULT_TIMEOUT_SEC)


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
    observation = strategy_state.get("observation") or {}
    # Sprint 2.2:evidence_cards / factor_cards 的 id 列表,
    # 给 AI 做 primary_drivers.evidence_ref 白名单
    factor_cards = strategy_state.get("factor_cards") or strategy_state.get("evidence_cards") or []
    available_card_ids = [
        c.get("card_id") for c in factor_cards if isinstance(c, dict) and c.get("card_id")
    ]
    # Sprint 2.5-B:6 组合因子快照,用于让 AI 写 current_analysis / strategy_impact
    composite_snapshot = _build_composite_snapshot(strategy_state)

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
        "observation_category": observation.get("observation_category"),
        "available_card_ids": available_card_ids,
        "composite_snapshot": composite_snapshot,
        "composite_factors_raw": strategy_state.get("composite_factors") or {},
    }


def _build_composite_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """精简版 composite_factors 快照,只保留 AI 写双段分析所需字段。"""
    composite = state.get("composite_factors") or {}
    if not isinstance(composite, dict):
        return {}
    out: dict[str, Any] = {}
    for key in _COMPOSITE_KEYS:
        c = composite.get(key)
        if not isinstance(c, dict):
            continue
        comp = c.get("composition")
        comp_short = []
        if isinstance(comp, list):
            for item in comp[:6]:
                if isinstance(item, dict):
                    comp_short.append({
                        "name": item.get("name"),
                        "value": item.get("value"),
                    })
        out[key] = {
            "score": c.get("score"),
            "band": c.get("band"),
            "value_interpretation": c.get("value_interpretation"),
            "affects_layer": c.get("affects_layer"),
            "composition": comp_short,
        }
    return out


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
        # Sprint 2.2:A/B/C 都应出现 open_*(空头建模只允许 A/B/none,无 C);
        # 前面各层已经收紧 permission 和 position_cap,此处不再二次限档。
        if stance == "bullish" and grade in {"A", "B", "C"} and perm in {
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
    l4_cap = facts.get("l4_position_cap") or 0.0
    max_cap_pct = round(float(l4_cap) * 100, 2) if l4_cap else 0.0
    hard_invalidation = facts.get("l4_hard_invalidation_levels") or []
    evidence_cards = facts.get("available_card_ids") or []
    composite_snapshot = facts.get("composite_snapshot") or {}

    lines = [
        "=== 证据链关键字段 ===",
        f"L1 Regime: regime={facts.get('l1_regime')}, vol={facts.get('l1_volatility')}, "
        f"stability={facts.get('l1_regime_stability')}",
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
            f"L5 Macro: stance={facts.get('l5_macro_stance')}, "
            f"headwind={facts.get('l5_headwind')}, "
            f"data_completeness={facts.get('l5_data_completeness')}%, "
            f"extreme_event={facts.get('l5_extreme_event_detected')}"
        ),
        f"State Machine: {facts.get('state_machine_current')}",
        f"Lifecycle: {facts.get('lifecycle_current')}",
        f"Observation: {facts.get('observation_category')}",
        "",
        "=== 系统约束(必须遵守)===",
        f"max_position_cap_pct: {max_cap_pct}",
        "hard_invalidation_levels(stop_loss 必须从这里选):",
        json.dumps(hard_invalidation, ensure_ascii=False),
        "",
        "=== 可引用的 evidence_card_id(primary_drivers.evidence_ref 必须在此列表)===",
        json.dumps(evidence_cards[:80], ensure_ascii=False),
        "",
        "=== 允许的 action(chosen_action_state 必须在此集合内)===",
        json.dumps(allowed_actions, ensure_ascii=False),
        "",
        "=== 6 个组合因子的当前快照(用来写 composite_factors 双段分析)===",
        json.dumps(composite_snapshot, ensure_ascii=False, indent=None)[:3000],
        "",
        "=== 输出规范 ===",
        "严格按 system prompt 描述的 JSON schema 输出。",
        "grade ∈ {A, B, C} 必须同时产出完整 trade_plan(带 confidence_tier);grade=none 则 trade_plan=null。",
        "composite_factors 数组必须输出(至少覆盖数据完整的那几个 key)。",
        "只输出 JSON,首字符 {,尾字符 }。",
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
    """同时兼容 anthropic(resp.content[0].text)和 openai(resp.choices[0].message.content)
    的响应形态,供 Sprint 1.5c 切换 SDK 后的双路径使用。"""
    # anthropic 风格优先
    try:
        content = getattr(resp, "content", None)
        if content:
            # anthropic 真实响应:content=[TextBlock(text=...)]
            if hasattr(content[0], "text"):
                return str(content[0].text)
            # mock 测试里 content[0].text 可能返回 Mock;若 resp.choices 存在再降级
    except (AttributeError, IndexError, TypeError):
        pass
    # openai 老风格(MagicMock 测试)
    try:
        return str(resp.choices[0].message.content)
    except (AttributeError, IndexError):
        return None


def _usage(resp: Any, key: str) -> int:
    """兼容 anthropic(input_tokens / output_tokens)和 openai
    (prompt_tokens / completion_tokens)。"""
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return 0
        # 优先按传入 key 精确取
        val = getattr(usage, key, None)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
        # 别名:prompt_tokens ↔ input_tokens;completion_tokens ↔ output_tokens
        if key in ("prompt_tokens", "input_tokens"):
            alt = getattr(usage, "input_tokens", None) or \
                  getattr(usage, "prompt_tokens", None)
            return int(alt or 0)
        if key in ("completion_tokens", "output_tokens"):
            alt = getattr(usage, "output_tokens", None) or \
                  getattr(usage, "completion_tokens", None)
            return int(alt or 0)
        return 0
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
        "narrative": rationale,
        "one_line_summary": rationale[:80],
        "opportunity_grade": "none",
        "trade_plan": None,
        "primary_drivers": [],
        "counter_arguments": [],
        "what_would_change_mind": [],
        "confidence_breakdown": {"trade_plan_confidence_tier": "none"},
        "transition_reason": "",
        "constraints": constraints,
        "evidence_gaps": list(evidence_gaps),
        "model_used": model_name,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "latency_ms": int(latency_ms),
        "status": status,
        "notes": list(notes or []),
        # Sprint 2.5-B:规则路径不调 AI,但前端 6 张卡仍要有占位文案
        "composite_factors": [
            {
                "key": k,
                "current_analysis": _COMPOSITE_FALLBACK_TEXT,
                "strategy_impact": _COMPOSITE_FALLBACK_TEXT,
                "missing_count": None,
                "total_count": None,
            }
            for k in _COMPOSITE_KEYS
        ],
    }


# ============================================================
# Sprint 2.5-B:composite_factors 双段分析验证
# ============================================================

def _composition_value_count(c: dict[str, Any]) -> tuple[int, int]:
    """返回 (有值项数, 总项数)。值为 None / "" 视为缺失。"""
    comp = c.get("composition")
    if not isinstance(comp, list):
        return (0, 0)
    total = len(comp)
    have = sum(
        1 for it in comp
        if isinstance(it, dict)
        and it.get("value") is not None
        and it.get("value") != ""
    )
    return (have, total)


def _validate_composite_factors(
    raw: Any,
    composite_raw: dict[str, Any],
    notes: list[str],
) -> list[dict[str, Any]]:
    """对齐 6 个 composite key 输出固定 6 个元素的数组。

    AI 给的优先,缺的 / 不完整的用 fallback。还检查软约束:
      - current_analysis 必须含至少 1 个数字
      - strategy_impact 必须含 "L1./L2./L3./L4./L5." 之一
    违反只追加 notes,不丢弃文本。
    """
    by_key: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for el in raw:
            if not isinstance(el, dict):
                continue
            k = el.get("key")
            if not isinstance(k, str) or k not in _COMPOSITE_KEYS:
                continue
            cur = str(el.get("current_analysis") or "").strip()
            imp = str(el.get("strategy_impact") or "").strip()
            by_key[k] = {
                "current_analysis": cur[:240],
                "strategy_impact": imp[:240],
            }

    out: list[dict[str, Any]] = []
    soft_warn_no_digit: list[str] = []
    soft_warn_no_layer: list[str] = []
    for k in _COMPOSITE_KEYS:
        c = composite_raw.get(k) if isinstance(composite_raw, dict) else None
        have, total = _composition_value_count(c) if isinstance(c, dict) else (0, 0)
        all_missing = (total > 0 and have == 0)

        ai_entry = by_key.get(k)
        if ai_entry and ai_entry["current_analysis"] and ai_entry["strategy_impact"] and not all_missing:
            current_analysis = ai_entry["current_analysis"]
            strategy_impact = ai_entry["strategy_impact"]
            # 软约束:数字检查
            if not any(ch.isdigit() for ch in current_analysis):
                soft_warn_no_digit.append(k)
            # 软约束:层级编号引用
            if not any(tag in strategy_impact for tag in ("L1.", "L2.", "L3.", "L4.", "L5.")):
                soft_warn_no_layer.append(k)
        else:
            current_analysis = _COMPOSITE_FALLBACK_TEXT
            strategy_impact = _COMPOSITE_FALLBACK_TEXT

        out.append({
            "key": k,
            "current_analysis": current_analysis,
            "strategy_impact": strategy_impact,
            "missing_count": (total - have) if total > 0 else None,
            "total_count": total if total > 0 else None,
        })

    if soft_warn_no_digit:
        notes.append(f"composite_no_digit:{','.join(soft_warn_no_digit)}")
    if soft_warn_no_layer:
        notes.append(f"composite_no_layer_ref:{','.join(soft_warn_no_layer)}")
    return out


_GRADE_TO_TIER: dict[str, str] = {
    "A": "high",
    "B": "medium",
    "C": "low",
    "none": "none",
}

_GRADE_CAP_MULTIPLIER: dict[str, float] = {
    "A": 1.0,
    "B": 0.7,
    "C": 0.4,
}


def _tier_for_grade(grade: Optional[str]) -> str:
    return _GRADE_TO_TIER.get(grade or "none", "none")


def _validate_trade_plan(
    raw: Any,
    facts: dict[str, Any],
    notes: list[str],
) -> Optional[dict[str, Any]]:
    """把 AI 返回的 trade_plan 走一遍程序校验 + 自动 clamp。

    - 不存在或非 dict → None
    - direction 必须 long/short 且与 facts.l2_stance 一致(若有)
    - max_position_size_pct 不得超过 L4.position_cap × grade 乘数
    - stop_loss 必须在 hard_invalidation_levels 的价位列表里(§6.4 #9)
    """
    if not isinstance(raw, dict):
        return None

    grade = facts.get("l3_grade") or "none"
    # grade=none 不返回 trade_plan
    if grade not in {"A", "B", "C"}:
        return None

    direction = raw.get("direction")
    if direction not in {"long", "short"}:
        stance = facts.get("l2_stance")
        if stance in {"bullish"}:
            direction = "long"
        elif stance in {"bearish"}:
            direction = "short"
        else:
            notes.append("trade_plan_direction_unresolved")
            return None

    # cap clamp
    l4_cap = facts.get("l4_position_cap")
    max_cap_pct = float(l4_cap or 0.0) * 100.0
    cap_ceiling = max_cap_pct * _GRADE_CAP_MULTIPLIER.get(grade, 0.0)
    raw_size = raw.get("max_position_size_pct")
    try:
        size_pct = float(raw_size) if raw_size is not None else cap_ceiling
    except (TypeError, ValueError):
        size_pct = cap_ceiling
    if size_pct > cap_ceiling + 0.01:
        notes.append("trade_plan_size_clamped_to_grade_ceiling")
    size_pct = max(0.0, min(size_pct, cap_ceiling))

    # stop_loss 校验(§6.4 #9):必须在 hard_invalidation_levels 里
    hard_levels = facts.get("l4_hard_invalidation_levels") or []
    valid_stops = [
        float(h.get("price"))
        for h in hard_levels
        if isinstance(h, dict) and h.get("price") is not None
    ]
    stop_loss = raw.get("stop_loss")
    try:
        stop_loss_num = float(stop_loss) if stop_loss is not None else None
    except (TypeError, ValueError):
        stop_loss_num = None
    if stop_loss_num is None and valid_stops:
        stop_loss_num = valid_stops[0]  # 默认取 priority=1
        notes.append("trade_plan_stop_loss_defaulted_to_l4_priority_1")
    elif stop_loss_num is not None and valid_stops:
        # 找最接近 AI 值的 L4 价位
        closest = min(valid_stops, key=lambda p: abs(p - stop_loss_num))
        if abs(closest - stop_loss_num) > 0.01:
            stop_loss_num = closest
            notes.append("trade_plan_stop_loss_snapped_to_l4")

    entry_zones_raw = raw.get("entry_zones") or []
    entry_zones: list[dict[str, Any]] = []
    if isinstance(entry_zones_raw, list):
        for z in entry_zones_raw[:4]:
            if not isinstance(z, dict):
                continue
            try:
                low = float(z.get("price_low"))
                high = float(z.get("price_high"))
                alloc = float(z.get("allocation_pct", 0.0))
            except (TypeError, ValueError):
                continue
            entry_zones.append({
                "price_low": round(low, 2),
                "price_high": round(high, 2),
                "allocation_pct": round(alloc, 2),
            })

    tp_raw = raw.get("take_profit_plan") or []
    tp_plan: list[dict[str, Any]] = []
    if isinstance(tp_raw, list):
        for t in tp_raw[:5]:
            if not isinstance(t, dict):
                continue
            try:
                price = float(t.get("price"))
                size = float(t.get("size_pct", 0.0))
            except (TypeError, ValueError):
                continue
            tp_plan.append({
                "price": round(price, 2),
                "size_pct": round(size, 2),
            })

    return {
        "direction": direction,
        "confidence_tier": _tier_for_grade(grade),
        "max_position_size_pct": round(size_pct, 2),
        "entry_zones": entry_zones,
        "stop_loss": round(stop_loss_num, 2) if stop_loss_num is not None else None,
        "take_profit_plan": tp_plan,
        "dynamic_notes": str(raw.get("dynamic_notes") or "")[:400],
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
