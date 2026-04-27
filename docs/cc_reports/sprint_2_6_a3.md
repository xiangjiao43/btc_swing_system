# Sprint 2.6-A.3 — Yahoo 批量 API 重写(⛔ 阻塞:服务器 IP 被 Yahoo 全面封禁)

**Date:** 2026-04-27
**Branch:** main · commits `3887020` + `7d23d27`
**Status:** ⛔ **STOPPED** — 决策点 #1 触发,batch + fallback 两路径都 429

---

## 一、2 个独立 commit(代码 + 测试完成)

| commit | 文件 | 摘要 |
|---|---|---|
| `3887020` | `src/data/collectors/yahoo_finance.py`(+177/−18) | 新增 `fetch_all_symbols_batch(since_days)` 用 `yf.download(tickers_list, ..., group_by='ticker', threads=True)` 批量;重写 `collect_and_save_all` 为"批量主 + per-symbol fallback"。`fetch_symbol` 保留作 fallback 入口 |
| `7d23d27` | `tests/test_yahoo_collector_batch.py`(+166) | 7 个 case:batch 解析 MultiIndex / 空抛 / yfinance 异常包装 / batch 成功不走 fallback / batch 整体失败走 fallback / 部分失败混合路径 / 两路径全失败抛错。表 schema 用真实的 `metric_name + captured_at_utc + value + source`(而非测试内 mock) |

pytest:416 → 423(+7),无回归。

---

## 二、生产端验证:batch 也被 429 封死

### 部署日志(关键片段)

```
$ ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && git pull && \
    .venv/bin/python scripts/backfill_data.py --only macro --days 180'

# Yahoo 批量主路径
[ERROR] (batch path 失败,日志被截断未显示首行)
[WARN]  Yahoo batch path failed (...); falling back to per-symbol

# Yahoo per-symbol fallback 6 个全 429
[ERROR] dxy (symbol=DX-Y.NYB) fallback failed: Too Many Requests
[ERROR] us10y (symbol=^TNX) fallback failed: Too Many Requests
[ERROR] vix (symbol=^VIX) fallback failed: Too Many Requests
[ERROR] sp500 (symbol=^GSPC) fallback failed: Too Many Requests
[ERROR] nasdaq (symbol=^IXIC) fallback failed: Too Many Requests
[ERROR] gold_price (symbol=GC=F) fallback failed: Too Many Requests
[INFO]  Yahoo Finance collect done: total=0 rows, 0/6 metrics succeeded
[ERROR] [macro.yahoo] failed: All 6 Yahoo metrics failed (batch + fallback both)

# FRED 仍正常
[INFO]  FRED collect done: total=308 rows, failures=0/4
[INFO]  [macro.fred] fetched=308 upserted=308

=== db before === 2400256 bytes
=== db after  === 2400256 bytes(0 字节增长 — 因为 FRED 已经回填过,本次都是 upsert 同行)

=== macro_metrics by source/metric ===
  fred  cpi                5
  fred  dff                177
  fred  dgs10              121
  fred  unemployment_rate  5
=== total rows: 308(无 yahoo) ===
```

### 诊断

`yf.download(threads=True)` 内部仍是并发 6 个 HTTP 请求 — 与 per-symbol 循环
唯一区别是 yfinance 自己做的并发 + 节流配合,但 Yahoo 已经在 IP 级别 ban 了我
的服务器,**任何来自 124.222.89.86 的请求都被拒**。批量 API 的"绕开 per-symbol
429" 假设在 IP 级 ban 面前不成立。

按 spec 第 5 段「关键决策点 — 必须停下问用户」第 1 条:
> 如果 yf.download 批量调用仍然 429 → 停下问我(可能 Yahoo 真的全面封禁,
> 需要彻底换方案)

→ 触发停下。

---

## 三、Yahoo 路径的最后一次复盘

经过 Sprint 2.6-A / 2.6-A.1 / 2.6-A.3 三轮尝试:
- **2.6-A**:重写 backfill_macro 调用约定 — Yahoo 全 429
- **2.6-A.1**:加 commit() 修事务丢失 — FRED 通了 308 rows;Yahoo 仍 429
- **2.6-A.3**:batch API + fallback — batch 也 429,fallback 也 429

可以确定:**这台服务器 IP 已被 Yahoo Finance 全局封禁**(可能是云服务商 IP 段
集体被 ban,常见于 Tencent Cloud / AWS / Azure 等公网池)。在不换 IP 或不
换数据源的前提下,Yahoo 路径无解。

---

## 四、决策项(用户必选)

### A — 接受现状,只用 FRED + 长期 L5 部分覆盖
- L5 `data_completeness ~ 25%`(只有 FRED 的 dff / dgs10 / cpi / unemployment_rate)
- 最缺:DXY / VIX / 纳指 / SP500 → 都是 L5 MacroHeadwind 主因子
- 系统按规则保守判断,长期不会真正激进

### B — 走 IP 代理 / 中转(违反 yfinance 直连约束)
- 在 yfinance.download 调用前设置 HTTP_PROXY / HTTPS_PROXY 环境变量
- 或部署一个境外 VPS(US/EU)作 HTTP 代理,服务器走代理出去
- 对手:仍可能因为代理 IP 也是 datacenter 池而被 ban
- 工作量:小(2 行代码 + 1 个 VPS),但需用户确认愿意付代理费

### C — 接 Alpha Vantage / Polygon / Finnhub 等付费友好的 API
- 都需注册免费 API key
- Alpha Vantage:免费 25 req/day,付费 $50/月起
- Polygon:免费 5 req/min,付费 $30/月起
- Finnhub:免费 60 req/min(含 forex / index)
- 工作量:中等,要写新 collector,但不会再被封

### D — 用浏览器插件 / 桌面应用从用户本地拉数据,周期性同步到服务器
- 例如:本地跑 cron 拉 Yahoo,upload 到服务器 DB
- 工作量:大,运维不方便,且本地需开机

### E — 改用 Stooq + apikey(回到 Sprint 2.6-A.2 的 A 选项)
- 用户去 https://stooq.com/q/d/?s=^spx&get_apikey 解 captcha
- 拿到 32 字符 apikey
- 我加 `&apikey=` 参数到 stooq.py 的 URL
- Stooq 包含 DXY / VIX / 纳指 / SP500 / 黄金 全部需要的 symbol
- 工作量:小

### 我推荐:E(回头用 Stooq + apikey)+ 保留 FRED

**理由**:
1. Stooq 是欧洲(波兰)IP,大概率不像 Yahoo 那样对 datacenter IP 敌视
2. apikey 一次拿,不到 5 分钟
3. 数据完整(6 个宏观指标都有)
4. 与 FRED 互补(FRED 出宏观经济指标,Stooq 出市场指数 + 商品)
5. 已经探好 Stooq 的 6 个 ticker 候选(写在 `scripts/probe_stooq_tickers.py`)

---

## 五、未触发的硬约束(本 sprint 全部遵守)

- ✅ 没改 fred.py / coinglass.py / glassnode.py
- ✅ 没改 L1-L5 evidence / scheduler 主流程 / state_builder
- ✅ 没改 modeling.md / CLAUDE.md
- ✅ 没 commit .env
- ✅ pytest 423 pass(416 + 7 新),无回归

---

## 六、git log

```
7d23d27 test(yahoo): add coverage for batch path and fallback behavior
3887020 feat(yahoo): use yf.download batch API to bypass per-symbol 429
```

(部署 + L5 验证因决策点 #1 停下未做;L5 仍是 unknown)
