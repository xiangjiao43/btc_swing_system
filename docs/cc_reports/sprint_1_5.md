# Sprint 1.5 — Indicators 模块(纯本地技术指标)

**日期**:2026-04-23
**对应建模章节**:§4.2.5(L1 判断三支柱)、§3.8 各组合因子所需指标

---

## ⚠️ Triggers for Human Attention

### 1. ADX / RSI / ATR 用 Wilder 平滑(`alpha = 1/period`)

建模 §4.2.5 没明说平滑方式;行业标准是 Wilder(等价于 `ewm(alpha=1/period, adjust=False)`)。这和"用 SMA 平滑"的结果**不同**:Wilder 平滑衰减更慢,适合长期趋势判定。

**如果 backtest 对比旧系统结果有差异**,优先排查平滑法是否一致。可通过切换 `_wilder_smooth` 为 `.rolling(period).mean()` 验证。

### 2. `atr_percentile` 用"包含自身 + 相等值计 0.5"的中值排名法

实现里 `rank = (< current).sum() + (== current).sum() / 2`。这是 scipy 的 `percentileofscore(kind='mean')` 约定。

**若建模 §4.2.5 的 30/60/85 阈值是按 scipy `kind='rank'` 或 `kind='weak'` 校准的**,会有边界处差 1-2 个百分点。实际差异通常 < 2%,不影响 regime 判定。

### 3. `ichimoku.senkou_*` 用 `.shift(26)` 向未来推移

Ichimoku 的 senkou 是"当前计算值显示在 26 根后的未来位置"。pandas `.shift(n)` 正数 = 向后推移(值对齐到更晚的 index)。所以我的实现:
- `senkou_a = ((tenkan + kijun) / 2).shift(26)` → 26 根后才能看到
- `chikou = close.shift(-26)` → 向前推移,显示在过去位置(对齐原始 close 的 26 根前)

这是 Ichimoku **标准约定**。若你的业务期望"立即看到当前 senkou 值",是 shift 语义反了。

### 4. Swing 检测用**严格唯一最大/最小**,禁止平头顶

`swing_points` 里:
```python
highs_arr[i] == window_h.max() and (window_h == highs_arr[i]).sum() == 1
```
即窗口内**只有一个**峰值才算 swing。平头顶(两个相等高点并列)不算。避免过度敏感 + 避免一段平台期产生多个 swing。

### 5. RSI 常数输入的约定

`rsi(close_constant, period=14)` 返回 100.0(所有非 NaN 行)。

数学上 RS = 0/0 未定义。约定:无上涨无下跌 → RSI = 100(等价于"市场无压力")。更常见的约定也可能是 50(中性)或 NaN。Sprint 1.5+ 如果 regime 判定规则要用 RSI,记得这个边界。

### 6. 命名空间包配置:`pyproject.toml` 加了 `[tool.pytest.ini_options]`

新增:
```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

让 pytest 能 import `src.*`。不加这段会报 `ModuleNotFoundError: No module named 'src'`。

后续任何测试模块都会受益,但若你把测试改到 `src/tests/` 目录下则要调整 testpaths。

### 7. 当前 indicators 模块**不读 DAO**

输入是 `pd.Series`(或 HLC 三个 Series),输出也是 `pd.Series` / `dict[str, Series]`。与存储层完全解耦。

Sprint 1.6+ 的组合因子层会:
1. 从 DAO 读 kline rows
2. 转 pd.DataFrame
3. 调 indicators.* 的函数
4. 把结果输入 evidence layer

### 8. `macd` / `bollinger_bands` / `ichimoku_cloud` 返回 `dict[str, Series]`,不是 tuple

便于按名字访问,与下游消费的可读性一致。若 Sprint 1.6+ 希望返回 namedtuple / dataclass,后续可 wrap。

---

## 1. 变更清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `src/indicators/__init__.py` | **新建** | 统一导出 API |
| `src/indicators/trend.py` | **新建** | `ema / adx / plus_di / minus_di / macd` + 私有 `_wilder_smooth / _true_range` |
| `src/indicators/volatility.py` | **新建** | `atr / atr_percentile / bollinger_bands` |
| `src/indicators/ichimoku.py` | **新建** | `ichimoku_cloud` 5 条线 |
| `src/indicators/momentum.py` | **新建** | `rsi / stoch_rsi` |
| `src/indicators/structure.py` | **新建** | `swing_points / latest_swing_amplitude` |
| `tests/test_indicators.py` | **新建** | 30 测试;30 passed |
| `pyproject.toml` | 修改 | 加 `[tool.pytest.ini_options]` 配 pythonpath |

---

## 2. API 一览

### trend.py

```python
ema(series: pd.Series, period: int) -> pd.Series
adx(high, low, close, period=14) -> pd.Series       # Wilder ADX
plus_di(high, low, close, period=14) -> pd.Series
minus_di(high, low, close, period=14) -> pd.Series
macd(close, fast=12, slow=26, signal=9) -> dict{macd, signal, hist}
```

### volatility.py

```python
atr(high, low, close, period=14) -> pd.Series        # Wilder ATR
atr_percentile(atr_series, lookback=180) -> pd.Series  # 0-100 分位
bollinger_bands(close, period=20, std_dev=2.0) -> dict{upper, middle, lower}
```

### ichimoku.py

```python
ichimoku_cloud(high, low, close, tenkan=9, kijun=26, senkou_b=52, shift=26)
  -> dict{tenkan, kijun, senkou_a, senkou_b, chikou}
```

### momentum.py

```python
rsi(close, period=14) -> pd.Series        # Wilder RSI
stoch_rsi(close, period=14) -> pd.Series  # 0-1 归一化
```

### structure.py

```python
swing_points(high, low, lookback=5) -> list[dict{type, index, price}]
latest_swing_amplitude(high, low, lookback=5) -> float
```

---

## 3. Pytest 结果

```
30 passed in 0.42s
```

测试分组:
- TestEma × 5(shape / monotonic / constant / type error / invalid period)
- TestAdx × 4(shape / range 0-100 / trending → +DI > -DI / length mismatch)
- TestMacd × 3(keys / hist = macd - signal / fast < slow)
- TestAtr × 2(shape / positive)
- TestAtrPercentile × 1(shape + range 0-100)
- TestBollinger × 2(all 3 bands / upper ≥ middle ≥ lower)
- TestRsi × 4(shape / 单调递增 → ~100 / 单调递减 → ~0 / 常数 → 100)
- TestStochRsi × 1(range 0-1)
- TestIchimoku × 2(all 5 lines / length mismatch)
- TestSwingPoints × 4(simple / empty on short / length mismatch / invalid lookback)
- TestLatestSwingAmplitude × 2(basic / empty no swings)

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | ADX / RSI / ATR 用 Wilder 平滑 | 行业标准;与大多数分析软件一致 |
| B | `atr_percentile` 用 mean-rank(scipy kind='mean')| 边界值稳定;分位差异 < 2% |
| C | Ichimoku 用标准 26 偏移 | 文献默认;业务需要可参数化覆盖 |
| D | Swing 严格唯一最大(禁平头)| 避免连续相等点产生虚假 swing |
| E | RSI 常数输入 → 100 | 避免 NaN 传播;语义"无下跌压力" |
| F | 模块组织按 5 个文件(trend/vol/ichimoku/momentum/structure)| 每个指标族独立文件;改一个不影响其他 |
| G | `_wilder_smooth / _true_range` 作 trend.py 内部私有,volatility.py 通过 import 共享 | 单点实现;避免重复计算 TR |
| H | 返回 `dict[str, Series]` 而非 NamedTuple | 按名字访问更清晰;dict.keys() 自文档化 |
| I | 所有指标函数 accepts pd.Series,非 Series 抛 TypeError | 与 pandas 生态契合;禁止隐式转换避免意外 |
| J | pytest 配置加入 pyproject.toml | 单文件配置;`pythonpath = ["."]` 解决 src 命名空间包 import |

---

## 5. Sprint 1.5 → Sprint 1.6 衔接

本模块完成后,indicators 已就位。接下来(Sprint 1.6+)的工作:

1. **组合因子**(`src/composite/*`)消费 indicators + DAO 数据,产出 TruthTrend / BandPosition / Crowding 等 6 个组合因子
2. **证据层 L1**(`src/evidence/layer1_regime.py`)读 ADX / ATR percentile / TruthTrend 输出 regime
3. 其他层依赖类似链路

`indicators` 本身无需再改动,**完成状态**。

---

## 6. 命令行验证

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV
uv run pytest tests/test_indicators.py -v
# 预期 30 passed
```
