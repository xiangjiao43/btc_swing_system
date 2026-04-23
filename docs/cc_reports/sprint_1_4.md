# Sprint 1.4 — Yahoo Finance + FRED 宏观采集器

**日期**:2026-04-23
**对应建模章节**:§3.6.4

---

## ⚠️ Triggers for Human Attention

### 1. Yahoo Finance 需要网络直连 Yahoo(可能被地域限制)

`yfinance` 包直接请求 Yahoo 的 Chart API(`query1.finance.yahoo.com`)。**美国本地通常可用**;但如果你在 VPS 上跑且 VPS IP 被 Yahoo 限流,可能 429 或空 DataFrame。

**处理**:`fetch_symbol` 返回空 DataFrame 时仅 warning 不报错;`collect_and_save_all` 仅在"全部 6 symbol 都失败"时抛错。

### 2. `yfinance` 是第三方库,API 可能变动

yfinance 社区维护,未来 Yahoo 改前端 HTML 时会失灵。Sprint 1.6+ 可考虑:
- 升级 yfinance 到最新
- 切换 yahoo_fin(另一个替代)
- 或只用 FRED(但 FRED 缺 VIX)

### 3. FRED **无 key 时 skip,不报错**

`FredCollector.__init__` 检查 `FRED_API_KEY`,空则 `enabled = False`,`collect_and_save_all` 返回 `{'__skipped': 0}`。

这是**有意的降级行为**:Yahoo 作主源已覆盖 DXY/US10Y/VIX/SP500/Nasdaq/Gold;FRED 只是 US10Y / CPI / 失业率的**备用**。无 FRED key 时系统仍能工作。

**获取 FRED key**:https://fred.stlouisfed.org/docs/api/api_key.html 免费注册 1 分钟。

### 4. Yahoo 和 FRED 都写入同一张 `macro_snapshot` 表,但 `source` 字段不同

- Yahoo:`source='yahoo_finance'`
- FRED:`source='fred'`

若两者采的同一指标(如 US10Y = `^TNX` vs `DGS10`)产生冲突,DAO 主键 `(timestamp, metric_name)` 会使后入者覆盖先入者。**metric_name 不同**可避免冲突:`us10y`(Yahoo)vs `dgs10`(FRED)。未来可在 indicators 层做一致性校验。

### 5. 数据量预期

- Yahoo:6 symbols × ~250 交易日/年 ≈ 1500 行
- FRED:4 series × 日频(DGS10/DFF)或月频(CPIAUCSL/UNRATE)混合 ≈ 700-800 行

若 Yahoo 某 symbol 零行,可能 Yahoo 临时拒绝此 ticker(如 DX-Y.NYB 偶尔出问题);重试或换 ticker(如 `DXY` 简写)。

### 6. `auto_adjust=False` 很重要

`yf.Ticker.history(auto_adjust=False)` 返回**原始**价格(未除权);如果用 `auto_adjust=True`,拆股/派息会调整历史 Close 价,**破坏 BTC 相关分析的一致性**。我们要原始价(`Close` 列,不是 `Adj Close`)。

对于 BTC 相关分析(DXY/VIX 等无股息拆分的宏观指标),True/False 结果应该一致,但为防意外仍显式 False。

---

## 1. 变更清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `pyproject.toml` / `uv.lock` | 修改 | 新增 `yfinance` |
| `src/data/collectors/yahoo_finance.py` | **新建** | YahooFinanceCollector,6 symbol |
| `src/data/collectors/fred.py` | **新建** | FredCollector,4 series,无 key 优雅 skip |
| `src/data/collectors/__init__.py` | 修改 | 暴露新 2 collector + 2 error 类 |
| `.env.example` | 修改 | 加 `FRED_API_KEY` 条目注释 |
| `scripts/test_macro_collector.py` | **新建** | 同时测 Yahoo + FRED |

---

## 2. Collector API

### YahooFinanceCollector

| Symbol | metric_name |
|---|---|
| `DX-Y.NYB` | `dxy` |
| `^TNX` | `us10y` |
| `^VIX` | `vix` |
| `^GSPC` | `sp500` |
| `^IXIC` | `nasdaq` |
| `GC=F` | `gold_price` |

- `fetch_symbol(symbol, since_days=365)` → `[{timestamp, metric_name, metric_value}]`
- `collect_and_save_all(conn, since_days=365)` → `{metric_name: rows_upserted}`

### FredCollector

| series_id | metric_name |
|---|---|
| `DGS10` | `dgs10` |
| `DFF` | `dff` |
| `CPIAUCSL` | `cpi` |
| `UNRATE` | `unemployment_rate` |

- `fetch_series(series_id, since_days=365)`
- `collect_and_save_all(conn, since_days=365)`(无 key 时返回 `{'__skipped': 0}`)

---

## 3. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 用 yfinance 而非直接调 Yahoo REST | 社区库封装稳定;失败模式清晰 |
| B | `auto_adjust=False` 获取原始价 | 与 BTC 对齐的一致性;避免隐式除权调整 |
| C | FRED 无 key 时 enabled=False + skip | 不阻塞主数据抓取;用户按需启用 |
| D | FRED 返回值为 `"."` 跳过 | FRED 官方约定的缺失标记 |
| E | Yahoo + FRED 共用 `macro_snapshot` 表不同 metric_name | 避免主键冲突;indicators 层按需选源 |
| F | 测试脚本 FRED 部分允许 skip verdict | `fred.enabled` 为 False 时该项判据跳过,不影响 PASS |
| G | 新 collector 用 `_env_loader` 自动加载 key 路径 | 与 CoinGlass/Glassnode 一致 |

---

## 4. 验证结果(本地烟测)

```
Yahoo symbol mapping: 6 symbols OK
FRED series mapping: 4 series OK
YahooFinanceCollector: mapped=6
FredCollector (no key): enabled=False, base_url=https://api.stlouisfed.org/fred
FredCollector (with key): enabled=True
FredCollector disabled collect returns: {'__skipped': 0}
```

**未跑真实网络抓取**(我的沙箱可能有网络限制,用户本地跑验证最稳)。

---

## 5. 用户验证路径

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV
uv run python scripts/test_macro_collector.py
```

预期(无 FRED_API_KEY 时):
- Yahoo 6 symbol,至少 5 个成功,各 ≥ 100 行
- FRED 跳过
- VERDICT: PASS ✓

有 FRED_API_KEY 时:
- 再抓 4 series,至少 3 个成功
