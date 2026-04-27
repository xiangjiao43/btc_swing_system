-- Sprint 2.6-B Commit 4:DROP 4 个无主空表
--
-- 这 4 张表是 Sprint 1.5c migration 001 应该删除的旧版 schema 残留,
-- 但因某些路径(可能是 schema.sql IF NOT EXISTS 又被新 init_db 重新创建)
-- 在生产端持续存在为空表。grep 全代码库确认 0 处主动写入这 4 张表,
-- 也 0 处主动读取(仅有注释和 docstring 提到"替代 X")。
--
-- 按工程纪律 §X(CLAUDE.md):"新代码部署后,旧代码永远不会被调用 → 必须删"
DROP TABLE IF EXISTS btc_klines;
DROP TABLE IF EXISTS derivatives_snapshot;
DROP TABLE IF EXISTS macro_snapshot;
DROP TABLE IF EXISTS onchain_snapshot;

-- 同时删它们的 indexes(如有)
DROP INDEX IF EXISTS idx_btc_klines_timestamp;
DROP INDEX IF EXISTS idx_btc_klines_tf_ts_desc;
DROP INDEX IF EXISTS idx_derivatives_snapshot_timestamp;
DROP INDEX IF EXISTS idx_macro_snapshot_timestamp;
DROP INDEX IF EXISTS idx_onchain_snapshot_timestamp;
