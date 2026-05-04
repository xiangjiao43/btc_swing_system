"""src/strategy/factor_cards_refresher.py — Sprint 2.8-A 实时刷新 factor_cards。

**问题**:strategy_state_history.factor_cards 是 pipeline_run(Sprint 1.9-B
起每天 16:05 BJT 1 次)的快照,网页"抓取于"显示该字段时是上次 run 的旧时间
(冷启动 / 异动外可能 24h 前)。用户希望"抓取于"反映数据真实从 API 拉回
的当下时刻(精确到秒)。

**解决**:每个 collector job 跑完后(:00 / 08:01 / 06:00 / 08:35 / 周一 08:01)
立即调 `refresh_factor_cards(conn)`:
  1. 用 _assemble_context(conn) 拼最新 context(metric_inserted_at 反映本次 collector 写入)
  2. 读上次 strategy_run 的完整 state(取 composite_factors / evidence_reports 缓存)
  3. 调 emit_factor_cards(state, context)— 这里 captured_at_bjt + fetched_at_bjt 用最新
  4. UPSERT 到 latest_factor_cards 表(id=1 单行)

**5 层证据 / 6 组合 / AI** 仍只在 pipeline_run 里跑,不在 refresher 里重算。
所以"composite 分数"等保持 pipeline_run 时刻的旧值,直到下次 pipeline 跑才更新。
但"抓取于"用本次 collector 的真实写入时间 → 用户视角"数据卡片实时刷新"。

**降级**:任何步骤失败都不抛错,logger.warning 后返回。collector 主流程不受影响。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..data.storage.dao import LatestFactorCardsDAO, StrategyStateDAO


logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def refresh_factor_cards(conn: Any) -> dict[str, Any]:
    """每个 collector 成功后调一次。返回 {refreshed: bool, card_count: int, error?: str}。"""
    try:
        # 1. 拼最新 context(用 StrategyStateBuilder._assemble_context,Sprint 2.6-J 起
        #    自带 metric_inserted_at)
        from ..pipeline.state_builder import StrategyStateBuilder
        builder = StrategyStateBuilder(conn)
        context = builder._assemble_context(conn)

        # 2. 取上次 strategy_run 的完整 state(供 emit_factor_cards 读 composite +
        #    evidence_reports;那些值保持上次 pipeline_run 的快照,不重算)
        latest_run = StrategyStateDAO.get_latest_state(conn)
        last_state = (latest_run or {}).get("state") or {}

        # 3. emit factor cards(captured_at_bjt + fetched_at_bjt 用 fresh context)
        from .factor_card_emitter import emit_factor_cards
        cards = emit_factor_cards(last_state, context)

        # 4. upsert 单行
        LatestFactorCardsDAO.upsert(conn, cards, refreshed_at_utc=_utc_now_iso())
        conn.commit()

        return {"refreshed": True, "card_count": len(cards)}
    except Exception as e:
        logger.warning("refresh_factor_cards failed: %s", e)
        return {"refreshed": False, "error": str(e)[:200]}
