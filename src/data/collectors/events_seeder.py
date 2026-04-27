"""events_seeder.py — 经济日历事件 seeder(Sprint 2.6-D)。

从 data/seeds/events_2026.json 读事件,转 EventRow 后调用
EventsCalendarDAO.upsert_events()(已有的 ON CONFLICT upsert 路径)。

设计原则(§X 工程纪律):
- 不重写 INSERT 逻辑,直接复用 EventsCalendarDAO.upsert_events
- 不依赖外部 API,数据来自仓库内 seed 文件
- 每次运行 idempotent
- 未来如需接 Finnhub API,可在 collector 内加路径选择,seed 永远是 fallback
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from ..storage.dao import EventRow, EventsCalendarDAO


logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_SEED_PATH = _PROJECT_ROOT / "data" / "seeds" / "events_2026.json"

_VALID_TZ = {"America/New_York", "UTC"}


class EventsSeederError(RuntimeError):
    """events seeder 异常。"""


class EventsSeeder:
    """从 JSON seed 文件加载经济事件到 events_calendar 表。"""

    def __init__(self, seed_path: Path | str | None = None) -> None:
        self.seed_path = Path(seed_path) if seed_path else _DEFAULT_SEED_PATH

    def load_seed(self) -> list[dict[str, Any]]:
        if not self.seed_path.exists():
            raise EventsSeederError(f"Seed file not found: {self.seed_path}")
        try:
            with open(self.seed_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise EventsSeederError(f"Invalid JSON in seed: {e}") from e
        events = data.get("events") or []
        if not isinstance(events, list):
            raise EventsSeederError(
                f"Seed 'events' field must be a list, got "
                f"{type(events).__name__}"
            )
        logger.info("Loaded %d events from %s", len(events), self.seed_path)
        return events

    def upsert_to_db(
        self,
        conn: sqlite3.Connection,
        events: list[dict[str, Any]],
    ) -> dict[str, int]:
        """转 EventRow 后调 EventsCalendarDAO.upsert_events(已有的 ON CONFLICT 路径)。

        Returns:
            {valid, skipped, total_rows_affected}
        """
        rows: list[EventRow] = []
        skipped = 0
        for ev in events:
            event_id = ev.get("event_id")
            if not event_id:
                logger.warning("Skipping event without event_id: %s", ev)
                skipped += 1
                continue

            tz = ev.get("timezone", "UTC")
            if tz not in _VALID_TZ:
                logger.warning(
                    "Skipping event %s with invalid timezone %r "
                    "(must be one of %s)",
                    event_id, tz, sorted(_VALID_TZ),
                )
                skipped += 1
                continue

            try:
                rows.append(EventRow(
                    event_id=event_id,
                    date=ev["date"],
                    timezone=tz,  # type: ignore[arg-type]
                    local_time=ev.get("local_time"),
                    utc_trigger_time=ev.get("utc_trigger_time"),
                    event_type=ev.get("event_type", "other"),
                    event_name=ev.get("event_name", "Unknown event"),
                    impact_level=int(ev["impact_level"])
                    if ev.get("impact_level") is not None else None,
                    notes=ev.get("notes"),
                ))
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    "Skipping malformed event %s: %s", event_id, e,
                )
                skipped += 1

        affected = EventsCalendarDAO.upsert_events(conn, rows)
        conn.commit()

        result = {
            "valid": len(rows),
            "skipped": skipped,
            "total_rows_affected": affected,
        }
        logger.info("EventsSeeder: %s", result)
        return result

    def run(self, conn: sqlite3.Connection) -> dict[str, int]:
        """加载 seed + upsert(便捷一行调用)。"""
        events = self.load_seed()
        return self.upsert_to_db(conn, events)


def seed_events(
    conn: sqlite3.Connection,
    seed_path: str | Path | None = None,
) -> dict[str, int]:
    return EventsSeeder(seed_path=seed_path).run(conn)
