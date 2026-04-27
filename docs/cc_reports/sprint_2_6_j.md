# Sprint 2.6-J — metric 级真实写入时间(方案 C 混合)

**Date:** 2026-04-27
**Branch:** main
**Status:** ✅ 5 个 commit 全完成

---

## 一、用户原诉求

> "目前各个数据的抓取时间显示都是 '抓取于 2026-04-27 14:06',我要的是真实的
> 抓取时间,而不是这样全都是一致的。就算是同一个频率抓取的数据(比如每小时
> 抓取的数据),也有可能有几秒或者几分钟的时间差,我需要严格按照实际时间来。"

Sprint 2.6-G 引入 `data_fetch_log` 表 → 4 个 group 共享 4 个时间戳,所有
onchain 卡显示同一时间;不满足 per-metric 精度要求。

---

## 二、Commits

| commit | 摘要 |
|---|---|
| `cc5a520` | migration(005): add inserted_at_utc to 4 metric tables (NULL for legacy) |
| `8edbf4e` | fix(dao): persist dataclass.fetched_at to inserted_at_utc column (was dropped) |
| `c81d0a5` | refactor(emitter,state_builder): per-metric inserted_at + §X drop data_fetch_log path |
| `14f7e21` | feat(web): show fetched_at to second precision |
| (本)     | docs(reports): sprint_2_6_j complete |

527 pytest pass(F.4/I 后 511 → J 后 527,新增 22:8 DAO + 14 emitter + 8 删除)。
pre-commit gitleaks 每次 Passed。

---

## 三、决策(用户拍板,本 sprint 严格遵循)

| 决策 | 用户选 |
|---|---|
| 方案 | **C(混合)**:onchain/macro per-metric;derivatives wide 表只能 snapshot 级 |
| 语义 | **(a)** 系统侧 wall clock(写入 DB 那一刻),非上游数据点时间 |
| derivatives 精度 | 接受 snapshot 级(wide 表共享 1 行 schema 固有限制) |
| legacy 行 | 默认 NULL → 前端降级回 captured_at_bjt 显示 |
| §X 范围 | 废弃 data_fetch_log 表 + DataFetchLogDAO + 6 处 record_fetch + state_builder data_freshness 注入 + emitter `_GROUP_TO_FRESHNESS_SOURCE` |

---

## 四、改动详情(按 commit 顺序)

### Commit 1 `cc5a520` — schema migration

#### `migrations/005_add_inserted_at_utc.sql`
ALTER 4 表加 `inserted_at_utc TEXT DEFAULT NULL`:price_candles /
derivatives_snapshots / onchain_metrics / macro_metrics。SQLite ALTER ADD
COLUMN 是元数据级操作,1647 行 onchain_metrics 几毫秒完成。

#### `src/data/storage/schema.sql`
同步加同样的 4 列(`init_db()` 用,测试要用)。

### Commit 2 `8edbf4e` — DAO 写入 + read helpers + e2e tests

#### `src/data/storage/dao.py`
- 新增 `_utc_now_iso_ms()` 工厂(微秒精度,`%Y-%m-%dT%H:%M:%S.%fZ`),
  4 个 dataclass 的 `fetched_at` 默认值都切到它
- `BTCKlinesDAO.upsert_klines` SQL 加 `inserted_at_utc` 列写入
  (绑 `KlineRow.fetched_at`),ON CONFLICT UPDATE 也覆盖
- `DerivativesDAO.upsert_batch`:wide 表 snapshot 级。每个 `captured_at_utc`
  桶取 `MAX(fetched_at)` 跨桶内所有行;ON CONFLICT 用 SQL `MAX(...)` 合并
- `_MetricLongTableDAO.upsert_batch`(parent of OnchainDAO + MacroDAO):
  per-row `inserted_at_utc`,真正的 per-metric 精度
- 新增 3 个 read helper:
  - `_MetricLongTableDAO.get_metric_inserted_at_map(conn) → dict[metric_name, ts]`
  - `BTCKlinesDAO.get_latest_inserted_at_by_timeframe(conn) → dict[tf, ts]`
  - `DerivativesDAO.get_latest_snapshot_inserted_at(conn) → ts | None`

#### `tests/test_dao_inserted_at_utc.py`(新建,8 测试)
- `_utc_now_iso_ms` 格式与微秒位数验证
- 4 个 DAO 路径分别端到端断言:`SELECT inserted_at_utc IS NOT NULL`
  + 时间在 `now ± 5s` 范围内
- derivatives 批次内 max(fetched_at) 取大者
- 两次 onchain upsert 间 `time.sleep(0.001)` → 微秒级 ISO 字符串字典序差异

### Commit 3 `c81d0a5` — emitter + state_builder 重构 + §X 大清理

#### `src/pipeline/state_builder.py`
- 删除 `context["data_freshness"] = DataFetchLogDAO.get_all(conn)` 注入
- 新增 `context["metric_inserted_at"]` 字典:
  ```python
  {
    "onchain":      {metric_name: iso_or_None},   # 长表 per-metric
    "macro":        {metric_name: iso_or_None},   # 长表 per-metric
    "klines_by_tf": {timeframe: iso_or_None},     # K线 per-tf
    "derivatives_snapshot": iso_or_None,          # wide 表 snapshot
  }
  ```

#### `src/strategy/factor_card_emitter.py`
- `_stamp_fetched_at` 重写:按 `card.category` 路由
  - `onchain` / `macro`:`_parse_metric_name_from_card_id` 从 card_id 反推
    metric_name(支持衍生后缀如 `_30d_change` / `_180d_percentile`),命中
    lookup 取该 metric 的 inserted_at;否则降级为该 category 的 max
  - `derivatives`:`metric_inserted_at["derivatives_snapshot"]` 单值
    (wide 表共享所有 metric)
  - `price_structure`:`klines_by_tf["1d"]`(K 线衍生卡都来自 1d bar)
  - `composite` / `ai` / `state_machine` / 等:max of 全部 metric inserted_at
  - `events`:不盖(events_calendar 不属于"系统抓取"概念)
- `_utc_iso_to_bjt_pretty`:格式从 `%Y-%m-%d %H:%M (BJT)` 改为
  `%Y-%m-%d %H:%M:%S (BJT)`(秒级精度)
- `_DERIVED_SUFFIXES`:`("_30d_change", "_20d_change", "_60d_change",
  "_24h_change", "_180d_percentile", ...)` 助手用于反推衍生卡
- 删除 `_GROUP_TO_FRESHNESS_SOURCE`(老 group-level 映射)

#### §X 删除清单
- `src/data/storage/dao.py::DataFetchLogDAO` 整个类
- `src/scheduler/jobs.py` 6 处 `DataFetchLogDAO.record_fetch` 调用 + 2 处 import
- `src/pipeline/state_builder.py::_layer_error_report` 里 `data_freshness: {}` 占位
- `tests/test_data_freshness_stamping.py` 整个文件(覆盖了已删 DAO + 老 stamping)

`data_fetch_log` 表本身**不删**(rollback 安全;`migrations/004` 也保留)。
代码层不再读不再写 → 实质上是 dead table。

#### `tests/test_emitter_inserted_at_per_card.py`(新建,14 测试)
- card_id 反向解析:直接命中 / 衍生后缀剥离 / 解析失败
- per-category 路由(onchain / macro / derivatives / price_structure /
  composite / events)
- legacy NULL 降级
- 秒级格式断言
- 端到端真 SQLite + sleep(1.05s) → 两个 onchain metric 显示不同秒级时间

### Commit 4 `14f7e21` — 前端秒级精度

#### `web/assets/app.js`
`_parseBjt` 正则增加可选秒捕获:
```js
const m = s.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
const [, y, mo, d, h, mi, sec] = m;
return new Date(Date.UTC(+y, +mo-1, +d, +h-8, +mi, +(sec||0)));
```

`fetchedAtPrimary` 逻辑无需改 — 已经做 `c.fetched_at_bjt.replace(/\s*\(BJT\)\s*$/, '')`
过滤后缀,后端给什么格式它都透传。

最终前端显示:`抓取于 2026-04-27 14:06:23(3 分钟前)`

---

## 五、测试

```
$ python -m pytest -q
527 passed, 1 skipped, 138 warnings in 58.96s
```

新增 22 个测试,删除 8 个(test_data_freshness_stamping.py 整个文件)。
无回归。

§Z 端到端验证(本 sprint 的关键)— `tests/test_dao_inserted_at_utc.py` 与
`tests/test_emitter_inserted_at_per_card.py` 都做了真 SQLite + 实际 SELECT
COUNT/字段值 的断言,**不是只 mock .called=True**。

---

## 六、用户验证脚本(部署后)

```bash
ssh user@124.222.89.86
cd /path/to/btc_swing_system
git pull
sqlite3 data/btc_strategy.db < migrations/005_add_inserted_at_utc.sql
sudo systemctl restart btc-strategy

# 等下个整点 scheduler 跑完 → 各 metric 写入 inserted_at_utc
# 也可以手动触发一次:
.venv/bin/python -c "
from src import _env_loader
from src.data.storage.connection import get_connection
from src.scheduler.jobs import job_data_collection
print(job_data_collection(conn_factory=get_connection))
"

# 验证 1:inserted_at_utc 真有值
sqlite3 data/btc_strategy.db <<'SQL'
SELECT
  metric_name,
  COUNT(*) AS rows,
  COUNT(inserted_at_utc) AS filled,
  MAX(inserted_at_utc) AS latest
FROM onchain_metrics
GROUP BY metric_name
ORDER BY metric_name;
SQL
# 预期:每个 metric_name 至少 1 行 filled > 0(本次 fetch 之后填的);
# legacy 1647 行 inserted_at_utc 仍 NULL → filled < rows,但 latest 是新值。

# 验证 2:不同 metric 显示不同时间(几秒级差异)
sqlite3 data/btc_strategy.db <<'SQL'
SELECT metric_name, inserted_at_utc
FROM onchain_metrics
WHERE inserted_at_utc IS NOT NULL
ORDER BY inserted_at_utc DESC
LIMIT 10;
SQL
# 预期:连续 10 行的 inserted_at_utc 微秒部分应该不同(假设系统正常运行)。

# 验证 3:浏览器 → 因子卡片
# - onchain 各卡的 "抓取于 ..." 行应该呈现不同时间(秒级精度)
# - derivatives 各卡仍共享同一时间(snapshot 级,wide 表限制)
# - 强制刷新 (Cmd+Shift+R) 让 Alpine.js 重载新 app.js
```

---

## 七、§X / §Y / §Z 践行

- ✅ §X:DataFetchLogDAO 整个类删除;6 处 record_fetch 调用全清;`_GROUP_TO_FRESHNESS_SOURCE` 映射删除;test_data_freshness_stamping.py 整个测试文件删除。**无残留 fallback 引用。**
- ✅ §Y:5 个 commit 都立即 push 到 origin/main。
- ✅ §Z:e2e 测试用真 SQLite + 真 DAO + SQL `SELECT COUNT(*)` / `SELECT inserted_at_utc`,断言字段真有值,不是只验证 mock `.called=True`。

---

## 八、剩余风险与同类潜在问题

1. **legacy 1647 行 NULL**:历史数据没有 inserted_at_utc。前端遇到 NULL
   降级回 captured_at_bjt 显示(诚实)。可以选择性 backfill `UPDATE
   onchain_metrics SET inserted_at_utc = captured_at_utc WHERE
   inserted_at_utc IS NULL` 但这是"撒谎"语义(把上游数据点时间当系统写入
   时间)— 当前不做。

2. **derivatives wide 表精度限制**:funding_rate / open_interest /
   long_short_ratio 三个 metric 在 wide 表共享 1 行 → 共享 1 个
   inserted_at_utc。即便它们 fetch 时差异几秒,卡 UI 也只能显示 max。
   如果用户日后仍嫌不够细,需要把 derivatives_snapshots 改回长表
   (大改,跨多个 sprint 可能涉及)。

3. **`data_fetch_log` 表 dead 但仍在 DB**:rollback 安全考虑保留。如未来
   确认不需要回滚,可单 sprint 删表 + drop migrations/004。

4. **微秒精度 vs 秒级显示**:DB 存微秒,UI 显秒。两个 metric 在同一秒内
   写入(< 1s 间隔)时显示一致 — 这是正常的(它们真的是同一秒发生)。
   用户原文"几秒或几分钟"覆盖典型场景,无需额外 UI 改动。

5. **格式不一致风险**:`captured_at_bjt` 仍是分钟级(`HH:MM (BJT)`),
   `fetched_at_bjt` 现在是秒级(`HH:MM:SS (BJT)`)。同一张卡两个时间戳
   格式不同 — 是预期行为(captured 是数据点时间,日级/小时级 metric 没必要
   显示秒;fetched 反映系统抓取动作的精确时刻)。如果有人觉得不一致,
   下个 sprint 候选(纯前端 ~10 行改动)。
