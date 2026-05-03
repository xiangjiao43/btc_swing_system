#!/usr/bin/env python3
"""scripts/verify_retry_mechanism.py — Sprint 1.10-F 端到端真实断言(§Z)。

验证完整 retry 机制:RetryPolicy + CircuitBreaker + migration 012 +
orchestrator post-validate retry + V22 SQL 滑动 72h + Master fallback 接通。

prefix `verify_1_10_f_retry_*`(继承 1.10-B/C/D/E 风险 #4)。

用法:.venv/bin/python scripts/verify_retry_mechanism.py [/path/to/db]
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

from src.ai.circuit_breaker import CircuitBreaker  # noqa: E402
from src.ai.retry_policy import RetryPolicy  # noqa: E402
from src.ai.validator import (  # noqa: E402
    count_master_failures_in_window,
    validate_master_output,
    validator_8_break_objectivity,
    validator_21_soft_resistance,
)
from src.data.storage.dao import StrategyStateDAO  # noqa: E402

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_PREFIX = "verify_1_10_f_retry_"

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
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"  ⚠ cleanup 失败:{e}")


def _insert_run_with_retry_log(
    conn: sqlite3.Connection,
    run_id: str,
    generated_at_utc: str,
    retry_log: dict | None,
) -> None:
    """直接插一条 strategy_runs(测试用,绕过 DAO 复杂业务装配)。"""
    rl_json = json.dumps(retry_log, ensure_ascii=False) if retry_log else None
    conn.execute(
        """
        INSERT INTO strategy_runs
            (run_id, generated_at_utc, generated_at_bjt,
             reference_timestamp_utc, action_state, run_trigger,
             full_state_json, retry_log_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, generated_at_utc, generated_at_utc,
         generated_at_utc, "FLAT", "verify_test", "{}", rl_json),
    )


def main(argv: list[str]) -> int:
    with open(_BASE_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db_path = (
        Path(argv[1]).resolve() if len(argv) > 1
        else (_REPO_ROOT / (cfg.get("paths", {}).get("db_path", "data/btc_strategy.db"))).resolve()
    )
    print(f"[verify_retry_mechanism] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 不存在,先跑 scripts/init_v14_tables.py")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 自动 apply migration(继承 1.10-C/D/E 教训)
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
        # Section A:RetryPolicy 指数退避 + 2h 窗口
        # ============================================================
        print("\n=== A. RetryPolicy(指数退避 + 2h 窗口)===")
        rp = RetryPolicy()
        check("attempt 1 → 5min(300s)", rp.compute_backoff_seconds(1) == 300)
        check("attempt 2 → 10min(600s)", rp.compute_backoff_seconds(2) == 600)
        check("attempt 3 → 20min(1200s)", rp.compute_backoff_seconds(3) == 1200)

        now = datetime(2026, 5, 1, 16, 0, 0, tzinfo=timezone.utc)
        within = now - timedelta(minutes=30)
        outside = now - timedelta(hours=3)
        check("窗口内(30 min ago)→ within=True", rp.is_within_window(within, now))
        check("窗口外(3 h ago)→ within=False", not rp.is_within_window(outside, now))

        # ============================================================
        # Section B:CircuitBreaker 短路依赖
        # ============================================================
        print("\n=== B. CircuitBreaker 短路依赖图(v1.4 §6.3.1)===")
        cb = CircuitBreaker()
        check("L1 失败 → 短路 L2/L3/master",
              cb.get_downstream_to_short("l1") == ["l2", "l3", "master"])
        check("L2 失败 → 短路 L3/master",
              cb.get_downstream_to_short("l2") == ["l3", "master"])
        check("L5 失败 → 不短路任何下游(master 仍跑)",
              cb.get_downstream_to_short("l5") == [])
        run, _ = cb.should_master_run(["l5"])
        check("L5 失败 → master 仍跑(D4=a)", run is True)
        run, _ = cb.should_master_run(["l1"])
        check("L1 失败 → master 短路", run is False)

        # ============================================================
        # Section C:macro fallback(D4=a)硬编码字段完整
        # ============================================================
        print("\n=== C. CircuitBreaker.apply_macro_fallback(L5 失败 D4=a)===")
        macro_fb = CircuitBreaker.apply_macro_fallback()
        check("macro_stance == risk_neutral",
              macro_fb.get("macro_stance") == "risk_neutral")
        check("headwind_score == 0",
              macro_fb.get("headwind_score") == 0)
        check("position_cap_macro_multiplier == 1.0",
              macro_fb.get("position_cap_macro_multiplier") == 1.0)
        check("extreme_event_detected == False",
              macro_fb.get("extreme_event_detected") is False)

        # ============================================================
        # Section D:Validator V8/V9/V11/V21 needs_retry 标记
        # ============================================================
        print("\n=== D. Validator V8/V21 needs_retry 标记 ===")
        _, act = validator_8_break_objectivity(
            {"mode": "new_thesis", "new_thesis": {"break_conditions": ["x", "y"]}},
            {},
        )
        check("V8 break < 3 → needs_retry=True",
              act.get("validator_8_needs_retry") is True)

        _, act = validator_21_soft_resistance(
            {"mode": "silent_cooldown"},
            {"active_thesis": None,
             "cooldown_state": {"in_cooldown": False},
             "fuse_state": {"in_14d_fuse": False, "in_thesis_cycle_fuse": False},
             "l3_grade": "A"},
        )
        check("V21 软抗拒 → needs_retry=True",
              act.get("validator_21_needs_retry") is True)
        check("V21 retry_hint 文本含 'V21' + 'new_thesis'",
              "V21" in act.get("validator_21_retry_hint", "")
              and "new_thesis" in act.get("validator_21_retry_hint", ""))

        # ============================================================
        # Section E:V22 SQL 滑动 72h 检测
        # ============================================================
        print("\n=== E. V22 SQL count_master_failures_in_window(D2=a)===")
        # 插 4 行:3 个 72h 内 + 1 个超出
        now_t = datetime(2026, 5, 1, 16, 0, 0, tzinfo=timezone.utc)
        for i, hours_ago in enumerate([10, 30, 60]):
            ts = (now_t - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
            _insert_run_with_retry_log(
                conn, f"{_PREFIX}master_fail_{i}", ts,
                {"thesis_aware_fallback_applied": True,
                 "thesis_aware_fallback_reason": "master_failed_silent"},
            )
        # 超出窗口
        ts_out = (now_t - timedelta(hours=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_run_with_retry_log(
            conn, f"{_PREFIX}master_fail_old", ts_out,
            {"thesis_aware_fallback_applied": True},
        )
        # 无 retry_log(对照)
        ts_ok = (now_t - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _insert_run_with_retry_log(
            conn, f"{_PREFIX}happy_no_log", ts_ok, None,
        )
        conn.commit()

        cnt = count_master_failures_in_window(
            conn, window_hours=72, now_utc=now_t,
        )
        check(f"72h 窗口内 master 失败 = 3(实际 {cnt})", cnt == 3)

        cnt6h = count_master_failures_in_window(
            conn, window_hours=6, now_utc=now_t,
        )
        check(f"6h 窗口内 master 失败 = 0(实际 {cnt6h})", cnt6h == 0)

        # ============================================================
        # Section F:retry_log_json 字段端到端写入 + 还原
        # ============================================================
        print("\n=== F. retry_log_json 端到端写入 + JSON 还原 ===")
        # 用 DAO 写一条含 retry_log 的 strategy_run
        dao_run_id = f"{_PREFIX}dao_e2e_{int(now_t.timestamp())}"
        state_with_rl = {
            "generated_at_utc": now_t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "generated_at_bjt": now_t.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "retry_log": {
                "macro_fallback_applied": True,
                "macro_fallback_reason": "l5_failed_apply_hardcoded_macro_d4_a",
                "thesis_aware_fallback_applied": True,
                "thesis_aware_fallback_reason": "master_failed_keep_thesis",
                "layers_status": {
                    "l1": "success", "l2": "success", "l3": "success",
                    "l4": "success", "l5": "fallback", "master": "fallback",
                },
                "failed_layers": ["l5", "master"],
                "validator_triggered_retry_applied": True,
                "validator_triggered_retry_succeeded": False,
            },
            "state_machine": {"current_state": "FLAT", "stable_in_state": True},
            "ai_layers": {},
            "market_snapshot": {"btc_price_usd": 75749},
            "observation": {"observation_category": "neutral"},
        }
        StrategyStateDAO.insert_state(
            conn,
            run_timestamp_utc=now_t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            run_id=dao_run_id,
            run_trigger="verify",
            rules_version="v1.4",
            ai_model_actual="claude-opus-4-7",
            state=state_with_rl,
        )
        conn.commit()

        row = conn.execute(
            "SELECT retry_log_json FROM strategy_runs WHERE run_id = ?",
            (dao_run_id,),
        ).fetchone()
        check("DAO 写入 strategy_runs 成功", row is not None)
        check("retry_log_json 不是 NULL",
              row is not None and row["retry_log_json"] is not None)
        if row and row["retry_log_json"]:
            parsed = json.loads(row["retry_log_json"])
            check("retry_log JSON 还原 macro_fallback_applied=True",
                  parsed.get("macro_fallback_applied") is True)
            check("retry_log JSON 还原 failed_layers=['l5','master']",
                  parsed.get("failed_layers") == ["l5", "master"])
            check("retry_log JSON 还原 validator_triggered_retry_applied",
                  parsed.get("validator_triggered_retry_applied") is True)

        # ============================================================
        # Section G:Orchestrator 端到端(mock 6 AI)— L5 失败 + master 仍跑
        # ============================================================
        print("\n=== G. Orchestrator e2e:L5 失败 → macro fallback,master 仍跑 ===")
        try:
            from src.ai.orchestrator import AIOrchestrator
            import numpy as np
            import pandas as pd

            def _mk_klines(days=200):
                idx = pd.date_range("2025-10-01", periods=days, freq="1D", tz="UTC")
                np.random.seed(42)
                close = 70000 + np.cumsum(np.random.randn(days) * 500)
                return pd.DataFrame({
                    "open": close - 100, "high": close + 200,
                    "low": close - 200, "close": close,
                }, index=idx)

            def _agent(out, raise_exc=False):
                a = MagicMock()
                full = {**out}
                full.setdefault("status", "success")
                if raise_exc:
                    a.analyze.side_effect = RuntimeError("simulated")
                else:
                    a.analyze.return_value = full
                a._fallback_output.return_value = {**out, "status": "degraded"}
                return a

            kl = _mk_klines()
            ctx = {
                "_shared": {
                    "klines_1d": kl, "klines_4h": kl,
                    "current_close": 75749, "events_count_72h": 0,
                },
                "l1": {"computed_indicators": {}, "previous_l1": None},
                "l2": {"computed_indicators": {}, "previous_l2": None},
                "l3": {"risk_preview": {}, "current_state": "FLAT",
                       "previous_l3": None},
                "l4": {"computed_indicators": {}, "current_state": "FLAT",
                       "previous_l4": None},
                "l5": {"computed_macro_indicators": {},
                       "events_calendar_72h": [],
                       "extreme_event_flags": {},
                       "previous_l5": None},
                "master": {
                    "current_state": "FLAT", "previous_strategy_run": None,
                    "active_thesis": None, "cooldown_state": {"in_cooldown": False},
                    "fuse_state": {"in_14d_fuse": False,
                                   "in_thesis_cycle_fuse": False},
                },
            }
            agents = {
                "l1": _agent({"regime": "trend_up", "confidence": 0.85}),
                "l2": _agent({"stance": "bullish", "phase": "early",
                              "confidence": 0.85}),
                "l3": _agent({"opportunity_grade": "B", "confidence": 0.80}),
                "l4": _agent({"risk_tier": "moderate",
                              "hard_invalidation_levels": [
                                  {"price": 73000, "type": "swing_low",
                                   "distance_from_current_pct": -3.7},
                              ],
                              "risk_breakdown": {"crowding_risk": 30},
                              "confidence": 0.85}),
                "l5": _agent({}, raise_exc=True),
                "master": _agent({
                    "mode": "new_thesis",
                    "new_thesis": {
                        "thesis_id": "t_e2e",
                        "direction": "long",
                        "core_judgment": "做多",
                        "confidence_score": 70,
                        "break_conditions": [
                            "BTC 1d close < 73000",
                            "BTC 1d close < 70000",
                            "BTC 1d close < 68000",
                        ],
                        "is_60d_capped": False,
                    },
                    "narrative": "层间一致,做多",
                    "one_line_summary": "做多",
                    "evidence_ref": ["l2"],
                    "counter_arguments": ["..."],
                }),
            }
            orch = AIOrchestrator(agents=agents)
            result = orch.run_full_a(ctx)

            check("e2e L5 失败 → l5_output.macro_stance=risk_neutral",
                  result["layers"]["l5"].get("macro_stance") == "risk_neutral")
            check("e2e L5 失败 → master 仍跑(layers 含 master)",
                  "master" in result["layers"])
            rl = result.get("retry_log") or {}
            check("e2e retry_log.macro_fallback_applied=True",
                  rl.get("macro_fallback_applied") is True)
        except Exception as e:
            check(f"orchestrator e2e 跑通", False, detail=str(e)[:200])

        # ============================================================
        # Section H:validate_master_output 32 字段 + needs_retry 聚合
        # ============================================================
        print("\n=== H. validate_master_output 聚合 needs_retry ===")
        _, act = validate_master_output(
            {"mode": "silent_cooldown", "silent_reason": "x",
             "narrative": "无层间矛盾"},
            {"active_thesis": None, "cooldown_state": {"in_cooldown": False},
             "fuse_state": {"in_14d_fuse": False}, "l3_grade": "A"},
        )
        check("V21 触发 → activations.validator_needs_retry=True",
              act.get("validator_needs_retry") is True)
        hints = act.get("validator_retry_hints") or []
        check("activations.validator_retry_hints 非空(V21 hint)",
              len(hints) >= 1 and "V21" in hints[0])
        check("activations 总字段 = 32(28 v1.4 + 4 1.10-F retry meta)",
              len(act) == 32, detail=f"实际 {len(act)}")

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
