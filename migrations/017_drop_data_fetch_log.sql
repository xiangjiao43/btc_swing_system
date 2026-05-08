-- ============================================================
-- Sprint D(2026-05-08)— 收尾清理
-- 老 data_fetch_log 表(Sprint 2.6-G 引入,Sprint 2.6-J 已废弃)
-- 11+ 天无写入,代码层 0 处读 0 处写,fetch_attempts(Sprint A,
-- migrations/016)完整替代。本 migration 把表从生产 DB 删除。
-- ============================================================

DROP TABLE IF EXISTS data_fetch_log;
