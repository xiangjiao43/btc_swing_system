"""
tests/test_alerts.py — Sprint 1.16c 单测

两部分:
  A. FallbackLogDAO.log_with_escalation 自动升级逻辑
  B. monitoring.check_alerts 告警检测

要求至少 5 case(实现 8 个,覆盖:空 / AI 失败率 / collector 连续失败 /
全线崩溃 / 冷启动卡住 / 多告警排序 / 升级 l1→l2 / 升级 l2→l3)。
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import FallbackLogDAO, StrategyStateDAO
from src.monitoring import check_alerts


# ==================================================================
# Fixtures
# ==================================================================

@pytest.fixture
def conn():
    tmp = Path(tempfile.mkdtemp()) / "alerts.db"
    init_db(db_path=tmp, verbose=False)
    c = get_connection(tmp)
    yield c
    c.close()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_fixture(
    *,
    ai_status: str = "success",
    adj_status: str = "success",
    ref_ts: str,
    cold_start_runs: int = 100,
    warming_up: bool = False,
) -> dict[str, Any]:
    return {
        "reference_timestamp_utc": ref_ts,
        "generated_at_utc": ref_ts,
        "cold_start": {
            "warming_up": warming_up,
            "runs_completed": cold_start_runs,
            "threshold": 42,
        },
        "evidence_reports": {
            "layer_2": {"stance": "neutral"},
            "layer_3": {"opportunity_grade": "none"},
        },
        "context_summary": {"status": ai_status},
        "state_machine": {"current_state": "neutral_observation"},
        "lifecycle": {"current_lifecycle": "FLAT"},
        "adjudicator": {
            "action": "watch", "confidence": 0.5, "status": adj_status,
        },
        "pipeline_meta": {"degraded_stages": []},
    }


def _insert_state(conn, ts: str, run_id: str, state: dict):
    StrategyStateDAO.insert_state(
        conn,
        run_timestamp_utc=ts,
        run_id=run_id,
        run_trigger="scheduled",
        rules_version="v1.2.0",
        ai_model_actual="mock",
        state=state,
    )
    conn.commit()


# ==================================================================
# A. Auto-escalation
# ==================================================================

class TestEscalation:
    def test_level_1_escalates_to_level_2_after_threshold(self, conn):
        now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
        # 先写 3 条 level_1(在 60min 窗口内)
        for i in range(3):
            ts = _iso(now - timedelta(minutes=10 * (i + 1)))
            FallbackLogDAO.log_with_escalation(
                conn, run_timestamp_utc=ts, stage="ai_summary",
                error="boom", fallback_applied="default",
            )
        conn.commit()
        # 第 4 次应被升级到 level_2
        _, actual = FallbackLogDAO.log_with_escalation(
            conn, run_timestamp_utc=_iso(now), stage="ai_summary",
            error="boom", fallback_applied="default",
        )
        conn.commit()
        assert actual == "level_2"

    def test_level_2_escalates_to_level_3(self, conn):
        now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
        # 6 条同阶段都在过去 60min 内,间隔 5 min:
        # 前 3 条 → level_1,后 3 条 → 自动升级到 level_2
        for i in range(6):
            FallbackLogDAO.log_with_escalation(
                conn,
                run_timestamp_utc=_iso(now - timedelta(minutes=55 - 5 * i)),
                stage="macro", error="boom", fallback_applied="d",
            )
        conn.commit()
        # 最近 240 分钟内应有 3 条 level_2;下一条应被升级到 level_3
        _, actual = FallbackLogDAO.log_with_escalation(
            conn, run_timestamp_utc=_iso(now), stage="macro",
            error="boom", fallback_applied="d",
        )
        conn.commit()
        assert actual == "level_3"

    def test_independent_stages_do_not_cross_escalate(self, conn):
        now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
        # 先 3 条 ai_summary 级别 1 → 下一条应升级到 level_2
        for i in range(3):
            FallbackLogDAO.log_with_escalation(
                conn, run_timestamp_utc=_iso(now - timedelta(minutes=5 * (i + 1))),
                stage="ai_summary", error="boom", fallback_applied="d",
            )
        # 对 layer_5 是第一次,应该保持 level_1
        _, level = FallbackLogDAO.log_with_escalation(
            conn, run_timestamp_utc=_iso(now), stage="layer_5",
            error="boom", fallback_applied="d",
        )
        conn.commit()
        assert level == "level_1"


# ==================================================================
# B. check_alerts
# ==================================================================

class TestCheckAlerts:
    def test_no_alerts_on_clean_db(self, conn):
        alerts = check_alerts(conn, lookback_hours=24)
        assert alerts == []

    def test_ai_high_failure_rate_alert(self, conn):
        now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
        # 6 条状态:4 条 AI 降级 + 2 条成功 → 失败率 67% > 30%
        for i in range(6):
            ts = _iso(now - timedelta(hours=i))
            ai = "degraded_error" if i < 4 else "success"
            _insert_state(conn, ts, f"r{i}", _state_fixture(
                ai_status=ai, ref_ts=ts,
            ))
        alerts = check_alerts(conn, lookback_hours=24, now_utc=now)
        types = {a["type"] for a in alerts}
        assert "ai_high_failure_rate" in types
        ai_alert = [a for a in alerts if a["type"] == "ai_high_failure_rate"][0]
        assert ai_alert["level"] == "level_2"

    def test_collector_mass_failure_alert(self, conn):
        now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
        # 两个不同 collector 各在 30 分钟内失败一次
        for stage in ("layer_5", "composite.macro_headwind"):
            FallbackLogDAO.insert_event(
                conn,
                run_timestamp_utc=_iso(now - timedelta(minutes=10)),
                fallback_level="level_1",
                triggered_by=f"pipeline.{stage}",
                details={"stage": stage},
            )
        conn.commit()
        alerts = check_alerts(conn, lookback_hours=24, now_utc=now,
                              mass_failure_window_hours=1)
        mass = [a for a in alerts if a["type"] == "collector_mass_failure"]
        assert len(mass) == 1
        assert mass[0]["level"] == "level_3"

    def test_cold_start_stuck_alert(self, conn):
        now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
        # 13 小时前 runs_completed=5,现在还是 5 且 warming_up=True
        old_ts = _iso(now - timedelta(hours=13))
        new_ts = _iso(now - timedelta(minutes=5))
        _insert_state(conn, old_ts, "old",
                      _state_fixture(ref_ts=old_ts,
                                     cold_start_runs=5, warming_up=True))
        _insert_state(conn, new_ts, "new",
                      _state_fixture(ref_ts=new_ts,
                                     cold_start_runs=5, warming_up=True))
        alerts = check_alerts(conn, lookback_hours=24, now_utc=now)
        stuck = [a for a in alerts if a["type"] == "cold_start_stuck"]
        assert len(stuck) == 1
        assert stuck[0]["level"] == "level_1"

    def test_alerts_sorted_by_level_desc(self, conn):
        now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
        # 制造 level_1(cold_start_stuck) + level_2(AI 失败率)
        for i in range(5):
            ts = _iso(now - timedelta(hours=i))
            _insert_state(conn, ts, f"r{i}", _state_fixture(
                ref_ts=ts, ai_status="degraded_error",
                cold_start_runs=5, warming_up=True,
            ))
        # 再插 13h 前同等 runs → 触发 cold_start_stuck
        old = _iso(now - timedelta(hours=14))
        _insert_state(conn, old, "older", _state_fixture(
            ref_ts=old, ai_status="success",
            cold_start_runs=5, warming_up=True,
        ))
        alerts = check_alerts(conn, lookback_hours=24, now_utc=now)
        # 至少两种类型
        types = [a["type"] for a in alerts]
        assert "ai_high_failure_rate" in types
        assert "cold_start_stuck" in types
        # 高 level 在前
        levels = [a["level"] for a in alerts]
        # level_2 应排在 level_1 前
        l2_idx = next(i for i, a in enumerate(alerts)
                      if a["level"] == "level_2")
        l1_idx = next(i for i, a in enumerate(alerts)
                      if a["level"] == "level_1")
        assert l2_idx < l1_idx
