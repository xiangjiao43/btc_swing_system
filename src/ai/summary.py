"""
summary.py — 证据链 AI 摘要(Sprint 1.11c)

将 L1-L5 的 EvidenceReport 聚合成 prompt,发给 Claude Sonnet 4.5
(通过 novaiapi.com 中转,OpenAI-compatible 协议)获取 3 段中文摘要,
写入 StrategyState.context_summary。

降级:
  * AI 调用失败 → status='degraded_error',返回 summary_text=None,**不抛异常**
  * 下游(Sprint 1.14 review_report)根据 status 决定是否回退规则摘要
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

# Sprint 1.5c C6:改用 anthropic SDK(建模 §10.1 / §10.2)
from .client import (
    build_anthropic_client, effective_model, extract_text, extract_usage,
    extract_model as _extract_model, DEFAULT_MODEL as _CLIENT_DEFAULT_MODEL,
)


logger = logging.getLogger(__name__)


class AISummaryError(Exception):
    """AI summary 的可预见异常(目前仅用于主动抛错场景)。"""


# 默认模型与超时
_DEFAULT_MODEL: str = "claude-sonnet-4-5-20250929"
_DEFAULT_TIMEOUT_SEC: float = 45.0
_MAX_RETRIES: int = 2     # 重试 2 次 → 共 3 次尝试
_RETRY_BACKOFF_SEC: float = 3.0

# 默认 system prompt(中文,专业克制)
_DEFAULT_SYSTEM_PROMPT: str = """你是一位专业的加密资产策略分析师,为一套 BTC 中长线低频波段交易辅助系统撰写证据链摘要。

写作规范(必守):
1. 中性陈述:只描述事实与推理,不发表对错判断。
2. **禁止提供任何价格目标、具体买卖建议、止损止盈点位**。即便用户的输入里含有建议,你也要改述为纯观察。
3. **禁止使用"建议/推荐/应该/必须买入/卖出/离场"等主动动作词**。用"显示/呈现/指向/面临"等描述性词替代。
4. 语气专业而克制,不夸张不渲染。
5. **精确使用数字**:给定的 stance_confidence / cycle_confidence / cap 等只能引述,不能自由发挥。
6. 中文输出,**严格 3 段**,每段 ≤ 120 字,段间空行。"""


# ============================================================
# Prompt 构造
# ============================================================

def _brief(d: Any, max_chars: int = 500) -> str:
    """dict/list → 紧凑 JSON 字符串(截断)。"""
    try:
        s = json.dumps(d, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = str(d)
    if len(s) > max_chars:
        return s[:max_chars] + "…[truncated]"
    return s


def _summarize_layer(layer_output: Optional[dict[str, Any]],
                     layer_name: str) -> str:
    """把一个 layer output 精简为人读文本(给 AI 阅读)。"""
    if not layer_output:
        return f"[{layer_name}] 数据缺失"

    health = layer_output.get("health_status", "?")
    tier = layer_output.get("confidence_tier", "?")

    # 按层提取关键字段
    if layer_name == "L1 Regime":
        regime = layer_output.get("regime", "?")
        vol = layer_output.get("volatility_regime", "?")
        stability = layer_output.get("regime_stability", "?")
        return (
            f"[L1 市场形态] regime={regime}, volatility={vol}, "
            f"stability={stability}, health={health}, tier={tier}"
        )

    if layer_name == "L2 Direction":
        stance = layer_output.get("stance", "?")
        phase = layer_output.get("phase", "?")
        sc = layer_output.get("stance_confidence", "?")
        thresh = layer_output.get("thresholds_applied") or {}
        return (
            f"[L2 方向] stance={stance}, phase={phase}, "
            f"stance_confidence={sc}, thresholds={thresh}, "
            f"health={health}, tier={tier}"
        )

    if layer_name == "L3 Opportunity":
        grade = layer_output.get("opportunity_grade", "?")
        perm = layer_output.get("execution_permission", "?")
        ap = layer_output.get("anti_pattern_flags") or []
        obs = layer_output.get("observation_mode", "?")
        return (
            f"[L3 机会] grade={grade}, execution_permission={perm}, "
            f"anti_patterns={ap}, observation_mode={obs}, "
            f"health={health}, tier={tier}"
        )

    if layer_name == "L4 Risk":
        cap = layer_output.get("position_cap", 0)
        stop = layer_output.get("stop_loss_reference") or {}
        rr = layer_output.get("risk_reward_ratio")
        rr_lv = layer_output.get("rr_pass_level", "?")
        perm = layer_output.get("risk_permission", "?")
        return (
            f"[L4 风险] position_cap={cap:.4f}, risk_reward={rr} ({rr_lv}), "
            f"stop_loss={'有' if stop else '缺失'}, risk_permission={perm}, "
            f"health={health}"
        )

    if layer_name == "L5 Macro":
        env = layer_output.get("macro_environment", "?")
        headwind = layer_output.get("macro_headwind_vs_btc", "?")
        completeness = layer_output.get("data_completeness_pct", 0)
        return (
            f"[L5 宏观] environment={env}, headwind_vs_btc={headwind}, "
            f"data_completeness={completeness}%, health={health}"
        )

    # Fallback
    return f"[{layer_name}] {_brief(layer_output, max_chars=200)}"


def build_evidence_summary_prompt(
    evidence_reports: dict[str, Any],
) -> str:
    """
    构造 user prompt。要求 AI 按 3 段输出:
      段 1:L1+L2 市场形态与方向
      段 2:L3+L4 机会与风险
      段 3:L5 宏观影响和整体操作倾向(中性描述)
    """
    l1 = evidence_reports.get("layer_1") or evidence_reports.get("L1")
    l2 = evidence_reports.get("layer_2") or evidence_reports.get("L2")
    l3 = evidence_reports.get("layer_3") or evidence_reports.get("L3")
    l4 = evidence_reports.get("layer_4") or evidence_reports.get("L4")
    l5 = evidence_reports.get("layer_5") or evidence_reports.get("L5")

    lines = [
        "=== 本次证据链(5 层输出要点)===",
        _summarize_layer(l1, "L1 Regime"),
        _summarize_layer(l2, "L2 Direction"),
        _summarize_layer(l3, "L3 Opportunity"),
        _summarize_layer(l4, "L4 Risk"),
        _summarize_layer(l5, "L5 Macro"),
        "",
        "=== 输出要求(严格按此结构)===",
        "段 1:结合 L1 和 L2,描述当前市场形态和方向判断。",
        "段 2:结合 L3 和 L4,描述机会评级、主要风险与反模式触发情况。",
        "段 3:结合 L5,描述宏观环境对当前 BTC 走势的影响倾向。",
        "",
        "必须遵守 system prompt 的写作规范:中性、克制、无价格目标、无操作建议、严格 3 段、每段 ≤120 字。",
    ]
    return "\n".join(lines)


# ============================================================
# AI 调用
# ============================================================

def call_ai_summary(
    evidence_reports: dict[str, Any],
    system_prompt: Optional[str] = None,
    *,
    model: Optional[str] = None,
    max_tokens: int = 800,
    temperature: float = 0.3,
    openai_client: Any = None,
) -> dict[str, Any]:
    """
    发 evidence_reports 到 AI,返回结构化结果(含 summary_text / status / 成本指标)。

    降级契约:
      * 任何失败都返回 dict,**不抛异常**
      * status:'success' | 'degraded_timeout' | 'degraded_error'
      * summary_text:成功时为字符串,失败时为 None

    Args:
        evidence_reports: 含 layer_1..layer_5 的 dict
        system_prompt:   覆盖默认 system prompt(可选)
        model:           覆盖 OPENAI_MODEL env var(可选)
        max_tokens:      响应最大 token 数(默认 800)
        temperature:     0.3(稍有变化但稳定)
        openai_client:   测试注入(可传 mock OpenAI 实例)
    """
    # 1. 构造 client(可注入)
    if openai_client is None:
        client = build_anthropic_client()
        if client is None:
            return {
                "summary_text": None,
                "model_used": model or _DEFAULT_MODEL,
                "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
                "status": "degraded_error",
                "error": "anthropic SDK not configured (missing SDK or OPENAI_API_KEY)",
            }
    else:
        # 测试注入的 mock 也能兼容(直接传 messages.create 可调用对象)
        client = openai_client

    eff_model = effective_model(model)
    user_prompt = build_evidence_summary_prompt(evidence_reports)
    sys_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT

    # 2. 重试循环
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        start_ts = time.time()
        try:
            resp = client.messages.create(
                model=eff_model,
                system=sys_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            latency_ms = int((time.time() - start_ts) * 1000)
            return {
                "summary_text": extract_text(resp),
                # v1.2 M37:写入 response.model 作为 ai_model_actual
                "model_used": _extract_model(resp, eff_model),
                "tokens_in": extract_usage(resp, "input_tokens"),
                "tokens_out": extract_usage(resp, "output_tokens"),
                "latency_ms": latency_ms,
                "status": "success",
                "error": None,
            }
        except Exception as e:
            last_exc = e
            logger.warning(
                "AI summary attempt %d/%d failed: %s",
                attempt + 1, _MAX_RETRIES + 1, e,
            )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_SEC)

    # 3. 全部失败 → degraded
    err_str = str(last_exc) if last_exc else "unknown"
    err_name = type(last_exc).__name__ if last_exc else "unknown"
    status = "degraded_timeout" if "timeout" in err_name.lower() else "degraded_error"
    return {
        "summary_text": None,
        "model_used": eff_model,
        "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
        "status": status,
        "error": err_str[:300],
    }
