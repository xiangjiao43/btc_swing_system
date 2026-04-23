-- ============================================================
-- schema.sql — SQLite schema for BTC Swing System
-- ============================================================
-- 对应建模文档 §10.4 + Sprint 1.1 任务定义。
-- 所有时间戳用 TEXT (ISO 8601 UTC, e.g. "2026-04-23T00:00:00Z")
-- 而非 INTEGER,便于人读与 SQL 调试。
-- 所有表使用 IF NOT EXISTS,init_db() 可幂等重入。
-- ============================================================


-- ---------- 1. BTC K 线(多时间框) ----------
-- 对应 data_catalog binance_klines_1h/4h/1d/1w。
-- timeframe ∈ {1h, 4h, 1d, 1w}。
-- volume_btc 强制 NOT NULL,volume_usdt 可缺(部分端点不返回)。
CREATE TABLE IF NOT EXISTS btc_klines (
    timeframe    TEXT    NOT NULL CHECK (timeframe IN ('1h', '4h', '1d', '1w')),
    timestamp    TEXT    NOT NULL,  -- ISO 8601 UTC; K 线开盘时间
    open         REAL    NOT NULL,
    high         REAL    NOT NULL,
    low          REAL    NOT NULL,
    close        REAL    NOT NULL,
    volume_btc   REAL    NOT NULL,
    volume_usdt  REAL,
    fetched_at   TEXT    NOT NULL,   -- 抓取该 K 线时的 UTC 时间(M29 data_captured_at)
    PRIMARY KEY (timeframe, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_btc_klines_timestamp ON btc_klines (timestamp);
CREATE INDEX IF NOT EXISTS idx_btc_klines_tf_ts_desc ON btc_klines (timeframe, timestamp DESC);


-- ---------- 2. 衍生品快照 ----------
-- 长表结构:一个 (timestamp, metric_name) 唯一,便于扩展新指标不改表。
-- metric_name 常用值:funding_rate / open_interest / long_short_ratio_top
--                     long_short_ratio_global / basis_annualized / put_call_ratio
--                     oi_change_24h_pct / liquidation_24h_usd
CREATE TABLE IF NOT EXISTS derivatives_snapshot (
    timestamp    TEXT NOT NULL,
    metric_name  TEXT NOT NULL,
    metric_value REAL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (timestamp, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_deriv_timestamp ON derivatives_snapshot (timestamp);
CREATE INDEX IF NOT EXISTS idx_deriv_metric    ON derivatives_snapshot (metric_name);


-- ---------- 3. 链上快照 ----------
-- 对应 data_catalog role_in_v1 ∈ {primary, display, delayed}(§3.6.3)。
-- source 字段区分三档,便于监控"display 档数据未抓"这种异常。
CREATE TABLE IF NOT EXISTS onchain_snapshot (
    timestamp    TEXT NOT NULL,
    metric_name  TEXT NOT NULL,
    metric_value REAL,
    source       TEXT NOT NULL CHECK (source IN ('glassnode_primary', 'glassnode_display', 'glassnode_delayed')),
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (timestamp, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_onchain_timestamp ON onchain_snapshot (timestamp);
CREATE INDEX IF NOT EXISTS idx_onchain_metric    ON onchain_snapshot (metric_name);


-- ---------- 4. 宏观快照 ----------
-- source ∈ {yahoo_finance, fred} 对应 data_sources.yaml 的直连源。
CREATE TABLE IF NOT EXISTS macro_snapshot (
    timestamp    TEXT NOT NULL,
    metric_name  TEXT NOT NULL,
    metric_value REAL,
    source       TEXT NOT NULL CHECK (source IN ('yahoo_finance', 'fred')),
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (timestamp, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_macro_timestamp ON macro_snapshot (timestamp);
CREATE INDEX IF NOT EXISTS idx_macro_metric    ON macro_snapshot (metric_name);


-- ---------- 5. 事件日历(缓存 YAML 加 UTC 触发时间) ----------
-- event_id:自拟唯一 ID(例如 "FOMC_decision_2026-03-18")
-- timezone:America/New_York 或 UTC(M39)
-- local_time:HH:MM 原始本地时间(ET 或 UTC)
-- utc_trigger_time:代码层用 zoneinfo 换算后的 UTC ISO 字符串;事件调度器查这个
CREATE TABLE IF NOT EXISTS events_calendar (
    event_id          TEXT PRIMARY KEY,
    date              TEXT NOT NULL,   -- YYYY-MM-DD
    timezone          TEXT NOT NULL CHECK (timezone IN ('America/New_York', 'UTC')),
    local_time        TEXT,
    utc_trigger_time  TEXT,             -- 由 loader 计算并写入
    event_type        TEXT NOT NULL,    -- fomc / cpi / nfp / options_expiry_major / other
    event_name        TEXT NOT NULL,    -- 映射前的名字,如 FOMC_decision / CPI
    impact_level      INTEGER CHECK (impact_level BETWEEN 1 AND 5),
    notes             TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_date ON events_calendar (date);
CREATE INDEX IF NOT EXISTS idx_events_utc  ON events_calendar (utc_trigger_time);
CREATE INDEX IF NOT EXISTS idx_events_type ON events_calendar (event_type);


-- ---------- 6. StrategyState 历史归档 ----------
-- 每次运行生成一份;run_timestamp_utc 作为主键(单次运行唯一)。
-- state_json 存完整的 12 业务块 JSON(见 schemas.yaml → strategy_state_schema)。
-- rules_version (M36) / run_trigger (M38) / ai_model_actual (M37) 提到顶层
-- 是为了支持按规则版本、触发源、AI 模型做过滤查询,不必解析 JSON。
CREATE TABLE IF NOT EXISTS strategy_state_history (
    run_timestamp_utc  TEXT PRIMARY KEY,   -- 对齐 StrategyState.reference_timestamp_utc
    run_id             TEXT NOT NULL,
    run_trigger        TEXT NOT NULL,
    rules_version      TEXT NOT NULL,
    ai_model_actual    TEXT,
    state_json         TEXT NOT NULL,
    created_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ss_run_id          ON strategy_state_history (run_id);
CREATE INDEX IF NOT EXISTS idx_ss_run_trigger     ON strategy_state_history (run_trigger);
CREATE INDEX IF NOT EXISTS idx_ss_rules_version   ON strategy_state_history (rules_version);
CREATE INDEX IF NOT EXISTS idx_ss_ai_model_actual ON strategy_state_history (ai_model_actual);


-- ---------- 7. ReviewReport 复盘 ----------
-- 对应建模 §8.3。每个 lifecycle 结束触发一次生成。
CREATE TABLE IF NOT EXISTS review_reports (
    run_timestamp_utc  TEXT PRIMARY KEY,
    lifecycle_id       TEXT NOT NULL,
    outcome_type       TEXT,             -- schemas.yaml 的 outcome_type enum(A_perfect 等)
    report_json        TEXT NOT NULL,
    created_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rr_lifecycle    ON review_reports (lifecycle_id);
CREATE INDEX IF NOT EXISTS idx_rr_outcome_type ON review_reports (outcome_type);


-- ---------- 8. Fallback 日志(M33) ----------
-- 每次 Fallback 触发写一条;连续 5 次 level_1 自动升级 level_2 的判定
-- 会查本表(base.yaml → fallback.level_1.auto_upgrade_to_l2_consecutive)。
CREATE TABLE IF NOT EXISTS fallback_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp_utc  TEXT NOT NULL,
    fallback_level     TEXT NOT NULL CHECK (fallback_level IN ('level_1', 'level_2', 'level_3')),
    triggered_by       TEXT NOT NULL,   -- 规则名,例如 ai_validation_failed / data_outage
    details            TEXT,             -- 可选 JSON 上下文
    created_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fb_timestamp    ON fallback_log (run_timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_fb_level        ON fallback_log (fallback_level);
CREATE INDEX IF NOT EXISTS idx_fb_triggered_by ON fallback_log (triggered_by);


-- ---------- 9. 运行元数据 ----------
-- 每次运行生命周期:started → completed / failed / fallback
-- 用于监控"运行卡住"(stuck_in_state 告警对应 §8.5)。
CREATE TABLE IF NOT EXISTS run_metadata (
    run_id             TEXT PRIMARY KEY,
    run_timestamp_utc  TEXT NOT NULL,
    run_trigger        TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('started', 'completed', 'failed', 'fallback')),
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    notes              TEXT
);

CREATE INDEX IF NOT EXISTS idx_rm_timestamp ON run_metadata (run_timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_rm_status    ON run_metadata (status);


-- ============================================================
-- 完成提示
-- ============================================================
-- 启用外键约束在 Python 层 PRAGMA foreign_keys = ON(connection.py)。
-- v1.0 上云时把本文件翻译成 Postgres 版;外键 / CHECK / 索引语义大致可直译。
