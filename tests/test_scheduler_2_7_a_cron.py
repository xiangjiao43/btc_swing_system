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


def test_scheduler_yaml_has_8_entries():
    """7 logical jobs + pipeline_run dual cron = 8 yaml entries."""
    cfg = load_scheduler_config(_CONFIG_PATH)
    jobs = cfg.get("jobs") or {}
    assert len(jobs) == 8, f"expected 8 entries, got {sorted(jobs.keys())}"


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

def test_build_job_configs_returns_8_jobs():
    cfg = load_scheduler_config(_CONFIG_PATH)
    out = build_job_configs(cfg)
    assert len(out) == 8


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
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["collect_klines_daily"]
    assert spec.trigger_kwargs == {"hour": 8, "minute": 1}


def test_collect_klines_weekly_monday_0801_bjt():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["collect_klines_weekly"]
    assert spec.trigger_kwargs == {"day_of_week": "mon", "hour": 8, "minute": 1}


def test_collect_macro_at_0600_bjt():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["collect_macro"]
    assert spec.trigger_kwargs == {"hour": 6, "minute": 0}


def test_collect_onchain_at_0835_bjt():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["collect_onchain"]
    assert spec.trigger_kwargs == {"hour": 8, "minute": 35}


def test_pipeline_run_regular_cron_5_hours():
    out = {jc.name: jc for jc in build_job_configs(load_scheduler_config(_CONFIG_PATH))}
    spec = out["pipeline_run_regular"]
    assert spec.trigger_kwargs == {"hour": "0,4,12,16,20", "minute": 5}


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
        expected_8 = {
            "collect_klines_1h",
            "collect_klines_daily",
            "collect_klines_weekly",
            "collect_macro",
            "collect_onchain",
            "pipeline_run_regular",
            "pipeline_run_8h_onchain",
            "event_listener",
        }
        assert registered_ids == expected_8, (
            f"missing={expected_8 - registered_ids}, extra={registered_ids - expected_8}"
        )
    finally:
        if sched.running:
            sched.shutdown(wait=False)


def test_all_cron_jobs_have_cron_trigger():
    """除 event_listener 外,所有 7 logical job 都用 cron。"""
    out = build_job_configs(load_scheduler_config(_CONFIG_PATH))
    for jc in out:
        if jc.name == "event_listener":
            assert jc.trigger_kind == "interval"
        else:
            assert jc.trigger_kind == "cron", (
                f"{jc.name} should use cron, not {jc.trigger_kind}"
            )
