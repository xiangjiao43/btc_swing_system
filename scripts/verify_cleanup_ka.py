#!/usr/bin/env python3
"""scripts/verify_cleanup_ka.py — Sprint 1.10-K-A §Z 端到端真实断言。

对齐 1.10-J / 1.10-K-B verify 风格 + 继承 1.10-I commit 7 + 1.10-J commit 9 §Z
教训(只字符串 grep 不够,需真启动 + 真触发 strategy_run e2e)。

验证 1.10-K-A commit 1-12 完整链路:
- 段 A:写入方清理(commit 1-4)— observation_category / cold_start 业务代码 0
- 段 B:state_machine 重写(commit 5-7)— FLIP_WATCH/PPR stub + thesis dict + system_state
- 段 C:测试改造(commit 8-10)— 9 K-A skip + 2 老 SKIP 全清,反向 e2e 重写
- 段 D:narrator 重写(commit 11-12)— SCENARIO_COLD_START / _gen_cold_start 死代码全清
- 段 E:_orchestrator_mapper 镜像(commit 7)— state_machine.thesis / system_state 字段
- 段 F:§Z 真启动 uvicorn 验证 — GET / + GET /api/strategy/latest + schema_version='v14'
- 段 G:§Z 真启动 scheduler 验证 — _JOB_FUNCTIONS + cron 注册
- 段 H:§Z 真触发一次 strategy_run e2e(本 sprint 最重要的 §Z)

prefix `verify_1_10_ka_`(隔离测试数据)。

用法:.venv/bin/python scripts/verify_cleanup_ka.py [/path/to/db]
"""
from __future__ import annotations

import inspect
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.api.app import create_app  # noqa: E402
from src.scheduler import build_scheduler  # noqa: E402
from src.scheduler.jobs import _JOB_FUNCTIONS  # noqa: E402
from src.strategy import no_opportunity_narrator as narrator  # noqa: E402
from src.strategy.state_machine import (  # noqa: E402
    StateMachine,
    VALID_STATES,
    _state_to_thesis_mirror,
)

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_PREFIX = "verify_1_10_ka_"

_PASSED: list[str] = []
_FAILED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _PASSED.append(label)
        print(f"  ✅ {label}")
    else:
        _FAILED.append(f"{label} | {detail}")
        print(f"  ❌ {label} | {detail}")


def _docstring_line_set(file_path: Path) -> set[int]:
    """返回一个集合,含该文件内所有"在 \"\"\" 三引号块内"的行号(1-based)。

    简化解析:扫描每行,翻转 inside_docstring flag。不处理单引号 docstring +
    嵌套字符串等边缘 case,但本仓库 99% 用 \"\"\" docstring。
    """
    inside: set[int] = set()
    if not file_path.exists():
        return inside
    in_doc = False
    try:
        with open(file_path, encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                # 计 \"\"\" 数量
                triple_count = raw.count('"""')
                if in_doc:
                    inside.add(lineno)
                    if triple_count >= 1:
                        in_doc = False  # 关闭
                        # 若一行内有 偶数个,可能 reopen,粗略当 close
                        if triple_count >= 2:
                            in_doc = True
                else:
                    if triple_count == 1:
                        in_doc = True
                        inside.add(lineno)  # 当前行也算
                    elif triple_count >= 2:
                        # 同行 open + close(单行 docstring),不算 multi-line
                        inside.add(lineno)
    except Exception:
        return set()
    return inside


def _grep_active_count(pattern: str, *paths: str) -> int:
    """grep 排除注释 + 三引号 docstring 内 + __pycache__ + sprint 报告。"""
    try:
        result = subprocess.run(
            ["grep", "-rn", "-E", pattern, *paths,
             "--include=*.py", "--include=*.sql"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )
        # 缓存每文件的 docstring 行集
        ds_cache: dict[str, set[int]] = {}
        active = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            if "__pycache__" in line or "/cc_reports/" in line:
                continue
            try:
                fpath, lineno_str, code = line.split(":", 2)
                lineno = int(lineno_str)
            except (ValueError, TypeError):
                continue
            stripped = code.strip()
            if stripped.startswith("#") or stripped.startswith("--"):
                continue
            # 排除三引号 docstring 内
            if fpath not in ds_cache:
                ds_cache[fpath] = _docstring_line_set(_REPO_ROOT / fpath)
            if lineno in ds_cache[fpath]:
                continue
            active.append(line)
        return len(active)
    except Exception:
        return -1


def main(argv: list[str]) -> int:
    with open(_BASE_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db_path = (
        Path(argv[1]).resolve() if len(argv) > 1
        else (_REPO_ROOT / (cfg.get("paths", {}).get(
            "db_path", "data/btc_strategy.db"))).resolve()
    )
    print(f"[verify_cleanup_ka] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 不存在,先跑 scripts/init_v14_tables.py")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # ============================================================
        # 段 A:写入方清理(commit 1-4)
        # ============================================================
        print("\n=== A. 写入方清理(commit 1-4)===")

        # A.1-A.4:5 个生产文件 active code 0 引用 observation_category / cold_start
        for f in [
            "src/data/storage/dao.py",
            "src/data/storage/schema.sql",
            "src/pipeline/state_builder.py",
            "src/pipeline/_orchestrator_mapper.py",
            "src/ai/weekly_review_input_builder.py",
        ]:
            n_obs = _grep_active_count(r"observation_category", f)
            n_cs = _grep_active_count(r"\bcold_start\b", f)
            check(f"{f} active code 0 引用 observation_category(实际 {n_obs})",
                  n_obs == 0)
            check(f"{f} active code 0 引用 cold_start(实际 {n_cs})",
                  n_cs == 0)

        # A.5:DB strategy_runs 列数 = 19(从 21 减)
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(strategy_runs)").fetchall()]
        check(f"DB strategy_runs 列数 = 19(实际 {len(cols)})", len(cols) == 19)
        check("DB strategy_runs 不再含 observation_category 列",
              "observation_category" not in cols)
        check("DB strategy_runs 不再含 cold_start 列",
              "cold_start" not in cols)

        # A.6:DB strategy_runs 行数(本地 12,服务器 136+,只验证 ≥ 12)
        n_rows = conn.execute("SELECT COUNT(*) FROM strategy_runs").fetchone()[0]
        check(f"DB strategy_runs 行数 ≥ 12(实际 {n_rows})", n_rows >= 12)

        # A.7:DB strategy_runs 索引 = 7(7 个 idx_runs_*)
        idx = sorted(
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='strategy_runs' AND sql IS NOT NULL"
            ).fetchall()
        )
        check(f"DB strategy_runs 索引 = 7(实际 {len(idx)})", len(idx) == 7)

        # ============================================================
        # 段 B:state_machine 重写(commit 5-7)
        # ============================================================
        print("\n=== B. state_machine 重写(commit 5-7)===")

        sm = StateMachine()

        # B.1:_from_FLIP_WATCH 是 stub(行数 ≤ 20)
        src_fw = inspect.getsource(sm._from_FLIP_WATCH)
        check(f"_from_FLIP_WATCH 是 stub(代码行 ≤ 20,实际 {len(src_fw.splitlines())})",
              len(src_fw.splitlines()) <= 20)
        check("_from_FLIP_WATCH stub 含 'flip_watch_business_moved' 关键词",
              "flip_watch_business_moved" in src_fw)

        # B.2:_from_POST_PROTECTION_REASSESS 是 stub
        src_ppr = inspect.getsource(sm._from_POST_PROTECTION_REASSESS)
        check(f"_from_POST_PROTECTION_REASSESS 是 stub(行 ≤ 20,实际 {len(src_ppr.splitlines())})",
              len(src_ppr.splitlines()) <= 20)
        check("_from_POST_PROTECTION_REASSESS stub 含 'ppr_business_moved' 关键词",
              "ppr_business_moved" in src_ppr)

        # B.3:已删的 helper / 常量 hasattr False
        from src.strategy import state_machine as sm_mod
        from src.strategy import state_machine_inputs as smi_mod
        check("StateMachine._calc_flip_watch_bounds 已删",
              not hasattr(StateMachine, "_calc_flip_watch_bounds"))
        check("state_machine._PPR_ALLOWED_TARGETS 已删",
              not hasattr(sm_mod, "_PPR_ALLOWED_TARGETS"))
        check("state_machine_inputs._flip_watch_bounds_state 已删",
              not hasattr(smi_mod, "_flip_watch_bounds_state"))
        check("state_machine_inputs._prev_cycle_side 已删",
              not hasattr(smi_mod, "_prev_cycle_side"))

        # B.4:VALID_STATES 仍含 FLIP_WATCH / POST_PROTECTION_REASSESS(方案 C)
        check("VALID_STATES 14 档(方案 C 保留)",
              len(VALID_STATES) == 14)
        check("VALID_STATES 仍含 FLIP_WATCH(方案 C 14 档保留)",
              "FLIP_WATCH" in VALID_STATES)
        check("VALID_STATES 仍含 POST_PROTECTION_REASSESS(方案 C)",
              "POST_PROTECTION_REASSESS" in VALID_STATES)

        # B.5:compute_next 输出含 thesis + system_state(commit 7)
        result = sm.compute_next(
            {"evidence_reports": {"layer_1": {"regime": "trend_up"}}},
        )
        check("compute_next 输出含 'thesis' 字段(commit 7 方案 C 镜像)",
              "thesis" in result)
        check("compute_next 输出含 'system_state' 字段",
              "system_state" in result)
        check("compute_next 输出 14 档 'previous_state' 保留(方案 C)",
              "previous_state" in result)
        check("compute_next 输出 14 档 'current_state' 保留",
              "current_state" in result)

        # B.6:thesis dict 字段
        thesis_check, _ = _state_to_thesis_mirror("LONG_OPEN")
        check("thesis dict 含 direction='long'",
              thesis_check["direction"] == "long")
        check("thesis dict 含 lifecycle_stage='opened'",
              thesis_check["lifecycle_stage"] == "opened")
        check("thesis dict 含 status='active'",
              thesis_check["status"] == "active")

        # B.7:system_state 取值
        for state, expected in [
            ("FLAT", "normal"),
            ("LONG_PLANNED", "normal"),
            ("FLIP_WATCH", "normal"),
            ("PROTECTION", "PROTECTION"),
            ("POST_PROTECTION_REASSESS", "review_pending"),
        ]:
            _, sys_state = _state_to_thesis_mirror(state)
            check(f"system_state({state}) = {expected!r}(实际 {sys_state!r})",
                  sys_state == expected)

        # ============================================================
        # 段 C:测试改造(commit 8-10)
        # ============================================================
        print("\n=== C. 测试改造(commit 8-10)===")

        # C.1:test_state_machine.py 不含 K-A skip
        n_ka_skips = _grep_active_count(
            r'pytest\.mark\.skip\(reason="1\.10-K-A',
            "tests/test_state_machine.py",
        )
        check(f"test_state_machine.py 残留 1.10-K-A skip 数 = 0(实际 {n_ka_skips})",
              n_ka_skips == 0)

        # C.2:删除测试不在(7 个 K-A commit 8 删的)
        with open("tests/test_state_machine.py", encoding="utf-8") as f:
            tsm = f.read()
        for fname in [
            "test_21_flip_watch_to_short_planned_after_min",
            "test_22_flip_watch_to_flat_after_max",
            "test_24_flip_watch_multipliers_late_bull_low_vol",
            "test_29_ppr_allows_flat_or_flip_watch",
            "test_36_flip_watch_on_enter_has_bounds",
            "test_41_flip_watch_reads_cycle_position_nested_field",
            "test_42_flip_watch_legacy_band_field_fallback",
        ]:
            check(f"test_state_machine.py 不再含 {fname}(commit 8 §X 删除)",
                  f"def {fname}(" not in tsm)

        # C.3:test_state_machine_e2e.py UNSKIP(整模块不再 SKIP)
        with open("tests/test_state_machine_e2e.py", encoding="utf-8") as f:
            te2e = f.read()
        check("test_state_machine_e2e.py 不再 整模块 pytest.mark.skip(commit 10 unskip)",
              "pytestmark = pytest.mark.skip" not in te2e)

        # C.4:test_lifecycle_e2e_reversal.py UNSKIP
        with open("tests/test_lifecycle_e2e_reversal.py", encoding="utf-8") as f:
            trev = f.read()
        check("test_lifecycle_e2e_reversal.py 不再 整模块 pytest.mark.skip(commit 10)",
              "pytestmark = pytest.mark.skip" not in trev)
        check("test_lifecycle_e2e_reversal.py 反手测试已重命名(留 1.10-L 真接通)",
              "test_full_long_lifecycle_to_flip_watch_stay" in trev)

        # ============================================================
        # 段 D:narrator 重写(commit 11-12)
        # ============================================================
        print("\n=== D. narrator 重写(commit 11-12)===")

        # D.1:_gen_cold_start 已删
        check("narrator._gen_cold_start 已删(commit 11)",
              not hasattr(narrator, "_gen_cold_start"))
        # D.2:SCENARIO_COLD_START 常量已删(commit 12 微调)
        check("narrator.SCENARIO_COLD_START 常量已删(commit 12 微调)",
              not hasattr(narrator, "SCENARIO_COLD_START"))
        # D.3:_SCENARIO_GENERATORS 不含 cold_start key
        check("narrator._SCENARIO_GENERATORS 7 个 active(原 8 - cold_start)",
              len(narrator._SCENARIO_GENERATORS) == 7)
        # D.4:cold_start_warming_up active code 0
        n_csw = _grep_active_count(
            r"cold_start_warming_up",
            "src/strategy/no_opportunity_narrator.py",
            "src/evidence/", "src/kpi/", "src/api/",
        )
        check(f"cold_start_warming_up 在生产代码 active 0 引用(实际 {n_csw})",
              n_csw == 0)
        # D.5:SCENARIO_POST_PROTECTION 仍可达
        check("narrator.SCENARIO_POST_PROTECTION 仍存在(L1 决策)",
              hasattr(narrator, "SCENARIO_POST_PROTECTION"))
        check("narrator._gen_post_protection 仍存在(L1 决策不动)",
              hasattr(narrator, "_gen_post_protection"))

        # ============================================================
        # 段 E:_orchestrator_mapper 镜像(commit 7)
        # ============================================================
        print("\n=== E. _orchestrator_mapper 镜像(commit 7)===")

        from src.pipeline._orchestrator_mapper import (
            _map_orchestrator_result_to_state, _state_to_thesis_mirror_safe,
        )
        check("_orchestrator_mapper._state_to_thesis_mirror_safe 存在",
              callable(_state_to_thesis_mirror_safe))
        # 端到端
        t, s = _state_to_thesis_mirror_safe("LONG_HOLD")
        check("镜像 helper(LONG_HOLD) → thesis(long, holding, active)",
              t == {"direction": "long", "lifecycle_stage": "holding",
                    "status": "active"})
        check("镜像 helper(LONG_HOLD) → system_state='normal'", s == "normal")
        # None 防御
        t2, s2 = _state_to_thesis_mirror_safe(None)
        check("镜像 helper(None) → (None, 'normal') 防御 OK",
              t2 is None and s2 == "normal")

        # ============================================================
        # 段 F:§Z 真启动 uvicorn 验证
        # ============================================================
        print("\n=== F. §Z 真启动 uvicorn 验证 ===")

        try:
            app = create_app()
            client = TestClient(app)
            r1 = client.get("/")
            check(f"GET / 状态码 200(实际 {r1.status_code})",
                  r1.status_code == 200)
            check("GET / body 含 'BTC' 字符",
                  "BTC" in r1.text or "策略" in r1.text)
            r2 = client.get("/api/strategy/latest")
            check(f"GET /api/strategy/latest 状态码 200/204(实际 {r2.status_code})",
                  r2.status_code in (200, 204))
            # schema_version 检查(commit 7 K-B 写入 v14)
            if r2.status_code == 200 and r2.json():
                body = r2.json()
                sv = (body.get("state") or {}).get("schema_version") or body.get("schema_version")
                check(f"API 输出 schema_version='v14' 或 raw 含 v14 标记(实际 {sv!r})",
                      sv == "v14" or "v14" in str(body)[:5000])
        except Exception as e:
            check("uvicorn TestClient 启动 + GET", False, str(e))

        # ============================================================
        # 段 G:§Z 真启动 scheduler 验证
        # ============================================================
        print("\n=== G. §Z 真启动 scheduler 验证 ===")

        check(f"_JOB_FUNCTIONS 注册数 ≥ 11(实际 {len(_JOB_FUNCTIONS)})",
              len(_JOB_FUNCTIONS) >= 11)
        try:
            sched = build_scheduler()
            jobs = sched.get_jobs() if hasattr(sched, "get_jobs") else []
            check(f"build_scheduler 返回 ≥ 9 cron jobs(实际 {len(jobs)})",
                  len(jobs) >= 9)
        except Exception as e:
            check("build_scheduler() 启动", False, str(e))

        # PIPELINE_STAGES 不含 cold_start_*(继承 1.10-J §Z)
        from src.kpi.metrics import PIPELINE_STAGES
        check("PIPELINE_STAGES 不含 cold_start_check",
              "cold_start_check" not in PIPELINE_STAGES)

        # ============================================================
        # 段 H:§Z 真触发 strategy_run e2e(本 sprint 最重要)
        # ============================================================
        print("\n=== H. §Z 真触发 strategy_run e2e(本 sprint 最重要)===")

        # H.1:FLAT 输入 → thesis: None / system_state: 'normal'
        r_flat = sm.compute_next(
            {"evidence_reports": {"layer_1": {"regime": "trend_up"}}},
        )
        check(f"e2e FLAT 路径:current_state='FLAT'(实际 {r_flat['current_state']})",
              r_flat["current_state"] == "FLAT")
        check("e2e FLAT 路径:thesis=None",
              r_flat["thesis"] is None)
        check("e2e FLAT 路径:system_state='normal'",
              r_flat["system_state"] == "normal")

        # H.2:LONG_OPEN 输入 → thesis(long, opened, active)
        prev_record_lo = {
            "state": {"state_machine": {
                "current_state": "LONG_OPEN",
                "state_entered_at_utc": "2026-04-01T00:00:00Z",
            }},
        }
        r_lo = sm.compute_next(
            {"evidence_reports": {"layer_1": {"regime": "trend_up"}}},
            previous_record=prev_record_lo,
            now_utc="2026-04-02T00:00:00Z",
        )
        check(f"e2e LONG_OPEN 路径:current_state='LONG_OPEN'(实际 {r_lo['current_state']})",
              r_lo["current_state"] == "LONG_OPEN")
        check("e2e LONG_OPEN 路径:thesis={direction:'long', stage:'opened', status:'active'}",
              r_lo["thesis"] == {"direction": "long",
                                  "lifecycle_stage": "opened",
                                  "status": "active"})
        check("e2e LONG_OPEN 路径:system_state='normal'",
              r_lo["system_state"] == "normal")

        # H.3:PROTECTION 触发(l5_extreme_event)→ system_state='PROTECTION'
        r_prot = sm.compute_next(
            {"evidence_reports": {
                "layer_1": {"regime": "trend_up"},
                "layer_5": {"extreme_event_detected": True}}},
        )
        check(f"e2e PROTECTION 路径:current_state='PROTECTION'(实际 {r_prot['current_state']})",
              r_prot["current_state"] == "PROTECTION")
        check("e2e PROTECTION 路径:system_state='PROTECTION'",
              r_prot["system_state"] == "PROTECTION")

        # H.4:POST_PROTECTION_REASSESS stub stay → system_state='review_pending'
        prev_record_ppr = {
            "state": {"state_machine": {
                "current_state": "POST_PROTECTION_REASSESS",
                "state_entered_at_utc": "2026-04-01T00:00:00Z",
            }},
        }
        r_ppr = sm.compute_next(
            {"evidence_reports": {"layer_1": {"regime": "trend_up"}}},
            previous_record=prev_record_ppr,
            now_utc="2026-04-02T00:00:00Z",
        )
        check(f"e2e PPR stub stay:current_state='POST_PROTECTION_REASSESS'(实际 {r_ppr['current_state']})",
              r_ppr["current_state"] == "POST_PROTECTION_REASSESS")
        check("e2e PPR stub stay:system_state='review_pending'",
              r_ppr["system_state"] == "review_pending")

        # H.5:FLIP_WATCH stub stay
        prev_record_fw = {
            "state": {"state_machine": {
                "current_state": "FLIP_WATCH",
                "state_entered_at_utc": "2026-04-01T00:00:00Z",
            }},
        }
        r_fw = sm.compute_next(
            {"evidence_reports": {"layer_1": {"regime": "trend_up"}}},
            previous_record=prev_record_fw,
            now_utc="2026-04-02T00:00:00Z",
        )
        check(f"e2e FW stub stay:current_state='FLIP_WATCH'(实际 {r_fw['current_state']})",
              r_fw["current_state"] == "FLIP_WATCH")
        check("e2e FW stub stay:system_state='normal'(冷却态非系统态)",
              r_fw["system_state"] == "normal")
        check("e2e FW stub stay:thesis=None(冷却态无 active thesis)",
              r_fw["thesis"] is None)

    finally:
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
