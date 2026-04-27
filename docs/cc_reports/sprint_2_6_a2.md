# Sprint 2.6-A.2 — Stooq 接入(⛔ 阻塞:Stooq 已改为 apikey 必填)

**Date:** 2026-04-27
**Branch:** main · commit `ba0ee1e`
**Status:** ⛔ **STOPPED** — 决策点 #1 触发,所有 ticker 候选全部失败

---

## 一、唯一 commit

| commit | 文件 | 摘要 |
|---|---|---|
| `ba0ee1e` | `scripts/probe_stooq_tickers.py`(新建,95 行) | Stooq ticker 探测工具,枚举 6 个宏观指标 × 多候选 ticker |

---

## 二、Stooq 已改为 apikey 必填 — 自由 CSV API 不复存在

### 探测脚本输出(服务器跑)

```
$ ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && .venv/bin/python scripts/probe_stooq_tickers.py'

metric       ticker       status   rows  latest        notes
------------------------------------------------------------------------------------------
dxy          ^DXY         FAIL                         ParserError: Expected 1 fields, saw 2
dxy          DX.F         FAIL                         empty/no data
dxy          DX-Y.NYB     FAIL                         ParserError: Expected 1 fields, saw 2
  ⚠ dxy 无可用 ticker
us10y        ^TNX         FAIL                         ParserError: ...
... (vix / sp500 / nasdaq / gold_price 全部 FAIL)

=== 最终选定 ticker map(空)===
```

**6 个宏观指标 × 17 个候选 ticker 全部失败,无 winner。**

### 根因诊断

直接 curl Stooq 返回的不是 CSV,而是文本说明:

```
$ curl -A "Mozilla/5.0 ..." "https://stooq.com/q/d/l/?s=^spx&i=d"

Get your apikey:

1. Open https://stooq.com/q/d/?s=^spx&get_apikey
2. Enter the captcha code.
3. Copy the CSV download link at the bottom of the page - it will contain the <apikey> variable.
4. Append the <apikey> variable with its value to your requests, e.g.
   https://stooq.com/q/d/l/?s=^spx&i=d&apikey=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

也即 Stooq.com 已经把"免费匿名 CSV 下载"改为"需 apikey",获取流程:
1. 用浏览器开 `https://stooq.com/q/d/?s=^spx&get_apikey`
2. 解 captcha
3. 拿到 32 字符 apikey
4. 后续请求 URL 加 `&apikey=XXX...`

从服务器 + Mac 两个网络都跑过同样的 curl,响应一致 — 不是 IP 地理封锁,是
Stooq 全局策略变更。

---

## 三、阻塞决策点(用户必选)

按 spec 第 5 段「关键决策点 — 必须停下问用户」第一条:
> 如果 probe 脚本显示某个 metric 所有候选 ticker 都不可用 → 停下问我

6 个 metric 全部所有候选都不可用 → 触发停下。

### 选项 A — 用户去拿 Stooq apikey,沿用 Sprint 2.6-A.2 计划

1. 用户浏览器开 https://stooq.com/q/d/?s=^spx&get_apikey
2. 解 captcha,复制 32 字符 apikey
3. 添加到服务器 .env:`STOOQ_API_KEY=xxx...`(也加到 .env.example 占位)
4. 我改 `probe_stooq_tickers.py` 和 stooq.py 在所有请求 URL 加 `&apikey={key}`
5. 重跑 probe → 选出 winner ticker → 写 `stooq.py` → 接入 scheduler

工作量小,纯文档 + 2 行代码加 apikey 参数,后续步骤照原 spec 走。

### 选项 B — 换其它免费源

候选(都未验证可用性):
- **Alpha Vantage**:免费层 5 req/min,500 req/day,需 API key(免费注册)
- **Polygon.io**:免费层 5 req/min,需 API key
- **Finnhub**:免费层 60 req/min,需 API key
- **TradingEconomics**:历史数据需 paid
- **Investing.com (investpy)**:被 Cloudflare 封,Python 库已停止维护

工作量较大:每换一家都要写新 collector + probe ticker 命名 + 处理限速。

### 选项 C — 修 Yahoo collector(违反 Sprint 2.6-A 硬约束 #1)

在 `yahoo_finance.py` 加:
- `time.sleep(60)` 在每个 symbol 之间(6 个 symbol 共 6 分钟,可接受)
- 或换用 `yfinance.download(["DX-Y.NYB", "^TNX", ...])` 批量 API(一次请求多 symbol,绕开 per-symbol 429)

工作量小,但违反"不动 collector 内部"约束 — 需用户开 Sprint 2.6-A.3 明确授权。

### 选项 D — 接受现状,不做宏观

当前生产已有 FRED 4 个 series(308 行),L5 `data_completeness ~ 25%`。
保持 Yahoo 退役 / Stooq 不接,L5 长期 unknown,系统按规则保守。

---

## 四、推荐

**A 选项**(用户拿 apikey)+ **C 选项**(批量 API 修 Yahoo)二选一,都简单。

我倾向 **C**:`yfinance.download(symbols, start, end)` 是 yfinance 库的批量
接口,一次请求拉多 symbol,绕开 per-symbol 限速;不需新增数据源、不需 apikey、
不增加运维负担。代价是:违反 2.6-A 硬约束 #1(改动 yahoo_finance.py 内部),
需用户明确授权。

---

## 五、未触发的硬约束(本 sprint 全部遵守)

- ✅ 没动 yahoo_finance.py / fred.py / coinglass.py / glassnode.py 内部
- ✅ 没改 modeling.md / CLAUDE.md
- ✅ 没 commit .env
- ✅ pytest 仍 416 passed(只加了 1 个 script 文件,无新代码影响逻辑)

---

## 六、git log(本 sprint 范围)

```
ba0ee1e scripts(probe): add Stooq ticker probe utility
```

(只有探测脚本一个 commit;stooq.py / 接入 / 部署等步骤全部因决策点停下未做)
