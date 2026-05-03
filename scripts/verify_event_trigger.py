#!/usr/bin/env python3
"""scripts/verify_event_trigger.py — Sprint 1.10-G 端到端真实断言(§Z)。

验证完整 1.10-G 链路:EventTrigger 双轨 + HardInvalidationMonitor 规则平仓 +
EmergencySimplifiedA + scheduler 2 新 cron + RetryPolicy 异步接通 + §X 改造。

prefix `verify_1_10_g_event_*`(继承 1.10-B/C/D/E/F 风险 #4)。

用法:.venv/bin/python scripts/verify_event_trigger.py [/path/to/db]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.ai.agents.emergency_simplified_a import (  # noqa: E402
    VALID_ACTIONS, EmergencySimplifiedA,
)
from src.ai.orchestrator import AIOrchestrator  # noqa: E402
from src.scheduler import jobs as jobs_module  # noqa: E402
from src.scheduler.event_listener import (  # noqa: E402
    check_and_trigger_events,
)
from src.strategy import thesis_manager  # noqa: E402
from src.strategy.event_trigger import (  # noqa: E402
    EVENT_CLASS_INVALIDATION, EVENT_CLASS_PRICE,
    EventTrigger, EventTriggerConfig, is_holding_state,
)
from src.strategy.hard_invalidation_monitor import (  # noqa: E402
    HardInvalidationMonitor,
)

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_PREFIX = "verify_1_10_g_event_"

_PASSED: list[str] = []
_FAILED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _PASSED.append(label)
        print(f"  ✅ {label}")
    else:
        _FAILED.append(f"{label} | {detail}")
        print(f"  ❌ {label} | {detail}")


def cleanup(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "DELETE FROM strategy_runs WHERE run_id LIKE ?", (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM theses WHERE thesis_id LIKE ?", (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM virtual_orders WHERE thesis_id LIKE ?",
            (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM event_throttle WHERE event_type IN "
            "('event_price', 'event_invalidation', 'event_macro')",
        )
        conn.execute(
            "DELETE FROM virtual_account WHERE snapshot_id LIKE ?",
            (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM price_candles WHERE open_time_utc LIKE '2099-%'",
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"  ⚠ cleanup 失败:{e}")


def main(argv: list[str]) -> int:
    with open(_BASE_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db_path = (
        Path(argv[1]).resolve() if len(argv) > 1
        else (_REPO_ROOT / (cfg.get("paths", {}).get("db_path", "data/btc_strategy.db"))).resolve()
    )
    print(f"[verify_event_trigger] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 不存在,先跑 scripts/init_v14_tables.py")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 自动 apply migration(继承 1.10-C/D/E/F 教训)
    try:
        from scripts.init_v14_tables import apply_migration as _apply
        _apply(conn)
        conn.commit()
    except Exception as e:
        print(f"⚠ apply_migration: {e}")

    try:
        print("\n=== 0. pre-clean ===")
        cleanup(conn)
        print("  ✅ pre-clean 完成")

        # ============================================================
        # Section A:base.yaml::event_trigger 段配置(D1=b + D2=b)
        # ============================================================
        print("\n=== A. base.yaml event_trigger 配置(D1=b + D2=b)===")
        et_cfg = EventTriggerConfig.from_dict(cfg)
        check(f"price_pct_flat == 0.05(实际 {et_cfg.price_pct_flat})",
              et_cfg.price_pct_flat == 0.05)
        check(f"price_pct_holding == 0.03(实际 {et_cfg.price_pct_holding})",
              et_cfg.price_pct_holding == 0.03)
        check(f"event_cooldown_seconds == 7200(实际 {et_cfg.event_cooldown_seconds})",
              et_cfg.event_cooldown_seconds == 7200)
        check(f"skip_if_recent_scheduled_seconds == 1800(实际 {et_cfg.skip_if_recent_scheduled_seconds})",
              et_cfg.skip_if_recent_scheduled_seconds == 1800)

        # §X 验证:base.yaml 老路径已删
        runtime = cfg.get("runtime", {})
        scheduled = runtime.get("scheduled", {})
        check("§X #3:base.yaml::runtime.scheduled.cron_hours_utc 已删",
              "cron_hours_utc" not in scheduled)
        event_driven = runtime.get("event_driven", {})
        check("§X #4:base.yaml::runtime.event_driven.throttle 已删",
              "throttle" not in event_driven)

        # ============================================================
        # Section B:EventTrigger 双轨判定(D1=b)
        # ============================================================
        print("\n=== B. EventTrigger 双轨判定(D1=b)===")
        et = EventTrigger(et_cfg)
        check("空仓 5% → 触发(triggered_flat_5pct)",
              et.should_trigger_event_price(
                  current_price=78750.0, baseline_price=75000.0,
                  current_state="FLAT")[0] is True)
        check("空仓 4.99% → 不触发(below_threshold)",
              et.should_trigger_event_price(
                  current_price=75000.0 * 1.0499,
                  baseline_price=75000.0, current_state="FLAT")[0] is False)
        check("持仓 3% → 触发(triggered_holding_3pct)",
              et.should_trigger_event_price(
                  current_price=77250.0, baseline_price=75000.0,
                  current_state="LONG_HOLD")[0] is True)
        check("持仓 2.99% → 不触发",
              et.should_trigger_event_price(
                  current_price=75000.0 * 1.0299,
                  baseline_price=75000.0, current_state="SHORT_HOLD")[0] is False)
        check("LONG_PLANNED 用 flat 5%(不算持仓)",
              not is_holding_state("LONG_PLANNED"))

        # ============================================================
        # Section C:event_throttle 双类独立(D2=b)
        # ============================================================
        print("\n=== C. event_throttle 两类独立(D2=b)===")
        # 检查 event_class 字段存在
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(event_throttle)").fetchall()]
        check("event_throttle 表含 event_class 字段(migration 013)",
              "event_class" in cols)

        now_iso = "2099-05-03T12:00:00Z"
        EventTrigger.record_event(
            conn, "event_price", EVENT_CLASS_PRICE, now_iso,
        )
        EventTrigger.record_event(
            conn, "event_invalidation", EVENT_CLASS_INVALIDATION,
            "2099-05-03T13:00:00Z",
        )
        conn.commit()
        rows = conn.execute(
            "SELECT event_type, event_class FROM event_throttle "
            "WHERE event_type IN ('event_price', 'event_invalidation') "
            "ORDER BY event_type"
        ).fetchall()
        classes = {r["event_type"]: r["event_class"] for r in rows}
        check("event_price 类独立行 + event_class='event_price'",
              classes.get("event_price") == EVENT_CLASS_PRICE)
        check("event_invalidation 类独立行 + event_class='event_invalidation'",
              classes.get("event_invalidation") == EVENT_CLASS_INVALIDATION)

        # ============================================================
        # Section D:HardInvalidationMonitor(D4=b1)
        # ============================================================
        print("\n=== D. HardInvalidationMonitor 规则平仓(D4=b1)===")
        # 创建 active thesis + stop_loss 挂单
        # virtual_account 初始化
        from src.data.storage.dao import VirtualAccountDAO
        VirtualAccountDAO.insert_snapshot(
            conn, snapshot_id=f"{_PREFIX}init_001",
            run_id=f"{_PREFIX}r_init",
            snapshot_at_utc="2099-05-01T00:00:00Z",
            btc_price_at_snapshot=80000.0, initial_capital=100000.0,
            available_cash=100000.0, total_equity=100000.0,
        )
        # 写一条 strategy_run 给 run_id 兜底(close_thesis 需要)
        conn.execute(
            "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
            "reference_timestamp_utc, action_state, run_trigger, "
            "btc_price_usd, full_state_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{_PREFIX}r_pre_breach", "2099-05-03T16:00:00Z",
             "2099-05-04T00:00:00+08:00", "2099-05-03T16:00:00Z",
             "LONG_HOLD", "scheduled", 75000.0, "{}"),
        )
        # 创建 thesis + stop_loss 挂单
        spec = {
            "direction": "long", "core_logic": "verify",
            "confidence_score": 70,
            "break_conditions": ["a", "b", "c"],
            "entry_orders": [{"price": 75000.0, "size_pct": 0.30, "size_usdt": 30000.0}],
            "stop_loss_orders": [{"price": 72000.0, "size_pct": 0.30, "size_usdt": 30000.0}],
            "take_profit_orders": [],
        }
        result_create = thesis_manager.create_thesis(
            conn, thesis_spec=spec, run_id=f"{_PREFIX}r_pre_breach",
            now_utc="2099-05-03T12:00:00Z",
            expires_at_utc="2099-05-10T12:00:00Z",
            thesis_id=f"{_PREFIX}t_001",
        )
        sl_id = result_create["stop_loss_order_ids"][0]
        conn.commit()

        # check_active_theses 未击穿
        breaches_safe = HardInvalidationMonitor.check_active_theses(
            conn, current_btc_price=75000.0,
        )
        check("未击穿(75000 > 72000)→ 空 list", breaches_safe == [])

        # 击穿
        breaches = HardInvalidationMonitor.check_active_theses(
            conn, current_btc_price=71000.0,
        )
        check("击穿(71000 < 72000)→ 1 breach",
              len(breaches) == 1)
        if breaches:
            check("breach.stop_loss_order_id 正确",
                  breaches[0]["stop_loss_order_id"] == sl_id)

        # 执行规则平仓
        exec_result = HardInvalidationMonitor.execute_invalidation(
            conn, thesis_id=f"{_PREFIX}t_001", stop_loss_order_id=sl_id,
            current_btc_price=71000.0, initial_capital=100000.0,
            now_utc=datetime(2099, 5, 3, 16, 5, 0, tzinfo=timezone.utc),
        )
        conn.commit()
        check("execute_invalidation status=event_invalidation_executed",
              exec_result["status"] == "event_invalidation_executed")
        # 验证 thesis 已 closed + channel A
        th_row = conn.execute(
            "SELECT status, close_channel FROM theses WHERE thesis_id = ?",
            (f"{_PREFIX}t_001",),
        ).fetchone()
        check("thesis status=closed_loss(stop_loss_filled reuse,D4=b1)",
              th_row["status"] == "closed_loss")
        check("thesis close_channel=A(D4=b1)",
              th_row["close_channel"] == "A")
        # retry_log_marker 5 字段
        marker = exec_result["retry_log_marker"]
        check("retry_log.event_invalidation_triggered=True",
              marker["event_invalidation_triggered"] is True)
        check("retry_log.event_invalidation_close_channel='A'",
              marker["event_invalidation_close_channel"] == "A")
        check("retry_log.event_invalidation_close_reason='stop_loss_filled'",
              marker["event_invalidation_close_reason"] == "stop_loss_filled")

        # ============================================================
        # Section E:EmergencySimplifiedA + orchestrator.run_event_a
        # ============================================================
        print("\n=== E. EmergencySimplifiedA + run_event_a(全 mock)===")
        # mock client 返 maintain
        mock_payload = {
            "thesis_still_valid": True,
            "immediate_action": "maintain",
            "reasoning": "异动温和,thesis 仍 valid",
        }

        def _mock_agent(out):
            a = MagicMock()
            full = {**out}; full.setdefault("status", "success")
            a.analyze.return_value = full
            a._fallback_output.return_value = {
                "agent": "emergency_simplified_a",
                "status": "degraded",
                "thesis_still_valid": None,
                "immediate_action": "maintain",
                "reasoning": "fallback",
            }
            return a

        agent = _mock_agent(mock_payload)
        orch = AIOrchestrator(agents={"emergency_simplified_a": agent})
        run_result = orch.run_event_a(
            event_type="event_price", triggered_at_price=78500.0,
            baseline_price=75000.0, current_strategy_state="LONG_HOLD",
            key_factors={"funding_rate": 0.0001},
            active_thesis={"direction": "long", "lifecycle_stage": "open"},
        )
        check("orchestrator.run_event_a status=ok",
              run_result["status"] == "ok")
        check("layers.emergency_simplified_a.immediate_action=maintain",
              run_result["layers"]["emergency_simplified_a"]["immediate_action"]
              == "maintain")
        check("run_trigger='event_price' 透传",
              run_result["run_trigger"] == "event_price")
        check("4 取值枚举完整(maintain/emergency_exit/tighten_stop/wait_next_full)",
              set(VALID_ACTIONS) == {
                  "maintain", "emergency_exit", "tighten_stop", "wait_next_full",
              })

        # ============================================================
        # Section F:scheduler.yaml 2 新 cron + RetryPolicy 异步接通
        # ============================================================
        print("\n=== F. scheduler 2 新 cron + RetryPolicy 异步接通 ===")
        check("_JOB_FUNCTIONS 含 hard_invalidation_monitor",
              "hard_invalidation_monitor" in jobs_module._JOB_FUNCTIONS)
        check("_JOB_FUNCTIONS 含 position_health_check",
              "position_health_check" in jobs_module._JOB_FUNCTIONS)
        check("_JOB_FUNCTIONS 含 pipeline_run_with_retry(D3=a)",
              "pipeline_run_with_retry" in jobs_module._JOB_FUNCTIONS)

        # _enqueue_pipeline_run 携带 attempt + retry_start_utc 给 wrapper
        fake_sched = MagicMock()
        jobs_module._active_scheduler = fake_sched
        try:
            ok = jobs_module._enqueue_pipeline_run(
                "event_price", delay_sec=300, attempt=2,
                retry_start_utc="2099-05-03T16:00:00Z",
            )
        finally:
            jobs_module._active_scheduler = None
        check("_enqueue_pipeline_run 返 True(scheduler 在)", ok is True)
        kwargs = fake_sched.add_job.call_args.kwargs
        check("add_job 用 job_pipeline_run_with_retry wrapper",
              kwargs["func"] is jobs_module.job_pipeline_run_with_retry)
        check("kwargs.attempt=2",
              kwargs["kwargs"]["attempt"] == 2)
        check("kwargs.retry_start_utc 透传",
              kwargs["kwargs"]["retry_start_utc"] == "2099-05-03T16:00:00Z")

        # ============================================================
        # Section G:check_and_trigger_events §X 改造(2 类)
        # ============================================================
        print("\n=== G. check_and_trigger_events §X 改造(3 → 2 类)===")
        # cleanup throttles 让 event_price 可触发
        conn.execute(
            "DELETE FROM event_throttle WHERE event_type IN "
            "('event_price', 'event_invalidation')",
        )
        # 写 1h K 线让 event_price 可判定
        conn.execute(
            "INSERT OR REPLACE INTO price_candles (symbol, timeframe, "
            "open_time_utc, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("BTCUSDT", "1h", "2099-05-03T16:00:00Z",
             78000, 78500, 77800, 78400, 1000),
        )
        # baseline 来自 strategy_runs 最新行(已写过 75000)
        conn.commit()
        triggered = check_and_trigger_events(
            conn, now=datetime(2099, 5, 3, 16, 30, 0, tzinfo=timezone.utc),
        )
        check(
            "check_and_trigger_events 包含 event_price"
            "(78400 vs 75000 = +4.5%,LONG_HOLD 触发 3% 阈值)",
            "event_price" in triggered,
        )
        check("§X:event_invalidation 不在返回(拆出 1h cron)",
              "event_invalidation" not in triggered)

    finally:
        print("\n=== Cleanup ===")
        cleanup(conn)
        print("  ✅ cleanup 完成")
        conn.close()

    print()
    print(f"=== 总结 ===")
    print(f"通过:{len(_PASSED)} 项")
    print(f"失败:{len(_FAILED)} 项")
    if _FAILED:
        for f in _FAILED:
            print(f"  ❌ {f}")
        print("\n❌ 全部通过 — 失败")
        return 1
    print("\n✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
