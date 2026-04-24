"""
ai/client.py — Sprint 1.5c C6:anthropic Python SDK 统一客户端工厂。

建模 §10.1 / §10.2 要求 AI SDK 用 anthropic,通过 base_url 切换中转站。
.env 沿用现有 OPENAI_API_BASE / OPENAI_API_KEY / OPENAI_MODEL 键名
(用户要求不动 .env,只改代码层调用)。

anthropic 默认会在 base_url 后附加 /v1/messages;若 OPENAI_API_BASE 已带 /v1
后缀(常见),需去掉避免重复。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


DEFAULT_MODEL: str = "claude-sonnet-4-5-20250929"
DEFAULT_TIMEOUT_SEC: float = 45.0


def normalize_base_url(base_url: Optional[str]) -> Optional[str]:
    """anthropic SDK 会自动拼 /v1/messages;若 base_url 已带 /v1 则剥掉。"""
    if not base_url:
        return None
    s = base_url.strip()
    if s.endswith("/v1"):
        s = s[: -len("/v1")]
    elif s.endswith("/v1/"):
        s = s[: -len("/v1/")]
    return s.rstrip("/")


def build_anthropic_client(
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> Any:
    """
    构造 anthropic.Anthropic 客户端。未传入则从 .env 读 OPENAI_API_BASE /
    OPENAI_API_KEY。anthropic SDK 未安装时返回 None。
    """
    if Anthropic is None:
        logger.error("anthropic SDK not installed (`uv add anthropic`)")
        return None

    eff_base = normalize_base_url(base_url or os.getenv("OPENAI_API_BASE"))
    eff_key = api_key or os.getenv("OPENAI_API_KEY")
    if not eff_key:
        logger.error("OPENAI_API_KEY not set in environment")
        return None

    kwargs: dict[str, Any] = {"api_key": eff_key, "timeout": timeout}
    if eff_base:
        kwargs["base_url"] = eff_base
    return Anthropic(**kwargs)


def effective_model(override: Optional[str] = None) -> str:
    return override or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL


def extract_text(response: Any) -> str:
    """anthropic Messages API 的 content 是 list[TextBlock],取第一个 text。"""
    try:
        blocks = response.content or []
        for b in blocks:
            txt = getattr(b, "text", None)
            if txt:
                return str(txt)
    except Exception as e:  # pragma: no cover
        logger.warning("extract_text failed: %s", e)
    return ""


def extract_usage(response: Any, key: str) -> int:
    """anthropic usage 字段名:input_tokens / output_tokens。
    key 接受 'prompt_tokens' / 'input_tokens' / 'completion_tokens' / 'output_tokens'。
    """
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0
        if key in ("prompt_tokens", "input_tokens"):
            return int(getattr(usage, "input_tokens", 0) or
                       getattr(usage, "prompt_tokens", 0) or 0)
        if key in ("completion_tokens", "output_tokens"):
            return int(getattr(usage, "output_tokens", 0) or
                       getattr(usage, "completion_tokens", 0) or 0)
        return int(getattr(usage, key, 0) or 0)
    except Exception:
        return 0


def extract_model(response: Any, fallback: str) -> str:
    """response.model 是实际调用的模型名(v1.2 M37)。"""
    return str(getattr(response, "model", None) or fallback)
