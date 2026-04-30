# Sprint 1.5k — BTC 现货价格接入(分钟级现货 + USDT 显示)

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,12 个新测试 + 892/892 全量回归过

---

## 一、根因(用户 SSH + 代码核实)

老顶栏 BTC 价格"实时 · 每分钟更新"是误导文案:

- `/api/market/btc-price` 实际查 `price_candles` 1h 表的 close
- 数据源是 CoinGlass `futures/price/history`(BTCUSDT-Binance,期货 1h 合约)
- 颗粒度只到 **1 小时**,差最多 1 小时;非现货
- 显示符号 `$` 跟数据语义不符(数据是 **USDT 计价**)

用户决策:
1. 数据源切到 CoinGlass `spot/price/history`(现货 1m,延迟 < 1 分钟)
2. 前端轮询 30 秒
3. 显示 `76,293.40 USDT`(数值 + USDT 后缀)
4. 仅改顶栏;策略层 fetch_klines 1h 仍是建模主数据源(不动)

**建模锚点**:§3.2.3 价格类 stale 阈值 = 30 分钟(本 sprint 修订:现货 1m
数据没理由超 2 分钟仍 stale,改 2 分钟阈值;K 线 fallback 路径仍 30 分钟)。

---

## 二、改动

### 任务 A:`CoinglassCollector.fetch_spot_price_history`

`src/data/collectors/coinglass.py`:

- 新增常量 `_PATH_SPOT_PRICE = f"{_PATH_PREFIX}/spot/price/history"`
- 新增方法 `fetch_spot_price_history(symbol, exchange, interval, limit)`,
  复用现有 `_request` / `_unwrap_data` / `_normalize_ohlc_row`
- 与 `fetch_klines` 隔离:策略层(jobs.py / backfill / pipeline)继续用
  `fetch_klines` 1h K 线(不动)

### 任务 B:`/api/market/btc-price` 双路径

`src/api/routes/market.py`:

| 路径 | 数据源 | source 字段 | stale 阈值 |
|---|---|---|---|
| **主**(spot) | `fetch_spot_price_history` 1m | `binance_spot_1m_via_coinglass` | **2 分钟** |
| **fallback**(K 线) | `price_candles` 1h + `_try_refresh_from_coinglass` | `binance_kline_1h_close_via_coinglass` | 30 分钟 |

24h / 7d 变化率始终走 K 线 1h 路径(spot 1m 算 24h 要 1440 根代价高;
变化率精度对小数点后 2 位足够)。两条路径独立计算,不互相阻塞。

新增内部 helper `_try_fetch_spot_1m()`:返回 `(price, captured_at)`,失败
返回 `(None, None)`。常量 `_STALE_THRESHOLD_SPOT_MIN = 2.0` /
`_STALE_THRESHOLD_KLINE_MIN = 30.0`。

`BtcPriceResponse` schema **不变**,只是 `source` 字段多了一种枚举值。

### 任务 C:前端

`web/assets/app.js`:
- `setInterval(60000)` → `setInterval(30000)`(轮询 30 秒)
- `formatPrice(v)`:`'$' + ...` → `... + ' USDT'`(后缀化)
- 新增 `livePriceSourceLabel()`:
  - `source.startsWith('binance_spot')` → "实时(分钟级,Binance 现货)"
  - `source.includes('kline_1h')` → "1h K 线(fallback)"

`web/index.html`:
- "BTC 价格" → "BTC 现价"
- 静态文案 "实时 · 每分钟更新" → `x-text="livePriceSourceLabel()"`
- stale tooltip 改 "现货 > 2 分钟 / K 线 fallback > 30 分钟"

---

## 三、测试

### `tests/test_coinglass_spot_price.py`(6 测试,Task A)

| 测试 | 验证 |
|---|---|
| `test_fetch_spot_price_history_success` | ms epoch → ISO,字符串数值 → float,末行是最新 close |
| `test_fetch_spot_price_hits_correct_endpoint` | 路径含 `spot/price/history`,不误用 `futures` |
| `test_fetch_spot_price_passes_correct_params` | symbol/exchange/interval/limit 透传 |
| `test_fetch_spot_price_returns_empty_on_empty_data` | 空 data → `[]` |
| `test_fetch_spot_price_raises_on_api_error_code` | code != "0" → `CoinglassCollectorError` |
| `test_fetch_spot_price_skips_malformed_row` | 异常行跳过,不让整批失败 |

### `tests/test_market_route_spot_priority.py`(6 测试,Task B)

| 测试 | 验证 |
|---|---|
| `test_spot_success_uses_realtime` | spot 成功:source/price/age < 2 真值断言 |
| `test_spot_stale_threshold_2min` | spot 时间 -3min → `stale=True` |
| **`test_24h_change_uses_kline_even_in_spot_path`** | **关键反退化**:price=99999 来自 spot,h24=+3% 来自 K 线 |
| `test_spot_fail_falls_back_to_kline` | spot 返回 [] → fallback,source=kline_1h |
| `test_spot_exception_falls_back_to_kline` | spot 抛异常 → fallback,endpoint 不崩溃 |
| `test_response_schema_unchanged` | 字段集 8 个不变 |

### 全量回归

```
892 passed, 1 skipped, 7.28s
```

(880 baseline + 6 spot + 6 market = 892)

---

## 四、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/collectors/coinglass.py` | 新增 `_PATH_SPOT_PRICE` + `fetch_spot_price_history` |
| `src/api/routes/market.py` | 双路径(spot 主 / K 线 fallback)+ stale 阈值常量 + `_try_fetch_spot_1m` helper |
| `tests/test_coinglass_spot_price.py` | **新文件** 6 测试 |
| `tests/test_market_route_spot_priority.py` | **新文件** 6 测试 |
| `web/assets/app.js` | 轮询 30s + USDT 后缀 + `livePriceSourceLabel()` |
| `web/index.html` | "BTC 现价" + 动态 source label + stale tooltip |

---

## 五、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

**本 sprint 无替代关系,无删除项。** 理由:纯新增 spot 路径 + 改前端文案/
符号,fallback 旧路径(_query_latest_1h / _try_refresh_from_coinglass /
fetch_klines)必须保留用于现货失败时降级。

git grep 自检:
- ✅ `_query_latest_1h` 仍存在(market.py:74),spot 路径 24h 计算 + fallback 都用
- ✅ `_try_refresh_from_coinglass` 仍存在(market.py:84),fallback 路径用
- ✅ `fetch_klines` 仍是策略层主数据源(jobs.py + backfill_data.py + market.py
  fallback 都在调)

### §Y
3 个代码 commit + 1 个 docs commit,一次性 push 到 GitHub。

### §Z(测试用真数值断言)
- spot price 数值断言 `== 76300.50`
- spot timestamp 断言 `== "2025-04-30T05:35:00Z"`(ms epoch → ISO 转换正确)
- 关键反退化:price=99999 spot 同时 h24=+3% K 线,**两源独立**
- spot stale -3min → `age_minutes >= 2.0` AND `stale=True`
- 全部 6 个 spot 测试 + 6 个 market 测试都用真数值,没有 `.called=True` only

### 同类风险扫描
- **CoinGlass 配额**:30s 轮询 = 120 次/小时,远低于配额(分钟级现货端点
  通常无独立 quota)。生产单用户场景无压力,不加缓存
- **WebSocket 实时推送**(币安 ws ticker):本 sprint 不启用,留 1.5k.1
- **24h 颗粒度**:仍 1h 颗粒度。如要分钟级 24h 变化,需另起 sprint 拉
  1440 根 1m 数据
- **COINGLASS_API_KEY 在 source 字段不显式暴露**(已用机器名 reified):
  无敏感泄露

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 892 passed, 1 skipped, 7.28s |
| GitHub push(commit hashes:`ed28641..ea7b51d` + report) | ✅ 一次性 push |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 本 sprint 无 schema/数据改动 |

### SSH 验证脚本(用户执行)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5
sudo systemctl is-active btc-strategy.service

# 1. /api/market/btc-price 真用现货 1m
curl -s -u admin:Y_RhcxeApFa0H- http://localhost/api/market/btc-price \
  | python3 -m json.tool
# 预期:source="binance_spot_1m_via_coinglass", age_minutes < 2,
#       captured_at_bjt 是当下分钟级 BJT 时间

# 2. 24h 变化率仍来自 K 线
# (响应里 price_24h_change_pct 不为 null,即 spot 和 K 线两源都活)
SSH
```

### 网页验证(用户浏览器打开 http://124.222.89.86)
- 顶栏:`76,xxx.xx USDT`(数值跟币安官网现货差 < $1)
- 文案:"BTC 现价 · 实时(分钟级,Binance 现货)"
- "采集 YYYY-MM-DD HH:MM (BJT)" 是当下分钟级
- 30 秒一次刷新,无 stale 标灯

### Fallback 验证(可选)
临时把 .env 里 `COINGLASS_API_KEY` 改错 → curl 同样端点 → source 应回退到
`binance_kline_1h_close_via_coinglass`(验完恢复 .env)。

---

## 七、未覆盖 / 留 v0.6

- **WebSocket 实时推送**(Binance ws ticker):前端仍 polling,留 1.5k.1
- **分钟级 24h 变化率**:需拉 1440 根 1m,代价高,目前用 1h 颗粒度
- **多用户配额压力**:单用户无压力,如未来公开访问需加 30s cache 兜底
- **历史价格存档**:spot 1m 数据不入库,只为顶栏即时显示。如要历史回放
  需另起 sprint 加 spot_price_candles 表
