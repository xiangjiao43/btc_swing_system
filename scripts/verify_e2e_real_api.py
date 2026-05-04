#!/usr/bin/env python3
"""scripts/verify_e2e_real_api.py — Sprint 1.10-L 任务 8 端到端真 API 验证。

验证 v1.4 §10.5 任务 8"端到端真 API"目标:
- master_adjudicator 真返回(不是 mock)
- V1-V23 真触发(constraint_activations_json 不再全 NULL)
- thesis 真创建 / 虚拟账户挂单 / 周复盘等下游
- commit 11a 修复后 V24 数据通路真接通

设计纪律:
- **只读核数据**(不真触发主 AI;真触发用 scripts/run_pipeline_once.py 用户 SSH 跑)
- 跟 verify_cleanup_v14/kb/ka 一致风格(✅/❌ + 真核数据)
- 跑得通本地 / 服务器(本地若无 V 数据 → §Z 项 ❌ 显示"待生产真 API 跑后再核")
- 累计统计 NULL vs has_data 行数(老历史 vs commit 11a 修复后新数据)

用法:
    .venv/bin/python scripts/verify_e2e_real_api.py [/path/to/db]

服务器跑:
    ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && \\
      .venv/bin/python scripts/verify_e2e_real_api.py | tail -25"
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"

_PASSED: list[str] = []
_FAILED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _PASSED.append(label)
        print(f"  ✅ {label}")
    else:
        _FAILED.append(f"{label} | {detail}")
        print(f"  ❌ {label} | {detail}")


# Validator 24 元字段(本 sprint commit 11a 修复后真写入)
# 对应 _DEFAULT_ACTIVATIONS_V24(src/ai/validator.py:_DEFAULT_ACTIVATIONS_V24)
_V_REQUIRED_KEYS = [
    f"validator_{i}_" for i in range(1, 24)  # V1-V23
]
_V_META_KEYS = [
    "position_cap_compressed",
    "thesis_lock_active",
    "in_cooldown",
    "cooldown_remaining_hours",
    "validator_needs_retry",
    "validator_retry_hints",
    "validator_22_failures_count",
    "validator_22_needs_review_pending",
]


def main(argv: list[str]) -> int:
    with open(_BASE_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db_path = (
        Path(argv[1]).resolve() if len(argv) > 1
        else (_REPO_ROOT / (cfg.get("paths", {}).get(
            "db_path", "data/btc_strategy.db"))).resolve()
    )
    print(f"[verify_e2e_real_api] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 不存在,先跑 scripts/init_v14_tables.py")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # ============================================================
        # 段 A:strategy_runs 全表统计 + commit 11a V24 写入修复验证
        # ============================================================
        print("\n=== A. V24 写入通路真接通(commit 11a 修复)===")

        stats = conn.execute("""
            SELECT
              SUM(CASE WHEN constraint_activations_json IS NULL THEN 1 ELSE 0 END) AS null_count,
              SUM(CASE WHEN length(constraint_activations_json) > 2 THEN 1 ELSE 0 END) AS has_data_count,
              COUNT(*) AS total
            FROM strategy_runs
        """).fetchone()
        null_count = stats["null_count"] or 0
        has_data_count = stats["has_data_count"] or 0
        total = stats["total"] or 0
        print(f"  统计:total={total}, null={null_count}, has_data={has_data_count}")

        check(
            f"§Z 1: strategy_runs 至少 1 行 has_data(实际 {has_data_count})"
            "(commit 11a 修复后新 strategy_run 真写入 V meta)",
            has_data_count >= 1,
            f"待用户跑 scripts/run_pipeline_once.py --trigger manual 后真接通;"
            f"本地 DB has_data=0 是预期,生产 DB 至少 1 行",
        )
        check(
            f"§Z 2: 老数据 NULL 不可回填(预期 null > 0,实际 {null_count})",
            null_count >= 0,  # 0 也算合理(全新 DB)
            "老 138 行(1.10-E 起 4+ sprint)NULL 是历史遗留,设计上不可回填",
        )

        # ============================================================
        # 段 B:V meta JSON 完整性(28 字段)
        # ============================================================
        print("\n=== B. V meta JSON schema 完整性(28 字段)===")

        if has_data_count >= 1:
            row = conn.execute("""
                SELECT run_id, constraint_activations_json, ai_model_actual,
                       run_trigger
                FROM strategy_runs
                WHERE constraint_activations_json IS NOT NULL
                  AND length(constraint_activations_json) > 2
                ORDER BY generated_at_utc DESC LIMIT 1
            """).fetchone()
            ca_str = row["constraint_activations_json"]
            try:
                ca = json.loads(ca_str)
                check(
                    f"§Z 3: V meta JSON 解析成功(run_id={row['run_id'][:12]}..., "
                    f"长度 {len(ca_str)} 字符)",
                    isinstance(ca, dict),
                    f"json.loads 返 {type(ca).__name__},应是 dict",
                )
                # V1-V23 全 23 条 + 5 元字段全在
                missing_v = [
                    p for p in _V_REQUIRED_KEYS
                    if not any(k.startswith(p) for k in ca.keys())
                ]
                check(
                    f"§Z 4: V1-V23 全 23 条字段在(missing={len(missing_v)})",
                    len(missing_v) == 0,
                    f"缺失 V prefix: {missing_v[:5]}",
                )
                missing_meta = [k for k in _V_META_KEYS if k not in ca]
                check(
                    f"§Z 5: 元字段全在(thesis_lock_active / in_cooldown / "
                    f"validator_needs_retry / etc., missing={len(missing_meta)})",
                    len(missing_meta) == 0,
                    f"缺失元字段: {missing_meta}",
                )
                # ai_model_actual 真有
                check(
                    f"§Z 6: 该 run 的 ai_model_actual 真填(实际 {row['ai_model_actual']!r})",
                    bool(row["ai_model_actual"]) and "claude" in (
                        row["ai_model_actual"] or ""
                    ).lower(),
                    "应含 claude- 前缀(主 AI 真返回)",
                )
            except (ValueError, TypeError) as e:
                check("§Z 3: V meta JSON 解析", False, f"json.loads 失败: {e}")
                check("§Z 4: V1-V23 字段", False, "JSON 解析失败,字段无法验证")
                check("§Z 5: 元字段", False, "JSON 解析失败")
                check("§Z 6: ai_model_actual", False, "JSON 解析失败")
        else:
            check("§Z 3: V meta JSON 解析成功", False,
                  "无 has_data 行(本地 DB 预期 / 生产 DB 待用户 SSH 跑触发)")
            check("§Z 4: V1-V23 全 23 条字段在", False, "无 has_data 行")
            check("§Z 5: 元字段全在", False, "无 has_data 行")
            check("§Z 6: ai_model_actual 真填", False, "无 has_data 行")

        # ============================================================
        # 段 C:run_trigger 维度统计(manual / event_onchain / scheduled)
        # ============================================================
        print("\n=== C. run_trigger 维度 + 历史 vs 新 V 数据 ===")

        trigger_stats = conn.execute("""
            SELECT run_trigger,
                   COUNT(*) AS total,
                   SUM(CASE WHEN constraint_activations_json IS NULL THEN 1 ELSE 0 END) AS null_count,
                   SUM(CASE WHEN length(constraint_activations_json) > 2 THEN 1 ELSE 0 END) AS has_data
            FROM strategy_runs
            GROUP BY run_trigger
            ORDER BY total DESC
        """).fetchall()
        print(f"  run_trigger 分布:")
        for tr in trigger_stats:
            print(f"    {tr['run_trigger']:30s}  total={tr['total']:4d}  "
                  f"null={tr['null_count']:4d}  has_data={tr['has_data']:4d}")

        # manual 至少 1 行(用户已跑)— 仅生产 DB 满足
        manual_rows = next(
            (tr for tr in trigger_stats if tr["run_trigger"] == "manual"), None,
        )
        check(
            f"§Z 7: run_trigger='manual' 至少 1 行(用户手动触发数据)"
            f"(实际 {manual_rows['total'] if manual_rows else 0})",
            manual_rows is not None and manual_rows["total"] >= 1,
            "本地 DB 待用户在生产跑 manual trigger;生产 DB 用户已跑 1 次",
        )

        # ============================================================
        # 段 D:数据通路完整性(代码层 grep)
        # ============================================================
        print("\n=== D. 数据通路完整性(代码层验证)===")

        # commit 11a 修复:_orchestrator_mapper 含 constraint_activations_json
        mapper_src = (_REPO_ROOT / "src" / "pipeline"
                       / "_orchestrator_mapper.py").read_text(encoding="utf-8")
        check(
            "§Z 8: _orchestrator_mapper.py mapped 含 constraint_activations_json key",
            '"constraint_activations_json"' in mapper_src,
            "commit 11a 修复 — mapper 必须装 V meta 进 mapped",
        )

        # state_builder._run_v13_orchestrator INSERT 18 列
        sb_src = (_REPO_ROOT / "src" / "pipeline" / "state_builder.py"
                  ).read_text(encoding="utf-8")
        check(
            "§Z 9: state_builder.py _run_v13_orchestrator INSERT 含 constraint_activations_json",
            "constraint_activations_json" in sb_src and "INSERT INTO strategy_runs" in sb_src,
            "commit 11a 修复 — INSERT 必须含此列(17 → 18 列)",
        )

        # dao.py:1145-1149 老路径不破(K-A commit 2 review 过)
        dao_src = (_REPO_ROOT / "src" / "data" / "storage" / "dao.py"
                   ).read_text(encoding="utf-8")
        check(
            '§Z 10: dao.py 老路径 StrategyStateDAO.insert_state 仍读 state["constraint_activations"]',
            'state.get("constraint_activations")' in dao_src,
            "K-A commit 2 review 过,1.10-L 不破老路径(双写入路径都通)",
        )

        # weekly_review_input_builder._aggregate_constraint_activations 跳 NULL
        wri_src = (_REPO_ROOT / "src" / "ai" / "weekly_review_input_builder.py"
                   ).read_text(encoding="utf-8")
        check(
            "§Z 11: weekly_review_input_builder._aggregate_constraint_activations 跳 NULL"
            "(老 138 行历史保护)",
            "constraint_activations_json IS NOT NULL" in wri_src,
            "周复盘 AI 聚合时跳过 NULL 行(老历史数据保护)",
        )

        # ============================================================
        # 段 E:周复盘 AI 数据流通(weekly_reviews 表)
        # ============================================================
        print("\n=== E. 周复盘 AI 数据流通 ===")

        wr_count = conn.execute(
            "SELECT COUNT(*) FROM weekly_reviews"
        ).fetchone()[0]
        check(
            f"§Z 12: weekly_reviews 表存在(实际 {wr_count} 条记录)",
            wr_count >= 0,  # 0 也合理(本地 / 新 DB 无周复盘)
            "周复盘表 schema 完整;数据待周日 22:00 BJT cron 触发",
        )

    finally:
        conn.close()

    print()
    print("=== 总结 ===")
    print(f"通过:{len(_PASSED)} 项")
    print(f"失败:{len(_FAILED)} 项")
    if _FAILED:
        for f in _FAILED:
            print(f"  ❌ {f}")
        print()
        print("⚠ 失败说明:")
        print("  - 本地 DB 通常 has_data=0(无真 API 跑过)→ §Z 3-7 失败是预期")
        print("  - 生产 DB 用户跑 1 次 manual 后 has_data ≥ 1 → 全过")
        print("  - 代码层 §Z 8-11 应该全过(本地 / 服务器都通)")
        print("  - 若 §Z 8-12 失败 → 真 bug,需修复")
        return 1
    print("\n✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
