-- ============================================================
-- schema.sql — SQLite schema aligned to modeling §10.4 (Sprint 1.5c)
-- ============================================================
-- 所有时间戳 TEXT(ISO 8601 UTC,"2026-04-23T00:00:00Z")。
-- 所有表 IF NOT EXISTS,init_db() 可幂等重入。
-- Sprint 1.5c 对齐修订:旧表(btc_klines/derivatives_snapshot/onchain_snapshot/
-- macro_snapshot/strategy_state_history/fallback_log/run_metadata)已被
-- migrations/001_align_to_modeling_schema.sql 重命名并迁移到新结构。
-- ============================================================


-- ============================================================
-- 一、策略运行归档(建模 §10.4 strategy_runs)
-- ============================================================
-- run_timestamp_utc 唯一 == 原 strategy_state_history.run_timestamp_utc
-- v1.2 新增:reference_timestamp_utc / rules_version / strategy_flavor /
--           observation_category / cold_start / ai_model_actual
-- run_mode / system_version / previous_run_id / state_transitioned 也按 §10.4 字段。
CREATE TABLE IF NOT EXISTS strategy_runs (
    run_id                   TEXT PRIMARY KEY,
    generated_at_utc         TEXT NOT NULL,
    generated_at_bjt         TEXT NOT NULL,
    reference_timestamp_utc  TEXT,
    previous_run_id          TEXT,
    action_state             TEXT NOT NULL,
    stance                   TEXT,
    btc_price_usd            REAL,
    state_transitioned       INTEGER,
    run_trigger              TEXT,
    run_mode                 TEXT,
    fallback_level           TEXT,
    system_version           TEXT,
    rules_version            TEXT,
    strategy_flavor          TEXT DEFAULT 'swing',
    observation_category     TEXT,
    cold_start               INTEGER DEFAULT 0,
    ai_model_actual          TEXT,
    full_state_json          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_time          ON strategy_runs(generated_at_utc);
CREATE INDEX IF NOT EXISTS idx_runs_reference     ON strategy_runs(reference_timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_runs_flavor        ON strategy_runs(strategy_flavor);
CREATE INDEX IF NOT EXISTS idx_runs_rules_version ON strategy_runs(rules_version);
CREATE INDEX IF NOT EXISTS idx_runs_trigger       ON strategy_runs(run_trigger);
CREATE INDEX IF NOT EXISTS idx_runs_ai_model      ON strategy_runs(ai_model_actual);
CREATE INDEX IF NOT EXISTS idx_runs_action_state  ON strategy_runs(action_state);


-- ============================================================
-- 二、生命周期(建模 §10.4 lifecycles,v1.2 新增 ai_models_used / rules_versions_used)
-- ============================================================
CREATE TABLE IF NOT EXISTS lifecycles (
    lifecycle_id          TEXT PRIMARY KEY,
    direction             TEXT,
    entry_time_utc        TEXT,
    exit_time_utc         TEXT,
    status                TEXT,
    origin_thesis         TEXT,
    ai_models_used        TEXT,        -- 逗号分隔 "claude-opus-4-7,claude-sonnet-4-5"
    rules_versions_used   TEXT,        -- 逗号分隔 "v1.2.0,v1.2.1"
    full_data_json        TEXT
);

CREATE INDEX IF NOT EXISTS idx_lc_status ON lifecycles(status);
CREATE INDEX IF NOT EXISTS idx_lc_entry  ON lifecycles(entry_time_utc);


-- ============================================================
-- 三、证据卡时序(建模 §10.4 evidence_card_history,v1.2 新增 data_fresh)
-- ============================================================
CREATE TABLE IF NOT EXISTS evidence_card_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id           TEXT NOT NULL,
    run_id            TEXT NOT NULL,
    captured_at_utc   TEXT NOT NULL,
    value_numeric     REAL,
    value_text        TEXT,
    data_fresh        INTEGER DEFAULT 1,
    full_data_json    TEXT
);

CREATE INDEX IF NOT EXISTS idx_card_time   ON evidence_card_history(card_id, captured_at_utc);
CREATE INDEX IF NOT EXISTS idx_card_run_id ON evidence_card_history(run_id);


-- ============================================================
-- 四、复盘(建模 §10.4 review_reports,v1.2 新增 rules_version_at_review)
-- ============================================================
CREATE TABLE IF NOT EXISTS review_reports (
    review_id                 TEXT PRIMARY KEY,
    lifecycle_id              TEXT NOT NULL,
    generated_at_utc          TEXT,
    outcome_type              TEXT,
    rules_version_at_review   TEXT,
    full_report_json          TEXT
);

CREATE INDEX IF NOT EXISTS idx_rr_lifecycle    ON review_reports(lifecycle_id);
CREATE INDEX IF NOT EXISTS idx_rr_outcome_type ON review_reports(outcome_type);


-- ============================================================
-- 五、告警(建模 §10.4 alerts,v1.2 新增 notification_sent)
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type         TEXT NOT NULL,
    severity           TEXT NOT NULL,
    message            TEXT,
    raised_at_utc      TEXT,
    acknowledged       INTEGER DEFAULT 0,
    notification_sent  INTEGER DEFAULT 0,
    related_run_id     TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_raised   ON alerts(raised_at_utc);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_ack      ON alerts(acknowledged);


-- ============================================================
-- 六、Fallback 事件(建模 §10.4 fallback_events,替代 fallback_log)
-- ============================================================
CREATE TABLE IF NOT EXISTS fallback_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at_utc    TEXT NOT NULL,
    fallback_level      TEXT NOT NULL CHECK (fallback_level IN ('level_1', 'level_2', 'level_3')),
    reason              TEXT,
    related_run_id      TEXT,
    resolved_at_utc     TEXT,
    resolution_note     TEXT
);

CREATE INDEX IF NOT EXISTS idx_fb_time  ON fallback_events(triggered_at_utc);
CREATE INDEX IF NOT EXISTS idx_fb_level ON fallback_events(fallback_level);
CREATE INDEX IF NOT EXISTS idx_fb_run   ON fallback_events(related_run_id);


-- ============================================================
-- 七、KPI 快照(建模 §10.4 kpi_snapshots,v1.2 新表)
-- ============================================================
CREATE TABLE IF NOT EXISTS kpi_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at_utc   TEXT NOT NULL,
    kpi_name          TEXT NOT NULL,
    window_start      TEXT,
    window_end        TEXT,
    value_numeric     REAL,
    met_threshold     INTEGER,
    note              TEXT
);

CREATE INDEX IF NOT EXISTS idx_kpi_time ON kpi_snapshots(captured_at_utc);
CREATE INDEX IF NOT EXISTS idx_kpi_name ON kpi_snapshots(kpi_name);


-- ============================================================
-- 八、K 线(建模 §10.4 price_candles,替代 btc_klines)
-- ============================================================
-- §10.4 的 price_candles 带 symbol,v0.1 只存 BTCUSDT;保留 volume 单列。
CREATE TABLE IF NOT EXISTS price_candles (
    symbol         TEXT NOT NULL,
    timeframe      TEXT NOT NULL CHECK (timeframe IN ('1h', '4h', '1d', '1w')),
    open_time_utc  TEXT NOT NULL,
    open           REAL,
    high           REAL,
    low            REAL,
    close          REAL,
    volume         REAL,
    PRIMARY KEY (symbol, timeframe, open_time_utc)
);

CREATE INDEX IF NOT EXISTS idx_pc_tf_time ON price_candles(timeframe, open_time_utc DESC);


-- ============================================================
-- 九、衍生品快照(建模 §10.4 derivatives_snapshots,宽表格式)
-- ============================================================
-- v1.2 规定宽表:每行 = 一个时间戳 + 主要衍生品主字段 + 其余入 full_data_json。
-- 旧版长表 (timestamp, metric_name, metric_value) 已在 migration 中 pivot 到此表。
CREATE TABLE IF NOT EXISTS derivatives_snapshots (
    captured_at_utc     TEXT PRIMARY KEY,
    funding_rate        REAL,
    open_interest       REAL,
    long_short_ratio    REAL,
    -- Sprint 2.6-B:加 3 列清算数据(对应 migrations/002_add_liquidation_columns.sql)
    liquidation_long    REAL,
    liquidation_short   REAL,
    liquidation_total   REAL,
    full_data_json      TEXT
);


-- ============================================================
-- 十、链上指标(建模 §10.4 onchain_metrics,替代 onchain_snapshot)
-- ============================================================
CREATE TABLE IF NOT EXISTS onchain_metrics (
    metric_name        TEXT NOT NULL,
    captured_at_utc    TEXT NOT NULL,
    value              REAL,
    source             TEXT DEFAULT 'glassnode',
    PRIMARY KEY (metric_name, captured_at_utc)
);

CREATE INDEX IF NOT EXISTS idx_onchain_time ON onchain_metrics(captured_at_utc);


-- ============================================================
-- 十一、宏观指标(建模 §10.4 macro_metrics,替代 macro_snapshot)
-- ============================================================
CREATE TABLE IF NOT EXISTS macro_metrics (
    metric_name        TEXT NOT NULL,
    captured_at_utc    TEXT NOT NULL,
    value              REAL,
    source             TEXT,
    PRIMARY KEY (metric_name, captured_at_utc)
);

CREATE INDEX IF NOT EXISTS idx_macro_time ON macro_metrics(captured_at_utc);


-- ============================================================
-- 附加:事件日历(§10.4 未单独列出,但 §3.4 明确需要;保留原表)
-- ============================================================
CREATE TABLE IF NOT EXISTS events_calendar (
    event_id           TEXT PRIMARY KEY,
    date               TEXT NOT NULL,
    timezone           TEXT NOT NULL CHECK (timezone IN ('America/New_York', 'UTC')),
    local_time         TEXT,
    utc_trigger_time   TEXT,
    event_type         TEXT NOT NULL,
    event_name         TEXT NOT NULL,
    impact_level       INTEGER CHECK (impact_level BETWEEN 1 AND 5),
    notes              TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_date ON events_calendar(date);
CREATE INDEX IF NOT EXISTS idx_events_utc  ON events_calendar(utc_trigger_time);
CREATE INDEX IF NOT EXISTS idx_events_type ON events_calendar(event_type);


-- ============================================================
-- 完成
-- ============================================================
-- Python 层在 connection.py 启用 PRAGMA foreign_keys=ON。
-- v1.0 上云时翻译成 Postgres,外键 / CHECK / 索引可直译。
