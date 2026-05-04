#!/usr/bin/env python3
"""scripts/verify_cleanup_kb.py — Sprint 1.10-K-B §Z 双重验证。

对齐 1.10-J verify_cleanup_v14.py 风格 + 继承 1.10-I commit 7 §Z 局限教训
(只字符串 grep 不够,需真启动验证)。

验证 1.10-K-B commits 1-6 完整链路:
- commit 2:master_adjudicator.txt 加 4 条 hard constraints(V3 / V9 / V21 / V23)
- commit 3:migration 015 工具就绪 + opt-in 状态(_drop_column_or_recreate /
  drop_obsolete_columns / 自适应 sqlite version)
- commit 4:normalize_state.py 三态(v14 / v13 / v12)+ explicit schema_version 支持
- commit 5:ThesesDAO docstring 对齐 + AlertsDAO mark_acknowledged / mark_notified

prefix `verify_1_10_kb_`(隔离测试数据)。

⚠ 注意:本脚本验证"工具就绪",不验证 "migration 015 真跑了"。
方案 A 延后:30+ 处写入方未清前 drop_obsolete_columns() 不该跑,
留 1.10-K-A / 1.10-K-C 处理后再 opt-in 调用。

用法:.venv/bin/python scripts/verify_cleanup_kb.py [/path/to/db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.api.app import create_app  # noqa: E402
from src.data.storage.dao import AlertsDAO, ThesesDAO  # noqa: E402
from src.web_helpers.normalize_state import (  # noqa: E402
    _detect_schema, normalize_state,
)

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_PREFIX = "verify_1_10_kb_"

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
    """清 verify 测试数据(prefix 隔离)。"""
    try:
        conn.execute(
            "DELETE FROM alerts WHERE alert_type LIKE ? OR message LIKE ?",
            (f"{_PREFIX}%", f"{_PREFIX}%"),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"  ⚠ cleanup 失败:{e}")


def main(argv: list[str]) -> int:
    with open(_BASE_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db_path = (
        Path(argv[1]).resolve() if len(argv) > 1
        else (_REPO_ROOT / (cfg.get("paths", {}).get(
            "db_path", "data/btc_strategy.db"))).resolve()
    )
    print(f"[verify_cleanup_kb] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 不存在,先跑 scripts/init_v14_tables.py")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
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
        # Section A:commit 2 prompt 4 V hard constraints
        # ============================================================
        print("\n=== A. commit 2 master_adjudicator.txt 4 V 硬约束 ===")
        prompt_path = (_REPO_ROOT / "src" / "ai" / "agents" / "prompts"
                       / "master_adjudicator.txt")
        prompt = prompt_path.read_text(encoding="utf-8")
        line_count = len(prompt.splitlines())
        check(f"master_adjudicator.txt 行数 ≤ 220(实际 {line_count})",
              line_count <= 220,
              f"实际 {line_count} 行,超出 30 行预算")
        check("prompt 含 'Validator 3'(V3 entry size sum)",
              "Validator 3" in prompt)
        check("prompt 含 'Validator 9'(V9 break_distance)",
              "Validator 9" in prompt)
        check("prompt 含 'Validator 21'(V21 软抗拒)",
              "Validator 21" in prompt)
        check("prompt 含 'Validator 23'(V23 conflict_resolution)",
              "Validator 23" in prompt)
        check("prompt 含关键词 '软抗拒'(V21 行为约束)",
              "软抗拒" in prompt)
        check("prompt 含关键词 '层间' 或 '矛盾'(V23 narrative 一致性)",
              "层间" in prompt or "矛盾" in prompt)
        check("prompt 含 'size_pct' + '100'(V3 entry sum 上限)",
              "size_pct" in prompt and "100" in prompt)
        check("prompt 含 '20%' 或 '≤ 20'(V9 价格类距 20%)",
              "20%" in prompt or "≤ 20" in prompt)

        # ============================================================
        # Section B:commit 3 migration 015 工具就绪 + opt-in
        # ============================================================
        print("\n=== B. commit 3 migration 015 工具就绪(opt-in 不自动跑) ===")
        from scripts.init_v14_tables import (
            _drop_column_or_recreate,
            _supports_native_drop_column,
            apply_migration,
            drop_obsolete_columns,
        )
        check("scripts/init_v14_tables.py:drop_obsolete_columns 存在",
              callable(drop_obsolete_columns))
        check("scripts/init_v14_tables.py:_drop_column_or_recreate 存在",
              callable(_drop_column_or_recreate))
        check("scripts/init_v14_tables.py:_supports_native_drop_column 存在",
              callable(_supports_native_drop_column))
        check(f"本机 sqlite_version={sqlite3.sqlite_version} ≥ 3.35.0",
              _supports_native_drop_column(),
              f"本机 {sqlite3.sqlite_version} < 3.35.0,需走 recreate 路径")
        check("migrations/015_v14_drop_old_columns.sql 文件存在",
              (_REPO_ROOT / "migrations" / "015_v14_drop_old_columns.sql").exists())

        # opt-in 安全门:apply_migration 源码不调 drop_obsolete_columns
        init_src = (_REPO_ROOT / "scripts" / "init_v14_tables.py").read_text(
            encoding="utf-8",
        )
        # apply_migration 函数体内不应调 drop_obsolete_columns
        # 简化判定:全文 drop_obsolete_columns 调用应只在函数定义,
        # 不在 apply_migration 函数体内
        # apply_migration 定义结束后到下一个 def 之间不应含 drop_obsolete_columns
        import re
        m = re.search(
            r"def apply_migration\(conn:[^)]+\)[^:]*:(.*?)\n(?:def |\Z)",
            init_src, re.DOTALL,
        )
        check(
            "apply_migration() 函数体内 **未** 调用 drop_obsolete_columns(opt-in 安全门)",
            m is not None and "drop_obsolete_columns" not in m.group(1),
            "apply_migration 不能自动调 drop_obsolete_columns(防写者未清崩溃)",
        )

        # 端到端烟测(更新于 1.10-K-A commit 4):
        # K-A commit 2 已从 schema.sql 删两列定义,K-A commit 4 已 ALTER 删生产 DB 列。
        # 新烟测验证:
        #  1. 新建 in-memory(schema.sql 不再含两列)→ apply_migration → 两列从未存在
        #  2. 模拟"老 schema 还有列"场景(手动 ALTER ADD)→ drop_obsolete_columns → 两列删
        smoke_conn = sqlite3.connect(":memory:")
        smoke_conn.row_factory = sqlite3.Row
        with open("src/data/storage/schema.sql", encoding="utf-8") as f:
            smoke_conn.executescript(f.read())
        apply_migration(smoke_conn)
        cols_after_apply = [r[1] for r in smoke_conn.execute(
            "PRAGMA table_info(strategy_runs)").fetchall()]
        check("烟测:apply_migration 后 strategy_runs **不再含** observation_category"
              "(K-A commit 2 schema.sql 已删定义)",
              "observation_category" not in cols_after_apply,
              f"实际列:{cols_after_apply}")
        check("烟测:apply_migration 后 strategy_runs **不再含** cold_start",
              "cold_start" not in cols_after_apply)
        check(f"烟测:strategy_runs 列数 = 19(K-A 后,实际 {len(cols_after_apply)})",
              len(cols_after_apply) == 19)
        # 模拟老 DB(K-A 之前)→ drop_obsolete_columns 仍可工作(K-A commit 4 真跑过的路径)
        smoke_conn.execute("ALTER TABLE strategy_runs ADD COLUMN observation_category TEXT")
        smoke_conn.execute("ALTER TABLE strategy_runs ADD COLUMN cold_start INTEGER DEFAULT 0")
        smoke_conn.commit()
        res = drop_obsolete_columns(smoke_conn)
        cols_after_drop = [r[1] for r in smoke_conn.execute(
            "PRAGMA table_info(strategy_runs)").fetchall()]
        check("烟测:drop_obsolete_columns 仍可 DROP(模拟老 schema → K-A commit 4 路径)",
              "observation_category" not in cols_after_drop and "cold_start" not in cols_after_drop,
              f"实际结果:{res} / 列:{cols_after_drop}")
        smoke_conn.close()

        # ============================================================
        # Section C:commit 4 normalize_state v14 三态
        # ============================================================
        print("\n=== C. commit 4 normalize_state.py 三态 + explicit schema_version ===")
        # default v14 路径(layered 但无显式字段)
        out_default = normalize_state(
            {"layers": {"l1": {"regime": "trend_up"},
                        "l2": {}, "l3": {}, "l4": {}, "l5": {}, "master": {}}},
            run_mode="ai_orchestrator",
        )
        check("default(layered + ai_orchestrator)→ schema_version='v14'",
              out_default["schema_version"] == "v14",
              f"实际 {out_default['schema_version']}")
        # explicit v13 backward compat
        out_v13 = normalize_state(
            {"schema_version": "v13",
             "layers": {"l1": {}, "l2": {}, "l3": {}, "l4": {}, "l5": {},
                        "master": {}}},
            run_mode="ai_orchestrator",
        )
        check("explicit schema_version='v13' → output 'v13'(backward compat)",
              out_v13["schema_version"] == "v13")
        # explicit v14
        out_v14 = normalize_state(
            {"schema_version": "v14",
             "layers": {"l1": {}, "l2": {}, "l3": {}, "l4": {}, "l5": {},
                        "master": {}}},
            run_mode="ai_orchestrator",
        )
        check("explicit schema_version='v14' → output 'v14'",
              out_v14["schema_version"] == "v14")
        # _detect_schema 直查
        check("_detect_schema({}, 'ai_orchestrator')='v14'(默认升级)",
              _detect_schema({}, "ai_orchestrator") == "v14")
        check("_detect_schema({'evidence_reports':{}}, None)='v12'",
              _detect_schema({"evidence_reports": {}}, None) == "v12")
        # normalize_state.py 源码不再 hardcode 'v13'
        ns_src = (_REPO_ROOT / "src" / "web_helpers"
                  / "normalize_state.py").read_text(encoding="utf-8")
        check(
            "normalize_state.py 源码不含 hardcoded \"schema_version\": \"v13\"",
            '"schema_version": "v13"' not in ns_src,
            "1.10-K-B commit 4 应已删除老 hardcode",
        )

        # ============================================================
        # Section D:commit 5 ThesesDAO docstring
        # ============================================================
        print("\n=== D. commit 5 ThesesDAO docstring 对齐统一 DAO 风格 ===")
        check("ThesesDAO.__doc__ 含 '统一 DAO 风格' 对齐说明",
              "统一 DAO 风格" in (ThesesDAO.__doc__ or ""))
        # 风格自检
        check("ThesesDAO.create 是 staticmethod",
              isinstance(ThesesDAO.__dict__.get("create"), staticmethod))
        check("ThesesDAO.update_assessment 是 staticmethod",
              isinstance(ThesesDAO.__dict__.get("update_assessment"),
                         staticmethod))
        check("ThesesDAO.close 是 staticmethod",
              isinstance(ThesesDAO.__dict__.get("close"), staticmethod))

        # ============================================================
        # Section E:commit 5 AlertsDAO mark_acknowledged / mark_notified
        # ============================================================
        print("\n=== E. commit 5 AlertsDAO mark_acknowledged / mark_notified ===")
        check("AlertsDAO.mark_acknowledged 存在",
              callable(getattr(AlertsDAO, "mark_acknowledged", None)))
        check("AlertsDAO.mark_notified 存在",
              callable(getattr(AlertsDAO, "mark_notified", None)))

        # 真 DB 端到端:insert → mark_acknowledged → mark_notified
        aid = AlertsDAO.insert_alert(
            conn, alert_type=f"{_PREFIX}e2e", severity="warning",
            message=f"{_PREFIX}e2e_test", raised_at_utc="2099-05-04T16:00:00Z",
        )
        conn.commit()
        check(f"真 DB:insert_alert 返回 id > 0(实际 {aid})", aid > 0)
        affected_a = AlertsDAO.mark_acknowledged(conn, aid)
        affected_n = AlertsDAO.mark_notified(conn, aid)
        conn.commit()
        check("真 DB:mark_acknowledged 返回 rowcount=1",
              affected_a == 1)
        check("真 DB:mark_notified 返回 rowcount=1",
              affected_n == 1)
        row = conn.execute(
            "SELECT acknowledged, notification_sent FROM alerts WHERE id=?",
            (aid,),
        ).fetchone()
        check("真 DB:acknowledged 列写入 1",
              row is not None and row["acknowledged"] == 1)
        check("真 DB:notification_sent 列写入 1",
              row is not None and row["notification_sent"] == 1)
        # 不存在 id graceful
        affected_z = AlertsDAO.mark_acknowledged(conn, 999_999_999)
        check("真 DB:mark_acknowledged(不存在 id)→ rowcount=0 不抛",
              affected_z == 0)

        # ============================================================
        # Section F:§Z 端到端启动验证(继承 1.10-I commit 7 教训)
        # ============================================================
        print("\n=== F. §Z 真启动 uvicorn TestClient + 页面渲染 ===")
        try:
            app = create_app()
            client = TestClient(app)
            r = client.get("/")
            check(f"GET / 状态码 200(实际 {r.status_code})",
                  r.status_code == 200)
            check("GET / body 含 'BTC' 字符(页面非空)",
                  "BTC" in r.text or "策略" in r.text)
            r2 = client.get("/api/strategy/latest")
            check(f"GET /api/strategy/latest 状态码 200/204(实际 {r2.status_code})",
                  r2.status_code in (200, 204))
        except Exception as e:
            check("uvicorn TestClient 启动 + GET 路由", False, str(e))

    finally:
        print("\n=== Cleanup ===")
        cleanup(conn)
        print("  ✅ cleanup 完成")
        conn.close()

    print()
    print("=== 总结 ===")
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
