"""src.web_helpers — Sprint 1.8.2-A 后端 web 适配层。

normalize_state.py:把 v12 / v13 strategy_runs.full_state_json 统一成
"前端友好 + 已翻译" schema(给 API /current /latest /history 用)。

labels.py:i18n 翻译表 v0(锁定)+ translate() helper。
"""

from .labels import translate
from .normalize_state import normalize_state

__all__ = ["translate", "normalize_state"]
