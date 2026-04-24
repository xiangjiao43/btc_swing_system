"""
api/state.py — App-level state shared across routes.

AppState 持有:
  * conn_factory:每次 handler 需要 DB 时调用
  * 节流窗口 + 最近一次 pipeline trigger 时间
  * 启动时间、版本号(用于 /health)

简单 dataclass,无需 pydantic。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Optional


@dataclass
class AppState:
    conn_factory: Callable[[], Any]
    pipeline_trigger_cooldown_sec: float
    started_at: float
    version: str
    last_trigger_ts: Optional[float] = None
    trigger_lock: Lock = field(default_factory=Lock)

    def register_trigger(self, now_ts: float) -> None:
        self.last_trigger_ts = now_ts

    def within_cooldown(self, now_ts: float) -> bool:
        if self.last_trigger_ts is None:
            return False
        return (now_ts - self.last_trigger_ts) < self.pipeline_trigger_cooldown_sec
