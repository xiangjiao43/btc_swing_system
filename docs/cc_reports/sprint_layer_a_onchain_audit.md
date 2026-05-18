# Sprint Layer A 链上采集链路专项排查(纯调查)

**日期**:2026-05-17
**调查范围**:hash_rate / hodl_waves / Puell Multiple 三个链上指标缺值与 429 的根因排查;Glassnode 月调用量评估;不修改任何代码或配置。
**Glassnode 订阅额度**:1,700 次/月(用户提供)。
**关键约束**:本机无法 SSH 服务器,`/home/ubuntu/pipeline_logs/` 真实报错日志需用户在服务器侧 grep 后回贴(本报告底部给出具体命令清单)。

---

## 1. 三现象的代码层根因(彼此独立,不是同一个根因)

### 现象 1:hash_rate 持续 missing — **代码 bug,不是配额、不是 endpoint 错**

- **根因**:Sprint commit [`82e59f9`](https://github.com/xiangjiao43/btc_swing_system/commit/82e59f9)(3 包重构那次)在 `src/data/collectors/glassnode.py:101` 加了 `_PATH_HASH_RATE = /v1/metrics/mining/hash_rate_mean`,在 `collect_and_save_all()` task list 第 774 行注册了 `("hash_rate", self.fetch_hash_rate)`,**但忘记同步注册到 `src/scheduler/jobs.py:264-278` 的 `_GLASSNODE_FETCHERS` tuple**
- 后果:`job_collect_onchain` 每天 08:35/09:35/10:35 跑的循环是 `for fn_name in _GLASSNODE_FETCHERS`,**不调 `fetch_hash_rate`** → `onchain_metrics` 表里永远不会有 `metric_name='hash_rate'` 的行 → Layer A `metric("hash_rate")` 返回 None
- 仅有的 hash_rate 入库路径是手动 `scripts/run_layer_a_once.py` 没有的(那个脚本不调采集器),或本机调试时直接调 `fetch_hash_rate()`。生产端因此永远没有
- **endpoint 正确性**:`/v1/metrics/mining/hash_rate_mean` 是 Glassnode 标准 Tier 1 端点,本机直接调返回 HTTP 422 "missing x-key"(说明 endpoint 存在且 alphanode 支持);上 sprint 在本机用 GLASSNODE_API_KEY 真实拿到过 960 EH/s 数据,确认订阅含该指标

### 现象 2:hodl_waves missing(但派生 hodl_waves_1y_plus_aggregate 有值)— **命名 mismatch,Sprint 1.6 起就有的预存 bug**

- **根因**:`fetch_hodl_waves` 把 Glassnode 一次返回的 12 个 bucket(`24h / 1d_1w / ... / more_10y`)拆成 **12 条独立 metric**,写入 DB 时 `metric_name` 是 `hodl_waves_24h` / `hodl_waves_1d_1w` / ... / `hodl_waves_more_10y`,**没有一条 `metric_name='hodl_waves'` 的裸名行**
- 但 [src/ai/spot_cycle_context_builder.py:1004](src/ai/spot_cycle_context_builder.py#L1004) 写的是 `"hodl_waves": metric("hodl_waves")` —— `metric()` 实际查的是 `onchain.get("hodl_waves")`,DB 里压根没有 → `_series_latest()` 返 `(None, None)` → 永远 missing
- **派生为什么有值**:`hodl_waves_1y_plus_aggregate` 在 [spot_cycle_context_builder.py:1015-1025](src/ai/spot_cycle_context_builder.py#L1015-L1025) 是**派生指标**,把 6 个长尾 bucket(`1y_2y / 2y_3y / 3y_5y / 5y_7y / 7y_10y / more_10y`)求和算出来,逐个 bucket 名都是匹配的 → 正常有值
- 与 Glassnode endpoint / 配额都无关。一次 fetch_hodl_waves 已经拿到了所有 12 桶,只是 Layer A 上层查错了名字

### 现象 3:Puell Multiple 429 → "沿用 5 月 18 日数据" — **机制工作正常,根因待服务器日志确认**

- **重试逻辑**(`src/data/collectors/glassnode.py:170-220`):
  - 429 / 5xx / timeout / 408 → 触发 `_RetryableHTTPError` → 指数退避重试,3 次(3s / 6s / 12s)
  - 3 次都失败 → 抛 `GlassnodeCollectorError`,该 fetcher 算失败,**不影响其他 fetcher 继续**
- **失败分类**(`src/data/collectors/_classify_failure.py:80-81`):
  - 状态码 429 **或** 错误文本含 `quota / rate limit / 配额` → `failure_reason='quota_exceeded'`
  - 否则 429 不算 quota — 但 Puell 报 429 → 一律归 quota
- **沿用旧数据**:不是显式 fallback 机制,是**天然结果** —— 新 fetch 失败 → DB 没新行 → Layer A `metric("puell_multiple")` 读 `onchain_metrics` 表里**最新一条成功 row**(可能是 5/18 那天的)→ freshness 检测发现 >48h 标 stale,但 value 还在
- **偶发还是常态**:**代码层无法判断,必须看服务器 `/home/ubuntu/pipeline_logs/` 真实历史**。命令清单见底部
- **429 的真正源头(中转 vs 官方)**:`alphanode.work` 中转返回的 HTTP 429 错误文本里可能带 `quota` 字样(`_classify_failure._has_quota_keyword` 匹配),也可能不带。**不读服务器日志无法分**

---

## 2. Layer A 每跑一轮的 Glassnode 调用数 = 0 次

**关键发现:Layer A AI 调用本身 0 次 Glassnode**。`layer_a_spot_runner.py / orchestrator.py / spot_cycle_context_builder.py` 全程不 import `GlassnodeCollector`,只通过 `OnchainDAO.get_all_metrics()` 读 DB 本地缓存。Layer B 同理 — 全员"DB 读取,不调外部 API"。

**真正调 Glassnode 的入口只有 1 个**:`src/scheduler/jobs.py:836 job_collect_onchain`,绑定在 `config/scheduler.yaml:100-115` 的 `collect_onchain` job,**每天 08:35 / 09:35 / 10:35 BJT 三档 cron**(带 quota-aware 短路)。

每次该 job 跑完的 HTTP 调用数 = `_GLASSNODE_FETCHERS` 数组长度:

| # | fetcher | 当前在 _GLASSNODE_FETCHERS 注册? |
|---|---|---|
| 1 | fetch_mvrv_z_score | ✅ |
| 2 | fetch_nupl | ✅ |
| 3 | fetch_lth_supply | ✅ |
| 4 | fetch_exchange_net_flow | ✅ |
| 5 | fetch_mvrv | ✅ |
| 6 | fetch_realized_price | ✅ |
| 7 | fetch_lth_realized_price | ✅ (与 #8 共享 2 个 HTTP via breakdowns,实际 2 个 HTTP 总) |
| 8 | fetch_sth_realized_price | ✅ (同上) |
| 9 | fetch_sopr_adjusted | ✅ |
| 10 | fetch_percent_supply_in_profit | ✅ |
| 11 | fetch_exchange_balance | ✅ |
| 12 | fetch_lth_sopr | ✅ |
| 13 | fetch_sth_sopr | ✅ |
| 14 | fetch_rhodl_ratio | ✅ |
| 15 | fetch_reserve_risk | ✅ |
| 16 | fetch_puell_multiple | ✅ |
| 17 | fetch_lth_net_position_change | ✅ |
| 18 | fetch_sth_supply | ✅ |
| 19 | fetch_ssr | ✅ |
| 20 | fetch_cdd | ✅ |
| 21 | fetch_hodl_waves | ✅ |
| 22 | **fetch_hash_rate** | ❌ **MISSING — Sprint 82e59f9 漏注册** |

**单次 collect_onchain 成功跑**:HTTP 请求数 = **22 个 fetcher 但只 22 次 HTTP**(因 lth/sth realized price 2 个 fetcher 共享 2 个 HTTP via breakdowns 内部缓存,实际 7+8 = 2 HTTP 而非 4)。**hash_rate 当前 0 次**(未注册);若修复,+1 fetcher = +1 HTTP → 23 HTTP/run。

每次成功 fetcher 配对一次 fetch_attempts 写入 + DB upsert,但**不占 Glassnode quota**(那些是本地 DB 操作)。

---

## 3. 全系统 Glassnode 调用入口清单 + 月调用量估算

### 所有调用点(全 grep 后只有 1 个生产入口)

| 入口 | 频率 | 估算 HTTP/天 |
|---|---|---|
| **scheduler `collect_onchain`** ← 唯一生产路径 | 3 cron slots × quota-aware 短路 | 22(typical:第一档成功)|
| `scripts/run_layer_a_once.py`(手动)| 用户手动,不规律 | 0(不调 Glassnode,只读 DB)|
| `scripts/backfill_data.py`(手动 backfill)| 一次性 | 22 × `since_days` 数量级(灾难性突发)|
| `scripts/test_glassnode_collector.py`(本地调试)| 手动 | 22 一次 |
| Layer A AI / Layer B AI / 系统自检 health endpoint | N/A | **0 — 这些都不调 Glassnode**,只读 DB |

**关键确认:**
- 系统自检页面(`/api/system/health-detail`)**不调 Glassnode**,只 `SELECT MAX(inserted_at_utc) FROM onchain_metrics` 和读 `fetch_attempts` 表
- Layer B `pipeline_run_regular`(每天 11:35)**不调 Glassnode**,只走 `OnchainDAO.get_all_metrics()`
- `event_listener`(60 秒高频)**不调 Glassnode**

### 月调用量估算

| 场景 | 每天 HTTP | 每月 HTTP | vs 1700 配额 |
|---|---|---|---|
| 最佳:08:35 一次成功,9:35/10:35 短路 | 22 | **660** | 39% — 充裕 |
| 普通:21 个成功 + 1 个 429 重试 3 次 | 22 + 2 (retry) = 24 | **720** | 42% |
| 较差:多个 fetcher 429,3 时段都跑 | 22 × 3 = 66(若都失败)| **1980** | **116% — 超额** |
| 含 backfill `since_days=30` 一次 | 22 + 660 = 682 临时 | 视频次 | |

**判断**:正常运行下月用量 ~660-720,**远低于 1700 配额**。即使 Puell 偶发 429 重试加 5-10/天,也只到 ~750/月。

**配额耗尽假设的可信度判定**:
- 若用户的 alphanode 中转账户**单独**有 quota 上限(独立于 Glassnode 官方订阅),则有可能;
- 若 1700/月 是 Glassnode 官方订阅额度,只要本机 + 服务器一直按 22/day 跑,根本撞不到;
- **但**:用户可能在某次 backfill 中一次性烧 1000+ 次(`scripts/backfill_data.py since_days=180` 估算 22 × ~26 数据点 = 几百次),后果是月内 quota 提前用光,后半月所有 fetcher 都吃 429
- 也可能是 alphanode 中转站对**短时间内同一 endpoint** 设了滑窗限流(比如 Puell 每 5 分钟最多 N 次),与月度 quota 无关。**需要看 alphanode 后台的 quota dashboard 或服务器 log 报错文本细节**

---

## 4. 缓存 / 去冗余机制盘点

| 机制 | 在哪 | 行为 |
|---|---|---|
| `_onchain_today_complete` | `src/scheduler/jobs.py:326-380` | 今天 onchain_metrics 已有一手 Glassnode 数据 OR fetch_attempts 已撞 quota → 9:35/10:35 短路 skip |
| LTH/STH realized price 共享 HTTP | `src/data/collectors/glassnode.py:_fetch_lth_sth_realized_price` | 同一实例内,breakdowns 接口 2 次 HTTP 服务 2 个 fetcher |
| DB upsert 即天然"缓存" | `OnchainDAO.upsert_batch` | 跨日跨重启复用;Layer A 永远读最新成功 row;Glassnode 失败时上次成功值仍可用 |
| Layer A / Layer B 读 DB 不读 API | `OnchainDAO.get_all_metrics` | 0 额外 Glassnode 调用 |

**没有的机制**:
- **没有 in-process LRU 缓存**(每次 collect_onchain 都重新拉 180 天历史,即使昨天刚拉过)
- **没有"昨天数据当今天用"的明文 fallback**(natural fallback 通过 DB 自然实现)
- **collect_and_save_all(脚本路径)和 _GLASSNODE_FETCHERS(scheduler 路径)是两个独立 list**,容易像 hash_rate 这次这样漂移

---

## 5. 综合根因判断

| 现象 | 根因 | 与配额关系 |
|---|---|---|
| hash_rate missing | `_GLASSNODE_FETCHERS` 漏注册 fetch_hash_rate | **0%,与配额无关。修代码 + 服务器跑下次 collect_onchain 立即恢复** |
| hodl_waves missing | Layer A 查 `metric("hodl_waves")` 但 DB 写的是 `hodl_waves_<bucket>`,命名 mismatch | **0%,与配额无关。改 Layer A 上层查询路径即可,不需多消耗一次 fetch** |
| Puell Multiple 429 | 中转或官方限流,系统的重试/短路/沿用旧数据机制都在工作 | **可能 50%~80%**:取决于 alphanode 中转给你的额度模型是月度 quota 还是滑窗 rate-limit。需服务器日志确认 |

**三个现象不是同一根因。前两个是确定性代码 bug(可独立修),第三个是运行时偶发,需要日志判断。**

---

## 6. 修复方案建议(具体到文件 + 改法,本轮不动手)

### 方案 A — 立即可做的零额外调用修复(2 个文件,5 行改动)

**A.1 `src/scheduler/jobs.py:264-278`** 在 `_GLASSNODE_FETCHERS` tuple 末尾追加 `"fetch_hash_rate",`(1 行 + 1 个尾逗号)。修复后下次 `collect_onchain` job 跑时自动开始入库 hash_rate,月用量 +30 次。

**A.2 `src/ai/spot_cycle_context_builder.py:1004`** 把 `"hodl_waves": metric("hodl_waves"),` 改为某个真实 metric_name —— 最合理的选项之一:
- 删掉这行(`hodl_waves_1y_plus_aggregate` 已经在第 1015 行单独提供,信息没丢)
- 或改为 `"hodl_waves_long_tail_pct": _factor("hodl_waves_long_tail_pct", hodl_long_pct, ...)` 沿用现有派生值
- 或拆 12 桶分别 expose,例如新增 `metric("hodl_waves_more_10y")` 等关键长尾

我推荐**直接删行** —— aggregate 已经能告诉 AI "1年+ HODL 占比",bucket 级细节 Layer A 用不上。

### 方案 B — 配额硬限制下的"省调用"改造(更深入,需用户确认是否要做)

| 项 | 文件 | 改动概要 | 月省 |
|---|---|---|---|
| B.1 周级降频:RHODL / Reserve Risk 这种慢变量改一周抓 1 次 | `scheduler.yaml + jobs.py` | 单开一个 `collect_onchain_weekly` job,周一跑;主 daily job 跳过这两个 | -6 × 30 = 60/月 |
| B.2 since_days 收敛:目前 default 180,但 Layer A 只看最近 30 天 series;非首次跑可改 30 | `glassnode.py:262, 318` | 改 default、或新增"增量模式"参数 | 减小响应 size,但 Glassnode 配额按"请求次数"算,不按 size,所以**无效** |
| B.3 in-process LRU:同一进程内同一 endpoint 1 小时内不重复请求 | `glassnode.py:_request` | 加一个 dict cache,key = (path, params hash) | 防止 backfill 脚本意外重复 |
| B.4 删冗余:`ssr` / `cdd` 当前在 Layer A 仍 wired 但实际作用边缘 | `_GLASSNODE_FETCHERS` + Layer A factor 列表 | 评估是否真用,真不用就拿掉 | 每砍 1 个省 30/月 |
| B.5 backfill 加 quota 守护 | `scripts/backfill_data.py` | 跑前查 `fetch_attempts` 今天的累计 GET 数,> 1500 就 abort | 防止意外烧光月度配额 |

### 方案 C — 系统自检不真调 Glassnode

**用户描述里有这一项,但实际我已确认系统自检 `/api/system/health-detail` 本来就不调 Glassnode**,只读 `onchain_metrics.MAX(inserted_at_utc)`。所以这条不需要做,**已经是这样了**。

---

## 7. 等用户在服务器执行的命令(本机 ssh 不通,需用户回贴)

请你 SSH 上服务器后跑下面这组,我等结果继续判断 Puell 429 性质:

```bash
# 1. Puell Multiple 最近 7 天的所有 attempt 失败记录(看 429 是常态还是偶发)
sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \
  "SELECT attempted_at_utc, status, failure_reason, rows_upserted, substr(error_message, 1, 120) FROM fetch_attempts WHERE source='glassnode_onchain' AND attempted_at_utc >= datetime('now', '-7 days') ORDER BY attempted_at_utc DESC LIMIT 30;"

# 2. hash_rate 在 DB 里有没有任何历史行(应该是 0)
sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \
  "SELECT COUNT(*) FROM onchain_metrics WHERE metric_name='hash_rate';"

# 3. hodl_waves 系列(应该看到 hodl_waves_24h 等 12 个 bucket 各有行)
sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \
  "SELECT metric_name, COUNT(*) FROM onchain_metrics WHERE metric_name LIKE 'hodl_waves%' GROUP BY metric_name;"

# 4. Puell 最新 N 天每天有没有新行(确认沿用 5/18 是不是 5/18 之后真的没新 row)
sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \
  "SELECT date(captured_at_utc), MAX(captured_at_utc), MAX(inserted_at_utc) FROM onchain_metrics WHERE metric_name='puell_multiple' AND captured_at_utc >= datetime('now', '-15 days') GROUP BY date(captured_at_utc) ORDER BY 1 DESC;"

# 5. 最近 collect_onchain pipeline log 里 Puell / hash_rate 报错原文
ls -t /home/ubuntu/pipeline_logs/ | head -20
grep -h "puell\|hash_rate\|429" /home/ubuntu/pipeline_logs/*.log | tail -30
```

把第 1/4/5 三段输出贴回来,我就能告诉你 Puell 429 是月度配额耗尽还是 alphanode 滑窗限流;第 2/3 段确认我对 hash_rate / hodl_waves bug 的分析无误。
