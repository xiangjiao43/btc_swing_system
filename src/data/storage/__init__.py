"""
src.data.storage — SQLite 存储层公共 API。

对应建模 §8.5 / §10.4。
"""

from .connection import get_connection, get_db_path, init_db
from .dao import (
    # Row dataclasses
    KlineRow,
    DerivativeMetric,
    OnchainMetric,
    MacroMetric,
    EventRow,
    # DAOs
    BTCKlinesDAO,
    DerivativesDAO,
    OnchainDAO,
    MacroDAO,
    EventsCalendarDAO,
    StrategyStateDAO,
    ReviewReportsDAO,
    FallbackLogDAO,
    RunMetadataDAO,
    # Type aliases
    TimeFrame,
    OnchainSource,
    MacroSource,
    FallbackLevel,
    RunStatus,
    EventTimezone,
)

__all__ = [
    # Connection
    "get_connection",
    "get_db_path",
    "init_db",
    # Row dataclasses
    "KlineRow",
    "DerivativeMetric",
    "OnchainMetric",
    "MacroMetric",
    "EventRow",
    # DAOs
    "BTCKlinesDAO",
    "DerivativesDAO",
    "OnchainDAO",
    "MacroDAO",
    "EventsCalendarDAO",
    "StrategyStateDAO",
    "ReviewReportsDAO",
    "FallbackLogDAO",
    "RunMetadataDAO",
    # Type aliases
    "TimeFrame",
    "OnchainSource",
    "MacroSource",
    "FallbackLevel",
    "RunStatus",
    "EventTimezone",
]
