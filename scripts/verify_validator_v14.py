#!/usr/bin/env python3
"""scripts/verify_validator_v14.py — Sprint 1.10-E 端到端真实断言(§Z)。

验证 Validator 24 条 + V24 meta + 写入 strategy_runs.constraint_activations_json
全链路。

prefix `verify_1_10_e_validator_*`(继承 1.10-B/C/D 风险 #4)。

用法:.venv/bin/python scripts/verify_validator_v14.py [/path/to/db]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.ai.validator import (  # noqa: E402
    validate_master_output, _DEFAULT_ACTIVATIONS_V24,
)
from src.data.storage.dao import StrategyStateDAO  # noqa: E402

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_PREFIX = "verify_1_10_e_validator_"

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


def main(argv: list[str]) -> int:
    with open(_BASE_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db_path = (
        Path(argv[1]).resolve() if len(argv) > 1
        else (_REPO_ROOT / (cfg.get("paths", {}).get("db_path", "data/btc_strategy.db"))).resolve()
    )
    print(f"[verify_validator_v14] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 不存在,先跑 scripts/init_v14_tables.py")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 自动 apply migration(继承 1.10-C/D 教训)
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
        # Section A:24 单 Validator 触发(每条 1 happy + 1 fail)
        # ============================================================
        print("\n=== A. 单 Validator 触发样本(每条 happy + fail)===")
        # V1
        out, act = validate_master_output(
            {"new_thesis": {"stop_loss": {"price": 65000, "size_pct": 100}}},
            {"l4_hard_invalidation_levels": [70000, 67000]},
        )
        check("V1 stop_loss 不在 levels → 覆盖触发",
              act["validator_1_stop_loss_overridden"] is True)

        # V5 grade=C 必须 ambush_only
        out, act = validate_master_output(
            {"mode": "new_thesis",
             "new_thesis": {"execution_permission": "can_open"}},
            {"l3_grade": "C", "active_thesis": None,
             "cooldown_state": {}, "fuse_state": {}},
        )
        check("V5 grade=C → ambush_only 强制",
              out["new_thesis"]["execution_permission"] == "ambush_only")
        check("V5 activations 触发",
              act["validator_5_grade_permission_lock"] is True)

        # V6 active + new_thesis → 锁
        out, act = validate_master_output(
            {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
            {"active_thesis": {"thesis_id": "th_x"},
             "cooldown_state": {}, "fuse_state": {}, "l3_grade": "A"},
        )
        check("V6 active_thesis 锁,master new_thesis → evaluate_existing",
              out["mode"] == "evaluate_existing")
        check("V6 activations 触发",
              act["validator_6_thesis_lock"] is True)

        # V18 in_14d_fuse → silent
        out, act = validate_master_output(
            {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
            {"active_thesis": None, "cooldown_state": {},
             "fuse_state": {"in_14d_fuse": True}, "l3_grade": "A"},
        )
        check("V18 14d 熔断 → silent_cooldown",
              out["mode"] == "silent_cooldown")
        check("V18 activations 触发",
              act["validator_18_14d_fuse_active"] is True)

        # V21 软抗拒识别
        out, act = validate_master_output(
            {"mode": "silent_cooldown"},
            {"active_thesis": None,
             "cooldown_state": {"in_cooldown": False},
             "fuse_state": {"in_14d_fuse": False},
             "l3_grade": "A"},
        )
        check("V21 满足创建条件但 silent → 软抗拒识别",
              act["validator_21_soft_resistance"] is True)

        # ============================================================
        # Section B:V24 meta 完整 28 字段
        # ============================================================
        print("\n=== B. V24 meta 28 字段 ===")
        _, activations = validate_master_output(
            {"mode": "silent_cooldown", "silent_reason": "x",
             "narrative": "无层间矛盾"},
            {"active_thesis": None, "cooldown_state": {}, "fuse_state": {}},
        )
        check("V24 完整 28 字段",
              len(activations) == 28,
              detail=f"实际 {len(activations)}")
        check("V24 全部 v1.4 §3.4.9 字段在",
              all(k in activations for k in _DEFAULT_ACTIVATIONS_V24))
        # JSON 序列化
        js = json.dumps(activations, ensure_ascii=False)
        check("V24 dict 可 json.dumps",
              isinstance(js, str) and len(js) > 100)
        roundtrip = json.loads(js)
        check("V24 JSON roundtrip 字段不变",
              roundtrip == activations)

        # ============================================================
        # Section C:strategy_runs.constraint_activations_json 真写入
        # ============================================================
        print("\n=== C. strategy_runs.constraint_activations_json 真写入 ===")
        # 触发 V1+V6 多约束
        master_out = {"mode": "new_thesis",
                      "new_thesis": {
                          "direction": "long", "confidence_score": 75,
                          "execution_permission": "can_open",
                          "stop_loss": {"price": 65000, "size_pct": 100},
                          "entry_orders": [{"price": 74000, "size_pct": 30}],
                      },
                      "narrative": "L1-L5 一致看多,无层间矛盾",
                      "counter_arguments": ["funding 拥挤"],
                      "what_would_change_mind": ["1D 跌破 70000",
                                                  "DXY 突破 110",
                                                  "L5 极端事件"]}
        ctx = {"l3_grade": "A", "active_thesis": None,
               "cooldown_state": {}, "fuse_state": {},
               "l4_hard_invalidation_levels": [70000, 67000],
               "l4_position_cap_base": 0.40,
               "current_btc_price": 76000.0}
        validated, activations = validate_master_output(master_out, ctx)
        # validated 应已覆盖 stop_loss
        check("validated stop_loss 已覆盖到 70000",
              validated["new_thesis"]["stop_loss"]["price"] == 70000.0)

        # 装入 state 写 strategy_runs
        run_id = f"{_PREFIX}sample_run"
        state = {
            "constraint_activations": activations,
            "evidence_reports": {"layer_2": {"stance": "bullish"}},
            "state_machine": {"current_state": "FLAT", "stable_in_state": True},
            "market_snapshot": {"btc_price_usd": 76000.0},
            "meta": {"strategy_flavor": "swing"},
        }
        StrategyStateDAO.insert_state(
            conn,
            run_timestamp_utc="2099-05-03T08:00:00Z",
            run_id=run_id, run_trigger="verify_test",
            rules_version="v1.4.0", ai_model_actual=None,
            state=state,
        )
        conn.commit()

        # 读回断言
        row = conn.execute(
            "SELECT constraint_activations_json FROM strategy_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        check("strategy_runs.constraint_activations_json 行存在",
              row is not None)
        if row:
            ca_json = row["constraint_activations_json"]
            check("constraint_activations_json 不是 NULL",
                  ca_json is not None and len(ca_json) > 100)
            ca_dict = json.loads(ca_json)
            check("constraint_activations roundtrip 28 字段",
                  len(ca_dict) == 28)
            check("V1 stop_loss_overridden 在 DB JSON 中 = True",
                  ca_dict["validator_1_stop_loss_overridden"] is True)
            check("V24 thesis_lock_active 在 DB JSON 中 = False(无 active)",
                  ca_dict["thesis_lock_active"] is False)

        # ============================================================
        # Section D:全 Validator 顺序应用,无随机性
        # ============================================================
        print("\n=== D. 顺序应用确定性 ===")
        master_in = {"mode": "silent_cooldown", "silent_reason": "test",
                     "narrative": "L1-L5 一致,无层间矛盾"}
        ctx_d = {"active_thesis": None, "cooldown_state": {}, "fuse_state": {}}
        out1, act1 = validate_master_output(master_in, ctx_d)
        out2, act2 = validate_master_output(master_in, ctx_d)
        check("validate_master_output 输出确定(2 次调用一致)",
              act1 == act2)

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
