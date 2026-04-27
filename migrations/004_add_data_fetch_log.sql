-- Sprint 2.6-G:数据抓取时间记录
--
-- 解决问题:网页因子卡片显示 K 线 bar 的开盘时间(8:00 BJT 当日),
-- 用户误以为系统 12 小时未刷新,实际系统每小时 fetch 一次。
-- 本表记录每个数据源最后一次成功 fetch 的 UTC 时间。
--
-- 写入方:
--   - src/scheduler/jobs.py::job_data_collection 每个 collector 成功后写入
--   - scripts/backfill_data.py 也写入
--
-- 读取方:
--   - src/pipeline/state_builder.py::_assemble_context 读 → context['data_freshness']
--   - src/strategy/factor_card_emitter.py 把对应 source 的 fetch 时间写入卡片 fetched_at_bjt
CREATE TABLE IF NOT EXISTS data_fetch_log (
    source             TEXT PRIMARY KEY,
    last_fetched_utc   TEXT NOT NULL,
    rows_upserted      INTEGER,
    notes              TEXT
);
