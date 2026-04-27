-- Sprint 2.6-J:每张 metric 表加 inserted_at_utc 列(系统侧 wall clock 写入时刻)
--
-- 背景:之前各 dataclass(KlineRow / DerivativeMetric / OnchainMetric / MacroMetric)
-- 上的 fetched_at 字段(default_factory=_utc_now_iso)在 collector 构造对象时设了
-- 真实时间,但 4 个 DAO 的 upsert SQL 都没把它写进 DB,落地丢失。
--
-- 本次新增 inserted_at_utc 列,DAO upsert 改为同时绑值。前端 factor card 可显示
-- per-metric 真实抓取时间(秒/微秒精度),解决用户"都是同一时间显得伪"的问题。
--
-- 旧行(legacy 1647 行 onchain_metrics 等)默认 NULL,前端遇到 NULL 会降级显示
-- captured_at_utc(诚实标注"未知系统侧时间")。
--
-- 与本次同步退役:Sprint 2.6-G 引入的 data_fetch_log 表(group 级别精度不够)
--             代码层不再读不再写,但 SQL 表保留(rollback 安全)。

ALTER TABLE price_candles          ADD COLUMN inserted_at_utc TEXT DEFAULT NULL;
ALTER TABLE derivatives_snapshots  ADD COLUMN inserted_at_utc TEXT DEFAULT NULL;
ALTER TABLE onchain_metrics        ADD COLUMN inserted_at_utc TEXT DEFAULT NULL;
ALTER TABLE macro_metrics          ADD COLUMN inserted_at_utc TEXT DEFAULT NULL;
