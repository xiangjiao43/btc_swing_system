"""src/ai/retry_policy.py — Sprint 1.10-F 重试策略类(v1.4 §6.3.2)。

orchestrator 层失败重试策略(异步重试,跨 cron tick):
- 指数退避:第 1/2/3 次重试间隔 5/10/20 分钟(可配置 base.yaml::ai_retry.intervals_minutes)
- 单层重试上限:3 次(超过 → 短路下游,由 CircuitBreaker 处理)
- 整次窗口:2 小时(超过 → 放弃所有重试,fallback Level 2)

注:与 BaseAgent._call_ai_with_retry 的 2-attempt 即时重试不同,
本类是 orchestrator 层的"等下次 cron"异步重试。

设计纪律:
- 纯函数 / 无 DB 写(配合 D1=b:retry_log 写入由 orchestrator 协调)
- 配置从 base.yaml 读,缺失时用 v1.4 §6.3 默认值
- 不调真 AI(retry 触发由 cron / orchestrator 决定)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


# v1.4 §6.3.2 默认值(若 base.yaml 缺失)
_DEFAULT_INTERVALS_MIN = [5, 10, 20]
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_WINDOW_HOURS = 2

# 失败分类枚举(供 retry_log 用)
FAILURE_TIMEOUT = "timeout"
FAILURE_API_ERROR = "api_error"
FAILURE_PARSE_ERROR = "parse_error"
FAILURE_VALIDATION = "validation_failed"
FAILURE_UNKNOWN = "unknown"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"


def _parse_iso(s: str) -> datetime:
    s = str(s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


class RetryPolicy:
    """orchestrator 层重试策略(v1.4 §6.3.2)。

    用法:
        policy = RetryPolicy()
        if policy.should_retry(attempt=1, run_started_at_utc="2026-05-03T08:00:00Z",
                                now_utc="2026-05-03T08:05:00Z"):
            wait_sec = policy.compute_backoff_seconds(attempt=1)  # 300
            # ... 等待后重试
    """

    def __init__(
        self,
        *,
        intervals_minutes: list[int] | None = None,
        max_attempts_per_layer: int | None = None,
        total_window_hours: float | None = None,
    ):
        cfg = self._load_config()
        ai_retry = cfg.get("ai_retry") or {}
        self.intervals_minutes = (
            intervals_minutes
            or ai_retry.get("intervals_minutes")
            or _DEFAULT_INTERVALS_MIN
        )
        self.max_attempts_per_layer = (
            max_attempts_per_layer
            or ai_retry.get("max_attempts_per_layer")
            or _DEFAULT_MAX_ATTEMPTS
        )
        self.total_window_hours = (
            total_window_hours
            or ai_retry.get("total_window_hours")
            or _DEFAULT_WINDOW_HOURS
        )

    @staticmethod
    def _load_config() -> dict[str, Any]:
        if not _BASE_YAML.exists():
            return {}
        try:
            with open(_BASE_YAML, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}

    def compute_backoff_seconds(self, attempt: int) -> int | None:
        """指数退避:给定第 N 次重试(1-based),返回等待秒数。

        - attempt=1 → intervals_minutes[0] * 60(默认 5min = 300s)
        - attempt=2 → intervals_minutes[1] * 60(默认 600s)
        - attempt=3 → intervals_minutes[2] * 60(默认 1200s)
        - attempt > max_attempts_per_layer → None(已超上限)

        Args:
            attempt: 1-indexed 重试次数(第几次重试,不含原始失败那次)
        """
        if attempt < 1 or attempt > self.max_attempts_per_layer:
            return None
        if attempt > len(self.intervals_minutes):
            # intervals 不够长时用最后一个值兜底
            return int(self.intervals_minutes[-1]) * 60
        return int(self.intervals_minutes[attempt - 1]) * 60

    def is_within_window(
        self, run_started_at_utc: str, now_utc: str,
    ) -> bool:
        """整次 run 窗口判定(v1.4 §6.3.3):2h 内可重试,超过 → 放弃。

        Args:
            run_started_at_utc: 本次 run 起始 ISO 8601 UTC
            now_utc: 当前时间 ISO 8601 UTC
        """
        try:
            start = _parse_iso(run_started_at_utc)
            now = _parse_iso(now_utc)
        except (ValueError, TypeError):
            return False
        elapsed_hours = (now - start).total_seconds() / 3600.0
        return elapsed_hours < self.total_window_hours

    def should_retry(
        self, attempt: int, run_started_at_utc: str, now_utc: str,
    ) -> bool:
        """组合判定:是否还应该重试?

        条件全满足:
        - attempt ≤ max_attempts_per_layer
        - 在 2h 窗口内
        """
        if attempt < 1 or attempt > self.max_attempts_per_layer:
            return False
        return self.is_within_window(run_started_at_utc, now_utc)

    @staticmethod
    def classify_failure(exception: BaseException) -> str:
        """分类失败原因(供 retry_log 写入)。

        粗略匹配:
        - TimeoutError / 包含 "timeout" → timeout
        - JSONDecodeError / 包含 "parse" / "json" → parse_error
        - 包含 "validation" / "validator" → validation_failed
        - 其他 Exception → api_error
        """
        msg = str(exception).lower()
        cls_name = type(exception).__name__.lower()
        if isinstance(exception, TimeoutError) or "timeout" in msg or "timeout" in cls_name:
            return FAILURE_TIMEOUT
        if "json" in cls_name or "parse" in msg or "decode" in msg:
            return FAILURE_PARSE_ERROR
        if "validation" in msg or "validator" in msg:
            return FAILURE_VALIDATION
        if isinstance(exception, Exception):
            return FAILURE_API_ERROR
        return FAILURE_UNKNOWN
