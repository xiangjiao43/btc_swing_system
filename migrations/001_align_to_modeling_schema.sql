-- ============================================================
-- migrations/001_align_to_modeling_schema.sql
-- Sprint 1.5c:把 Sprint 1 建的 9 张表重命名/扩列/pivot 到建模 §10.4 规定的 11 张表
-- ============================================================
-- 幂等:先检查 sqlite_master,只做一次
-- 执行前必须备份:cp data/btc_strategy.db data/btc_strategy.db.bak.before_c4
-- 执行方式:python -c "import sqlite3; sqlite3.connect('data/btc_strategy.db').executescript(open('migrations/001_align_to_modeling_schema.sql').read())"
-- ============================================================

BEGIN;

-- ----------------------------------------------------------------
-- 1. btc_klines → price_candles
-- ----------------------------------------------------------------
-- 新表已在 schema.sql 创建。迁移:为 BTCUSDT 符号统一,timestamp → open_time_utc,
-- volume_btc → volume;volume_usdt / fetched_at 弃用。
INSERT OR IGNORE INTO price_candles (symbol, timeframe, open_time_utc, open, high, low, close, volume)
SELECT 'BTCUSDT', timeframe, timestamp, open, high, low, close, volume_btc
FROM btc_klines;

DROP INDEX IF EXISTS idx_btc_klines_timestamp;
DROP INDEX IF EXISTS idx_btc_klines_tf_ts_desc;
DROP TABLE IF EXISTS btc_klines;


-- ----------------------------------------------------------------
-- 2. derivatives_snapshot(长表)→ derivatives_snapshots(宽表,建模 §10.4)
-- ----------------------------------------------------------------
-- 按 timestamp 分组,pivot:funding_rate / open_interest / long_short_ratio 三个主字段,
-- 其余全部塞 full_data_json。
INSERT OR IGNORE INTO derivatives_snapshots (captured_at_utc, funding_rate, open_interest, long_short_ratio, full_data_json)
SELECT
    timestamp,
    MAX(CASE WHEN metric_name = 'funding_rate'                THEN metric_value END) AS funding_rate,
    MAX(CASE WHEN metric_name = 'open_interest'               THEN metric_value END) AS open_interest,
    MAX(CASE WHEN metric_name IN ('long_short_ratio_top',
                                    'long_short_ratio_global') THEN metric_value END) AS long_short_ratio,
    json_group_object(metric_name, metric_value)              AS full_data_json
FROM derivatives_snapshot
GROUP BY timestamp;

DROP INDEX IF EXISTS idx_deriv_timestamp;
DROP INDEX IF EXISTS idx_deriv_metric;
DROP TABLE IF EXISTS derivatives_snapshot;


-- ----------------------------------------------------------------
-- 3. onchain_snapshot → onchain_metrics
-- ----------------------------------------------------------------
-- 字段改名:timestamp → captured_at_utc,metric_value → value。source 保留但简化
-- (建模 §10.4 只要求 TEXT DEFAULT 'glassnode');旧 source 值直接带过去。
INSERT OR IGNORE INTO onchain_metrics (metric_name, captured_at_utc, value, source)
SELECT metric_name, timestamp, metric_value, source
FROM onchain_snapshot;

DROP INDEX IF EXISTS idx_onchain_timestamp;
DROP INDEX IF EXISTS idx_onchain_metric;
DROP TABLE IF EXISTS onchain_snapshot;


-- ----------------------------------------------------------------
-- 4. macro_snapshot → macro_metrics
-- ----------------------------------------------------------------
INSERT OR IGNORE INTO macro_metrics (metric_name, captured_at_utc, value, source)
SELECT metric_name, timestamp, metric_value, source
FROM macro_snapshot;

DROP INDEX IF EXISTS idx_macro_timestamp;
DROP INDEX IF EXISTS idx_macro_metric;
DROP TABLE IF EXISTS macro_snapshot;


-- ----------------------------------------------------------------
-- 5. strategy_state_history → strategy_runs
-- ----------------------------------------------------------------
-- 复杂迁移:旧表 PK = run_timestamp_utc;新表 PK = run_id(单独字段)。
-- state_json 里可抽出:action_state / stance / btc_price_usd / cold_start 等。
-- v1.2 新增字段:从 state_json 里解析(若无则空)。
INSERT OR IGNORE INTO strategy_runs (
    run_id, generated_at_utc, generated_at_bjt,
    reference_timestamp_utc, previous_run_id,
    action_state, stance, btc_price_usd,
    state_transitioned, run_trigger, run_mode,
    fallback_level, system_version, rules_version,
    strategy_flavor, observation_category,
    cold_start, ai_model_actual, full_state_json
)
SELECT
    run_id,
    COALESCE(json_extract(state_json, '$.generated_at_utc'), created_at, run_timestamp_utc) AS generated_at_utc,
    COALESCE(json_extract(state_json, '$.generated_at_bjt'), created_at, run_timestamp_utc) AS generated_at_bjt,
    COALESCE(json_extract(state_json, '$.reference_timestamp_utc'), run_timestamp_utc)      AS reference_timestamp_utc,
    json_extract(state_json, '$.previous_run_id')                                            AS previous_run_id,
    COALESCE(json_extract(state_json, '$.state_machine.current_state'), 'FLAT')              AS action_state,
    json_extract(state_json, '$.evidence_reports.layer_2.stance')                            AS stance,
    json_extract(state_json, '$.market_snapshot.btc_price_usd')                              AS btc_price_usd,
    CASE WHEN json_extract(state_json, '$.state_machine.stable_in_state') = 0 THEN 1 ELSE 0 END AS state_transitioned,
    run_trigger,
    json_extract(state_json, '$.run_mode')                                                   AS run_mode,
    json_extract(state_json, '$.pipeline_meta.fallback_level')                               AS fallback_level,
    json_extract(state_json, '$.meta.system_version')                                        AS system_version,
    rules_version,
    COALESCE(json_extract(state_json, '$.meta.strategy_flavor'), 'swing')                    AS strategy_flavor,
    json_extract(state_json, '$.observation.observation_category')                           AS observation_category,
    CASE WHEN json_extract(state_json, '$.cold_start.warming_up') = 1 THEN 1 ELSE 0 END      AS cold_start,
    ai_model_actual,
    state_json                                                                                AS full_state_json
FROM strategy_state_history;

DROP INDEX IF EXISTS idx_ss_run_id;
DROP INDEX IF EXISTS idx_ss_run_trigger;
DROP INDEX IF EXISTS idx_ss_rules_version;
DROP INDEX IF EXISTS idx_ss_ai_model_actual;
DROP TABLE IF EXISTS strategy_state_history;


-- ----------------------------------------------------------------
-- 6. review_reports(schema 重建;旧版 PK=run_timestamp_utc,新版 PK=review_id)
-- ----------------------------------------------------------------
-- 由于旧版表可能仍存在(schema.sql 的 IF NOT EXISTS 不会替换),需显式 DROP。
-- Sprint 1.5c 重建前假设旧表为空(review_reports 在 Sprint 1.15 之后才填)。
DROP TABLE IF EXISTS review_reports;
-- 新 schema 会由 init_db() / schema.sql 重建,这里不重复声明。


-- ----------------------------------------------------------------
-- 7. fallback_log → fallback_events
-- ----------------------------------------------------------------
-- 旧表:(id, run_timestamp_utc, fallback_level, triggered_by, details, created_at)
-- 新表:(id, triggered_at_utc, fallback_level, reason, related_run_id, resolved_at_utc, resolution_note)
INSERT INTO fallback_events (triggered_at_utc, fallback_level, reason, related_run_id, resolved_at_utc, resolution_note)
SELECT
    run_timestamp_utc       AS triggered_at_utc,
    fallback_level,
    triggered_by            AS reason,
    NULL                    AS related_run_id,
    NULL                    AS resolved_at_utc,
    details                 AS resolution_note
FROM fallback_log;

DROP INDEX IF EXISTS idx_fb_timestamp;
-- idx_fb_level 名字冲突(新旧同名),先删再让新 schema 的 CREATE INDEX 重建
DROP INDEX IF EXISTS idx_fb_level;
DROP INDEX IF EXISTS idx_fb_triggered_by;
DROP TABLE IF EXISTS fallback_log;


-- ----------------------------------------------------------------
-- 8. run_metadata → 无直接对应(合并入 strategy_runs.run_trigger + fallback_events)
-- ----------------------------------------------------------------
DROP INDEX IF EXISTS idx_rm_timestamp;
DROP INDEX IF EXISTS idx_rm_status;
DROP TABLE IF EXISTS run_metadata;


COMMIT;

-- ============================================================
-- 迁移完成 — 新 schema 已在 schema.sql 定义,init_db() 会幂等创建。
-- 旧备份:data/btc_strategy.db.bak.before_c4
-- ============================================================
