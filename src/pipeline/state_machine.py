"""
state_machine.py — Sprint 1.13 系统状态分类器(14 档)

职责:
  * 读取 config/state_machine.yaml 的 transition_priority 和各状态 enter_conditions
  * 每 tick 独立求值,按优先级第一个满足全部条件的状态 = current_state
  * neutral_observation 兜底永远 match

这不是交易生命周期 FSM(那个在 config/lifecycle_fsm.yaml,Sprint 1.15+ 的
src/strategy/ 模块处理)。这里只是"系统此刻应该进入哪一档运行状态"。

DSL 操作符(后缀):
  _eq       相等(bool / str / num)
  _in       值 ∈ 列表
  _gt _gte  数值 >  / >=
  _lt _lte  数值 <  / <=

字段取值层级:
  1. 顶层 shortcut:strategy_state['cold_start'] / ['layer_1'] / ...
  2. Sprint 1.12 嵌套:strategy_state['evidence_reports']['layer_1'] / ...
  3. 其他派生字段(stages_failed_count / minutes_since_* / previous_state / ...)
     在 _FIELD_EXTRACTORS 里显式定义。

值为 None / 字段缺失 → 条件评估 False(保守)。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

import yaml


logger = logging.getLogger(__name__)


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH: Path = _PROJECT_ROOT / "config" / "state_machine.yaml"


# ============================================================
# 字段提取:从 strategy_state + account_state 抽出各个条件需要的量
# ============================================================

def _get_evidence(state: dict[str, Any], key: str) -> dict[str, Any]:
    """优先顶层 state[key],没有则 state['evidence_reports'][key]。"""
    if isinstance(state.get(key), dict):
        return state[key]
    er = state.get("evidence_reports") or {}
    if isinstance(er.get(key), dict):
        return er[key]
    return {}


def _get_composite(state: dict[str, Any], key: str) -> dict[str, Any]:
    c = state.get("composite_factors") or {}
    if isinstance(c.get(key), dict):
        return c[key]
    return {}


def _event_risk_level(state: dict[str, Any]) -> Optional[str]:
    """
    event_risk 实际输出字段是 `band` ∈ {low, medium, high}。
    YAML 里 event_risk_level_in: [high] 就按 band 映射。
    """
    er = _get_composite(state, "event_risk")
    return er.get("event_risk_level") or er.get("band")


def _event_hours_ahead(state: dict[str, Any]) -> Optional[float]:
    """取 event_risk.contributing_events 里 hours_to 最小的(最近一个事件)。"""
    er = _get_composite(state, "event_risk")
    events = er.get("contributing_events") or []
    hours = [e.get("hours_to") for e in events if e.get("hours_to") is not None]
    if not hours:
        return None
    try:
        return float(min(h for h in hours if h >= 0))
    except ValueError:
        return None


def _nearest_event_name(state: dict[str, Any]) -> Optional[str]:
    er = _get_composite(state, "event_risk")
    events = er.get("contributing_events") or []
    candidates = [e for e in events if e.get("hours_to") is not None
                  and e.get("hours_to") >= 0]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda e: e["hours_to"])
    return nearest.get("name") or nearest.get("type")


def _stages_failed_count(state: dict[str, Any]) -> int:
    meta = state.get("pipeline_meta") or state.get("meta") or {}
    failed = meta.get("failures")
    if failed is None:
        failed = meta.get("stages_failed") or []
    return len(failed)


def _cold_start_warming(state: dict[str, Any]) -> bool:
    cs = state.get("cold_start") or {}
    return bool(cs.get("warming_up", False))


def _cold_start_runs(state: dict[str, Any]) -> int:
    cs = state.get("cold_start") or {}
    return int(cs.get("runs_completed", 0))


def _cold_start_threshold(state: dict[str, Any]) -> int:
    cs = state.get("cold_start") or {}
    return int(cs.get("threshold", 42))


def _l5_correlation_coef(l5: dict[str, Any]) -> Optional[float]:
    """
    容错:支持 float 直值(当前 L5 输出) 或 {coefficient: ...} dict。
    """
    v = l5.get("btc_nasdaq_correlation")
    if isinstance(v, dict):
        v = v.get("coefficient") or v.get("value")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ============================================================
# StateMachine
# ============================================================

class StateMachine:
    """
    读取 YAML,对 strategy_state 做状态分类。
    详见模块 docstring。
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        *,
        active_execution_states: tuple[str, ...] = (
            "active_long_execution", "active_short_execution",
        ),
        history_dao_cls: Any = None,  # 测试注入用;默认动态 import
    ) -> None:
        self.config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self.config = _load_yaml(self.config_path)
        self.priority: list[str] = list(self.config.get("transition_priority") or [])
        self.states_config: dict[str, Any] = dict(self.config.get("states") or {})
        self._active_states = active_execution_states
        # 避免循环 import;默认从 DAO 模块查 state history
        if history_dao_cls is None:
            from ..data.storage.dao import StrategyStateDAO
            self._StateDAO = StrategyStateDAO
        else:
            self._StateDAO = history_dao_cls

        # 校验:所有 priority 里出现的 state 必须在 states 里有配置
        missing = [s for s in self.priority if s not in self.states_config]
        if missing:
            raise ValueError(
                f"state_machine.yaml: priority 含 {missing} 但 states 里没有定义"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def determine_state(
        self,
        strategy_state: dict[str, Any],
        *,
        previous_record: Optional[dict[str, Any]] = None,
        account_state: Optional[dict[str, Any]] = None,
        conn: Any = None,
    ) -> dict[str, Any]:
        """
        Args:
            strategy_state:    本轮 pipeline 已填好的 state(含 L1-L5、cold_start、meta 等)
            previous_record:   上一条 strategy_state_history 行(含 state.state_machine)
            account_state:     账户状态 dict。支持 long_position_size / short_position_size / stop_triggered
            conn:              SQLite 连接;post_execution_cooldown 需要反查最近 active_*

        Returns:
            {
              previous_state: str | None,
              current_state: str,
              transition_reason: str,
              transition_evidence: {
                matched_conditions: list[str],
                evaluated_order: list[str],
                state_entered: str,
                fields_snapshot: dict,
              },
              stable_in_state: bool,
              minutes_since_previous_transition: float | None,
              state_entered_at_utc: str,
            }
        """
        previous_state = _previous_state_from_record(previous_record)
        ref_now = _ref_timestamp(strategy_state)
        mins_since_prev = _minutes_between(
            _ref_timestamp(previous_record) if previous_record else None,
            ref_now,
        )
        mins_since_active = self._minutes_since_last_active(
            conn=conn,
            now_utc=ref_now,
        )

        # 构造完整字段快照(日志 + 模板填充 + 条件求值共用)
        fields = _extract_fields(
            strategy_state=strategy_state,
            account_state=account_state,
            previous_state=previous_state,
            minutes_since_previous_transition=mins_since_prev,
            minutes_since_last_active_execution=mins_since_active,
        )

        evaluated_order: list[str] = []
        for state_name in self.priority:
            evaluated_order.append(state_name)
            conds = (self.states_config[state_name].get("enter_conditions") or [])
            matched, matched_list = _eval_conditions(conds, fields)
            if matched:
                reason_tpl = self.states_config[state_name].get(
                    "transition_reason_template", state_name
                )
                reason = _safe_format(reason_tpl, fields)
                # previous_state_entered_at:如果 current == previous,沿用原时间;否则新时间
                if previous_state == state_name and previous_record is not None:
                    state_entered_at = (
                        ((previous_record.get("state") or {}).get("state_machine") or {})
                        .get("state_entered_at_utc") or ref_now
                    )
                else:
                    state_entered_at = ref_now

                return {
                    "previous_state": previous_state,
                    "current_state": state_name,
                    "transition_reason": reason,
                    "transition_evidence": {
                        "matched_conditions": matched_list,
                        "evaluated_order": evaluated_order,
                        "state_entered": state_name,
                        "fields_snapshot": _snapshot_for_log(fields),
                    },
                    "stable_in_state": previous_state == state_name,
                    "minutes_since_previous_transition": mins_since_prev,
                    "state_entered_at_utc": state_entered_at,
                }

        # 理论上不会到这里(neutral_observation 兜底),但留一个安全返回
        return {
            "previous_state": previous_state,
            "current_state": "neutral_observation",
            "transition_reason": "fallback: no state matched (config error)",
            "transition_evidence": {
                "matched_conditions": [],
                "evaluated_order": evaluated_order,
                "state_entered": "neutral_observation",
                "fields_snapshot": _snapshot_for_log(fields),
            },
            "stable_in_state": previous_state == "neutral_observation",
            "minutes_since_previous_transition": mins_since_prev,
            "state_entered_at_utc": ref_now,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _minutes_since_last_active(
        self,
        *,
        conn: Any,
        now_utc: Optional[str],
    ) -> Optional[float]:
        """反查最近一条 active_*_execution 记录,返回到 now_utc 的分钟数。"""
        if conn is None or now_utc is None:
            return None
        try:
            row = self._StateDAO.get_latest_with_state_in(
                conn, list(self._active_states)
            )
        except Exception as e:
            logger.warning("get_latest_with_state_in failed: %s", e)
            return None
        if row is None:
            return None
        prev_ref = row.get("run_timestamp_utc") or _ref_timestamp(row)
        return _minutes_between(prev_ref, now_utc)


# ============================================================
# 字段抽取
# ============================================================

# 以 (name, extractor) 形式声明,避免在 eval 时写一堆 if/else
_FIELD_EXTRACTORS: dict[str, Callable[[dict, dict], Any]] = {
    # cold_start
    "cold_start_warming_up": lambda s, a: _cold_start_warming(s),
    "runs_completed": lambda s, a: _cold_start_runs(s),
    "threshold": lambda s, a: _cold_start_threshold(s),

    # L1
    "l1_regime": lambda s, a: (
        _get_evidence(s, "layer_1").get("regime")
        or _get_evidence(s, "layer_1").get("regime_primary")
    ),
    "volatility_regime": lambda s, a: (
        _get_evidence(s, "layer_1").get("volatility_regime")
        or _get_evidence(s, "layer_1").get("volatility_level")
    ),

    # L2
    "l2_stance": lambda s, a: _get_evidence(s, "layer_2").get("stance"),

    # L3
    "l3_grade": lambda s, a: (
        _get_evidence(s, "layer_3").get("opportunity_grade")
        or _get_evidence(s, "layer_3").get("grade")
    ),
    "l3_execution_permission": lambda s, a: (
        _get_evidence(s, "layer_3").get("execution_permission")
    ),

    # L4
    "l4_position_cap": lambda s, a: _get_evidence(s, "layer_4").get("position_cap"),

    # L5
    "l5_macro_headwind": lambda s, a: (
        _get_evidence(s, "layer_5").get("macro_headwind_vs_btc")
    ),
    "l5_macro_environment": lambda s, a: (
        _get_evidence(s, "layer_5").get("macro_environment")
    ),
    "btc_nasdaq_correlation": lambda s, a: (
        _l5_correlation_coef(_get_evidence(s, "layer_5"))
    ),

    # event_risk
    "event_risk_level": lambda s, a: _event_risk_level(s),
    "event_hours_ahead": lambda s, a: _event_hours_ahead(s),
    "nearest_event_name": lambda s, a: _nearest_event_name(s),

    # meta
    "stages_failed_count": lambda s, a: _stages_failed_count(s),

    # account
    "account_has_long_position": lambda s, a: bool(
        (a or {}).get("long_position_size", 0) > 0
    ),
    "account_has_short_position": lambda s, a: bool(
        (a or {}).get("short_position_size", 0) > 0
    ),
    "account_stop_triggered": lambda s, a: bool(
        (a or {}).get("stop_triggered", False)
    ),
}


def _extract_fields(
    *,
    strategy_state: dict[str, Any],
    account_state: Optional[dict[str, Any]],
    previous_state: Optional[str],
    minutes_since_previous_transition: Optional[float],
    minutes_since_last_active_execution: Optional[float],
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name, fn in _FIELD_EXTRACTORS.items():
        try:
            fields[name] = fn(strategy_state, account_state or {})
        except Exception as e:
            logger.warning("field extractor %s failed: %s", name, e)
            fields[name] = None
    fields["previous_state"] = previous_state
    fields["minutes_since_previous_transition"] = minutes_since_previous_transition
    fields["minutes_since_last_active_execution"] = minutes_since_last_active_execution
    return fields


# ============================================================
# 条件求值 DSL
# ============================================================

_OP_SUFFIXES: tuple[str, ...] = (
    "_gte", "_lte", "_gt", "_lt", "_in", "_eq",
)


def _split_field_op(condition_key: str) -> Optional[tuple[str, str]]:
    """'l3_grade_in' → ('l3_grade', 'in')。找不到返回 None。"""
    for suf in _OP_SUFFIXES:
        if condition_key.endswith(suf):
            return condition_key[: -len(suf)], suf[1:]
    return None


def _eval_single(field_value: Any, op: str, expected: Any) -> bool:
    """单条件求值。field_value is None → False(保守)。"""
    if op in ("eq", "in"):
        if op == "eq":
            return field_value == expected
        if not isinstance(expected, (list, tuple, set)):
            return False
        return field_value in expected
    # 数值运算:None → False
    if field_value is None:
        return False
    try:
        fv = float(field_value)
        ev = float(expected)
    except (TypeError, ValueError):
        return False
    if op == "gt":
        return fv > ev
    if op == "gte":
        return fv >= ev
    if op == "lt":
        return fv < ev
    if op == "lte":
        return fv <= ev
    return False


def _eval_conditions(
    conditions: list[dict[str, Any]],
    fields: dict[str, Any],
) -> tuple[bool, list[str]]:
    """
    conditions 是 list of 单键 dict,AND 语义。空 list → 永远 True(neutral 兜底)。
    """
    if not conditions:
        return True, ["__always_true__"]
    matched: list[str] = []
    for cond in conditions:
        if not isinstance(cond, dict) or len(cond) != 1:
            logger.warning("skipping malformed condition: %r", cond)
            return False, matched
        (key, expected), = cond.items()
        parsed = _split_field_op(key)
        if parsed is None:
            logger.warning("unknown operator suffix in %r", key)
            return False, matched
        field_name, op = parsed
        fv = fields.get(field_name)
        ok = _eval_single(fv, op, expected)
        if not ok:
            return False, matched
        matched.append(f"{field_name} {op} {expected!r} (actual={fv!r})")
    return True, matched


# ============================================================
# Template / timestamp helpers
# ============================================================

def _safe_format(template: str, fields: dict[str, Any]) -> str:
    """用 dict 做字符串占位替换;缺字段的占位替换为 '?'。"""
    class _SafeDict(dict):
        def __missing__(self, key):
            return "?"
    # format_map 接受任何 Mapping
    try:
        return template.format_map(_SafeDict(fields))
    except Exception as e:
        logger.warning("format template failed (%r): %s", template, e)
        return template


def _ref_timestamp(record: Optional[dict[str, Any]]) -> Optional[str]:
    if not record:
        return None
    # DAO 返回的 row 有顶层 run_timestamp_utc
    ts = record.get("run_timestamp_utc")
    if ts:
        return ts
    state = record.get("state")
    if isinstance(state, dict):
        return state.get("reference_timestamp_utc")
    # 直接是 state
    return record.get("reference_timestamp_utc")


def _previous_state_from_record(
    record: Optional[dict[str, Any]],
) -> Optional[str]:
    if not record:
        return None
    state = record.get("state") if isinstance(record.get("state"), dict) else record
    sm = (state or {}).get("state_machine") or {}
    return sm.get("current_state")


def _minutes_between(a_iso: Optional[str], b_iso: Optional[str]) -> Optional[float]:
    if not a_iso or not b_iso:
        return None
    try:
        a = _parse_iso(a_iso)
        b = _parse_iso(b_iso)
    except Exception:
        return None
    return (b - a).total_seconds() / 60.0


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _snapshot_for_log(fields: dict[str, Any]) -> dict[str, Any]:
    """只留标量 + 短字符串,避免巨大 JSON 混入。"""
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if v is None or isinstance(v, (bool, int, float)):
            out[k] = v
        elif isinstance(v, str) and len(v) <= 80:
            out[k] = v
    return out


# ============================================================
# YAML loader
# ============================================================

@lru_cache(maxsize=8)
def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
