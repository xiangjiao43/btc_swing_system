# Sprint 1.2 — `src/data/collectors/binance.py`

**日期**:2026-04-23
**Sprint**:1.2(Binance 数据采集器)
**对应建模文档章节**:§3.6.1 Binance 数据源、§3.2 M29 reference_timestamp、§10.4.2 data/ 模块职责

---

## ⚠️ Triggers for Human Attention

> 以下是本次任务需要人类注意的决策点,可直接摘录给审阅者。

### 1. 🐛 我修了一个自己刚写下的重试 bug

初版代码对"非重试 HTTP 错"(如 400 / 451)也会进入 3 次重试循环,因为 `retry_on_status` 里的和非重试的都共用了 `BinanceCollectorError`,被同一个 except 捕获。

**修复**:引入内部异常类 `_RetryableHTTPError`,只它会被 except 捕获走重试;`BinanceCollectorError`(非重试)直接穿出循环。

**验证结果**:我的沙箱访问 Binance 时拿到 `HTTP 451`(地域限制),修复前会重试 3 次才失败,修复后一次失败。

**影响建议**:Sprint 1.3 起,其他 collector(glassnode/coinglass/yahoo 等)要复用相同的重试模式。可以把 `_request` 抽到基类 `_BaseCollector`(下一 Sprint 再做)。

### 2. 🌍 我的沙箱被 Binance 地域封禁,只能做"离线验证"

Bash 工具所在环境从官方 API 拉数据返回 `HTTP 451` —— Binance 对 restricted location 的封禁。这意味着:
- **我无法在沙箱里跑通 end-to-end 真实抓取**
- 已验证:配置解析 / 类构造 / URL 正确性 / 错误处理路径
- **未验证**:实际 JSON 解析 / 字段映射 / DAO 写入一致性 —— **需要你在本地(有 VPN)跑一次 `scripts/test_binance_collector.py`**

如果你本地跑的时候出现字段 KeyError / 类型转换错误,说明 Binance 接口返回格式与我代码的假设不匹配。**先报我具体的错误信息,我按你的实际响应修代码**,比我盲猜字段名更可靠。

### 3. `fetch_basis` **不是真正的"年化基差"**

建模 §3.7.2 的 `basis_annualized` 指**季度合约价 vs 永续合约价**的年化偏离,需要季度合约符号(例如 `BTCUSDT_240927`)。我当前实现用 `/fapi/v1/premiumIndex` 的**瞬时 premium**(永续 markPrice vs index price):

```
basis_premium_pct = (markPrice - indexPrice) / indexPrice
```

- 数量级差 1-2 个数量级(真实年化基差通常 5-20%,瞬时 premium 通常 0.01-0.5%)
- 方向一致性大致可用(牛市正、熊市负)
- **编码期需要评估是否足以替代** `basis_annualized` 因子

**TODO for Sprint 1.3+**:写一个 `fetch_quarterly_contract_basis()` 方法,先查 `/fapi/v1/exchangeInfo` 找到当前季度合约符号,再 GET 其 markPrice 和永续 markPrice 做差算年化。本 Sprint 未做。

### 4. 没有实现建模 §3.6.1 中的"永续 K 线"和"24h 成交统计"/"订单簿深度"

**已实现**:
- 现货 K 线 1h/4h/1d/1w × 500 条
- 资金费率历史(500 条)
- 未平仓当前 + 历史(500 条 daily)
- 多空比历史(500 条 daily)
- 瞬时 basis premium + mark price + index price

**未实现**(建模 §3.6.1 列出但本 Sprint 未覆盖):
- 永续 K 线(`/fapi/v1/klines`)—— L4 交叉验证用
- 24h ticker(`/api/v3/ticker/24hr`)
- 订单簿深度(`/api/v3/depth?limit=100`)—— liquidation_density_index 用
- BTC 历史 ATH(从 1d K 线计算,indicators 层做)

理由:本 Sprint scope 按你的任务定义来,未扩散。Sprint 1.3 或 1.4 可补。

### 5. `scripts/test_binance_collector.py` 与你样例代码有一处方法名偏差

你在任务描述里写的是:
```python
deriv_latest = DerivativesDAO.get_latest_snapshot(conn, metric_name='funding_rate')
```
但 Sprint 1.1 的 `DerivativesDAO` 方法叫 `get_latest`(不是 `get_latest_snapshot`)。我在验证脚本里用了**实际存在的** `get_latest`。

**判断**:你的样例是伪代码,目的是演示验证流程;方法名微调无语义影响。如果你希望改方法名,我下个 Sprint 在 DAO 里加别名 `get_latest_snapshot`(保留 `get_latest`)。

### 6. 没有自动加载 `.env`

用户没有 `python-dotenv` 依赖,`uv run` 也不会自动 source `.env`。`load_source_config()` 只读 `os.environ`。后果:用户在 `.env` 里设置的 `BINANCE_BASE_URL=...` **不会生效**。

**对 Sprint 1.2 的实际影响**:几乎没有,因为 Binance 默认用官方域名(api.binance.com / fapi.binance.com),`.env` 覆盖是中转站场景才需要。

**修复路径**:Sprint 1.2a(尚未启动的 config loader)加 `dotenv.load_dotenv()`;或者在测试脚本顶部用 `subprocess.check_output(["source", ".env"])` 等价物。

### 7. HTTP 451 (Unavailable For Legal Reasons) 是**非重试**(我分类对)

`retry_on_status: [408, 418, 429, 500, 502, 503, 504]` 没有 451。451 是"永久禁止"(地域封禁),重试无意义。分类正确。

**对用户的意义**:如果你未来切 VPS 部署(服务器 IP 可能在 restricted list),collector 会立即失败不会卡重试。此时需要切中转站(走 `BINANCE_BASE_URL` env override)。

---

## 1. 产出概览

| 文件 | 行数 | 作用 |
|---|---|---|
| `src/data/collectors/_config_loader.py` | 116 | data_sources.yaml 读取 + env 覆盖解析 |
| `src/data/collectors/binance.py` | 542 | BinanceCollector 类 + 7 fetch_* 方法 + collect_and_save_all |
| `src/data/collectors/__init__.py` | 12 | 暴露 BinanceCollector / BinanceCollectorError |
| `scripts/test_binance_collector.py` | 100 | 人工验证脚本(从项目任意位置可运行) |
| **小计** | 770 | |

同时删除 `scripts/.gitkeep`(已有真实脚本)。

---

## 2. BinanceCollector API 一览

| 方法 | 端点 | 对应建模 |
|---|---|---|
| `fetch_klines(symbol, interval, limit, start_time, end_time)` | `GET /api/v3/klines` (spot) | §3.6.1 K 线 4 档 |
| `fetch_funding_rate(symbol, limit)` | `GET /fapi/v1/fundingRate` | §3.6.2 资金费率 |
| `fetch_open_interest(symbol)` | `GET /fapi/v1/openInterest` | §3.6.2 OI 当前 |
| `fetch_open_interest_hist(symbol, period, limit)` | `GET /futures/data/openInterestHist` | §3.6.2 OI 历史 |
| `fetch_long_short_ratio(symbol, period, limit)` | `GET /futures/data/globalLongShortAccountRatio` | §3.6.2 多空比 |
| `fetch_basis(symbol)` | `GET /fapi/v1/premiumIndex` | §3.7.2 basis(瞬时 premium,非年化) |
| `collect_and_save_all(conn, symbol)` | 以上全部组合 | §3.2 一次性采集契约 |

### `collect_and_save_all` 数据量预估(正常跑通时)

| Label | 预期行数 |
|---|---|
| binance_klines_1h | 500 |
| binance_klines_4h | 500 |
| binance_klines_1d | 500 |
| binance_klines_1w | 500(可能 < 500,BTC 只交易约 15 年) |
| funding_rate_history | 500 |
| open_interest_current | 1 |
| open_interest_hist_daily | 1000(500 条 × 2 字段) |
| long_short_ratio_daily | 500 |
| basis_premium_current | 3(premium_pct + mark_price + index_price) |
| **总计** | ~3500 + |

---

## 3. 重试 / 节流 设计

### 重试策略(读自 data_sources.yaml)

```
max_attempts: 3
backoff_sec: 2
backoff_strategy: exponential  →  首次 2s,二次 4s
retry_on_status: [408, 418, 429, 500, 502, 503, 504]
```

### 异常分类

| 类型 | 动作 |
|---|---|
| 网络错误 `requests.RequestException` | 重试 |
| HTTP status ∈ retry_on_status | 重试(`_RetryableHTTPError`) |
| HTTP status 非 OK 且不在列表 | **立即失败**(`BinanceCollectorError` 不被 except 捕获) |
| JSON 解析失败 `ValueError` | 重试 |
| 字段缺失(单条数据)| `logger.warning` + 跳过该条,不中断批次 |

### 节流

- 每次请求间最小间隔 `0.1s`(单调时钟);IP 限流宽松,这个保守值够用
- 任务要求里说"每次请求后 `time.sleep(0.1)` 即可";我的实现做了更聪明的:只在距上次请求 < 0.1s 时 sleep,不浪费时间

### 错误不静默

- 每个 `collect_and_save_all` 里的子任务用 `try/except Exception`,失败记 `logger.error` 并累积到 `failures` 列表
- **全部失败**(`len(failures) == len(stats)`)才抛 `BinanceCollectorError`
- 部分失败返回统计字典,让调用方决定如何处理(典型做法:把未 stale 的源结果写库,stale 源记 degraded)

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | `_config_loader.py` 放在 collectors/ 目录下,名字带下划线 | 明确为"collectors 专用辅助",将来被 src/common/config.py 替换 |
| B | env var 不存在时回退到 base_url_default | 不强制用户配 `.env`;本地直连 Binance 官方可裸用 |
| C | 不加载 `.env` 文件 | python-dotenv 未在依赖;统一 config loader 做 |
| D | 引入 `_RetryableHTTPError` 分类 | 避免非重试 HTTP 被误重试 |
| E | 节流用单调时钟而非固定 sleep(0.1) | 省时间,正确性不变 |
| F | `fetch_basis` 用 premiumIndex 瞬时 premium | 任务允许;真正年化基差留到 Sprint 1.3+ |
| G | `collect_and_save_all` 部分失败不抛,全部失败才抛 | 允许降级写入,契合 M29 freshness 纪律 |
| H | Row dataclass 的 `fetched_at` 用当前 UTC | 对应 M29 data_captured_at 语义 |
| I | 测试脚本加 sys.path.insert 支持项目任意位置运行 | 避免用户手动设 PYTHONPATH |
| J | Row 批量的 `timeframe` 字段强制传 `interval` 字符串 | KlineRow 声明用 `TimeFrame` Literal,类型安全 |
| K | 单个端点的字段缺失只 warning 不中断 | 建模"不因单条坏数据中断整批" |
| L | `DerivativesDAO.get_latest(metric_name=...)` 代替你样例的 `get_latest_snapshot` | 用实际存在的方法名,语义等价 |

---

## 5. 用户验证路径

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV
uv run python scripts/test_binance_collector.py
```

**预期输出**(带 VPN 直连 Binance 时):

```
[init_db] db_path = .../data/btc_strategy.db
[init_db] tables (10): ...
[init_db] user indices: 22

… (INFO logs for each endpoint upsert)

============================================================
Collect stats:
  binance_klines_1h                  500 rows
  binance_klines_4h                  500 rows
  binance_klines_1d                  500 rows
  binance_klines_1w              ~XX rows
  funding_rate_history              500 rows
  open_interest_current               1 rows
  open_interest_hist_daily         1000 rows
  long_short_ratio_daily            500 rows
  basis_premium_current               3 rows
============================================================

1d K 线:共 500 根;最新一根:
  2026-04-XXT00:00:00Z  O=XXXXX  H=XXXXX  L=XXXXX  C=XXXXX  vol=XXXXX BTC

Latest funding_rate: 0.0001 @ 2026-04-XXT00:00:00Z
Latest basis_premium_pct: 0.000XXX @ 2026-04-XXT10:XX:XXZ
Latest open_interest_btc: XXXXX.XX @ 2026-04-XXT10:XX:XXZ
```

**如果遇到 HTTP 451 或其他错误**,请把完整错误贴给我,我按实际响应修代码。

---

## 6. 下一步 Sprint 1.3 候选

- **1.3a**(推荐)`src/common/config.py` — 统一 config loader(含 `.env` 自动加载 / 多 YAML 合并 / 类型校验)
- **1.3b** `src/data/collectors/glassnode.py` — 链上 collector(走 alphanode 中转)
- **1.3c** `src/data/collectors/coinglass.py` — 衍生品聚合 collector(走 alphanode 中转)
- **1.3d** `src/data/collectors/yahoo_finance.py` + `fred.py` — 宏观 collector

建议按 a → b → c → d 顺序,因为后几个都依赖统一 config loader。另外 b 和 c 共用同一中转站(alphanode),可以抽出中转站认证共用代码。

---
