# BTC 中长线低频双向波段交易辅助系统 — 建模 v1.3

**版本**:v1.3
**修订日期**:2026-04-30
**修订人**:用户 + 网页 Claude(协作)
**前一版本**:v1.2(2026-04-23)

---

# 第零部分:v1.2 → v1.3 修订摘要

## 0.1 修订动机

v1.2 在 Sprint 1.5 系列实施后暴露了 5 个根本设计问题:

1. **加权打分机械,临界值踩空**:TruthTrend 当 ADX 23.77(差 25 阈值 1.23)时直接给 0/9 分,L1 失效。建模文档自相矛盾(§1.3 说"不是堆砌指标简单打分",§3.8 又给了简单打分公式)。

2. **L3 硬切分单一阈值**:stance_confidence 必须 ≥ 0.65 才给 A/B 级,差 0.01 直接归零,病根和加权打分一样。

3. **组合因子是"加权聚合"不是"真组合"**:5 个组合因子(TruthTrend/BandPosition/CyclePosition/Crowding/MacroHeadwind)本质都是把多个原始因子线性加权,丢失原始信息细节,违背"组合因子应有化学反应"的设计意图。

4. **EventRisk 设计不符合中长线哲学**:Sprint 1.5q.1 已删除。事件影响通过价格/funding/宏观自然反映,不需要单独读。

5. **AI 介入太晚**:当前 AI 只在 L3 给 A/B/C 时被调用产 trade_plan,grade=none 时完全不调,导致系统在临界期无任何救场机制。

## 0.2 v1.3 核心改动

| 改动项 | v1.2 | v1.3 |
|---|---|---|
| 架构哲学 | 规则主导 + AI 在最后产策略 | AI 主导 + 规则做硬约束 |
| 判断方式 | 规则层做加权打分 / 硬条件查表 | AI 协作分析(6 AI 角色) + 规则只做硬约束 |
| 组合因子数 | 6 个(EventRisk 已删) | 1 个(只保留 CyclePosition 作锚点) |
| 因子总数 | 43 个 | 44 个(删 8 + 降级 3 + 新增 9) |
| 核心判断(regime/stance/grade) | 规则层产出 | AI 产出,规则做硬约束 |
| AI 调用频率 | 每 4h 整点 + 异动 | 每日 16:00 BJT(完整 A) + 异动 ±5% 简化 + 持仓期 4h 健康检查 |
| 网页输出 | 4 段叙事 + 散乱模块 | 5 层推演样式(交易员研判报告) |
| L5 AI | 设计意图但未接入 | 本次正式接入 |

## 0.3 v1.3 不变的核心原则

- **三道闸门(Filter / Gate / Adjudicator)** 概念保留,但实现方式变化
- **数据真实性**:不允许 mock,所有数据来自真实 API
- **§X 删除纪律**:旧代码必须删除,不堆叠
- **§Y commit 即 push**:不允许累积本地 commit
- **§Z 端到端 DB 行数 / 字段值断言**:不允许只 mock `.called=True`
- **质量第一,不为工期妥协**

---

# 第一部分:系统定位与设计哲学

## 1.1 系统定位

BTC 中长线低频双向波段策略辅助系统,辅助用户做真实交易决策。

**关键词**:
- **中长线**:持仓周期几周到几个月,不是日内交易
- **低频**:每日 1 次完整决策(对齐美东收盘),不追求高频
- **双向**:支持做多做空(空头判定更严格,v1 简化为 A/B/none 三档)
- **辅助**:不自动下单,给用户清晰的策略建议 + 完整推演说明

## 1.2 用户画像

- 中文用户,代码新手
- 信任系统的判断,但希望看到"系统为什么这么判断"
- 接受小仓位试错,但不接受"系统永远不出策略"
- 愿意用 token 成本换策略精准度("策略错误造成的损失远大于 token 费用")

## 1.3 核心设计哲学(v1.3)

### 1.3.1 AI 主导,规则硬约束

**为什么 AI 主导**:
- 中长线波段需要识别"临界过渡 / 化学反应 / 反常情景",这些规则难以穷举
- AI 看完所有 44 个因子能自然识别"主升浪中段 / 假突破 / 空头力竭" 等情景
- AI 输出可解释(narrative),不是黑盒分数

**为什么规则做硬约束**:
- 止损价、仓位上限、状态机迁移规则、极端事件检测必须确定性
- AI 不能突破这些约束(否则系统不可信)
- Validator 在 AI 输出后强制校验

### 1.3.2 不堆砌指标,不简单打分

v1.2 的"组合因子加权打分"模式被废弃。v1.3 让 AI 直接读原始因子做综合判断。

### 1.3.3 化学反应通过 AI 自然识别

不需要预设"funding+OI+LSR=拥挤共振"这种组合规则。AI 看到 funding 极端 + OI 飙升 + LSR 偏多 + 多头持续被清算,**自然识别为"极度多头拥挤,反向挤压风险"**。

### 1.3.4 临界值不踩空

AI 看到 ADX 23.77 不会给"0 分",而会判断"接近 25,趋势在确立中"。

### 1.3.5 反过度保守

v1.2 多重保守叠加导致系统几乎从不开仓。v1.3 由 AI 自然识别"多重证据补偿单一条件不足"的情景,不要求全条件命中。

### 1.3.6 质量第一,不为成本妥协

每月 ~$13-15 的 AI 调用成本,远低于策略错误造成的潜在损失。

---

# 第二部分:数据层 — 44 因子地基

## 2.1 总览

| 类别 | 数量 | 来源 |
|---|---|---|
| 价格类 | 10 | CoinGlass(K 线)+ 计算 |
| 衍生品类 | 10(删 1 + 降级 1) | CoinGlass |
| 链上类 | 15(删 2 + 升级 1 + 新增 6) | Glassnode(经 alphanode 中转) |
| 宏观类 | 4(删 5) | FRED |
| 机构 / 市场结构类(新增) | 2 | CoinGlass |
| 事件类 | 2 | yaml + CoinGlass spot |
| **总计** | **44** | |

## 2.2 价格类(10 个,全保留)

| # | 因子 | 来源 | 频率 | 用途 |
|---|---|---|---|---|
| 1 | BTC K 线 1H | CoinGlass | 每小时 | 执行确认 |
| 2 | BTC K 线 4H | CoinGlass | 每 4h | L1/L2 |
| 3 | BTC K 线 1D | CoinGlass | 每天 | L1/L2/L3 主判断 |
| 4 | BTC K 线 1W | CoinGlass | 每周 | L1/L2 长周期 |
| 5 | ATH 跌幅 | 从 K 线计算 | 每次运行 | CyclePosition |
| 6 | ATR 14 | 计算 | 每次运行 | L1 波动率 / L4 止损 |
| 7 | ADX 14(1D) | 计算 | 每天 | L1 趋势强度 |
| 8 | ADX 14(4H) | 计算 | 每 4h | L1 辅助 |
| 9 | 多周期方向一致性 | 计算 | 每 4h | L1 关键 |
| 10 | MA 20/60/120/200(1D) | 计算 | 每天 | L1 趋势结构 |

## 2.3 衍生品类(10 个,删 1 + 降级 1)

| # | 因子 | 来源 | 频率 | 角色 |
|---|---|---|---|---|
| 11 | funding_rate(币安永续) | CoinGlass | 8h | primary L4 |
| 12 | funding_rate_aggregated(全交易所 OI 加权) | CoinGlass | 8h | primary L4 |
| 13 | funding_rate_7d_avg | 计算 | 每小时 | primary L4 |
| 14 | funding_rate_z_score_90d | 计算 | 每天 | primary L4 |
| 15 | open_interest(全交易所聚合) | CoinGlass | 每小时 | primary L4 |
| 16 | oi_change_24h | 计算 | 每小时 | primary L4 |
| 17 | long_short_ratio | CoinGlass | 每小时 | primary L4 |
| 18 | lsr_change_24h | 计算 | 每小时 | primary L4 |
| 19 | liquidation_total / long / short(24h) | CoinGlass | 每小时 | primary L4 |
| 20 | put_call_ratio(期权) | CoinGlass | 每小时 | **display(降级,不参决策)** |

❌ **删除 1 个**:basis_annualized(funding 已覆盖此信号 90%,基差主要价值是套利)

## 2.4 链上类(15 个,删 2 + 升级 1 + 新增 6)

### 2.4.1 Primary(参与决策,11 个)

| # | 因子 | Glassnode 端点 | 频率 | 用途 |
|---|---|---|---|---|
| 21 | MVRV Z-Score | `/v1/metrics/market/mvrv_z_score` | 每天 | CyclePosition |
| 22 | NUPL | `/v1/metrics/indicators/net_unrealized_profit_loss` | 每天 | CyclePosition + L3 |
| 23 | LTH Supply | `/v1/metrics/supply/lth_sum` | 每天 | CyclePosition + L2 |
| 24 | 🆕 **STH Supply** | `/v1/metrics/supply/sth_sum` | 每天 | CyclePosition + L2 |
| 25 | Exchange Net Flow | `/v1/metrics/transactions/transfers_volume_exchanges_net` | 每小时 | L2 / L3 |
| 26 | 🆕 **LTH-MVRV** | `/v1/metrics/market/mvrv_more` | 每天 | CyclePosition + 顶/底信号 |
| 27 | 🆕 **STH-MVRV** | `/v1/metrics/market/mvrv_more` | 每天 | L2 短期支撑 |
| 28 | aSOPR(升级到 primary) | `/v1/metrics/indicators/sopr_adjusted` | 每天 | L3 |
| 29 | 🆕 **SSR** | `/v1/metrics/indicators/ssr` | 每天 | L5 / CyclePosition |
| 30 | 🆕 **HODL Waves** | `/v1/metrics/supply/hodl_waves` | 每周 | CyclePosition + 派发/累积 |
| 31 | 🆕 **CDD** | `/v1/metrics/indicators/cdd` | 每天 | L3 顶部领先指标 |

### 2.4.2 Display(只显示,4 个)

| # | 因子 | 来源 | 频率 |
|---|---|---|---|
| 32 | Realized Price | Glassnode | 每天 |
| 33 | LTH Realized Price | Glassnode breakdowns 聚合 | 每天 |
| 34 | STH Realized Price | Glassnode breakdowns 聚合 | 每天 |
| 35 | MVRV Ratio | Glassnode | 每天 (display, MVRV-Z 已覆盖) |
| 36 | SOPR | Glassnode | 每天 (display, aSOPR 已替代) |

❌ **删除 2 个**:Reserve Risk(MVRV-Z + LTH Supply 已覆盖 90%+)、Puell Multiple(ETF 时代失效,矿工占抛压 < 5%)

## 2.5 宏观类(4 个,删 5)

| # | 因子 | 来源 | 频率 | 用途 |
|---|---|---|---|---|
| 37 | DXY(美元指数) | FRED | 每天 | L5 流动性 |
| 38 | US10Y / DGS10 | FRED | 每天 | L5 利率方向 |
| 39 | VIX | FRED | 每天 | L5 风险偏好 |
| 40 | NASDAQ | FRED | 每天 | L5 风险资产同步性 |

❌ **删除 5 个**:DFF(US10Y 已覆盖)、CPI(频率太低)、失业率(同 CPI)、SP500(与 NASDAQ 重叠 90%+)、黄金价格(目前没用上)

## 2.6 机构 / 市场结构类(2 个,全新)

| # | 因子 | CoinGlass 端点 | 频率 | 用途 |
|---|---|---|---|---|
| 41 | 🆕 **ETF Flows** | `/api/etf/flow-history` | 每天 | L5 机构动向 |
| 42 | 🆕 **Bitcoin Dominance** | `/api/index/bitcoin-dominance` | 每天 | L5 行情阶段 |

## 2.7 事件 / 价格类(2 个)

| # | 因子 | 来源 | 频率 | 用途 |
|---|---|---|---|---|
| 43 | 事件日历(FOMC/CPI/NFP/PCE) | yaml | 每次运行 | **仅参考显示,不参与策略评分**(1.5q.1 后) |
| 44 | BTC 现货分钟价(USDT) | CoinGlass spot | 每分钟 | 网页顶栏 |

## 2.8 因子动态变化清单(v1.2 → v1.3)

### 删除的(8 个)
1. basis_annualized
2. Reserve Risk
3. Puell Multiple
4. DFF
5. CPI
6. 失业率
7. SP500
8. 黄金价格

### 降级到 display 的(3 个)
1. MVRV Ratio
2. SOPR
3. put_call_ratio

### 新增的(9 个)
1. STH Supply
2. LTH-MVRV
3. STH-MVRV
4. SSR
5. HODL Waves
6. CDD
7. aSOPR(升级到 primary)
8. ETF Flows
9. Bitcoin Dominance

### 数据源汇总
- **CoinGlass** via alphanode(共享中转,key COINGLASS_API_KEY):BTC 现货 + 衍生品 + ETF + Dominance
- **Glassnode** via alphanode(同中转,key GLASSNODE_API_KEY,通常和 CoinGlass key 同值):所有链上指标
- **FRED**(独立):宏观 4 个

---

# 第三部分:架构 — AI 主导 + 规则硬约束

## 3.1 整体架构图

```
┌─────────────────────────────────────────────────┐
│  原始 44 因子(数据层)                            │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 1: 规则层(轻量,只做硬约束 + CyclePosition) │
│                                                   │
│  做的事:                                         │
│  - 计算 hard_invalidation_levels(止损价)         │
│  - 计算 position_cap_base(仓位上限基础值)        │
│  - 状态机迁移规则(14 档)                         │
│  - 极端事件检测(进 PROTECTION)                   │
│  - 数据降级判定(Fallback Level 1-3)              │
│  - 计算 CyclePosition(9 档周期标签,作锚点)       │
│                                                   │
│  不做:                                           │
│  - 不做 grade 判定 → 交给 L3 AI                   │
│  - 不做 stance / regime 判定 → 交给 L1/L2 AI      │
│  - 不做 macro_stance 判定 → 交给 L5 AI            │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 2: AI 协作分析(5 个层 AI)                  │
│                                                   │
│  L1 AI:市场状态分析师                             │
│  L2 AI:方向结构分析师(读 L1 输出)                │
│  L3 AI:机会判断分析师(读 L1+L2 输出)             │
│  L4 AI:风险评估分析师(读 L1+L2+L3 输出)          │
│  L5 AI:宏观环境分析师(独立)                      │
│                                                   │
│  每个 AI 在严格 System Prompt 框架内,             │
│  输出结构化 JSON                                  │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 3: 主裁 AI(综合 + 仲裁)                    │
│                                                   │
│  - 读所有 5 个层 AI 输出                          │
│  - 检测层间矛盾 + 仲裁                            │
│  - 产 trade_plan(在 L4 硬约束内)                  │
│  - 写 5 层推演叙事(交易员研判报告)                │
│  - 必须包含反向证据 + 改变判断条件                 │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 4: Validator 校验(10 条硬规则)              │
│                                                   │
│  违反 → 强制覆盖 + 标记 'ai_overridden'           │
└─────────────────────────────────────────────────┘
                    ↓
        最终策略 + 5 层推演说明 + 写 DB
```

## 3.2 规则层职责详细定义

### 3.2.1 hard_invalidation_levels(止损价计算)

**做多场景**:
- 找最近 4H/1D 的主要 swing low(HL 序列)
- 取最低的 3 个 swing low 作为候选
- 减去 ATR × 1.5 的缓冲
- 输出列表:`[swing_low_1 - 1.5×ATR, swing_low_2 - 1.5×ATR, swing_low_3 - 1.5×ATR]`

**做空场景**:镜像

**输出字段**:`l4.hard_invalidation_levels: list[float]`

**纪律**:**这是唯一权威的止损价来源。AI 必须从这个列表里选,不能自创**。

### 3.2.2 position_cap_base(仓位上限基础值)

**计算**:基础 70%
- 若 L4 AI 给出 risk_level=low → ×1.0 = 70%
- 若 elevated → ×0.7 = 49%
- 若 critical → ×0.3 = 21%

**纪律**:**AI 给的 max_position_size_pct 必须 ≤ position_cap_base**。

### 3.2.3 状态机迁移规则(14 档,见第五部分详述)

不变,沿用 v1.2 §5。

### 3.2.4 极端事件检测

**触发条件**(任一满足):
- BTC 1h 价格 ±10%
- BTC 24h 价格 ±20%
- VIX 1d 涨幅 > 30%
- 重大事件实际数值 vs 预期 偏差 ≥ 2σ

**触发后**:状态机强制进入 PROTECTION,AI 调用暂停 30 分钟。

### 3.2.5 数据降级判定(Fallback Level 1-3)

| Level | 触发 | 行为 |
|---|---|---|
| 0(健康) | 数据完整度 ≥ 95% | 正常运行 |
| 1(轻度) | 完整度 80-95% 或 1 个数据源失败 | AI 调用,但 confidence 上限 0.7 |
| 2(中度) | 完整度 60-80% 或 2 个数据源失败 | 不调用 AI,走规则模板,permission 强制 watch |
| 3(严重) | 完整度 < 60% 或 3+ 数据源失败 | 状态机强制 hold_only,推送告警 |

### 3.2.6 CyclePosition 计算(唯一保留的组合因子)

**输入**(8 个主指标):
- MVRV Z-Score
- NUPL
- LTH Supply 90d 变化
- STH Supply 90d 变化
- LTH-MVRV
- 距 ATH 跌幅
- HODL Waves(>1y 区段比例)
- SSR

**输出**:9 档之一 + confidence

| 档位 | 主要特征 |
|---|---|
| accumulation(底部累积) | MVRV-Z < 0,NUPL < 0,LTH 持续上升,STH 持续下降,距 ATH 跌幅 > 70% |
| early_bull(牛市早期) | MVRV-Z 0.5-2.0,NUPL 0.25-0.5,LTH 上升,距 ATH 跌幅 30-70% |
| mid_bull(牛市中期) | MVRV-Z 2.0-4.0,NUPL 0.5-0.65,LTH 平稳或微降 |
| late_bull(牛市晚期) | MVRV-Z 4.0-6.0,NUPL 0.65-0.75,LTH 开始下降,LTH-MVRV > 3 |
| distribution(顶部派发) | MVRV-Z > 6,NUPL > 0.75,LTH 大幅下降,HODL Waves >1y 区段塌缩,SSR 极低 |
| early_bear(熊市早期) | MVRV-Z 4-6 但下降,NUPL 0.5-0.75 但下降,LTH 持续下降 |
| mid_bear(熊市中期) | MVRV-Z 0-2,NUPL 0-0.25,LTH 触底 |
| late_bear(熊市晚期) | MVRV-Z < 0 但回升,NUPL 接近 0,STH-MVRV < 1,SSR 高位 |
| unclear(看不清) | 主指标投票池为空或分歧严重 |

**实现方式**:每个主指标输出"投票"(投哪一档),取得票最多的。投票池为空 → unclear,confidence=0.30。

**输出字段**:
- `composite_factors.cycle_position.cycle_position`(标签)
- `composite_factors.cycle_position.cycle_confidence`(0.0-1.0)
- `composite_factors.cycle_position.voting_details`(每个主指标的投票)
- `composite_factors.cycle_position.last_stable_cycle_position`(展示用)

## 3.3 各层 AI 职责详细定义

### 3.3.1 L1 AI — 市场状态分析师

**输入**:
- 8 个 L1 因子(ADX 1D/4H、多周期一致、MA 20-200 排列、价格 vs MA200、ATR、ATR 历史分位、价格 7d 涨跌)
- BTC 30 天历史价格数据(让 AI 看趋势)
- 当前 CyclePosition 标签(参考)

**任务**:判断 BTC 当前的市场性格 — 趋势性还是震荡性,波动稳不稳。

**输出 JSON Schema**:
```json
{
  "regime": "trend_up" | "trend_down" | "transition_up" | "transition_down" |
            "range_high" | "range_mid" | "range_low" | "chaos",
  "volatility": "low" | "normal" | "elevated" | "extreme",
  "key_observations": [
    "中文 1 句话描述,要讲组合关系不是简单罗列数值"
    // 3-5 条
  ],
  "confidence_tier": "high" | "medium" | "low",
  "narrative": "中文 2-3 句话,L1 视角的简短分析"
}
```

**System Prompt(草稿)**:

```
你是 BTC 中长线波段交易系统的 L1 市场状态分析师。

【你的任务】
判断 BTC 当前是真趋势还是震荡,波动稳不稳。这是判断"市场性格"的层。

【你必须基于的数据】
- ADX 14 日(衡量趋势强度)和 ADX 4 小时
- MA 20/60/120/200 的排列状态
- 当前价格 vs MA 200 位置
- 多周期(4H/1D/1W)方向一致性
- ATR 14 和历史分位
- 价格 7 天变化

【输出 regime 的标准】
- trend_up:ADX 强 + 多周期一致看多 + MA 排列正确(短上长)
- trend_down:镜像
- transition_up / transition_down:多周期方向一致但 ADX 在临界(20-25),
  或 MA 部分对部分错,趋势在确立但未完成
- range_high / mid / low:ADX 弱 + MA 散乱,价格在区间高/中/低位置
- chaos:多周期分歧严重 + ATR 极高,失序状态

【输出 volatility 的标准】
- low:ATR < 历史 30 分位
- normal:ATR 30-60 分位
- elevated:ATR 60-85 分位
- extreme:ATR > 85 分位

【你必须做的】
1. 读完所有数据,综合判断
2. 输出严格 JSON 格式
3. key_observations 要讲组合关系(例:"ADX 临界 + 多周期一致 = 趋势在确立中"),不能简单列数值
4. 必须给信心档(high/medium/low)

【你绝对不能做的】
1. 不允许给"中性偏多"或"中性偏空"等模糊标签
2. 不允许在 ADX 23.77 这种临界值时直接给 chaos 或 range_low(临界要识别为 transition_*)
3. 不允许忽略矛盾信号(若 ADX 强但 MA 没排列对,必须明确指出)
4. 不允许"这次不一样"的判断 — 历史模式必须引用
5. 不允许情绪化语言("可能会"/"似乎"等模糊词必须替换)
6. 数据不足时(数据降级)必须给 low 信心,不能硬撑

【你必须诚实承认的】
- 数据冲突时,如实指出冲突
- 临界值时,如实说"在边界,可能向任何方向"
- 信号不足时,给 low 信心
- 历史无明确先例时,如实说"无类似先例参考"

【输出格式】
严格 JSON,首字符 `{`,尾字符 `}`,不要任何 markdown 代码块。
```

### 3.3.2 L2 AI — 方向结构分析师

**输入**:
- L1 AI 的输出(让 L2 在 L1 基础上判断)
- L2 因子(swing high/low、价格结构 HH+HL、LTH/STH Realized Price、funding、ATR、CyclePosition、Exchange Net Flow)
- 30 天历史

**任务**:判断 stance(多空方向)+ phase(波段位置)+ 当前价格在关键位置的位置。

**输出 JSON Schema**:
```json
{
  "stance": "bullish" | "bearish" | "neutral",
  "stance_confidence_tier": "high" | "medium" | "low" | "none",
  "phase": "early" | "mid" | "late" | "exhausted" | "unclear" | "n_a",
  "phase_evidence": "中文一句话",
  "structure_features": {
    "hh_count": int,
    "hl_count": int,
    "lh_count": int,
    "ll_count": int,
    "latest_structure": "HH+HL" | "LH+LL" | "mixed"
  },
  "key_levels": {
    "nearest_support": float,
    "nearest_resistance": float,
    "major_support": float,
    "major_resistance": float,
    "current_position": "near_support" | "mid_range" | "near_resistance" | "above_all_key_levels"
  },
  "long_cycle_context": {
    "cycle_position": "...",  // 引用规则算的 CyclePosition
    "ai_assessment": "agree" | "disagree" | "neutral",  // AI 是否同意规则
    "ai_alternative": "..." | null  // AI 不同意时给出的替代判断
  },
  "key_observations": [...],
  "narrative": "中文 2-3 句"
}
```

**System Prompt(核心要点)**:

```
你是 BTC 中长线波段交易系统的 L2 方向结构分析师。

【你的任务】
基于 L1 的市场状态判断,进一步判断:
1. stance(方向):多空哪边占优
2. phase(波段位置):走到第几段
3. key_levels(支撑阻力):当前在什么位置
4. 长周期背景:是否同意规则算的 CyclePosition

【stance 判定原则】
- bullish:HH+HL 结构成立 + 价格站稳关键支撑 + LTH Supply 上升 + 多周期偏多
- bearish:镜像
- neutral:结构混乱或方向冲突,这是合法输出,不要硬给方向

【stance_confidence_tier 判定】
- high:核心证据 3/3 全满足(结构 + 多周期一致 + 长周期支持)
- medium:核心证据 2/3 满足
- low:核心证据 1/3 满足或多重矛盾
- none:无任何方向证据,等同 neutral

【phase 判定原则】
- early:扩展比 < 50%(从最近 swing low 到当前距离,占 swing 范围的比例)
- mid:50-100%
- late:100-138%
- exhausted:> 138%
- unclear:数据不足或场景不明
- n_a:stance=neutral 时使用

【绝对不允许】
1. 不允许在 stance=neutral 时给非 n_a 的 phase
2. 不允许 stance_confidence_tier 给 high 但只有 1 项证据
3. 不允许给 0.335 这种连续数字 — 必须用 4 档(high/medium/low/none)

【长周期背景纪律】
规则算了 CyclePosition(9 档),你必须:
- 默认采纳规则结论(大部分情况)
- 但若你看到价格行为明显不像规则给的档位(例如规则给 early_bull
  但价格已创新高 + LTH 大幅派发),你可以在 long_cycle_context.ai_assessment
  里给 "disagree",并在 ai_alternative 里给出你认为的真实档位 + 理由
- 不允许无理由 disagree(必须有充分证据)
```

### 3.3.3 L3 AI — 机会判断分析师

**输入**:
- L1 + L2 AI 输出
- L3 因子(LTH Supply、STH Supply、Exchange Net Flow、ETF Flows、aSOPR、HODL Waves、CDD)
- CyclePosition 标签
- 当前状态机状态

**任务**:判断当前是不是好的动手时机 + 给机会等级 A/B/C/none + 给 execution_permission。

**输出 JSON Schema**:
```json
{
  "opportunity_grade": "A" | "B" | "C" | "none",
  "execution_permission": "can_open" | "cautious_open" | "ambush_only" |
                           "no_chase" | "watch" | "hold_only" | "protective",
  "matched_combinations": [
    {
      "combination_name": "强信心 + 早中期 + 好位置",
      "matched": true,
      "evidence": "...",
      "tier_contribution": "A"
    }
    // 列出 2-4 个评估的组合
  ],
  "necessary_conditions_met": {
    "regime_ok": bool,
    "stance_ok": bool,
    "no_anti_pattern": bool
  },
  "supporting_evidence": [...],  // 至少 3 条
  "counter_arguments": [...],    // 至少 1 条反向证据
  "key_observations": [...],
  "narrative": "中文 3-4 句"
}
```

**System Prompt(核心要点)**:

```
你是 BTC 中长线波段交易系统的 L3 机会判断分析师。

【你的任务】
基于 L1 + L2 的判断,确定:
1. opportunity_grade(机会等级):A / B / C / none
2. execution_permission(执行许可):决定开仓 / 谨慎 / 埋伏 / 观望

【做多机会等级判定(用必要 + 充分组合,不要全条件命中)】

必要条件(任一不满足 → 直接 none):
- L1 regime 不是 chaos / trend_down
- L2 stance 不是 bearish / neutral
- 没有反模式触发(假突破 / 逆势)

A 级机会(以下任一组合满足即可):
- 组合 a:L2 confidence high + L2 phase=mid + 位置 near_support
- 组合 b:L2 confidence medium + 多重证据(LTH Supply 上升 +
  ETF 5d 净流入 + 多周期一致 + 价格站稳 MA200)
- 组合 c:L2 confidence high + L2 phase=early + cycle=early_bull
  + LTH Supply 上升 + STH Supply 下降(底部累积特征)

B 级机会(以下任一组合满足即可):
- 组合 a:L2 confidence medium + L2 phase=mid + 位置不是 above_all_key_levels
- 组合 b:L2 confidence low + 大量证据支持(任 4 项:LTH 上升 / ETF 流入 /
  HODL Waves >1y 上升 / SSR 高 / aSOPR 接近 1 / 多周期一致)
- 组合 c:L2 confidence high + L2 phase=late + 位置 mid_range(B 级回补机会)

C 级机会(以下任一组合满足即可):
- 组合 a:L2 stance=bullish + 任何 1 项支持证据 + 长周期非熊市
- 组合 b:试探机会(系统连续 30+ 天 grade=none 的兜底)

none:以上都不满足

【做空机会等级(v1 简化为 A/B/none,不允许 C)】

A 级做空(必要 + 充分,任一组合满足):
- 必要:cycle ∈ {distribution, early_bear, mid_bear} +
       L2 stance=bearish + L1 regime ∈ {trend_down, transition_down, range_high}
- 组合 a:L2 confidence high + 拥挤 + 位置 near_resistance
- 组合 b:LTH 大幅派发 + ETF 净流出 + HODL Waves >1y 塌缩 + LTH-MVRV > 3.5

B 级做空(必要条件同 A,充分条件略宽):
- 充分组合:L2 confidence medium + 任 3 项支持证据

【execution_permission 给定原则】
- A 级 + 风险低 → can_open
- A 级 + 风险中 → cautious_open
- B 级 → cautious_open 或 ambush_only
- C 级 → ambush_only(只能埋伏单)
- none → watch

【你必须做的】
1. 必须明确说"命中了哪个组合"(matched_combinations)
2. 必须列至少 3 条支持证据
3. 必须列至少 1 条反向证据(counter_arguments)
4. 不允许全条件命中后还自己降级 — 一旦组合命中,就给该等级
5. 不允许"组合 b 部分满足" — 要么全满足,要么不满足

【你绝对不能做的】
1. 不允许跳过必要条件检查
2. 不允许在 stance=neutral 时给 A/B/C
3. 不允许在 PROTECTION 状态时给非 none
4. 不允许在数据降级 Level 2+ 时给 A 级
```

### 3.3.4 L4 AI — 风险评估分析师

**输入**:
- L1+L2+L3 AI 输出
- L4 因子(funding 全维度、OI 变化、LSR、清算总额/方向、价格结构、CyclePosition)
- 规则计算的 hard_invalidation_levels 和 position_cap_base

**任务**:判断风险等级 + 微调仓位上限 + 验证止损价。

**输出 JSON Schema**:
```json
{
  "risk_level": "low" | "elevated" | "critical",
  "crowding_assessment": "extreme_long" | "mild_long" | "normal" |
                          "mild_short" | "extreme_short" | "exhaustion_signal" |
                          "false_breakout_warning",
  "position_cap_pct": float,  // ≤ position_cap_base
  "hard_invalidation_chosen": float,  // 从规则算的列表选
  "hard_invalidation_distance_pct": float,
  "key_observations": [...],
  "counter_arguments": [...],
  "narrative": "中文 2-3 句"
}
```

**System Prompt(核心要点)**:

```
你是 BTC 中长线波段交易系统的 L4 风险评估分析师。

【你的任务】
判断当前的风险情景 + 微调仓位上限 + 选定止损价。

【crowding_assessment 情景】
- extreme_long:funding z>2 + OI 24h>+20% + LSR>1.5 + Long Liquidation
  → 多头极度拥挤,反向挤压风险高
- extreme_short:funding z<-2 + LSR<0.7 + Short Liquidation
  → 空头极度拥挤
- exhaustion_signal:funding 极端负 + 价格不跌 + Short Liquidation
  → 空头力竭可能反转(关键化学反应信号)
- false_breakout_warning:价格新高 + OI 没跟上 + funding 失败转正
  → 假突破风险
- normal:funding/LSR 都在正常区间
- mild_*:轻度倾向

【风险等级与拥挤度对应】
- normal / mild_* → low
- extreme_* → elevated
- exhaustion_signal / false_breakout_warning → elevated
- 配合极端事件 → critical

【position_cap_pct 计算】
基础值由规则给(position_cap_base = 70% × risk_multiplier)。你可以:
- 维持基础值(大部分情况)
- 微调 -10% 到 -20%(若有特殊风险)
- 不能超过基础值

【hard_invalidation_chosen 选定】
规则给了一个列表(hard_invalidation_levels),你必须从中选 1 个:
- 默认选最近的(最严)
- 若数据不足或 ATR 极大,选中位的
- 不允许自创止损价

【你必须做的】
1. 必须从 hard_invalidation_levels 选,不能自创
2. position_cap_pct 必须 ≤ position_cap_base
3. 必须给出 hard_invalidation_distance_pct(止损距离百分比)
4. 必须列至少 1 条反向证据
```

### 3.3.5 L5 AI — 宏观环境分析师(本次新增)

**输入**:
- L5 因子(DXY、US10Y、VIX、NASDAQ、ETF Flows、BTC.D)
- 事件日历(未来 72h)
- BTC 30 天价格 + BTC-NASDAQ 60d 相关性
- BTC 30 天历史(用于判断是否进入极端事件)

**任务**:判断宏观环境 + macro_headwind_score + 检测极端事件。

**输出 JSON Schema**:
```json
{
  "macro_stance": "extreme_risk_off" | "risk_off" | "risk_neutral" | "risk_on",
  "macro_headwind_score": int,  // -10 到 +10
  "liquidity_environment": "中文,流动性叙事 (DXY+US10Y+VIX 综合)",
  "risk_asset_synchrony": "中文,纳指顺/逆 + BTC-纳指相关性",
  "institutional_flow": "中文,ETF + BTC.D 综合",
  "extreme_event_detected": bool,
  "extreme_event_description": "中文" | null,
  "key_observations": [...],
  "narrative": "中文 200 字内"
}
```

**System Prompt(核心要点)**:

```
你是 BTC 中长线波段交易系统的 L5 宏观环境分析师。

【你的任务】
读宏观数据 + 事件日历,综合判断 BTC 当前的宏观环境。

【macro_stance 判定】
- risk_on:DXY 明显走弱 + US10Y 下行 + VIX 低位 + NASDAQ 上行 + ETF 净流入
- risk_neutral:多数维度在正常区间,无明显方向
- risk_off:DXY 走强 + US10Y 上行 + VIX 偏高 + NASDAQ 下行 + ETF 净流出
- extreme_risk_off:同上但程度极端,VIX > 30 或 NASDAQ 单日 -3%+

【macro_headwind_score 计算】
-10(强逆风)到 +10(强顺风),你综合判断给数值。
注意:这个分数是给 L4 用来调整 position_cap 的乘数依据。

【extreme_event 检测】
任一满足 → extreme_event_detected = true:
- VIX 1d 涨幅 > 30%
- 重大事件实际数值 vs 预期 偏差 ≥ 2σ
- DXY 1d 涨幅 > 1.5%
- US10Y 1d 上行 > 20bp

【你必须输出 3 段叙事】
1. 流动性环境(DXY+US10Y+VIX 综合,1-2 句)
2. 风险资产同步性(NASDAQ + BTC-纳指相关性,1-2 句)
3. 机构资金动向(ETF Flows + BTC.D,1-2 句)

【特殊规则】
若 BTC-NASDAQ 60d 相关性 > 0.7,所有宏观项权重 × 1.5
(意思是 BTC 跟着美股走的时候,美股的影响放大)
```

### 3.3.6 主裁 AI — 综合裁决官

**输入**:
- 5 个层 AI 的输出(完整)
- 状态机当前状态 + on_enter_effects 上下文
- 持仓信息(若有)
- 14 档状态机的 allowed_transitions
- 规则计算的 hard_invalidation_levels 和 position_cap_base

**任务**:
1. 检测层间矛盾,做最终仲裁
2. 产出 final action(从 allowed_transitions 选)
3. 产 trade_plan(若 grade ∈ {A, B, C})
4. 写 5 层推演叙事(交易员研判报告)

**输出 JSON Schema**:
```json
{
  "action": "...",  // 必须在 allowed_transitions
  "direction": "long" | "short" | null,
  "confidence": float,  // 0.0-1.0,但要受 Validator 校验
  "rationale": "中文 2-3 句",
  "narrative": "中文 5 层推演整体叙事",

  "layer_summaries": {
    "L1": "中文 2-4 句,L1 视角的总结",
    "L2": "中文 2-4 句",
    "L3": "中文 2-4 句",
    "L4": "中文 2-4 句",
    "L5": "中文 2-4 句"
  },

  "opportunity_grade": "...",  // 必须等于 L3 输出
  "trade_plan": null | {
    "direction": "long" | "short",
    "confidence_tier": "high" | "medium" | "low",
    "max_position_size_pct": float,  // 必须 ≤ L4 position_cap_pct
    "entry_zones": [
      {"price_low": ..., "price_high": ..., "allocation_pct": ...}
    ],
    "stop_loss": float,  // 必须 ∈ hard_invalidation_levels
    "take_profit_plan": [
      {"price": ..., "size_pct": ...}
    ],
    "dynamic_notes": "中文"
  },

  "primary_drivers": [
    {"evidence_ref": "...", "text": "..."}
  ],
  "counter_arguments": [
    {"text": "..."}
  ],
  "what_would_change_mind": ["...", "...", "..."],

  "conflict_resolution": "中文,若无矛盾写 '无层间矛盾'",

  "transition_reason": "中文,说明状态迁移原因"
}
```

**System Prompt(核心要点)**:

```
你是 BTC 中长线波段交易系统的主裁决官。读完 5 个层 AI 的分析,
做最终决策。

【你的核心任务】
1. 识别层间矛盾(若 L1 trend_up 但 L2 bearish,这是矛盾)
2. 仲裁矛盾(必须明确说哪边对)
3. 给最终 action(必须在 allowed_transitions 内)
4. 若 grade ∈ {A, B, C},给完整 trade_plan
5. 写 5 层推演叙事(交易员研判报告样式)

【十条纪律(严格执行)】
1. action 必须在 allowed_transitions 列表里
2. opportunity_grade 必须严格等于 L3 AI 给的(不可修改)
3. trade_plan.stop_loss 必须从 L4 给的 hard_invalidation_levels 选
4. trade_plan.max_position_size_pct 必须 ≤ L4 给的 position_cap_pct
5. 持仓中必须明确评估 thesis_still_valid
6. what_would_change_mind 至少 3 条,必须可客观判断
7. 证据冲突时保守(降低 confidence,缩仓位)
8. 输出严格 JSON,首字符 `{`,尾字符 `}`
9. 必须包含至少 1 条反向证据(counter_arguments)
10. 严禁"这次不一样"判断,必须引用历史先例

【layer_summaries 写作要求】
每个层 2-4 句中文,**用交易员能看懂的语言**,不是机器输出。
不要简单复述层 AI 的输出,要用你自己的角度总结这一层告诉了你什么。

【conflict_resolution 写作要求】
若 5 个层 AI 输出一致 → 写"无层间矛盾"
若有矛盾 → 必须明确说:
- 哪 2 层之间矛盾
- 你认为哪边对(必须有依据)
- 因为这个矛盾你做了什么调整(降级/收紧/缩仓)

【你绝对不能做的】
1. 不允许越过 Validator 的硬约束
2. 不允许给 stance/regime/grade 改名(必须用各层 AI 给的标签)
3. 不允许在 PROTECTION 状态时给非 watch/hold 的 action
4. 不允许 confidence > 0.7 当数据降级 Level 1+
5. 不允许给 trade_plan 当 grade=none
6. 不允许跳过 layer_summaries 任何一层
```

## 3.4 Validator 校验框架(10 条硬规则)

```
1. AI 给的 stop_loss 必须从 hard_invalidation_levels 选
   → 否则:强制覆盖为 hard_invalidation_levels[0],notes 添加 "stop_loss_overridden_by_validator"

2. AI 给的 max_position_size_pct 必须 ≤ position_cap_pct
   → 否则:强制 cap,notes 添加 "position_capped_by_validator"

3. AI 给的 action 必须在 allowed_transitions
   → 否则:强制为最接近的合法 action,notes 添加 "action_overridden_by_validator"

4. AI 引用的 evidence_ref 必须在 evidence_cards 真实存在
   → 否则:从 primary_drivers 删除该项,notes 添加 "missing_evidence_ref"

5. PROTECTION 状态不允许 trade_plan
   → 否则:trade_plan 强制 null,action 强制 watch

6. AI 必须在 narrative 包含至少 1 条 counter_arguments
   → 否则:notes 添加 "missing_counter_argument"

7. AI 给的 confidence 必须 ≤ data_completeness × historical_precedent_match
   → 数据降级 Level 1+ 时,confidence 必须 < 0.7

8. opportunity_grade 必须严格等于 L3 AI 输出
   → 否则:覆盖为 L3 给的,notes 添加 "grade_overridden_to_l3"

9. 若 grade=none,trade_plan 必须 null
   → 否则:强制 null,notes 添加 "trade_plan_dropped_for_none_grade"

10. 主裁 AI 必须输出 conflict_resolution 字段(可以是"无层间矛盾")
    → 否则:notes 添加 "conflict_resolution_missing"
```

---

# 第四部分:状态机(14 档,沿用 v1.2 §5)

## 4.1 状态定义(不变)

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

## 4.2 核心迁移规则(沿用 v1.2 §5.2)

不展开,沿用 v1.2 现有规则。

## 4.3 三条核心纪律(不变)

1. 不允许从 *_HOLD 直接跳到反向 PLANNED,必须经 EXIT → FLIP_WATCH 完整路径
2. FLIP_WATCH 冷却期强制;1H 信号永远不能单独触发方向切换
3. PROTECTION 全局入口,唯一出口经 POST_PROTECTION_REASSESS

---

# 第五部分:频率与触发设计

## 5.1 数据收集频率(不变)

数据收集仍按各因子频率运行,与 AI 决策频率解耦:
- 价格:1H/4H/1D/1W,每对应频率运行
- 衍生品:多数 1H,资金费率 8H
- 链上:多数每天,Exchange Net Flow 每小时
- 宏观:每天

数据收集**不消耗 AI token**,只消耗 API 调用配额。

## 5.2 AI 决策频率(v1.3 重新设计)

### 5.2.1 空仓状态(FLAT / *_PLANNED / FLIP_WATCH)

| 触发条件 | AI 方案 | 频率 | 单次成本 |
|---|---|---|---|
| 每日 16:00 BJT(美东收盘) | 完整 A(6 AI 协作) | 1 次/天 | ~$0.30 |
| 价格异动 ±5% | 简化 A(1 个应急 AI) | 0-2 次/天平均 | ~$0.10 |
| 手动触发 | 完整 A | 按需 | ~$0.30 |

### 5.2.2 持仓状态(*_OPEN / *_HOLD / *_TRIM)

| 触发条件 | AI 方案 | 频率 | 单次成本 |
|---|---|---|---|
| 每日 16:00 BJT | 完整 A(6 AI) | 1 次/天 | ~$0.30 |
| 每 4h 整点 | 持仓健康检查(1 AI 简化版) | 6 次/天 | ~$0.05 × 6 |
| 价格异动 ±3% | 简化 A(1 AI) | 立刻 | ~$0.10 |
| 价格触及 stop_loss | 规则平仓(无 AI) | 立刻 | $0 |
| 手动触发 | 完整 A | 按需 | ~$0.30 |

### 5.2.3 极端状态(PROTECTION / POST_PROTECTION_REASSESS)

按 v1.2 §5 既定规则处理。AI 调用暂停。

### 5.2.4 总成本估算

按 30% 持仓 / 70% 空仓比例:

```
空仓期(70%):
  每日完整 A:30 × 0.7 × $0.30 = ~$6.3/月
  异动触发:5 × $0.10 = ~$0.5/月

持仓期(30%):
  每日完整 A:30 × 0.3 × $0.30 = ~$2.7/月
  4h 健康检查:6 × 30 × 0.3 × $0.05 = ~$2.7/月
  异动触发:8 × $0.10 = ~$0.8/月

总计:~$13-15/月
```

## 5.3 简化 A(应急 AI)规格

**用途**:价格异动触发时快速判断"当前持仓/挂单是否需要立即调整"

**输入**:
- 当前完整 strategy_state(上次完整 A 的输出)
- 异动后的最新价格 + 关键因子(funding, LSR, OI 变化)
- 当前状态机状态 + 持仓信息

**任务**:
- 判断"上次完整 A 给的策略是否仍然成立"
- 给出"立即行动建议":maintain / 紧急平仓 / 紧急调整 / 等待下次 16:00

**输出**:简化 JSON(快速决策)
```json
{
  "thesis_still_valid": "valid" | "weakened" | "invalidated",
  "immediate_action": "maintain" | "emergency_exit" | "tighten_stop" | "wait_next_full",
  "reasoning": "中文 2-3 句"
}
```

**调用模型**:同 sonnet-4-5,但 prompt 短,max_tokens 500,~30 秒响应。

## 5.4 持仓健康检查 AI 规格

**用途**:持仓期每 4h 整点跑一次,确认持仓 thesis 是否仍然成立

**输入**:
- 上次完整 A 的输出
- 最新 4h 周期的关键因子
- 当前持仓 P&L

**输出**:
```json
{
  "thesis_status": "valid" | "weakening" | "challenged",
  "max_favorable_pct": float,
  "max_adverse_pct": float,
  "should_trigger_full_a": bool,  // 若 challenged,提前触发完整 A
  "narrative": "中文 1-2 句"
}
```

---

# 第六部分:网页输出规格

## 6.1 网页结构

```
[顶栏 BTC 价格 + 状态条 + 系统自检入口]
[AI 策略说明区(本次重写)]
[持仓预览灰框(状态机条件显示)]
[原始因子卡区(31 张 primary + 13 张 display)]
[CyclePosition 卡(嵌入到 L2 推演段内,不单独成区)]
[事件日历(参考显示)]
```

## 6.2 删除的模块

- ❌ 5 张组合因子卡(整块删除)
- ❌ 当前 AI 策略说明区(布局乱,重写)

## 6.3 AI 策略说明区(重写,5 层推演样式)

```
┌─────────────────────────────────────────────┐
│ 🎯 AI 策略建议                                  │
├─────────────────────────────────────────────┤
│ 方向:观望  机会等级:none  执行许可:watch         │
├─────────────────────────────────────────────┤
│ 【系统逐层推演】                                  │
│                                                  │
│ 📊 L1 市场状态                                   │
│   regime: transition_up · volatility: low        │
│   关键观察:                                       │
│     ✅ ADX 1D 23.77 + 多周期一致 → 趋势在确立中  │
│     ❌ MA 200 未对齐 → 长期还没站稳              │
│   L1 分析:市场处于过渡上行,可耐心等待。          │
│   信心档:medium                                  │
│                                                  │
│ 🎯 L2 方向结构                                   │
│   stance: bullish · phase: unclear               │
│   长周期位置:early_bull(置信度 0.748,AI 同意)  │
│   关键观察:                                       │
│     ✅ HH+HL 结构 → 看多结构成立                 │
│     ✅ LTH Supply +1.63%/90d → 长持有者屯币      │
│     ❌ 1W stance=neutral → 多周期未共振          │
│   L2 分析:看多但信心 medium,1W 没和 1D 共振。   │
│   信心档:medium                                  │
│                                                  │
│ 🏆 L3 机会执行                                   │
│   grade: none · permission: watch                │
│   评估的充分组合:                                 │
│     ❌ 强信心 + 早中期 + 好位置(差信心)          │
│     ❌ 中等信心 + 多重证据(差 1 项证据)          │
│   反向证据:                                       │
│     - ETF 5d 净流入 → 机构在买                   │
│   L3 分析:虽然规则上不到 A/B/C,但综合看是早期   │
│           布局窗口。建议观望但每日重检。           │
│   信心档:medium                                  │
│                                                  │
│ 🛡️ L4 风险失效                                   │
│   risk: low · position_cap: 70%                  │
│   关键观察:                                       │
│     ❌ 极度多头拥挤(funding z=0.8,未达 ±2)     │
│     ✅ 拥挤度正常                                 │
│   止损:72,500(从 hard_invalidation 列表选)     │
│   仓位上限:70%                                   │
│   L4 分析:风险等级低,如果出机会允许 70% 上限。   │
│   信心档:high                                    │
│                                                  │
│ 🌍 L5 宏观背景                                   │
│   stance: risk_neutral · headwind: -1            │
│   AI 综合分析:                                    │
│   1. 流动性环境:DXY 弱 + US10Y 平稳 + VIX 低位 │
│      → 流动性偏宽松                               │
│   2. 风险资产同步:NASDAQ +2.3%/30d → 美股顺风   │
│      BTC-纳指相关性 0.65,偏正                    │
│   3. 机构动向:ETF 5d +$680m + BTC.D 60.3% 平稳  │
│      → 机构在买,无 altseason 干扰                │
│   L5 分析:宏观偏顺风但没到强顺风,无极端事件。    │
│   信心档:high                                    │
├─────────────────────────────────────────────┤
│ 【综合结论】                                       │
│ 所有指标朝好方向走,但还没扣扳机时机。系统在等    │
│ "L2 信心从 medium 升 high" + "L3 从 none 升 B/A" │
│ 两个信号同时确立。                                │
│                                                  │
│ 【交易计划】                                       │
│ 当前为 watch,无入场计划                           │
│                                                  │
│ 【硬失效位】                                       │
│ 72,500(若价格跌破,系统判定多头论点失效)          │
│                                                  │
│ 【什么会改变判断】                                 │
│   ✅ ADX 1D 越过 25(L1 趋势确立)                │
│   ✅ stance_confidence 升 high(L2 信心达门槛)   │
│   ✅ 1W 转 bullish 与 1D 共振                    │
│   ❌ LTH Supply 转跌 → 立刻平仓                   │
│   ❌ ETF 净流出 → 机构态度反转                    │
│                                                  │
│ 【未来 72H 事件】72h 内无登记事件                 │
│ 【活跃风险标签】无                                 │
├─────────────────────────────────────────────┤
│ AI 输出于 2026-04-30 16:09 · sonnet-4-5         │
│ 6 AI 协作 · token 12,485 · 耗时 3 分 24 秒       │
└─────────────────────────────────────────────┘
```

## 6.4 因子卡格式(每张卡片一致)

每张卡片(primary + display)统一格式:

```
┌──────────────────────────────────────┐
│ [卡片标题]              [当前数值] [●圆点] │  ← 颜色:绿/黄/红
├──────────────────────────────────────┤
│ 📊 当前怎么解读                        │
│ [具体数值描述 + 一句话判断]              │
│                                       │
│ 🔍 历史阈值参考                        │
│ [阈值含义解释]                         │
├──────────────────────────────────────┤
│ 影响:偏空/偏多/中性 · L?  抓取于 ... (X 小时前) │
└──────────────────────────────────────┘
```

字段:
- card_id(唯一标识)
- name / name_en
- current_value + value_unit
- captured_at_bjt(北京时间)
- plain_interpretation(📊 段)
- strategy_impact(🔍 段)
- impact_direction(偏空/偏多/中性)
- impact_weight(0-1)
- linked_layer(L1/L2/L3/L4/L5)
- source(CoinGlass/Glassnode/FRED/计算)

## 6.5 因子卡同步增删原则

- **删除老因子时**:网页卡片同步删除
- **新增因子时**:网页卡片同步新增,严格按 6.4 格式
- **降级因子时**:卡片移动到"display 区"(只展示,不参与决策标签)

## 6.6 CyclePosition 嵌入展示

不单独成区,**嵌入到 L2 推演段开头**:

```
🎯 L2 方向结构
  stance: bullish · phase: unclear
  长周期位置:early_bull(置信度 0.748,AI 同意)
  ...
```

若 AI 不同意规则:
```
长周期位置:early_bull(规则)/ mid_bull(AI 建议)
```

## 6.7 系统自检面板(保留,不变)

显示数据健康度、AI 调用状态、Fallback Level、最后运行时间等。

---

# 第七部分:M26 三场景回测验收(必须先过才能上线)

## 7.1 回测目的

实施完 v1.3 后,**第一个 sprint 必须是回测**。AI 在历史数据上的判断必须达到既定标准,达不到就调 prompt 重测,直到达标。

## 7.2 三个回测场景

### 场景 1:2020-10-15 → 2021-04-15(主升浪 6 个月)

**应有判断**:
- 11 月初:L1 trend_up + L2 stance bullish + L3 grade A → LONG_PLANNED → LONG_OPEN
- 12 月-1 月:LONG_HOLD,thesis_still_valid
- 2 月底-3 月:LONG_TRIM(分批减仓)
- 4 月中:LONG_EXIT 或 FLIP_WATCH

**验收标准**:
- 抓取 BTC 从 $11,000 → $63,000 的趋势 ≥ 70%
- 在主升浪 80% 时间内保持持仓
- 没有在中途因小回撤误平仓

### 场景 2:2022-05-01 → 2022-12-01(主跌浪 7 个月)

**应有判断**:
- 5 月-6 月:L1 transition_down + L2 stance bearish + L3 grade A → SHORT_PLANNED → SHORT_OPEN
- 7 月-10 月:SHORT_HOLD
- 11 月:SHORT_TRIM 或 SHORT_EXIT

**验收标准**:
- 在 BTC 从 $39,000 → $16,000 的跌幅中规避或做空 ≥ 60%
- 在 LUNA 崩盘(5 月)+ 3AC 事件(6 月)+ FTX 崩盘(11 月)期间正确进入 PROTECTION
- 不在熊市反弹(8 月、10 月)误开多

### 场景 3:2023-07-01 → 2023-10-31(震荡 4 个月)

**应有判断**:
- 大部分时间:FLAT 或 LONG_PLANNED 但未触发(grade C 或 none)
- 偶尔 ambush_only(底部埋伏)
- 不应有大量错误开仓

**验收标准**:
- 整个震荡期开仓次数 ≤ 3 次
- 开仓后亏损率 ≤ 30%
- 大部分时间保持 watch

## 7.3 回测失败处理

任一场景不达标:
1. 分析 AI 输出的 narrative,找原因
2. 调整对应层 AI 的 System Prompt
3. 重新跑该场景
4. 直到达标

**不达标不上线**。

## 7.4 上线后观察期

回测达标后:
1. 小仓位(总仓位 ≤ 5%)运行 1-2 周
2. 每天人工审核 AI 输出
3. 若发现新的判断偏差,继续调 prompt
4. 观察期通过后逐步放开仓位上限

---

# 第八部分:实施 Sprint 路径

| Sprint | 内容 | 工作量预估 |
|---|---|---|
| **1.6** | 新增 9 个因子(STH Supply / LTH-MVRV / STH-MVRV / SSR / HODL Waves / CDD / aSOPR 升级 / ETF Flows / BTC.D)。验证可抓 + 入库 + 网页卡片同步 | 4-5 小时 |
| **1.7** | 删 8 个噪音因子 + 降级 3 个因子 + 网页卡片同步删除 + 配置文件更新 | 3-4 小时 |
| **1.8** | 实施 6 个 AI 角色(L1/L2/L3/L4/L5 + 主裁)+ System Prompt + Validator 10 条硬规则 | 6-8 小时 |
| **1.9** | 实施频率与触发设计(每日 16:00 完整 A + 异动 ±5% 简化 A + 持仓期 4h 健康检查) | 3-4 小时 |
| **1.10** | 网页改造(5 层推演展示 + 删组合因子卡 + 因子卡格式统一) | 4-5 小时 |
| **1.11** | M26 三场景回测(2020 主升 / 2022 主跌 / 2023 震荡) | 5-6 小时 |
| **1.12** | 调优 prompt 直到回测达标 | 不定 |
| **1.13** | 小仓位观察期(1-2 周) | 1-2 周 |

总预计:**1.5-2 周技术实施 + 1-2 周观察期**

---

# 第九部分:工程纪律(不变,沿用 CLAUDE.md)

## 9.1 §X 删除纪律

旧 collector / 旧因子 / 旧组合因子代码部署后必须删除,不堆叠。

## 9.2 §Y commit 即 push

不允许累积本地 commit。每个 sprint 必须 push GitHub 后才算完成。

## 9.3 §Z 端到端 DB 行数 / 字段值断言

不允许只 mock `.called=True`。所有测试必须包含 DB 真实写入断言。

## 9.4 双轨原则(§2.5)

机读版给 AI / 人读版给用户。两个版本同步维护。

---

# 第十部分:数据真实性

## 10.1 数据源

- **Binance**:已退场(美国 IP 451 封禁)
- **CoinGlass**:via alphanode 中转
- **Glassnode**:via alphanode 中转(同 base_url 不同 path)
- **FRED**:独立直连
- **Yahoo Finance**:已退场(Sprint 1.5p 决议)

## 10.2 共享 API key

CoinGlass + Glassnode 通常共享同一个 alphanode key,通过 header `x-key`(小写连字符)鉴权。

## 10.3 不允许 mock 数据

所有测试 fixture 必须用真实数据快照。生产路径不允许 fallback 到 mock。

---

# 第十一部分:版本变更日志

## v1.3(2026-04-30)— 当前版本

**核心变化**:架构从"规则主导 + AI 辅助"切换到"AI 主导 + 规则硬约束"

**详细变化**:
1. 删 8 个噪音因子(basis / Reserve Risk / Puell / DFF / CPI / 失业率 / SP500 / 黄金)
2. 降级 3 个重叠因子(MVRV Ratio / SOPR / put_call_ratio)到 display
3. 新增 9 个关键因子(STH Supply / LTH-MVRV / STH-MVRV / SSR / HODL Waves / CDD / aSOPR primary / ETF Flows / BTC.D)
4. 6 个组合因子 → 1 个组合因子(只保留 CyclePosition 作锚点)
5. L1-L5 判断全部交给 AI(6 个 AI 角色 + 主裁 AI)
6. AI 调用频率重新设计(每日 16:00 完整 A + 异动简化 A + 持仓 4h 健康检查)
7. 网页 AI 策略说明区改为 5 层推演样式
8. L5 AI 正式接入(本版完成)
9. Validator 强制框架(10 条硬规则)
10. M26 三场景回测验收必须先过

## v1.2(2026-04-23)

EventRisk 设计 / 14 档状态机 / 6 组合因子 / 5 层证据 / 9 档 CyclePosition。

## v1.1 / v1.0

初版设计。

---

**END of v1.3 modeling document.**
