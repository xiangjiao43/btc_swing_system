# Sprint 1.2 fix — 拆分 Binance(K 线)与 CoinGlass(衍生品)

**日期**:2026-04-23
**触发**:Sprint 1.2 验证时 api.binance.com 返回 HTTP 451(美国 IP 地域封禁)
**依据**:旧系统验证过的架构 —— Binance 走 `data.binance.vision`(仅 K 线)+ CoinGlass 负责所有衍生品

---

## ⚠️ Triggers for Human Attention

> 以下是本次修正需要人类注意的决策点,可直接摘录给审阅者。

### 1. ⚠️ **最关键** —— 我没有验证 `data.binance.vision` 是否真支持 `/api/v3/klines` REST 接口

**背景**:公开资料里 `data.binance.vision` 通常是 **静态数据仓库**(serving ZIP/CSV archives,URL 形如 `/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01.zip`),**不是** Binance 的 REST API 镜像。

我**只改了 base_url**,`fetch_klines` 内部仍然请求 `/api/v3/klines`。两种可能:

- **(乐观)** 你旧系统验证过的 `data.binance.vision` **确实**也暴露了 `/api/v3/klines` 或类似路径的 REST 接口(可能是某个 reverse-proxy 行为)。本地跑 `uv run python scripts/test_binance_collector.py` 成功即此路径。
- **(悲观)** `data.binance.vision` 只服务 ZIP/CSV,请求 `/api/v3/klines` 会 404 或返回 HTML。你的旧系统实际是下载 ZIP + 解析 CSV,我没照抄那个逻辑。

**请你先本地跑一次验证命令:**
```bash
unset VIRTUAL_ENV && uv run python scripts/test_binance_collector.py
```

**如果跑通**:太好了,我的假设成立,任务完成。
**如果 404 / 返回 HTML / JSON 解析错**:把完整错误贴给我,我重写 `fetch_klines` 为 ZIP 下载 + CSV 解析的方式(这需要:
(a) 查 ZIP 索引找最近 N 天的月份文件;
(b) 下载 ZIP;
(c) 解压读 CSV;
(d) 拼成时间序列并写 DAO。非小改动,是完整的一次重构)。

**替代方案**:如果你的旧系统实际是别的某个 REST 端点(比如 `api.binance.vision` 或 `data-api.binance.vision` 或其他),告诉我 URL 我改就行。

### 2. 字段命名迁移:`api_key_header` / `api_key_query` → `api_key_header_name` / `api_key_query_name` + 新增 `auth_method`

你本次任务里的写法 "auth_method=query,api_key_query_name=..." 用了更显式的命名,我跟随你的风格统一了:

| 原字段名 | 新字段名 |
|---|---|
| `api_key_header`(null / header name) | `api_key_header_name` |
| `api_key_query`(null / query param name) | `api_key_query_name` |
| — | `auth_method`(new: "header" / "query" / null) |

**影响范围**:
- `config/data_sources.yaml`:6 个 source 全部更新(binance / glassnode / coinglass / yahoo_finance / fred / event_calendar_source)
- `src/data/collectors/_config_loader.py`:返回 dict 的 key 跟随重命名
- **已破坏性改动**,但由于只有 `binance.py` 消费 loader 输出,且它 auth_type=none 不用这些字段,**无实际代码失效**

### 3. 删除了 5 个 Binance 衍生品方法,**对任何调用方都会破坏**(但当前没有调用方)

删除清单:`fetch_funding_rate` / `fetch_open_interest` / `fetch_open_interest_hist` / `fetch_long_short_ratio` / `fetch_basis`。本 Sprint 截止前**没有任何代码调用这些方法**(前一版测试脚本是唯一调用者,已同步改写)。

**Sprint 1.4 的职责扩大提醒**:以前打算让 `CoinGlassCollector` 只提供"Binance 没覆盖"的东西,现在它要**全面覆盖**衍生品:funding_rate / open_interest / long_short_ratio / basis / put_call_ratio / liquidation / ETF flows。已记入 `docs/PROJECT_LOG.md`。

### 4. `.env.example` 有轻微用户体验损失

删掉了 `BINANCE_FUTURES_BASE_URL`,但如果你本地的旧 `.env` 文件**已经有**这个变量,它只会被忽略(loader 不再读取),不会报错。

另外我在注释里写了"CoinGlass 的 key 通常与 Glassnode **分开** 签发",因为两个域名明显不同,一般代理方会给不同的 key。如果你这里实际是**共用一个 key**,把两个 env 填同样的值即可。

### 5. 建模文档与实现的不一致暂未同步

`docs/modeling.md §3.6.1` 仍然写 "BTC 永续 K 线(Binance)"、"币安永续资金费率" 等。严格按 "建模文档是最终权威" 原则,我应该同步改建模文档。

**我的判断**:
- 建模文档是**v1.2 冻结版**,不应频繁修订内容
- 本次是"**实现层的路由选择**"(哪个域名、哪个服务)变更,不是模型变更
- 因此**不改建模文档**,在 `docs/PROJECT_LOG.md` 记录决策即可

如果你希望同步建模文档,告诉我,我会在 §3.6.1 / §3.6.2 加一行说明 "v1 实现层:衍生品由 CoinGlass 提供(因美国 IP 限制)"。

### 6. `schemas.yaml` 没有同步改

`schemas.yaml` 的 `consistency_notes` 还列着原来几处跨文件不一致。本次改 `data_sources.yaml` 不涉及 schemas 的字段契约(`data_sources` 不在 `schemas.yaml` 的 scope),所以没改。

---

## 1. 变更清单

| 文件 | 变更 |
|---|---|
| `src/data/collectors/binance.py` | 从 542 行 → 约 270 行;删 5 个衍生品方法;`collect_and_save_all` 只抓 K 线;docstring 重写;移除 futures_base_url 逻辑;import 从 dao 里去掉未用的 DerivativeMetric / DerivativesDAO / TimeFrame |
| `src/data/collectors/_config_loader.py` | 返回 dict 字段重命名 + 新增 auth_method;移除 futures_base_url |
| `config/data_sources.yaml` | binance / glassnode / coinglass 三条目全面校准;字段命名统一 6 处 |
| `.env.example` | 删 `BINANCE_FUTURES_BASE_URL`;注释校准 |
| `scripts/test_binance_collector.py` | 删衍生品测试段;通过判据改为"四档 K 线都 > 0" |
| `docs/PROJECT_LOG.md` | 追加 2026-04-23 决策记录 |
| `docs/cc_reports/sprint_1_2_fix.md` | 本报告(新增) |

**未修改**:`config/schemas.yaml` / `docs/modeling.md` / `src/data/storage/*`(存储层无关) / `tests/fixtures/*`(不受影响)

---

## 2. 验证结果(我的沙箱)

### YAML 合法性

```
config/data_sources.yaml: YAML OK
config/base.yaml: YAML OK
```

### 配置解析

```
binance:
  base_url:         https://data.binance.vision
  auth_type:        none
  auth_method:      None
  header_name:      None
  query_name:       None

glassnode:
  base_url:         https://api.alphanode.work
  auth_type:        api_key
  auth_method:      query
  header_name:      None
  query_name:       api_key

coinglass:
  base_url:         https://coinglass-api.alphanode.work
  auth_type:        api_key
  auth_method:      header
  header_name:      coinglass-secret
  query_name:       None
```

### BinanceCollector 类接口

```
BinanceCollector OK; base_url=https://data.binance.vision
(futures_base_url has been removed)
has fetch_klines: True
has fetch_funding_rate: False (should be False)
has fetch_basis: False (should be False)
```

**未跑真实抓取**(我沙箱被 Binance 451,此外前文 Trigger 1 描述的 data.binance.vision 不确定性也需你本地验证)。

---

## 3. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | `api_key_header` → `api_key_header_name` 全局重命名 | 跟随任务里的显式命名风格;语义更清晰 |
| B | 新增 `auth_method: "header"/"query"/null` 字段 | 任务要求;也比"二选一非 null"的隐式约定更易读 |
| C | 6 个 source 全部跟随命名迁移(非仅 binance/glassnode/coinglass) | 配置一致性比"最小改动"优先 |
| D | 删除 binance.py 里 5 个衍生品方法(而非保留为 deprecated) | 没有调用方;保留只会让 schema 混乱 |
| E | `collect_and_save_all` 返回 `{timeframe: count}` 而非原 `{endpoint_label: count}` | 任务要求;粒度更细 |
| F | test_binance_collector.py 的通过判据用"四档都 > 0" | 简单、容错(1w 数据量可能 < 500 但应 > 0) |
| G | 保留 `BinanceCollectorError` + `_RetryableHTTPError` 分类 | Sprint 1.2 的正确修复,继续有效 |
| H | 不改建模文档 §3.6.1/§3.6.2 | "实现路由"非"模型变更";PROJECT_LOG 记录足够 |
| I | CoinGlass 的 key env 注释暗示"通常与 Glassnode 分开" | 域名明显不同(coinglass-api vs api);用户可自行填相同值若 proxy 支持 |

---

## 4. 用户验证路径

```bash
cd ~/Projects/btc_swing_system
unset VIRTUAL_ENV
uv run python scripts/test_binance_collector.py
```

**预期**(如果 data.binance.vision 支持 REST):

```
[init_db] ...
...
Collect stats (K-lines only — derivatives now go via CoinGlass):
  1h     500 rows
  4h     500 rows
  1d     500 rows
  1w    ~XXX rows

1d K 线:共 500 根
最新 1d K 线:
  2026-04-XXT00:00:00Z O=XXX H=XXX L=XXX C=XXX ...

最旧 5 根:
  ...

VERDICT: PASS ✓
```

**失败路径**:
- HTTP 404 → Trigger 1 的悲观情况(数据仓库 URL 架构不对)
- HTTP 451 → data.binance.vision 也被地域封(不太可能,但若发生需换源)
- JSON 解析错 → 返回的是 HTML(数据仓库页面,非 JSON)

以上任何情况,请贴完整 ERROR 日志给我。

---

## 5. Sprint 1.3+ 工作面

- **Sprint 1.3**:`src/data/collectors/glassnode.py`(链上 collector,query 参数鉴权)
- **Sprint 1.4**:`src/data/collectors/coinglass.py`(衍生品 collector,**职责全面扩大** —— 含 funding / OI / long_short / basis / put_call / liquidation / ETF)
- **Sprint 1.5**:`src/data/collectors/yahoo_finance.py` + `fred.py`(宏观)
- 并行可做:`src/common/config.py` 统一 loader(替代当前的 `_config_loader.py`)
