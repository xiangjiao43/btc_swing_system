"""tests/test_scheduler_2_7_a_cron.py — Sprint 2.7-A 整点 cron 改造。

验证:
1. config/scheduler.yaml 解析成功,产出 8 个 JobConfig(7 logical jobs +
   pipeline_run 拆 2 cron entry 共享 func)
2. 每个 job 的 cron 字段对齐 BJT 整点(:00 / :05 / :40 / etc)
3. timezone='Asia/Shanghai'
4. pipeline_run_regular + pipeline_run_8h_onchain 共享 job_pipeline_run 函数
5. 老的 data_collection / pipeline_run 4h interval 配置已删除
"""

from __future__ import annotations

from pathlib import Path

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.scheduler.jobs import (
    JobConfig,
    build_job_configs,
    load_scheduler_config,
)
from src.scheduler.main import build_scheduler


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "scheduler.yaml"


# ============================================================
# YAML structural
# ============================================================

def test_scheduler_yaml_loads_with_bjt_timezone():
    cfg = load_scheduler_config(_CONFIG_PATH)
    assert cfg.get("timezone") == "Asia/Shanghai"


def test_scheduler_yaml_has_11_entries():
    """v1.4 §10.4.1 + Sprint 1.10-G/H:8 + 2 (1.10-G hard_invalidation +
    position_health_check) + 1 (1.10-H weekly_review) = 11。"""
    cfg = load_scheduler_config(_CONFIG_PATH)
    jobs = cfg.get("jobs") or {}
    assert len(jobs) == 11, f"expected 11 entries, got {sorted(jobs.keys())}"
    assert "hard_invalidation_monitor" in jobs
    assert "position_health_check" in jobs
    assert "weekly_review" in jobs


def test_scheduler_yaml_no_legacy_data_collection_or_4h_interval():
    """§X:老的 data_collection job + pipeline_run 4h interval 必须被删除。"""
    cfg = load_scheduler_config(_CONFIG_PATH)
    jobs = cfg.get("jobs") or {}
    assert "data_collection" not in jobs, (
        "Sprint 2.6-A's data_collection must be removed in 2.7-A"
    )
    # 老 pipeline_run 4h interval 形态;新版必须用 cron
    for name, spec in jobs.items():
        if name.startswith("pipeline_run"):
            assert "cron" in spec, f"{name} must use cron, not interval"
            assert "interval" not in spec or not spec.get("interval"), (
                f"{name} should not have interval"
            )


# ============================================================
# Build_job_configs
# ============================================================

def test_build_job_configs_returns_11_jobs():
    """Sprint 1.10-G:8 + 2 cron(§10.4.1) + Sprint 1.10-H:1 weekly_review = 11。"""
    cfg = load_scheduler_config(_CONFIG_PATH)
    out = build_job_configs(cfg)
    assert len(out) == 11


def test_pipeline_run_dual_entries_have_dedicated_wrappers():
    """Sprint 2.7-C:pipeline_run_regular + pipeline_run_8h_onchain 各自独立函数,
    分别传 run_trigger='scheduled' / 'scheduled_8h_onchain' 给 builder.run。"""
    cfg = load_scheduler_config(_CONFIG_PATH)
    out = build_job_configs(cfg)
    by_name = {jc.name: jc for jc in out}
    assert "pipeline_run_regular" in by_name
    assert "pipeline_run_8h_onchain" in by_name
    # 2.7-C 起 wrapper 各自独立(原 2.7-A 共享 func 的设计已用 §X 删除)
    from src.scheduler.jobs import (
        job_pipeline_run_regular, job_pipeline_run_8h_onchain,
    )
    assert by_name["pipeline_run_regular"].func is job_pipeline_run_regular
    assert by_name["pipeline_run_8h_onchain"].func is job_pipeline_run_8h_onchain


def test_collect_klines_1h_runs_at_minute_zero():
    cfg = load_scheduler_config(_CONFIG_PATH)
    out = {jc.name: jc for jc in build_job_configs(cfg)}
    spec = out["collect_klines_1h"]
    assert spec.trigger_kind == "cron"
    assert spec.trigger_kwargs == {"minute": 0}


def test_collect_klines_daily_at_0801_bjt():
    """Sprint 2.8-F:multi-cron 后,主时刻仍是 08:01,但 trigger_kind=cron_or。"""
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["collect_klines_daily"]
    assert spec.trigger_kind == "cron_or"
    assert spec.trigger_kwargs["cron_list"][0] == {"hour": 8, "minute": 1}


def test_collect_klines_weekly_monday_0801_bjt():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["collect_klines_weekly"]
    assert spec.trigger_kind == "cron_or"
    assert spec.trigger_kwargs["cron_list"][0] == {
        "day_of_week": "mon", "hour": 8, "minute": 1,
    }


def test_collect_macro_at_0600_bjt():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["collect_macro"]
    assert spec.trigger_kind == "cron_or"
    assert spec.trigger_kwargs["cron_list"][0] == {"hour": 6, "minute": 0}


def test_collect_onchain_at_0835_bjt():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["collect_onchain"]
    assert spec.trigger_kind == "cron_or"
    assert spec.trigger_kwargs["cron_list"][0] == {"hour": 8, "minute": 35}


def test_pipeline_run_regular_cron_at_1605_bjt():
    """Sprint 1.9-B(2026-05-01)改为每日 1 档 16:05 BJT(= UTC 08:05)。
    原 5 档 00/04/12/16/20:05 是 v1.2 多档轮询;v1.3 AI orchestrator 跑得慢
    + 成本敏感,改每日 1 档。"""
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["pipeline_run_regular"]
    assert spec.trigger_kwargs == {"hour": 16, "minute": 5}


def test_pipeline_run_8h_onchain_at_0840_bjt():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["pipeline_run_8h_onchain"]
    assert spec.trigger_kwargs == {"hour": 8, "minute": 40}


def test_event_listener_60s_interval():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["event_listener"]
    assert spec.trigger_kind == "interval"
    assert spec.trigger_kwargs == {"seconds": 60}


# ============================================================
# Scheduler registration with BJT timezone
# ============================================================

def test_build_scheduler_uses_bjt_timezone(monkeypatch):
    """build_scheduler 实际注册 8 jobs 到 APScheduler,timezone = Asia/Shanghai。"""
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")  # 不让 startup hook 跑
    sched = build_scheduler(config_path=str(_CONFIG_PATH), blocking=False)
    try:
        assert str(sched.timezone) == "Asia/Shanghai"
        registered_ids = {j.id for j in sched.get_jobs()}
        # Sprint 1.9-B(2026-05-01)启用 pipeline_run_regular(16:05 BJT 每日);
        # pipeline_run_8h_onchain 仍 disabled。
        # Sprint 1.10-G(§10.4.1)+ 1.10-H(§3.3.9 weekly_review)新增。
        # 共 10 个 enabled cron。
        expected_10 = {
            "collect_klines_1h",
            "collect_klines_daily",
            "collect_klines_weekly",
            "collect_macro",
            "collect_onchain",
            "event_listener",
            "pipeline_run_regular",
            "hard_invalidation_monitor",
            "position_health_check",
            "weekly_review",
        }
        assert registered_ids == expected_10, (
            f"missing={expected_10 - registered_ids}, extra={registered_ids - expected_10}"
        )
    finally:
        if sched.running:
            sched.shutdown(wait=False)


def test_all_cron_jobs_have_cron_trigger():
    """除 event_listener / hard_invalidation_monitor / position_health_check 外,
    所有 logical job 都用 cron。
    Sprint 2.8-F:低频 4 job 多档 cron → trigger_kind='cron_or'(也是 cron 类)。
    Sprint 1.10-G v1.4 §10.4.1:hard_invalidation_monitor 1h interval +
    position_health_check 4h interval(简单周期触发)。"""
    interval_jobs = {
        "event_listener", "hard_invalidation_monitor", "position_health_check",
    }
    out = build_job_configs(load_scheduler_config(_CONFIG_PATH))
    for jc in out:
        if jc.name in interval_jobs:
            assert jc.trigger_kind == "interval"
        else:
            assert jc.trigger_kind in ("cron", "cron_or"), (
                f"{jc.name} should use cron / cron_or, not {jc.trigger_kind}"
            )
