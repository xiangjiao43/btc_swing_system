-- Sprint 2.7-D:event 触发基础设施
--
-- 1) event_throttle 表:为每种 event_type 记录 last_triggered_at_utc。
--    event_listener 用 2h 冷却(避免短时间内同种 event 反复触发 pipeline)。
-- 2) events_calendar 加 triggered_at_utc 列:macro 类 event 触发后写入此列,
--    防止同一 calendar 行被触发多次(每个 event 天然只触发一次)。
--
-- 幂等:使用 IF NOT EXISTS / 检查列存在再 ALTER。本次 migration 与
-- scripts/migrate_2_7_d.py 配合使用,可重跑。

CREATE TABLE IF NOT EXISTS event_throttle (
    event_type             TEXT PRIMARY KEY,
    last_triggered_at_utc  TEXT NOT NULL
);

-- events_calendar.triggered_at_utc 列(SQLite 不支持 IF NOT EXISTS for ALTER COLUMN,
-- 由 scripts/migrate_2_7_d.py 检查后再执行)。
-- 直接执行的话第二次运行会报"duplicate column",所以本 SQL 单独跑只用于全新 DB。
ALTER TABLE events_calendar ADD COLUMN triggered_at_utc TEXT;
