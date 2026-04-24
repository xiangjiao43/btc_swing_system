# 项目日志(PROJECT_LOG)

本文件记录 BTC 中长线低频双向波段交易辅助系统在开发过程中的关键决策、里程碑与版本变更。
流水式倒序排列(最新在上)。非决策性的细节或临时状态不写入本文件,保持信噪比。

---

## 2026-04-24 — Sprint 1 完成

数据层 + 证据层 + 决策层 + 持久层 + HTTP + 调度 + KPI + 复盘全部就位。
269 passed + 1 skipped,系统可 24/7 自动运行。手工触发、定时执行、查询历史、
生成复盘、活跃告警均已就绪。Sprint 2 起接入真实账户执行。

里程碑子 Sprint:
- 1.11 L5 Macro + AI Summary;1.12 StrategyStateBuilder;1.13 State Machine
- 1.14 AI Adjudicator + Lifecycle FSM;1.15 FastAPI + APScheduler
- 1.16 KPI Tracker + Review Report(Markdown)+ Fallback 自动升级 + /api/alerts

---

## 2026-04-23 — Sprint 1.2 重做:放弃 Binance,统一到 CoinGlass 承担 K 线 + 衍生品

### 背景

Sprint 1.2 及其第一次修正(上一条记录)连续尝试了两条 Binance 路径,都因美国节点的访问限制失败:
- `api.binance.com` / `fapi.binance.com` → HTTP 451 地域封禁
- `data.binance.vision` → 实际是静态 ZIP/CSV 数据仓库,不提供 REST API

### 根因与新架构(依据旧系统 `data_fetchers.py` 已验证路径)

阅读用户旧系统代码确认真实架构:

- **BTC K 线主数据源**改为 CoinGlass `/v4/api/futures/price/history`(参数 `symbol=BTCUSDT, exchange=Binance`),通过中转站 `api.alphanode.work` 访问
- **所有衍生品**(funding rate / open interest / long-short / liquidation / net_position)全部走 CoinGlass `/v4/api/futures/*/history`
- **链上**走 Glassnode,同样经 `api.alphanode.work` 中转站(与 CoinGlass **共享域名**)
- **共享鉴权**:HTTP header `x-key`(小写连字符)
- **共享 API key**:`COINGLASS_API_KEY` 和 `GLASSNODE_API_KEY` 通常填同一个 alphanode 中转站发的 key
- **限速**:15 req/min(旧系统 RateLimiter 参数)
- **超时 / 重试**:20s / 首次 + 2 次重试,固定 8s 间隔

### 代码层改动(commit `Sprint 1.2 redo`)

| 文件 | 变更 |
|---|---|
| `src/data/collectors/binance.py` | **删除**(Sprint 1.2 及其 fix 版本全部作废) |
| `scripts/test_binance_collector.py` | **删除** |
| `src/data/collectors/coinglass.py` | **新建** CoinglassCollector 类;6 个 fetch 方法 + collect_and_save_all |
| `src/data/collectors/__init__.py` | 去掉 BinanceCollector,暴露 CoinglassCollector |
| `config/data_sources.yaml` | 删除 `binance` 条目;`coinglass` 改为 `api.alphanode.work` + header `x-key`;`glassnode` 同步改为 header `x-key`(之前 Sprint 1.2 fix 里的 query auth 错了) |
| `.env.example` | 删除 `BINANCE_BASE_URL`;注明 CoinGlass / Glassnode 两个 key 通常填同一个 alphanode 值 |
| `scripts/test_coinglass_collector.py` | 新建;抓 4 档 K 线 + 5 衍生品端点 |

### 对后续 Sprint 的影响

- **Sprint 1.3**(Glassnode collector):直接复用本次 `api.alphanode.work + x-key` 配置,不需要再动配置
- **原计划 Sprint 1.4**(单独 CoinGlass):本次已合并进 Sprint 1.2 v2,该 Sprint 号直接跳过或用于 CoinGlass 扩展端点(如 ETF flows、期权 OI / PCR)
- **建模文档 §3.6.1 / §3.6.2**:保持不变。文档描述 v1.2 模型层约定,实现层的数据路由属于工程细节

---

## 2026-04-23 — Sprint 1.2 架构修正:Binance 仅抓 K 线,衍生品改走 CoinGlass

### 背景

Sprint 1.2 完成 BinanceCollector 后本地验证遇到**美国 IP 访问 api.binance.com 返回 HTTP 451**(地域封禁)。用户回忆旧系统验证过的方案:

- **Binance K 线**走 `data.binance.vision`(公开数据镜像,美国 IP 可访问)
- **衍生品**走 **CoinGlass**(因为 data.binance.vision 不提供 fundingRate / OI / long_short 等 fapi 端点)

### 决策

1. **拆分职责**
   - `BinanceCollector` 仅抓 K 线(1h / 4h / 1d / 1w)
   - `CoinGlassCollector`(Sprint 1.4 实现)抓所有衍生品

2. **数据源真实域名(旧系统验证过)**
   - Binance K 线:`https://data.binance.vision`
   - CoinGlass:`https://coinglass-api.alphanode.work`(注意 `coinglass-` 前缀)
     - 认证:HTTP header `coinglass-secret: <key>`
   - Glassnode:`https://api.alphanode.work`(裸域名)
     - 认证:查询参数 `?api_key=<key>`

3. **代码层改动**(2026-04-23 commit `Sprint 1.2 fix`)
   - `src/data/collectors/binance.py`:删除 5 个衍生品 fetch 方法,只留 `fetch_klines` + 简化版 `collect_and_save_all`
   - `config/data_sources.yaml`:binance/glassnode/coinglass 三条目 URL + 认证配置校准为真实值;字段命名统一(`api_key_header`/`api_key_query` → `api_key_header_name`/`api_key_query_name` + 新增 `auth_method`)
   - `.env.example`:删除 `BINANCE_FUTURES_BASE_URL`,修正 Glassnode / CoinGlass 说明
   - `scripts/test_binance_collector.py`:删掉衍生品测试段,只测 4 档 K 线
   - `src/data/collectors/_config_loader.py`:跟随字段重命名

### 对后续 Sprint 的影响

- **Sprint 1.4**(CoinGlass collector)职责扩大:需覆盖 funding_rate / open_interest / long_short_ratio / basis / put_call_ratio / liquidation / ETF flows(即 §3.6.2 全部衍生品指标)
- 涉及字段命名迁移(`api_key_header` → `api_key_header_name` 等)的后续 collector 读配置时要用新字段名

---

## 2026-04-22 — 项目初始化 / v1.2 建模完成,Sprint 1 前置工作计划

### 里程碑

- 建模文档 v1.2 定稿并归档至 [docs/modeling.md](modeling.md),作为编码唯一蓝本。
- 初始化项目骨架:目录结构按建模文档 §10.3 搭建;`uv init --python 3.12`;基础依赖登记到 `pyproject.toml`(未安装)。
- 本地 Git 仓库初始化,首次提交 `Initial project structure with v1.2 modeling doc`。

### Sprint 1 前置工作(三项优化)

在进入 Sprint 1(v0.1 骨架编码)之前,先完成三项基础优化,以降低后续编码阶段的返工成本。

**优化一:Schemas 契约(字段唯一真相来源)**

- 抽取建模文档中所有字段:
  - `StrategyState` 的 12 个业务块
  - 五层 `EvidenceReport`(L1 regime / L2 direction / L3 opportunity / L4 risk / L5 macro)
  - 6 个组合因子的 output
  - `AIAdjudicatorInput` / `AIAdjudicatorOutput`
- 生成 `config/schemas.yaml` 或 `config/schemas.json`,作为全项目字段的唯一真相来源。
- 所有 Pydantic model 后续从这份 schema 生成或与之对齐。
- **目的**:避免编码期字段散落在 3000 行建模文档里,减少跨模块字段不一致。

**优化二:9 个 Config 文件骨架**

- 按建模文档 §10.3 填充 9 个 config 文件的字段结构:
  - `base.yaml`
  - `data_sources.yaml`
  - `data_catalog.yaml`
  - `layers.yaml`
  - `state_machine.yaml`
  - `thresholds.yaml`
  - `event_calendar.yaml`
  - 3 个 prompt 文件:`adjudicator_system.txt` / `layer5_context.txt` / `adjudicator_fewshot_*`
- 骨架包含字段名 + 类型 + 示例值,真实数值和 API key 留到后续填。
- 其中 `event_calendar.yaml` 按 v1.2 M39 要求,用 `America/New_York` 时区存储 2026 全年 FOMC / CPI / NFP。
- **目的**:config 格式固定,代码只是读取层;后续改参数改 config,不改代码。

**优化三:3 个测试快照(fixtures)**

- 准备 3 个历史日期的完整数据快照,服务于单元测试和 M26 可交易性验收:
  - **场景 1(主升浪)**:2020-10-15
  - **场景 2(主跌浪)**:2022-05-01
  - **场景 3(震荡)**:2023-07-01
- 每个快照含:当天的原始数据(K 线 / 衍生品 / 链上 / 宏观)+ 预期证据层输出(regime、stance、phase、cycle_position 等)。
- 存到 `tests/fixtures/{scenario_name}/` 下,JSON 格式。
- **目的**:写函数时可以快速单元测试(输入快照 → 期待输出),不需要每次跑完整管道。

### 下一步

- 优化二的第一小步:生成 9 个 config 文件骨架(将另起对话)。
- 优化一、三依次推进;三项全部完成后进入 Sprint 1(v0.1 数据管道 + L1+L2 规则)。

---
