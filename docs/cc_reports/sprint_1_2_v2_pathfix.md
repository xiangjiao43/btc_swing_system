# Sprint 1.2 v2 pathfix — 路径改为 `/open-api-v4.coinglass.com/api/*` + 字符串数字处理

**日期**:2026-04-23
**依据**:用户手工 curl 验证 alphanode 中转站真实路径与响应结构

---

## ⚠️ Triggers for Human Attention

### 1. 🔑 路径前缀从 `/v4/api/` 改成 `/open-api-v4.coinglass.com/api/`

alphanode 中转站**不做 `/v4/api/*` 自动映射**,必须用 CoinGlass 开放 API 的完整路径作为 path 前缀。所有 6 个端点路径常量统一改写,用一个 `_PATH_PREFIX = "/open-api-v4.coinglass.com/api"` 基底拼接。

```
/v4/api/futures/price/history        ❌ 404
/open-api-v4.coinglass.com/api/futures/price/history  ✓
```

### 2. 响应 envelope 改为 `{"code": "0", "data": [...]}`,无 `msg`

- **成功判据**:`str(code) == "0"` 且 `"data" in body`(code 可能是字符串 `"0"` 或整数 `0`,都接受)
- **失败时**:若 `code != "0"`,`_unwrap_data` 直接抛 `CoinglassCollectorError`,携带 code 值(即便响应无 `msg` 字段也能看到错误码)
- **null data**:`{"code": "0", "data": null}` → 返回 `[]`(不是错误,只是没数据)

### 3. 数值全部字符串!统一走 `safe_float`

CoinGlass 响应里的 `open / high / low / close / volume_usd / fundingRate / ...` **全是字符串**(如 `"78139.7"`)。

- 新增 `safe_float(v)` 辅助函数(在 `_field_extractors.py`),处理 `None / "" / 非数字字符串` 返回 `None`,其他走 `float()`
- `extract_value(row, keys)` 内部改用 `safe_float`,原有调用方无需改动
- `_normalize_ohlc_row` 每个字段都用 `safe_float`,避免 `float("")` 等异常

### 4. 成交量字段是 `volume_usd`(USDT 计价),**不是** `volume` / `v`

`_normalize_ohlc_row` 产出两个字段:
- `volume_usd`:来自响应 `volume_usd` 字段,**优先**;兜底 `volume_usdt` / `quoteAssetVolume` / `volume` / `v` / `vol`
- `volume_btc`:**计算得出** = `volume_usd / close`(close > 0 时),否则 0.0

**重要**:`volume_btc` 是**估算值**,不是真实 BTC 成交量。CoinGlass 不直接提供 BTC 计价的成交量。对大多数下游消费(ADX/ATR 不用 volume;VWAP 是 close-weighted 本来就近似)够用。如果 Sprint 1.3+ 有因子(如 OBV / Volume Delta)需要**精确** BTC 成交量,应该:
- 额外调用 CoinGlass spot-volume 端点(如果有)
- 或在 `data_catalog.yaml` 给这类因子加 `accuracy_note: estimate` 标记

### 5. 兼容性保留了旧字段变体

`_normalize_ohlc_row` 的字段优先级:
```
open:   open → o
close:  close → c → value
volume_usd:  volume_usd → volume_usdt → quoteAssetVolume → volume → v → vol
```

即便未来某个端点变回用 `volume` / `v` 字段,也能兜住。优先级保证**CoinGlass 真实字段名总是第一选择**,旧变体作 fallback。

### 6. 测试脚本没改,但判据现在更可能通过

因为:
- 路径对了 → 请求不会 404
- envelope 检查对了 → 响应能解析
- 字符串数字处理对了 → OHLC 行不会因 `float("...")` 失败
- volume_usd 识别对了 → K 线不会漏掉 volume_usdt 列

预期本地跑通后:
- `stats['klines_1h'] = 500`(或其他四档)
- `stats['funding_rate'] ≥ 50`
- `volume_usdt` 列会填真实值;`volume_btc` 列填估算值

### 7. 字段清单 `FUNDING_RATE_VALUE_KEYS` 首选 `close` 仍然对

因为 funding-rate/history 响应是 OHLC 形状(用 close 代表该时段末费率),清单顺序是对的。只是**close 值现在是字符串**,safe_float 会处理。

---

## 1. 变更清单

| 文件 | 变更 |
|---|---|
| `src/data/collectors/_field_extractors.py` | 新增 `safe_float`;`extract_value` 改用 `safe_float` |
| `src/data/collectors/coinglass.py` | **6 个 `_PATH_*` 常量**改成新前缀;`_unwrap_data` 加 `code=="0"` 检查;`_normalize_ohlc_row` 改用 `safe_float` 并产出 `volume_usd` + `volume_btc`;`collect_and_save_all` 把 `volume_usd` 映射到 `volume_usdt` 列 |

**未改动**:
- 字段优先级清单(`FUNDING_RATE_VALUE_KEYS` 等)内容不变
- `scripts/test_coinglass_collector.py`(按用户指示)
- `config/data_sources.yaml` / `.env.example`
- 存储层 DAO

---

## 2. 关键验证点(本地已跑通)

```python
# 真实响应形态,字符串数值
row = {
    'time': 1776902400000,
    'open': '78139.7', 'high': '78534.9', 'low': '77410.7',
    'close': '77941.1', 'volume_usd': '2641079736.2696',
}
n = _normalize_ohlc_row(row)
# → timestamp: 2026-04-23T00:00:00Z
# → open: 78139.7, close: 77941.1
# → volume_usd: 2641079736.27
# → volume_btc: 33885.58  (估算,volume_usd / close)

# Envelope 失败
body = {'code': '50001', 'msg': 'invalid key'}
# → CoinglassCollectorError("code='50001': invalid key")

# Envelope 成功 (code 字符串)
body = {'code': '0', 'data': [...]}
# → 返回 data

# Envelope 成功 (code 整数,legacy 兼容)
body = {'code': 0, 'data': []}
# → 返回 []

# null data
body = {'code': '0', 'data': null}
# → 返回 []
```

全部通过。

---

## 3. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 用 `_PATH_PREFIX` 常量 + f-string 拼接 6 个 _PATH_* | 未来换前缀只改一行;Python 类体允许 f-string 引用前面定义的类属性 |
| B | `_unwrap_data` 同时接受字符串 `"0"` 和整数 `0` | 不同 API 版本返回类型可能变;`str(code) == "0"` 是跨类型最稳 |
| C | `data: null` 返回 `[]` 而非报错 | 空数据不是错误(端点正常响应但该时段无数据);下游按空列表处理即可 |
| D | `safe_float` 放在 `_field_extractors.py` 而不是 coinglass.py | 未来其他 collector(glassnode/yahoo)也会用;共享模块 |
| E | `safe_float` 对 `""` 返回 None | 空字符串在 Python 里 `float("")` 会抛,明确处理 |
| F | `volume_btc = volume_usd / close` 估算 | CoinGlass 不给 BTC 成交量;估算值对 ADX/ATR 等不用 volume 的因子 0 影响;VWAP 级别估算够用 |
| G | 字段优先级保留 `volume / v / vol` 兜底 | 未来端点变化时兜住;首选仍是 `volume_usd` |
| H | `_normalize_ohlc_row` 的 `pick` 辅助也过滤 `""` | 防御字符串空值 |
| I | `_unwrap_data` 错误信息带 code 值不带变量名 | 用户看 code 查 CoinGlass 文档即可;msg 字段截断到 200 字符避免日志爆炸 |

---

## 4. 用户验证路径

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV

# 确认 .env 里的 COINGLASS_API_KEY 已填
grep COINGLASS_API_KEY .env

# 跑(约 36-60 秒)
uv run python scripts/test_coinglass_collector.py 2>&1 | tee logs_coinglass_pathfix.txt
```

**预期**:
- 每个端点请求日志显示 `GET https://api.alphanode.work/open-api-v4.coinglass.com/api/futures/.../history params=...`
- 响应 `first-row keys=[...]` 含 `time` / `open` / `close` / `volume_usd` / ...
- VERDICT: PASS ✓

**若某端点仍报错**:
- 401 → `COINGLASS_API_KEY` 未设或无效
- 400/422 → params 需要微调(用户指示的 Part 7 "这次先不动",若失败再调)
- 超 15s 无响应 → 中转站本身慢;不动我代码

---

## 5. 当前 commit 历史

```
cc7018e Sprint 1.2 v2 fix: align CoinGlass field names with legacy system
bca9130 Sprint 1.2 redo: drop Binance, unify to CoinGlass for klines and derivatives
77e78b6 Sprint 1.2 fix: split Binance klines and CoinGlass derivatives based on legacy architecture
e99bd6b Sprint 1.2: Binance collector with klines and derivatives
550802c Sprint 1.1: data/storage/ with SQLite schema and DAOs
```

本次 commit 将是 `Sprint 1.2 v2 path fix`,定位在 `cc7018e` 之后。

---

## 6. Sprint 1.2 v2 完整修复路径回顾

| 迭代 | 关键发现 | 修复 |
|---|---|---|
| Sprint 1.2 | Binance 官方 API 被美国 IP 封(451)| 已废弃 |
| Sprint 1.2 fix | 改成 data.binance.vision | 不可用,静态仓库不是 REST |
| Sprint 1.2 v2 | 放弃 Binance,统一到 CoinGlass(/v4/api/*)| **路径错** |
| Sprint 1.2 v2 fieldfix | 字段名清单按旧系统对齐 | 字段对了但**路径还是错** |
| **Sprint 1.2 v2 pathfix**(本次)| 路径改成 /open-api-v4.coinglass.com/api/*;响应 envelope 是 `{code, data}`;数值是字符串 | 👈 |

**若本次仍失败**,可能原因:
1. **某端点 params 要微调**(用户 Part 7 已留出预期)— 给我日志我调
2. **响应字段名小变体**(如某端点返回 `funding_rate` 字段不在我优先级清单里)— 给我 `first-row keys` 日志我补清单
3. **中转站限速策略**(15 req/min 可能超)— 可能要再降

---

## 7. 下一步 Sprint 1.3 工作面(本次通过后)

- 1.3:`src/data/collectors/glassnode.py` —— 复用 `api.alphanode.work + x-key`;路径前缀可能是 `/open-api.glassnode.com/v1/...`(待用户旧系统确认)
- 并行:`src/common/config.py` 统一 loader + `.env` 自动加载(可选)
