-- Sprint 2.8-A:latest_factor_cards 单行表(覆盖式更新)。
--
-- 背景:strategy_state_history 的 factor_cards 字段是 pipeline_run(每 4h 1 次)
-- 写入的快照,网页"抓取于"显示该字段时是 4h 前的旧时间。
-- 用户希望"抓取于"显示数据真实从 API 拉回的当下时刻(精确到秒)。
--
-- 解决:每个 collector job 跑完后立即调 factor_cards_refresher.refresh_factor_cards(conn),
-- 把最新的 factor_cards 写入本表。前端 /api/strategy/current 优先读这表。
--
-- 单行设计(id PK CHECK(id=1)):每次 upsert 覆盖,不保留历史(decision 2 = 单行)。
-- strategy_state_history 仍写 factor_cards 列,作为历史归档(decision 1 = 仍写)。

CREATE TABLE IF NOT EXISTS latest_factor_cards (
    id                INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    cards_json        TEXT NOT NULL,
    refreshed_at_utc  TEXT NOT NULL
);
