"""
_env_loader.py — 项目启动时自动加载 .env 到 os.environ。

用法:
    **在任何读 os.getenv / os.environ 的模块最顶部**加:
        from src import _env_loader  # noqa: F401

语义:
    - 只在首次 import 时执行(Python 模块缓存);后续 import 是 no-op
    - override=False:已设置的真实环境变量不被覆盖(生产上云友好)
    - .env 不存在时打印提示但不报错(生产上云时 .env 不一定存在)
    - 空行、注释行、无 "=" 的行都会被 python-dotenv 跳过

对应建模:§10.2(中转站 .env 模板) + Sprint 1.2 Envfix 决策。
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


# 项目根 = src 的父目录
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_ENV_FILE: Path = _PROJECT_ROOT / ".env"


def _count_keys(env_path: Path) -> int:
    """统计 .env 中非空非注释的 key 行数。"""
    n = 0
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" in stripped:
                    n += 1
    except OSError:
        return 0
    return n


if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)
    _n = _count_keys(_ENV_FILE)
    print(f"[env_loader] loaded .env: {_n} keys")
else:
    print(f"[env_loader] no .env file found at {_ENV_FILE} (expected in production)")


__all__: list[str] = []
