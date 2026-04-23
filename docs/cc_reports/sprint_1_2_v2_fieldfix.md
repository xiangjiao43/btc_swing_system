# Sprint 1.2 v2 fieldfix — 按旧系统 utils_common.py 对齐字段名契约

**日期**:2026-04-23
**依据**:用户从旧系统 `utils_common.py` 提取的权威字段名清单 + param 契约

---

## ⚠️ Triggers for Human Attention

### 1. `_field_extractors.py` 是"**易变常量的单一真相**",下次 CoinGlass API 改动改这里就行

新建的 `_field_extractors.py` 里 8 组优先级字段清单全部来自你旧系统验证。**顺序反映实际出现频率**,不要手动改序。若本地跑遇到未覆盖的字段名(日志里会出现 `Skipping ... row without numeric value ... keys=[...]`),把那行的 key 追加到对应列表末尾即可 —— 保持旧优先级不变。

### 2. `liquidation` 端点 param 变体 4 组 + metric 拆 3 份

- **Params 变体**:按旧系统兜底顺序尝试 `{symbol+exchange}` → `{pair+exchange}` → `{symbol}` → `{pair}`,第一个非 400 就用。`_try_request_variants` 封装实现,返回 `(body, used_params)`,日志里会打印"used params=..."便于 debug
- **每个 timestamp 产生 3 行入库**:`liquidation_long` / `liquidation_short` / `liquidation_total`
  - 这让 `stats['liquidation']` 的数字约等于 `行数 × 3`(比端点返回行数大)
  - 单边 None 时,另一边按 0 进入 total(和旧系统一致)
  - 两边都 None 才跳过整行

### 3. `long_short_ratio` 有**双路径兜底**

主路径:10 个 ratio 字段名优先级列表(含旧 API 的拼写错误 `longShortRadio`)
备用路径:用 `long_pct / short_pct`(5 + 5 个字段名)计算 → 仅当 short_pct > 0 时生效

**预期行为**:响应正常时走主路径;旧系统遇到过只返回百分比不返回比值的端点形态时才走备用路径。日志里若看到较多 row 的 keys 列表同时缺 ratio 和 pct 字段,可能是新的响应变体。

### 4. `funding_rate` / `open_interest` 用 OHLC normalizer,取 `close` 作为值

按你提供的契约:两个端点的响应是 **OHLC 形状**(不是单值行)。实现上分两层:
- 先用 `_normalize_ohlc_row` 统一成 {open, high, low, close, volume}
- 然后 `extract_value(row, FUNDING_RATE_VALUE_KEYS)`,首选是 `close` / `c`,兜底 `fundingRate` / `rate` / `value`

这样双保险:即便某天端点返回单值行而非 OHLC,`extract_value` 的兜底也能接住。

### 5. `net_position` 拆 `net_position_long` + `net_position_short` 两个 metric

字段清单显示旧系统字段名里含 `change`(`net_long_change`、`netLongChange`),即这是**净持仓变化量**,不是净持仓绝对值。入库时 metric_name 按你契约用 `net_position_long` / `net_position_short`(不带 `_change` 后缀),下游消费按 metric_name 识别即可。

如果 Sprint 1.3+ 有因子需要"绝对净持仓",要加新 metric `net_position_long_absolute` 等新字段,届时再扩。

### 6. 所有 fetch 方法统一打印了 URL + params + row count + 首行 keys

每次 API 调用的 INFO 日志:

```
CoinGlass GET https://api.alphanode.work/v4/api/futures/price/history params={'symbol': 'BTCUSDT', 'exchange': 'Binance', 'interval': '1d', 'limit': 500}
  klines[1d]: 500 rows; first-row keys=['t', 'open', 'high', 'low', 'close', 'volume']
```

这样本地跑时你可以直接看日志发现:
- 请求没发出 → 网络/限速问题
- 请求发了但 rows=0 → 响应 envelope 可能变了
- rows > 0 但"Skipping ... no numeric value" → 字段名需补

### 7. 测试脚本的 PASS 判据**加严**了

旧版只要"K 线 1d+4h OK + 任一衍生品 OK"即可 PASS。新版要求:
- **K 线 4 档各 ≥ 100**(1h/4h/1d/1w)
- **核心衍生品各 ≥ 50**(funding_rate / open_interest / long_short_ratio)
- **liquidation 至少一个方向 ≥ 1**(long 或 short)
- **net_position 不强制**(只报告)

如果某个核心 metric 小于阈值但非 0,说明字段解析丢了一部分;如果是 0,端点本身可能挂了或 params 变体都失败。

### 8. `liquidation` stats 统计值可能让人困惑

`stats['liquidation']` 显示的是 **upsert 的行数**(liquidation_long + liquidation_short + liquidation_total 合计),而非端点返回的原始行数。测试脚本额外单独统计 `liquidation_long` / `liquidation_short` 的 DAO 行数,便于清晰判断。

---

## 1. 变更清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `src/data/collectors/_field_extractors.py` | **新建** | 8 组优先级字段清单 + `extract_value` / `extract_raw` 辅助 |
| `src/data/collectors/coinglass.py` | **重写** | 每个 fetch 方法按契约实现;新增 `_try_request_variants` / `_log_response_shape`;Params 按"首选项"构造 |
| `scripts/test_coinglass_collector.py` | **重写** | 加严 PASS 判据;打印每类数据最新 3 条样本 |

**未改动**:`_config_loader.py` / `data_sources.yaml` / `.env.example` / 存储层(字段名契约变动不影响数据库 schema,因为 DAO 是 metric_name 长表结构)。

---

## 2. 各端点契约对齐结果

| 端点 | Params(对齐后) | 字段清单(priority) | 产出 metric |
|---|---|---|---|
| `/v4/api/futures/price/history` | `symbol=BTCUSDT, exchange=Binance, interval, limit` | OHLC(`open/o` 等) | K 线(DAO: btc_klines) |
| `/v4/api/futures/funding-rate/history` | `symbol=BTCUSDT, exchange=Binance, interval, limit` | `FUNDING_RATE_VALUE_KEYS`(close 优先) | funding_rate |
| `/v4/api/futures/open-interest/aggregated-history` | `symbol=BTC, interval, limit`(**无 exchange**) | `OPEN_INTEREST_VALUE_KEYS`(close 优先) | open_interest |
| `/v4/api/futures/global-long-short-account-ratio/history` | `symbol=BTCUSDT, exchange=Binance, interval, limit` | `LONG_SHORT_RATIO_VALUE_KEYS` +(pct 兜底)| long_short_ratio |
| `/v4/api/futures/liquidation/history` | **4 组变体**(symbol/pair × with/without exchange) | `LIQUIDATION_LONG_KEYS` / `..._SHORT_KEYS` | liquidation_long / _short / _total |
| `/v4/api/futures/net-position/history` | `symbol=BTCUSDT, exchange=Binance, interval, limit` | `NET_POSITION_LONG_KEYS` / `..._SHORT_KEYS` | net_position_long / _short |

---

## 3. 关键实现要点

### 3.1 `_try_request_variants(path, variants)`

```python
for i, params in enumerate(variants):
    try:
        body = self._request("GET", path, params=params)
        return body, params    # 成功立即返回
    except CoinglassCollectorError as e:  # 非重试 4xx
        continue
raise last_exc  # 全部用尽
```

每个 variant **仍走完整的重试链**(5xx / 网络错重试 3 次 × 8s 固定);只有 4xx 非重试错才移到下一个 variant。这保证"临时网络抖动"不会跳到下一个 variant,只有"这组参数服务器明确拒绝"才换。

### 3.2 Priority field lists 设计原则

每个清单**顺序反映旧系统遇到的变体频率**,首项是最常见的。`extract_value` 循环到第一个非 None 且可转 float 的就返回,保证**稳定行为**:同一数据在同一响应形态下始终映射到同一个字段。

### 3.3 响应 envelope 兜底

`_unwrap_data` 处理 4 种响应形态:
- `list` → 直接返回
- `{data: list}` → 返回 data
- `{data: {list: ...}}` → 返回 data.list
- `{data: {}}` → 单对象包装成 list
- `{list: ...}` → 返回 list

### 3.4 Debug 日志三层

- **请求前**:URL + params(INFO)
- **响应后**:label + row count + first row keys(INFO)
- **行解析失败**:metric_name + timestamp + 尝试的 key 清单 + 实际 keys 前 10(WARNING)

任何 CoinGlass 问题都能从日志直接定位。

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 单独文件 `_field_extractors.py` 而非嵌在 coinglass.py 顶部 | 清单可能随 API 变动增长;单独文件便于 diff 审计 |
| B | `liquidation` 合并为一个 `fetch_liquidation_history`,内部产出 3 metric | 单 API 调用产 3 个 metric,合并更紧凑;变体尝试逻辑只需写一次 |
| C | `_try_request_variants` 提升为方法 | 将来其他端点若也遇 400-variants 可复用 |
| D | `net_position` 不计算 `total`(不像 liquidation) | long/short 净持仓变化的"总和"语义不明;两个分开更清晰 |
| E | funding_rate / OI 即使是 OHLC 响应也用 `_normalize_ohlc_row` + `extract_value` 双保险 | 日后若端点形态变了(不再 OHLC),兜底仍能跑通 |
| F | 测试脚本的采样函数 `_print_samples` 区分 OHLC 与 单值行 | 两种 row 结构显示字段不同,统一函数显示逻辑 |
| G | PASS 判据用分项检查,逐条 ✓ / ✗ 打印 | 失败时能一眼看出哪项未达标 |
| H | `FUNDING_RATE_VALUE_KEYS` 首项改成 `close` / `c` | 响应是 OHLC 结构;close 一定存在,其他兜底字段只是防御 |
| I | 保留字段清单里旧 API 的 typo `longShortRadio` | 旧系统真遇到过这种拼错;删掉会让某些响应失败 |
| J | 日志 URL 日志在 `_request` 内部,不是每个 fetch 重复 | 单一位置,减少重复 |

---

## 5. 验证结果(我的沙箱,无真实 API 调用)

```
field_extractors: OK
  - basic extract_value ✓
  - typo variant 'longShortRadio' accepted ✓
  - pct fallback path ✓
  - LIQUIDATION_LONG_KEYS / NET_POSITION_LONG_KEYS ✓

CoinglassCollector: base_url=https://api.alphanode.work, rpm=15
normalization helpers: OK
all 9 methods present: OK

=== SMOKE TEST PASS ===
```

**未跑真实 API**(本地沙箱无 COINGLASS_API_KEY)。

---

## 6. 用户验证路径

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV
uv run python scripts/test_coinglass_collector.py 2>&1 | tee logs_coinglass_test.txt
```

**观察要点**:
1. 日志里每次请求的 `CoinGlass GET ... params=...` 行是否与契约一致
2. 每个端点的 `first-row keys=[...]` 是否含我们优先级清单里的字段
3. 如果有 `Skipping ... no numeric value` warning,是字段名漂移了
4. 最终 VERDICT 是 PASS ✓ 还是 FAIL ✗

**常见失败场景**:
- liquidation 四个 variants 全 400 → 中转站可能改了路径;回报给我
- long_short_ratio 0 行 → 确认 `long_pct/short_pct` 兜底字段名清单是否需要补充
- open_interest 0 行 → 是否要求 `symbol=BTCUSDT` 而非 `BTC`?回报日志中的 first-row keys

---

## 7. 当前项目状态

commit 完成后:

```
btc_swing_system/
├── config/
│   ├── data_sources.yaml     (CoinGlass + Glassnode + ...,Binance 已删)
│   └── ... (9 个其他 yaml)
├── src/
│   ├── data/
│   │   ├── collectors/
│   │   │   ├── coinglass.py           (本次重写,~570 行)
│   │   │   ├── _field_extractors.py   (本次新建,~130 行)
│   │   │   ├── _config_loader.py
│   │   │   └── __init__.py
│   │   └── storage/                   (Sprint 1.1)
│   └── ...
├── scripts/
│   └── test_coinglass_collector.py    (本次加严判据)
└── docs/
    ├── cc_reports/
    │   ├── sprint_1_2_v2_fieldfix.md  (本报告)
    │   └── ... (之前的)
    └── PROJECT_LOG.md
```

**下一步**(待用户本地验证通过):
- Sprint 1.3:`src/data/collectors/glassnode.py`(链上;复用 `api.alphanode.work` + `x-key`)
- Sprint 1.4:原计划的"独立 CoinGlass"已合并进本 sprint,可用于**扩展端点**(ETF flows / 期权 OI / PCR / 基差)或**归并到 Sprint 1.3 之后**
