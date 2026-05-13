"""src/ai/agents/_base.py — Sprint 1.8 6 个 AI 角色公共基类。

每个 L1-L5 + 主裁继承 BaseAgent,统一处理:
- prompt 文件加载(从 src/ai/agents/prompts/*.txt)
- anthropic client 调用 + 重试
- 响应解析(JSON loose + fallback)
- 失败 fallback dict(API timeout / 解析失败 / 校验不过)
- 统一日志埋点(latency / tokens / model_used)

子类只需实现:
- AGENT_NAME(类常量,如 'l1_regime')
- PROMPT_FILE(类常量,如 'l1_regime.txt')
- _build_user_prompt(context)(把 context dict 拍平成 user prompt 字符串)
- _fallback_output()(失败时返回的最小合法 dict)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from ..client import (
    build_anthropic_client, effective_model, extract_text, extract_usage,
    extract_model,
)


logger = logging.getLogger(__name__)


_PROMPTS_DIR = Path(__file__).parent / "prompts"
_DEFAULT_TIMEOUT_SEC = 120.0
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_TEMPERATURE = 0.2
_RETRY_TEMPERATURE = 0.4

# Sprint I:中转站(novaiapi.com)有多个上游 channel,部分 channel 偶发返回
# 400 "Provider API error: Model 'X' is not supported" 等中转站特定错误
# (实测同一 client + 同一 model id 反复重试可命中正常 channel 成功)。
# 重试间 sleep 2s 让中转站 channel 路由切换,避免连续打到同一个坏 channel。
_RETRY_SLEEP_SEC = 2.0

_TERMINAL_ERROR_STATUS_CODES = {401, 403}
_TERMINAL_ERROR_MARKERS = (
    "restricted to claude code clients only",
    "cannot be accessed through other api clients",
    "permission denied",
    "invalid api key",
    "unauthorized",
)
_OVERLOADED_ERROR_MARKERS = (
    "model is currently overloaded",
    "当前模型过载",
    "overloaded",
)


def _extract_status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    text = str(exc).lower()
    for code in (401, 403, 408, 429, 500, 502, 503, 504):
        if f"error code: {code}" in text or f"status_code={code}" in text:
            return code
    return None


def _is_terminal_ai_error(exc: BaseException) -> bool:
    status = _extract_status_code(exc)
    if status in _TERMINAL_ERROR_STATUS_CODES:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _TERMINAL_ERROR_MARKERS)


def _is_overloaded_ai_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _OVERLOADED_ERROR_MARKERS)


def _should_retry_ai_error(exc: BaseException, *, attempt: int) -> bool:
    if _is_terminal_ai_error(exc):
        return False
    if _is_overloaded_ai_error(exc):
        return attempt < 2
    return True


def build_factor_status_block_for_layer(
    layer_id: int, context: dict[str, Any],
) -> str:
    """Sprint E Step 2 — sub-agent prompt 注入「因子状态」段。

    context 需要含:
      - 'source_stale_map': {source: is_stale}(orchestrator 在 Step 3 装配)
      - 'source_hours_map': {source: hours_since_last_success}(可选,用于带
        "过期 N 小时"细节)

    若 context 缺这两个 key → 返 ""(向后兼容,Sprint E 之前的 caller 不破)。
    """
    stale_map = context.get("source_stale_map") or {}
    if not stale_map:
        return ""
    hours_map = context.get("source_hours_map")
    from ...strategy.factor_dependencies import format_factor_status_block
    return format_factor_status_block(
        layer_id, stale_map, source_hours_map=hours_map,
    )


class BaseAgent:
    """6 AI 角色公共基类。每个角色一个独立类继承本类。"""

    AGENT_NAME: str = ""        # e.g. 'l1_regime'
    PROMPT_FILE: str = ""       # e.g. 'l1_regime.txt'

    def __init__(
        self,
        *,
        client: Any = None,
        model: Optional[str] = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client_override = client
        self._model_override = model
        self._max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def analyze(
        self,
        context: dict[str, Any],
        *,
        client: Any = None,
    ) -> dict[str, Any]:
        """主入口。读 context → 调 AI → 解析 → 返回结构化 dict。

        v5(Sprint 1.8):支持 multi-modal — context 可含 'chart_b64' 字段
        (base64 PNG)。BaseAgent 自动构造 anthropic 多模态 message
        (image content block + text content block)。子类不需要管。

        Sprint 1.9-A.5.2 修:加 client= 参数。优先级:
          1. 调用方传入(orchestrator 每层新建避中转站连接复用限流)
          2. self._client_override(__init__ 注入,测试用)
          3. build_anthropic_client(timeout=_DEFAULT_TIMEOUT_SEC) 兜底

        失败时返回 _fallback_output(),status='degraded' / 'fallback'。
        绝不抛异常。
        """
        if not self.AGENT_NAME or not self.PROMPT_FILE:
            raise NotImplementedError(
                f"{type(self).__name__} 必须定义 AGENT_NAME + PROMPT_FILE"
            )

        try:
            system_prompt = self._load_system_prompt()
        except Exception as e:
            logger.warning(
                "%s: failed to load system prompt: %s", self.AGENT_NAME, e,
            )
            out = self._fallback_output()
            out["status"] = "degraded_prompt_load_failed"
            out["error"] = str(e)[:200]
            return out

        try:
            user_prompt = self._build_user_prompt(context)
        except Exception as e:
            logger.warning(
                "%s: failed to build user prompt: %s", self.AGENT_NAME, e,
            )
            out = self._fallback_output()
            out["status"] = "degraded_user_prompt_failed"
            out["error"] = str(e)[:200]
            return out

        # 优先级:调用方 client > self._client_override > 工厂兜底
        eff_client = client or self._client_override or build_anthropic_client(
            timeout=_DEFAULT_TIMEOUT_SEC,
        )
        if eff_client is None:
            out = self._fallback_output()
            out["status"] = "degraded_client_unavailable"
            return out

        chart_b64 = context.get("chart_b64") if context else None
        return self._call_ai_with_retry(
            eff_client, system_prompt, user_prompt, chart_b64=chart_b64,
        )

    # ------------------------------------------------------------------
    # Hooks for subclasses
    # ------------------------------------------------------------------

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """子类实现:把 context dict 拍平成 user prompt 字符串。"""
        raise NotImplementedError

    def _fallback_output(self) -> dict[str, Any]:
        """子类实现:失败时返回的最小合法 dict(含 agent / status 字段)。"""
        return {
            "agent": self.AGENT_NAME,
            "status": "degraded",
            "error": None,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_system_prompt(self) -> str:
        path = _PROMPTS_DIR / self.PROMPT_FILE
        if not path.exists():
            raise FileNotFoundError(
                f"prompt file missing: {path} "
                f"(Sprint 1.8 实施期间,prompt 文件需用户审完后才提交)"
            )
        return path.read_text(encoding="utf-8")

    def _call_ai_with_retry(
        self,
        client: Any,
        system_prompt: str,
        user_prompt: str,
        *,
        chart_b64: Optional[str] = None,
    ) -> dict[str, Any]:
        """3 次重试:温度 0.2 → 0.4 → 0.4。任一次解析成功即返回。

        v5:chart_b64 不为空时,user content 是 [image, text] list
        (anthropic multi-modal);否则纯 text。

        Sprint I:从 2 次重试改为 3 次,且重试间 sleep 2s 让中转站 channel
        重路由(中转站偶发 400 "Model not supported" 是 channel 路由问题,
        不是 model id 问题)。
        """
        model = effective_model(self._model_override)
        last_error: Optional[str] = None
        last_error_type: Optional[str] = None
        terminal_error = False
        total_tokens_in = 0
        total_tokens_out = 0
        total_latency_ms = 0
        last_model_used = model

        if chart_b64:
            user_content: Any = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": chart_b64,
                    },
                },
                {"type": "text", "text": user_prompt},
            ]
        else:
            user_content = user_prompt

        attempts_temps = (
            _DEFAULT_TEMPERATURE,
            _RETRY_TEMPERATURE,
            _RETRY_TEMPERATURE,
        )
        for attempt, temperature in enumerate(attempts_temps, start=1):
            if attempt > 1:
                time.sleep(_RETRY_SLEEP_SEC)
            start_ts = time.time()
            try:
                resp = client.messages.create(
                    model=model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_content}],
                    max_tokens=self._max_tokens,
                    temperature=temperature,
                )
            except Exception as e:
                elapsed_ms = int((time.time() - start_ts) * 1000)
                retryable = _should_retry_ai_error(e, attempt=attempt)
                last_error = f"attempt {attempt}: {e}"
                last_error_type = type(e).__name__
                terminal_error = terminal_error or _is_terminal_ai_error(e)
                total_latency_ms += elapsed_ms
                logger.warning(
                    "%s: attempt %d failed model=%s elapsed_ms=%d "
                    "error_type=%s retryable=%s error=%s",
                    self.AGENT_NAME, attempt, model, elapsed_ms,
                    type(e).__name__, retryable, e,
                )
                if not retryable:
                    break
                continue

            total_latency_ms += int((time.time() - start_ts) * 1000)
            total_tokens_in += extract_usage(resp, "input_tokens")
            total_tokens_out += extract_usage(resp, "output_tokens")
            last_model_used = extract_model(resp, model)

            text = extract_text(resp)
            parsed = _parse_json_loose(text)
            if parsed is None:
                last_error = (
                    f"attempt {attempt}: JSON parse failed; "
                    f"text[:200]={(text or '')[:200]!r}"
                )
                continue

            parsed.setdefault("agent", self.AGENT_NAME)
            parsed.setdefault("status", "success")
            parsed["model_used"] = last_model_used
            parsed["tokens_in"] = total_tokens_in
            parsed["tokens_out"] = total_tokens_out
            parsed["latency_ms"] = total_latency_ms
            return parsed

        out = self._fallback_output()
        out["status"] = (
            "degraded_ai_terminal_error" if terminal_error
            else "degraded_ai_failed"
        )
        out["error"] = (last_error or "all retries failed")[:200]
        out["error_type"] = last_error_type
        out["model_used"] = last_model_used
        out["tokens_in"] = total_tokens_in
        out["tokens_out"] = total_tokens_out
        out["latency_ms"] = total_latency_ms
        return out


# ============================================================
# JSON loose parser(沿用 adjudicator.py 模式,提取到这里给所有 agent 用)
# ============================================================

def _parse_json_loose(text: Optional[str]) -> Optional[dict[str, Any]]:
    """JSON loose:去 ```code 包裹 → 直接 parse → 退而求其次找最外层 {...}。"""
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
            obj = json.loads(t[first : last + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return obj if isinstance(obj, dict) else None
