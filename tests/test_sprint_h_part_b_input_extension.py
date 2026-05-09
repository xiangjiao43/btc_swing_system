"""Sprint H Part B — weekly_review input builder 4 个新聚合 + prompt 扩展。

§Z 端到端 DB 字段值断言:
- input builder 真返新字段(JSON 解析,不是 .called)
- prompt 真含新段
- agent fallback 仍有 ai_vs_actual_comparison 占位
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ai.weekly_review_input_builder import (
    _aggregate_anti_pattern_signals,
    _aggregate_l3_grade_distribution,
    _aggregate_l4_risk_tier_distribution,
    _aggregate_master_runs_with_trade_plan,
    _aggregate_weekly_price_action,
    build_weekly_review_input,
)
from src.data.storage.connection import init_db


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "sprint_h_b.db"
    init_db(db_path=tmp, verbose=False)
    from scripts.init_v14_tables import apply_migration
    c = sqlite3.connect(str(tmp))
    apply_migration(c)
    c.commit()
    c.close()
    return tmp


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _now():
    return datetime.now(timezone.utc)


def _seed_strategy_run(
    conn, *, generated_at_utc: str, l3_grade: str, l4_risk: str,
    anti_pattern_flags: list[str], master: dict | None = None,
    btc_price: float = 78000.0, fallback_level: str | None = None,
    run_trigger: str = "scheduled",
):
    full_state = {
        "schema_version": "v14",
        "layers": {
            "l1": {"status": "success"},
            "l2": {"status": "success"},
            "l3": {"opportunity_grade": l3_grade,
                   "anti_pattern_flags": anti_pattern_flags},
            "l4": {"risk_tier": l4_risk},
            "l5": {"status": "success"},
            "master": master or {},
        },
    }
    bjt_str = generated_at_utc.replace("Z", "+00:00")
    conn.execute(
        "INSERT INTO strategy_runs "
        "(run_id, generated_at_utc, generated_at_bjt, action_state, "
        " btc_price_usd, run_trigger, fallback_level, full_state_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (f"r_{generated_at_utc}", generated_at_utc, bjt_str,
         "FLAT", btc_price, run_trigger, fallback_level,
         json.dumps(full_state, ensure_ascii=False)),
    )


def _seed_kline(conn, *, day: str, o: float, h: float, l: float, c: float):
    conn.execute(
        "INSERT INTO price_candles "
        "(symbol, timeframe, open_time_utc, open, high, low, close, volume, "
        " inserted_at_utc) "
        "VALUES ('BTCUSDT', '1d', ?, ?, ?, ?, ?, 1.0, ?)",
        (f"{day}T00:00:00Z", o, h, l, c, f"{day}T00:00:00Z"),
    )


# ============================================================
# 1. _aggregate_anti_pattern_signals
# ============================================================

def test_anti_pattern_aggregate_counts_per_flag(conn):
    now = _now()
    week_start = now - timedelta(days=7)
    base = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_strategy_run(conn, generated_at_utc=base, l3_grade="B",
                       l4_risk="moderate",
                       anti_pattern_flags=["extending_late_phase"])
    _seed_strategy_run(conn,
                       generated_at_utc=(now - timedelta(days=2))
                       .strftime("%Y-%m-%dT%H:%M:%SZ"),
                       l3_grade="C", l4_risk="elevated",
                       anti_pattern_flags=["extending_late_phase"])
    _seed_strategy_run(conn,
                       generated_at_utc=(now - timedelta(days=1))
                       .strftime("%Y-%m-%dT%H:%M:%SZ"),
                       l3_grade="none", l4_risk="moderate",
                       anti_pattern_flags=[])
    conn.commit()

    out = _aggregate_anti_pattern_signals(
        conn, week_start=week_start, week_end=now,
    )
    assert out["total_runs_with_l3"] == 3
    assert out["anti_pattern_counts"]["extending_late_phase"] == 2
    assert out["trigger_rates"]["extending_late_phase"] == round(2/3, 4)
    assert out["top_flag"] == "extending_late_phase"


# ============================================================
# 2. _aggregate_l3_grade_distribution
# ============================================================

def test_l3_grade_distribution(conn):
    now = _now()
    week_start = now - timedelta(days=7)
    for i, grade in enumerate(["A", "B", "B", "C", "C", "C", "none", "none"]):
        ts = (now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_strategy_run(conn, generated_at_utc=ts, l3_grade=grade,
                           l4_risk="moderate", anti_pattern_flags=[])
    conn.commit()
    out = _aggregate_l3_grade_distribution(
        conn, week_start=week_start, week_end=now + timedelta(seconds=10),
    )
    assert out["A"] == 1
    assert out["B"] == 2
    assert out["C"] == 3
    assert out["none"] == 2
    assert out["empty"] == 0


# ============================================================
# 3. _aggregate_l4_risk_tier_distribution
# ============================================================

def test_l4_risk_tier_distribution(conn):
    now = _now()
    week_start = now - timedelta(days=7)
    for i, tier in enumerate(["low", "moderate", "moderate",
                              "elevated", "elevated", "extreme"]):
        ts = (now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_strategy_run(conn, generated_at_utc=ts, l3_grade="none",
                           l4_risk=tier, anti_pattern_flags=[])
    conn.commit()
    out = _aggregate_l4_risk_tier_distribution(
        conn, week_start=week_start, week_end=now + timedelta(seconds=10),
    )
    assert out["low"] == 1
    assert out["moderate"] == 2
    assert out["elevated"] == 2
    assert out["extreme"] == 1
    assert out["empty"] == 0


# ============================================================
# 4. _aggregate_weekly_price_action
# ============================================================

def test_weekly_price_action(conn):
    now = _now()
    week_start = now - timedelta(days=7)
    # 7 days of K-lines using TODAY-relative dates so they fall inside window
    today_date = now.date()
    seed_data = [
        (today_date - timedelta(days=6), 78000, 79000, 77800, 78600),
        (today_date - timedelta(days=5), 78600, 79500, 78200, 79000),
        (today_date - timedelta(days=4), 79000, 81000, 78800, 80500),
        (today_date - timedelta(days=3), 80500, 82000, 80200, 81500),
        (today_date - timedelta(days=2), 81500, 82800, 80700, 81000),
        (today_date - timedelta(days=1), 81000, 81500, 79500, 80100),
    ]
    for day, o, h, l, c in seed_data:
        _seed_kline(conn, day=day.strftime("%Y-%m-%d"), o=o, h=h, l=l, c=c)
    conn.commit()
    out = _aggregate_weekly_price_action(
        conn, week_start=week_start, week_end=now,
    )
    assert len(out["daily"]) == 6
    assert out["week_open"] == 78000
    assert out["week_close"] == 80100
    assert out["week_high"] == 82800
    assert out["week_low"] == 77800
    assert out["week_pct_change"] is not None
    assert abs(out["week_pct_change"] - ((80100 - 78000) / 78000 * 100)) < 0.01


def test_weekly_price_action_empty(conn):
    """price_candles 表空 → 返 None 字段 + 空 daily list。"""
    now = _now()
    out = _aggregate_weekly_price_action(
        conn, week_start=now - timedelta(days=7), week_end=now,
    )
    assert out["daily"] == []
    assert out["week_open"] is None


# ============================================================
# 5. _aggregate_master_runs_with_trade_plan(v1.3 schema)
# ============================================================

def test_master_runs_with_trade_plan_v13(conn):
    now = _now()
    week_start = now - timedelta(days=7)
    master_v13 = {
        "status": "success",
        "state_transition": {"from_state": "FLAT", "to_state": "LONG_PLANNED"},
        "trade_plan": {
            "action": "open", "direction": "long",
            "entry_price_zone": [76251, 77000],
            "stop_loss": 76251,
            "take_profit_zones": [79455, 82309, 85000],
            "position_size_pct": 0.33,
        },
    }
    _seed_strategy_run(
        conn,
        generated_at_utc=(now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        l3_grade="B", l4_risk="moderate",
        anti_pattern_flags=[], master=master_v13,
        btc_price=78337.0, fallback_level=None, run_trigger="scheduled",
    )
    conn.commit()

    out = _aggregate_master_runs_with_trade_plan(
        conn, week_start=week_start, week_end=now,
    )
    assert len(out) == 1
    rec = out[0]
    assert rec["schema"] == "v1.3"
    assert rec["master_direction"] == "long"
    assert rec["entry_zone"] == [76251, 77000]
    assert rec["stop_loss"] == 76251
    assert rec["take_profit_zones"] == [79455, 82309, 85000]
    assert rec["btc_price_at_run"] == 78337.0
    assert rec["l3_grade"] == "B"


def test_master_runs_excludes_fallback(conn):
    """fallback_level=level_2 不入 master_runs_with_trade_plan(master AI 失败的 run)。"""
    now = _now()
    week_start = now - timedelta(days=7)
    master_failed = {"status": "degraded", "state_transition": {}}
    _seed_strategy_run(
        conn,
        generated_at_utc=(now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        l3_grade="B", l4_risk="moderate", anti_pattern_flags=[],
        master=master_failed, fallback_level="level_2",
        run_trigger="scheduled",
    )
    conn.commit()
    out = _aggregate_master_runs_with_trade_plan(
        conn, week_start=week_start, week_end=now,
    )
    assert out == []


# ============================================================
# 6. build_weekly_review_input 集成:5 个新字段全部存在
# ============================================================

def test_build_weekly_review_input_includes_5_new_fields(conn):
    """end-to-end:返回 dict 必含 anti_pattern_signals / l3_grade_distribution /
    l4_risk_tier_distribution / weekly_price_action / master_runs_with_trade_plan。"""
    now = _now()
    week_start = now - timedelta(days=7)
    # 种点数据
    base = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_strategy_run(conn, generated_at_utc=base, l3_grade="B",
                       l4_risk="moderate",
                       anti_pattern_flags=["extending_late_phase"])
    conn.commit()

    inp = build_weekly_review_input(conn, now_utc=now, window_days=7)
    # §Z 真断言新字段都在
    assert "anti_pattern_signals" in inp
    assert "l3_grade_distribution" in inp
    assert "l4_risk_tier_distribution" in inp
    assert "weekly_price_action" in inp
    assert "master_runs_with_trade_plan" in inp
    # 内容合理
    assert inp["l3_grade_distribution"]["B"] == 1
    assert inp["anti_pattern_signals"]["top_flag"] == "extending_late_phase"
    assert isinstance(inp["weekly_price_action"]["daily"], list)
    assert isinstance(inp["master_runs_with_trade_plan"], list)


# ============================================================
# 7. WeeklyReviewAnalyst._build_user_prompt 含新段
# ============================================================

def test_prompt_includes_new_sections(conn):
    """prompt 字符串必含「反模式触发率」「L3 opportunity_grade 分布」
    「L4 risk_tier 分布」「BTC 实际走势」「master 真跑通」「ai_vs_actual_comparison」。"""
    from src.ai.agents.weekly_review_analyst import WeeklyReviewAnalyst
    now = _now()
    inp = build_weekly_review_input(conn, now_utc=now, window_days=7)
    agent = WeeklyReviewAnalyst(client=None)
    prompt = agent._build_user_prompt(inp)

    assert "反模式触发率" in prompt
    assert "L3 opportunity_grade 分布" in prompt
    assert "L4 risk_tier 分布" in prompt
    assert "BTC 实际走势" in prompt
    assert "master 真跑通" in prompt
    assert "ai_vs_actual_comparison" in prompt
    # 中立性纪律
    assert "中立性纪律" in prompt or "中立性" in prompt
    # 具体调整路径强制
    assert "具体调整路径" in prompt


# ============================================================
# 8. prompt .txt 含 Sprint H Part B 段
# ============================================================

def test_prompt_txt_contains_sprint_h_section():
    from pathlib import Path
    text = (
        Path(__file__).parent.parent
        / "src" / "ai" / "agents" / "prompts" / "weekly_review_analyst.txt"
    ).read_text(encoding="utf-8")
    assert "Sprint H Part B" in text
    assert "ai_vs_actual_comparison" in text
    assert "具体调整路径" in text
    assert "反模式触发率" in text or "anti_pattern" in text
