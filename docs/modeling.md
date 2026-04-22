# BTC 中长线低频双向波段交易辅助系统
## 完整建模文档 v1.2(编码唯一蓝本)

---

**文档性质**:系统设计建模文档,作为编码实施的唯一蓝本
**文档版本**:v1.2(基于 v1.1 + 45 条修订收口)
**建模状态**:建模正式结束,进入工程实施阶段
**阅读对象**:开发者、AI 编程助手(Claude Code 等)、交叉审阅者

---

## 文档使用说明

本文档是整个系统的蓝图总册。它自包含,不依赖任何其他文档。任何人或任何 AI 编程助手拿到这份文档,应该能独立完成以下事情:

- 理解系统要做什么、不做什么
- 理解系统的全部架构和模块划分
- 理解每一层的输入输出、判断逻辑、接口契约
- 理解每一个数据因子的来源、公式、用途
- 理解状态机和生命周期如何流转
- 理解 AI 如何被提示、如何被约束、如何被校验
- 理解网页如何展示
- 理解工程上如何实施、测试、部署

编码实施时,代码必须严格对齐本文档。若代码实施过程中发现文档有遗漏或不合理,应先回到文档修订,再修改代码,不得直接让代码与文档脱节。

---

## 版本变更记录

**v1.0(初版)**:系统定位、五层证据架构、13 状态状态机、StrategyState、AI 契约框架、网页 API、工程目录

**v1.1**:10 问收口 38 条修订;数据因子体系从战略地图落到可执行颗粒度;新增组合因子设计;证据层 v0.1 参数初始值;AI Prompt 终稿;14 状态(新增 POST_PROTECTION_REASSESS);中转站配置

**v1.2(本版)**:基于 v1.1 再做 45 条修订收口,聚焦四个主题:

- **架构封闭性**(删除 EWQ / L3 纯规则判档 / 因子单一作用点 / opportunity_grade 三重封闭)
- **多层收紧不过度保守**(position_cap 合成 + 硬下限;execution_permission 归并 + A 级缓冲;观察分类字段;低频边界定义;可交易性验收与 KPI)
- **数据契约完整**(数据时间对齐;执行顺序;数据新鲜度;事件触发运行;美国夏令时处理)
- **工程落地细节**(evidence_cards 规则;降级版 StrategyState;告警通道;冷启动;版本号;AI 模型记录)

**v1.2 的目标**:覆盖所有"若不澄清会让代码走偏或让系统长期不给策略"的问题,作为编码的唯一蓝本。

---

# 目录

- 第一部分:系统定位与目标
- 第二部分:总体架构
- 第三部分:数据与因子建模
- 第四部分:证据层详细建模
- 第五部分:状态机与生命周期
- 第六部分:AI 裁决契约与 Prompt 终稿
- 第七部分:策略输出模型 StrategyState
- 第八部分:历史、复盘与监控
- 第九部分:网页与 API 设计
- 第十部分:工程落地
- 第十一部分:未决问题与风险
- 第十二部分:v1.2 修订合并清单
- 附录 A:术语表
- 附录 B:核心设计原则
- 附录 C:系统不做的事

---

# 第一部分:系统定位与目标

## 1.1 一句话定位

一个以 BTC 大级别波段为观察与交易单位、以低频高确定性为行为准则、以双向切换为机会结构、以可审计可复盘为工程底色的中长线交易辅助系统。

## 1.2 系统是什么

- 观察单位:4H / 1D / 1W 级别为主,1H 仅作执行确认
- 决策颗粒度:天到周级别
- 方向能力:双向,可多、可空、可切换
- 定位:辅助系统,输出策略建议,不自动执行
- 运行模式:定时运行 + 事件触发补充运行(详见第五部分)
- 输出形式:结构化策略对象,含完整的开仓/持仓/减仓/离场/切换指令
- 可审计:每个结论可追溯至具体证据,带时间戳
- 可复盘:每轮完整生命周期结束后自动生成归因报告

## 1.3 系统不是什么

- 不是高频或短线系统
- 不是单向(只多或只空)系统
- 不是追求极限抄底逃顶的预测系统
- 不是主观喊单或黑箱学习系统
- 不是堆砌指标简单打分的系统
- 不是机构量化模板的照搬
- 不是把所有宏观新闻当主链因子的系统

## 1.4 目标函数

```
目标 = 累计主行情覆盖率 × 平均持有期长度 ÷ 全周期交易次数
```

三个变量必须同时优化。单看任一维度都会误判系统价值。

## 1.5 最该避免的代价(按严重度排序)

1. 震荡区反复打脸(最严重)
2. 主行情中途被短周期噪音震下车
3. 方向对但执行窗口错导致反复止损
4. 策略切换不及时
5. 错过一轮主行情(代价最小)

核心原则:**错过比做错便宜**。

## 1.6 系统默认行为

系统的默认状态是**观望**,不是"选方向"。每一层都可以合法输出 insufficient_data 或低置信度结论。每次裁决都可以选择"继续保持当前状态"。

## 1.7 低频与过度保守的边界(v1.2 新增,对应 M25)

本系统是"低频",不是"过度保守"。两者的边界:

**合格的低频(期望行为)**:
- 每 30-90 天产出 1-3 次 PLANNED 状态
- 每轮完整生命周期持续 2 周到 3 个月
- 单次生命周期内状态迁移次数 ≤ 8 次

**过度保守(不合格行为,触发人工介入)**:
- 连续 > 90 天无 PLANNED 迁移
- KPI-1(主升浪捕捉率)或 KPI-2(主跌浪反应率)未达标
- Fallback Level 1 连续触发 ≥ 5 次
- 同一 CyclePosition 下 position_cap final 连续 ≥ 10 次 < 20%

任何触发"过度保守"的事件必须:
- 推送 critical 告警
- 在 StrategyState 中显式标记
- 进入下一次人工复盘议程

## 1.8 Observation Category 机制说明(v1.2 新增,对应 M28)

系统对"每次观望的质量"做实时分类,输出到 StrategyState 的 observation_category 字段。三个标签:

- **disciplined**:证据明确不利于开仓(方向不明、位置不好、风险大)
- **watchful**:证据有正面但不足以开仓(正常的等待)
- **possibly_suppressed**:多项正面证据存在但叠加后仍无机会(需用户关注)

**纪律条款**:observation_category 是系统自我观察的产物,不是系统自我调节的依据。任何试图让其进入决策路径的代码实现都是违反建模的行为。具体作用范围见第 4.7 节。

---

# 第二部分:总体架构

## 2.1 架构图

```
┌────────────────────────────────────────────────────┐
│                  数据采集层                        │
│    币安 / Glassnode / Coinglass / 宏观 / 事件      │
│        (全部经中转站,v1.2 强制"先抓后算")         │
└──────────────────────┬─────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────┐
│              数据就绪与新鲜度标记                   │
│  reference_timestamp + data_captured_at + stale 标 │
└──────────────────────┬─────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────┐
│                  指标计算层                        │
│     单因子计算(ADX、ATR、MVRV、资金费率分位等)    │
└──────────────────────┬─────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────┐
│                  组合因子层                        │
│  TruthTrend / BandPosition / CyclePosition /       │
│  Crowding / MacroHeadwind / EventRisk(共 6 个)   │
│  (v1.2 删除 EWQ;ExchangeMomentum 降为 L2 修正项) │
└──────────────────────┬─────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────┐
│                  证据层(五层)                    │
│   L1 市场状态 / L2 方向结构 / L3 机会执行          │
│            L4 风险失效 / L5 背景事件               │
│        (v1.2 强制单次运行内 L1→L5 顺序执行)      │
└──────────────────────┬─────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────┐
│             Observation Classifier                  │
│   规则层产出 observation_category(只读标记)       │
└──────────────────────┬─────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────┐
│                  裁决层                            │
│  状态机(14 状态)+ 证据汇总 + AI 裁决 + Fallback │
└──────────────────────┬─────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────┐
│                  策略输出层                        │
│   StrategyState + 生命周期管理 + 差异计算          │
└──────────────────────┬─────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
  ┌──────────┐   ┌───────────┐   ┌──────────┐
  │ 历史复盘 │   │ 监控告警  │   │ 网页 API │
  └──────────┘   └───────────┘   └──────────┘
```

## 2.2 核心原则

1. **单向信息流**:底层数据向上流动,上层不直接访问底层原始数据
2. **证据不足默认沉默**:每层可合法输出低置信度
3. **状态迁移而非状态选择**:系统不是每次从零选方向,而是在当前状态基础上判断是否迁移
4. **规则为主,AI 辅助**:AI 只在第 5 层(语义理解)和最终裁决(多维权衡)介入
5. **失败降级优于失败停机**:分三级 Fallback(详见第六部分)
6. **v1.2 新增:先抓后算**:所有数据采集完成后才开始证据层计算,严禁交错
7. **v1.2 新增:因子单一作用点**:每个组合因子只在指定的一个层发挥作用,禁止跨层再次评分
8. **v1.2 新增:opportunity_grade 三重封闭**:L3 为唯一产出点,AI 不可修改,其他层不可旁路改写

## 2.3 程序与 AI 分工

| 环节 | 主责 | 理由 |
|---|---|---|
| 数据采集清洗 | 程序 | 确定性工作 |
| 指标计算 | 程序 | 规则明确 |
| 组合因子 | 程序 | 权重可配置化 |
| L1 市场状态 | 程序 | 可规则化 |
| L2 方向结构 | 程序 | 可规则化 |
| L3 机会执行 | 程序 | **纯规则判档层**(v1.2 强化) |
| L4 风险失效 | 程序 | 可规则化 |
| L5 背景事件 | AI | 涉及语义理解 |
| Observation 分类 | 程序 | v1.2 新增,规则判定 |
| 证据汇总 | 程序 | 结构化组装 |
| 最终裁决 | AI 主导,程序约束 | 多维权衡 + 叙事 |
| 输出校验 | 程序 | 确保 AI 输出合法 |
| 历史归档 | 程序 | 确定性 |
| 复盘分析 | 程序为主,AI 辅助 | 规则归因 + 文字总结 |

## 2.4 证据层分层职责与否决权分类

| 层 | 问题 | 否决类型 |
|---|---|---|
| L1 | 现在是什么性质的市场? | 软否决(chaos/extreme 通过标准通道影响下游) |
| L2 | 方向偏哪边?阶段在哪? | 非否决(方向不明时输出 neutral) |
| L3 | 是好的动手时机吗? | 非否决(只能降到 watch) |
| L4 | 什么条件下判断失效? | **硬否决**(hard_invalidation_levels 唯一权威) |
| L5 | 宏观是加分还是减分? | 软否决(extreme_event_detected=true 时接管 PROTECTION) |

**三类否决的显式分类(v1.2 对应 M21)**:

**硬否决(Hard Block)**:
- L4 hard_invalidation_levels 触发 → 强制平仓
- L5 extreme_event_detected = true → 强制 PROTECTION

**软否决(Soft Block,效果接近否决但走标准通道)**:
- L1 regime = chaos → 下游 execution_permission 强制 watch
- L1 volatility_regime = extreme → 下游 position_cap × 0.5
- L4 overall_risk_level = critical → 下游 final_permission = protective

**非否决(只修正)**:
- L2 neutral stance
- L3 opportunity_grade = none  
- L4 其他风险标签
- L5 非 extreme 事件

---

# 第三部分:数据与因子建模

## 3.1 数据平台选择与访问方式

### 3.1.1 数据平台

| 平台 | 用途 | 账户 | 访问 |
|---|---|---|---|
| 币安(Binance) | K 线、合约、持仓、订单簿 | 免费 API | 经中转站 |
| Glassnode | 链上数据 | Advanced / Pro | 经中转站 |
| Coinglass | 衍生品聚合、清算、ETF | Professional | 经中转站 |
| Yahoo Finance | 宏观(DXY / US10Y / VIX / 指数) | 免费 | 直连,`yfinance` |
| FRED | 美国经济官方数据(备用) | 免费 | 直连 |
| investpy / Trading Economics | 事件日历备用 | 免费 | 直连(v1 手动维护优先) |

### 3.1.2 中转站配置

- 所有数据采集器的 base_url 从 `config/data_sources.yaml` 读取
- 中转站 URL 与 API key 放 `.env`,不进代码库
- 每个数据源独立配置 timeout、重试、速率限制
- 中转站切换或失效时,只改配置,不改代码

### 3.1.3 预算

- Glassnode Advanced:已订阅
- Coinglass Professional:已订阅
- 其他数据源:免费
- 云部署(可选):海外 VPS $5-15/月

## 3.2 数据采集与决策的时序契约(v1.2 新增,对应 M29)

### 3.2.1 执行顺序硬规则

单次系统运行的阶段顺序:

```
阶段 1:数据采集阶段
        - 一次性完成所有数据源的抓取和入库
        - 记录每个数据点的 data_captured_at
        - 本阶段完成后才进入下一阶段
阶段 2:证据层计算阶段
        - 按 L1 → L2 → L3 → L4 → L5 顺序
        - 各层只读本次已就绪的上层结论
        - 若上层失败,本层标记 depends_on_failed_upstream,输出 insufficient_data
阶段 3:Observation 分类阶段
        - 产出 observation_category
阶段 4:AI 裁决阶段
        - 读取完整 evidence_summary + observation_category
        - 产出决策
阶段 5:校验与输出阶段
        - program validator 校验 AI 输出
        - 写入 StrategyState
```

**不允许**的模式:
- 一边抓数据一边算证据
- L2 读取上一次运行的 L1 结论
- 跨阶段并发执行

### 3.2.2 reference_timestamp 机制

- 每次运行记录一个 `reference_timestamp`(本次运行的"判断时刻")
- 以数据采集阶段结束时的 UTC 时间为准
- 所有新鲜度检查以此为基准

### 3.2.3 数据新鲜度阈值

| 数据类别 | stale 阈值 |
|---|---|
| 价格类 | > 30 分钟 |
| 衍生品类 | > 6 小时 |
| 宏观类 | > 36 小时 |
| 链上类 | > 48 小时 |

### 3.2.4 Stale 数据的处理

- 单个 stale 数据点 → 对应组合因子置信度 × 0.7
- 某个数据源全部 stale → 对应证据层标记 degraded
- 3+ 数据源全部 stale → 触发 Fallback Level 2
- 每个 evidence_card 和 evidence_summary 都携带 `data_freshness` 字段,AI 裁决时可见

## 3.3 事件触发运行机制(v1.2 新增,对应 M38)

### 3.3.1 三层运行机制

**第一层:定时基线运行(保留)**
- 北京时间每日 6 次:00 / 04 / 08 / 12 / 16 / 20
- 作用:常态监控、持仓管理、状态机推进

**第二层:事件驱动补充运行(v1.2 新增)**
- 宏观数据事件:数据发布后 15 分钟自动触发
- 链上数据事件:Glassnode 日级更新后触发(北京 08:15-08:30)
- 衍生品事件:资金费率结算后 15 分钟
- 期权事件:月度/季度到期前 1 小时
- 市场事件:价格 ±3% 异动 / 硬失效位触发 / 事件窗口前 30 分钟

**第三层:手动触发(调试用)**

### 3.3.2 节流规则

- 同类事件 2 小时内只触发一次
- 整点运行进行中,事件触发推迟 5 分钟
- 距上次整点运行 < 30 分钟,跳过本次事件触发

### 3.3.3 run_trigger 字段枚举

StrategyState 中的 `run_trigger` 字段:
- scheduled:整点运行
- event_macro:宏观数据事件
- event_onchain:链上数据事件
- event_funding:资金费率事件
- event_options:期权到期事件
- event_price:价格异动事件
- event_invalidation:失效位触发事件
- manual:手动触发

## 3.4 美国事件时区与夏令时处理(v1.2 新增,对应 M39)

### 3.4.1 时间存储规则

- 所有美国事件在 `config/event_calendar.yaml` 中用**美国东部时间(America/New_York)**存储
- 所有 UTC 基准事件用 UTC 存储
- **绝不直接存北京时间**
- 时区转换由系统运行时完成,使用 Python `zoneinfo`(优先)或 `pytz`

### 3.4.2 受夏令时影响的事件

- FOMC 决议及新闻发布会
- FOMC 会议纪要
- 美国 CPI / 核心 CPI / PPI
- 美国非农就业
- 美联储主席及要员讲话
- 美国 GDP / 零售销售 / 消费者信心
- 美股开盘 / 收盘
- 所有以美国东部时间为基准发布的宏观数据

### 3.4.3 不受夏令时影响的事件(固定 UTC)

- 币安资金费率结算(UTC 00/08/16)
- Glassnode 日级数据更新(UTC 00:00)
- 期权月度/季度到期(UTC 16:00)

### 3.4.4 事件日历数据来源

- v1 阶段:**手动维护** `config/event_calendar.yaml`
- 每年 12 月人工更新下一年度的 FOMC / CPI / NFP 日程
- 更新来源:美联储官网 / BLS 官网 / 交易所财经日历

### 3.4.5 实施要求

- 使用 Python 内置 `zoneinfo`(Python 3.9+),不依赖 pytz
- 时区转换单元测试必须覆盖"夏令时切换日前后各 3 天"
- 事件日历加载失败时:仅运行定时整点 6 次,不执行事件触发;推送 warning 告警
- 事件触发时 StrategyState 记录:event_source、event_time_us_east、event_time_bjt、dst_active

## 3.5 因子三层分类

```
L1 原始数据(Raw Data)
  从 API 直接抓回的一手数据
    ↓
L2 单因子(Single Indicator)
  基于原始数据计算的独立指标
    ↓
L3 组合因子(Composite Signal)
  多个单因子按规则组合产生的高阶信号
    ↓
  证据层消费组合因子做出结论
```

## 3.6 L1 原始数据清单

### 3.6.1 价格与成交(币安)

| 因子 | 接口 | 频率 | 归属 |
|---|---|---|---|
| BTC 现货 K 线 1H | `/api/v3/klines?symbol=BTCUSDT&interval=1h` | 每小时 | 执行确认 |
| BTC 现货 K 线 4H | `/api/v3/klines?symbol=BTCUSDT&interval=4h` | 每 4 小时 | L1, L2 |
| BTC 现货 K 线 1D | `/api/v3/klines?symbol=BTCUSDT&interval=1d` | 每天 | L1, L2, L3 |
| BTC 现货 K 线 1W | `/api/v3/klines?symbol=BTCUSDT&interval=1w` | 每周 | L1, L2 |
| BTC 永续 K 线(同四个周期) | `/fapi/v1/klines` | 同上 | L4 验证 |
| 24h 成交统计 | `/api/v3/ticker/24hr` | 每次运行 | L3 |
| 订单簿深度 | `/api/v3/depth?limit=100` | 每次运行 | L3 |
| BTC 历史 ATH 价格 | 从 K 线计算 | 每次运行 | 熊市分档必需(v1.2) |

### 3.6.2 衍生品(币安 + Coinglass 并用)

| 因子 | 平台 / 接口 | 频率 |
|---|---|---|
| 币安永续资金费率 | Binance `/fapi/v1/fundingRate` | 每 8h |
| 全交易所加权资金费率 | Coinglass `/api/futures/fundingRate` | 每小时 |
| 币安永续 OI | Binance `/futures/data/openInterestHist` | 每小时 |
| 全交易所总 OI | Coinglass OI aggregated | 每小时 |
| 币安大户多空比 | Binance `/futures/data/topLongShortAccountRatio` | 每小时 |
| 币安散户多空比 | Binance `/futures/data/globalLongShortAccountRatio` | 每小时 |
| 清算历史 | Coinglass `/api/futures/liquidation` | 每小时 |
| 清算热力图 | Coinglass `/api/futures/liquidationChart` | 每 4h |
| ETF 流入流出 | Coinglass ETF API | 每天 |
| 期权未平仓 | Coinglass Options OI | 每小时 |
| Put/Call Ratio | Coinglass | 每小时 |
| 基差(永续 vs 季度) | Coinglass Basis | 每小时 |

### 3.6.3 链上(Glassnode Advanced,v1.2 分三档)

**第一类:主裁决因子(v1 必抓,参与规则判定,共 5 个)**

| 指标 | 端点 | 频率 |
|---|---|---|
| MVRV Z-Score | `/v1/metrics/market/mvrv_z_score` | 每天 |
| NUPL | `/v1/metrics/indicators/net_unrealized_profit_loss` | 每天 |
| LTH Supply | `/v1/metrics/supply/lth_sum` | 每天 |
| Exchange Net Flow | `/v1/metrics/transactions/transfers_volume_exchanges_net` | 每小时 |
| (BTC 距 ATH 跌幅由价格计算,不是 Glassnode) | — | — |

**第二类:证据卡展示因子(v1 抓取但不直接参与规则,共 7 个)**

| 指标 | 端点 | 频率 |
|---|---|---|
| MVRV Ratio | `/v1/metrics/market/mvrv` | 每天 |
| Realized Price | `/v1/metrics/market/price_realized_usd` | 每天 |
| LTH Realized Price | `/v1/metrics/indicators/realized_price_lth` | 每天 |
| STH Realized Price | `/v1/metrics/indicators/realized_price_sth` | 每天 |
| SOPR | `/v1/metrics/indicators/sopr` | 每天 |
| aSOPR | `/v1/metrics/indicators/sopr_adjusted` | 每天 |
| Reserve Risk | `/v1/metrics/indicators/reserve_risk` | 每天 |
| Puell Multiple | `/v1/metrics/indicators/puell_multiple` | 每天 |

**第三类:延后到 v1.x(v1 不抓)**

HODL Waves / CDD / Liveliness / LTH-SOPR / STH-SOPR / Active Addresses / New Addresses / Transaction Count / Miner 系列 / Hash Ribbon / SSR

### 3.6.4 宏观(Yahoo Finance / FRED)

| 因子 | 来源 | 频率 |
|---|---|---|
| DXY | Yahoo `^DXY` | 每天 |
| US10Y | Yahoo `^TNX` / FRED `DGS10` | 每天 |
| VIX | Yahoo `^VIX` | 每天 |
| 标普 500 | Yahoo `^GSPC` | 每天 |
| 纳指 100 | Yahoo `^NDX` | 每天 |
| 黄金 | Yahoo `GC=F` | 每天 |

### 3.6.5 事件日历

- v1 阶段手动维护 YAML(按问题 M39)
- 备用库:investpy / Trading Economics 免费层

## 3.7 L2 单因子清单

### 3.7.1 价格结构

| 因子 | 计算 | 归属 |
|---|---|---|
| ADX-14(1D) | Wilder ADX 周期 14 | L1 |
| ADX-14(4H) | 同上 | L1 辅助 |
| ATR-14(1D) | 14 周期 ATR | L1 |
| ATR/Price 比率 | ATR / 收盘价 | L1 |
| ATR 百分位 | 过去 180 天分位 | L1 |
| MA-20/60/120/200(1D) | 简单移动平均 | L1 + L2 |
| Swing Highs / Lows(1D) | 左右 N=5 窗口 | L2 |
| 多周期方向一致性 | 4H/1D/1W | L1 |

### 3.7.2 衍生品

| 因子 | 计算 | 归属 |
|---|---|---|
| 资金费率当前值 | 直接读 | L4 |
| 资金费率 7 日均 | 最近 21 个 8h 均值 | L4 |
| 资金费率 30 日分位 | 当前值在 30 日分布中的位置 | L4 |
| 资金费率 Z-score(90 天) | (current - mean_90d) / std_90d | L4 |
| OI 24h 变化率 | (OI_now - OI_24h_ago) / OI_24h_ago | L4 |
| OI / 市值比率 | 全市场 OI / BTC 市值 | L4 |
| 多空比变化率(24h) | 速度变化 | L4 |
| 清算密度指数 | 关键位附近潜在清算总量 | L3 + L4 |
| 基差年化 | (季度 - 永续) / 永续 × 年化 | L4 |
| Put/Call Ratio(OI) | 看跌 OI / 看涨 OI | L4 |

### 3.7.3 链上

| 因子 | 计算 | 归属 | v1 角色 |
|---|---|---|---|
| MVRV | 直接读 | L2 长周期 | 展示 |
| MVRV Z-Score | 直接读 | L2 长周期 + L4 | 主裁决(CyclePosition) |
| NUPL | 直接读 | L2 | 主裁决(CyclePosition) |
| LTH Supply 90 日变化 | LTH 增减速度 | L2 | 主裁决(CyclePosition) |
| Exchange Net Flow 7 日均 | 平滑净流入 | L2 | 主裁决(ExchangeMomentum) |
| Reserve Risk | 直接读 | L2 底部信号 | 展示 |
| Puell Multiple | 直接读 | L2 | 展示 |
| SOPR | 直接读 | L2 | 展示 |
| aSOPR | 直接读 | L2 | 展示(B4 明确) |
| BTC 距 ATH 跌幅 | (ATH - 当前) / ATH | L2 | 主裁决(CyclePosition 辅助条件) |

### 3.7.4 宏观

| 因子 | 计算 | 归属 |
|---|---|---|
| DXY 20 日变化率 | 趋势 | L5 |
| US10Y 30 日变化(bp) | 利率趋势 | L5 |
| VIX 当前值 | 直接读 | L5 |
| 纳指 20 日变化 | 趋势 | L5 |
| BTC-纳指 60 日相关性 | 滚动相关系数 | L5 |
| BTC-黄金 60 日相关性 | 滚动相关系数 | L5 |

## 3.8 L3 组合因子清单(v1.2 最终 6 个)

**v1.2 组合因子总览**:

- **保留**:TruthTrend、BandPosition、CyclePosition、Crowding、MacroHeadwind、EventRisk
- **删除**:EntryWindowQuality
- **移位**:ExchangeMomentum 降为 L2 内部 stance_confidence 修正项,不作为独立组合因子

### 3.8.1 组合因子一:趋势真实性指数(TruthTrend)

**问题**:当前趋势是真实结构性趋势还是噪音误导?
**归属**:L1 → L2
**单一作用点**:L1 的 regime 判定和 regime_confidence,不跨层

**评分规则**:
- ADX-14(1D) ≥ 25 → +2
- ADX-14(4H) ≥ 20 → +1
- 4H/1D/1W 三周期方向一致 → +3
- MA-20/60/120 排列正确 → +2
- 当前价格与 MA-200 相对位置符合趋势方向 → +1

**输出**:0-9 分
- ≥ 6:真趋势
- 4-5:弱趋势
- ≤ 3:无趋势

**失真提醒**:regime 切换第一周滞后 1-3 天

### 3.8.2 组合因子二:波段位置综合指数(BandPosition,v1.2 只用价格几何)

**问题**:当前波段走到哪个阶段?
**归属**:L2 phase 判定
**单一作用点**:L2 的 phase 输出,不跨层

**v1.2 只用价格几何,移除 MVRV Z 和 STH-SOPR 档位**:

**评分规则**(做多方向,做空对称):

**价格结构项**:
- 最近一轮 impulse 的扩展比率 < 50% → early +3
- 扩展比率 50-100% → mid +3
- 扩展比率 100-138% → late +3
- 扩展比率 > 138% → exhausted +3

**Swing 序列项**:
- 近期 HH+HL 明显 → early/mid +2
- 最近出现 LH 或 LL → late/exhausted +2

**均线距离项**:
- 靠近 MA-60 → early/mid +1
- 远离 MA-60 上方 → late/exhausted +1

**回撤深度项**:
- 最近回撤 > 0.5 impulse → early +1
- 最近回撤 < 0.2 impulse → late/exhausted +1

**输出**:最高得分 phase 标签 + 置信度(得分 / 理论最大)

### 3.8.3 组合因子三:拥挤度指数(Crowding,v1.2 限定 L4)

**问题**:市场情绪是否极端?有反向挤压风险?
**归属**:L4
**单一作用点**:L4 的 risk_score 和 position_cap 修正,**不进 L2,不进 L3 opportunity_grade,无方向反转含义**

**评分规则**(多头拥挤,空头对称):
- 资金费率 > 0.03% 且连续 3 次(24h)→ +2
- 资金费率 30 日分位 > 85 → +2
- OI 24h 变化 > +15% → +1
- 币安大户多空比 > 2.5 → +1
- 基差年化 > 20% → +1
- Put/Call Ratio < 0.5 → +1
- 清算热力图显示上方清算密集 → −1(反向减分)

**输出**:0-8 分
- ≥ 6:极度拥挤(position_cap × 0.7)
- 4-5:偏拥挤(position_cap × 0.85)
- ≤ 3:正常(× 1.0)

### 3.8.4 组合因子四:周期位置综合判断(CyclePosition,v1.2 九档完整化)

**问题**:BTC 处于长周期的哪个位置?
**归属**:L2 long_cycle_context
**单一作用点**:L2 的 long_cycle_context 输出和动态门槛表查询

**九档判定表**(v1.2 对应 M1、M2):

| cycle_position | MVRV Z | NUPL | LTH Supply 90 日变化 | 辅助条件 |
|---|---|---|---|---|
| accumulation | < -0.5 | < 0 | 持续增持(> +2%) | 距上一轮 distribution ≥ 180 天 |
| early_bull | -0.5 ~ 2 | 0 ~ 0.25 | 持续增持或稳定 | 距 accumulation ≥ 60 天 |
| mid_bull | 2 ~ 4 | 0.25 ~ 0.5 | 缓慢减持或稳定 | 无 |
| late_bull | 4 ~ 6 | 0.5 ~ 0.65 | 开始减持 | 无 |
| distribution | > 6 | > 0.65 | 快速减持(< -3%)| 无 |
| early_bear | 2 ~ 6 下行途中 | 0.5 → 0.25 下行 | 持续减持 | 价格已从 ATH 跌 > 20% |
| mid_bear | -0.5 ~ 2 下行 | -0.25 ~ 0.25 | 减持放缓 | 下跌已 > 90 天 |
| late_bear | < -0.5 未企稳 | < -0.25 | 减持放缓或转增持 | 下跌已 > 180 天 |
| unclear | 三指标不一致 | — | — | — |

**判定优先级**(v1.2 对应 B2):

**辅助条件是否决权,不是加权项**。流程:

1. 三主指标各自映射候选档
2. 对每个候选档,检查辅助时间/跌幅条件
3. 通过检查的候选档进入投票池
4. 投票池为空 → unclear + confidence = 0.3(**不允许维持上一次档位,对应 M17**)
5. 投票池非空 → 投票:
   - 三票一致 → 该档 + confidence = 0.85
   - 两票一致 → 该档 + confidence = 0.6
   - 全不一致 → unclear + confidence = 0.3

**last_stable_cycle_position 的处理**:
- 可记录在 evidence_summary 中,供网页展示和复盘
- **不参与当前决策**,不进动态门槛查询

**失真提醒**:减半前后 6 个月各指标基准偏移,此期间 CyclePosition 置信度自动降一档;ETF 时代 MVRV 上限可能偏移,每半年校准一次

### 3.8.5 组合因子五:宏观逆风指数(MacroHeadwind)

**问题**:宏观环境对风险资产是顺风还是逆风?
**归属**:L5
**单一作用点**:L5 的 adjustment_guidance(position_cap_multiplier 和 permission_adjustment)

**评分规则**:
- DXY 20 日变化 > +2% → −2
- US10Y 30 日变化 > +30bp → −2
- VIX > 25 → −2
- 纳指 20 日 < -5% → −2
- 纳指 20 日 > +5% → +2
- BTC-纳指相关性 > 0.7 时,上述项权重 × 1.5

**输出**:−10 到 +10
- ≤ −5:强逆风(position_cap × 0.7)
- −4 ~ −2:轻度逆风(× 0.85)
- ≥ −1:中性或顺风(× 1.0)

### 3.8.6 组合因子六:风险事件密度(EventRisk)

**问题**:未来 72 小时累计事件风险多大?
**归属**:L4
**单一作用点**:L4 的 position_cap 和 execution_permission 修正

**评分规则**:
- 每事件按类型赋分:FOMC=4 / CPI=3 / NFP=3 / 期权大到期=2
- 距离小时数权重:24h 内 × 1.5,24-48h × 1.0,48-72h × 0.5
- 当前波动率 extreme 时所有事件分 +1
- BTC-纳指相关性 > 0.7 时美国经济事件分 +1

**输出**:0-15+ 分
- < 4:低(position_cap × 1.0)
- 4-7:中(position_cap × 0.85)
- ≥ 8:高(position_cap × 0.7,execution_permission 降档建议)

## 3.9 ExchangeMomentum(v1.2 降为 L2 内部修正项)

**归属**:L2 内部修正项(不作为独立组合因子)
**单一作用点**:L2 stance_confidence 的轻度修正(× 1.05 或 × 0.95,不改变方向)

**评分规则**:
- Exchange Net Flow 7 日均 < 0(净流出)→ 偏多 +2
- Exchange Net Flow 30 日均 < 0 → 偏多 +1
- Exchange Balance 整体下降趋势 → 偏多 +1

反向同样计分。

**输出**:−5 到 +5

**应用规则**:
- 方向与 stance 一致 → stance_confidence × 1.05(上限 1.0)
- 方向与 stance 不一致 → stance_confidence × 0.95
- **做空侧不参与 stance_confidence 计算**(v1.2 对应 B5),但保留展示和复盘

## 3.10 明确放弃的噪音项

- ❌ 5 分钟 / 15 分钟级别任何指标
- ❌ 单一 KOL 推特情绪
- ❌ Fear & Greed Index
- ❌ Pi Cycle Top Indicator
- ❌ Rainbow Chart
- ❌ 小币种联动
- ❌ Google 搜索指数
- ❌ Telegram 活跃度
- ❌ GitHub 活跃度
- ❌ 闪电网络容量

## 3.11 数据目录规范

所有数据源、单因子、组合因子必须在 `config/data_catalog.yaml` 中统一注册:

```yaml
sources:
  - name: binance_klines_1h
    platform: binance
    endpoint: /api/v3/klines
    params: { symbol: BTCUSDT, interval: 1h }
    frequency: hourly
    timeout_sec: 10
    retry: 3
    via_proxy: true

single_factors:
  - name: mvrv_z_score
    depends_on: [glassnode_mvrv_z_score]
    formula_ref: indicators/onchain.py::read_glassnode_direct
    frequency: daily
    layer: L2
    role_in_v1: primary  # primary / display / delayed

composite_factors:
  - name: cycle_position
    depends_on: [mvrv_z_score, nupl, lth_supply_90d_change, ath_drawdown]
    formula_ref: composite/cycle_position.py::compute
    layer: L2
    single_use_point: l2_long_cycle_context
```

## 3.12 缓存与采集策略

- 日级指标(Glassnode 绝大多数):每天一次 + 本地 DB
- 小时级:每次运行前检查最新一小时是否已有,增量抓取
- 4 小时级:每次运行抓最新
- 宏观:每天一次
- 事件日历:每天一次

**硬规则**:任何 API 一次运行最多调一次,读缓存优先。

---

# 第四部分:证据层详细建模

## 4.1 EvidenceReport 通用结构

所有五层的输出遵循同一基础结构。

**基础元信息**:
- layer_id(integer,1-5)
- layer_name(string)
- generated_at_bjt(string)
- computation_method(enum:rule_based / ai_assisted / ai_primary / hybrid)

**健康状态**:
- health_status(enum:healthy / degraded / insufficient_data / error)
- degraded_reasons(list)
- **data_freshness**(dict,v1.2 新增):每个关键数据点的新鲜度

**核心结论**:
- verdict(string)
- verdict_enum(enum)
- confidence(number,0.0-1.0)
- confidence_tier(enum:high ≥ 0.75 / medium 0.5-0.75 / low 0.3-0.5 / very_low < 0.3)

**证据支撑**:
- key_signals(list)
- contradicting_signals(list)

**对主策略的贡献**:
- contribution(supportive / neutral / challenging / blocking)
- contribution_note(string)

**可解释性**:
- human_readable_summary(2-3 句)
- detail_reference(证据卡 ID 或文档路径)

**生命周期**:
- valid_until_bjt
- trigger_conditions

**层级专属字段**:
- layer_specific(各层扩展)

## 4.2 第 1 层:市场状态层

### 4.2.1 核心命题
当前市场性格是什么?趋势性还是震荡性,稳定还是动荡?

### 4.2.2 判断三支柱

**支柱一:趋势强度**
- 主指标:ADX-14(1D)
- > 25:有效趋势;< 20:无明显趋势;20-25:过渡

**支柱二:结构一致性**
- 4H / 1D / 1W 三周期方向
- 一致 = 稳定;不一致 = 过渡期

**支柱三:波动率体制**
- ATR/Price 比率在过去 180 天的分位
- < 30:低;30-60:正常;60-85:偏高;> 85:极端

### 4.2.3 判断纪律

1. 三支柱共振才给高置信度
2. regime 判断要有粘性:新 regime 需连续 2-3 次输出一致才正式切换
3. 不确定时倾向 transition,不倾向 trend
4. volatility extreme 时强制 chaos

### 4.2.4 专属字段

| 字段 | 枚举 / 类型 |
|---|---|
| regime_primary | trend_up / trend_down / range_high / range_mid / range_low / transition_up / transition_down / chaos |
| regime_stability | stable / slightly_shifting / actively_shifting / unstable |
| regime_duration_days | number |
| volatility_level | low / normal / elevated / extreme |
| volatility_percentile | number 0-100 |
| trend_strength | 0.0-1.0 |
| trend_direction | up / down / flat |
| structure_coherence | 0.0-1.0 |
| timeframe_alignment | { tf_4h, tf_1d, tf_1w, aligned } |
| environmental_flags | { is_trending, is_ranging, trust_breakouts, trust_mean_reversion } |
| truth_trend_score | 0-9(来自 TruthTrend,L1 内部使用) |

### 4.2.5 v0.1 参数初始值

| 参数 | 初始值 | 校准方向 |
|---|---|---|
| ADX 强趋势阈值 | 25 | 震荡误判多则上调至 28 |
| ADX 弱趋势阈值 | 20 | 漏掉早期趋势则下调至 18 |
| ATR 分位 low | 30 | 较少调整 |
| ATR 分位 elevated | 60 | 较少调整 |
| ATR 分位 extreme | 85 | 相对合理 |
| regime 切换最少连续次数 | 3 | 反应太慢降至 2 |
| swing 识别窗口 | 5 | 太短噪音多,太长迟钝 |

## 4.3 第 2 层:方向与结构层

### 4.3.1 核心命题
方向偏哪边?阶段在哪?

### 4.3.2 判断三支柱

**支柱一:结构序列** — HH + HL(多)vs LH + LL(空),比均线更基础

**支柱二:相对位置** — 扩展比率,< 50% early / 50-100% mid / 100-138% late / > 138% exhausted

**支柱三:长周期背景** — 来自 CyclePosition,影响 phase 置信度,不直接改 stance

### 4.3.3 判断纪律

1. 结构优于指标
2. phase 承认不确定性,exhausted 谨慎给
3. neutral 是合法输出
4. 长周期只修正置信度,不直接改 stance

### 4.3.4 专属字段

| 字段 | 枚举 / 类型 |
|---|---|
| stance | bullish / bearish / neutral |
| stance_confidence | 0.0-1.0(**仅供动态门槛比较的内部量**,v1.2 对应 M18) |
| stance_strength | strong / moderate / weak |
| phase | early / mid / late / exhausted / unclear / n_a |
| phase_evidence | string |
| structure_features | { hh_count, hl_count, lh_count, ll_count, latest_structure } |
| key_levels | { nearest_support, nearest_resistance, major_support, major_resistance, current_position } |
| trend_position | { estimated_pct_of_move, estimation_basis, reliability } |
| long_cycle_context | { cycle_position, cycle_confidence, data_basis, last_stable_cycle_position(展示用,不参与决策)} |
| band_position_score | 来自 BandPosition,L2 内部使用 |
| exchange_momentum_score | 来自 ExchangeMomentum 降级项,L2 内部使用 |

### 4.3.5 stance_confidence 字段定性(v1.2 对应 M18)

**纪律**:
- 此字段**仅**用于与 active_direction_thresholds 比较以决定是否允许方向迁移
- **不代表系统的整体置信度**
- 外部展示用 `ai_verdict.confidence_breakdown.overall`(overall_confidence),不用 stance_confidence
- 混用是反模式

### 4.3.6 做多做空门槛动态表

| cycle_position | 多头门槛 | 空头门槛 |
|---|---|---|
| early_bull | 0.55 | 0.75 |
| mid_bull | 0.60 | 0.70 |
| late_bull | 0.65 | 0.65 |
| distribution | 0.70 | 0.60 |
| early_bear | 0.75 | 0.55 |
| mid_bear | 0.75 | 0.55 |
| late_bear | 0.65 | 0.65 |
| accumulation | 0.60 | 0.70 |
| **unclear** | **0.65** | **0.70** |

- 硬地板 0.55,硬天花板 0.75
- cycle_position 切换后门槛延迟 7 天完全生效,过渡期插值
- **注意**:无"空头门槛总高于多头"的断言,完全按此表

## 4.4 第 3 层:机会与执行层(v1.2 重写为纯规则判档)

### 4.4.1 核心命题
现在是不是好的动手时机?怎么动手?

### 4.4.2 L3 定位(v1.2 对应 M16)

**L3 是纯规则判档层**。

**反模式清单(明确禁止)**:
- ❌ 不写"L3 加权评估"
- ❌ 不写"L3 综合置信度"
- ❌ 不写"L3 考虑多因素后输出"
- ✅ 只写"L3 按规则表输出"

**L3 的实现必须是查找表 + 硬条件函数,不含任何 `score += X` 式的加分逻辑。**
**L3 的任何修订必须通过修改查找表完成,不允许在代码中引入新的加权计算。**

### 4.4.3 L3 读取层级结论(v1.2 对应 B1)

L3 读取的是**L1/L2 的最终结论**(regime、stance、phase、confidence 这些字段),**不读取 TruthTrend / BandPosition 原始分数**。

- TruthTrend 在 L1 内部用完就用完,不跨层传递
- BandPosition 在 L2 内部决定 phase,L3 只读 phase,不读原始得分

### 4.4.4 opportunity_grade 判定规则表(做多)

| 条件组合 | opportunity_grade |
|---|---|
| regime ∈ {trend_up, transition_up} AND stance=bullish (conf ≥ 动态门槛) AND phase ∈ {early, mid} AND 位置 ∈ {near_support, mid_range} | **A** |
| regime 同上 AND stance=bullish (conf ≥ 动态门槛) AND phase ∈ {early, mid, late} AND 位置 ≠ above_all_key_levels | **B** |
| regime 同上 AND stance=bullish (conf ≥ 动态门槛) AND phase = late AND 位置 ∈ {near_resistance} | **C** |
| 其他所有情况 | **none** |

### 4.4.5 opportunity_grade 判定规则表(做空,v1.2 简化,对应 M3 + B3)

**v1 空头只允许 A / B / none 三档,不允许 C**。

**空头 A 级条件(同时满足)**:
- CyclePosition ∈ {distribution, early_bear, mid_bear}
- L2 stance = bearish,confidence ≥ 动态门槛
- L1 regime ∈ {trend_down, transition_down, range_high}
- 位置 near_resistance 或 above_all_key_levels
- Crowding 的 crowded_long ≥ 6
- **且** TruthTrend ≥ 6 方向下行

**空头 B 级条件**:上述条件满足但 TruthTrend 在 4-5 之间

**其他情况**:none

### 4.4.6 opportunity_grade 单一来源(v1.2 对应问题 6 的三重封闭)

- **L3 规则映射表是 opportunity_grade 的唯一产出点**
- L4 / L5 / AI 裁决 / Fallback 规则均不可修改 opportunity_grade
- AI 输出的 `main_strategy.opportunity_grade` 必须严格等于 L3 的输出值,程序校验拒绝不一致

### 4.4.7 入场确认规则

- 价格进入 entry_zone 后,必须等该 zone 对应的 **1H K 线收盘**确认成交
- 硬失效位:默认需要 **4H 收盘**确认;1H 级别已明显击穿(偏离 > 1%)时标记"预警触发"但不自动执行
- 早期失败保护(持仓 < 24h):1H 级别反向信号可提前触发

### 4.4.8 1H 数据访问边界(v1.2 对应问题 2 和 P5)

**允许读取 1H 的模块**:
- `src/data/collectors/binance.py`(采集)
- `src/evidence/layer3_opportunity.py` 的**入场确认函数**
- `src/evidence/layer4_risk.py` 的**硬失效预警函数**
- `src/scheduler/event_listener.py`(事件触发监听)
- `src/strategy/lifecycle_manager.py` 的**早期失败保护函数**(仅 OPEN 阶段)

**禁止读取 1H 的模块**:
- `src/evidence/layer1_regime.py` 所有函数
- `src/evidence/layer2_direction.py` 所有函数
- 所有组合因子(`src/composite/`)
- `src/decision/adjudicator_ai.py`(AI 输入的 evidence_summary 不含 1H 衍生指标;1H 只能以"事实陈述"形式出现,如"entry_zone 已 1H 收盘确认")
- `src/decision/adjudicator_fallback.py`(Fallback 判定不引用 1H)

**强制方式**:
- 禁止模块的函数签名显式不接受 1H 参数
- 数据加载函数设白名单(module_id 不在白名单抛异常)
- 代码库加 linter 规则,grep 禁止字符串(`interval="1h"` / `_1h` / `TIMEFRAME_1H`)

### 4.4.9 专属字段

| 字段 | 类型 |
|---|---|
| opportunity_grade | A / B / C / none |
| opportunity_reason | string |
| execution_permission | 初步建议,最终归并后见 4.5.6 |
| suggested_entry_plan | struct 或 null |
| risk_reward | { estimated_target, estimated_stop, rr_ratio, win_rate_estimate } |
| timing_assessment | { momentum_phase, is_extended, needs_pullback, pullback_depth_estimate } |
| liquidity_context | { nearby_long_liq, nearby_short_liq, liquidity_imbalance } |
| entry_confirmation_timeframe | 默认 "1h" |

### 4.4.10 v0.1 参数初始值

| 参数 | 初始值 |
|---|---|
| 仓位分层权重(3 档) | 30 / 40 / 30 |
| entry_zone 最深档位回撤幅度 | 0.5(斐波那契) |
| 入场确认周期 | 1H |
| 硬失效确认周期 | 4H |
| 硬失效提前预警偏离阈值 | 1% |

## 4.5 第 4 层:风险与失效层

### 4.5.1 核心命题
判断在什么条件下失效?有哪些风险?

### 4.5.2 判断三角度

**角度一:结构性失效位** — 多头失效位 = 最近主要 HL 下方;空头反之。硬失效。

**角度二:衍生品拥挤度** — 由 Crowding 输出

**角度三:事件窗口** — 由 EventRisk 输出,事件窗口前 48 小时生效

### 4.5.3 判断纪律

1. 硬失效位一票否决,无条件触发
2. 风险标签是乘数,不是开关
3. 事件窗口前 48h 生效
4. "没风险"要谨慎,默认至少 moderate

### 4.5.4 hard_invalidation_levels 的唯一权威(v1.2 对应 P4 和问题 1)

**唯一权威来源**:L4 的 `hard_invalidation_levels`

**与 trade_plan.stop_loss 的关系**:
- trade_plan.stop_loss 是 L4 hard_invalidation_levels 的**表层复制**
- AI 裁决在生成 trade_plan 时,必须从 L4 给出的价位中选一个作为 stop_loss
- AI 不得凭空另设 stop_loss,不得修改 L4 给出的价位

**不一致时**:**按 L4 hard_invalidation_levels 执行**。若 trade_plan.stop_loss 与 L4 不一致,程序校验拒绝,启用 Fallback Level 1。

### 4.5.5 position_cap 串行合成机制(v1.2 对应 M19)

**合成顺序(固定,不可换)**:

```
step 1:基础 position_cap = 70%(可配置)
step 2:× L4_overall_risk_level_multiplier
        (low=1.0 / moderate=0.9 / elevated=0.7 / high=0.5 / critical=0.3)
step 3:× L4_crowding_multiplier
        (Crowding ≤ 3: 1.0 / Crowding 4-5: 0.85 / Crowding ≥ 6: 0.7)
step 4:× L5_macro_headwind_multiplier
        (MacroHeadwind ≥ -1: 1.0 / -4 ~ -2: 0.85 / ≤ -5: 0.7)
step 5:× L4_event_risk_multiplier
        (EventRisk < 4: 1.0 / 4-7: 0.85 / ≥ 8: 0.7)
```

**全局硬下限 15%**:

```
final_position_cap = max(基础 × 各乘数累乘, HARD_FLOOR = 15%)
```

**例外**:L4 overall_risk_level = critical 时,final_position_cap 可低于 15%,甚至为 0。非 critical 时绝不低于 15%。

**硬下限的适用范围(v1.2 对应问题 4)**:
- 仅当 `final_permission ∈ {can_open, cautious_open, ambush_only}` 时生效
- `final_permission = no_chase`:保留计算值
- `final_permission = hold_only`:仅约束新开仓,对已持仓无约束
- `final_permission ∈ {watch, protective}`:不抬升

**审计字段 `position_cap_composition`**:

```yaml
position_cap_composition:
  base: 70
  after_l4_risk: 49
  after_l4_crowding: 41.65
  after_l5_macro: 35.40
  after_l4_event: 30.09
  hard_floor_applied_to_final: false
  final: 30
```

### 4.5.6 execution_permission 归并规则(v1.2 对应 M20)

**每个因子产出建议档位,不直接修改主 permission**:

**L4 overall_risk_level 建议**:
- critical → protective
- high → watch
- elevated → ambush_only
- moderate → cautious_open
- low → can_open

**L4 Crowding 建议**:
- ≥ 6 → cautious_open(至多)
- ≤ 5 → can_open

**L4 EventRisk 建议**:
- ≥ 8 → ambush_only
- 4-7 → cautious_open
- < 4 → can_open

**L5 MacroHeadwind 建议**:
- ≤ -5 → ambush_only
- -4 ~ -2 → cautious_open
- ≥ -1 → can_open

**归并规则**:`final_permission = 所有建议中的最严档位`

**A 级缓冲**:
- 若 opportunity_grade = A 且 regime 稳定(regime ∈ {trend_up, trend_down} 且 regime_stability ∈ {stable, slightly_shifting})
- 最终 permission 不得严于 **cautious_open**
- 即归并结果更严时,抬升到 cautious_open

**A 级缓冲的例外(v1.2 对应问题 3)**:以下硬状态不受 A 级缓冲覆盖:
- PROTECTION 态:强制 protective
- L5 extreme_event_detected = true:强制 PROTECTION 流程
- L4 overall_risk_level = critical:强制 protective
- L1 regime = chaos:强制 watch

**L1 volatility_regime = extreme**(仍走标准归并,A 级缓冲在此时仍适用)

**审计字段 `permission_composition`**:每个因子的建议值都写入。

### 4.5.7 专属字段

| 字段 | 类型 |
|---|---|
| overall_risk_level | low / moderate / elevated / high / critical |
| hard_invalidation_levels | list,每条含 price / direction / basis / priority / confirmation_timeframe |
| active_risk_tags | list |
| event_windows | list |
| worst_case_estimate | { drawdown_scenario, estimated_drawdown_pct, probability_hint } |
| recommended_position_cap_pct | number |
| position_cap_composition | 见 4.5.5 |
| permission_composition | 见 4.5.6 |
| crowding_score | 来自 Crowding |
| event_risk_score | 来自 EventRisk |

### 4.5.8 v0.1 参数初始值

| 参数 | 初始值 |
|---|---|
| 基础 position_cap_pct | 70 |
| 资金费率告警阈值 | 0.03% 连续 3 次 |
| 资金费率 30 日分位告警 | > 85 |
| OI 24h 告警 | > 15% |
| 多空比告警 | > 2.5 |
| 事件窗口开始影响(小时) | 48 |

### 4.5.9 风险标签类型

funding_extreme / oi_spike / crowded_long / crowded_short / liquidity_thin / correlation_break / leverage_stretched / volatility_regime_shift / structural_divergence

## 4.6 第 5 层:背景与事件层

### 4.6.1 核心命题
宏观与外部事件对当前 BTC 判断是加分、减分还是不确定?

### 4.6.2 四类数据处理

1. 结构化宏观指标(程序抓):DXY / US10Y / VIX / 股指 → MacroHeadwind
2. 结构化事件日历(程序抓,手动维护):FOMC / CPI / 非农 → EventRisk
3. 定性事件摘要(AI 加工):声明鹰鸽、地缘、监管、黑天鹅(v0.5 启用)
4. 极端事件检测:触发进入 PROTECTION

### 4.6.3 判断纪律

1. 只修正,不主导
2. 仅 extreme_event_detected=true 时能临时接管
3. 多项共振才触发标签
4. AI 置信度 < 0.6 时影响力自动降级

### 4.6.4 专属字段

| 字段 | 类型 |
|---|---|
| macro_stance | risk_on / risk_neutral / risk_off / extreme_risk_off |
| macro_trend | improving / stable / deteriorating / volatile |
| structured_macro | { DXY, US10Y, VIX, sp500, nasdaq, ... } |
| active_macro_tags | list |
| active_event_summaries | list(AI 生成) |
| extreme_event_detected | bool |
| extreme_event_details | struct 或 null |
| adjustment_guidance | { stance_modifier, position_cap_multiplier, permission_adjustment, note } |
| macro_headwind_score | 来自 MacroHeadwind |

### 4.6.5 v0.1 参数初始值

| 参数 | 初始值 |
|---|---|
| DXY 20 日变化阈值 | ±2% |
| US10Y 30 日变化阈值 | ±30bp |
| VIX elevated | 25 |
| VIX extreme | 35 |
| BTC-纳指相关性强联动阈值 | 0.7 |
| 极端事件 BTC 单日波动阈值 | ±15% |
| AI 事件摘要置信度降级线 | 0.6 |

## 4.7 Observation Classifier(v1.2 新增,对应 M28)

### 4.7.1 定位

**由规则层产出**,不由 AI 产出。位置在 L3 证据层输出之后、AI 裁决之前,作为独立模块 `src/strategy/observation_classifier.py::classify`。

### 4.7.2 输出字段

`observation_category`:
- disciplined:证据明确不利于开仓
- watchful:证据有正面但不足以开仓
- possibly_suppressed:多项正面证据存在但叠加后仍无机会

### 4.7.3 判定规则

**`disciplined`** — 任一成立即触发:
- L1 regime ∈ {chaos, transition_up, transition_down}
- L1 volatility_regime = extreme
- L2 stance = neutral
- L2 CyclePosition = unclear
- L4 overall_risk_level ∈ {high, critical}
- L5 macro_stance = extreme_risk_off
- PROTECTION 态或 POST_PROTECTION_REASSESS 态

**`watchful`** — 同时满足:
- 不满足 disciplined 条件
- L1 regime ∈ {trend_up, trend_down, range_*} 至少一个
- L2 stance ∈ {bullish, bearish}(非 neutral)
- L3 opportunity_grade ∈ {C, none}
- L4 overall_risk_level ∈ {low, moderate, elevated}

**`possibly_suppressed`** — 同时满足:
- 不满足 disciplined 条件
- L1 regime ∈ {trend_up, trend_down}
- L1 regime_confidence ≥ 0.7
- L2 stance_confidence ≥ 动态门槛
- L2 CyclePosition 非 unclear
- L3 opportunity_grade = none
- **持续状态**:以上条件已连续成立 ≥ 7 天(42 次运行)

### 4.7.4 纪律(只读、只展示、只告警)

- **不能进入**:任何层的证据判定逻辑、组合因子计算、position_cap 合成、permission 归并、状态机迁移规则、L3 规则表、Fallback 规则
- **AI 裁决**:只读,不因此调整自己的行为。即 possibly_suppressed 时 AI 依然按正常标准评估,不"因为系统疑似保守就激进一点"
- **纪律条款**:observation_category 是系统自我观察的产物,不是系统自我调节的依据。任何试图让其进入决策路径的代码实现都是违反建模的行为

### 4.7.5 告警触发

- possibly_suppressed 连续 ≥ 14 天 → warning 级告警
- possibly_suppressed 连续 ≥ 30 天 → critical 级告警
- 冷启动期间(系统运行不足 7 天)可输出 `cold_start_warming_up` 作为第四个临时标签

---

# 第五部分:状态机与生命周期(14 状态)

## 5.1 状态定义

| 状态 | 含义 |
|---|---|
| FLAT | 空仓观望,默认态 |
| LONG_PLANNED | 多头计划中,挂单埋伏 |
| LONG_OPEN | 多头已开仓(观察期) |
| LONG_HOLD | 多头稳定持有 |
| LONG_TRIM | 多头分批减仓 |
| LONG_EXIT | 多头完全离场 |
| SHORT_PLANNED | 空头计划中 |
| SHORT_OPEN | 空头已开仓(观察期) |
| SHORT_HOLD | 空头稳定持有 |
| SHORT_TRIM | 空头分批减仓 |
| SHORT_EXIT | 空头完全离场 |
| FLIP_WATCH | 反手观察期 |
| PROTECTION | 保护态 |
| POST_PROTECTION_REASSESS | 保护态退出后的重评期 |

## 5.2 核心迁移规则

### FLAT → LONG_PLANNED

全部满足:
- L1 regime ∈ {trend_up, transition_up, range_low}
- L2 stance = bullish,stance_confidence ≥ 动态门槛
- L3 opportunity_grade ∈ {A, B}
- L3 execution_permission ∈ {can_open, cautious_open, ambush_only}
- L4 无 critical 风险
- L5 macro_stance ≠ extreme_risk_off
- 非 protection_mode

### FLAT → SHORT_PLANNED(镜像,门槛动态,v1.2 简化)

空头只在 A / B 级别下迁移,门槛按动态表。

### LONG_PLANNED → LONG_OPEN

条件:trade_plan 至少一个 entry_zone 经 **1H 收盘**确认成交

### LONG_OPEN → LONG_HOLD(v1.2 采用时间+走势组合)

**时间条件**:持仓满 24 小时(保底)
**且 走势条件至少满足其一**:
- 浮盈 ≥ +2%
- 已穿越开仓后第一个 4H 收盘且方向未反转
- 已度过至少一次回撤-反弹小周期

**或**:价格已达 take_profit 第一档的 50% 距离

lifecycle 记录四个 bool:open_phase_min_time_reached、open_phase_pnl_confirmed、open_phase_structure_confirmed、open_phase_pullback_survived

### LONG_OPEN → LONG_EXIT(早期失败保护)

任一触发:
- 跌破 hard_invalidation_level(4H 收盘确认;1H 提前预警)
- 浮亏达到预设止损
- 开仓后 12 小时内 L2 stance 翻转且 confidence ≥ 0.7
- L4 出现新 critical 风险
- thesis_still_valid = invalidated

### LONG_HOLD → LONG_TRIM

任一:
- 达到 take_profit 档 target_price
- AI 判断 phase 进入 late 且 confidence ≥ 0.65
- L1 regime 从 trend_up 过渡到 transition_down 或 range_high
- thesis_still_valid 降至 partially_valid / weakened
- L5 macro_stance 转为 risk_off 或更严重

### LONG_TRIM 后续

- → LONG_HOLD:完成当前减仓,剩余继续
- → LONG_TRIM:下一档止盈
- → LONG_EXIT:最后一档或衰竭进一步强化

### LONG_EXIT → FLIP_WATCH

全部满足:
- 所有仓位已平
- L2 初步偏空迹象
- L1 regime ∈ {transition_down, trend_down, range_high}

进入时启动 FLIP_WATCH 动态冷却(见 5.3)

### LONG_EXIT → FLAT

平仓完毕但无反手条件

### FLIP_WATCH → SHORT_PLANNED(高门槛)

- 已超过 effective_min_hours
- L2 stance = bearish,stance_confidence ≥ 空头动态门槛
- 原多头论点已明确失效
- L3 opportunity_grade ∈ {A, B}

### FLIP_WATCH → FLAT

- 超过 effective_max_hours
- L2 stance 回到 bullish 或明确 neutral
- L1 regime 转回 trend_up

### PROTECTION 的进出

- 任何状态 → PROTECTION:极端事件,程序自动
- PROTECTION → POST_PROTECTION_REASSESS:事件结束 + 数据健康 + 无新极端风险

### POST_PROTECTION_REASSESS

- 强制持续至少一个 4H 周期
- execution_permission 固定 hold_only
- 允许迁移到:LONG_HOLD / SHORT_HOLD / LONG_EXIT / SHORT_EXIT / FLAT / FLIP_WATCH
- 禁止迁移到任何 PLANNED 状态(必须先 FLAT 重新规划)
- 禁止直接回到 PROTECTION(复发走正常流程)

## 5.3 FLIP_WATCH 动态冷却(v1.2 轻动态,对应 M14)

**基础**:min 18h / max 96h(可配置)

**动态乘数**(v1.2 删除 previous outcome_type 影响):
- cycle_position ∈ {late_bull, distribution, late_bear, accumulation}:× 0.7
- cycle_position ∈ {mid_bull, mid_bear}:× 1.3
- volatility_regime = extreme:× 1.3
- volatility_regime = low:× 0.8

**硬界限**:
- effective_min = max(8h, 18 × 乘数累乘)
- effective_max = min(168h, 96 × 乘数累乘)

**进入 FLIP_WATCH 时计算并锁定,周期内不变**

**复盘纪律**:复盘发现 FLIP_WATCH 冷却设置不合理由人工决定调参,不自动反哺状态机参数

## 5.4 三条核心纪律

1. 不允许从 *_HOLD 直接跳到反向 PLANNED,必须经 EXIT → FLIP_WATCH 完整路径
2. FLIP_WATCH 冷却期强制;**1H 信号永远不能单独触发方向切换**
3. PROTECTION 全局入口,唯一出口经 POST_PROTECTION_REASSESS

## 5.5 状态进入副作用(on_enter)

| 状态 | 副作用 |
|---|---|
| FLAT | 清空 current_lifecycle(归档);重置 position_cap;清除所有挂单;记日志 |
| *_PLANNED | 创建 lifecycle 草稿;记 origin_thesis;设 planned_expiry;推送通知 |
| *_OPEN | lifecycle 从 pending 转 active;记 origin_time;开启"初期保护模式";推送通知 |
| *_HOLD | 关闭"初期保护";启用"常规监控";初始化 max_favorable_pct / max_adverse_pct |
| *_TRIM | 记 position_adjustments;更新 stage=partial_trimmed;更新剩余止损止盈 |
| *_EXIT | 记 position_adjustments;准备 lifecycle 归档;记离场原因 |
| FLIP_WATCH | 归档上一 lifecycle;记 flip_watch_start_time;计算并锁定 effective_min/max;重置仓位 |
| PROTECTION | 记 protection_entry_time / reason;冻结开仓;按 AI 处理残留;推送紧急通知;触发人工确认 |
| POST_PROTECTION_REASSESS | 记 reassess_entry_time;保留 lifecycle(不归档);强制 hold_only |

## 5.6 主判断周期与辅助周期

**主判断周期**:4H / 1D / 1W(L1、L2、L3 主逻辑只读这三个)

**辅助周期**:1H(仅用于执行确认、硬失效提前预警、早期失败保护、事件触发运行输入)

**硬规则**:1H 信号永远不能单独改变 stance / phase / regime,不能单独触发方向切换。**函数签名强制限制 1H 数据的可访问性**(见 4.4.8)。

---

# 第六部分:AI 裁决契约与 Prompt 终稿

## 6.1 AI 裁决定位

AI 裁决官:读取五层证据,在当前状态和合法迁移选项内做决策,输出结构化结果。

介入两个点:
- 第 5 层宏观摘要(v0.5 后)
- 最终裁决(v0.5 后)

v0.1-v0.4 用 Fallback 规则。

## 6.2 AI 裁决输入契约

```
AIAdjudicatorInput {
  current_state              : enum
  allowed_transitions        : list
  market_snapshot            : struct
  evidence_summary           : struct  (五层摘要)
  evidence_cards_summary     : list    (摘要版,v1.2 对应 M31)
  observation_category       : enum    (v1.2 新增)
  current_lifecycle          : struct 或 null
  recent_runs                : list    (最近 3-5 次运行浓缩)
  data_freshness             : struct  (v1.2 新增,显示哪些数据 stale)
  constraints {
    must_stay_within_transitions : bool (true)
    max_position_cap_pct         : number
    position_cap_composition     : struct (可审计)
    hard_invalidation_levels     : list
    protection_mode_active       : bool
    flip_watch_effective_min_hours : number
    flip_watch_effective_max_hours : number
    active_direction_thresholds  : { long, short }
    l3_opportunity_grade         : enum (必须原样引用,不可修改)
  }
  required_outputs             : list
}
```

## 6.3 AI 裁决输出契约

```
AIAdjudicatorOutput {
  chosen_action_state       : enum   (必须在 allowed_transitions)
  stance                    : enum
  stance_confidence         : number
  phase                     : enum
  phase_confidence          : number
  opportunity_grade         : enum   (必须等于 L3 输出,不可修改)
  execution_permission      : enum   (最终值,归并后)
  trade_plan                : struct 或 null
  thesis_assessment         : struct 或 null
  holding_guidance          : string 或 null
  narrative                 : string (3-5 句)
  one_line_summary          : string
  primary_drivers           : list
  counter_arguments         : list
  what_would_change_mind    : list   (至少 3 条)
  confidence_breakdown      : struct
  transition_reason         : string
  self_check {
    stayed_within_allowed_transitions : bool
    respects_position_cap             : bool
    all_evidence_refs_valid           : bool
    no_invented_data                  : bool
    opportunity_grade_matches_l3      : bool  (v1.2 新增)
    stop_loss_matches_l4              : bool  (v1.2 新增)
  }
}
```

## 6.4 程序校验规则

任一失败即启用对应级别 Fallback:

1. chosen_action_state 必须在 allowed_transitions
2. trade_plan 总仓位 ≤ constraints.max_position_cap_pct
3. 做多止损低于入场下沿,做空反之
4. primary_drivers.evidence_ref 指向的 card_id 真实存在
5. self_check 任一 false 则拒绝
6. what_would_change_mind 至少 3 条
7. protection_mode_active=true 时,chosen_action_state 必须合法
8. **opportunity_grade 必须等于 L3 输出**(v1.2 新增)
9. **trade_plan.stop_loss 必须在 L4 hard_invalidation_levels 中**(v1.2 新增)

## 6.5 AI 裁决 System Prompt 终稿(v1.2)

```
================================================================
SYSTEM PROMPT - BTC 策略裁决官
================================================================

你是一个 BTC 中长线低频双向波段交易系统的"裁决官"。
你的唯一工作是:读取程序提供的五层证据,在当前状态和合法迁移
选项内做出下一步策略决策,并输出严格结构化的 JSON。

═══ 十条纪律(不可违反)═══

1. 你只能在 allowed_transitions 列表中选择下一个状态。
   发明列表外的状态 = 无效输出 = 系统启用 Fallback。

2. 你只能引用 evidence_cards 中实际存在的 card_id。
   编造或推断证据 = 无效输出。

3. 你的仓位建议不得超过 constraints.max_position_cap_pct。
   超过 = 无效输出。

4. 做多的 stop_loss 必须低于入场区间下沿;做空反之。
   stop_loss 必须选自 constraints.hard_invalidation_levels,
   不得另设或修改。

5. 若当前 lifecycle 存在 origin_thesis,你必须对
   thesis_still_valid 做出明确评估,不得回避。

6. 你必须在 what_would_change_mind 中列出至少 3 个可检测、
   可客观判断的条件。模糊条件(如"市场变化")= 不合格。

7. 证据严重冲突或不足时,选择保守状态(保持当前或 FLAT)。
   不得强行给出高置信度结论。

8. 输出必须是严格 JSON,不得包含任何 JSON 之外的文字、
   注释、解释、前后缀。你的回复第一个字符必须是 {。

9. 前面各层已经通过 position_cap 和 permission 机制完成风险收紧。
   你不得在此基础上再独立降低 execution_permission 或 opportunity_grade。
   你的角色是:在给定的证据集合中,选择最合适的 action_state 和 trade_plan。
   过度保守是一种失职,和过度激进同样不可接受。

10. 你会收到两个特殊字段:
    - activity_state 或 observation_category:当前系统观察分类
    - opportunity_grade:来自 L3 的判档结果
    
    纪律:
    - opportunity_grade 必须原样引用,不得修改
    - observation_category = possibly_suppressed 时:
      在 narrative 中必须明确提及系统已长期观望
      在 what_would_change_mind 中至少有 1 条是"什么条件会结束当前抑制状态"
    - observation_category 的存在,不是你激进或保守的理由
      你仍按正常标准评估机会

═══ 核心决策原则 ═══

• 本系统是低频中长线波段,不是短线择时。
  "没有高确定性机会时保持观望"永远是合法且常常正确的选择。

• "方向对但位置不对"时,选择 ambush_only 或 no_chase,
  绝不强行开仓追涨杀跌。

• 已持仓时,首要问题是"原始 thesis 是否还成立",
  其次才是"要不要动仓位"。顺序不能颠倒。

• 不要被短期剧烈波动引诱做反手。
  反手必须经过 EXIT → FLIP_WATCH 的完整冷却。

• L4 hard_invalidation 触发时,无条件执行平仓,不辩解。

• L5 是修正层,不是主导层。
  只能调整乘数、调整 execution_permission、压低 opportunity_grade,
  不能单独把 bullish 改成 bearish(除非 extreme_event_detected=true)。

• 1H 时间框架的信号不能单独改变 stance / phase / regime。
  决策的锚永远是 4H / 1D / 1W。

• 做多做空门槛不对称。具体门槛见 constraints.active_direction_thresholds,
  严格按此数值执行。

═══ 身份定位 ═══

你不是"预测大师",你是"纪律执行官"。
优雅地错过机会,好于鲁莽地制造亏损;
但长期不给策略,也不是纪律性,是失灵。
平衡的关键在于:严格按证据和规则,不多不少。

═══ 输出格式 ═══

严格遵循 AIAdjudicatorOutput schema。第一个字符 `{`,
最后一个字符 `}`。不要 markdown code block,不要任何说明文字。
```

## 6.6 AI 裁决 User Prompt 模板

```
[本次运行上下文]
当前时间: {generated_at_bjt} (BJT)
参考时间戳: {reference_timestamp_utc} (UTC)
BTC 价格: ${btc_price_usd}
当前系统状态: {current_state}
本次运行触发源: {run_trigger}
合法迁移选项: {allowed_transitions}
观察类别: {observation_category}

[数据新鲜度]
{data_freshness_summary}

[系统约束]
最大仓位上限: {max_position_cap_pct}%
仓位合成过程: {position_cap_composition}
硬失效位:
{hard_invalidation_levels_formatted}
保护态是否激活: {protection_mode_active}
FLIP_WATCH 冷却范围: {flip_watch_effective_min_hours}-{flip_watch_effective_max_hours} 小时
当前多空门槛: 多头 {active_direction_thresholds.long} / 空头 {active_direction_thresholds.short}
L3 判档结果: {l3_opportunity_grade}  ← 不可修改,必须原样引用

[当前生命周期]
{current_lifecycle_json or "无"}

[五层证据报告]

L1 市场状态:
{layer1_report_json}

L2 方向结构:
{layer2_report_json}

L3 机会执行:
{layer3_report_json}

L4 风险失效:
{layer4_report_json}

L5 背景事件:
{layer5_report_json}

[证据卡摘要 ID 清单]
可供 primary_drivers 引用的 card_id(共 {N} 张):
{evidence_cards_summary_list}

[最近 3 次运行的浓缩历史]
{recent_runs_digest}

═══ 请按 AIAdjudicatorOutput schema 输出你的裁决 ═══
仅输出 JSON,第一个字符必须是 {。
```

## 6.7 evidence_cards 规范(v1.2 对应 M31)

**card_id 命名规则**:`{category}_{metric_name}_{bjt_date}`,例如 `onchain_mvrv_z_20260421`

**一次运行产出上限**:50 张

**AI 输入版本**:使用**摘要版**(只含 name、current_value、one_line_interpretation),不含完整 analysis

**完整 analysis**:存数据库,网页点击卡片查询读取

## 6.8 第 5 层宏观摘要 AI Prompt 终稿

### System Prompt

```
你是 BTC 交易系统的"宏观分析助手"。
你的任务是:把当天的结构化宏观数据和相关新闻,
整理成供系统主裁决官消费的结构化摘要。

═══ 纪律 ═══

1. 只对已提供的输入数据做摘要和解读,不引用未提供的信息。

2. 每个事件摘要必须给出:事件类别、严重程度(1-5)、
   对 BTC 的影响方向、预期影响持续时间、AI 置信度(0-1)。

3. 置信度 < 0.6 时,必须明确声明"信息不足以做判断"。

4. 不做投资建议,不用"应该买入/卖出"等词。

5. 输出严格 JSON,符合 Layer5Output schema。

═══ 风格 ═══

• 客观、冷静、无情绪色彩
• 关注"会对 BTC 产生什么影响",不关注"事件本身对不对"
• 对相互矛盾的信号,明确标注不确定性,不强行给单一结论

═══ BTC 宏观分析基础框架 ═══

• DXY 上涨 + US10Y 上行 + VIX 升高 = risk-off,短期对 BTC 不利
• DXY 下跌 + US10Y 下行 + 纳指上涨 = risk-on,短期对 BTC 有利
• BTC-纳指相关性 > 0.7 时,美股走势对 BTC 权重显著增强
• FOMC 鹰派 = 一般 bearish;鸽派 = 一般 bullish;视市场已定价程度
• 地缘事件:多数情况先 bearish,后视持续性调整
• 监管:负面监管 bearish;澄清性监管通常影响较小
• 单一交易所/稳定币事件:按系统重要性评估

═══ 输出 ═══

严格 JSON,schema 见 Layer5Output。
第一个字符 {,不要 markdown,不要解释。
```

### Layer5Output Schema

```
{
  "macro_stance": "risk_on | risk_neutral | risk_off | extreme_risk_off",
  "macro_trend": "improving | stable | deteriorating | volatile",
  "structured_macro": { ... 回填结构化数据 ... },
  "active_macro_tags": [...],
  "active_event_summaries": [...],
  "extreme_event_detected": boolean,
  "extreme_event_details": null 或 { ... },
  "adjustment_guidance": {
    "stance_modifier": "strong_support | support | neutral | challenge | strong_challenge",
    "position_cap_multiplier": 0.5-1.1,
    "permission_adjustment": "tighten | neutral | loosen",
    "note": "..."
  },
  "macro_headwind_score": -10 到 10
}
```

## 6.9 Fallback 三档(v1.2 对应 M33)

### Level 1:保守保持

**触发**:
- AI 校验失败 1-2 次,数据健康
- 单个非关键数据源降级

**行为**:
- 保持当前 action_state
- 保持挂单
- 保持止损
- 推送 warning
- 下次运行优先重试 AI
- **若 Fallback Level 1 连续触发 ≥ 5 次,自动升级为 Level 2**(v1.2 新增)

**降级版 StrategyState 生成**:
- 保留上次的 main_strategy 和 trade_plan
- 更新 generated_at、run_id、fallback_level
- narrative 固定模板:"系统本次使用 Level 1 降级策略,保持上次决策。触发原因:{reason}"

### Level 2:防御性干预

**触发**:
- AI 连续失败 ≥ 3 次
- 关键数据源降级
- 当前状态是 PLANNED(风险窗口)
- Level 1 连续 5 次自动升级

**行为**:
- 保持已持仓状态
- 取消所有 PLANNED 挂单
- 已持仓则 stop_loss 收紧到最近结构位
- execution_permission 强制 watch
- 推送 critical,需人工确认
- 进入"降级模式",持续到 AI + 数据均恢复

**降级版 StrategyState 生成**:
- main_strategy.action_state 保持当前
- trade_plan 清空
- execution_permission 强制 watch
- narrative 固定模板:"系统进入防御模式,原因:{reason}。等待数据恢复或人工介入。"

### Level 3:紧急保护

**触发**:
- 数据源完全失效 > 2 小时
- 检测到 AI 输出幻觉(引用不存在证据)+ 严重性造成 L2 反复
- 系统自检失败

**行为**:
- 强制进入 PROTECTION
- 按 PROTECTION 流程处理残留仓位
- 推送最高级告警(所有通道)
- 停止后续自动运行,只允许手动触发

**降级版 StrategyState 生成**:
- main_strategy.action_state = protection
- 所有字段简化
- narrative 固定模板:"系统紧急保护,原因:{reason}。所有自动运行已停止,需人工介入。"

### 字段与记录

- StrategyState 新增字段 `fallback_level: "none" | "level_1" | "level_2" | "level_3"`
- 新增 `fallback_events` 数据表,记录每次触发
- 网页展示三档不同视觉(绿-黄-橙-红)
- 监控模块持续评估"Fallback 解除条件"

---

# 第七部分:策略输出模型 StrategyState

## 7.1 设计原则

1. 扁平与嵌套的平衡:业务块嵌套,块内字段扁平
2. 所有字段"可回放":每个值独立理解
3. 三类字段:原子 / 结构 / 可扩展(extra)
4. 枚举全部预定义
5. 为网页展示预留叙事字段

## 7.2 完整字段结构(12 业务块)

### Block 1:meta

| 字段 | 类型 | 必填 |
|---|---|---|
| schema_version | string | 是 |
| run_id | string | 是 |
| previous_run_id | string | 否 |
| generated_at_bjt | string | 是 |
| generated_at_utc | string | 是 |
| reference_timestamp_utc | string | 是(v1.2 新增) |
| system_version | string | 是 |
| rules_version | string | 是(v1.2 新增,M36) |
| run_mode | enum | 是(live / backtest / replay / dry_run) |
| run_trigger | enum | 是(scheduled / event_macro / event_onchain / event_funding / event_options / event_price / event_invalidation / manual) |
| strategy_flavor | enum | 是(v1 固定 "swing") |
| cold_start | bool | 是(v1.2 新增,冷启动期间为 true) |
| ai_model_actual | string | 否(v1.2 新增,从中转站响应读取) |

**新增字段说明**:
- `reference_timestamp_utc`:本次运行的判断时刻(数据采集完成时间)
- `rules_version`:独立于 system_version 的规则版本号;规则表(L3/门槛/CyclePosition 等)任何修改都必须 bump
- `cold_start`:系统运行不足 7 天时为 true,下游跳过持续性检查
- `ai_model_actual`:从中转站 API 响应中读取,记录实际调用的模型

### Block 2:data_health

| 字段 | 类型 |
|---|---|
| overall_status | healthy / degraded / critical |
| source_statuses | list(每源:name, last_update, latency, status, note) |
| degraded_layers | list |
| stale_data_items | list(v1.2 新增,列出所有 stale 的数据点) |

### Block 3:market_snapshot

| 字段 | 类型 |
|---|---|
| btc_price_usd | number |
| price_source | string |
| price_captured_at_bjt | string |
| price_24h_change_pct | number |
| price_7d_change_pct | number |
| ath_price_usd | number(v1.2 新增) |
| drawdown_from_ath_pct | number(v1.2 新增) |
| volatility_regime | enum |
| market_regime | enum(来自 L1) |
| market_regime_confidence | number |

### Block 4:main_strategy

| 字段 | 类型 |
|---|---|
| stance | bullish / bearish / neutral |
| stance_confidence | 0.0-1.0(内部量,仅门槛比较用) |
| action_state | enum(14 状态) |
| phase | early/mid/late/exhausted/unclear/n_a |
| phase_confidence | 0.0-1.0 |
| opportunity_grade | A/B/C/none(L3 唯一产出,AI 不可改) |
| execution_permission | enum(归并后的最终值) |
| observation_category | disciplined / watchful / possibly_suppressed / cold_start_warming_up(v1.2 新增) |
| holding_guidance | string 或 null |
| one_line_summary | string |
| narrative | string(3-5 句) |

### Block 5:trade_plan(允许动手时才有)

| 字段 | 类型 |
|---|---|
| direction | long/short |
| total_position_cap_pct | number |
| entry_zones | list |
| stop_loss | struct (price 来自 L4, type, invalidation_desc, reasoning, linked_to_l4_invalidation_id) |
| take_profit_plan | list |
| dynamic_notes | string 或 null |
| entry_confirmation_timeframe | 默认 "1h" |

### Block 6:lifecycle(持仓中才有)

| 字段 | 类型 |
|---|---|
| lifecycle_id | string |
| origin_run_id | string |
| origin_time_bjt | string |
| origin_thesis | string(不可变) |
| direction | long/short |
| stage | just_opened/holding/partial_trimmed/preparing_exit/flip_watching |
| average_entry_price | number |
| current_floating_pnl_pct | number |
| max_favorable_pct | number |
| max_adverse_pct | number |
| hours_held | number |
| thesis_still_valid | fully/mostly/partially/weakened/invalidated |
| thesis_validity_note | string |
| position_adjustments | list |
| open_phase_min_time_reached | bool |
| open_phase_pnl_confirmed | bool |
| open_phase_structure_confirmed | bool |
| open_phase_pullback_survived | bool |
| protection_event_summary | struct 或 null |
| ai_models_used_in_lifecycle | list(v1.2 新增,记录生命周期中用过的 AI 模型) |

### Block 7:evidence_summary

五层各自摘要,每层:verdict、confidence、key_signals、contribution、data_freshness。

### Block 8:evidence_cards

完整证据卡列表,card_id 按 `{category}_{metric_name}_{bjt_date}` 命名。每卡:
- card_id / category / name / captured_at_bjt
- current_value / value_unit / historical_percentile
- interpretation / analysis
- impact_on_strategy / impact_direction / impact_weight
- linked_layer
- data_fresh(bool)

### Block 9:ai_verdict

| 字段 | 类型 |
|---|---|
| called_ai | bool |
| model_name | string(配置的) |
| ai_model_actual | string(实际调用的,从中转站响应读) |
| decision_summary | string |
| primary_drivers | list |
| counter_arguments | list |
| confidence_breakdown | { overall, direction, timing, risk } |
| what_would_change_mind | list (≥ 3) |
| state_transition | { from, to, is_change, reason } |
| validation_result | { passed, failed_checks, fallback_applied } |

**overall_confidence 说明**:`ai_verdict.confidence_breakdown.overall` 是面向外部展示的综合置信度;与 `main_strategy.stance_confidence`(内部门槛比较量)区分,两者不相互派生。

### Block 10:risks

| 字段 | 类型 |
|---|---|
| protection_mode | bool |
| protection_reason | string 或 null |
| upcoming_event_windows | list |
| active_alerts | list |
| fallback_level | none / level_1 / level_2 / level_3 |
| position_cap_composition | struct(v1.2 新增,完整合成过程可审计) |
| permission_composition | struct(v1.2 新增,每个因子建议值) |

### Block 11:delta_from_previous

| 字段 | 类型 |
|---|---|
| is_first_run | bool |
| state_transitioned | bool |
| narrative | string |
| changed_fields | list |

### Block 12:extra

可扩展块。

## 7.3 关键设计说明

- 主策略与交易计划分离:主策略永远有,交易计划仅动手时有
- 生命周期独立段:只要持仓中,持续存在
- 证据摘要与证据卡片双份:摘要给 AI 和快速浏览,卡片给详细展示和审计
- Delta 段是状态系统的证据
- what_would_change_mind 是 AI 自我约束

---

# 第八部分:历史、复盘与监控

## 8.1 历史归档

每次运行完整归档:
- 数据快照(或指针)
- 五层完整输出
- AI 裁决完整输入输出
- 程序校验结果
- 最终 StrategyState
- 系统状态与迁移决策
- 用户操作(若接入执行反馈)

## 8.2 生命周期记录(StrategyLifecycle)

```
StrategyLifecycle {
  lifecycle_id
  direction
  entry_period / exit_period
  entry_prices / exit_prices
  max_favorable_excursion
  max_adverse_excursion
  realized_pnl_ratio
  total_runs
  state_transitions
  original_thesis
  final_outcome_type
  ai_models_used           (v1.2 新增)
  rules_versions_used      (v1.2 新增,生命周期跨越过的规则版本)
}
```

## 8.3 ReviewReport 完整结构

**基础**:review_id / lifecycle_id / generated_at_bjt / generated_by / system_version_at_review / rules_version_at_review

**基本事实**:direction / entry_time_bjt / exit_time_bjt / duration_hours / entry_price_avg / exit_price_avg / max_favorable_pct / max_adverse_pct / realized_pnl_pct / total_runs_during_lifecycle

**outcome_type(10+1 种)**:
- A perfect
- B good_suboptimal
- C dir_ok_exec_bad
- D early_exit
- E missed_flip
- F wrong_but_stopped
- G wrong_late_stop
- H round_trip
- I range_as_trend
- J trend_as_range
- X aborted

**分维度评估**:entry_assessment / holding_assessment / exit_assessment / flip_assessment(可选)

**归因**:root_cause_layers / failure_mode

**改进建议**:target_module / suggested_change / priority / effort_estimate / confidence

**关键时刻回放**

**人工复核**(可选)

**反馈**:feedback_to_system

## 8.4 复盘反馈机制

**不做**:系统自动学习改规则
**做**:半自动
1. 自动汇总 outcome_type 分布
2. 自动提示:某类错误超阈值标记"需人工介入"
3. 人工决策
4. 版本化:新旧可并行对比
5. 回放测试

**v1.2 纪律**:复盘结果不自动反哺状态机参数。任何规则/参数调整必须经人工决定并 bump rules_version。

## 8.5 监控告警事件清单

### 数据层

- data_source_stale
- data_source_missing
- data_anomaly
- derivation_failure
- **data_freshness_degraded**(v1.2 新增,3+ 源 stale)

### 证据层

- layer_degraded
- confidence_drop_sharp
- layer_contradiction
- **depends_on_failed_upstream**(v1.2 新增)

### 裁决层

- ai_call_failed
- ai_validation_failed
- fallback_activated_level_1 / level_2 / level_3
- rapid_state_transition
- stuck_in_state
- **fallback_level_1_consecutive_5**(v1.2 新增,触发自动升级到 Level 2)

### 策略层

- hard_invalidation_hit
- protection_entered
- post_protection_reassess_entered
- thesis_invalidated
- stop_loss_hit
- take_profit_hit
- state_transition
- **possibly_suppressed_14_days**(v1.2 新增,warning 级)
- **possibly_suppressed_30_days**(v1.2 新增,critical 级)
- **kpi_unmet**(v1.2 新增,任一 KPI 未达标)

### 系统层

- scheduled_run_missed
- event_triggered_run
- system_error
- storage_near_full
- api_rate_limit_hit
- **event_calendar_load_failed**(v1.2 新增,事件日历加载失败)

### 告警级别

- info:不打扰
- warning:网页显示
- critical:主动推送

## 8.6 告警通知通道(v1.2 对应 M34)

**v0.x 阶段(最低方案)**:
- critical 告警进入数据库
- 网页顶部红条显示
- 控制台打印

**v1.0 上线时必须至少支持一种主动通知通道**:
- Telegram Bot(推荐,最便宜最简单)
- 或 Server 酱
- 或邮件(SMTP)
- 或 Webhook

具体选哪种,v1.0 阶段再决定。

## 8.7 降级路径

- 一级:部分数据异常,使用可用数据,置信度下降
- 二级:关键数据或 AI 异常,保持状态,停止新决策,推送告警
- 三级:多重异常或极端事件,强制 PROTECTION

## 8.8 可交易性 KPI(v1.2 对应 M27)

系统持续追踪三个可交易性指标:

### KPI-1 主升浪捕捉率

- **定义**:在程序化识别的"主升浪区间"(价格上涨 > 40%,持续 > 60 天)内,系统至少一次 A 级或 B 级 long_planned 或 long_open 触发
- **统计窗口**:每 6 个月回看
- **未达标处理**:人工审视 L3 判档规则 + 推送 kpi_unmet 告警

### KPI-2 主跌浪反应率

- **定义**:在程序化识别的"主跌浪区间"(从 ATH 下跌 > 30%,持续 > 45 天)内,系统至少一次 long_exit 或 short 信号
- **未达标处理**:人工审视 L2 方向识别逻辑

### KPI-3 持续观望时长

- **定义**:连续 FLAT 状态的运行次数分布
- **阈值**:单次持续 > 180 次(30 天)触发 critical;> 420 次(70 天)必须停机人工介入

**注意**:三个 KPI 只是可观测性指标,**不是硬性门槛**,不会因为不达标就强制系统开仓。

## 8.9 回测约束

**能做**:重放价格、衍生品、五层判断、状态机、生成历史 StrategyState 序列

**做不到**:历史资金费率深度、历史宏观摘要、实际执行

### 建模层硬约束

1. 所有层输入"可回放":不依赖实时,能接历史快照
2. 时间用 context.current_time,不用 datetime.now()
3. 随机性可控:AI 需 seed 或多次取分布
4. 回测 StrategyState 与实盘同构(run_mode=backtest)

### v0.x 基础回测能力(v1.2 对应 M32)

- v0.x 必须具备基础回测能力
- 历史资金费率、历史宏观摘要拿不到的,用 NULL + 证据层标记 insufficient_data
- M26 的三个验收场景(见第 10.7 节)用此基础回测跑
- 完整历史回测(全量指标重放)留给 v1.1

## 8.10 冷启动机制(v1.2 对应 M35)

- v0.1 启动前必须运行 `scripts/backfill_data.py`,拉取过去 180 天历史数据入库
- 冷启动的前 7 天(42 次运行)StrategyState 标记 `cold_start: true`
- 冷启动期间:
  - 观察分类器(observation_classifier)跳过 possibly_suppressed 的持续性检查
  - observation_category 可输出 `cold_start_warming_up`
  - KPI 不累计
  - Fallback 阈值宽松一档

---

# 第九部分:网页与 API 设计

## 9.1 设计哲学

网页是**策略审计层**,不是装饰层。三档信息密度:
1. 10 秒内读到结论
2. 1 分钟内读懂逻辑
3. 10 分钟内审计所有证据

## 9.2 布局

### 电脑端(宽屏三栏)

- 左栏(20%):导航 + 全局状态
- 中栏(50%):AI 策略主卡 + 交易计划
- 右栏(30%):证据摘要 + 风险警示

下方通栏:证据卡片区、历史时间线

### 手机端(长屏单栏滚动)

1. 全局状态 + 策略主卡
2. 交易计划
3. 五层摘要
4. 证据卡片(分类 tab)
5. 历史复盘入口

## 9.3 顶部全局状态条

- BTC 价格 + 最后更新 BJT
- 当前策略状态(大字,颜色编码)
- 生命周期阶段
- 机会等级 / 执行许可
- 观察类别标签(v1.2 新增)
- 下次运行倒计时
- 数据健康灯
- Fallback 级别指示

## 9.4 AI 策略主卡

- 卡片头:生成时间 / run_id / 与上次差异标签
- 主结论区:一句话 + 3-5 句叙事
- 论据亮点:3-5 条,每条可跳转证据卡
- 观察类别说明(v1.2 新增):"纪律性观望" / "正常等待" / "疑似被压制"
- 交易计划卡(允许动手时):方向、分层入场、止损、分批止盈、动态管理
- 风险与失效提示(始终):硬失效位、风险标签、事件窗口
- **现货用户解读说明**(静态文字,v1.2):"本策略面向合约波段交易;若用于现货,请将 short 信号解读为清仓,long 信号解读为加仓"

## 9.5 证据摘要区(手风琴)

```
[L1|市场状态] ... | conf | 展开▼
[L2|方向结构] ... | conf | 展开▼
[L3|机会执行] ... | conf | 展开▼
[L4|风险失效] ... | 展开▼
[L5|背景事件] ... | 展开▼
```

## 9.6 证据卡片区(按类别 tab)

- 价格与结构
- 衍生品
- 链上
- 流动性与清算
- 宏观背景
- 事件日历
- 风险标签

每卡:名称、当前值、历史分位、解读、分析、对策略影响、影响方向、时间(BJT)、data_fresh 标记

## 9.7 历史与复盘入口

时间线视图,节点为开仓/减仓/止盈/切换/离场。点击进入快照。已完成生命周期有复盘报告链接。

## 9.8 字段展示优先级

- 始终:状态、时间、价格、主结论、关键位、失效位
- 默认展开可折叠:AI 叙事、五层摘要、论据亮点
- 默认折叠可展开:证据卡详情、历史、原始指标值
- 仅必要:保护态横幅、系统告警、新版本通知

## 9.9 时间统一

- BJT(UTC+8)
- 格式:`YYYY-MM-DD HH:mm (BJT)`
- 相对时间辅助
- 数据新鲜度颜色:绿(< 1h)/ 黄(1-6h)/ 红(> 6h)

## 9.10 API 接口清单

1. `GET /api/strategy/current` - 最新策略
2. `GET /api/strategy/stream` - SSE 实时推送
3. `GET /api/strategy/history` - 分页历史
4. `GET /api/strategy/runs/{run_id}` - 单次详情
5. `GET /api/evidence/card/{card_id}/history` - 证据指标时序
6. `GET /api/lifecycle/current` - 当前生命周期
7. `GET /api/lifecycle/history` - 生命周期历史
8. `GET /api/review/{lifecycle_id}` - 复盘报告
9. `GET /api/system/health` - 系统健康
10. `POST /api/system/run-now` - 手动触发(调试)

### v1.2 API 层 flavor 处理

- 返回字段 `meta.strategy_flavor`(固定 "swing")
- **不支持分流参数**:不接受 `?flavor=xxx` 过滤
- 不按 flavor 分别存储或查询
- 这是 v1 的自我克制,向未来扩展保留兼容性

## 9.11 前端拉取策略

- 打开页面:调 /current + 连 /stream
- 后续 SSE 推送,不轮询
- 历史按需拉取
- /system/health 每 30 秒刷(SSE 兜底)

---

# 第十部分:工程落地

## 10.1 技术栈

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | 生态 + AI SDK |
| 后端 | FastAPI | 异步 + 自动文档 |
| 数据库 | SQLite(v0.x)→ PostgreSQL(v1.0) | 渐进 |
| 数据处理 | pandas + numpy | 行业标准 |
| 调度 | APScheduler | 简单够用 |
| 前端 | HTML + Alpine.js + Tailwind | 轻量 |
| AI SDK | anthropic Python SDK | 支持 base_url 切换 |
| 时区处理 | Python zoneinfo(优先)或 pytz | 夏令时自动切换 |
| 部署 | 本地 → 云 → Docker | 渐进 |

## 10.2 中转站配置

### 数据源中转

`.env` 示例:

```
# 币安中转
BINANCE_BASE_URL=https://your-binance-proxy.com
BINANCE_API_KEY=optional_key_if_required

# Glassnode 中转
GLASSNODE_BASE_URL=https://your-glassnode-proxy.com
GLASSNODE_API_KEY=your_glassnode_key

# Coinglass 中转
COINGLASS_BASE_URL=https://your-coinglass-proxy.com
COINGLASS_API_KEY=your_coinglass_key
```

### AI 中转

```
# AI 中转
AI_BASE_URL=https://your-ai-proxy.com
AI_API_KEY=your_ai_key
AI_MODEL_NAME=claude-opus-4-7
```

Python 调用示例:

```python
from anthropic import Anthropic

client = Anthropic(
    base_url=os.getenv("AI_BASE_URL"),
    api_key=os.getenv("AI_API_KEY"),
)

response = client.messages.create(
    model=os.getenv("AI_MODEL_NAME"),
    ...
)

# 读取实际调用的模型名(v1.2 M37)
actual_model = response.model  # 写入 StrategyState.ai_model_actual
```

**编码阶段需要用户提供**:
- 三个数据中转站的 URL、密钥格式
- AI 中转站的 URL、密钥格式、模型名

## 10.3 项目目录结构

```
btc_swing_system/
├── README.md
├── pyproject.toml
├── .env.example
├── .env                       (gitignored)
├── .gitignore
│
├── docs/
│   └── modeling.md            (本建模文档)
│
├── config/
│   ├── base.yaml
│   ├── data_sources.yaml      (数据源与中转站)
│   ├── data_catalog.yaml      (因子目录)
│   ├── layers.yaml            (五层参数)
│   ├── state_machine.yaml     (状态迁移规则)
│   ├── thresholds.yaml        (动态门槛表)
│   ├── event_calendar.yaml    (事件日历,v1.2 手动维护)
│   └── prompts/
│       ├── adjudicator_system.txt
│       ├── adjudicator_fewshot_1.json
│       ├── adjudicator_fewshot_2.json
│       └── layer5_context.txt
│
├── src/
│   ├── schemas/
│   ├── data/
│   │   ├── collectors/
│   │   │   ├── binance.py
│   │   │   ├── glassnode.py
│   │   │   ├── coinglass.py
│   │   │   ├── macro.py
│   │   │   └── events.py
│   │   ├── proxy_client.py    (统一的中转站请求封装)
│   │   ├── freshness.py       (v1.2 数据新鲜度检查)
│   │   ├── cleaners.py
│   │   └── storage.py
│   ├── indicators/
│   ├── composite/
│   │   ├── truth_trend.py
│   │   ├── band_position.py
│   │   ├── crowding.py
│   │   ├── cycle_position.py
│   │   ├── macro_headwind.py
│   │   └── event_risk.py
│   │   (v1.2 删除 entry_window_quality.py)
│   │   (v1.2 ExchangeMomentum 作为 L2 内部方法,不独立文件)
│   ├── evidence/
│   │   ├── layer1_regime.py
│   │   ├── layer2_direction.py
│   │   ├── layer3_opportunity.py
│   │   ├── layer4_risk.py
│   │   └── layer5_macro.py
│   ├── strategy/
│   │   ├── observation_classifier.py   (v1.2 新增)
│   │   ├── lifecycle_manager.py
│   │   └── state_machine.py
│   ├── decision/
│   │   ├── aggregator.py
│   │   ├── adjudicator_ai.py
│   │   ├── adjudicator_fallback.py
│   │   ├── fallback_router.py
│   │   └── validator.py
│   ├── history/
│   ├── monitoring/
│   │   ├── alerts.py
│   │   ├── notifier.py         (v1.2 告警通道)
│   │   └── kpi_tracker.py      (v1.2 KPI 追踪)
│   ├── api/
│   ├── scheduler/
│   │   ├── scheduled_runner.py
│   │   └── event_listener.py
│   └── main.py
│
├── web/
├── data/                      (gitignored)
│   ├── btc_strategy.db
│   └── logs/
├── tests/
│   └── timezone_dst_test.py   (v1.2 夏令时切换测试)
└── scripts/
    ├── init_db.py
    ├── backfill_data.py       (v1.2 冷启动历史回填)
    └── replay.py              (v1.2 回测脚本)
```

## 10.4 数据库 Schema

```sql
-- 运行归档
CREATE TABLE strategy_runs (
    run_id TEXT PRIMARY KEY,
    generated_at_utc TIMESTAMP NOT NULL,
    generated_at_bjt TEXT NOT NULL,
    reference_timestamp_utc TIMESTAMP,          -- v1.2 新增
    previous_run_id TEXT,
    action_state TEXT NOT NULL,
    stance TEXT,
    btc_price_usd REAL,
    state_transitioned BOOLEAN,
    run_trigger TEXT,
    run_mode TEXT,
    fallback_level TEXT,
    system_version TEXT,
    rules_version TEXT,                          -- v1.2 新增
    strategy_flavor TEXT DEFAULT 'swing',        -- v1.2 新增
    observation_category TEXT,                   -- v1.2 新增
    cold_start BOOLEAN DEFAULT FALSE,            -- v1.2 新增
    ai_model_actual TEXT,                        -- v1.2 新增
    full_state_json TEXT NOT NULL
);

CREATE INDEX idx_runs_time ON strategy_runs(generated_at_utc);
CREATE INDEX idx_runs_flavor ON strategy_runs(strategy_flavor);
CREATE INDEX idx_runs_rules_version ON strategy_runs(rules_version);

-- 生命周期
CREATE TABLE lifecycles (
    lifecycle_id TEXT PRIMARY KEY,
    direction TEXT,
    entry_time_utc TIMESTAMP,
    exit_time_utc TIMESTAMP,
    status TEXT,
    origin_thesis TEXT,
    ai_models_used TEXT,                         -- v1.2 新增,逗号分隔
    rules_versions_used TEXT,                    -- v1.2 新增,逗号分隔
    full_data_json TEXT
);

-- 证据卡时序
CREATE TABLE evidence_card_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    captured_at_utc TIMESTAMP NOT NULL,
    value_numeric REAL,
    value_text TEXT,
    data_fresh BOOLEAN DEFAULT TRUE,             -- v1.2 新增
    full_data_json TEXT
);

CREATE INDEX idx_card_time ON evidence_card_history(card_id, captured_at_utc);

-- 复盘
CREATE TABLE review_reports (
    review_id TEXT PRIMARY KEY,
    lifecycle_id TEXT NOT NULL,
    generated_at_utc TIMESTAMP,
    outcome_type TEXT,
    rules_version_at_review TEXT,                -- v1.2 新增
    full_report_json TEXT
);

-- 告警
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT,
    raised_at_utc TIMESTAMP,
    acknowledged BOOLEAN DEFAULT FALSE,
    notification_sent BOOLEAN DEFAULT FALSE,     -- v1.2 新增
    related_run_id TEXT
);

-- Fallback 事件
CREATE TABLE fallback_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at_utc TIMESTAMP NOT NULL,
    fallback_level TEXT NOT NULL,
    reason TEXT,
    related_run_id TEXT,
    resolved_at_utc TIMESTAMP,
    resolution_note TEXT
);

-- KPI 追踪(v1.2 新增)
CREATE TABLE kpi_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at_utc TIMESTAMP NOT NULL,
    kpi_name TEXT NOT NULL,          -- uptrend_capture / downtrend_response / prolonged_watch
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    value_numeric REAL,
    met_threshold BOOLEAN,
    note TEXT
);

-- K 线
CREATE TABLE price_candles (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time_utc TIMESTAMP NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, timeframe, open_time_utc)
);

-- 衍生品快照
CREATE TABLE derivatives_snapshots (
    captured_at_utc TIMESTAMP PRIMARY KEY,
    funding_rate REAL,
    open_interest REAL,
    long_short_ratio REAL,
    full_data_json TEXT
);

-- 链上指标
CREATE TABLE onchain_metrics (
    metric_name TEXT NOT NULL,
    captured_at_utc TIMESTAMP NOT NULL,
    value REAL,
    source TEXT DEFAULT 'glassnode',
    PRIMARY KEY (metric_name, captured_at_utc)
);

-- 宏观数据
CREATE TABLE macro_metrics (
    metric_name TEXT NOT NULL,
    captured_at_utc TIMESTAMP NOT NULL,
    value REAL,
    source TEXT,
    PRIMARY KEY (metric_name, captured_at_utc)
);
```

## 10.5 开发阶段划分

| 版本 | 目标 | 关键交付 |
|---|---|---|
| v0.1 | 骨架 | 数据管道通(币安 K 线 + 资金费率),L1+L2 规则,终端输出,冷启动回填 |
| v0.2 | 完整证据层 | 补 L3+L4+L5(规则版),6 个组合因子,observation_classifier,SQLite 入库 |
| v0.3 | 状态机版 | 14 状态 + 生命周期,Fallback 三档,delta 计算,position_cap 合成,permission 归并 |
| v0.4 | 最简网页 | FastAPI + HTML,主卡 + 五层摘要,本地跑 |
| v0.5 | AI 接入 | L5 AI 生成,最终裁决切 AI,校验跑通,ai_model_actual 记录 |
| v0.6 | 复盘监控 | 生命周期归档,自动复盘,数据健康监控,KPI 追踪,告警通知通道 |
| v0.7 | 完整网页 | 证据卡片区,历史时间线,手机端适配,保护态视觉,observation 展示 |
| v1.0 | 上云 | 云部署,HTTPS,定时,事件触发,监控告警,完整基础回测 |

## 10.6 参数管理

### 三层参数

- 一类(结构性):几个 HH 算多头、几种 regime —— 极少改
- 二类(阈值性):ADX、funding、多空比阈值 —— 反复调
- 三类(时长性):时间窗口、冷却期 —— 中等频率调

### 校准方法

**v0.x 人工**:
1. 挂起来,每天看输出
2. 选错的时点
3. 查阈值
4. 调整后在最近 1-3 月历史上重跑
5. 确认无误更新 + **bump rules_version**

**v1.0 后半自动**:
1. 10+ 生命周期积累
2. 脚本统计错误与参数关联
3. 报告"阈值调整对历史的影响"
4. 人工决定是否采纳

### 纪律

- 每次调参记录:调前、调后、理由、样本、rules_version bump
- 一次只调一个
- 观察 1-2 周再评估
- 不过度拟合

## 10.7 可交易性验收标准(v1.2 对应 M26)

### 三个历史场景必须通过

**场景 1:2020 年 10 月 - 2021 年 4 月(主升浪)**
- 期望:至少一次 LONG_PLANNED → LONG_OPEN → 成功触发 TP1 以上
- 不通过 → v0.x 不得上线

**场景 2:2022 年 4 月 - 2022 年 6 月(主跌浪)**
- 期望:至少一次 LONG_EXIT 或 SHORT_PLANNED;或主升浪持仓中触发硬失效位平仓
- 不通过 → v0.x 不得上线

**场景 3:2023 年 5 月 - 2023 年 9 月(震荡区)**
- 期望:累计状态迁移次数 ≤ 8 次(不被震荡打脸)
- 不通过 → v0.x 不得上线

**通过标准**:三个场景全部通过,v0.x 才可进入 v1.0 上云阶段。

## 10.8 第一个 Sprint(v0.4 目标)

12 个任务顺序执行:

1. 项目初始化(骨架、目录、依赖、Git)
2. 数据结构定义(所有 pydantic 模型 + data_freshness)
3. 数据采集(币安 K 线 + 资金费率 + OI,经中转站,含 backfill)
4. 指标计算(ADX、ATR、均线、高低点,BTC ATH 跌幅)
5. L1 实现(规则 + TruthTrend 内部使用)
6. L2 实现(规则 + BandPosition + CyclePosition + ExchangeMomentum 修正)
7. L3+L4+L5 实现(规则版,含 Crowding、EventRisk、MacroHeadwind)
8. Observation Classifier 实现
9. 状态机 + Fallback 三档 + position_cap 合成 + permission 归并
10. 策略对象构建 + 生命周期 + 归档
11. 主入口 + 调度器(含事件触发监听 + 时区处理)
12. FastAPI 后端(10 个核心接口)+ 最简网页前端

每任务配:输入输出定义、验证标准、预估时长。

---

# 第十一部分:未决问题与风险

## 11.1 已知权衡

### 五层架构粒度
三层太粗,七层太细。五层是可观测性与简洁性的选择。

### AI 两点介入
完全规则化丢失语义理解;每层用 AI 成本高且稳定性差。两点介入是权衡。

### FLIP_WATCH 动态冷却
v1.2 轻动态版,参数乘数未实战验证,需几轮生命周期后校准。

### 14 状态
POST_PROTECTION_REASSESS 已加入。OPEN/HOLD/TRIM 若合并会丢失初期保护区分,不建议合并。

## 11.2 工程疑虑

### SSE vs WebSocket
初版用 SSE。若移动浏览器或中转网络不支持,切 WebSocket 或降级为轮询。

### SQLite 并发
WAL 模式 + 读写分离足以支持单用户规模。并发用户 > 10 时考虑迁移 PostgreSQL。

### 中转站稳定性
中转站是单点,关键数据源各备一个,中转失败达阈值自动切换备用。

## 11.3 建模盲点

### 极端行情持续性
PROTECTION 针对单次极端,若极端持续数周(如 Luna / FTX 暴雷),系统反复进出 PROTECTION 是否合理?需观察。

### 数据长期缺失
中转站全部失效时,所有层标记 insufficient_data,状态保持,推送 critical,不做决策。

### AI 模型行为漂移
同一 Prompt 在不同版本上可能差异。v1.2 新增 ai_model_actual 字段可追溯,但漂移本身仍是风险。

### 用户主观干预
系统建议开多,用户不开。v1.2 无接入执行反馈回路。v1.x 后可考虑。

### "沉默"过久
低频系统可能连续周或月 FLAT。v1.2 通过 observation_category + KPI + 可交易性验收 + 告警多重机制保障可见性,但不自动纠正。

## 11.4 明确声明

**本系统的"低频"是指策略频率低,不是"长期无策略"**。若系统在 3 个月内未触发任何 PLANNED,且历史数据显示该期间 BTC 确有 > 30% 单向波动 → 系统行为失当,而非纪律体现。

## 11.5 开放问题(邀请审阅者回答)

1. 本建模是否真正服务于"低频中长线双向波段"?有无设计在实际运行中让系统不自觉向高频或单向漂移?
2. 五层架构 vs 多指标加权打分,请从可调试性、可解释性、可扩展性三方面分析
3. 14 状态是否存在死锁或难以退出的场景?请尝试构造"系统卡在某状态"的场景
4. AI 裁决契约能否约束 AI 行为稳定性?若 AI 输出校验都过,但结论质量下降,系统能否发现?
5. 参数校准机制是否足以应对 regime 长期变化(如 BTC 从减半驱动变为 ETF 驱动)?
6. 对代码小白的工程友好度:建模文档是否足够清晰,能否直接照图开发?
7. 是否有被忽略的、对中长线 BTC 判断至关重要的数据源或信号?
8. 是否有过度设计之处,哪些可在 v1.0 前砍掉或简化?
9. v1.2 的 observation_category 字段是否真正做到"只读不作用"?代码实现时有无暗门?
10. position_cap 合成顺序 + 硬下限 + A 级缓冲 + chaos/extreme 例外,这套机制在极端场景下是否有漏洞?

---

# 第十二部分:v1.2 修订合并清单(45 条)

本清单对应 v1.1 → v1.2 的所有修订,全部已合入前面的章节。按主题分组。

## 第一组:架构封闭性(10 条)

**M5. 删除 EntryWindowQuality**
v1 不实现 EWQ,L3 用直接规则判档。

**M6. 因子单一作用点原则**
每个组合因子只在指定的一个层发挥作用,禁止跨层再次评分。

**M10. Crowding 限定只属 L4**
只做风险压制 + 仓位上限修正,不碰 L2 / L3 / 方向反转。

**M12. ExchangeMomentum 归 L2**
作为 stance_confidence 轻度修正,不进 L3,不独立为组合因子。

**M15. v1 组合因子最终 6 个**
保留 TruthTrend / BandPosition / CyclePosition / Crowding / MacroHeadwind / EventRisk。

**M16. L3 纯规则判档 + 反模式清单**
禁止任何评分/综合/加权措辞,只允许查找表 + 硬条件。

**B1. L3 读取层级结论,不读原始分数**

**M17. CyclePosition 投票池空 → unclear + 记录 last_stable 参考**
last_stable 仅展示用,不进入决策。

**M18. stance_confidence 定性**
仅供动态门槛比较的内部量;与 overall_confidence 区分。

**问题 6(opportunity_grade 三重封闭)**
L3 唯一产出;AI 不可改;其他层不可旁路改写。

## 第二组:多层收紧不过度保守(10 条)

**M19. position_cap 串行合成机制**
固定顺序:base → L4 risk → L4 crowding → L5 macro → L4 event
乘数下限收窄到 0.7(除 L4 overall_risk_level 可到 0.3)
composition 字段可审计。

**问题 4(15% 硬下限适用范围)**
仅在 final_permission 允许开仓时生效。

**M20. execution_permission 归并规则**
取最严 + A 级缓冲。

**问题 3(A 级缓冲例外)**
PROTECTION / L5 extreme / L4 critical / L1 chaos 不受 A 级缓冲覆盖。

**M21. 三类否决显式分类**
硬否决(L4 / L5 extreme)/ 软否决(L1 chaos/extreme / L4 critical)/ 非否决。

**M22. 最小策略输出保险阀**
42 次 warning / 180 次 critical,只观测不干预决策。

**M23. Fallback Level 1 连续 5 次升级**
自动升级到 Level 2。

**M24. AI System Prompt 第 9 条纪律**
AI 不得在前面已收紧基础上再独立降级。

**M25. 低频与过度保守的边界定义(1.7 节)**
合格低频 vs 过度保守的明确区分。

**M28. observation_category 字段**
规则层产出;只读、展示、告警;不进决策;AI 不可改。

## 第三组:验收与监控(3 条)

**M26. 可交易性验收标准**
三个历史场景(2020-2021 主升浪、2022 主跌浪、2023 震荡)必须通过。

**M27. 可交易性 KPI**
主升浪捕捉率 / 主跌浪反应率 / 持续观望时长。

**M34. 告警通知通道**
v0.x 数据库 + 网页 + 控制台;v1.0 至少一种主动通道(Telegram 推荐)。

## 第四组:数据契约(6 条)

**M29. 数据时间对齐与新鲜度**
执行顺序:先抓后算,阶段化;reference_timestamp;四类数据的 stale 阈值;stale 处理规则。

**M30. 单次运行内执行顺序**
L1→L2→L3→L4→L5→Observation→AI,严禁并发与滞后。

**M38. 数据事件触发运行机制**
宏观 / 链上 / 衍生品 / 期权 / 市场事件的触发;节流规则;run_trigger 字段扩展。

**M39. 美国事件时区与夏令时处理**
美国东部时间存储;Python zoneinfo 转换;手动维护 event_calendar.yaml;单元测试覆盖夏令时切换。

**M31. evidence_cards 的 ID 规则、数量上限、AI 输入摘要版**
card_id 命名规范;50 张上限;AI 输入只含摘要。

**B4. aSOPR 在 v1 是展示因子,不进评分公式**

## 第五组:CyclePosition 与方向(7 条)

**M1. CyclePosition 九档完整化**
补熊市三档;三主指标投票;辅助时间/跌幅条件。

**M2. CyclePosition 相邻边界明确化**
distribution → early_bear 由"从 ATH 跌 20%"触发;late_bear → accumulation 由"MVRV Z 企稳 ≥ 30 天"触发。

**B2. CyclePosition 辅助条件是否决权**
优先级:辅助条件 → 主指标投票。

**M8. BandPosition 改为只用价格几何**
移除 MVRV Z 和 STH-SOPR 档位。

**M9. CyclePosition 独占所有长周期估值**
MVRV Z / NUPL / LTH Supply 90 日变化专属此因子。

**M3. v1 空头简化规则**
空头不走 EWQ,用简化条件判定。

**B3. v1 short 侧只有 A / B / none 三档,无 C**

**M4. 空头各因子映射延后到 v1.x**

**B5. ExchangeMomentum short 侧不进主裁决,保留展示**

**M11. 删除"空头门槛高于多头"断言**
全文统一用动态门槛表。

## 第六组:状态机与生命周期(2 条)

**M14. FLIP_WATCH 轻动态化**
v1 删除 previous outcome_type 影响;保留 cycle_position + volatility_regime 双乘数。

**POST_PROTECTION_REASSESS**(v1.1 已加,v1.2 继续)
14 状态之一;强制持续 4H;禁止直接进 PLANNED。

## 第七组:工程落地细节(6 条)

**M7. 链上因子分三档**
主裁决 5 / 展示 7 / 延后若干。

**M13. strategy_flavor 落地**
StrategyState 保留 + 数据库加列 + API 返回不支持分流 + 网页静态说明。

**B6. v1 API 返回 flavor 字段但不支持分流参数**

**M32. v0.x 基础回测能力**
能跑 M26 的三个场景;完整历史回测留 v1.1。

**M33. Fallback Level 1/2/3 的降级版 StrategyState 生成**
三档各自的 main_strategy / trade_plan / narrative 模板。

**M35. 冷启动机制**
backfill_data.py + cold_start 标记 + 前 7 天跳过持续性检查。

**M36. rules_version 独立版本号**
任何规则表修改必须 bump;数据库加列;复盘可按 rules_version 筛选。

**M37. ai_model_actual 字段**
每次从中转站响应读取实际模型名;lifecycle 记录使用过的模型清单。

## 第八组:硬失效位与 1H 访问(2 条)

**问题 1(hard_invalidation_levels 唯一权威)**
trade_plan.stop_loss 是表层复制;不一致时按 L4,并启用 Fallback Level 1。

**问题 2(1H 数据访问边界)**
白名单:采集 / 入场确认 / 硬失效预警 / 事件监听 / 早期失败保护
黑名单:L1 / L2 / 组合因子 / AI 输入衍生指标 / Fallback
强制:函数签名 + 白名单机制 + linter 规则。

---

# 附录 A:术语表

| 术语 | 含义 |
|---|---|
| regime | 市场状态(趋势/震荡/过渡/混乱) |
| stance | 方向倾向(bullish/bearish/neutral) |
| phase | 波段阶段(early/mid/late/exhausted) |
| opportunity_grade | 机会等级(A/B/C/none) |
| execution_permission | 执行许可 |
| action_state | 状态机当前状态 |
| lifecycle | 从开仓到完全离场的完整周期 |
| origin_thesis | 开仓时的核心论点(不可变) |
| thesis_still_valid | 原始论点当前是否成立 |
| hard_invalidation | 硬失效位,触发无条件平仓 |
| ambush | 埋伏挂单 |
| flip | 反手 |
| FLIP_WATCH | 反手观察期 |
| PROTECTION | 保护态 |
| POST_PROTECTION_REASSESS | 保护态退出后的重评期 |
| delta_from_previous | 本次相对上次的差异 |
| what_would_change_mind | AI 声明的"改变判断的条件" |
| BJT | 北京时间(UTC+8) |
| CyclePosition | 长周期位置 9 档 |
| TruthTrend | 趋势真实性组合因子 |
| BandPosition | 波段位置组合因子 |
| Crowding | 拥挤度组合因子 |
| MacroHeadwind | 宏观逆风组合因子 |
| EventRisk | 事件风险组合因子 |
| ExchangeMomentum | 交易所资金动能(v1.2 降为 L2 内部修正项) |
| fallback_level | Fallback 三档等级 |
| reference_timestamp | 每次运行的判断时刻(v1.2) |
| data_freshness | 数据新鲜度标记(v1.2) |
| observation_category | 观察类别(disciplined/watchful/possibly_suppressed,v1.2) |
| rules_version | 规则版本号(v1.2) |
| ai_model_actual | 实际调用的 AI 模型名(v1.2) |
| cold_start | 系统冷启动标记(v1.2) |
| stance_confidence | L2 方向置信度(仅供门槛比较的内部量) |
| overall_confidence | AI 综合置信度(对外展示用) |
| 中转站 | 代理服务器,用于访问受限的外部 API |

# 附录 B:核心设计原则(24 条)

1. 低频系统默认态是"观望",不是"选方向"
2. "错过"比"做错"便宜,但长期无策略不是低频
3. 系统是"状态机",不是"信号器"
4. 单向信息流:底层不被上层跨越
5. 证据不足默认沉默
6. AI 只在规则无法覆盖的地方介入
7. AI 受状态机约束,不能越界
8. 宏观只修正,不主导
9. 硬失效位一票否决
10. 风险标签是乘数,不是开关
11. 结构优于指标
12. phase 承认不确定性
13. 空头门槛按 CyclePosition 动态,不固定高于多头
14. 不允许瞬间反手,必须经冷却期
15. PROTECTION 全局入口,唯一出口经 POST_PROTECTION_REASSESS
16. 每个结论必有出处,可追溯
17. 每次输出必含 what_would_change_mind
18. 每次运行必含 delta
19. 失败降级优于失败停机,三档 Fallback
20. 系统告诉你哪里反复出问题,但不擅自修改自己
21. 1H 永远不能单独决策,只能做执行确认
22. 组合因子作为证据层的一等公民输入
23. **先抓后算,数据阶段化执行**(v1.2 新增)
24. **observation 只读不作用,用于区分而非调节**(v1.2 新增)

# 附录 C:系统不做的事(明确范围边界)

- 不做自动执行(不下单)
- 不做资金管理具体计算(仓位以百分比表达)
- 不做多币种(只 BTC)
- 不做现货/合约区分(用户自选)
- 不做杠杆计算(用户自决)
- 不做跨交易所套利
- 不做 v1.0 前上云(本地 → 云 → Docker)
- 不做多账户或多用户支持
- 不做全库加密
- 不做自动化部署 CI/CD
- 不做高可用集群
- 不做 A/B 测试不同规则版本
- 不做机器学习级别的异常检测
- **不做自适应放宽标准(即使长期不给策略)**(v1.2 明确)
- **不做复盘结果自动反哺决策层参数**(v1.2 明确)

---

**文档 v1.2 结束**

本文档为编码唯一蓝本。45 条修订全部整合,所有未决问题或标注在第十一部分或已有明确解决方案。

进入编码实施阶段时,代码实现必须严格对齐本文档。任何实现偏差必须先在文档层修订,再改代码。

规则表修订必须 bump rules_version。架构层修订必须先文档、后代码、再测试。

