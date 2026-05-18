# Sprint Puell Multiple 持续失败根因排查

**日期**:2026-05-17
**前置假设(已推翻)**:Glassnode 月度配额耗尽。用户指出其他 22 个 Glassnode 指标全部正常,只 puell 一个失败 → 不可能是配额问题(配额按 key 计,卡也卡全部)。
**纯调查 + 方案**,本轮不改代码。

---

## 1. 关键证据(本机直接调 alphanode 验证)

我从本机用真实 GLASSNODE_API_KEY(脱敏)对 alphanode 中转站同时调 6 个 endpoint(puell + 5 个其他正常工作的 `/indicators/` 端点 + hash_rate 控制组)。结果:

| Endpoint | Source 标签 | HTTP | 响应 |
|---|---|---|---|
| `/v1/metrics/indicators/puell_multiple`(failing in prod) | `glassnode_layer_a` | **200** | 完整 7 天数据,值 0.78~0.97(BTC Puell 正常范围)|
| `/v1/metrics/indicators/rhodl_ratio`(working in prod) | `glassnode_layer_a` | **200** | 7 天 RHODL 数据 |
| `/v1/metrics/indicators/reserve_risk`(working) | `glassnode_layer_a` | **200** | 7 天 Reserve Risk |
| `/v1/metrics/indicators/sopr_more_155`(LTH SOPR, working) | `glassnode_layer_a` | **200** | 7 天 LTH SOPR |
| `/v1/metrics/indicators/sopr_adjusted`(working) | `glassnode_display` | **200** | 7 天 SOPR adjusted |
| `/v1/metrics/mining/hash_rate_mean`(本 sprint 修过的)| `glassnode_layer_a` | **200** | 7 天 hash rate |

**结论(代码 + 路径层)**:
- puell 与 RHODL / Reserve Risk / LTH SOPR / SOPR Adjusted 走**完全同构**的 `/v1/metrics/indicators/<name>` 路径
- 同样 `source="glassnode_layer_a"` 标签,同一份 GLASSNODE_API_KEY,同一个 alphanode 中转域名
- puell 当前(本次调用时刻)**完全没坏**:200 OK + 真实数据
- 配额没耗尽、订阅权限正常、endpoint 路径正确、参数正确、key 工作正常

**那为什么生产端持续失败?**问题不在路径、订阅或配额,**而在系统逻辑设计**。

---

## 2. 根因 1(核心,真正困死 puell 的元凶):`_onchain_today_complete` 锁死后续档

### 锁死机制(致命路径)

[src/scheduler/jobs.py:319-323 `_ONCHAIN_FIRST_HAND_SOURCES`](src/scheduler/jobs.py#L319-L323)+ [`_onchain_today_complete` (line 326-380)](src/scheduler/jobs.py#L326-L380):

```python
_ONCHAIN_FIRST_HAND_SOURCES = (
    "glassnode_primary",
    "glassnode_display",
    "glassnode_derived_breakdown_by_age",
)

def _onchain_today_complete(conn):
    # (a) 今天 onchain_metrics 表有任意一手 Glassnode 数据 → 返 True → skip
    # (b) 今天 fetch_attempts 撞 quota → 返 True → skip
    ...
```

**致命:puell_multiple 的 source 是 `"glassnode_layer_a"`,不在白名单!**

每天 collect_onchain 的实际命运:

1. **08:35 BJT 第一档 cron 触发**:循环 _GLASSNODE_FETCHERS 22 个 fetcher
2. mvrv (primary) / nupl (primary) / sopr_adjusted (display) / mvrv_z_score (primary) 等 21 个 fetcher **顺利成功** → `onchain_metrics` 表当天有 `source='glassnode_primary'` 行
3. **puell 失败**(任何瞬时原因:alphanode 在 00:35 UTC = Glassnode daily refresh 高峰对 puell 临时限流;3 次内部重试都没过 — `_request` 的指数退避 3s→6s→12s 也吃不了)
4. 整个 collect_onchain job 当作"部分成功"返回,fetch_attempts 写一行(rows_upserted ≈ 21 个 fetcher 总和)
5. **09:35 第二档 cron**:`_onchain_today_complete()` → (a) 当天 source IN (primary, display, breakdown) 已经有行(mvrv 等的) → **返 True → skip 整个 collect_onchain**
6. **10:35 第三档**:同理 skip
7. **puell 当天没有第二次重试机会**
8. 次日 08:35 再来一次:同样的瞬时窗口(00:35 UTC alphanode 高峰),puell **又失败**,其他 21 个 fetcher 又成功 → 同样的锁死循环
9. **puell 持续 stuck 自 5/15 (or 5/16) 的最后一次成功**

### 这个设计为什么这样?

代码注释([jobs.py:314-318](src/scheduler/jobs.py#L314-L318))写道:
> "Sprint C(2026-05-08):onchain '今日完整性'门简化 — 任一一手 Glassnode 行今天写过就算完成。老的 _ONCHAIN_EXPECTED_METRICS_TODAY 13-metric 全集合检查 + _ONCHAIN_HODL_WAVES_PREFIX 已删除(13 个 fetcher 共用一个 fetch_attempts bucket,所以'全部 13 metric 今天都写过'和'任一一手 source 今天有行'在 quota 分流后语义等价)。"

**这个简化是在"quota 短路 + 全 fetcher 同进同退"假设下做的**。当时假设 22 个 fetcher 要么全成功要么全失败(配额耗尽全栽);"任一一手 source 有行"就等于"全部成功"。

**但实际不是这样**。22 个 fetcher 是独立 try/except,**puell 单独可以失败 21 个独活**。Sprint C 的简化破坏了"细粒度完整性门",直接让单 endpoint 失败永久卡死。

---

## 3. 根因 2(辅助,误导用户但不直接卡死 puell):`_classify_failure` 把 429 一刀切归 `quota_exceeded`

[src/data/collectors/_classify_failure.py:80](src/data/collectors/_classify_failure.py#L80):

```python
if status == 429 or _has_quota_keyword(raw):
    return "quota_exceeded", msg
```

**所有 429 都被归 quota_exceeded**,**不论 alphanode 返回的正文有没有 `quota` / `rate limit` / `配额` 字样**。

这导致:
- health 面板显示"配额耗尽"误导用户以为 5/14 续费后真的没生效
- fetch_attempts.failure_reason='quota_exceeded' 触发 `_onchain_today_complete` (b) 分支 — 但 (b) 只当天阻断,不跨天,所以不是 puell **持续**失败的根因(根因 1 才是)
- 服务器侧 fetch_attempts 表里历史"quota_exceeded"很可能不是真配额耗尽,而是 alphanode 对 puell 临时限流被错分类

### Glassnode 官方 429 含义(行业知识)

Glassnode / alphanode 都使用 HTTP 429,但语义不同:
- **真配额耗尽(月度)**:响应正文通常含 `"You have exceeded your monthly quota"` / `"plan limit"` / `"quota_exhausted"`
- **短时滑窗限流(per-second / per-minute rate limit)**:正文含 `"rate limit exceeded, retry after N seconds"` / `"too many requests"`
- **endpoint 单独限流**:正文可能含 `"endpoint busy"` / `"upstream provider 429"` / 也可能裸 429 无正文

代码这里**全部归 quota,信息损失**,且系统的不同分支(`_onchain_today_complete` (b))会因此误启动短路。

---

## 4. 为什么本机刚才能 200 OK?

刚才我从本机用同 key + 同 endpoint 调 puell:HTTP 200 + 完整数据。证明:
- **当前**(我跑命令的时刻)alphanode 对 puell 不限流
- 但 alphanode **在某些时刻**(尤其 Glassnode 全网 daily refresh 高峰 00:00-01:00 UTC = BJT 08:00-09:00)对热门 endpoint **可能**临时返 429
- 服务器 cron 偏巧设在 08:35 BJT(= 00:35 UTC),正好撞这个窗口
- 我从本机在别的 UTC 时刻调,避开了这窗口

**根因 1 + 这个时刻巧合 = puell 持续从 5/15、5/16 之后失败**。

---

## 5. 修复方案(本轮不动手)

### 方案 1 — 修根因 1:`_onchain_today_complete` 细粒度化(强烈推荐)

让"今天完成"判定基于**关键 fetcher 各自都写过**,不是"任一一手 source 今天有行"。两个实现选择:

**1A(精细但代码量大)**:维护一个"必须今天写过"的 metric 白名单(7-10 个 Layer A 关键因子),`_onchain_today_complete` 检查每个白名单 metric 今天都有行才返 True:

```python
_REQUIRED_TODAY_METRICS = (
    "puell_multiple", "mvrv_z_score", "nupl", "rhodl_ratio",
    "reserve_risk", "lth_sopr", "sth_sopr", "hash_rate",
)
def _onchain_today_complete(conn):
    today = date.today().isoformat()
    for m in _REQUIRED_TODAY_METRICS:
        row = conn.execute(
            "SELECT 1 FROM onchain_metrics WHERE metric_name=? AND captured_at_utc LIKE ? LIMIT 1",
            (m, f"{today}%"),
        ).fetchone()
        if row is None:
            return False  # 任一缺失就让后续 cron 重试
    return True
```

**1B(更精打细算)**:在 `job_collect_onchain` 循环里**先查 metric 是否今天已有行,有就 skip 该 fetcher**;这样 09:35 cron 触发时只会重抓昨日没成功的 fetcher。HTTP 用量增长 = 重试失败 fetcher 的 1-2 次(最坏 +60 HTTP/月)。

**对 quota 影响**:最坏情况(每天都有 1 个 fetcher 失败 1 次)= 22 + 1 = 23 HTTP/day × 30 = 690/月,vs 当前 22 × 30 = 660/月,差 30。仍**远低于 1700/月**。

### 方案 2 — 修根因 2:`_classify_failure` 细分 429

```python
# 改前
if status == 429 or _has_quota_keyword(raw):
    return "quota_exceeded", msg

# 改后
if status == 429:
    if _has_quota_keyword(raw):
        return "quota_exceeded", msg  # 月度配额耗尽,真正硬阻塞
    return "rate_limited", msg          # 短时限流,可重试,不应触发 today_complete (b) 短路
if _has_quota_keyword(raw):
    return "quota_exceeded", msg        # 无 429 但带 quota 关键字也归
```

然后 `_onchain_today_complete` (b) 检查从 `failure_reason='quota_exceeded'` 改为只在真 quota 时短路(不再被 rate_limited 误触发)。

这条独立可做,即使方案 1 不上也能让 health 面板诚实显示,以及避免假阳性短路。

### 方案 3 — 部署期错峰(无代码,最快验证)

把 [config/scheduler.yaml:108-114](config/scheduler.yaml#L108-L114) 的 `collect_onchain` cron 时间从 **08:35 / 09:35 / 10:35** 改为 **09:30 / 10:30** 两档(避开 00:35-01:00 UTC alphanode 高峰)。

副作用小、零代码改动,**但治标不治本**:只要还有任何瞬时单 endpoint 失败,根因 1 仍然会锁死后续档。

### 推荐顺序

1. **方案 1B(细粒度 today_complete)** —— 根本修复,中等复杂度
2. **方案 2(429 细分)** —— 同时做,信息层修复 + 健康面板更准 + 避免假阳性短路
3. **方案 3(错峰)** —— 可选,作为方案 1 上线之前的临时缓解;1 上线后这条可不做

---

## 6. 等用户在服务器验证根因 1 的命令

按方案 1 上线之前,跑这两条 SQL 确认根因 1 假设:

### #6.1 — 今天(任意一天)collect_onchain 跑完后,puell **当天**有没有行 vs 其他 fetcher 有没有

```bash
sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \
  "WITH today AS (SELECT strftime('%Y-%m-%d', 'now') AS d)
   SELECT metric_name,
          MAX(captured_at_utc) AS latest_captured,
          MAX(inserted_at_utc) AS latest_inserted
   FROM onchain_metrics
   WHERE metric_name IN ('puell_multiple','mvrv_z_score','nupl','rhodl_ratio',
                          'reserve_risk','lth_sopr','sth_sopr',
                          'sopr_adjusted','exchange_balance','mvrv')
   GROUP BY metric_name
   ORDER BY metric_name;"
```

**怎么看**:
- 多数 metric latest_captured/inserted 是今天(说明 08:35 cron 跑成功了这些 fetcher)
- **puell_multiple 的 latest 停在 5/15 或 5/16**(说明从那天起就再没成功过)
- 这与根因 1 完全吻合:其他成功 → today_complete=True → puell 没第二次机会

### #6.2 — fetch_attempts 5/13 起每天的状态码 / 失败 reason / rows_upserted

```bash
sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \
  "SELECT attempted_at_utc, status, failure_reason,
          rows_upserted,
          substr(error_message, 1, 150) AS err
   FROM fetch_attempts
   WHERE source='glassnode_onchain'
     AND attempted_at_utc >= '2026-05-13'
   ORDER BY attempted_at_utc DESC
   LIMIT 25;"
```

**怎么看**:
- 每天通常 1 条记录(第一档跑完,后续档 skip)
- `status='success'` 但 `rows_upserted` 比之前少几十(因为 puell 那部分行没入)→ 印证"部分成功"模式
- `status='failure'` failure_reason='quota_exceeded' 几条 → 是 _classify_failure 误归类,实际正文需要 pipeline_logs 看

### #6.3 — 在 server 上跑一次"绕过 today_complete 短路"的强制 puell 抓取(零风险,只 +1 HTTP)

```bash
cd /home/ubuntu/btc_swing_system && .venv/bin/python -c "
from src import _env_loader  # noqa
from src.data.collectors.glassnode import GlassnodeCollector
from src.data.storage.connection import get_connection
from src.data.storage.dao import OnchainDAO, OnchainMetric
import datetime as dt

c = GlassnodeCollector()
try:
    rows = c.fetch_puell_multiple(since_days=10)
    print(f'fetch_puell_multiple OK: {len(rows)} rows')
    for r in rows[-3:]:
        print(' ', r)
    # 入库一次
    conn = get_connection()
    metrics = [OnchainMetric(r['timestamp'], r['metric_name'], r['metric_value'], r['source']) for r in rows]
    n = OnchainDAO.upsert_batch(conn, metrics)
    conn.commit()
    print(f'upserted {n} rows')
except Exception as e:
    print(f'FAILED: {type(e).__name__}: {e}')
"
```

**怎么看**:
- 成功 + 200 OK + 入库几行 → **证实根因 1**:puell endpoint 本身工作正常,只是被系统逻辑锁死。修复方案 1 即可
- 失败 + 429 + 完整 error body → 把 body 文本贴回来,我能进一步判断 alphanode 限流类型(月度配额 / 滑窗 / endpoint 维护)

---

## 7. 部署四件事清单(纯调查 + 方案)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A(纯调查)|
| GitHub 推送 | N/A |
| 服务器 git pull | N/A |
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 | N/A |
