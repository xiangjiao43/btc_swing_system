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
from pathlib import Path
from typing import Any, Optional

import yaml

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


DEFAULT_MODEL: str = "claude-sonnet-4-5-20250929"
# 手动 pipeline 需要能在中转站无响应时及时降级。120s 是单次 AI 请求上限,
# BaseAgent 仍会按原有重试策略 fallback/degraded。
DEFAULT_TIMEOUT_SEC: float = 120.0
_ROOT = Path(__file__).resolve().parents[2]
_AI_CONFIG_PATH = _ROOT / "config" / "ai.yaml"


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

    # anthropic SDK 自带内部 retry。项目外层 BaseAgent 已有显式 retry、
    # stage 日志和 fallback；关闭 SDK 隐藏 retry，避免一次 agent 调用被放大
    # 成几分钟且日志看不出卡在哪。
    kwargs: dict[str, Any] = {
        "api_key": eff_key,
        "timeout": timeout,
        "max_retries": 0,
    }
    if eff_base:
        kwargs["base_url"] = eff_base
    return Anthropic(**kwargs)


def effective_model(override: Optional[str] = None) -> str:
    return override or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL


def _split_models(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def _load_ai_config() -> dict[str, Any]:
    try:
        with _AI_CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def effective_fallback_models(primary_model: str | None = None) -> list[str]:
    """Return fallback models from env/config without guessing model names.

    Priority:
      1. OPENAI_FALLBACK_MODELS comma-separated list
      2. OPENAI_FALLBACK_MODEL single value
      3. config/ai.yaml fallback_models.model_name_defaults
    """
    models = _split_models(os.getenv("OPENAI_FALLBACK_MODELS"))
    if not models:
        models = _split_models(os.getenv("OPENAI_FALLBACK_MODEL"))
    if not models:
        fb_cfg = (_load_ai_config().get("fallback_models") or {})
        defaults = fb_cfg.get("model_name_defaults") or []
        if isinstance(defaults, str):
            models = _split_models(defaults)
        elif isinstance(defaults, list):
            models = [str(x).strip() for x in defaults if str(x).strip()]

    primary = (primary_model or effective_model()).strip()
    seen: set[str] = set()
    out: list[str] = []
    for model in models:
        if model == primary or model in seen:
            continue
        seen.add(model)
        out.append(model)
    return out


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
