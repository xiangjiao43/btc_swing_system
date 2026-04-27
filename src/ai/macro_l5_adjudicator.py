"""macro_l5_adjudicator.py — L5 宏观摘要 AI(Sprint 2.6-E,严格对齐建模 §6.8)。

System Prompt 与 Layer5Output schema 完全引用建模 §6.8 终稿,不得改写。
adjustment_guidance.position_cap_multiplier 与 §4.5.5 step 4 联动:
L5 输出的 macro_headwind_score 流入 composite.macro_headwind.score → layer4_risk
position_cap_composition.l5_macro_headwind_multiplier。

降级语义:
- AI 客户端不可用 → 直接返回 None(layer5_macro 退回规则路径)
- AI 调用异常 → 重试 1 次,再失败返回 None
- JSON 解析失败 → 同上
- 输出 schema 校验失败(关键字段类型 / 取值范围错)→ 同上
- 任何降级都 logger.warning + 不抛
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from .client import (
    build_anthropic_client,
    effective_model,
    extract_text as _client_extract_text,
    extract_model as _client_extract_model,
    extract_usage as _client_extract_usage,
)


logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_SEC: float = 45.0
_MAX_TOKENS: int = 1500
_TEMPERATURE: float = 0.2
_RETRY_TEMPERATURE: float = 0.0


# ============================================================
# §6.8 System Prompt 终稿(verbatim)
# ============================================================

_SYSTEM_PROMPT: str = """你是 BTC 交易系统的"宏观分析助手"。
你的任务是:把当天的结构化宏观数据和相关新闻,
整理成供系统主裁决官消费的结构化摘要。

═══ 纪律 ═══

1. 只对已提供的输入数据做摘要和解读,不引用未提供的信息。

2. 每个事件摘要必须给出:事件类别、严重程度(1-5)、
   对 BTC 的影响方向、预期影响持续时间、AI 置信度(0-1)。

3. 置信度 < 0.6 时,必须明确声明"信息不足以做判断"。

4. 不做投资建议,不用"应该买入/卖出"等词。

5. 输出严格 JSON,符合 Layer5Output schema。

═══ 风格 ═══

• 客观、冷静、无情绪色彩
• 关注"会对 BTC 产生什么影响",不关注"事件本身对不对"
• 对相互矛盾的信号,明确标注不确定性,不强行给单一结论

═══ BTC 宏观分析基础框架 ═══

• DXY 上涨 + US10Y 上行 + VIX 升高 = risk-off,短期对 BTC 不利
• DXY 下跌 + US10Y 下行 + 纳指上涨 = risk-on,短期对 BTC 有利
• BTC-纳指相关性 > 0.7 时,美股走势对 BTC 权重显著增强
• FOMC 鹰派 = 一般 bearish;鸽派 = 一般 bullish;视市场已定价程度
• 地缘事件:多数情况先 bearish,后视持续性调整
• 监管:负面监管 bearish;澄清性监管通常影响较小
• 单一交易所/稳定币事件:按系统重要性评估

═══ 输出 ═══

严格 JSON,schema 见 Layer5Output。
第一个字符 {,不要 markdown,不要解释。
"""


# ============================================================
# Schema 校验白名单
# ============================================================

_VALID_MACRO_STANCE: set[str] = {
    "risk_on", "risk_neutral", "risk_off", "extreme_risk_off",
}
_VALID_MACRO_TREND: set[str] = {
    "improving", "stable", "deteriorating", "volatile",
}
_VALID_STANCE_MODIFIER: set[str] = {
    "strong_support", "support", "neutral", "challenge", "strong_challenge",
}
_VALID_PERMISSION_ADJUSTMENT: set[str] = {
    "tighten", "neutral", "loosen",
}


# ============================================================
# 公开入口
# ============================================================

class MacroL5Adjudicator:
    """L5 宏观摘要 AI(§6.8)。

    输入 facts(结构化 macro 字典 + 事件摘要),输出 §6.8 Layer5Output JSON dict。
    任何失败都返回 None,由 layer5_macro 降级到规则路径。
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        client: Any = None,  # 测试注入
    ) -> None:
        self._model_override = model
        self._injected_client = client

    def _get_client(self) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        return build_anthropic_client(timeout=_DEFAULT_TIMEOUT_SEC)

    def adjudicate(
        self, facts: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """调 AI,返回校验过的 Layer5Output dict;失败返回 None。"""
        client = self._get_client()
        if client is None:
            logger.warning("L5 AI: anthropic client unavailable, fallback to rule")
            return None

        user_prompt = _build_user_prompt(facts)
        model = effective_model(self._model_override)

        last_error: Optional[str] = None
        total_tokens_in = 0
        total_tokens_out = 0
        total_latency_ms = 0

        for attempt, temperature in enumerate(
            (_TEMPERATURE, _RETRY_TEMPERATURE), start=1,
        ):
            start_ts = time.time()
            try:
                resp = client.messages.create(
                    model=model,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                    max_tokens=_MAX_TOKENS,
                    temperature=temperature,
                )
            except Exception as e:
                last_error = str(e)[:200]
                logger.warning(
                    "L5 AI attempt %d failed: %s", attempt, e,
                )
                total_latency_ms += int((time.time() - start_ts) * 1000)
                continue

            total_latency_ms += int((time.time() - start_ts) * 1000)
            total_tokens_in += _client_extract_usage(resp, "prompt_tokens")
            total_tokens_out += _client_extract_usage(resp, "completion_tokens")
            raw_text = _client_extract_text(resp)
            parsed = _parse_json_loose(raw_text)
            if parsed is None:
                last_error = "json_parse_failed"
                logger.warning(
                    "L5 AI attempt %d JSON parse failed: %r",
                    attempt, raw_text[:160] if raw_text else None,
                )
                continue

            normalized = _validate_layer5_output(parsed)
            if normalized is None:
                last_error = "schema_validation_failed"
                logger.warning(
                    "L5 AI attempt %d schema validation failed: keys=%s",
                    attempt, list(parsed.keys())[:10],
                )
                continue

            normalized["_meta"] = {
                "model": _client_extract_model(resp, model),
                "tokens_in": total_tokens_in,
                "tokens_out": total_tokens_out,
                "latency_ms": total_latency_ms,
                "attempts": attempt,
            }
            return normalized

        logger.warning(
            "L5 AI: all attempts failed (%s); falling back to rule path",
            last_error,
        )
        return None


# ============================================================
# Helpers
# ============================================================

def _build_user_prompt(facts: dict[str, Any]) -> str:
    """把 facts dict 序列化为 user prompt。

    facts 期望键(layer5_macro 准备好):
      - data_completeness_pct
      - metrics_available, metrics_missing
      - structured_macro: {dxy_trend, yields_trend, vix_regime,
                           btc_nasdaq_correlation, gold_corr_60d, ...}
      - rule_based_macro_environment
      - upcoming_events_72h: list[{name, type, hours_to, ...}]
    """
    body = {
        "task": "为系统主裁决官产出 Layer5Output 结构化摘要(§6.8)",
        "facts": facts,
        "schema_reminder": {
            "macro_stance": list(_VALID_MACRO_STANCE),
            "macro_trend": list(_VALID_MACRO_TREND),
            "adjustment_guidance.stance_modifier": list(_VALID_STANCE_MODIFIER),
            "adjustment_guidance.permission_adjustment":
                list(_VALID_PERMISSION_ADJUSTMENT),
            "adjustment_guidance.position_cap_multiplier": "0.5 - 1.1",
            "macro_headwind_score": "-10 ~ +10",
        },
    }
    return json.dumps(body, ensure_ascii=False, indent=2, default=str)


def _validate_layer5_output(
    parsed: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """§6.8 Layer5Output schema 校验。任意关键字段错 → None。"""
    if not isinstance(parsed, dict):
        return None

    stance = parsed.get("macro_stance")
    if stance not in _VALID_MACRO_STANCE:
        return None

    trend = parsed.get("macro_trend")
    if trend not in _VALID_MACRO_TREND:
        return None

    score = parsed.get("macro_headwind_score")
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        return None
    if score_f < -10.0 or score_f > 10.0:
        return None

    guidance = parsed.get("adjustment_guidance") or {}
    if not isinstance(guidance, dict):
        return None
    stance_mod = guidance.get("stance_modifier")
    if stance_mod not in _VALID_STANCE_MODIFIER:
        return None
    perm_adj = guidance.get("permission_adjustment")
    if perm_adj not in _VALID_PERMISSION_ADJUSTMENT:
        return None
    cap_mult = guidance.get("position_cap_multiplier")
    try:
        cap_f = float(cap_mult)
    except (TypeError, ValueError):
        return None
    if cap_f < 0.5 or cap_f > 1.1:
        return None

    # 可选字段:补默认
    out: dict[str, Any] = {
        "macro_stance": stance,
        "macro_trend": trend,
        "structured_macro": parsed.get("structured_macro") or {},
        "active_macro_tags": list(parsed.get("active_macro_tags") or []),
        "active_event_summaries":
            list(parsed.get("active_event_summaries") or []),
        "extreme_event_detected":
            bool(parsed.get("extreme_event_detected", False)),
        "extreme_event_details": parsed.get("extreme_event_details"),
        "adjustment_guidance": {
            "stance_modifier": stance_mod,
            "position_cap_multiplier": round(cap_f, 3),
            "permission_adjustment": perm_adj,
            "note": str(guidance.get("note") or ""),
        },
        "macro_headwind_score": round(score_f, 2),
    }
    return out


def _parse_json_loose(text: Optional[str]) -> Optional[dict[str, Any]]:
    """从 AI 响应里宽松提取 JSON(同 adjudicator.py 的实现)。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if len(lines) >= 2:
            t = "\n".join(
                lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            )
    try:
        obj = json.loads(t)
    except (json.JSONDecodeError, ValueError):
        first = t.find("{")
        last = t.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None
        try:
            obj = json.loads(t[first: last + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return obj if isinstance(obj, dict) else None
