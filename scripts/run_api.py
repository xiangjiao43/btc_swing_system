"""
scripts/run_api.py — 启动 FastAPI 服务(Sprint 1.15a)

用法:
    unset VIRTUAL_ENV
    uv run python scripts/run_api.py --host 0.0.0.0 --port 8000

退出:Ctrl+C。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import _env_loader  # noqa: F401


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn
    from src.data.storage.connection import init_db
    init_db(verbose=False)
    uvicorn.run(
        "src.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
