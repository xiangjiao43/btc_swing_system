-- ============================================================
-- Sprint A(数据真实性透明化底座)— 2026-05-08
--   每次 collector 抓取记一行(成功/失败 + 原因),供网页 / state_builder /
--   skip-guard / quota-aware retry 共用查询。
--
--   data_fetch_log 老表保留(Sprint 2.6-J 已废弃,代码层不再读写,本 sprint 不动)。
-- ============================================================

CREATE TABLE IF NOT EXISTS fetch_attempts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source             TEXT NOT NULL,        -- binance_kline / coinglass_derivatives / glassnode_onchain / fred_macro
    attempted_at_utc   TEXT NOT NULL,
    status             TEXT NOT NULL,        -- 'success' | 'failure'
    failure_reason     TEXT,                  -- quota_exceeded / network_error / api_error / parse_error / unknown / NULL(成功时)
    error_message      TEXT,                  -- 简短,≤ 200 字符,无敏感信息
    rows_upserted      INTEGER,               -- 成功时的入库行数
    duration_ms        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fetch_attempts_source_time
    ON fetch_attempts(source, attempted_at_utc DESC);
