"""
tests/test_state_builder.py — Sprint 1.12 Pipeline 调度层单测。

覆盖:
  1. happy path:所有 stage 成功 → state 结构完整 + 持久化
  2. 冷启动:DB 记录不足 → cold_start.warming_up=True,降档体现在 L1
  3. cycle_position_last_stable:有历史非 unclear → 注入 context
  4. 单阶段失败不抛出、记入 failures + FallbackLog
  5. AI 返回 degraded_error → context_summary.status=degraded_error + FallbackLog
  6. AI caller 抛异常 → 走 default + degraded_stages 含 ai_summary
  7. build(persist=False) → 不写 strategy_state_history
  8. run() + 写库 → strategy_state_history 有 1 条,state_json 可解析
  9. event_risk 在 L1 之后跑(拿到 is_volatility_extreme)
 10. pipeline_meta.failures 为全部 stage 失败时的兜底路径
 11. run() 没有 conn 会 raise ValueError
 12. 最小 context(没有任何数据)也能跑完,全走 insufficient_data / degraded
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import (
    BTCKlinesDAO, EventRow, EventsCalendarDAO,
    FallbackLogDAO, KlineRow, StrategyStateDAO,
)
from src.pipeline import StrategyStateBuilder, BuildResult


# ==================================================================
# Fixtures / helpers
# ==================================================================

@pytest.fixture
def conn():
    """每个测试用独立的内存 SQLite。"""
    from pathlib import Path
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    init_db(db_path=tmp, verbose=False)
    c = get_connection(tmp)
    yield c
    c.close()


def _ai_ok(summary: str = "段 1\n\n段 2\n\n段 3",
           tokens_in: int = 120, tokens_out: int = 90) -> Any:
    """返回一个符合 call_ai_summary 契约的 success dict 的 fake caller。"""
    def _fake(evidence, openai_client=None, **kwargs):
        return {
            "summary_text": summary,
            "model_used": "mock-model",
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_ms": 42, "status": "success", "error": None,
        }
    return _fake


def _ai_degraded(err: str = "api down") -> Any:
    def _fake(evidence, openai_client=None, **kwargs):
        return {
            "summary_text": None, "model_used": None,
            "tokens_in": 0, "tokens_out": 0, "latency_ms": 0,
            "status": "degraded_error", "error": err,
        }
    return _fake


def _ai_throws():
    def _fake(evidence, openai_client=None, **kwargs):
        raise RuntimeError("boom")
    return _fake


def _seed_klines(conn, *, n: int = 260, timeframes=("1d", "4h", "1h", "1w"),
                 start: float = 50_000.0, daily_pct: float = 0.0,
                 noise_pct: float = 0.005, seed: int = 7) -> None:
    """写若干 K 线到 DB(4 个时间周期)。"""
    rng = np.random.default_rng(seed)
    closes = [start]
    for _ in range(n - 1):
        closes.append(
            closes[-1] * (1 + daily_pct + rng.normal(0, noise_pct))
        )
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # 不同 timeframe 给不同间隔
    intervals = {"1h": 3600, "4h": 4 * 3600, "1d": 86400, "1w": 7 * 86400}
    for tf in timeframes:
        sec = intervals[tf]
        rows = []
        for i, c in enumerate(closes):
            ts = (base + timedelta(seconds=sec * i)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            rows.append(KlineRow(
                timeframe=tf, timestamp=ts,
                open=float(c), high=float(c * 1.005),
                low=float(c * 0.995), close=float(c),
                volume_btc=10.0,
            ))
        BTCKlinesDAO.upsert_klines(conn, rows)
    conn.commit()


def _seed_prior_state(conn, *, cycle_band: str = "late_bear",
                      ts: str = "2024-01-10T00:00:00Z") -> None:
    """写一条以前的 StrategyState,cycle_position.band=cycle_band。"""
    state = {
        "composite_factors": {
            "cycle_position": {
                "factor": "cycle_position", "band": cycle_band,
                "cycle_position": cycle_band,
            },
        },
    }
    StrategyStateDAO.insert_state(
        conn, run_timestamp_utc=ts, run_id="prev-run",
        run_trigger="manual", rules_version="v1.2.0",
        ai_model_actual="x", state=state,
    )
    conn.commit()


def _count_fallback_log(conn) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM fallback_log").fetchone()
    return int(row["n"])


# ==================================================================
# 1. Happy path
# ==================================================================

class TestHappyPath:
    def test_run_end_to_end(self, conn):
        _seed_klines(conn, n=260, daily_pct=0.003)
        builder = StrategyStateBuilder(conn, ai_caller=_ai_ok())
        result = builder.run(run_trigger="scheduled")

        assert isinstance(result, BuildResult)
        assert result.persisted is True
        assert result.ai_status == "success"
        assert result.duration_ms >= 0

        # state 5 大块齐全
        state = result.state
        for key in ("run_id", "reference_timestamp_utc", "cold_start",
                    "evidence_reports", "composite_factors",
                    "context_summary", "pipeline_meta"):
            assert key in state, f"missing {key}"
        for lk in ("layer_1", "layer_2", "layer_3", "layer_4", "layer_5"):
            assert state["evidence_reports"][lk] is not None

        # DB 有 1 条
        got = StrategyStateDAO.get_latest_state(conn)
        assert got is not None
        assert got["run_id"] == result.run_id
        # state_json 正常 round-trip
        assert isinstance(got["state"], dict)


# ==================================================================
# 2. Cold start
# ==================================================================

class TestColdStart:
    def test_cold_start_warming_up(self, conn):
        # StrategyStateDAO.get_count() = 0 → warming_up
        _seed_klines(conn, n=260)
        result = StrategyStateBuilder(
            conn, ai_caller=_ai_ok(),
        ).run()
        cs = result.state["cold_start"]
        assert cs["warming_up"] is True
        assert cs["runs_completed"] == 0
        # L1 证据 health_status 被降为 cold_start_warming_up
        l1 = result.state["evidence_reports"]["layer_1"]
        assert l1["health_status"] == "cold_start_warming_up"

    def test_cold_start_passed_after_threshold(self, conn):
        _seed_klines(conn, n=100)
        # 写 42 条假 state 把 cold start 过掉
        for i in range(42):
            ts = f"2024-02-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00Z"
            StrategyStateDAO.insert_state(
                conn, run_timestamp_utc=ts, run_id=f"r{i}",
                run_trigger="manual", rules_version="v1.2.0",
                ai_model_actual=None, state={"noop": True},
            )
        conn.commit()
        result = StrategyStateBuilder(
            conn, ai_caller=_ai_ok(),
        ).run()
        assert result.state["cold_start"]["warming_up"] is False
        assert result.state["cold_start"]["runs_completed"] >= 42


# ==================================================================
# 3. cycle_position last_stable 预注入
# ==================================================================

class TestLastStableInjected:
    def test_last_stable_pulled_from_history(self, conn):
        _seed_klines(conn, n=260)
        _seed_prior_state(conn, cycle_band="late_bear")

        result = StrategyStateBuilder(conn, ai_caller=_ai_ok()).run()
        cp = result.state["composite_factors"]["cycle_position"]
        # CyclePositionFactor 输出字段名 last_stable_cycle_position
        assert cp.get("last_stable_cycle_position") == "late_bear"


# ==================================================================
# 4. 单阶段失败降级
# ==================================================================

class TestStageFailure:
    def test_stage_exception_captured_and_logged(self, conn, monkeypatch):
        _seed_klines(conn, n=260)

        # patch TruthTrendFactor.compute 抛异常(stage = composite.truth_trend)
        from src.composite.truth_trend import TruthTrendFactor

        def _boom(self, ctx):
            raise RuntimeError("deliberate truth_trend failure")
        monkeypatch.setattr(TruthTrendFactor, "compute", _boom)

        builder = StrategyStateBuilder(conn, ai_caller=_ai_ok())
        result = builder.run()

        assert result.persisted is True  # 其他 stage 仍然跑完
        assert any(f["stage"] == "composite.truth_trend"
                   for f in result.failures)
        assert "composite.truth_trend" in result.degraded_stages
        # FallbackLog 写进去(composite.truth_trend + 可能 ai_summary 无)
        assert _count_fallback_log(conn) >= 1
        # composite_factors.truth_trend 应该是降级占位
        tt = result.state["composite_factors"]["truth_trend"]
        assert tt["health_status"] == "error"


# ==================================================================
# 5. AI degraded 但不抛 → 记 FallbackLog
# ==================================================================

class TestAIDegradedLogged:
    def test_ai_degraded_marks_stage_and_logs(self, conn):
        _seed_klines(conn, n=100)
        result = StrategyStateBuilder(
            conn, ai_caller=_ai_degraded("api timeout")
        ).run()
        assert result.persisted is True
        assert result.ai_status == "degraded_error"
        assert "ai_summary" in result.degraded_stages
        # context_summary 透传
        cs = result.state["context_summary"]
        assert cs["status"] == "degraded_error"
        assert cs["summary_text"] is None
        # FallbackLog 里应有 pipeline.ai_summary 记录
        rows = conn.execute(
            "SELECT triggered_by FROM fallback_log"
        ).fetchall()
        triggers = [r["triggered_by"] for r in rows]
        assert any("ai_summary" in t for t in triggers)


# ==================================================================
# 6. AI caller 抛异常 → 走 default
# ==================================================================

class TestAICallerRaises:
    def test_ai_exception_falls_back(self, conn):
        _seed_klines(conn, n=100)
        result = StrategyStateBuilder(
            conn, ai_caller=_ai_throws(),
        ).run()
        assert result.persisted is True
        assert "ai_summary" in result.degraded_stages
        cs = result.state["context_summary"]
        assert cs["status"] == "degraded_error"
        # Failure 列表里必有 ai_summary
        assert any(f["stage"] == "ai_summary"
                   for f in result.failures)


# ==================================================================
# 7. build(persist=False) 不写 DB
# ==================================================================

class TestDryRun:
    def test_persist_false_skips_write(self, conn):
        _seed_klines(conn, n=100)
        result = StrategyStateBuilder(
            conn, ai_caller=_ai_ok(),
        ).run(persist=False)
        assert result.persisted is False
        # DB 里应该没有 strategy_state_history 记录
        assert StrategyStateDAO.get_count(conn) == 0


# ==================================================================
# 8. run() 写入的 state_json 能正常 JSON 反解析
# ==================================================================

class TestPersistenceRoundTrip:
    def test_state_json_roundtrip(self, conn):
        _seed_klines(conn, n=100)
        result = StrategyStateBuilder(
            conn, ai_caller=_ai_ok(),
        ).run()
        row = conn.execute(
            "SELECT state_json FROM strategy_state_history "
            "WHERE run_timestamp_utc = ?",
            (result.run_timestamp_utc,),
        ).fetchone()
        parsed = json.loads(row["state_json"])
        assert parsed["run_id"] == result.run_id
        assert "evidence_reports" in parsed
        assert "composite_factors" in parsed


# ==================================================================
# 9. event_risk 在 L1 之后跑(能拿到 is_volatility_extreme)
# ==================================================================

class TestEventRiskAfterL1:
    def test_event_risk_uses_l1_volatility(self, conn):
        _seed_klines(conn, n=260)
        # 埋一个 72h 内的高权重事件(FOMC)
        utc = datetime.now(timezone.utc) + timedelta(hours=12)
        ts_str = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        EventsCalendarDAO.upsert_event(
            conn,
            EventRow(
                event_id="fomc-1", date=utc.strftime("%Y-%m-%d"),
                timezone="UTC", local_time=None,
                utc_trigger_time=ts_str,
                event_type="fomc", event_name="FOMC Meeting",
                impact_level=3, notes=None,
            ),
        )
        conn.commit()

        # 保证 L1 输出一定 "extreme"(monkey-patch Layer1Regime)
        import src.pipeline.state_builder as sb
        class _FakeL1:
            def compute(self, ctx, rules_version="v1.2.0"):
                return {
                    "layer_id": 1, "layer_name": "regime",
                    "regime": "chaos", "regime_primary": "chaos",
                    "volatility_regime": "extreme",
                    "volatility_level": "extreme",
                    "health_status": "healthy", "confidence_tier": "medium",
                    "reference_timestamp_utc": "2024-01-01T00:00:00Z",
                    "run_trigger": "scheduled", "rules_version": rules_version,
                    "data_freshness": {}, "computation_method": "rule_based",
                    "notes": [], "generated_at_utc": "2024-01-01T00:00:00Z",
                }
        sb.Layer1Regime = _FakeL1  # type: ignore

        try:
            result = StrategyStateBuilder(conn, ai_caller=_ai_ok()).run()
            er = result.state["composite_factors"]["event_risk"]
            # 有事件被计入且应用了 vol bonus
            assert er["upcoming_events_count"] >= 1
            assert any(e.get("vol_bonus_applied") is True
                       for e in er.get("contributing_events", []))
        finally:
            from src.evidence import Layer1Regime as _RealL1
            sb.Layer1Regime = _RealL1


# ==================================================================
# 10. run() without conn raises
# ==================================================================

class TestRunWithoutConn:
    def test_run_without_conn_raises(self):
        builder = StrategyStateBuilder(conn=None, ai_caller=_ai_ok())
        with pytest.raises(ValueError):
            builder.run()


# ==================================================================
# 11. build() 可以不带 DB(测试注入)
# ==================================================================

class TestBuildWithoutDB:
    def test_build_no_conn_no_persist(self):
        """没有 DB 也能跑:所有 stage 走 insufficient_data / degraded。"""
        builder = StrategyStateBuilder(conn=None, ai_caller=_ai_ok())
        ctx = {
            "reference_timestamp_utc": "2024-02-02T00:00:00Z",
            # 空数据:klines / derivatives / onchain 全缺
        }
        result = builder.build(ctx, run_trigger="manual", persist=False)
        assert result.persisted is False
        # state 结构依然完整
        assert result.state["evidence_reports"]["layer_1"] is not None
        assert result.state["evidence_reports"]["layer_5"] is not None
        # AI 仍然被调用(caller 不关心 evidence 内容)
        assert result.state["context_summary"]["status"] == "success"


# ==================================================================
# 12. Fallback level_1 写入 details 可反解析
# ==================================================================

class TestFallbackLogDetailsShape:
    def test_log_stage_error_details(self, conn):
        # 直接调 DAO 验证 shape(给后续 Sprint 做 auto_upgrade 判定做准备)
        FallbackLogDAO.log_stage_error(
            conn, run_timestamp_utc="2024-03-01T00:00:00Z",
            stage="composite.truth_trend",
            error=RuntimeError("bad"), fallback_applied="default_returned",
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM fallback_log WHERE "
            "triggered_by = 'pipeline.composite.truth_trend'"
        ).fetchone()
        assert row is not None
        assert row["fallback_level"] == "level_1"
        parsed = json.loads(row["details"])
        assert parsed["stage"] == "composite.truth_trend"
        assert parsed["error_type"] == "RuntimeError"
        assert parsed["fallback_applied"] == "default_returned"


# ==================================================================
# 13. get_latest_non_unclear_cycle 基础查询(没数据时 None)
# ==================================================================

class TestLatestNonUnclearQuery:
    def test_returns_none_when_empty(self, conn):
        assert StrategyStateDAO.get_latest_non_unclear_cycle(conn) is None

    def test_skips_unclear(self, conn):
        # 写一条 unclear + 一条 late_bear,取最近非 unclear
        for i, (band, ts) in enumerate([
            ("late_bear", "2024-03-01T00:00:00Z"),
            ("unclear", "2024-03-02T00:00:00Z"),
        ]):
            StrategyStateDAO.insert_state(
                conn, run_timestamp_utc=ts, run_id=f"r{i}",
                run_trigger="manual", rules_version="v1.2.0",
                ai_model_actual=None,
                state={"composite_factors": {
                    "cycle_position": {"band": band}
                }},
            )
        conn.commit()
        got = StrategyStateDAO.get_latest_non_unclear_cycle(conn)
        assert got == "late_bear"
