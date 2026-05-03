-- Sprint 1.10-A:v1.4 三表 — virtual_account / virtual_orders / theses
--
-- 对齐 docs/modeling.md b25cfe6(v1.4 修订版)§5.1.2 / §5.2.2 / §5.3.2
--
-- 设计要点(用户 v2 补充):
--   B. theses.break_conditions 用 TEXT(JSON 字符串),DAO 写时 json.dumps,
--      JSON 反序列化合法性校验留给 1.10-D master AI 改造。
--   C. virtual_orders.expires_at_utc 不写 SQL DEFAULT,由 DAO 计算
--      (created_at + base.yaml::virtual_orders.default_expiry_days * 86400)。
--      理由:7 天的"7"是配置项,将来可能改。
--
-- 跑法:
--   scripts/init_v14_tables.py(commit 5)幂等执行本 migration + 写入
--   virtual_account 第一行 initial_capital。

-- =============================================================================
-- §5.1.2 virtual_account(每次 strategy_run 1:1 快照)
-- =============================================================================
CREATE TABLE IF NOT EXISTS virtual_account (
    snapshot_id              TEXT PRIMARY KEY,
    run_id                   TEXT NOT NULL UNIQUE,
    snapshot_at_utc          TEXT NOT NULL,
    btc_price_at_snapshot    REAL NOT NULL,

    -- 资金
    initial_capital          REAL NOT NULL,           -- 100000(永久不变)
    available_cash           REAL NOT NULL,

    -- 多头持仓
    long_position_usdt       REAL NOT NULL DEFAULT 0,
    long_avg_price           REAL,
    long_btc_amount          REAL NOT NULL DEFAULT 0,

    -- 空头持仓
    short_position_usdt      REAL NOT NULL DEFAULT 0,
    short_avg_price          REAL,
    short_btc_amount         REAL NOT NULL DEFAULT 0,

    -- 收益指标
    total_equity             REAL NOT NULL,
    realized_pnl_total       REAL NOT NULL DEFAULT 0,
    unrealized_pnl           REAL NOT NULL DEFAULT 0,
    total_return_pct         REAL NOT NULL DEFAULT 0,

    FOREIGN KEY (run_id) REFERENCES strategy_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_va_time ON virtual_account(snapshot_at_utc);


-- =============================================================================
-- §5.2.2 virtual_orders(挂单引擎)
-- =============================================================================
CREATE TABLE IF NOT EXISTS virtual_orders (
    order_id                 TEXT PRIMARY KEY,
    thesis_id                TEXT NOT NULL,
    direction                TEXT NOT NULL,           -- long / short
    order_type               TEXT NOT NULL,           -- entry / stop_loss / take_profit

    price                    REAL NOT NULL,           -- 精确挂单价
    size_pct                 REAL NOT NULL,           -- 占总仓百分比
    size_usdt                REAL NOT NULL,           -- = initial_capital × size_pct

    status                   TEXT NOT NULL,           -- pending / filled / cancelled / expired
    created_at_utc           TEXT NOT NULL,
    expires_at_utc           TEXT NOT NULL,           -- 由 DAO 计算(created_at + default_expiry_days * 86400)

    filled_at_utc            TEXT,
    filled_price             REAL,                    -- = price(等于挂单价,§5.2.4)
    filled_btc_amount        REAL,                    -- = size_usdt / filled_price

    cancelled_reason         TEXT,                    -- thesis_invalidated / superseded / expired / manual

    FOREIGN KEY (thesis_id) REFERENCES theses(thesis_id)
);

CREATE INDEX IF NOT EXISTS idx_vo_status ON virtual_orders(status);
CREATE INDEX IF NOT EXISTS idx_vo_thesis ON virtual_orders(thesis_id);


-- =============================================================================
-- §5.3.2 theses(论点生命周期)
-- =============================================================================
CREATE TABLE IF NOT EXISTS theses (
    thesis_id                TEXT PRIMARY KEY,
    created_at_run_id        TEXT NOT NULL,
    created_at_utc           TEXT NOT NULL,
    direction                TEXT NOT NULL,           -- long / short

    -- 论点核心(创建后不可变)
    core_logic               TEXT NOT NULL,
    confidence_score         INTEGER NOT NULL,        -- 0-100,master 给

    -- 失效条件:JSON 字符串(b 补充:DAO json.dumps,1.10-D validator 校验合法性)
    -- 例:'["1D 收盘跌破 70000", "DXY 突破 110 持续 3 天", "L5 extreme_event_detected=true"]'
    break_conditions         TEXT NOT NULL,

    -- 生命周期阶段
    lifecycle_stage          TEXT NOT NULL,           -- planned / opened / holding / trim / closed

    -- 状态
    status                   TEXT NOT NULL,           -- active / invalidated / closed_profit / closed_loss / closed_60d_cap / closed_protection
    invalidated_reason       TEXT,                    -- 失效时填:"1D 跌破 70000 已触发"
    closed_at_utc            TEXT,

    -- 评估快照(每次 run 更新)
    last_assessment          TEXT,                    -- fully / mostly / partially / weakened / invalidated
    last_assessment_note     TEXT,
    last_assessment_at_run   TEXT,

    -- 反手通道(v1.4 新增,closed 时填)
    close_channel            TEXT,                    -- A / B / C

    -- 最终结果(closed 时填)
    final_realized_pnl       REAL,
    final_realized_pnl_pct   REAL,
    final_outcome            TEXT                     -- profit / loss / breakeven / 60d_cap / protection
);

CREATE INDEX IF NOT EXISTS idx_theses_status ON theses(status);
CREATE INDEX IF NOT EXISTS idx_theses_created ON theses(created_at_utc);
