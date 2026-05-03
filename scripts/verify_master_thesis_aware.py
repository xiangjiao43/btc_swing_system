#!/usr/bin/env python3
"""scripts/verify_master_thesis_aware.py — Sprint 1.10-D 端到端轻量验证(§Z)。

D2=a 锁定:**不调真 master AI**(留 1.10-L 端到端测试)。
本 verify 只验证 master_input_builder 装配 + 输出结构 + thesis-aware 字段就位。

prefix `verify_1_10_d_master_*`(继承 1.10-B/C 风险 #4 教训:稳定 prefix +
pre/post cleanup,即使中间报错也不污染 DB)。

用法:
    .venv/bin/python scripts/verify_master_thesis_aware.py [/path/to/db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.ai.master_input_builder import build_master_input  # noqa: E402
from src.ai.agents.master_adjudicator import (  # noqa: E402
    MasterAdjudicator, VALID_MODES,
)
from src.data.storage.dao import (  # noqa: E402
    ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy.fuse_monitor import (  # noqa: E402
    record_thesis_cycle, record_channel_c_use,
)


_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_PREFIX = "verify_1_10_d_master_"
_TEST_THESIS_ID = f"{_PREFIX}thesis"
_TEST_RUN_ID = f"{_PREFIX}run"

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
            "DELETE FROM virtual_orders WHERE thesis_id LIKE ?", (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM theses WHERE thesis_id LIKE ?", (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM virtual_account WHERE snapshot_id LIKE ?",
            (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM fuse_events WHERE thesis_id LIKE ? "
            "OR (event_type='14d_fuse_triggered' AND metadata_json LIKE ?)",
            (f"{_PREFIX}%", f"%{_PREFIX}%"),
        )
        conn.execute(
            "DELETE FROM system_states WHERE related_thesis_id LIKE ? "
            "OR reason LIKE ?",
            (f"{_PREFIX}%", f"%{_PREFIX}%"),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"  ⚠ cleanup 部分失败:{e}")


def main(argv: list[str]) -> int:
    with open(_BASE_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db_path = (
        Path(argv[1]).resolve() if len(argv) > 1
        else (_REPO_ROOT / (cfg.get("paths", {}).get("db_path", "data/btc_strategy.db"))).resolve()
    )
    print(f"[verify_master_thesis_aware] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 不存在,先跑 scripts/init_v14_tables.py")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 自动 apply migrations(继承 1.10-C 教训)
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

        print("\n=== 1. setup:active thesis + 持仓 + 挂单 + fuse 历史 ===")
        # 创建 active thesis
        ThesesDAO.create(
            conn, thesis_id=_TEST_THESIS_ID,
            created_at_run_id=_TEST_RUN_ID,
            created_at_utc="2026-04-25T08:00:00Z",
            direction="long",
            core_logic="verify_1_10_d 测试 thesis",
            confidence_score=72,
            break_conditions=[
                "1D 收盘跌破 70000",
                "DXY 突破 110 持续 3 天",
                "L5 极端事件触发",
            ],
            lifecycle_stage="opened",
        )
        # 写持仓快照(future date 保证是 latest,继承 1.10-C 教训)
        VirtualAccountDAO.insert_snapshot(
            conn, snapshot_id=f"{_PREFIX}snap",
            run_id=_TEST_RUN_ID,
            snapshot_at_utc="2099-04-30T08:00:00Z",
            btc_price_at_snapshot=74000.0,
            initial_capital=100000.0,
            available_cash=80000.0,
            long_position_usdt=20000.0,
            long_avg_price=74000.0,
            long_btc_amount=20000.0/74000.0,
            total_equity=100000.0,
        )
        # 创建 2 个 pending 挂单(stop_loss + take_profit)
        VirtualOrdersDAO.create_order(
            conn, order_id=f"{_PREFIX}o_sl",
            thesis_id=_TEST_THESIS_ID,
            direction="long", order_type="stop_loss",
            price=67000.0, size_pct=1.00, size_usdt=20000.0,
            created_at_utc="2026-04-25T08:00:00Z",
            expires_at_utc="2026-12-01T00:00:00Z",
        )
        VirtualOrdersDAO.create_order(
            conn, order_id=f"{_PREFIX}o_tp",
            thesis_id=_TEST_THESIS_ID,
            direction="long", order_type="take_profit",
            price=80000.0, size_pct=0.50, size_usdt=10000.0,
            created_at_utc="2026-04-25T08:00:00Z",
            expires_at_utc="2026-12-01T00:00:00Z",
        )
        # 写 1 个 fuse_event(thesis_cycle)
        record_thesis_cycle(conn, f"{_PREFIX}old_th",
                            "2026-05-01T08:00:00Z",
                            metadata={"prefix": _PREFIX})
        conn.commit()
        print("  ✅ setup 完成")

        print("\n=== 2. 调 build_master_input ===")
        layer_outs = {
            "l1": {"regime": "trend_up", "confidence": 0.85},
            "l2": {"stance": "bullish", "stance_confidence_tier": "high"},
            "l3": {"opportunity_grade": "A", "execution_permission": "active_open"},
            "l4": {"risk_level": "elevated", "position_cap_pct": 0.40,
                   "hard_invalidation_chosen": 67000.0},
            "l5": {"macro_stance": "neutral", "headwind_score": 30},
        }
        master_input = build_master_input(
            conn, layer_outputs=layer_outs,
            current_btc_price=76000.0,
            now_utc="2026-05-03T08:00:00Z",
        )

        print("\n=== 3. 断言 v1.4 §3.3.6 input schema 全字段 ===")
        # L1-5
        for layer in ("l1_output", "l2_output", "l3_output", "l4_output", "l5_output"):
            check(f"{layer} 字段在", master_input.get(layer) is not None,
                  detail="orchestrator 透传缺失")
        # thesis-aware 7 字段
        check("active_thesis 不为 None", master_input.get("active_thesis") is not None)
        ath = master_input["active_thesis"]
        check("active_thesis.thesis_id 正确",
              ath.get("thesis_id") == _TEST_THESIS_ID)
        check("active_thesis.direction = long", ath.get("direction") == "long")
        check("active_thesis.confidence_score = 72", ath.get("confidence_score") == 72)
        check("active_thesis.break_conditions ≥ 3",
              len(ath.get("break_conditions") or []) >= 3)
        check("active_thesis.lifecycle_stage = opened",
              ath.get("lifecycle_stage") == "opened")
        check("active_thesis.created_days_ago > 0",
              (ath.get("created_days_ago") or 0) > 0)
        check("active_thesis.is_60d_capped = False",
              ath.get("is_60d_capped") is False)

        cp = master_input.get("current_position")
        check("current_position 不为 None",
              cp is not None,
              detail="持仓快照应被读到")
        if cp:
            check("current_position.long_position_usdt = 20000",
                  cp.get("long_position_usdt") == 20000.0)
            check("current_position.long_pnl_pct ≈ 2.7%(76000/74000-1)",
                  abs((cp.get("long_pnl_pct") or 0) - 2.7027) < 0.01)

        po = master_input.get("pending_orders") or []
        check("pending_orders 数量 = 2(sl + tp)", len(po) == 2)
        order_types = {o.get("type") for o in po}
        check("pending_orders 含 stop_loss + take_profit",
              order_types == {"stop_loss", "take_profit"})

        cs = master_input.get("cooldown_state") or {}
        check("cooldown_state.in_cooldown = False(无 closed thesis)",
              cs.get("in_cooldown") is False)

        fs = master_input.get("fuse_state") or {}
        check("fuse_state.thesis_cycles_in_14d = 1(测试写的)",
              fs.get("thesis_cycles_in_14d") == 1)
        check("fuse_state.in_14d_fuse = False(只 1 次,未 ≥ 2)",
              fs.get("in_14d_fuse") is False)

        last = master_input.get("last_5_assessments") or []
        check("last_5_assessments 是 list", isinstance(last, list))

        print("\n=== 4. 断言 master_adjudicator v1.4 接口 ===")
        # _build_user_prompt 应能消费 master_input 不抛异常
        agent = MasterAdjudicator()
        prompt = agent._build_user_prompt(master_input)
        check("_build_user_prompt 返字符串", isinstance(prompt, str) and len(prompt) > 100)
        check("prompt 含 'active_thesis'", "active_thesis" in prompt)
        check("prompt 含 'fuse_state'", "fuse_state" in prompt)
        check("prompt 含 'L1' / 'l1_output'", "l1_output" in prompt)

        # _fallback_output 验证
        fb = agent._fallback_output()
        check("fallback.mode = silent_cooldown", fb.get("mode") == "silent_cooldown")

        # thesis_aware_fallback 验证
        fb_active = MasterAdjudicator.thesis_aware_fallback(has_active_thesis=True)
        check("thesis_aware_fallback(has=True).mode = evaluate_existing",
              fb_active.get("mode") == "evaluate_existing")
        fb_no_thesis = MasterAdjudicator.thesis_aware_fallback(has_active_thesis=False)
        check("thesis_aware_fallback(has=False).mode = silent_cooldown",
              fb_no_thesis.get("mode") == "silent_cooldown")

        # validate_mode 验证
        ok1, _ = MasterAdjudicator.validate_mode(
            {"mode": "evaluate_existing"}, has_active_thesis=True,
        )
        check("validate_mode evaluate_existing + has_thesis = ok", ok1)
        ok2, err2 = MasterAdjudicator.validate_mode(
            {"mode": "new_thesis"}, has_active_thesis=True,
        )
        check("validate_mode new_thesis + has_thesis = invalid (Validator 6)",
              not ok2 and "new_thesis" in (err2 or ""))

        print("\n=== 5. VALID_MODES 常量 ===")
        check("VALID_MODES 与 v1.4 §3.3.6 三选一一致",
              set(VALID_MODES) == {"evaluate_existing", "new_thesis", "silent_cooldown"})

    finally:
        print("\n=== 6. cleanup ===")
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
    print("\n✅ 全部通过(D2=a:不调真 master AI,留 1.10-L 端到端)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
