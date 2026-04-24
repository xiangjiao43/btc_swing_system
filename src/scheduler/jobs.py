"""
jobs.py — Sprint 1.15b 任务定义 + 配置装载

三个 job:
  * job_pipeline_run:调 StrategyStateBuilder.run();异常写 FallbackLog,不 crash。
  * job_data_collection:数据采集骨架(默认关闭,占位用)。
  * job_cleanup:清理骨架(默认关闭,占位用)。

build_job_configs(cfg) 把 yaml dict 拍平成 JobConfig 列表,
config 读完后交给 src/scheduler/main.py 注册到 APScheduler。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml


logger = logging.getLogger(__name__)


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH: Path = _PROJECT_ROOT / "config" / "scheduler.yaml"


class JobConfigError(Exception):
    """scheduler.yaml 解析错误。"""


@dataclass
class JobConfig:
    name: str
    enabled: bool
    func: Callable[[], Any]
    trigger_kind: str                 # 'interval' | 'cron'
    trigger_kwargs: dict[str, Any]
    misfire_grace_time: int = 300
    coalesce: bool = True
    max_instances: int = 1
    description: str = ""


# ============================================================
# Job function skeletons
# ============================================================

def job_pipeline_run(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    builder_factory: Optional[Callable[[Any], Any]] = None,
) -> dict[str, Any]:
    """
    主 Pipeline 任务。异常捕获后写 FallbackLog 并返回 error dict,不 crash。

    依赖注入:
      * conn_factory():返回 sqlite3.Connection。默认走 get_connection()。
      * builder_factory(conn):返回 StrategyStateBuilder。默认用项目类。

    Returns:
      * 成功 → {status: 'ok', run_id, persisted, ai_status, duration_ms}
      * 失败 → {status: 'error', error_type, error_message}
    """
    from ..data.storage.connection import get_connection
    from ..data.storage.dao import FallbackLogDAO

    cf = conn_factory or get_connection
    conn = None
    try:
        conn = cf()
        if builder_factory is None:
            from ..pipeline import StrategyStateBuilder
            builder = StrategyStateBuilder(conn)
        else:
            builder = builder_factory(conn)
        result = builder.run(run_trigger="scheduled")
        return {
            "status": "ok",
            "run_id": result.run_id,
            "run_timestamp_utc": result.run_timestamp_utc,
            "persisted": result.persisted,
            "ai_status": result.ai_status,
            "duration_ms": result.duration_ms,
            "degraded_stages": result.degraded_stages,
            "failure_count": len(result.failures),
        }
    except Exception as e:
        logger.exception("job_pipeline_run crashed: %s", e)
        # 尝试写 FallbackLog(连接失败就只记日志)
        if conn is not None:
            try:
                from datetime import datetime, timezone
                FallbackLogDAO.log_stage_error(
                    conn,
                    run_timestamp_utc=(
                        datetime.now(timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ")
                    ),
                    stage="scheduler.pipeline_run",
                    error=e,
                    fallback_applied="skip_this_run",
                )
                conn.commit()
            except Exception as inner:
                logger.warning("failed to write FallbackLog: %s", inner)
        return {
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e)[:300],
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def job_data_collection() -> dict[str, Any]:
    """骨架。真实实现在 Sprint 2+,这里只打日志。"""
    logger.info("job_data_collection: skeleton (no-op)")
    return {"status": "skipped", "reason": "skeleton_only"}


def job_cleanup() -> dict[str, Any]:
    """骨架。"""
    logger.info("job_cleanup: skeleton (no-op)")
    return {"status": "skipped", "reason": "skeleton_only"}


_JOB_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "pipeline_run": job_pipeline_run,
    "data_collection": job_data_collection,
    "cleanup": job_cleanup,
}


# ============================================================
# Config loading
# ============================================================

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)


def _parse_interval(value: str) -> dict[str, Any]:
    """
    '4h' → {hours: 4}, '30m' → {minutes: 30}, '7200s' → {seconds: 7200}, '1d' → {days: 1}
    """
    m = _INTERVAL_RE.match(str(value))
    if not m:
        raise JobConfigError(f"invalid interval string: {value!r}")
    n, unit = int(m.group(1)), m.group(2).lower()
    mapping = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    return {mapping[unit]: n}


def load_scheduler_config(
    config_path: Optional[str | Path] = None,
) -> dict[str, Any]:
    """读 scheduler.yaml,返回原始 dict(便于测试注入)。"""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_job_configs(
    cfg: dict[str, Any],
    *,
    functions_override: Optional[dict[str, Callable[..., Any]]] = None,
) -> list[JobConfig]:
    """
    把 yaml 的 jobs 段转成 JobConfig 列表(含 disabled 的 — 调用方自行过滤)。
    """
    funcs = dict(_JOB_FUNCTIONS)
    if functions_override:
        funcs.update(functions_override)

    jobs_cfg = cfg.get("jobs") or {}
    if not isinstance(jobs_cfg, dict):
        raise JobConfigError("scheduler.yaml: 'jobs' section must be a dict")

    out: list[JobConfig] = []
    for name, spec in jobs_cfg.items():
        if not isinstance(spec, dict):
            raise JobConfigError(f"job {name}: spec must be a dict")
        if name not in funcs:
            raise JobConfigError(f"job {name}: no registered function")
        if "interval" in spec:
            trigger_kind = "interval"
            trigger_kwargs = _parse_interval(spec["interval"])
        elif "cron" in spec:
            cron = spec["cron"]
            if not isinstance(cron, dict):
                raise JobConfigError(f"job {name}: 'cron' must be a dict")
            trigger_kind = "cron"
            trigger_kwargs = dict(cron)
        else:
            raise JobConfigError(
                f"job {name}: must provide either 'interval' or 'cron'"
            )
        out.append(JobConfig(
            name=name,
            enabled=bool(spec.get("enabled", False)),
            func=funcs[name],
            trigger_kind=trigger_kind,
            trigger_kwargs=trigger_kwargs,
            misfire_grace_time=int(spec.get("misfire_grace_time", 300)),
            coalesce=bool(spec.get("coalesce", True)),
            max_instances=int(spec.get("max_instances", 1)),
            description=str(spec.get("description", "")),
        ))
    return out
