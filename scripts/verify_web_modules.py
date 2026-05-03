#!/usr/bin/env python3
"""scripts/verify_web_modules.py — Sprint 1.10-I 端到端真实断言(§Z)。

验证 1.10-I 完整链路:11 个新 API + GET /strategy/current 4 字段扩展 +
5 个 web 模块 + RP 红色横幅 + 失败状态显示 + ThesesDAO.get_by_id +
HealthResponse.review_pending。

prefix `verify_1_10_i_*`(继承 1.10-B/C/D/E/F/G/H 风险 #4)。

用法:.venv/bin/python scripts/verify_web_modules.py [/path/to/db]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.api.app import create_app  # noqa: E402
from src.data.storage.connection import get_connection  # noqa: E402

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_INDEX_HTML = _REPO_ROOT / "web" / "index.html"
_APP_JS = _REPO_ROOT / "web" / "assets" / "app.js"
_PREFIX = "verify_1_10_i_"

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
    """清 verify 测试数据(2099-XX 时间戳隔离)。"""
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
            "DELETE FROM virtual_account WHERE snapshot_id LIKE ?",
            (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM weekly_reviews WHERE week_start_utc LIKE '2099-%'",
        )
        # 清所有 2099 测试数据(继承 1.10-H §Z 教训)
        conn.execute(
            "DELETE FROM system_states WHERE entered_at_utc LIKE '2099-%'",
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"  ⚠ cleanup 失败:{e}")


def main(argv: list[str]) -> int:
    with open(_BASE_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db_path = (
        Path(argv[1]).resolve() if len(argv) > 1
        else (_REPO_ROOT / (cfg.get("paths", {}).get("db_path",
                                                       "data/btc_strategy.db"))).resolve()
    )
    print(f"[verify_web_modules] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 不存在,先跑 scripts/init_v14_tables.py")
        return 1

    # 自动 apply migration
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        from scripts.init_v14_tables import apply_migration as _apply
        _apply(conn)
        conn.commit()
    except Exception as e:
        print(f"⚠ apply_migration: {e}")

    # 构造 TestClient(API + StaticFiles)
    def _factory():
        return get_connection(db_path)
    app = create_app(
        conn_factory=_factory, pipeline_trigger_cooldown_sec=60.0,
    )
    client = TestClient(app)

    try:
        print("\n=== 0. pre-clean ===")
        cleanup(conn)
        print("  ✅ pre-clean 完成")

        # ============================================================
        # Section A:11 新 API 接口可达
        # ============================================================
        print("\n=== A. 11 个新 API 接口可达 ===")
        endpoints = [
            ("GET", "/api/account/current"),
            ("GET", "/api/account/history?days=30"),
            ("GET", "/api/account/returns"),
            ("GET", "/api/theses/active"),
            ("GET", "/api/theses/history?limit=10"),
            ("GET", "/api/orders/pending"),
            ("GET", "/api/orders/history?days=30"),
            ("GET", "/api/review/weekly/latest"),
            ("GET", "/api/review/weekly/history?limit=12"),
        ]
        for method, ep in endpoints:
            r = client.get(ep)
            check(f"{method} {ep} 200", r.status_code == 200,
                  detail=f"status={r.status_code}")
        # /api/theses/{thesis_id} 404 测试
        r404 = client.get("/api/theses/nonexistent_id_xyz")
        check("GET /api/theses/{thesis_id} 不存在 → 404",
              r404.status_code == 404)
        # POST /api/review_pending/resolve 校验
        r422 = client.post("/api/review_pending/resolve",
                            json={"exit_type": "x", "reason": "1234567890"})
        check("POST /api/review_pending/resolve invalid exit_type → 422",
              r422.status_code == 422)

        # ============================================================
        # Section B:GET /api/strategy/current 4 字段扩展(向后兼容)
        # ============================================================
        print("\n=== B. GET /api/strategy/current 4 字段扩展 ===")
        # 写一条 strategy_run + virtual_account snapshot
        conn.execute(
            "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
            "reference_timestamp_utc, action_state, run_trigger, "
            "rules_version, full_state_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{_PREFIX}r1", "2099-05-04T08:00:00Z", "2099-05-04T16:00:00+08:00",
             "2099-05-04T08:00:00Z", "FLAT", "scheduled", "v1.4",
             json.dumps({"x": "y"})),
        )
        conn.execute(
            "INSERT INTO virtual_account (snapshot_id, run_id, snapshot_at_utc, "
            "btc_price_at_snapshot, initial_capital, available_cash, total_equity) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"{_PREFIX}s1", f"{_PREFIX}s1", "2099-05-04T08:00:00Z", 75000.0,
             100000.0, 50000.0, 102500.0),
        )
        conn.commit()

        r = client.get("/api/strategy/current")
        check("GET /current 200", r.status_code == 200)
        body = r.json()
        # 原字段保留
        check("原字段 run_id 存在(向后兼容)",
              "run_id" in body and body["run_id"] == f"{_PREFIX}r1")
        check("原字段 rules_version 存在",
              body.get("rules_version") == "v1.4")
        # 4 新字段在 state 内
        state = body.get("state") or {}
        check("state.account_summary 存在(模块 1)",
              "account_summary" in state)
        check("state.active_thesis 存在(模块 2,无 active 时 null)",
              "active_thesis" in state)
        check("state.position_summary 存在(模块 3)",
              "position_summary" in state)
        check("state.pending_orders_summary 存在",
              "pending_orders_summary" in state)
        # account_summary 数据正确
        acc = state.get("account_summary")
        if acc:
            check("account_summary.total_equity = 102500",
                  acc.get("total_equity") == 102500.0)
            check("account_summary.total_pnl_pct = 2.5(102500/100000)",
                  abs(acc.get("total_pnl_pct", 0) - 2.5) < 0.01)

        # ============================================================
        # Section C:HealthResponse.review_pending(D2=a)
        # ============================================================
        print("\n=== C. GET /api/health.review_pending(D2=a)===")
        # 无 active RP
        r = client.get("/api/health")
        body = r.json()
        check("/api/health.review_pending 字段存在",
              "review_pending" in body)
        check("无 active RP → review_pending=null",
              body.get("review_pending") is None)
        # 进入 RP
        from src.strategy.review_pending import enter_review_pending
        enter_review_pending(
            conn, reason="overly_conservative",
            related_thesis_id=None,
            entered_at_utc="2099-05-04T08:00:00Z",
        )
        conn.commit()
        r2 = client.get("/api/health")
        rp = r2.json().get("review_pending") or {}
        check("有 active RP → review_pending.active=True",
              rp.get("active") is True)
        check("review_pending.reason='overly_conservative'",
              rp.get("reason") == "overly_conservative")

        # ============================================================
        # Section D:POST /api/review_pending/resolve 端到端
        # ============================================================
        print("\n=== D. POST /api/review_pending/resolve(D4=b+c)===")
        # EXIT_A 成功
        r3 = client.post(
            "/api/review_pending/resolve",
            json={"exit_type": "a",
                  "reason": "用户调阈值,降 grade B 门槛(verify 测)"},
        )
        check("EXIT_A 成功 200",
              r3.status_code == 200, detail=f"got {r3.status_code}")
        body3 = r3.json()
        check("response.exited=True", body3.get("exited") is True)
        check("response.exit_type='a'", body3.get("exit_type") == "a")
        # exit_reason 含 user_reason
        rp_after = conn.execute(
            "SELECT exit_reason FROM system_states "
            "WHERE state_type='review_pending' AND exit_at_utc IS NOT NULL "
            "ORDER BY entered_at_utc DESC LIMIT 1"
        ).fetchone()
        check("system_states.exit_reason 含 user_reason 文本(D4=c)",
              rp_after is not None
              and "user_reason=" in (rp_after["exit_reason"] or ""))

        # ============================================================
        # Section E:web/index.html 5 模块 + RP 横幅 + 失败状态
        # ============================================================
        print("\n=== E. web/index.html 5 模块 + RP 横幅 + 失败状态 ===")
        html = _INDEX_HTML.read_text(encoding="utf-8")
        check("模块 1:region-virtual-account 存在",
              'id="region-virtual-account"' in html)
        check("模块 2:region-active-thesis 存在",
              'id="region-active-thesis"' in html)
        check("模块 3:region-orders-position 存在",
              'id="region-orders-position"' in html)
        check("模块 4:region-thesis-timeline 存在",
              'id="region-thesis-timeline"' in html)
        check("模块 5:region-weekly-review 存在",
              'id="region-weekly-review"' in html)
        check("RP 红色横幅(bg-rose-600 + reviewPending.active)",
              "bg-rose-600" in html
              and "reviewPending && reviewPending.active" in html)
        check("RP 解除模态框 4 选 + reason min 10",
              "rpExitType" in html and "rpReason" in html
              and "min 10 字符" in html)
        check("失败状态显示(aiFailureStatus)",
              "aiFailureStatus()" in html)

        # ============================================================
        # Section F:风格硬约束(§9.1)+ 现有 12 卡保留
        # ============================================================
        print("\n=== F. 风格硬约束 + 现有 12 卡保留 ===")
        check("audit-card 风格沿用(无新设计语言)",
              html.count("audit-card") >= 8)
        check("font-mono 数字字段(>= 15 处)",
              html.count("font-mono") >= 15)
        check("不引入 Chart.js / D3",
              "chart.js" not in html.lower() and "d3.js" not in html.lower())
        for region in ("region-1", "region-layer-cards", "region-4", "region-5"):
            check(f"§X 现有 {region} 保留(不删)",
                  f'id="{region}"' in html)
        # sparkline 是纯 SVG polyline
        check("D1=c sparkline 纯 SVG <polyline>",
              "polyline" in html
              and "sparklinePoints(accountHistory)" in html)

        # ============================================================
        # Section G:app.js Alpine state + 23 V key 完整
        # ============================================================
        print("\n=== G. app.js Alpine 23 V key 完整 + helpers ===")
        js = _APP_JS.read_text(encoding="utf-8")
        check("Alpine state:virtualAccount", "virtualAccount:" in js)
        check("Alpine state:reviewPending", "reviewPending:" in js)
        check("validatorKeys() 返 23 V",
              all(f"validator_{n}_" in js for n in range(1, 24)))
        check("_refreshV14Modules 拉 9 endpoints",
              "/api/account/current" in js
              and "/api/account/returns" in js
              and "/api/account/history?days=30" in js
              and "/api/theses/active" in js
              and "/api/theses/history" in js
              and "/api/orders/pending" in js
              and "/api/review/weekly/latest" in js
              and "/api/review/weekly/history" in js
              and "/api/health" in js)
        check("aiFailureStatus 处理 5 类失败",
              "AI 介入失败 — 请人工介入" in js
              and "已接管" in js
              and "Master 已短路" in js
              and "macro fallback" in js
              and "重试中" in js)

        # ============================================================
        # Section H:ThesesDAO.get_by_id(commit 2 新加)
        # ============================================================
        print("\n=== H. ThesesDAO.get_by_id 新加(1.10-A 补漏)===")
        from src.data.storage.dao import ThesesDAO
        # 写一条 thesis
        conn.execute(
            "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
            "direction, core_logic, confidence_score, break_conditions, "
            "lifecycle_stage, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{_PREFIX}t1", "r", "2099-05-04T08:00:00Z", "long",
             "test", 70, '["a","b","c"]', "planned", "active"),
        )
        conn.commit()
        res = ThesesDAO.get_by_id(conn, thesis_id=f"{_PREFIX}t1")
        check("get_by_id 返 dict",
              res is not None and res["thesis_id"] == f"{_PREFIX}t1")
        check("get_by_id break_conditions 已 JSON 还原",
              res["break_conditions"] == ["a", "b", "c"])
        # API 路径 /api/theses/{thesis_id}
        r4 = client.get(f"/api/theses/{_PREFIX}t1")
        check(f"GET /api/theses/{_PREFIX}t1 200",
              r4.status_code == 200
              and r4.json()["thesis_id"] == f"{_PREFIX}t1")

        # ============================================================
        # Section I:静态资源挂载(StaticFiles 仍工作)
        # ============================================================
        print("\n=== I. 静态资源挂载(/ + /assets) ===")
        r5 = client.get("/")
        check("GET / → 200(StaticFiles 挂 web/index.html)",
              r5.status_code == 200)
        check("响应含 BTC Strategy 标题",
              "BTC Strategy" in r5.text or "策略审计台" in r5.text)

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
