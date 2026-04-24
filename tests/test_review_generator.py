"""
tests/test_review_generator.py — Sprint 1.16b 单测

覆盖:
  1. 正常数据 → 完整 7 节 Markdown
  2. 空库 → 各节标注"无数据",不 crash
  3. AI 失败 → 第 7 节显示"AI 分析暂不可用"
  4. 不同 period(daily / weekly / monthly)→ lookback 不同
  5. generate_and_save 写出文件
  6. Markdown 语法能被 markdown 解析器解析为 HTML(含 <h1><h2> 若干)
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import StrategyStateDAO, FallbackLogDAO
from src.review import ReviewReportGenerator


@pytest.fixture
def conn():
    tmp = Path(tempfile.mkdtemp()) / "review.db"
    init_db(db_path=tmp, verbose=False)
    c = get_connection(tmp)
    yield c
    c.close()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_fixture(
    *,
    sm: str = "neutral_observation",
    lifecycle: str = "FLAT",
    prev_lifecycle: str = "FLAT",
    l2_stance: str = "neutral",
    l3_grade: str = "none",
    action: str = "watch",
    ref_ts: str,
    gen_ts: str,
) -> dict[str, Any]:
    return {
        "reference_timestamp_utc": ref_ts,
        "generated_at_utc": gen_ts,
        "cold_start": {
            "warming_up": False,
            "runs_completed": 50,
            "threshold": 42,
        },
        "evidence_reports": {
            "layer_2": {"stance": l2_stance, "stance_confidence": 0.55},
            "layer_3": {"opportunity_grade": l3_grade},
            "layer_5": {"data_completeness_pct": 75.0},
        },
        "context_summary": {"status": "success"},
        "state_machine": {"current_state": sm},
        "lifecycle": {
            "current_lifecycle": lifecycle,
            "previous_lifecycle": prev_lifecycle,
            "transition_triggered_by": (
                "action" if lifecycle != prev_lifecycle else "default"
            ),
        },
        "adjudicator": {
            "action": action,
            "confidence": 0.6,
            "status": "success",
        },
        "pipeline_meta": {"degraded_stages": []},
    }


def _insert(conn, run_ts: str, run_id: str, state: dict):
    StrategyStateDAO.insert_state(
        conn,
        run_timestamp_utc=run_ts,
        run_id=run_id,
        run_trigger="scheduled",
        rules_version="v1.2.0",
        ai_model_actual="mock",
        state=state,
    )
    conn.commit()


# ==================================================================
# 1. Full report with data
# ==================================================================

def test_full_report_with_data(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    # 5 轮分散 5 天,后两轮切换 state_machine
    rows = [
        ("neutral_observation", "neutral", "none", "FLAT", "FLAT", "watch"),
        ("neutral_observation", "neutral", "none", "FLAT", "FLAT", "watch"),
        ("active_long_execution", "bullish", "A", "FLAT", "FLAT", "open_long"),
        ("active_long_execution", "bullish", "A", "LONG_OPEN", "FLAT", "hold"),
        ("active_long_execution", "bullish", "A", "LONG_OPEN", "LONG_OPEN", "hold"),
    ]
    for i, (sm, stance, grade, life, prev_life, action) in enumerate(rows):
        ts = _iso(now - timedelta(days=4 - i))
        _insert(conn, ts, f"r{i}", _state_fixture(
            sm=sm, lifecycle=life, prev_lifecycle=prev_life,
            l2_stance=stance, l3_grade=grade, action=action,
            ref_ts=ts, gen_ts=ts,
        ))
    # 加 1 条 fallback
    FallbackLogDAO.log_stage_error(
        conn, run_timestamp_utc=_iso(now - timedelta(days=1)),
        stage="ai_summary", error="timeout", fallback_applied="default",
    )
    conn.commit()

    gen = ReviewReportGenerator(
        conn, now_utc=now,
        ai_caller=lambda kpi: "系统本周期 5 次运行。观察到由中性转入主动做多档位。无严重降级。",
    )
    md = gen.generate(period="weekly")
    assert "# BTC 策略系统复盘报告" in md
    assert "## 一、总览" in md
    assert "## 二、市场判断分布" in md
    assert "## 三、决策行为" in md
    assert "## 四、数据质量" in md
    assert "## 五、降级统计" in md
    assert "## 六、关键事件" in md
    assert "## 七、AI 观察" in md
    assert "5 次" in md  # runs_total
    assert "ai_summary" in md  # top fallback stage
    # 关键事件应捕获 sm 切换 + lifecycle 切换
    assert "state_machine 切换" in md
    assert "lifecycle 切换" in md
    # AI 观察段
    assert "主动做多" in md


# ==================================================================
# 2. Empty DB still renders
# ==================================================================

def test_empty_db_renders_with_na(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    gen = ReviewReportGenerator(conn, now_utc=now, ai_caller=lambda k: None)
    md = gen.generate(period="weekly")
    assert "# BTC 策略系统复盘报告" in md
    # 执行次数 0
    assert "0 次" in md
    # 无数据占位
    assert "无数据" in md
    # 第 7 节降级
    assert "AI 分析暂不可用" in md


# ==================================================================
# 3. AI failure still renders
# ==================================================================

def test_ai_failure_falls_back(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)

    def _boom(kpi):
        raise RuntimeError("ai api is down")

    # 至少插一条 state,让其他段落正常渲染
    ts = _iso(now - timedelta(hours=2))
    _insert(conn, ts, "r0", _state_fixture(ref_ts=ts, gen_ts=ts))
    gen = ReviewReportGenerator(conn, now_utc=now, ai_caller=_boom)
    md = gen.generate(period="weekly")
    assert "AI 分析暂不可用" in md
    assert "## 七、AI 观察" in md


# ==================================================================
# 4. Different periods → different lookback
# ==================================================================

def test_periods_map_to_different_lookbacks(conn):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    # 一条在 2 天前,一条在 15 天前
    ts_recent = _iso(now - timedelta(days=2))
    ts_old = _iso(now - timedelta(days=15))
    _insert(conn, ts_recent, "recent", _state_fixture(
        ref_ts=ts_recent, gen_ts=ts_recent))
    _insert(conn, ts_old, "old", _state_fixture(
        ref_ts=ts_old, gen_ts=ts_old))

    gen = ReviewReportGenerator(conn, now_utc=now, ai_caller=lambda k: None)
    daily_md = gen.generate(period="daily")
    weekly_md = gen.generate(period="weekly")
    monthly_md = gen.generate(period="monthly")

    assert "0 次" in daily_md      # 2 天前不在 daily(1d)窗口
    assert "1 次" in weekly_md     # 2 天前在 weekly(7d)窗口
    assert "2 次" in monthly_md    # 两条都在 monthly(30d)


# ==================================================================
# 5. generate_and_save writes to disk
# ==================================================================

def test_generate_and_save_writes_file(conn, tmp_path: Path):
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    gen = ReviewReportGenerator(conn, now_utc=now, ai_caller=lambda k: None)
    out_dir = tmp_path / "reviews"
    path = gen.generate_and_save(period="weekly", output_dir=out_dir)
    assert path.exists()
    assert path.name == "weekly_20260424.md"
    content = path.read_text(encoding="utf-8")
    assert content.startswith("# BTC 策略系统复盘报告")


# ==================================================================
# 6. Markdown is parseable (markdown lib)
# ==================================================================

def test_markdown_parses_without_errors(conn):
    import markdown
    now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    ts = _iso(now - timedelta(hours=2))
    _insert(conn, ts, "r0", _state_fixture(ref_ts=ts, gen_ts=ts))
    gen = ReviewReportGenerator(conn, now_utc=now, ai_caller=lambda k: "ok")
    md = gen.generate(period="weekly")
    html = markdown.markdown(md)
    # 至少应有 h1, h2, li 标签
    assert "<h1>" in html
    assert html.count("<h2>") >= 7  # 7 节标题
    assert "<li>" in html
