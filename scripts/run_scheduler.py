"""
scripts/run_scheduler.py — 启动 APScheduler 进程(Sprint 1.15b)

用法:
    unset VIRTUAL_ENV
    uv run python scripts/run_scheduler.py

按 Ctrl+C 退出。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import _env_loader  # noqa: F401


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None,
                        help="覆盖 config/scheduler.yaml 路径")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    from src.data.storage.connection import init_db
    init_db(verbose=False)

    from src.scheduler import run_forever
    run_forever(config_path=args.config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
