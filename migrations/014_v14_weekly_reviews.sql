-- Sprint 1.10-H:weekly_reviews 表
--
-- 对齐 docs/modeling.md b25cfe6(v1.4)§3.3.9 + §8.1
--
-- 用途:每周日 22:00 BJT WeeklyReviewAnalyst 跑完后写一行,
--   PK = week_start_utc(YYYY-MM-DD 周一 UTC)→ UPSERT 幂等(同周触发 2 次时覆盖)。
--
-- output_json 存 4 段完整 JSON(performance_summary / system_health_diagnosis /
--   strategy_quality / hard_constraint_activation_review / adjustment_recommendations)。
--
-- critical_count = 计 adjustment_recommendations.priority='high' 的条数,
--   ≥ 1 → job_weekly_review 写一行 alerts(severity='critical');
--   = 0 → severity='info'。
--
-- 1.10-I 网页 SELECT * FROM weekly_reviews ORDER BY week_start_utc DESC LIMIT 12。
--
-- ALTER 不需要(全新表,CREATE TABLE IF NOT EXISTS 幂等)。

-- =============================================================================
-- weekly_reviews(v1.4 §3.3.9 + §8.1,Sprint 1.10-H D1=a)
-- =============================================================================
CREATE TABLE IF NOT EXISTS weekly_reviews (
    week_start_utc        TEXT PRIMARY KEY,  -- YYYY-MM-DD,周一 UTC
    triggered_at_utc      TEXT NOT NULL,
    output_json           TEXT NOT NULL,
    critical_count        INTEGER DEFAULT 0,
    notification_sent     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_weekly_reviews_triggered
    ON weekly_reviews(triggered_at_utc);
