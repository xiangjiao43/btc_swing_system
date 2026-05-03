-- Sprint 1.10-C:fuse_events + system_states + theses.is_60d_capped
--
-- 对齐 docs/modeling.md b25cfe6(v1.4)
-- 用户决策:
--   D1 = b 新增 fuse_events 表(独立 schema,FuseMonitor 高频查询用)
--   D2 = a 新增 system_states 表(review_pending 等持久状态)
--   D4 = b 显式字段:theses.is_60d_capped INTEGER DEFAULT 0
--
-- 跑法:scripts/init_v14_tables.py 应在 migration 009 后跑此 migration(幂等 IF NOT EXISTS)。

-- =============================================================================
-- fuse_events(D1):FuseMonitor 高频查询的 audit log
-- =============================================================================
-- event_type 取值:
--   thesis_cycle_completed   每次 thesis 关闭(用于 14d 熔断双触发条件 #1)
--   channel_c_used           每次反手 channel C(用于 14d 熔断双触发条件 #2)
--   14d_fuse_triggered       14d 熔断触发(用于连续熔断检测 Validator 20)
CREATE TABLE IF NOT EXISTS fuse_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type          TEXT NOT NULL,
    thesis_id           TEXT,                    -- 可空(14d_fuse_triggered 不绑定单 thesis)
    triggered_at_utc    TEXT NOT NULL,
    metadata_json       TEXT                     -- 可选 JSON 详情
);

CREATE INDEX IF NOT EXISTS idx_fuse_type_time
    ON fuse_events(event_type, triggered_at_utc DESC);


-- =============================================================================
-- system_states(D2):持久状态(review_pending 等),可跨多 run
-- =============================================================================
-- state_type 取值:
--   review_pending           Validator 19/20/22 / 极端事件 → 等用户介入
--   14d_fuse_active          14 天熔断期(强制 FLAT)
--   protection               极端事件 PROTECTION(留 1.10-G)
--
-- exit_at_utc IS NULL → 当前 active 状态;NOT NULL → 已退出
CREATE TABLE IF NOT EXISTS system_states (
    state_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    state_type          TEXT NOT NULL,
    entered_at_utc      TEXT NOT NULL,
    exit_at_utc         TEXT,
    reason              TEXT NOT NULL,
    related_thesis_id   TEXT,                    -- 可空
    exit_reason         TEXT                     -- 退出时填(三出口 A/B/C 之一)
);

-- 部分索引:只索引 active 状态(SQLite 3.8.0+ 支持)
CREATE INDEX IF NOT EXISTS idx_sys_state_active
    ON system_states(state_type) WHERE exit_at_utc IS NULL;


-- =============================================================================
-- theses.is_60d_capped(D4)注:由 scripts/init_v14_tables.py 在 Python 侧
-- 用 PRAGMA table_info 检查后条件 ALTER(SQLite ALTER TABLE 不支持 IF NOT EXISTS)。
-- D4=b 显式字段:60d-capped thesis 维持 lifecycle_stage(holding/trim),
-- 不进 closed 终态;挂单仍触发走自然平仓 → 通道 A
-- =============================================================================
