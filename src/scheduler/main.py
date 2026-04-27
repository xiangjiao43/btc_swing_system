"""
scheduler/main.py — 构造并运行 APScheduler (Sprint 1.15b)

build_scheduler(...) 创建 BackgroundScheduler(不启动)。
run_forever(...) 用 BlockingScheduler 挂住进程。测试只需 build + inspect jobs。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .jobs import JobConfig, build_job_configs, load_scheduler_config


logger = logging.getLogger(__name__)


def _build_trigger(kind: str, kwargs: dict[str, Any]):
    if kind == "interval":
        return IntervalTrigger(**kwargs)
    if kind == "cron":
        return CronTrigger(**kwargs)
    raise ValueError(f"unsupported trigger kind: {kind}")


def _register_jobs(scheduler, job_configs: list[JobConfig]) -> list[str]:
    """把启用的 job 注册到 scheduler。返回已注册的 job id 列表。"""
    registered: list[str] = []
    for jc in job_configs:
        if not jc.enabled:
            logger.info("scheduler: skip disabled job %s", jc.name)
            continue
        scheduler.add_job(
            func=jc.func,
            trigger=_build_trigger(jc.trigger_kind, jc.trigger_kwargs),
            id=jc.name,
            name=jc.description or jc.name,
            misfire_grace_time=jc.misfire_grace_time,
            coalesce=jc.coalesce,
            max_instances=jc.max_instances,
            replace_existing=True,
        )
        registered.append(jc.name)
    return registered


def build_scheduler(
    *,
    config_path: Optional[str] = None,
    blocking: bool = False,
    timezone: Optional[str] = None,
):
    """
    构造 scheduler 并注册任务,但不 start()。

    Args:
        config_path: 覆盖默认 config/scheduler.yaml 路径
        blocking:    True 返回 BlockingScheduler;False(默认)返回 BackgroundScheduler
        timezone:    覆盖 yaml 的 timezone
    """
    cfg = load_scheduler_config(config_path)
    tz = timezone or cfg.get("timezone", "UTC")
    cls = BlockingScheduler if blocking else BackgroundScheduler
    scheduler = cls(timezone=tz)

    job_configs = build_job_configs(cfg)
    _register_jobs(scheduler, job_configs)
    return scheduler


def run_forever(*, config_path: Optional[str] = None) -> None:
    """用 BlockingScheduler 挂住主线程直到 Ctrl+C。"""
    scheduler = build_scheduler(config_path=config_path, blocking=True)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler: received shutdown signal")
