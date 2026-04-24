"""
metrics.py — KPI 类别与 stage 名单(Sprint 1.16a)

集中列出 KPICollector 输出的 6 大类;stage 名单与 state_builder._STAGES 一致。
"""

from __future__ import annotations


KPI_CATEGORIES: tuple[str, ...] = (
    "execution",
    "stage_success",
    "state_distribution",
    "decision",
    "data_quality",
    "fallback",
)


PIPELINE_STAGES: tuple[str, ...] = (
    "cold_start_check",
    "cycle_position_last_stable_lookup",
    "composite.truth_trend",
    "composite.band_position",
    "composite.cycle_position",
    "composite.crowding",
    "composite.macro_headwind",
    "layer_1",
    "composite.event_risk",
    "layer_2",
    "layer_3",
    "layer_4",
    "layer_5",
    "ai_summary",
    "adjudicator",
    "lifecycle_fsm",
    "state_machine",
    "persist_state",
)


STATE_MACHINE_STATES: tuple[str, ...] = (
    "cold_start_warming_up",
    "degraded_data_mode",
    "stop_triggered",
    "chaos_pause",
    "macro_shock_pause",
    "event_window_freeze",
    "post_execution_cooldown",
    "active_long_execution",
    "active_short_execution",
    "long_protective_hold",
    "short_protective_hold",
    "disciplined_bull_watch",
    "disciplined_bear_watch",
    "neutral_observation",
)


LIFECYCLE_STATES: tuple[str, ...] = (
    "FLAT",
    "LONG_PLANNED", "LONG_OPEN", "LONG_SCALING", "LONG_REDUCING", "LONG_CLOSED",
    "SHORT_PLANNED", "SHORT_OPEN", "SHORT_SCALING", "SHORT_REDUCING", "SHORT_CLOSED",
    "STOP_TRIGGERED", "COOLDOWN", "FLAT_AFTER_STOP",
)


ADJUDICATOR_ACTIONS: tuple[str, ...] = (
    "open_long", "open_short",
    "scale_in_long", "scale_in_short",
    "reduce_long", "reduce_short",
    "close_long", "close_short",
    "hold", "watch", "pause",
)


DEFAULT_COLD_START_THRESHOLD: int = 42
