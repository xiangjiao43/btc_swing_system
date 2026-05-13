-- 018_add_latest_layer_a_spot_strategy.sql
-- Layer A 大周期现货策略独立 10:00 BJT 任务的最新结果表。
-- 单行覆盖,避免覆盖 Layer B strategy_runs 最新行。

CREATE TABLE IF NOT EXISTS latest_layer_a_spot_strategy (
    id                   INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    run_id               TEXT NOT NULL,
    generated_at_utc     TEXT NOT NULL,
    generated_at_bjt     TEXT NOT NULL,
    run_trigger          TEXT,
    status               TEXT,
    ai_model_actual      TEXT,
    layer_a_json         TEXT NOT NULL,
    updated_at_utc       TEXT NOT NULL
);
