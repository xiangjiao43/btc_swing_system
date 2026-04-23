"""
_config_loader.py — data_sources.yaml 配置读取(Collectors 专用辅助)

职责:
  - 从 config/data_sources.yaml 读取源配置
  - 合并 defaults 和 source 自己的字段
  - 解析 URL 的 env 覆盖(BINANCE_BASE_URL 等 → os.environ)
  - 不做 .env 自动加载(若需要,调用方先 `source .env`)

之所以叫 _config_loader(下划线开头):这是 collectors 模块的私有辅助,
后续统一的 src/common/config.py 落地时此文件会被替换/收拢。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


_THIS_DIR: Path = Path(__file__).resolve().parent
_REPO_ROOT: Path = _THIS_DIR.parent.parent.parent
_DATA_SOURCES_YAML: Path = _REPO_ROOT / "config" / "data_sources.yaml"


def load_data_sources_config() -> dict[str, Any]:
    """
    读取完整 data_sources.yaml(未解析 env)。

    Returns:
        {"defaults": {...}, "sources": {binance: {...}, glassnode: {...}, ...}}
    """
    with open(_DATA_SOURCES_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_env_or_default(env_var: str | None, default: str | None) -> str | None:
    """
    env_var 名对应的环境变量存在且非空 → 返回其值;否则返回 default。
    env_var 为 None 时直接返回 default。
    """
    if env_var:
        val = os.environ.get(env_var, "")
        if val:
            return val
    return default


def load_source_config(source_name: str) -> dict[str, Any]:
    """
    加载指定数据源的**解析后**配置:
      - URL 已按 env var / default 兜底解析
      - retry / rate_limit 已与 defaults 合并(source 字段覆盖 defaults)

    Args:
        source_name: data_sources.yaml → sources.<name> 的键,如 "binance"。

    Returns:
        已解析的源配置 dict,包含:
          base_url (str)
          futures_base_url (str | None,仅 binance 有)
          auth_type, api_key_env, api_key_header, api_key_query
          timeout_sec (int)
          retry (dict)
          rate_limit (dict)
          freshness_class (str)
          enabled (bool)
          name (str),purpose (str)

    Raises:
        KeyError: 若 source_name 不在 data_sources.yaml → sources。
    """
    full = load_data_sources_config()
    defaults: dict[str, Any] = full.get("defaults") or {}
    sources: dict[str, Any] = full.get("sources") or {}
    if source_name not in sources:
        raise KeyError(
            f"Source {source_name!r} not found in data_sources.yaml; "
            f"available: {list(sources)}"
        )
    src = sources[source_name]

    # ---- URL 解析 ----
    base_url = resolve_env_or_default(
        src.get("base_url_env"), src.get("base_url_default")
    )
    futures_base_url = resolve_env_or_default(
        src.get("futures_base_url_env"), src.get("futures_base_url_default")
    )

    # ---- API key 解析(不返回真值,只返回是否启用) ----
    api_key_env = src.get("api_key_env")
    api_key = os.environ.get(api_key_env, "") if api_key_env else ""

    # ---- defaults 合并(source 覆盖 defaults) ----
    merged_retry = {**(defaults.get("retry") or {}), **(src.get("retry") or {})}
    merged_rate = {**(defaults.get("rate_limit") or {}), **(src.get("rate_limit") or {})}

    return {
        "name": src.get("name", source_name),
        "purpose": src.get("purpose", ""),
        "enabled": bool(src.get("enabled", False)),
        "base_url": base_url,
        "futures_base_url": futures_base_url,
        "auth_type": src.get("auth_type", "none"),
        "api_key_env": api_key_env,
        "api_key": api_key,                        # 运行时值;空字符串表示未设置
        "api_key_header": src.get("api_key_header"),
        "api_key_query": src.get("api_key_query"),
        "timeout_sec": int(src.get("timeout_sec") or defaults.get("timeout_sec") or 10),
        "retry": merged_retry,
        "rate_limit": merged_rate,
        "freshness_class": src.get("freshness_class"),
    }
