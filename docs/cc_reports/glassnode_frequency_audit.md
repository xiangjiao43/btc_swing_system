# Glassnode 调度频率事实核查(只查不改)

**日期**:2026-05-08
**类型**:事实核查 sprint(纯只读 SSH + DB + journalctl)
**触发**:用户怀疑 Glassnode 配额被频繁抓取烧光,需要本地代码与生产服务器实际行为的事实对照

## 结论一句话

**生产服务器目前每天对 Glassnode 发出 130 次请求**(10 档 cron × 13 metric),
**绝大多数返回 HTTP 403「您的 glassnode 周期内配额已用尽」**;
最近 7 天里,2026-05-01 至 2026-05-05 每天只有 24 行真正写入(显然只有 1 个
fetcher 偶尔成功),2026-05-07 全天 0 行成功,今天(2026-05-08)所有 13 个
glassnode fetcher 全部 403,只有本地派生 `lth_mvrv` / `sth_mvrv` 写了 748 行。

**和用户 mental model 的差异**:
- 用户说「config/scheduler.yaml 里 data_collection job interval='1h'」 — 这是**老配置,Sprint 2.7-A/B 已删**;现在不是 1h 间隔,而是 BJT 上午-下午 10 个固定时刻 cron(08:35 主档 + 9 档补救)。
- 用户说「全文搜不到 `_onchain_today_complete` 函数」 — 函数实际**存在**于 `src/scheduler/jobs.py:279`(本机也有,可能是本地搜索路径错过)。

---

## Q1:代码层 — 关键函数定位

### `_onchain_today_complete` 函数(SSH grep 结果)
```
src/scheduler/jobs.py:279  def _onchain_today_complete(conn: Any) -> bool:
src/scheduler/jobs.py:312  "_onchain_today_complete: still missing today: %s"
src/scheduler/jobs.py:681  if _onchain_today_complete(conn):
```

存在 ✅。在 `job_collect_onchain` 入口处用作 skip-guard:今日已写齐 13 个期望
metric 就跳过整个 fetch。

### `collect_onchain` 调用链
```
src/scheduler/jobs.py:667  def job_collect_onchain(...)
src/scheduler/jobs.py:1298 "collect_onchain": job_collect_onchain   # ← 注册到调度器
config/scheduler.yaml:95   collect_onchain:                          # ← 10 档 cron 配置
```

### `_GLASSNODE_FETCHERS` 列表实际长度
```python
# src/scheduler/jobs.py:217
_GLASSNODE_FETCHERS: tuple[str, ...] = (
    "fetch_mvrv_z_score", "fetch_nupl", "fetch_lth_supply",
    "fetch_exchange_net_flow", "fetch_mvrv", "fetch_realized_price",
    "fetch_lth_realized_price", "fetch_sth_realized_price",
    "fetch_sopr_adjusted",
    "fetch_sth_supply", "fetch_ssr", "fetch_cdd", "fetch_hodl_waves",
)
```
**共 13 个 fetcher**(jobs.py:667 docstring 写的「12 个」是 stale 注释)。
`config/scheduler.yaml:113 description: 'Glassnode 13 个 metric'` 才是对的。

---

## Q2:DB 实际写入频率(`onchain_metrics`,最近 7 天按日 + 按小时)

### 按日总量

| day | rows |
|---|---|
| 2026-05-08 | 748 |
| 2026-05-07 | **0**(整天 0 写入)|
| 2026-05-06 | 720 |
| 2026-05-05 | 24 |
| 2026-05-04 | 24 |
| 2026-05-03 | 24 |
| 2026-05-02 | 24 |
| 2026-05-01 | 24 |

### 按小时(过去 7 天)

| day | hour(UTC) | rows |
|---|---|---|
| 2026-05-08 | 06 | 748 |
| 2026-05-06 | 06 | 180 |
| 2026-05-06 | 04 | 540 |
| 2026-05-05 | 12 | 24 |
| 2026-05-04 | 12 | 24 |
| 2026-05-03 | 12 | 24 |
| 2026-05-02 | 12 | 24 |
| 2026-05-01 | 12 | 24 |

### 按 metric_name(最近 24h 谁实际写了)

| metric_name | rows | last_insert_utc |
|---|---|---|
| `lth_mvrv` | 374 | 2026-05-08T06:00:07Z |
| `sth_mvrv` | 374 | 2026-05-08T06:00:07Z |

**关键观察**:今天写入的 748 行**全部是本地派生 MVRV**(Sprint 1.6 在 Glassnode
fetch 之后跑 `_compute_local_derived_mvrv` 用现有 realized_price 数据本地算出的)。
**13 个 Glassnode 一手 fetcher 今天 0 行成功**。

---

## Q3:`data_fetch_log` 表(整库 dump,4 行)

| source | last_fetched_utc | rows_upserted | notes |
|---|---|---|---|
| onchain | 2026-04-27T06:06:24Z | 63 | |
| klines | 2026-04-27T06:06:13Z | 100 | |
| derivatives | 2026-04-27T06:06:13Z | 100 | |
| macro | 2026-04-27T06:06:07Z | 26 | |

**关键观察**:`data_fetch_log` 表 4 行全部停在 **2026-04-27**,11 天没更新。
这表说明:**新的 collector 通路没在更新这张表**(之前 2.7-B 删 `job_data_collection`
时连带没维护这张老表),作为「最近 fetch 时间」监控不可信。

---

## Q4:systemd journalctl(最近 24h 实际跑了几档)

按 BJT 时刻分组(每行 13 条 fetch 失败):

| BJT 时刻 | UTC 时刻 | failed fetcher 条数 |
|---|---|---|
| 2026-05-07 16:00 BJT | May 07 08:00 UTC | 13 |
| 2026-05-07 18:00 BJT | May 07 10:00 UTC | 13 |
| 2026-05-07 20:00 BJT | May 07 12:00 UTC | 13 |
| 2026-05-08 08:35 BJT | May 08 00:35 UTC | 13 |
| 2026-05-08 09:05 BJT | May 08 01:05 UTC | 13 |
| 2026-05-08 09:35 BJT | May 08 01:35 UTC | 13 |
| 2026-05-08 10:35 BJT | May 08 02:35 UTC | 13 |
| 2026-05-08 11:35 BJT | May 08 03:35 UTC | 13 |
| 2026-05-08 12:35 BJT | May 08 04:35 UTC | 13 |
| 2026-05-08 14:00 BJT | May 08 06:00 UTC | 13 |

**24h 总计**:10 档 × 13 fetcher = **130 次 Glassnode 请求**。
**所有 130 次** journal 关键字 `failed: HTTP 403` + `您的 glassnode 周期内配额已用尽`。

每条失败 log 长这样:
```
collect_onchain.fetch_mvrv_z_score failed: HTTP 403 (non-retry) on
/v1/metrics/market/mvrv_z_score: {"error":{"code":"HTTP_ERROR",
"message":"您的 glassnode 周期内配额已用尽"}}
```

注意 `(non-retry)`:HTTP 403 在 collector 里是 non-retry 错误,所以单条 fetch
失败后**不会**自动重试;但**整个 cron job 每 30-90 分钟跑一次**,每次都把
13 个 fetcher 全跑一遍。

---

## Q5:中转站 quota 限制信息

`grep -iE 'glassnode.*quota|alphanode.*quota|glassnode.*limit'` 在
`.env` `.env.example` `docs/dev_setup.md` `docs/modeling.md` `docs/PROJECT_LOG.md`
**没有找到任何 quota 数字**。`.env.example` 只说明 alphanode 是 CoinGlass + Glassnode
共享中转,两个 key 通常填同一个值,没有 quota / rate / limit 字样。

`docs/dev_setup.md` 命中段:
- 链上走 Glassnode,经 `api.alphanode.work` 中转(与 CoinGlass 共享域名)
- 共享 API key,`COINGLASS_API_KEY` 和 `GLASSNODE_API_KEY` 通常填同一个 alphanode key

**无 quota 限额数字**,但 alphanode 中转站直接吐了「您的 glassnode 周期内配额已用尽」
的 403,说明配额逻辑在中转站这一侧,不在我方代码内。

---

## Q1+Q2 联立解读:为什么 skip-guard 不生效

`_onchain_today_complete()` 判定逻辑(`src/scheduler/jobs.py:279`):
- 期望集合 = `_ONCHAIN_EXPECTED_METRICS_TODAY` ∪ `{"hodl_waves"}`(13 个 metric)
- 「今天写过」= `onchain_metrics` 表 `captured_at_utc LIKE 'YYYY-MM-DD%'` 出现的 metric
- 全部 13 个都在写过集合 → 返回 True(skip 整个 fetch)

**今天的实际情况**:
- 13 个 Glassnode 一手 fetcher 全 403 → 0 行入表
- skip-guard 永远返回 False → 下一档 cron(30-90 分钟后)继续重试 13 个 fetcher
- 形成**无限重试循环**:`130 calls/day × N 天` 全部撞配额墙

---

## scheduler.yaml 的真实 cron 配置

```yaml
collect_onchain:
  enabled: true
  cron:                              # BJT 时区(顶部 timezone: 'Asia/Shanghai')
    - {hour: 8,  minute: 35}         # 主档
    - {hour: 9,  minute: 5}          # 补救 1
    - {hour: 9,  minute: 35}         # 补救 2
    - {hour: 10, minute: 35}         # 补救 3
    - {hour: 11, minute: 35}         # 补救 4
    - {hour: 12, minute: 35}         # 补救 5
    - {hour: 14, minute: 0}          # 补救 6
    - {hour: 16, minute: 0}          # 补救 7
    - {hour: 18, minute: 0}          # 补救 8
    - {hour: 20, minute: 0}          # 补救 9
  description: 'Glassnode 13 个 metric(多档补救)'
```

**10 档 cron 共同设计意图**:8:35 主抓如果失败,补救档让 1 天里多次机会重抓。
**当前问题**:配额已耗尽时,补救机制反而变成「持续打配额墙的放大器」。

---

## 改动清单

**本次纯查不改,无代码 / 配置改动**。仅产出本报告。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A(纯查不改)|
| GitHub push(commit hash) | ✅ 见下文 commit |
| 服务器 git pull | N/A(本次没有需要服务器拉的代码改动)|
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 / 清污 | N/A |

## 本 sprint 删除清单

**本 sprint 无替代关系,无删除项**(纯事实核查报告,无代码/配置改动)。

---

## 用户决策点(给用户建议,不自动执行)

1. **缩减 cron 档位** — 10 档 → 1 档(只保留 08:35 主),把 9 档补救改成「失败后重试」机制(单次重试 30 分钟后)。预期:130 calls/day → ~13 calls/day。
2. **调用前 quota 检查** — 写一条 healthcheck 调用,403 一次后**当日整体 disable** Glassnode collector,等 BJT 0 点重置(需先确认中转站重置时区)。
3. **skip-guard 加宽** — 当前 `_onchain_today_complete` 要求 13 个 metric **全部**写过才 skip;改成「过去 1 小时内试过且全 403 → skip」也可以,但治标不治本。
4. **联系中转站确认 quota** — 用户的 alphanode 中转站 quota 数字到底是多少 / 周期是 day/month / 重置时刻在哪个时区,目前文档完全没记录,建议补到 `docs/dev_setup.md`。

**CC 推荐**:方案 1 + 方案 4 一起做,方案 1 解决「补救档变放大器」,方案 4 解决「我们不知道 quota 上限就随便建 cron」的根因。
