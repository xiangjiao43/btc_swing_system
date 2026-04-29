"""
state_builder.py — Sprint 1.12

把原始数据(klines / derivatives / onchain / macro / events)经过:
    composite_factors (5) → L1 → composite.event_risk (需 L1) →
    L2 → L3 → L4 → L5 → AI summary → persist

编排成一个 BtcStrategyState dict 并写入 strategy_state_history。

核心契约:
  * 单阶段失败**不抛异常**,用 FallbackLogDAO 记 level_1,其余阶段继续。
  * 返回 BuildResult(state, run_id, failures, ...)给调用方处理。
  * 冷启动由 base.yaml → cold_start.warming_up_runs(默认 42)决定:
      StrategyStateDAO.get_count() < 阈值 → warming_up=True,注入 context。
  * CyclePosition 的 last_stable 通过 context['cycle_position_last_stable']
    预注入,避免 factor 内部再调 DAO。

State Machine、review_reports、scheduler 均不在本 sprint。
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from ..ai.adjudicator import AIAdjudicator
from ..ai.summary import call_ai_summary
from ..composite import (
    BandPositionFactor,
    CrowdingFactor,
    CyclePositionFactor,
    EventRiskFactor,
    MacroHeadwindFactor,
    TruthTrendFactor,
)
from ..data.storage.dao import (
    BTCKlinesDAO,
    DerivativesDAO,
    EventsCalendarDAO,
    FallbackLogDAO,
    MacroDAO,
    OnchainDAO,
    RunMetadataDAO,
    StrategyStateDAO,
)
from ..evidence import (
    Layer1Regime,
    Layer2Direction,
    Layer3Opportunity,
    Layer4Risk,
    Layer5Macro,
)


logger = logging.getLogger(__name__)


DEFAULT_RULES_VERSION: str = "v1.2.0"

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_BASE_YAML: Path = _PROJECT_ROOT / "config" / "base.yaml"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _derive_market_snapshot(klines_1d: Any) -> dict[str, Any]:
    """Sprint 2.2 hotfix:从 1D K 线派生 market_snapshot。

    用 context.klines_1d(BTCKlinesDAO.get_recent_as_df 已按 open_time_utc
    升序返回的 DataFrame,close 字段是当日收盘价)。
    冷启动/数据缺失 → btc_price_usd=null + status='missing'。
    """
    from zoneinfo import ZoneInfo
    _BJT = ZoneInfo("Asia/Shanghai")

    empty = {
        "btc_price_usd": None,
        "btc_price_change_24h_pct": None,
        "btc_price_change_7d_pct": None,
        "btc_price_updated_bjt": None,
        "price_captured_at_utc": None,
        "price_source": "binance_kline_1d_close_via_coinglass",
        "status": "missing",
    }
    try:
        import pandas as pd
    except Exception:
        return empty
    if klines_1d is None or not isinstance(klines_1d, pd.DataFrame) or klines_1d.empty:
        return empty

    try:
        closes = klines_1d["close"].dropna().astype(float)
        if closes.empty:
            return empty
        current = float(closes.iloc[-1])

        change_24h = None
        if len(closes) >= 2:
            prev = float(closes.iloc[-2])
            if prev > 0:
                change_24h = (current / prev - 1.0) * 100.0

        change_7d = None
        if len(closes) >= 8:
            seven_ago = float(closes.iloc[-8])
            if seven_ago > 0:
                change_7d = (current / seven_ago - 1.0) * 100.0

        ts_utc = klines_1d.index[-1]
        try:
            iso_utc = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            bjt = ts_utc.tz_convert(_BJT).strftime("%Y-%m-%d %H:%M (BJT)")
        except Exception:
            iso_utc = None
            bjt = None

        return {
            "btc_price_usd": round(current, 2),
            "btc_price_change_24h_pct": (
                round(change_24h, 2) if change_24h is not None else None
            ),
            "btc_price_change_7d_pct": (
                round(change_7d, 2) if change_7d is not None else None
            ),
            "btc_price_updated_bjt": bjt,
            "price_captured_at_utc": iso_utc,
            "price_source": "binance_kline_1d_close_via_coinglass",
            "status": "ok",
        }
    except Exception:
        return empty


def _load_base_cfg() -> dict[str, Any]:
    try:
        with open(_BASE_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


@dataclass(slots=True)
class BuildResult:
    """Pipeline 一次跑完的结果。"""
    run_id: str
    run_timestamp_utc: str
    state: dict[str, Any]
    failures: list[dict[str, Any]] = field(default_factory=list)
    degraded_stages: list[str] = field(default_factory=list)
    ai_status: str = "unknown"
    persisted: bool = False
    duration_ms: int = 0


# ==================================================================
# StrategyStateBuilder
# ==================================================================

class StrategyStateBuilder:
    """
    五层 + 六因子 + AI summary 的调度器。

    用法:
        builder = StrategyStateBuilder(conn)
        result = builder.run(run_trigger="scheduled")
        # 或者:
        result = builder.build(context, run_trigger="manual", persist=False)

    context 由 `_assemble_context(conn)` 自动从 DB 拼装;想单测时可手工注入。
    """

    _STAGES: tuple[str, ...] = (
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
        "observation_classifier",
        "ai_summary",
        "factor_cards",
        "adjudicator",
        "state_machine",
        "persist_state",
    )

    def __init__(
        self,
        conn: Optional[sqlite3.Connection] = None,
        *,
        rules_version: str = DEFAULT_RULES_VERSION,
        ai_caller: Optional[Callable[..., dict[str, Any]]] = None,
        openai_client: Any = None,
        klines_lookback: int = 600,
        macro_lookback_days: int = 365,
        events_window_hours: float = 72.0,
        state_machine: Any = None,
        adjudicator: Any = None,
        account_state_provider: Optional[Callable[[], dict[str, Any]]] = None,
        preflight_retry_after_sec: float = 300.0,
        preflight_sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        """
        Args:
            conn:               sqlite3.Connection(None = 仅在 build() 调用时不持久化)
            rules_version:      写入每条 EvidenceReport 和 StrategyState(M36)
            ai_caller:          覆盖默认的 call_ai_summary(测试注入)
            openai_client:      传给 call_ai_summary(mock 用)
            klines_lookback:    取多少根 K 线
            macro_lookback_days: MacroDAO.get_all_metrics 的 lookback
            events_window_hours: 事件窗口(默认 72h,和 event_risk 对齐)
            preflight_retry_after_sec: Sprint 2.7-C pre-flight 重试间隔(默认 300s);
                                       测试可传 0 立即重试(配合 sleep_fn=lambda s: None)
            preflight_sleep_fn: 注入的 sleep 函数(默认 time.sleep);测试可传
                                lambda s: None 跳过等待
        """
        self.conn = conn
        self.rules_version = rules_version
        self._ai_caller = ai_caller or call_ai_summary
        self._openai_client = openai_client
        self.klines_lookback = klines_lookback
        self.macro_lookback_days = macro_lookback_days
        self.events_window_hours = events_window_hours
        self._account_state_provider = account_state_provider
        self._preflight_retry_after_sec = preflight_retry_after_sec
        self._preflight_sleep_fn = preflight_sleep_fn or time.sleep
        # 延迟 import 避免循环依赖
        if state_machine is None:
            from ..strategy.state_machine import StateMachine
            self._state_machine = StateMachine()
        else:
            self._state_machine = state_machine

        if adjudicator is None:
            self._adjudicator = AIAdjudicator(
                openai_client=self._openai_client,
                rules_version=self.rules_version,
            )
        else:
            self._adjudicator = adjudicator

        self._base_cfg = _load_base_cfg()

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        run_trigger: str = "scheduled",
        persist: bool = True,
        now_utc: Optional[str] = None,
    ) -> BuildResult:
        """
        从 self.conn 拼 context,一路跑完并写库。conn=None 时 raise。
        """
        if self.conn is None:
            raise ValueError("run() requires a sqlite3 Connection; "
                             "pass one via __init__ or use build()")
        context = self._assemble_context(self.conn, now_utc=now_utc)
        return self.build(
            context=context,
            run_trigger=run_trigger,
            persist=persist,
        )

    def build(
        self,
        context: dict[str, Any],
        *,
        run_trigger: str = "scheduled",
        persist: bool = True,
    ) -> BuildResult:
        """
        用传入的 context 运行 pipeline(可不带 DB)。

        任一阶段异常只会被记录到 failures,不会抛出;直到 persist_state 也
        失败时,BuildResult.persisted=False 但 state 仍然返回。
        """
        start_ts = time.time()
        run_id = str(uuid.uuid4())
        run_ts_utc = (
            context.get("reference_timestamp_utc")
            or _utc_now_iso()
        )
        # 保证 reference_timestamp_utc 一路通到下游
        context.setdefault("reference_timestamp_utc", run_ts_utc)
        context.setdefault("run_trigger", run_trigger)

        failures: list[dict[str, Any]] = []
        degraded_stages: list[str] = []

        # 是否在 run_metadata 起一条 started 记录(conn 可用时)
        if persist and self.conn is not None:
            self._safe(
                lambda: RunMetadataDAO.start_run(
                    self.conn, run_id=run_id,
                    run_timestamp_utc=run_ts_utc,
                    run_trigger=run_trigger,
                ),
                stage="run_metadata.start", failures=failures,
                degraded_stages=degraded_stages, run_ts_utc=run_ts_utc,
            )

        # === Stage 0(Sprint 2.7-C):pre-flight 数据就绪检查 ===
        # 根据 run_trigger 选择阈值表(scheduled / scheduled_8h_onchain),
        # 失败 → sleep 5 min 重试一次 → 仍失败 → 写 degraded_stages 但不阻塞。
        if persist and self.conn is not None:
            try:
                degraded_groups, refreshed_inserted_at = (
                    _run_pre_flight_freshness_check(
                        self.conn,
                        context.get("metric_inserted_at") or {},
                        run_trigger,
                        retry_after_sec=self._preflight_retry_after_sec,
                        sleep_fn=self._preflight_sleep_fn,
                    )
                )
                # 用刷新过的 inserted_at 替换(让 emitter / 后续阶段拿到最新)
                if refreshed_inserted_at is not context.get("metric_inserted_at"):
                    context["metric_inserted_at"] = refreshed_inserted_at
                for g in degraded_groups:
                    degraded_stages.append(f"pre_flight.{g}")
            except Exception as e:
                logger.warning("pre_flight stage exception: %s", e)
                degraded_stages.append("pre_flight.exception")

        # === Stage 1: cold_start 判定 ===
        cold_start_info = self._run_stage(
            "cold_start_check", failures, degraded_stages, run_ts_utc,
            lambda: self._determine_cold_start(context),
            default={"warming_up": False, "runs_completed": 0,
                     "threshold": 42, "reason": "cold_start_check failed"},
        )
        context["cold_start"] = cold_start_info

        # === Stage 2: cycle_position last_stable 预查 ===
        last_stable = self._run_stage(
            "cycle_position_last_stable_lookup",
            failures, degraded_stages, run_ts_utc,
            lambda: self._lookup_last_stable_cycle(context),
            default=None,
        )
        context["cycle_position_last_stable"] = last_stable

        # === Stage 3-7: 5 个 composite(event_risk 除外)===
        composite_factors: dict[str, Any] = {}
        composite_factors["truth_trend"] = self._run_stage(
            "composite.truth_trend", failures, degraded_stages, run_ts_utc,
            lambda: TruthTrendFactor().compute(context),
            default=_factor_degraded("truth_trend"),
        )
        composite_factors["band_position"] = self._run_stage(
            "composite.band_position", failures, degraded_stages, run_ts_utc,
            lambda: BandPositionFactor().compute(context),
            default=_factor_degraded("band_position"),
        )
        composite_factors["cycle_position"] = self._run_stage(
            "composite.cycle_position", failures, degraded_stages, run_ts_utc,
            lambda: CyclePositionFactor().compute(context),
            default=_factor_degraded("cycle_position"),
        )
        composite_factors["crowding"] = self._run_stage(
            "composite.crowding", failures, degraded_stages, run_ts_utc,
            lambda: CrowdingFactor().compute(context),
            default=_factor_degraded("crowding"),
        )
        composite_factors["macro_headwind"] = self._run_stage(
            "composite.macro_headwind", failures, degraded_stages, run_ts_utc,
            lambda: MacroHeadwindFactor().compute(context),
            default=_factor_degraded("macro_headwind"),
        )

        # === Stage 8: L1 Regime ===
        context["composite_factors"] = composite_factors
        layer_1_output = self._run_stage(
            "layer_1", failures, degraded_stages, run_ts_utc,
            lambda: Layer1Regime().compute(context, self.rules_version),
            default=_layer_error_report(1, "regime", "Layer1 failed"),
        )
        context["layer_1_output"] = layer_1_output

        # === Stage 9: event_risk(需 L1.volatility_regime 和 macro_headwind 相关性)===
        context["is_volatility_extreme"] = (
            (layer_1_output.get("volatility_regime")
             or layer_1_output.get("volatility_level")) == "extreme"
        )
        context["btc_nasdaq_correlated"] = bool(
            (composite_factors.get("macro_headwind") or {}).get(
                "correlation_amplified", False
            )
        )
        composite_factors["event_risk"] = self._run_stage(
            "composite.event_risk", failures, degraded_stages, run_ts_utc,
            lambda: EventRiskFactor().compute(context),
            default=_factor_degraded("event_risk"),
        )
        context["composite_factors"] = composite_factors  # event_risk 已就位

        # === Stage 10: L2 ===
        layer_2_output = self._run_stage(
            "layer_2", failures, degraded_stages, run_ts_utc,
            lambda: Layer2Direction().compute(context, self.rules_version),
            default=_layer_error_report(2, "direction", "Layer2 failed"),
        )
        context["layer_2_output"] = layer_2_output

        # === Stage 11: L3 ===
        layer_3_output = self._run_stage(
            "layer_3", failures, degraded_stages, run_ts_utc,
            lambda: Layer3Opportunity().compute(context, self.rules_version),
            default=_layer_error_report(3, "opportunity", "Layer3 failed"),
        )
        context["layer_3_output"] = layer_3_output

        # === Stage 12: L4 ===
        # Sprint 1.5c C1:把上一次运行的 state_machine.current_state 作为"前一次态"
        # 传给 L4,用于 A 级缓冲 PROTECTION 例外判定(L4 在 state_machine 之前跑,
        # 读不到本次的 current_state;用前一次态近似)。
        context["previous_state_machine_state"] = self._read_previous_state_machine_state()
        layer_4_output = self._run_stage(
            "layer_4", failures, degraded_stages, run_ts_utc,
            lambda: Layer4Risk().compute(context, self.rules_version),
            default=_layer_error_report(4, "risk", "Layer4 failed"),
        )
        context["layer_4_output"] = layer_4_output

        # === Stage 13: L5 ===
        layer_5_output = self._run_stage(
            "layer_5", failures, degraded_stages, run_ts_utc,
            lambda: Layer5Macro().compute(context, self.rules_version),
            default=_layer_error_report(5, "macro", "Layer5 failed"),
        )
        context["layer_5_output"] = layer_5_output

        # === Stage 13b(Sprint 2.6-E):L5 AI loopback to L4 position_cap ===
        # §6.8 / §4.5.5 / §4.5.6:L4 先于 L5 跑,所以 L4 用的是 composite 规则分。
        # L5 AI(若启用且成功)给出更精准的 macro_headwind_score + adjustment_guidance
        # → 回写 L4 position_cap step 4 + permission(tighten/loosen)。
        # AI 未启用 / 失败 → 原样返回。
        try:
            from ..evidence.layer4_risk import apply_l5_ai_loopback
            layer_4_output = apply_l5_ai_loopback(
                layer_4_output, layer_5_output,
            )
            context["layer_4_output"] = layer_4_output
        except Exception as e:
            logger.warning("L5 AI loopback to L4 failed (non-fatal): %s", e)

        # === Stage: Observation Classifier(建模 §4.7,在 L3 之后 / 裁决之前)===
        # 先拼一个半成品 state 供 classifier 读取,真实 state 在后面 _assemble_state
        _pre_state_for_observation = {
            "evidence_reports": {
                "layer_1": layer_1_output,
                "layer_2": layer_2_output,
                "layer_3": layer_3_output,
                "layer_4": layer_4_output,
                "layer_5": layer_5_output,
            },
            "composite_factors": composite_factors,
            "cold_start": context.get("cold_start") or {},
            # state_machine 还没算,先空着;classifier 读 None 归位 watchful 路径
            "state_machine": {},
        }
        observation_result = self._run_stage(
            "observation_classifier", failures, degraded_stages, run_ts_utc,
            lambda: self._run_observation_classifier(_pre_state_for_observation),
            default=_observation_fallback(run_ts_utc),
        )
        context["observation_output"] = observation_result

        # === Stage 14: AI summary ===
        ai_input = {
            "layer_1": layer_1_output, "layer_2": layer_2_output,
            "layer_3": layer_3_output, "layer_4": layer_4_output,
            "layer_5": layer_5_output,
        }
        ai_result = self._run_stage(
            "ai_summary", failures, degraded_stages, run_ts_utc,
            lambda: self._ai_caller(
                ai_input, openai_client=self._openai_client,
            ),
            default={
                "summary_text": None, "model_used": None,
                "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
                "status": "degraded_error", "error": "ai_caller exception",
            },
        )
        # ai_summary 返回 degraded_* 也算"软失败",也要记 FallbackLog(单阶段)
        if ai_result.get("status", "").startswith("degraded"):
            if "ai_summary" not in degraded_stages:
                degraded_stages.append("ai_summary")
            if persist and self.conn is not None:
                self._safe(
                    lambda: FallbackLogDAO.log_with_escalation(
                        self.conn, run_timestamp_utc=run_ts_utc,
                        stage="ai_summary",
                        error=ai_result.get("error") or "ai degraded",
                        fallback_applied="context_summary=None",
                    ),
                    stage="fallback_log.ai_summary", failures=failures,
                    degraded_stages=degraded_stages, run_ts_utc=run_ts_utc,
                )

        # === 组装 state dict(初版:无 adjudicator / lifecycle / state_machine)===
        state = self._assemble_state(
            run_id=run_id,
            run_ts_utc=run_ts_utc,
            run_trigger=run_trigger,
            context=context,
            composite_factors=composite_factors,
            ai_result=ai_result,
            failures=failures,
            degraded_stages=degraded_stages,
        )

        # === Sprint 2.2 Task C:为五层证据注入 plain_reading 人话解读 ===
        try:
            from ..evidence.plain_reading import inject_plain_readings
            inject_plain_readings(state)
        except Exception as e:
            logger.warning("inject_plain_readings failed: %s", e)

        # === Sprint 2.3 Task A:为五层注入 pillars / core_question / downstream_hint ===
        try:
            from ..evidence.pillars import inject_pillars
            inject_pillars(state)
        except Exception as e:
            logger.warning("inject_pillars failed: %s", e)

        # === Sprint 2.3 Task A:为 6 组合因子注入 composition / 规则描述 ===
        try:
            from ..strategy.composite_composition import inject_composite_composition
            inject_composite_composition(state, context)
        except Exception as e:
            logger.warning("inject_composite_composition failed: %s", e)

        # === Stage: Factor Cards(Sprint 2.2 新增,在 adjudicator 之前)===
        # 生成全量数据因子卡;adjudicator 要用 available_card_ids 做 evidence_ref
        # 白名单(§6.4 #4)。
        factor_cards = self._run_stage(
            "factor_cards", failures, degraded_stages, run_ts_utc,
            lambda: self._emit_factor_cards(state, context),
            default=[],
        )
        state["factor_cards"] = factor_cards

        # === Stage: Adjudicator ===
        # Sprint 1.5a:adjudicator 先跑,State Machine 在其后,读取 adjudicator
        # 产出的 trade_plan / thesis_still_valid 等字段(Sprint 1.5b 补齐链路)
        account_state = None
        if self._account_state_provider is not None:
            try:
                account_state = self._account_state_provider()
            except Exception as e:
                logger.warning("account_state_provider failed in adjudicator: %s", e)
        if account_state is not None:
            state["account_state"] = account_state
        adjudicator_result = self._run_stage(
            "adjudicator", failures, degraded_stages, run_ts_utc,
            lambda: self._adjudicator.decide(state),
            default=_adjudicator_fallback("adjudicator stage failed"),
        )
        state["adjudicator"] = adjudicator_result
        # adjudicator 返回 degraded_* 也算软失败
        adj_status = (adjudicator_result or {}).get("status", "")
        if isinstance(adj_status, str) and adj_status.startswith("degraded"):
            if "adjudicator" not in degraded_stages:
                degraded_stages.append("adjudicator")

        # === Stage: State Machine(建模 §5 14 档 —— Sprint 1.5a 对齐)===
        sm_block = self._run_stage(
            "state_machine", failures, degraded_stages, run_ts_utc,
            lambda: self._run_state_machine(state, run_ts_utc, context),
            default=_state_machine_fallback(
                "state_machine stage failed", run_ts_utc,
            ),
        )
        state["state_machine"] = sm_block

        # lifecycle 字段保留占位,Sprint 1.5b 由 lifecycle_manager 写入真实值
        state["lifecycle"] = {
            "current_lifecycle": "pending_lifecycle_manager",
            "managed_by": "sprint_1_5b_pending",
        }

        # === Stage: persist ===
        persisted = False
        if persist and self.conn is not None:
            persisted_val = self._run_stage(
                "persist_state", failures, degraded_stages, run_ts_utc,
                lambda: self._persist_state(
                    self.conn, run_ts_utc=run_ts_utc, run_id=run_id,
                    run_trigger=run_trigger,
                    ai_model=ai_result.get("model_used"),
                    state=state,
                ),
                default=False,
            )
            persisted = bool(persisted_val)

            # 更新 run_metadata 最终状态
            final_status = (
                "completed" if not failures and persisted
                else ("fallback" if persisted else "failed")
            )
            self._safe(
                lambda: RunMetadataDAO.finish_run(
                    self.conn, run_id=run_id, status=final_status,
                    notes=(f"failures={len(failures)}, "
                           f"degraded={len(degraded_stages)}")[:500],
                ),
                stage="run_metadata.finish", failures=failures,
                degraded_stages=degraded_stages, run_ts_utc=run_ts_utc,
            )
            # 提交本次所有写入(DAO 只执行,不 commit)
            try:
                self.conn.commit()
            except Exception as e:
                logger.warning("final commit failed: %s", e)

            # Sprint 2.8-B:pre-flight degraded → 写一条 alerts 行,
            # 让用户能在 /api/system/health 和 show_preflight_alerts.py 里查到。
            try:
                _write_preflight_degraded_alert(
                    self.conn,
                    run_id=run_id,
                    run_ts_utc=run_ts_utc,
                    degraded_stages=degraded_stages,
                    metric_inserted_at=context.get("metric_inserted_at") or {},
                )
            except Exception as e:
                logger.warning("write_preflight_degraded_alert failed: %s", e)

        return BuildResult(
            run_id=run_id,
            run_timestamp_utc=run_ts_utc,
            state=state,
            failures=failures,
            degraded_stages=degraded_stages,
            ai_status=ai_result.get("status", "unknown"),
            persisted=persisted,
            duration_ms=int((time.time() - start_ts) * 1000),
        )

    # ------------------------------------------------------------------
    # Context assembly(从 DB 拼)
    # ------------------------------------------------------------------

    def _assemble_context(
        self,
        conn: sqlite3.Connection,
        *,
        now_utc: Optional[str] = None,
    ) -> dict[str, Any]:
        """从数据库把 klines / derivatives / onchain / macro / events 全部取齐。"""
        klines_1h = BTCKlinesDAO.get_recent_as_df(
            conn, "1h", limit=self.klines_lookback)
        klines_4h = BTCKlinesDAO.get_recent_as_df(
            conn, "4h", limit=self.klines_lookback)
        klines_1d = BTCKlinesDAO.get_recent_as_df(
            conn, "1d", limit=self.klines_lookback)
        klines_1w = BTCKlinesDAO.get_recent_as_df(
            conn, "1w", limit=self.klines_lookback)

        derivatives = DerivativesDAO.get_all_metrics(
            conn, lookback_days=self.macro_lookback_days)
        onchain = OnchainDAO.get_all_metrics(
            conn, lookback_days=self.macro_lookback_days)
        macro = MacroDAO.get_all_metrics(
            conn, lookback_days=self.macro_lookback_days)

        events = EventsCalendarDAO.get_upcoming_within_hours(
            conn, hours=self.events_window_hours, now_utc=now_utc)
        # Sprint 2.6-M B2:不限时间窗口,取每类事件最近的 1 个(供 emitter
        # "下次 X 卡"展示。EventRisk composite 仍用 events_upcoming_48h 的 72h 窗口)
        next_events_by_type = EventsCalendarDAO.get_next_events_by_type(
            conn, event_types=["fomc", "cpi", "nfp"], now_utc=now_utc)

        # Sprint 2.6-J:per-metric 系统侧写入时间(extracted to helper for 2.7-C reuse)
        metric_inserted_at = _query_metric_inserted_at(conn)

        return {
            "reference_timestamp_utc": now_utc or _utc_now_iso(),
            "klines_1h": klines_1h, "klines_4h": klines_4h,
            "klines_1d": klines_1d, "klines_1w": klines_1w,
            "derivatives": derivatives, "onchain": onchain, "macro": macro,
            "events_upcoming_48h": events,
            "next_events_by_type": next_events_by_type,
            # Sprint 2.6-M C2:exchange_momentum_score 给 L2 §B5 修正项用
            # (modeling §3.8 把 ExchangeMomentum 从 composite 降级为 L2 内部
            #  stance_confidence 修正,但 single_factors 此前从未写入)
            "single_factors": _build_single_factors(onchain),
            "metric_inserted_at": metric_inserted_at,
        }

    # ------------------------------------------------------------------
    # Cold start & last_stable
    # ------------------------------------------------------------------

    def _determine_cold_start(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        对比 StrategyStateDAO.get_count() 与 base.yaml → cold_start.warming_up_runs
        (默认 42)。conn 缺失时默认 not warming(单测友好)。
        """
        cs_cfg = (self._base_cfg.get("cold_start") or {})
        threshold = int(cs_cfg.get("warming_up_runs", 42))
        enabled = bool(cs_cfg.get("enabled", True))

        if not enabled:
            return {
                "warming_up": False, "runs_completed": 0,
                "threshold": threshold, "reason": "cold_start.enabled=false",
            }
        if self.conn is None:
            # build() 不带 DB 跑时,直接接受 context 预注入的 cold_start
            existing = context.get("cold_start")
            if isinstance(existing, dict):
                return existing
            return {
                "warming_up": False, "runs_completed": 0,
                "threshold": threshold, "reason": "no_conn_and_no_context_hint",
            }
        runs = int(StrategyStateDAO.get_count(self.conn))
        warming = runs < threshold
        return {
            "warming_up": warming,
            "runs_completed": runs,
            "threshold": threshold,
            "days_elapsed": cs_cfg.get("warming_up_days", 7) if warming else None,
        }

    def _lookup_last_stable_cycle(self, context: dict[str, Any]) -> Optional[str]:
        """预注入的优先,否则查 DB。"""
        hint = context.get("cycle_position_last_stable")
        if hint is not None:
            return hint
        if self.conn is None:
            return None
        return StrategyStateDAO.get_latest_non_unclear_cycle(self.conn)

    # ------------------------------------------------------------------
    # State assembly
    # ------------------------------------------------------------------

    def _assemble_state(
        self,
        *,
        run_id: str,
        run_ts_utc: str,
        run_trigger: str,
        context: dict[str, Any],
        composite_factors: dict[str, Any],
        ai_result: dict[str, Any],
        failures: list[dict[str, Any]],
        degraded_stages: list[str],
    ) -> dict[str, Any]:
        """
        把所有输出聚合成 BtcStrategyState(schemas.yaml §4.8 简化版)。

        Sprint 1.12 只写 Builder 必须保留的字段;State Machine 相关的
        state_key / transition_reason 等留到 1.13。
        """
        cold_start = context.get("cold_start") or {}
        market_snapshot = _derive_market_snapshot(context.get("klines_1d"))
        return {
            # --- identity ---
            "run_id": run_id,
            "reference_timestamp_utc": run_ts_utc,
            "generated_at_utc": _utc_now_iso(),
            "run_trigger": run_trigger,
            "rules_version": self.rules_version,
            "ai_model_actual": ai_result.get("model_used"),

            # --- cold start ---
            "cold_start": cold_start,

            # --- market snapshot(Sprint 2.2 hotfix:真实 BTC 价格从 1D K 线派生)---
            "market_snapshot": market_snapshot,

            # --- evidence 五层 ---
            "evidence_reports": {
                "layer_1": context.get("layer_1_output"),
                "layer_2": context.get("layer_2_output"),
                "layer_3": context.get("layer_3_output"),
                "layer_4": context.get("layer_4_output"),
                "layer_5": context.get("layer_5_output"),
            },

            # --- 组合因子 ---
            "composite_factors": composite_factors,

            # --- AI 摘要 ---
            "context_summary": {
                "summary_text": ai_result.get("summary_text"),
                "status": ai_result.get("status", "unknown"),
                "tokens_in": ai_result.get("tokens_in", 0),
                "tokens_out": ai_result.get("tokens_out", 0),
                "latency_ms": ai_result.get("latency_ms", 0),
                "error": ai_result.get("error"),
            },

            # --- Observation(§4.7,只读,不进决策路径)---
            "observation": context.get("observation_output") or {},

            # --- Pipeline 自省元信息 ---
            "pipeline_meta": {
                "failures": failures,
                "degraded_stages": list(degraded_stages),
                "stages_total": len(self._STAGES),
                "stages_succeeded": (
                    len(self._STAGES) - len(degraded_stages)
                ),
            },

            # --- Sprint 2.2 hotfix:价格缺失时 data_health 标记 missing ---
            "data_health": (
                {"price_status": "missing"}
                if market_snapshot.get("status") == "missing"
                else {"price_status": "ok"}
            ),
        }

    # ------------------------------------------------------------------
    # Stage runner (带 Fallback 日志 + 降级记录)
    # ------------------------------------------------------------------

    def _run_stage(
        self,
        stage: str,
        failures: list[dict[str, Any]],
        degraded_stages: list[str],
        run_ts_utc: str,
        fn: Callable[[], Any],
        default: Any,
    ) -> Any:
        """
        跑一个 stage。异常 → 记 failures + FallbackLog(level_1) + 返回 default。
        """
        try:
            return fn()
        except Exception as e:
            logger.exception("stage %s failed: %s", stage, e)
            failures.append({
                "stage": stage,
                "error_type": type(e).__name__,
                "error_message": str(e)[:300],
            })
            if stage not in degraded_stages:
                degraded_stages.append(stage)
            # 写 fallback_log,带自动升级(自身不能再抛)
            if self.conn is not None:
                try:
                    FallbackLogDAO.log_with_escalation(
                        self.conn, run_timestamp_utc=run_ts_utc,
                        stage=stage, error=e,
                        fallback_applied="stage_default_returned",
                    )
                except Exception as log_err:
                    logger.warning(
                        "fallback_log for stage=%s failed: %s",
                        stage, log_err,
                    )
            return default

    def _safe(
        self,
        fn: Callable[[], Any],
        *,
        stage: str,
        failures: list[dict[str, Any]],
        degraded_stages: list[str],
        run_ts_utc: str,
    ) -> Any:
        """和 _run_stage 同语义,但 default=None,供非 stage 的辅助调用。"""
        return self._run_stage(
            stage, failures, degraded_stages, run_ts_utc, fn, default=None,
        )

    def _persist_state(
        self,
        conn: sqlite3.Connection,
        *,
        run_ts_utc: str,
        run_id: str,
        run_trigger: str,
        ai_model: Optional[str],
        state: dict[str, Any],
    ) -> bool:
        StrategyStateDAO.insert_state(
            conn,
            run_timestamp_utc=run_ts_utc,
            run_id=run_id,
            run_trigger=run_trigger,
            rules_version=self.rules_version,
            ai_model_actual=ai_model,
            state=state,
        )
        return True

    # ------------------------------------------------------------------
    # State Machine stage
    # ------------------------------------------------------------------

    def _emit_factor_cards(
        self,
        state: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Sprint 2.2:从 composite + collectors 产出 factor cards 列表。"""
        from ..strategy.factor_card_emitter import emit_factor_cards
        return emit_factor_cards(state, context)

    def _read_previous_state_machine_state(self) -> str:
        """Sprint 1.5c C1:从 DB 最近一条 strategy_state 读 state_machine.current_state。

        冷启动 / 首次运行 / 失败 → 默认 "FLAT"(建模 §5.1 默认态)。
        """
        if self.conn is None:
            return "FLAT"
        try:
            row = StrategyStateDAO.get_latest_state(self.conn)
            if not row:
                return "FLAT"
            state = row.get("state") or {}
            sm = state.get("state_machine") or {}
            return sm.get("current_state") or "FLAT"
        except Exception as e:
            logger.warning("read previous state_machine failed: %s", e)
            return "FLAT"

    def _run_observation_classifier(
        self,
        pre_state: dict[str, Any],
    ) -> dict[str, Any]:
        """§4.7 Observation Classifier。只读 state 片段 + 可选历史记录。"""
        from ..strategy.observation_classifier import classify
        previous_records: Optional[list[dict[str, Any]]] = None
        if self.conn is not None:
            # 取最近 200 次(覆盖 14 天 warning + 30 天 critical 阈值所需 streak)
            previous_records = StrategyStateDAO.get_recent_states(
                self.conn, limit=200,
            )
        return classify(pre_state, previous_records=previous_records)

    def _run_state_machine(
        self,
        state: dict[str, Any],
        run_ts_utc: str,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """查上一条 state + 调 StateMachine.compute_next(建模 §5 14 档)。

        Sprint 1.5b-A:在调 compute_next 之前,先用 build_state_machine_fields
        计算所有触发字段并 apply 到 state(trade_plan / lifecycle / layer_2/4),
        让 state_machine 的内部 _build_field_snapshot 拿到真实数据,而非空 dict。
        """
        from ..strategy.state_machine_inputs import (
            apply_inputs_to_strategy_state,
            build_state_machine_fields,
            derive_account_state,
        )

        previous_record = None
        if self.conn is not None:
            previous_record = StrategyStateDAO.get_latest_state(self.conn)

        # 解析 prev_state 字符串(state_machine 子块的 current_state)
        prev_state_str: Optional[str] = None
        prev_strategy_state: Optional[dict[str, Any]] = None
        if previous_record:
            prev_full = previous_record.get("state")
            if isinstance(prev_full, dict):
                prev_strategy_state = prev_full
                sm_block = prev_full.get("state_machine") or {}
                if isinstance(sm_block, dict):
                    prev_state_str = sm_block.get("current_state")

        # Sprint 1.5b-A:计算并填充触发字段(in-place 修改 state)
        try:
            sm_fields = build_state_machine_fields(
                prev_state=prev_state_str,
                prev_strategy_state=prev_strategy_state,
                current_strategy_state=state,
                context=context or {},
                lifecycle=(state.get("lifecycle") or {}),
                now_utc=run_ts_utc,
            )
            apply_inputs_to_strategy_state(state, sm_fields)
            derived_account = derive_account_state(sm_fields)
        except Exception as e:
            logger.warning("build_state_machine_fields failed (non-fatal): %s", e)
            sm_fields = {}
            derived_account = {}

        # account_state 优先级:外部 provider > sm_fields 推断 > 空 dict
        account_state: Optional[dict[str, Any]] = state.get("account_state")
        if account_state is None and self._account_state_provider is not None:
            try:
                account_state = self._account_state_provider()
            except Exception as e:
                logger.warning("account_state_provider failed: %s", e)
        if account_state is None:
            account_state = derived_account

        return self._state_machine.compute_next(
            state,
            previous_record=previous_record,
            account_state=account_state,
            now_utc=run_ts_utc,
        )


# ==================================================================
# 降级占位符构造
# ==================================================================

def _query_metric_inserted_at(conn: Any) -> dict[str, Any]:
    """Sprint 2.7-C:查询所有 metric 的最新 inserted_at_utc(系统侧 wall clock)。

    单点提取自 Sprint 2.6-J 的 _assemble_context,供 pre-flight 重查使用。
    返回结构:
      {
        "onchain":      {metric_name: iso | None},
        "macro":        {metric_name: iso | None},
        "klines_by_tf": {timeframe:   iso | None},
        "derivatives_snapshot": iso | None,
      }
    任何失败 → 返回所有空 dict / None,不抛错。
    """
    try:
        return {
            "onchain": OnchainDAO.get_metric_inserted_at_map(conn),
            "macro":   MacroDAO.get_metric_inserted_at_map(conn),
            "klines_by_tf": BTCKlinesDAO.get_latest_inserted_at_by_timeframe(conn),
            "derivatives_snapshot": (
                DerivativesDAO.get_latest_snapshot_inserted_at(conn)
            ),
        }
    except Exception as e:
        logger.warning("_query_metric_inserted_at failed: %s", e)
        return {
            "onchain": {}, "macro": {},
            "klines_by_tf": {}, "derivatives_snapshot": None,
        }


def _write_preflight_degraded_alert(
    conn: Any,
    *,
    run_id: str,
    run_ts_utc: str,
    degraded_stages: list[str],
    metric_inserted_at: dict[str, Any],
) -> bool:
    """Sprint 2.8-B:把 pre_flight degraded 写成一条 alerts 行。

    只在 degraded_stages 至少有一个 'pre_flight.<group>' 时写;无则返回 False。
    message 含 group 列表 + 每 group 最新 inserted_at,便于事后排查。
    任何 DB 错误只 log warning,不抛(本函数是 pipeline 末尾的最佳努力诊断)。
    """
    pf_groups = [
        s.split(".", 1)[1] for s in degraded_stages
        if s.startswith("pre_flight.") and "." in s
    ]
    if not pf_groups:
        return False

    inserted_map: dict[str, Optional[str]] = {}
    for g in pf_groups:
        # exception 这种伪 group 没法查 inserted_at,跳过
        if g == "exception":
            inserted_map[g] = None
            continue
        try:
            inserted_map[g] = _latest_iso_for_group(metric_inserted_at, g)
        except Exception:
            inserted_map[g] = None

    msg = (
        f"pre-flight degraded for groups: {pf_groups}; "
        f"latest inserted_at per group: {inserted_map}"
    )
    conn.execute(
        "INSERT INTO alerts "
        "(alert_type, severity, message, raised_at_utc, related_run_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("pre_flight_degraded", "warning", msg, run_ts_utc, run_id),
    )
    conn.commit()
    return True


# Sprint 2.7-C:pre-flight 数据就绪阈值(秒)。
# 常规档(00/04/12/16/20:05 BJT)宽松,允许日级数据 30h 内即可。
# 8 点链上档(08:40 BJT)严格,要求当天链上 < 10 min 落地。
_PREFLIGHT_THRESHOLDS_SEC: dict[str, dict[str, int]] = {
    "scheduled": {
        "klines_1h":     10 * 60,
        "derivatives":   10 * 60,
        "klines_1d_4h":  30 * 3600,
        "onchain":       30 * 3600,
        "macro":         30 * 3600,
    },
    "scheduled_8h_onchain": {
        "klines_1h":     10 * 60,
        "derivatives":   10 * 60,
        "klines_1d_4h":  30 * 60,
        "onchain":       10 * 60,
        "macro":         30 * 3600,
    },
}


def _latest_iso_for_group(
    metric_inserted_at: dict[str, Any], group: str,
) -> Optional[str]:
    """从 metric_inserted_at dict 中取该 group 的最新 ISO 时间戳。"""
    onchain = metric_inserted_at.get("onchain") or {}
    macro = metric_inserted_at.get("macro") or {}
    klines_by_tf = metric_inserted_at.get("klines_by_tf") or {}
    deriv_snap = metric_inserted_at.get("derivatives_snapshot")

    if group == "klines_1h":
        return klines_by_tf.get("1h")
    if group == "derivatives":
        return deriv_snap
    if group == "klines_1d_4h":
        candidates = [klines_by_tf.get("1d"), klines_by_tf.get("4h")]
        valid = [c for c in candidates if c]
        return max(valid) if valid else None
    if group == "onchain":
        valid = [v for v in onchain.values() if v]
        return max(valid) if valid else None
    if group == "macro":
        valid = [v for v in macro.values() if v]
        return max(valid) if valid else None
    return None


def _evaluate_freshness(
    metric_inserted_at: dict[str, Any],
    run_trigger: str,
    *,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> list[str]:
    """Sprint 2.7-C:返回未通过 pre-flight 的 group 名单。"""
    thresholds = _PREFLIGHT_THRESHOLDS_SEC.get(
        run_trigger, _PREFLIGHT_THRESHOLDS_SEC["scheduled"],
    )
    now = now_fn()
    failed: list[str] = []
    for group, max_age_sec in thresholds.items():
        latest_iso = _latest_iso_for_group(metric_inserted_at, group)
        if latest_iso is None:
            failed.append(group)
            continue
        try:
            s = latest_iso.replace("Z", "+00:00")
            ts = datetime.fromisoformat(s)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_sec = (now - ts).total_seconds()
        except Exception:
            failed.append(group)
            continue
        if age_sec > max_age_sec:
            failed.append(group)
    return failed


def _run_pre_flight_freshness_check(
    conn: Any,
    metric_inserted_at: dict[str, Any],
    run_trigger: str,
    *,
    retry_after_sec: float = 300.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[list[str], dict[str, Any]]:
    """Sprint 2.7-C 关键函数:Stage 0 数据就绪检查。

    Returns (degraded_groups, refreshed_metric_inserted_at)。
    - degraded_groups: 重试一次后仍未通过的 group 名(空 list = 全部 OK)
    - refreshed_metric_inserted_at: 重试后重读的 inserted_at(让上游用最新)

    流程:
      1. 立即评估 metric_inserted_at vs 阈值
      2. 全 OK → 返回 ([], 入参)
      3. 有 failed → sleep retry_after_sec 秒,重读 inserted_at,再评估
      4. 仍 failed → 返回 (failed_after_retry, refreshed_inserted_at)
    """
    failed_first = _evaluate_freshness(metric_inserted_at, run_trigger, now_fn=now_fn)
    if not failed_first:
        return [], metric_inserted_at

    logger.warning(
        "pre_flight: %s failed groups=%s, sleeping %ss and retrying",
        run_trigger, failed_first, retry_after_sec,
    )
    sleep_fn(retry_after_sec)
    refreshed = _query_metric_inserted_at(conn)
    failed_after = _evaluate_freshness(refreshed, run_trigger, now_fn=now_fn)
    if failed_after:
        logger.warning(
            "pre_flight: still failed after retry: %s", failed_after,
        )
    return failed_after, refreshed


def _build_single_factors(onchain: dict[str, Any]) -> dict[str, Any]:
    """Sprint 2.6-M C2:产出 L2 §B5 用的 single_factors 字典。

    当前只含 exchange_momentum_score(modeling §3.8 降级项)。
    数据不足 → score=None,L2 走 skip 路径。
    """
    from ..single_factors.exchange_momentum import compute_exchange_momentum_score
    return {
        "exchange_momentum_score": compute_exchange_momentum_score(onchain),
    }


def _factor_degraded(name: str, reason: str = "stage exception") -> dict[str, Any]:
    return {
        "factor": name,
        "health_status": "error",
        "computation_method": "error",
        "notes": [reason],
    }


def _adjudicator_fallback(reason: str) -> dict[str, Any]:
    return {
        "action": "watch",
        "direction": None,
        "confidence": 0.3,
        "rationale": f"adjudicator 阶段失败,保守回退 watch:{reason}",
        "constraints": {
            "max_position_size": None,
            "stop_loss_reference": None,
            "event_risk_warning": None,
            "execution_permission_binding": None,
        },
        "evidence_gaps": ["adjudicator_stage_failed"],
        "model_used": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "status": "degraded_error",
        "notes": [reason],
    }


def _observation_fallback(run_ts_utc: str) -> dict[str, Any]:
    """observation_classifier stage 整体失败时的占位(保守归到 watchful)。"""
    return {
        "observation_category": "watchful",
        "suppressed_base_satisfied": False,
        "streak_runs": 0,
        "alert_level": None,
        "reason": "observation_classifier degraded fallback",
        "signals": {},
        "discipline_note": (
            "observation_category 只读:禁止进入任何决策路径。"
        ),
    }


def _state_machine_fallback(reason: str, run_ts_utc: str) -> dict[str, Any]:
    """state_machine stage 整体失败时的占位(保守回到 FLAT)。"""
    return {
        "previous_state": None,
        "current_state": "FLAT",
        "transition_reason": f"state_machine degraded: {reason}",
        "matched_conditions": [],
        "state_entered_at_utc": run_ts_utc,
        "minutes_since_entered": None,
        "stable_in_state": False,
        "flip_watch_bounds": None,
        "on_enter_effects": {"applied": False, "reason": "degraded_fallback"},
        "disciplines_violated": [],
    }


def _layer_error_report(layer_id: int, layer_name: str,
                        reason: str) -> dict[str, Any]:
    return {
        "layer_id": layer_id,
        "layer_name": layer_name,
        "reference_timestamp_utc": _utc_now_iso(),
        "generated_at_utc": _utc_now_iso(),
        "rules_version": DEFAULT_RULES_VERSION,
        "run_trigger": "scheduled",
        "health_status": "error",
        "confidence_tier": "very_low",
        "computation_method": "error",
        "notes": [reason],
    }
