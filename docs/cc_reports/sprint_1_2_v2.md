# Sprint 1.2 v2 — 放弃 Binance,统一到 CoinGlass 承担 K 线 + 衍生品

**日期**:2026-04-23
**触发**:Sprint 1.2 + 1.2-fix 连续两次尝试 Binance 都因美国 IP 失败
**依据**:用户旧系统 `data_fetchers.py` 已验证 `api.alphanode.work + x-key`

---

## ⚠️ Triggers for Human Attention

> 以下是本次重做需要人类注意的决策点。

### 1. ⚠️ 每个衍生品端点的 params 是我**按 CoinGlass v4 API 惯例推测**的,可能和你旧系统实际传参不完全一致

旧系统的 `data_fetchers.py` 我没拿到原文,只读了你转述的端点路径和 K 线参数(`symbol=BTCUSDT, exchange=Binance, interval, limit`)。衍生品的参数我按 CoinGlass v4 文档惯例猜测:

| 端点 | 我传的 params |
|---|---|
| K 线 | `symbol=BTCUSDT, exchange=Binance, interval, limit` |
| funding-rate/history | `symbol=BTCUSDT, exchange=Binance, interval, limit` |
| open-interest/aggregated-history | `symbol=BTC, interval, limit`(aggregated = 不传 exchange)|
| global-long-short-account-ratio/history | `symbol=BTCUSDT, exchange=Binance, interval, limit` |
| liquidation/history | `symbol=BTC, interval, limit` |
| net-position/history | `symbol=BTCUSDT, exchange=Binance, interval, limit` |

**本地验证路径**:跑 `uv run python scripts/test_coinglass_collector.py`。如果某端点 400 / 422 / 返回空 data 数组,很可能是**缺失某个 required param**。把完整报错贴给我,我按旧系统实际参数修。

### 2. ⚠️ 响应字段名兜底列表可能不全

CoinGlass 不同版本 / 不同端点的 value 字段命名不统一。我按常见变体写了兜底(见 `coinglass.py` 里 `_extract_numeric` 调用列表),例如 funding 试 `["fundingRate", "funding_rate", "rate", "value", "close", "c"]`。

如果本地跑时日志出现 `Skipping ... row without numeric value (...)`,说明**实际字段名不在我的候选列表**。请把一条原始响应 JSON 示例贴给我(比如 `curl ...` 一次看看),我加字段名。

### 3. `liquidation/history` 端点拆分为三个 metric

CoinGlass 清算数据常返回 `{longLiquidation, shortLiquidation}` 分开两列。我的实现:
- `liquidation`:总和(longLiq + shortLiq 或 API 直接提供的 total)
- `liquidation_long`:多头清算
- `liquidation_short`:空头清算

这让单次 `fetch_liquidation_history` 可能产生**超过 500 行 DAO 记录**(3 × timestamps)。统计字典里仍按 `liquidation` 聚合显示。

### 4. Glassnode 的 auth_method 在这一轮被"**二次修正**"

Sprint 1.2 fix 写了 glassnode 用 `auth_method: query`(`?api_key=<key>`)。你这次明确了旧系统 **两个中转都用 header `x-key`**。我把 glassnode 也改成 `auth_method: header`。

**连锁效应**:Sprint 1.3(Glassnode collector)实现时按本轮配置来,不要按旧 fix 的 query 方式。如果实际验证时 Glassnode 要求 query 而 CoinGlass 要求 header(即两边鉴权方式其实不同),告诉我,我再拆。

### 5. 中转站 `/v4/api/` 路径前缀的含义

CoinGlass 官方 v4 API 是 `https://open-api.coinglass.com/api/v4/...`;alphanode 中转站把它映射成 `https://api.alphanode.work/v4/api/...`(路径里 **v4 在 api 前面**,顺序反了)。这是旧系统验证过的路径。

如果本地 404,可能是:
- 中转站改了路径映射(比如改成 `/api/v4/`)
- 某些端点只有部分版本支持

### 6. 限速:**跑一次完整 `collect_and_save_all` 约需 36-60 秒**

15 req/min → 4s 最小间隔。9 次请求至少 32-36s(首次请求不需要等)。如果你观察到跑得比这更快,说明限速逻辑有问题;如果更慢,说明中转站本身慢。

### 7. K 线的 `volume_usdt` 字段未填

CoinGlass `/v4/api/futures/price/history` 响应通常只有单列 `volume`(基础币种 BTC 计)。DAO 的 `KlineRow.volume_usdt` 是 Optional,我传了 `None`。

**影响**:以后 `data_catalog.yaml` 里如果有因子依赖 `volume_usdt`,需要**另外从 `/futures/trading-volume` 或类似端点**拉取,或直接从 K 线 close × volume_btc 估算。Sprint 1.3+ 再处理。

### 8. 建模文档 §3.6.1 / §3.6.2 **没有**同步

建模文档还写 "Binance K 线"、"币安永续资金费率" 等。我**不改建模文档**:
- 建模文档是 v1.2 冻结的"决策蓝本",不应为实现路由变更而修订
- PROJECT_LOG.md 记录实现层决策已经足够审计

如果你希望同步建模文档,告诉我,我会在对应章节加"v1 实现:通过 CoinGlass 中转站提供"的说明。

---

## 1. 变更清单

### 删除

| 路径 | 说明 |
|---|---|
| `src/data/collectors/binance.py` | Sprint 1.2 的 BinanceCollector + Sprint 1.2 fix 的 klines-only 版本 全部作废 |
| `scripts/test_binance_collector.py` | 对应测试脚本 |

### 新增

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/data/collectors/coinglass.py` | ~450 | CoinglassCollector 类 |
| `scripts/test_coinglass_collector.py` | ~105 | 人工验证脚本 |
| `docs/cc_reports/sprint_1_2_v2.md` | — | 本报告 |

### 修改

| 文件 | 变更 |
|---|---|
| `src/data/collectors/__init__.py` | 暴露 `CoinglassCollector` / `CoinglassCollectorError`,去掉 Binance |
| `config/data_sources.yaml` | 删 `binance`;`coinglass` 改 `api.alphanode.work` + `x-key` header;`glassnode` 同步改 header auth;顶部加架构说明注释 |
| `.env.example` | 删 `BINANCE_BASE_URL`;明确两个 API_KEY 通常填同一个 alphanode 值 |
| `docs/PROJECT_LOG.md` | 追加 2026-04-23 重做决策(放在同日 fix 记录之前) |

### 未修改

- `src/data/storage/*`(无关)
- `src/data/collectors/_config_loader.py`(字段结构沿用 Sprint 1.2 fix 命名)
- `config/schemas.yaml` / `tests/fixtures/*`(无关)
- `docs/modeling.md`(不改,理由见 Trigger 8)

---

## 2. CoinglassCollector API 一览

| 方法 | 端点 | 产出 |
|---|---|---|
| `fetch_klines(interval, limit, symbol, exchange)` | `/v4/api/futures/price/history` | OHLCV list |
| `fetch_funding_rate_history(interval, limit, symbol, exchange)` | `/v4/api/futures/funding-rate/history` | `{ts, metric_name=funding_rate, value}` |
| `fetch_open_interest_history(interval, limit, symbol)` | `/v4/api/futures/open-interest/aggregated-history` | 同上(metric_name=open_interest)|
| `fetch_long_short_ratio_history(interval, limit, symbol, exchange)` | `/v4/api/futures/global-long-short-account-ratio/history` | 同上(long_short_ratio) |
| `fetch_liquidation_history(interval, limit, symbol)` | `/v4/api/futures/liquidation/history` | 拆 long/short/total 三个 metric |
| `fetch_net_position_history(interval, limit, symbol, exchange)` | `/v4/api/futures/net-position/history` | net_position |
| `collect_and_save_all(conn)` | (以上全部) | `{label: rows_upserted}` |

### `collect_and_save_all` 预期行数(每 interval 500 条为上限)

| Label | 预期 |
|---|---|
| klines_1h / 4h / 1d / 1w | 各 ≤ 500 |
| funding_rate | ≤ 500 |
| open_interest | ≤ 500 |
| long_short_ratio | ≤ 500 |
| liquidation | ≤ 500 × 3 个 metric = 1500 |
| net_position | ≤ 500 |
| **总计** | **~4500 rows** |

---

## 3. 实现要点

### 限速(旧系统 RateLimiter 15 req/min)

采用**滑动窗口**:维护 `deque` 记录最近 60 秒内的请求时间,若当前时间窗口内已有 15 次,sleep 到最老一次超过 60s 为止。比固定 4s 间隔更精确。

### 重试(旧系统 2 次 × 8s 间隔)

实现为 `max_attempts: 3`(首次 + 2 次重试),`backoff_strategy: fixed`,`backoff_sec: 8`。复用 Sprint 1.2 的 `_RetryableHTTPError` / `CoinglassCollectorError` 分类模式:retry_on_status(408/429/5xx)走重试,其他 4xx 立即失败。

### 响应 envelope

CoinGlass 响应通常是 `{code, msg, data: [...]}` 或 `{success, data: [...]}`。`_unwrap_data` 兜底:
- 顶层是 list → 直接返回
- 顶层是 dict → 找 `data`;若 data 是 list 返回,若 data 是 dict 且含 `list` 返回 `data.list`,否则包装成单元素 list

### 字段名兼容(见 Trigger 2)

`_normalize_ohlc_row`:同时支持旧缩写(`o/h/l/c/v`)和全名(`open/high/low/close/volume`)+ 以及 `close` 还兼容 `value`(某些指标端点把值放在 value 里)。
`_normalize_timestamp`:同时支持 ms int、秒 int、ISO string、数字字符串。
`_extract_numeric`:按候选列表顺序试,第一个非 None 的 float 化。

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 完全删除 `binance.py` / `test_binance_collector.py`(不保留 deprecated) | 架构决策 + 文件无调用方;git 历史留作审计 |
| B | 同步修正 Glassnode auth 为 header `x-key`(用户本次未显式要求,但说 "两个中转共享鉴权") | 架构一致性优先 |
| C | `data_sources.yaml` 顶部加大段架构说明注释 | 未来读配置的人能一眼看懂"为什么没有 binance" |
| D | `liquidation` 端点拆三个 metric(total/long/short)| CoinGlass 响应通常分开;保留细分信息利于 Crowding 分析 |
| E | 限速用滑动窗口 deque 而非固定 4s sleep | 更精确,突发 busrt 场景下表现更好 |
| F | 路径前缀写 `_PATH_*` 类变量,不硬编码到方法内 | 一个地方改路径,便于后续中转站换路径映射 |
| G | `_fetch_derivative_history` 抽公共函数 | 5 个衍生品端点逻辑相同,去重 |
| H | 空 API key 只 warning 不抛错 | 允许离线测试(看类构造、帮助文档等);实际调用会 401 自然失败 |
| I | `CoinglassCollector` 类名 G 小写(而非 CoinGlass)| 沿用你测试脚本模板里的写法;避免纠结 |
| J | 测试脚本的 PASS 判据放宽为"K 线 1d+4h OK + 任一衍生品 OK" | 某个衍生品端点 404 不应全盘否定;宽松判据便于诊断 |
| K | 不改建模文档 §3.6.1 / §3.6.2 | 实现路由非模型变更;PROJECT_LOG 足够 |

---

## 5. 验证结果(我的沙箱,无真实 API 调用)

```
sources: [coinglass, glassnode, yahoo_finance, fred, event_calendar_source]
binance removed: OK

coinglass config:
  base_url:   https://api.alphanode.work
  header:     x-key
  timeout:    20s
  retry:      {max_attempts: 3, backoff_sec: 8, backoff_strategy: fixed, ...}
  rate_limit: {requests_per_minute: 15, on_exceed: queue}

glassnode header: x-key @ https://api.alphanode.work
CoinglassCollector OK; base_url=https://api.alphanode.work, rpm=15
BinanceCollector removed: OK

ohlc normalization helpers: OK
  - ms int → ISO ✓
  - ISO with Z → ISO ✓
  - ISO with +00:00 → ISO ✓
  - short keys {t,o,h,l,c,v} 和 long keys {time,open,...} 产出一致 ✓
```

**未跑真实 API**(无 key,地域封禁影响有限因为走 alphanode 中转;但沙箱可能出站受限)。等你本地跑 `scripts/test_coinglass_collector.py` 验证。

---

## 6. 用户验证路径

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV

# 确保 .env 里的 COINGLASS_API_KEY 已填(可与 GLASSNODE_API_KEY 相同)
grep -E 'COINGLASS_API_KEY|GLASSNODE_API_KEY' .env

# 执行(约 36-60 秒)
uv run python scripts/test_coinglass_collector.py
```

**预期**(成功路径):

```
[init_db] ...
CoinGlass rate limit reached (15/min), sleeping X.Xs   # 可能出现一次
klines_1h: upserted 500 rows
klines_4h: upserted 500 rows
klines_1d: upserted 500 rows
klines_1w: upserted ~XXX rows
funding_rate: upserted ~500 rows
open_interest: upserted ~500 rows
...

Collect stats:
  klines_1h                 500 rows
  klines_4h                 500 rows
  klines_1d                 500 rows
  klines_1w                 XXX rows
  funding_rate              500 rows
  ...

1d K 线:共 500 根
最新 1d K 线: 2026-04-22T00:00:00Z O=... H=... L=... C=... vol=... BTC

latest funding_rate       : 0.0001 @ 2026-04-22T...
...

VERDICT: PASS ✓
```

**失败路径**:
- 401/403 → COINGLASS_API_KEY 未设或失效
- 400/422 → 某端点 params 不对(回报错误给我)
- 空 data 数组 → 字段名可能不匹配(回报 JSON 示例给我)

---

## 7. Sprint 1.3 工作面(更新)

本轮合并了原计划 Sprint 1.4 的 CoinGlass 工作,所以:

- **Sprint 1.3**:`src/data/collectors/glassnode.py`(链上 collector,直接复用本轮 `api.alphanode.work + x-key` 配置)
- **Sprint 1.4**(原):**取消或用于扩展** —— CoinGlass 额外端点(ETF flows、期权 OI、PCR、基差)
- **Sprint 1.5**:`src/data/collectors/yahoo_finance.py` + `fred.py`(宏观)
- **Sprint 1.6 候选**:`src/common/config.py` 统一 loader + `.env` 自动加载
