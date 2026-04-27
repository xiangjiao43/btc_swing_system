"""
tests/test_scheduler.py — Sprint 1.15b APScheduler 单测

只验证配置装载 / 注册逻辑 / 异常隔离,不真跑定时任务。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.scheduler.jobs import (
    JobConfig,
    JobConfigError,
    build_job_configs,
    job_pipeline_run,
    load_scheduler_config,
)
from src.scheduler.main import build_scheduler


# ==================================================================
# Helpers
# ==================================================================

def _write_yaml(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


# ==================================================================
# 1. job_pipeline_run reads interval from config ('4h' -> hours=4)
# ==================================================================

def test_pipeline_job_reads_interval_from_config(tmp_path: Path):
    cfg_path = tmp_path / "scheduler.yaml"
    _write_yaml(cfg_path, {
        "timezone": "UTC",
        "jobs": {
            "pipeline_run": {
                "enabled": True,
                "interval": "4h",
                "misfire_grace_time": 600,
            }
        },
    })
    cfg = load_scheduler_config(cfg_path)
    configs = build_job_configs(cfg)
    assert len(configs) == 1
    jc = configs[0]
    assert jc.name == "pipeline_run"
    assert jc.enabled is True
    assert jc.trigger_kind == "interval"
    assert jc.trigger_kwargs == {"hours": 4}
    assert jc.misfire_grace_time == 600


# ==================================================================
# 2. Once started, pipeline job is registered with the scheduler
# ==================================================================

def test_scheduler_has_pipeline_job_registered(tmp_path: Path):
    cfg_path = tmp_path / "scheduler.yaml"
    _write_yaml(cfg_path, {
        "timezone": "UTC",
        "jobs": {
            "pipeline_run": {
                "enabled": True,
                "interval": "4h",
            },
            "data_collection": {
                "enabled": False,
                "interval": "1h",
            },
            "cleanup": {
                "enabled": False,
                "cron": {"hour": 3, "minute": 0},
            },
        },
    })
    scheduler = build_scheduler(config_path=str(cfg_path))
    try:
        job_ids = [j.id for j in scheduler.get_jobs()]
        assert "pipeline_run" in job_ids
        # disabled jobs 不应注册
        assert "data_collection" not in job_ids
        assert "cleanup" not in job_ids

        pipeline_job = scheduler.get_job("pipeline_run")
        assert isinstance(pipeline_job.trigger, IntervalTrigger)
    finally:
        # 确保 scheduler 不会被 gc 时触发
        scheduler.shutdown(wait=False) if scheduler.running else None


# ==================================================================
# 3. Builder crash inside job does not raise; returns error dict
# ==================================================================

def test_pipeline_job_isolates_builder_crash():
    # conn_factory 抛异常 → job 捕获,返回 {status: error, ...}
    def _crashy():
        raise RuntimeError("boom in conn_factory")

    result = job_pipeline_run(conn_factory=_crashy)
    assert result["status"] == "error"
    assert "RuntimeError" in result["error_type"]
    assert "boom" in result["error_message"]


# ==================================================================
# 4. misfire_grace_time is propagated from yaml to scheduler
# ==================================================================

def test_misfire_grace_time_propagates(tmp_path: Path):
    cfg_path = tmp_path / "scheduler.yaml"
    _write_yaml(cfg_path, {
        "timezone": "UTC",
        "jobs": {
            "pipeline_run": {
                "enabled": True,
                "interval": "4h",
                "misfire_grace_time": 777,
                "coalesce": False,
                "max_instances": 2,
            },
        },
    })
    scheduler = build_scheduler(config_path=str(cfg_path))
    try:
        job = scheduler.get_job("pipeline_run")
        assert job.misfire_grace_time == 777
        assert job.coalesce is False
        assert job.max_instances == 2
    finally:
        scheduler.shutdown(wait=False) if scheduler.running else None


# ==================================================================
# 5. Disabled jobs are not registered
# ==================================================================

def test_disabled_jobs_are_not_registered(tmp_path: Path):
    cfg_path = tmp_path / "scheduler.yaml"
    _write_yaml(cfg_path, {
        "timezone": "UTC",
        "jobs": {
            "pipeline_run": {
                "enabled": False,
                "interval": "4h",
            },
        },
    })
    scheduler = build_scheduler(config_path=str(cfg_path))
    try:
        assert scheduler.get_jobs() == []
    finally:
        scheduler.shutdown(wait=False) if scheduler.running else None


# ==================================================================
# 6. cron trigger support
# ==================================================================

def test_cron_trigger_supported(tmp_path: Path):
    cfg_path = tmp_path / "scheduler.yaml"
    _write_yaml(cfg_path, {
        "timezone": "UTC",
        "jobs": {
            "cleanup": {
                "enabled": True,
                "cron": {"hour": 3, "minute": 0},
            },
        },
    })
    scheduler = build_scheduler(config_path=str(cfg_path))
    try:
        job = scheduler.get_job("cleanup")
        assert isinstance(job.trigger, CronTrigger)
    finally:
        scheduler.shutdown(wait=False) if scheduler.running else None


# ==================================================================
# 7. Invalid interval string raises JobConfigError
# ==================================================================

def test_invalid_interval_raises():
    cfg = {
        "jobs": {
            "pipeline_run": {
                "enabled": True,
                "interval": "not-a-duration",
            },
        },
    }
    with pytest.raises(JobConfigError):
        build_job_configs(cfg)


