# Sprint 1.3 — Glassnode 链上数据采集器

**日期**:2026-04-23
**对应建模章节**:§3.6.3(链上数据三档分层)

---

## ⚠️ Triggers for Human Attention

### 1. Display 7 中某些 path 可能需要按 Glassnode 文档调整

旧系统 `glassnode_fetchers.py` 我没拿到原文,路径按 Glassnode 公开文档惯例拼:

| Metric | 我用的 path |
|---|---|
| lth_realized_price | `/v1/metrics/supply/lth_realized_price` |
| sth_realized_price | `/v1/metrics/supply/sth_realized_price` |

Glassnode 官方文档里 LTH/STH 的 realized price 有时在 `indicators/realized_price_lth` 路径下。本地跑如果 404,把实际 path 告诉我,两行改动。

### 2. Glassnode `t` 字段单位是**秒**,与 CoinGlass 的毫秒不同

`_fetch_series` 明确用 `to_iso_utc(t_raw, unit="s")`。若某天 Glassnode 改 API 用毫秒,要改 `unit="ms"` 或改成 `"auto"`。

### 3. Rate limit 注释写的是 15/min,但实际从 data_sources.yaml 读到 120/min

`data_sources.yaml` 里 glassnode 的 `rate_limit.requests_per_minute: 120`(Sprint 1.2 fix 时保留的值)。烟测输出 `rpm=120`。若你希望和 CoinGlass 一致(15/min),改 yaml 即可;我没擅自改,因为 Glassnode 中转站对链上数据可能有更宽的配额。

### 4. `lth_supply` 的"90 日变化"计算**不在 collector 层**

Collector 只抓原始时间序列。indicator 层(Sprint 1.5 开始)负责 `lth_supply_90d_change = (lth_supply_now - lth_supply_90d_ago) / lth_supply_90d_ago`。当前 since_days=180,保证有 180 天历史足够算 90d 变化。

### 5. `btc_price_close` 单独用 720 天(2 年)覆盖

ATH 跌幅计算需要历史最高价。2024-04 减半以来的最高点(~$69K / $109K 视截止日)在近 2 年数据里。Sprint 1.5 的 `ath_drawdown` 因子从此 metric 的历史序列算。

### 6. `v` 字段偶尔是 dict(多字段聚合)会被跳过并 warning

有些 Glassnode metric 返回 `{t, v: {...}}` 结构(如 HODL Waves 各年龄段分桶)。当前 `_fetch_series` 只接受 scalar `v`,非 scalar 会 warning 跳过。这是故意的 —— Sprint 1.3 覆盖的 13 个 metric 都是 scalar;未来遇到 dict 类 metric 时专门处理。

### 7. 没有 indicator / composite 层交叉验证,路径可能漂移

这 13 个 metric 拉到后,数据能入库,但**下游 indicators 还没建**(Sprint 1.5 任务 D)。本 Sprint 不保证"数据 → 因子"完整链路跑通,只保证"抓取 + 入库"正确。

---

## 1. 变更清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `src/data/collectors/_timestamp.py` | **新建** | `to_iso_utc(value, unit)` + `since_days_ago_unix(days, unit)` 跨 collector 共享 |
| `src/data/collectors/glassnode.py` | **新建** | GlassnodeCollector,13 个 fetch 方法 + `_fetch_series` 公共方法 |
| `src/data/collectors/__init__.py` | 修改 | 暴露 GlassnodeCollector / GlassnodeCollectorError |
| `scripts/test_glassnode_collector.py` | **新建** | 人工验证脚本,含 `_env_loader` + assertion |

---

## 2. GlassnodeCollector API

### Primary 5(主裁决,source="glassnode_primary")

| 方法 | path | 默认 since_days |
|---|---|---|
| `fetch_mvrv_z_score()` | `/v1/metrics/market/mvrv_z_score` | 180 |
| `fetch_nupl()` | `/v1/metrics/indicators/net_unrealized_profit_loss` | 180 |
| `fetch_lth_supply()` | `/v1/metrics/supply/lth_sum` | 180 |
| `fetch_exchange_net_flow()` | `/v1/metrics/transactions/transfers_volume_exchanges_net` | 180 |
| `fetch_btc_price_and_ath()` | `/v1/metrics/market/price_usd_close` | **720** |

### Display 7(辅助,source="glassnode_display")

| 方法 | path |
|---|---|
| `fetch_mvrv()` | `/v1/metrics/market/mvrv` |
| `fetch_realized_price()` | `/v1/metrics/market/price_realized_usd` |
| `fetch_lth_realized_price()` | `/v1/metrics/supply/lth_realized_price` |
| `fetch_sth_realized_price()` | `/v1/metrics/supply/sth_realized_price` |
| `fetch_sopr()` | `/v1/metrics/indicators/sopr` |
| `fetch_sopr_adjusted()` | `/v1/metrics/indicators/sopr_adjusted` |
| `fetch_reserve_risk()` | `/v1/metrics/indicators/reserve_risk` |
| `fetch_puell_multiple()` | `/v1/metrics/indicators/puell_multiple` |

### 高层

| 方法 | 说明 |
|---|---|
| `collect_and_save_all(conn)` | 抓上述 13 个 metric,写 OnchainDAO;全失败才抛错 |

---

## 3. 实现要点

### 3.1 `_fetch_series` 公共方法

```python
params = {"a": "BTC", "i": interval}
if since_days > 0:
    params["s"] = since_days_ago_unix(since_days, unit="s")
body = self._request("GET", path, params=params)
rows = self._unwrap_data(body)
# 每行 {t: 秒, v: 数值} → {timestamp, metric_name, metric_value, source}
```

13 个 metric 的逻辑相同,DRY。

### 3.2 `_unwrap_data` 区别于 CoinGlass

Glassnode 原生响应是**裸 JSON 数组**:`[{t, v}, ...]`。中转站可能偶尔包装成 `{data: [...]}`,两种都支持。

### 3.3 `_timestamp.py` 跨 collector 共用

`to_iso_utc(value, unit="auto")`:
- int/float: 按 unit 决定秒 or 毫秒;`auto` 时 >1e12 视为毫秒
- datetime: 直接格式化
- ISO 字符串: 支持 `Z` 和 `+00:00` 后缀
- 数字字符串: 递归转 float

`since_days_ago_unix(days, unit="s")`:返回 N 天前的整数 unix 时间戳,避免每个 collector 手写 `datetime.now - timedelta`。

### 3.4 与 CoinGlass 差异对照

| 维度 | CoinGlass | Glassnode |
|---|---|---|
| 时间戳单位 | ms | **s** |
| 响应 envelope | `{code, data}` | 裸数组(或兜底 `{data}`) |
| Key header | `x-key` | `x-key`(同) |
| base_url | `api.alphanode.work` | `api.alphanode.work`(同) |
| 路径前缀 | `/open-api-v4.coinglass.com/api/...` | `/v1/metrics/...`(原生) |

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 新建 `_timestamp.py` 放共享时间戳工具 | CoinGlass 毫秒 / Glassnode 秒 / Yahoo datetime 都会用,统一 |
| B | Glassnode 传 `s` 参数(since 秒戳) | 避免"返回所有历史"的带宽浪费;若中转站忽略也无害 |
| C | `lth_supply` 只抓原值,90d 变化放 indicators 层 | Collector 纪律:只抓,不算 |
| D | `btc_price_close` since_days=720 单独加长 | ATH 跌幅需要 ~2 年历史 |
| E | Display 7 path 按公开文档惯例拼;旧系统实际 path 以真实运行为准 | 没拿到旧系统原文;跑失败再按 404 调整 |
| F | `source='glassnode_primary'` vs `'glassnode_display'` 明确分档 | data_catalog / 下游按 source 过滤便利 |
| G | `v` 是 dict 时 warning 跳过 | 当前 13 metric 都是 scalar;未来遇到 HODL Waves 等字典类再扩 |
| H | 保留原有 Glassnode rate_limit 120/min(不同于 CoinGlass 15) | data_sources.yaml 没说明要同步;Glassnode 中转配额可能更宽 |
| I | `_fetch_series` 作为底层,13 个 fetch 方法做薄包装 | 单点维护逻辑 + 清晰 API |
| J | Primary/Display 混写在一个 collector | Glassnode API 结构同构,无需拆两个类;source 字段做区分 |

---

## 5. 验证结果(本地烟测 OK,无真实 API)

```
_timestamp module:
  ms auto detect: 1704067200000 → 2024-01-01T00:00:00Z ✓
  s auto detect:  1704067200 → 2024-01-01T00:00:00Z ✓
  explicit unit='s' ✓
  datetime passthrough ✓
  since_days_ago_unix returns valid unix seconds ✓

GlassnodeCollector:
  base_url=https://api.alphanode.work, rpm=120
  all 13 path constants correct ✓
  all 18 methods present ✓
  _unwrap_data: bare array ✓, wrapped dict ✓, null data ✓
```

**未跑真实 API**(当前 GLASSNODE_API_KEY 为空,因 Task A 烟测误删 .env;用户重建 .env 后可跑真实验证)。

---

## 6. 用户验证路径(重建 .env 后)

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV
uv run python scripts/test_glassnode_collector.py
```

预期 PASS:
- primary 5 各 ≥ 100 行(180 天日级数据)
- btc_price_close ≥ 500 行(720 天)
- display 7 ≥ 5 个成功
