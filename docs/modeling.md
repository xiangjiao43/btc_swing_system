# BTC 中长线低频双向波段交易辅助系统 — 建模 v1.4

**版本**:v1.4
**修订日期**:2026-05-02
**前一版本**:v1.3(2026-04-30)
**修订人**:用户 + 网页 Claude(协作)
**实施定位**:v1.4 sprint 唯一蓝本

---

# 第零部分:v1.3 → v1.4 修订摘要

## 0.1 修订动机

v1.3 完成了"AI 主导 + 规则硬约束"的架构翻转,但实施后(Sprint 2.6 + 1.8.2 系列)暴露了 6 个真实问题:

1. **状态机依赖 account_state 真实账户字段** → 用户不接交易所 → 状态机永远卡 FLAT
2. **缺少 thesis 主线锁** → master AI 每天可重新出方向 → 反复横跳风险
3. **AI 链失败处理不够** → 6 个 AI 串行,1 个挂就 fallback 到 FLAT,等 24 小时
4. **缺少虚拟账户** → 无法做收益率追踪 / 无法支撑"AI 顶级交易员"产品定位
5. **缺少边界保护**(60 天上限 / 14 天熔断 / 过度保守监控等)→ 极端情况下系统会僵死
6. **缺少周复盘机制** → 系统设计问题无法系统性发现

## 0.2 v1.4 核心改动

| 改动项 | v1.3 | v1.4 |
|---|---|---|
| **产品定位** | 中长线策略辅助系统 | **虚拟交易员账户系统**(AI 决策 + 用户审计跟单) |
| **虚拟账户** | 无 | initial_capital 100,000 USDT,完整资金/持仓/收益率追踪 |
| **挂单引擎** | 无(状态机依赖真实账户) | 精确价格挂单 + 4h K 线 high/low 触发判定 |
| **状态机** | 14 档(LONG/SHORT 镜像 + FLIP_WATCH + PROTECTION + POST_PROTECTION_REASSESS) | **简化为 thesis.lifecycle_stage 5 档**(planned/opened/holding/trim/closed)+ 系统级特殊态 PROTECTION / review_pending |
| **thesis 机制** | 无 | 同时 1 个 active thesis,主线锁防反复横跳 |
| **反手机制** | 三条核心纪律(沿用 v1.2)| 反手 3 档通道(慢 3 天 / 中 24h / 快 0 冷却)+ 14 天反复横跳熔断 |
| **AI 失败处理** | Fallback Level 1-3 | **指数退避重试**(5/10/20 分钟)+ **层级依赖短路** + **2h 重试窗口** + review_pending 兜底 |
| **事件触发** | 仅 ±5% 简化 A | **空仓 ±5% / 持仓 ±3% 双轨 event_price**(继承 v1.3 §5.2 双轨)+ **新增 event_invalidation 硬失效位击穿(规则平仓,无 AI)** |
| **复盘机制** | 实施 sprint 完成后人工复盘 | **每周日 22:00 BJT 自动 weekly_review_analyst** |
| **边界保护** | KPI + observation_category(只读告警) | **S1-S5 + 6 细化(共 11 条硬保护)** |
| **架构清理** | observation_category(只读) / cold_start | **全部删除** |
| **运营节奏** | 每日 16:00 完整 A + 持仓期 4h 健康检查 + 空仓异动 ±5% / 持仓 ±3% | **保持原 v1.3 设计不变**(每日 16:00 BJT 完整 A + 持仓期 4h 健康检查 + 空仓 ±5% / 持仓 ±3% 双轨异动) |
| **硬约束 meta 监控** | 无 | **第 24 条 meta 约束:硬约束激活频率监控**(供周复盘 AI 评估) |

## 0.3 v1.4 不变的核心原则(继承 v1.3)

- **AI 主导 + 规则硬约束**(v1.3 §1.3.1)
- **不堆砌指标,不简单打分**(v1.3 §1.3.2)
- **化学反应通过 AI 自然识别**(v1.3 §1.3.3)
- **临界值不踩空**(v1.3 §1.3.4)
- **反过度保守**(v1.3 §1.3.5)
- **质量第一,不为成本妥协**(v1.3 §1.3.6)
- **44 因子地基**(v1.3 §2)— v1.4 不变,继承 v1.3 的"删 8 加 7 降 3"
- **CyclePosition 9 档作唯一锚点**(v1.3 §3.2.6)— v1.4 不变
- **三道工程纪律**:§X 删除纪律 / §Y commit 即 push / §Z 端到端 DB 真实断言

## 0.4 v1.4 设计哲学(承上启下)

v1.3 已经定调"AI 主导 + 规则硬约束"。v1.4 把这个哲学**落到具体的"刚刚好"标准**:

```
框架太死(纯规则) → 不需要 AI(脚本就行)
框架太松(AI 自由) → 不需要系统(直接问 ChatGPT 就行)
框架"刚刚好" → AI 在客观约束内自由判断
```

**三层各司其职**:
- **AI 决定"是什么"**:regime / stance / grade / risk_level / macro / direction / 综合判断
- **规则决定"输出格式 + 客观依据 + 自洽性"**:Validator + schema + objective_evidence + 数学算的指标 + L4 提供的客观候选(hard_invalidation_levels / position_cap_base)
- **thesis 决定"何时允许改主意"**:break_conditions + 冷却期 + 主线锁

**v1.4 AI 介入清单(继承 v1.3,完整保留 6 个主决策 AI)**:
- **L1 AI**:市场状态分析师(regime / volatility)
- **L2 AI**:方向结构分析师(stance / phase)
- **L3 AI**:机会判断分析师(opportunity_grade / execution_permission)
- **L4 AI**:风险评估分析师(risk_level / crowding / 从 hard_invalidation_levels 选 stop_loss / 微调 position_cap)
- **L5 AI**:宏观环境分析师(macro_stance / macro_headwind / extreme_event 检测)
- **Master AI**:综合裁决(thesis 评估或创建 / trade_plan / narrative)

**v1.4 辅助 AI(简化版,持仓期或事件触发时跑)**:
- **持仓健康检查 AI**(单 AI,持仓期 4h 整点跑,~$0.05/次)
- **简化 A 应急 AI**(单 AI,价格异动触发时跑,~$0.10/次)
- **weekly_review_analyst**(单 AI,每周日 22:00 BJT 复盘,~$0.15/次)

---

# 第一部分:系统定位与设计哲学

## 1.1 系统定位(v1.4 重写)

**这个系统是一个虚拟顶级交易员账户**:
- 初始资金 **100,000 USDT**(虚拟,可配置)
- AI 自己决策、自己挂单、自己持仓、自己止盈止损
- 系统目标:**利润最大化**(在风险约束下)
- 用户角色:**审计员**(观察 AI 每笔操作)+ **跟单决策者**(用真钱在自己交易所跟操作)

**关键词**(继承 v1.3 + v1.4 增):
- **中长线**:持仓周期几周到几个月
- **低频**:每日 1 次完整决策(BJT 16:00,对齐美东收盘)
- **双向**:支持做多做空(空头判定更严格)
- **辅助**:不自动下单到交易所,但有完整虚拟账户记录"AI 自己怎么操作"
- **可审计**:用户能完整看到 AI 的每一步,包括反向证据 + 改变判断条件

## 1.2 用户画像(继承 v1.3)

- 中文用户,代码新手
- 信任系统判断,但要求"看到系统为什么这么判断"
- 接受小仓位试错,**但不接受"系统永远不出策略"**
- 愿意用 token 成本换策略精准度("策略错误造成的损失远大于 token 费用")
- **新增(v1.4)**:每天 16:30 BJT 看一次系统输出,周一额外看一次复盘报告

## 1.3 用户场景(v1.4 新增)

### 典型一天

1. 16:00 BJT 系统跑完整 6 AI 协作(每天一次)
2. 16:30 BJT 用户打开网页:
   - 看 BTC 价格 + 状态条 + 系统自检
   - 看虚拟账户面板(总资产 / 收益率 / 浮盈)
   - 看当前 active thesis(论点 / 失效条件 / AI 评估变化)
   - 看挂单 + 持仓状态(精确价格 + 距当前距离)
   - 看 5 层推演 + 综合结论
3. 用户决定是否真实跟单(在自己的交易所)

### 持仓中(*_OPEN / *_HOLD / *_TRIM)

- 4h 健康检查 AI(单 AI 简化版,~$0.05 一次)自动跑
- 用户随时可看"thesis_status"(valid / weakening / challenged)
- challenged 时系统会提前触发完整 A,推送告警

### 黑天鹅响应

1. BTC 价格 1H 内 ±3% 异动
2. 触发 event_price → 简化 A(应急 AI)立刻跑
3. 应急 AI 判断:maintain / emergency_exit / tighten_stop / wait_next_full
4. 若硬失效位被击穿 → event_invalidation → 自动关闭 thesis(规则平仓,无 AI)
5. 推送告警给用户

### 典型一周

1. 周日 22:00 BJT 系统自动跑 weekly_review_analyst
2. 周一打开网页看复盘报告
3. AI 给出"过去 7 天表现 + 系统调整建议"
4. 用户决定是否手动调阈值/prompt(系统不自动调)

## 1.4 设计哲学(v1.4 落地)

继承 v1.3 §1.3 全部 6 条,**并明确 v1.4 的"刚刚好"标准**:

### 1.4.1 AI 主导(继承 v1.3 §1.3.1)

- 中长线波段需要识别"临界过渡 / 化学反应 / 反常情景",规则难以穷举
- AI 看完所有 44 个因子能自然识别"主升浪中段 / 假突破 / 空头力竭"等情景
- AI 输出可解释(narrative + counter_arguments + objective_evidence),不是黑盒

### 1.4.2 规则硬约束(继承 v1.3 §1.3.1 + v1.4 强化)

- 止损价、仓位上限、状态机迁移、极端事件检测必须确定性
- AI 不能突破这些约束(否则系统不可信)
- Validator 在 AI 输出后强制校验
- **v1.4 强化**:break_conditions 客观可判定 / thesis 主线锁 / 反手必经冷却

### 1.4.3 "刚刚好"标准(v1.4 新增)

硬约束设计的"刚刚好"具体表现:
- 单条硬约束:**保护资金安全 + 防 AI 乱来**,缺一不可
- 总体数量:不重叠 / 不矛盾 / 互补
- **激活频率监控**(第 24 条 meta 约束):周复盘 AI 评估每条硬约束的激活频率,过严或过松都要调

### 1.4.4 thesis 主线锁(v1.4 新增)

- 反复横跳的根源是"AI 每次重新判断方向"
- 解决:有 active thesis 时,master AI 强制走"评估模式",不允许出新方向
- 真转向时通过 break_conditions 客观触发 + 冷却期合规反手

## 1.5 系统不是什么

继承 v1.3 全部 + v1.4 强调:

- 不是高频或短线
- 不是单向(只多或只空)
- 不是预测系统(不喊"BTC 会涨到多少")
- 不是黑箱
- **不是自动下单到交易所**(虚拟账户是系统内部模拟)
- **不是 AI 完全自由判断**(受 hard constraints 约束)
- **不是纯规则系统**(规则只在 AI 周围搭框架)

## 1.6 v1.4 最该避免的代价(按严重度)

继承 v1.3 + 落到 v1.4 防御机制:

1. **反复横跳**:今天多明天空 → v1.4 通过 thesis 主线锁 + 14 天熔断防御
2. **迟迟不出策略**:AI 链失败 24h 无策略 → v1.4 通过指数退避重试 + 短路 + review_pending 防御
3. **僵尸 thesis**:break 永不触发 → v1.4 通过 60 天上限 + 距离 validator 防御
4. **过度保守**:连续 30+ 天无 thesis → v1.4 通过过度保守监控 + 复盘建议防御
5. **重大转向反应迟钝** → v1.4 通过反手通道 C(0 冷却)+ event_price/invalidation 防御
6. **数据陈旧导致误判** → v1.4 通过数据采集每小时 + freshness 监控防御

---

# 第二部分:数据层 — 44 因子地基(继承 v1.3 §2,不变)

## 2.1 总览

| 类别 | 数量 | 来源 |
|---|---|---|
| 价格类 | 10 个(全保留) | Binance K 线 / 自算 |
| 衍生品类 | 10 个(删 1 + 降级 1) | CoinGlass |
| 链上类 | 15 个(删 2 + 升级 1 + 新增 6) | Glassnode |
| 宏观类 | 4 个(删 5) | **FRED**(Yahoo Finance Sprint 1.5p 已退场) |
| 机构 / 市场结构类 | 2 个(全新) | CoinGlass / 自算 |
| 事件 / 价格类 | 3 个 | 手动 YAML / CoinGlass spot / 自算 |
| **合计** | **44 个** | |

> **v1.4 注**:44 个因子完整明细见 v1.3 §2.2-§2.7(其中事件类细分:#43 事件日历仅参考显示 / #44 BTC 现货分钟价网页顶栏)。v1.4 保持 v1.3 实施现状,以代码 `config/data_catalog.yaml` 为权威。任何因子增减必须先改 v1.4 文档再改代码。
> **数据源说明**:Yahoo Finance 在 v1.3 Sprint 1.5p 已退场,宏观数据完全走 FRED。v1.4 不恢复 Yahoo。

具体明细见 v1.3 §2.2-§2.7,v1.4 不重复列。

## 2.2 因子频率(继承 v1.3,不变)

- 价格:1H/4H/1D/1W
- 衍生品:多数 1H,资金费率 8H
- 链上:多数每天,Exchange Net Flow 每小时
- 宏观:每天

**数据采集每小时增量跑**(`scheduler.yaml::data_collection: 1h`),**不消耗 AI token**,只消耗 API 调用配额。

## 2.3 v1.4 因子层不变,变化全在更上层

v1.4 不动数据层。所有"删 8 加 7 降 3"v1.3 已经实施。v1.4 工程量集中在"AI 介入层 + 虚拟账户 + thesis 机制 + 网页"。

---

# 第三部分:架构 — AI 主导 + 规则硬约束(v1.4 重写)

## 3.1 整体架构图(v1.4)

```
┌─────────────────────────────────────────────────┐
│  数据采集层(每小时增量,不消耗 AI token)         │
│  Binance / CoinGlass / Glassnode / FRED         │
└─────────────────────────────────────────────────┘
                    ↓
        (每天 BJT 16:00 触发主决策流程)
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 1: 规则层(轻量,只做硬约束 + 锚点)         │
│                                                   │
│  做的事:                                         │
│  - 计算 hard_invalidation_levels(止损价候选)     │
│  - 计算 position_cap_base(仓位上限基础值)        │
│  - 极端事件检测(进 PROTECTION 系统级停)           │
│  - 数据降级判定(Fallback Level 1-3)              │
│  - 计算 CyclePosition(9 档周期标签,作锚点)       │
│  - thesis 状态读取(active / cooldown / 熔断)      │
│                                                   │
│  不做(交给 AI):                                  │
│  - regime / stance / grade / risk_level 判断      │
│  - macro_stance 判断                              │
│  - 从候选选 stop_loss / 微调 position_cap         │
│  - trade_plan 生成                                │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 2: AI 介入层(6 个 AI 协作)                  │
│              (指数退避重试 + 短路依赖)             │
│                                                   │
│  L1 (AI) ──┬──► L2 (AI) ──┬──► L3 (AI) ──┐       │
│            │              │              │       │
│            ├──► L4 (AI)   ┤              ▼       │
│            │  规则给候选    │       Master (AI)    │
│            │              │                       │
│            └──► L5 (AI) ──┘                       │
│                                                   │
│  失败处理:                                        │
│  - 单层失败 → 指数退避重试(5/10/20 分钟,3 次)   │
│  - 上层失败 → 下层短路不调                        │
│  - 整次窗口 2 小时(BJT 16:00-18:00)              │
│  - 超时 → fallback thesis-aware                   │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 3: Hard Constraints 层(v1.4 强化)          │
│                                                   │
│  Validator 24 条硬规则:                            │
│  - 23 条:输出 schema / objective_evidence /       │
│           thesis 主线锁 / break_conditions 客观    │
│           可判 / 距离 validator / 等              │
│  - 第 24 条(meta):激活频率统计 → 供周复盘 AI    │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 4: virtual_account + 挂单引擎               │
│                                                   │
│  - thesis 创建 / 评估 / 关闭                       │
│  - 挂单触发判定(回看 1H K 线 high/low)           │
│  - 资金更新(已实现 / 浮盈 / total_equity)         │
│  - thesis lifecycle 推进                          │
│  - 反手 3 档通道判定(慢/中/快)                    │
│  - 14 天反复横跳熔断 + 60 天 thesis 上限           │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 5: 策略输出层                              │
│  StrategyState v1.4 + virtual_account 快照 +     │
│  active thesis 写 DB                             │
└─────────────────────────────────────────────────┘
                    ↓
       ┌────────────┼─────────────┐
       ▼            ▼             ▼
  ┌──────────┐  ┌────────┐  ┌──────────┐
  │ 周复盘 AI │  │ 监控告 │  │ 网页 API │
  │ (周日)   │  │ 警     │  │          │
  └──────────┘  └────────┘  └──────────┘

       并行运行:
       - 持仓期 4h 健康检查 AI(单 AI 简化版)
       - 每小时硬失效位监控 cron(规则,不调 AI)
       - 事件触发:±3% 价格异动 / 硬失效位击穿
                  → 触发简化 A 或规则平仓
```

## 3.2 规则层职责(继承 v1.3 §3.2,微调)

### 3.2.1 hard_invalidation_levels(止损价候选,不变)

继承 v1.3 §3.2.1。算法:
- 做多:找最近 4H/1D 的 swing low(HL 序列),取最低 3 个,各减 ATR × 1.5 作缓冲
- 做空:镜像
- 输出 `l4.hard_invalidation_levels: list[float]`
- **唯一权威止损价来源**,AI 必须从中选

### 3.2.2 position_cap_base(仓位上限基础值,不变)

继承 v1.3 §3.2.2:
- 基础 70%
- L4 risk_level=low → ×1.0 = 70%
- L4 risk_level=elevated → ×0.7 = 49%
- L4 risk_level=critical → ×0.3 = 21%
- AI 给的 max_position_size_pct ≤ position_cap_base

### 3.2.3 极端事件检测(继承 v1.3 §3.2.4,行为微调)

**触发条件**(任一满足,继承 v1.3):
- BTC 1H 价格 ±10%
- BTC 24H 价格 ±20%
- VIX 1D 涨幅 > 30%
- 重大事件实际数值 vs 预期偏差 ≥ 2σ

**触发后**(v1.4 调整):
- 状态机强制进入 **PROTECTION**(系统级特殊态)
- AI 调用暂停 30 分钟
- 所有 active thesis 进入 review_pending
- 推送 critical 告警

> **v1.4 关键澄清**:PROTECTION 是**系统级自动应急停**(没人也能保护资金),review_pending 是**等用户介入**。两者并存,各管各的。极端事件用 PROTECTION,其他兜底场景(60 天到期 / 连续熔断 / 3 天 master 失败)用 review_pending。

### 3.2.4 数据降级判定 Fallback Level 1-3(继承 v1.3 §3.2.5,不变)

| Level | 触发 | 行为 |
|---|---|---|
| 0(健康) | 数据完整度 ≥ 95% | 正常运行 |
| 1(轻度) | 完整度 80-95% 或 1 个数据源失败 | AI 调用,但 confidence 上限 0.7 |
| 2(中度) | 完整度 60-80% 或 2 个数据源失败 | 不调用 AI,走规则模板,permission 强制 watch |
| 3(严重) | 完整度 < 60% 或 3+ 数据源失败 | 状态机强制 hold_only,推送告警 |

### 3.2.5 CyclePosition 计算(继承 v1.3 §3.2.6,不变)

CyclePosition 是**唯一保留的组合因子**(v1.3 已废弃 5 个,v1.4 不恢复)。详细规则见 v1.3 §3.2.6。

输入 8 个主指标(MVRV-Z / NUPL / LTH 90d / STH 90d / LTH-MVRV / 距 ATH 跌幅 / HODL Waves / SSR),投票得 9 档之一 + confidence。

输出字段:`composite_factors.cycle_position.{cycle_position, cycle_confidence, voting_details, last_stable_cycle_position}`

> **v1.4 关键澄清**:CyclePosition 保留的理由是它**不是综合判断**,而是**客观分类**(BTC 整体处于哪个长周期)。AI 引用此锚点不算"程序替 AI 判断"。v1.2 的其他 5 个组合因子(TruthTrend / BandPosition / Crowding / MacroHeadwind / EventRisk)是加权综合,**违反"不堆砌打分"哲学,v1.3 已废弃,v1.4 不恢复**。

### 3.2.6 thesis 状态读取(v1.4 新增)

每次 16:00 跑前,规则层读 `theses` 表:
- 是否有 active thesis(同时只能 1 个)
- 是否在冷却期(若 thesis 刚关闭 < 冷却时长)
- 是否在 14 天熔断期
- active thesis 的关键字段(direction / break_conditions / stop_loss / 创建天数)

这些状态作为 master AI 的输入,影响 mode 选择(evaluate_existing / new_thesis / silent_cooldown)。

## 3.3 各层 AI 职责(继承 v1.3 §3.3,v1.4 微调)

### 3.3.1 L1 AI 市场状态分析师(继承 v1.3 §3.3.1)

输入:8 个 L1 因子 + 30 天历史 + CyclePosition 锚点。
输出:regime / volatility / key_observations / confidence_tier / narrative
System Prompt 完整保留 v1.3 草稿(代码层 prompt 可能跟草稿不一致,**v1.4 sprint 必须 SSH 调研对齐**)。

### 3.3.2 L2 AI 方向结构分析师(继承 v1.3 §3.3.2)

输入:L1 输出 + L2 因子 + 30 天历史 + CyclePosition。
输出:stance / phase / structure_features / key_levels / long_cycle_context.ai_assessment + ai_alternative。
完整保留 v1.3 草稿。

### 3.3.3 L3 AI 机会判断分析师(继承 v1.3,v1.4 强化封闭)

输入:L1 + L2 输出 + L3 因子。
输出:**opportunity_grade(A/B/C/none)** + execution_permission + reasoning。

> **v1.4 强化**:**L3 是 grade 唯一权威**。master AI 不能改 grade,只能在 narrative 表达"对 L3 grade 的保留意见"。Validator 8 强制:master 输出的 grade 必须 = L3 输出。

### 3.3.4 L4 AI 风险评估分析师(继承 v1.3 §3.3.4)

**v1.4 关键澄清**:L4 是 **规则 + AI 协作**,不是纯规则。规则给客观候选,AI 在候选内做综合判断。

**输入**:
- L1+L2+L3 AI 输出
- L4 因子(funding 全维度、OI 变化、LSR、清算总额/方向、价格结构、CyclePosition)
- 规则计算的 `hard_invalidation_levels`(止损价候选列表)
- 规则计算的 `position_cap_base`(仓位上限基础值)

**任务**:
1. 判断风险等级(low / elevated / critical)
2. 判断拥挤情景(extreme_long / extreme_short / exhaustion_signal / false_breakout_warning / mild_long / mild_short / normal)
3. 从 hard_invalidation_levels 候选**选**一个止损价
4. 微调 position_cap_pct(在 base 基础上 -10% 到 -20%,不能高于 base)

**输出 JSON Schema**:
```json
{
  "risk_level": "low | elevated | critical",
  "crowding_assessment": "extreme_long | mild_long | normal | mild_short | extreme_short | exhaustion_signal | false_breakout_warning",
  "position_cap_pct": float,                    // ≤ position_cap_base
  "hard_invalidation_chosen": float,            // 必须从规则给的列表选 1 个
  "hard_invalidation_distance_pct": float,
  "key_observations": [...],
  "counter_arguments": [...],
  "objective_evidence": [...],                  // v1.4 新增,引用客观字段
  "narrative": "中文 2-3 句"
}
```

**System Prompt(核心要点,继承 v1.3 §3.3.4 + v1.4 增强)**:

```
你是 BTC 中长线波段交易系统的 L4 风险评估分析师。

【你的任务】
判断当前的风险情景 + 微调仓位上限 + 选定止损价。

【crowding_assessment 情景判定参考】
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
基础值由规则给(position_cap_base)。你可以:
- 维持基础值(大部分情况)
- 微调 -10% 到 -20%(若有特殊风险)
- 不能超过基础值

【hard_invalidation_chosen 选定】
规则给了一个列表(hard_invalidation_levels),你必须从中选 1 个:
- 默认选最近的(最严)
- 若数据不足或 ATR 极大,选中位的
- 不允许自创止损价(Validator 1 硬拦截)

【你必须做的】
1. 必须从 hard_invalidation_levels 选,不能自创
2. position_cap_pct 必须 ≤ position_cap_base
3. 必须给出 hard_invalidation_distance_pct(止损距离百分比)
4. 必须列至少 1 条反向证据
5. objective_evidence 必须引用上下文中真实存在的字段值(防 AI 幻觉,Validator 13)
```

**Validator 校验**(详见 §3.4):
- Validator 1:`hard_invalidation_chosen` 必须 ∈ `hard_invalidation_levels`
- Validator 2:`position_cap_pct` 必须 ≤ `position_cap_base`
- Validator 13:`objective_evidence` 引用真实字段
- Validator 14:必须有 `counter_arguments`

**L4 与 L5 macro_headwind 配合**:
- L5 输出 `macro_headwind_score`(-10 到 +10)
- 规则按公式调整 `position_cap_base`(继承 v1.2 设计)
- L4 在调整后的 base 上再做 AI 微调
- 保证最终 cap = `position_cap_base × L4 调整因子`,绝不超过

### 3.3.5 L5 AI 宏观环境分析师(继承 v1.3 §6.8 v1.2 设计)

输入:结构化宏观数据 + 事件摘要。
输出:macro_stance / macro_trend / adjustment_guidance / macro_headwind_score。

### 3.3.6 Master AI 综合裁决(v1.4 重写,thesis-aware)

**v1.4 关键改造**:master AI 接收 thesis 上下文,强制走 3 种 mode 之一。

#### 输入(v1.4 新增 thesis 上下文)

```python
master_input = {
    # 原有 v1.3 输入
    "L1_output": {...},
    "L2_output": {...},
    "L3_output": {...},
    "L4_output": {...},
    "L5_output": {...},
    
    # v1.4 新增
    "active_thesis": {
        "thesis_id": "thesis_20260502_1249",
        "direction": "long",
        "confidence_score": 85,
        "core_logic": "...",
        "break_conditions": [...],
        "created_days_ago": 3,
        "last_assessment": "mostly_valid",
        "last_assessment_at": "2026-05-01 16:00 BJT",
    } | None,
    
    "current_position": {
        "long_position_usdt": 20000,
        "long_avg_price": 74568,
        "long_btc_amount": 0.2682,
        "current_pnl_pct": -1.2,
    } | None,
    
    "pending_orders": [
        {"price": 70666, "size_pct": 30, "type": "entry"},
        {"price": 63000, "size_pct": 100, "type": "stop_loss"},
        ...
    ],
    
    "cooldown_state": {
        "in_cooldown": False,
        "cooldown_remaining_hours": 0,
        "cooldown_reason": null,
    },
    
    "fuse_state": {
        "in_14d_fuse": False,
        "thesis_cycles_in_14d": 0,
        "channel_c_uses_in_14d": 0,
    },
    
    "last_5_assessments": [
        {"run_id": "...", "assessment": "mostly_valid", "narrative_brief": "..."},
        ...
    ],
}
```

#### 输出(v1.4 强制 mode 字段)

```json
{
  "mode": "evaluate_existing | new_thesis | silent_cooldown",
  
  // 当 mode=evaluate_existing(active thesis 存在)
  "thesis_assessment": {
    "still_valid": "fully | mostly | partially | weakened | invalidated",
    "which_break_triggered": null | "1D 跌破 70000",
    "reasoning": "...",
    "stop_loss_adjustment": null | <新止损价>,  // 仅 weakened 允许
    "objective_evidence": ["1D 收盘 76200 > 70000", "DXY 当前 105 < 108", ...]
  },
  
  // 当 mode=new_thesis(无 active thesis,不在冷却期/熔断期)
  "new_thesis": {
    "direction": "long | short",
    "confidence_score": 0-100,
    "core_logic": "...",
    "entry_orders": [
      {"price": 74568, "size_pct": 20},
      {"price": 70666, "size_pct": 30}
    ],
    "stop_loss": {"price": 63000, "size_pct": 100},
    "take_profit": [
      {"price": 85000, "size_pct": 30},
      {"price": 90000, "size_pct": 40}
    ],
    "break_conditions": [
      "1D 收盘跌破 70000",
      "DXY 突破 108 持续 3 天",
      "L5 极端事件触发"
    ],
    "objective_evidence": [...]
  },
  
  // 当 mode=silent_cooldown(在冷却期/熔断期/数据降级 Level 2+)
  "silent_reason": "在 24h 冷却期(剩余 12h)" | "14 天熔断中(剩余 8 天)" | "数据降级 Level 2",
  
  // 通用字段(所有 mode)
  "narrative": "中文 5 段推演说明(L1+L2+L3+L4+L5)",
  "one_line_summary": "中文一句话",
  "counter_arguments": ["反向证据 1", "反向证据 2"],
  "what_would_change_mind": ["客观条件 1", "客观条件 2", "客观条件 3"],
  "evidence_ref": ["card_id_1", "card_id_2", ...]
}
```

#### Master AI System Prompt(v1.4 新增,在 v1.3 草稿基础上加 thesis-aware)

```
你是 BTC 中长线波段交易系统的主裁 AI。

【你的身份】
你是虚拟账户的顶级 BTC 交易员。
- 初始资金 100,000 USDT(虚拟)
- 当前账户状态:{account_state}
- 当前持仓:{position_state}
- 你的目标:利润最大化(在风险约束下)

【你必须做的】

1. **首先决定 mode**(三选一):
   - 如果 active_thesis 不为 null → mode = "evaluate_existing"
     必须评估 thesis 是否仍成立,不允许出新方向
   - 如果 active_thesis 为 null + cooldown_state.in_cooldown=true → mode = "silent_cooldown"
     输出固定 silent reason,不允许创建新 thesis
   - 如果 active_thesis 为 null + 不在冷却 + 不在熔断 + L3 grade ∈ {A, B, C} → mode = "new_thesis"
     创建新 thesis(必须给完整 trade_plan)
     注意:C 级也创建 thesis(继承 v1.3 设计),但 execution_permission 必须给 ambush_only(只能埋伏单)
   - 如果 active_thesis 为 null + 不在冷却 + L3 grade=none → 输出 silent(等下一档机会)

2. **mode=evaluate_existing 时必须做**:
   - 评估 still_valid(fully/mostly/partially/weakened/invalidated)
   - 如果 still_valid=invalidated → 必须填 which_break_triggered
     这必须是 active_thesis.break_conditions 中已客观触发的某条
     如果你想 invalidated 但没有 break 条件触发 → 你必须改为 weakened,reasoning 说明为什么
   - 如果 still_valid=weakened → 你可以建议 stop_loss_adjustment(收紧但有上限,见 Validator 11)
   - reasoning 必须引用客观数据(objective_evidence)

3. **mode=new_thesis 时必须做**:
   - 给 3 条客观可判定的 break_conditions(每条必须能程序化判断)
     好例子:"1D 收盘跌破 70000" / "DXY 突破 108 持续 3 天" / "L5 极端事件触发"
     坏例子(被拒):"市场情绪转空" / "趋势反转" / "宏观恶化"
   - break_conditions 距当前必须在合理范围内(Validator 12 检查)
   - entry_orders 必须是精确价格(如 74568,不是区间)
   - stop_loss 必须从 hard_invalidation_levels 选(Validator 1)
   - 配套 confidence_score 0-100(必须跟 L3 grade 对齐:A→80-100 / B→60-80 / **C→40-60(只允许 ambush_only)** / none→不创建)
   - C 级 thesis 特殊约束:execution_permission 必须设为 `ambush_only`(只允许埋伏单,不允许追涨/追空)

【你绝对不能做的】

1. **不能凭感觉改主意**:有 active_thesis 时,必须先关闭旧 thesis(通过 break 触发)再出新方向
2. **不能凭感觉给主观 break 条件**:必须是程序能判断的客观条件
3. **不能改 L3 grade**:你只能在 narrative 表达保留意见,但 grade 字段必须照抄 L3
4. **不能违反硬约束**:stop_loss 必须从 hard_invalidation_levels 选,position_cap 不能超
5. **不能在 silent_cooldown 模式下创建 thesis**

【必须包含的输出元素】

- objective_evidence:你的判断必须引用上下文中真实存在的字段(防 AI 幻觉)
- counter_arguments:至少 1 条反向证据(强制自我审查)
- what_would_change_mind:至少 3 条客观条件(可被程序判断)

【关于"刚刚好"判断】

- 不要为了"出策略"而出策略 → grade=none 时就静默,不要硬凑
- 不要为了"不犯错"而保守 → 满足 thesis 创建条件时(grade A/B + 不在冷却 + 不在熔断)必须创建
- 不要为了"显得在思考"而模糊 → 信心档要明确给(high/medium/low)

【输出格式】
严格 JSON,首字符 `{`,尾字符 `}`,无 markdown,无解释。
```

### 3.3.7 持仓健康检查 AI(继承 v1.3 §5.4)

持仓期(*_OPEN / *_HOLD / *_TRIM)每 4h 跑。单 AI 简化版,~$0.05 / 次。

输入:上次完整 A 输出 + 最新 4h 因子 + 当前持仓 P&L。
输出:`{thesis_status, max_favorable_pct, max_adverse_pct, should_trigger_full_a, narrative}`

challenged 时提前触发完整 A。

### 3.3.8 简化 A 应急 AI(继承 v1.3 §5.3,v1.4 阈值改 ±3%)

**触发**:价格 ±3% 异动(v1.3 是 ±5%,v1.4 改 ±3% 反应更灵敏)。

输入:当前 strategy_state + 异动后价格 + 关键因子 + 持仓信息。
输出:`{thesis_still_valid, immediate_action, reasoning}`

immediate_action 取值:maintain / emergency_exit / tighten_stop / wait_next_full

### 3.3.9 Weekly Review AI 周复盘分析师(v1.4 新增)

**触发**:每周日 22:00 BJT(避开 16:00 主档,资源不冲突)。也支持手动触发。

#### 输入

- 过去 7 天所有 strategy_runs
- 过去 7 天所有 thesis 创建/关闭记录
- 过去 7 天所有 virtual_orders 触发记录
- 过去 7 天所有 fallback_events
- 过去 7 天 AI 重试 / 失败日志
- 当前 virtual_account 状态 + 7 天资金曲线
- 14 天熔断 / review_pending 触发记录
- **硬约束激活频率统计**(第 24 条 meta 约束的产物)

#### 输出 JSON

```json
{
  "performance_summary": {
    "total_runs": 7,
    "successful_runs": 5,
    "ai_failures": 2,
    "thesis_created": 1,
    "thesis_closed_profit": 0,
    "thesis_closed_loss": 1,
    "weekly_pnl_pct": -2.3,
    "max_drawdown_pct": -3.5
  },
  
  "system_health_diagnosis": [
    {
      "issue": "L3 AI 失败率偏高(过去 7 天 2 次)",
      "evidence": "run_001, run_004 L3 fallback",
      "severity": "warning",
      "suggested_action": "检查中转站延迟 / 调整 L3 prompt 长度"
    }
  ],
  
  "strategy_quality": {
    "thesis_quality": "good | acceptable | poor",
    "break_conditions_calibration": "适中 | 太严 | 太松",
    "false_signals": [...],
    "missed_opportunities": [...]
  },
  
  "hard_constraint_activation_review": {
    // 每条 Validator(1-23)的过去 7 天激活率,必须全部输出
    "validator_1_stop_loss_overridden": {"activations": 0, "rate": "0/7 days", "evaluation": "未触发,正常"},
    "validator_2_position_capped": {"activations": 1, "rate": "1/7 days", "evaluation": "适中"},
    "validator_6_thesis_lock": {"activations": 6, "rate": "6/7 days", "evaluation": "高频但符合预期(thesis active 期间正常状态)"},
    "validator_7_invalidation_check": {"activations": 0, "rate": "0/7 days", "evaluation": "未触发"},
    "validator_8_break_objectivity": {"activations": 1, "rate": "1/7 days", "evaluation": "适中"},
    "validator_15_confidence_capped": {"activations": 5, "rate": "5/7 days", "evaluation": "⚠️ 触发率偏高,可能数据降级阈值过严"},
    // ... 23 条全部都要列出 ...
    
    // meta 统计
    "position_cap_compressed_avg": 0.42,
    "thesis_lock_blocks_count": 1,
    "channel_c_uses_count": 0,
    "review_pending_triggers": 0,
    
    // 总评估
    "overall_evaluation": "硬约束体系总体合理,Validator 15 和 position_cap_compressed 偏紧",
    "suggested_actions": [
      "Validator 15 触发率 5/7,建议放宽 stale_data_policy.freshness 阈值",
      "position_cap_compressed 平均 42% 偏低,建议审视 L4 prompt 是否过度保守"
    ]
  },
  
  "adjustment_recommendations": [
    {
      "目标": "降低 L3 AI 失败率",
      "建议": "考虑把 L3 prompt 从 5000 token 缩到 3000 token",
      "优先级": "high",
      "影响": "可能降低判断精度,但提升稳定性"
    }
  ]
}
```

#### 复盘结果使用方式

- **不自动改参数**(系统硬纪律)
- 网页"周复盘"模块展示
- critical 级别建议 → 推送告警(电报/邮件,v1.0 后接)
- 用户根据建议**手动**调阈值/prompt
- 调整必须 bump rules_version

## 3.4 Validator 24 条硬规则(v1.4 重写)

### 3.4.1 资金安全类(5 条,继承 v1.3 + 微调)

**Validator 1**:AI 给的 stop_loss 必须从 `hard_invalidation_levels` 选
- 失败处理:强制覆盖为 `hard_invalidation_levels[0]`,notes 添加 `stop_loss_overridden_by_validator`
- meta 记录:`activations.validator_1`

**Validator 2**:AI 给的 max_position_size_pct 必须 ≤ position_cap_base
- 失败处理:强制 cap,notes 添加 `position_capped_by_validator`
- meta 记录:`activations.validator_2`

**Validator 3**:`mode=new_thesis` 时,entry_orders 总 size_pct 必须 ≤ 100%
- 失败处理:按比例缩到 100%,notes 添加 `entry_size_normalized`
- meta 记录:`activations.validator_3`

**Validator 4**:PROTECTION 状态不允许新 thesis / 不允许 trade_plan
- 失败处理:强制 mode=silent_cooldown,trade_plan 强制 null
- meta 记录:`activations.validator_4`

**Validator 5**:grade 与 thesis 创建 / execution_permission 对应关系强制
- `grade=none` 时不允许创建 thesis(强制 mode=silent,trade_plan=null)
- `grade=A` 时:execution_permission ∈ {can_open, cautious_open}
- `grade=B` 时:execution_permission ∈ {cautious_open, ambush_only}
- **`grade=C` 时:execution_permission 必须 = `ambush_only`**(继承 v1.3 §3.3.3,只允许埋伏单)
- 失败处理:强制改为合法 permission,notes 添加 `permission_overridden_for_grade`
- meta 记录:`activations.validator_5_grade_permission_lock`

### 3.4.2 thesis 主线锁类(4 条,v1.4 新增)

**Validator 6**:有 active_thesis 时,master 输出 mode 必须是 `evaluate_existing` 或 `silent_cooldown`,不能是 `new_thesis`
- 失败处理:强制 mode=evaluate_existing,丢弃 new_thesis 内容
- meta 记录:`activations.validator_6_thesis_lock`

**Validator 7**:`mode=evaluate_existing` 输出 `still_valid=invalidated` 时,必须填 `which_break_triggered`,且必须是 active_thesis.break_conditions 中已客观触发的某条
- 失败处理:降级为 `still_valid=weakened`,notes 添加 `invalidation_rejected_no_break_triggered`
- meta 记录:`activations.validator_7_invalidation_check`

**Validator 8**:`mode=new_thesis` 时,break_conditions 必须 ≥ 3 条且全部客观可判定
- 主观条件示例(被拒):"市场情绪转空" / "趋势反转" / "宏观恶化"
- 客观条件示例(通过):"1D 收盘跌破 X" / "DXY 突破 Y 持续 N 天" / "L5 extreme_event_detected=true"
- 失败处理:重试 1 次,再失败 → fallback 不创建 thesis
- meta 记录:`activations.validator_8_break_objectivity`

**Validator 9**:`mode=new_thesis` 时,break_conditions 距当前距离合理性
- 价格类 break:距当前 ≤ 20%
- 指标类 break(DXY/VIX 等):距当前 ≤ 15%
- 事件类 break(L5/macro):不限距离
- 失败处理:重试 1 次,再失败 → fallback 不创建
- meta 记录:`activations.validator_9_break_distance`

### 3.4.3 grade 封闭类(2 条,v1.4 强化)

**Validator 10**:master 输出的 opportunity_grade 必须严格等于 L3 输出
- 失败处理:覆盖为 L3 给的,notes 添加 `grade_overridden_to_l3`
- meta 记录:`activations.validator_10_grade_lock`

**Validator 11**:`mode=evaluate_existing` 时,master 不能改 active_thesis 的 direction
- 失败处理:重试 1 次,再失败 → fallback 保留旧 thesis
- meta 记录:`activations.validator_11_direction_lock`

### 3.4.4 evidence 真实性类(3 条,v1.3 + v1.4 强化)

**Validator 12**:AI 引用的 evidence_ref 必须在 evidence_cards 真实存在
- 失败处理:从 primary_drivers 删除该项,notes 添加 `missing_evidence_ref`
- meta 记录:`activations.validator_12_evidence_real`

**Validator 13**:objective_evidence 必须引用上下文中真实存在的字段值
- 失败处理:重试 1 次,再失败 → 该 objective_evidence 项被删除
- meta 记录:`activations.validator_13_objective_evidence`

**Validator 14**:narrative 必须包含至少 1 条 counter_arguments
- 失败处理:notes 添加 `missing_counter_argument`
- meta 记录:`activations.validator_14_counter_argument`

### 3.4.5 信心和质量类(3 条,继承 v1.3 + v1.4 强化)

**Validator 15**:AI 给的 confidence 必须 ≤ data_completeness × historical_precedent_match
- Fallback Level 1+ 时 confidence 必须 < 0.7
- 失败处理:cap 到合法值,notes 添加 `confidence_capped`
- meta 记录:`activations.validator_15_confidence_cap`

**Validator 16**:what_would_change_mind 必须至少 3 条且全部客观可判定
- 失败处理:重试 1 次,再失败 → notes 添加 `what_would_change_mind_insufficient`
- meta 记录:`activations.validator_16_change_mind`

**Validator 17**:weakened 状态下 stop_loss 收紧上限
- 同一 thesis 内最多收紧 2 次
- stop_loss 距离不能高于初始 stop 距离的 50%(即不能从 -10% 收紧到 -3%)
- 失败处理:拒绝收紧,notes 添加 `stop_tightening_capped`
- meta 记录:`activations.validator_17_stop_tightening`

### 3.4.6 系统级反复横跳类(3 条,v1.4 新增)

**Validator 18**:14 天反复横跳熔断
- 14 天内 thesis 完整周期 ≥ 2 次 → 强制进入 14 天 FLAT 熔断 + critical 告警
- 14 天内通道 C 触发 ≥ 2 次 → 14 天禁用通道 C
- 失败处理:已经在熔断期 → 拒绝创建 thesis
- meta 记录:`activations.validator_18_14d_fuse`

**Validator 19**:60 天 thesis 上限
- thesis 创建满 60 天且未关闭 → 进入 review_pending
- 失败处理:挂单仍按 thesis 触发,但不允许新加仓 / 调整 stop
- meta 记录:`activations.validator_19_60d_cap`

**Validator 20**:连续熔断保护
- 连续 2 次 14 天熔断 → 进入 review_pending,要求用户审视系统设计
- meta 记录:`activations.validator_20_consecutive_fuse`

### 3.4.7 master AI 软抗拒识别(2 条,v1.4 新增)

**Validator 21**:master AI 软抗拒识别
- 满足 thesis 创建条件(无 active + 不在冷却 + 不在熔断 + L3 grade ∈ {A, B, **C**})但 master 输出 silent
- 失败处理:重试 1 次,再失败 → fallback(可能是 master 出 bug)
- meta 记录:`activations.validator_21_soft_resistance`

**Validator 22**:master AI 连续 3 天失败兜底
- master AI 连续 3 天失败 → 进入 review_pending
- 期间挂单仍按 thesis 触发,但不允许新加仓 / 调整 stop
- 推送 critical 告警
- meta 记录:`activations.validator_22_3day_fail`

### 3.4.8 conflict_resolution(1 条,继承 v1.3)

**Validator 23**:主裁 AI 必须输出 conflict_resolution 字段(可以是"无层间矛盾")
- 失败处理:notes 添加 `conflict_resolution_missing`
- meta 记录:`activations.validator_23_conflict`

### 3.4.9 Meta 约束(1 条,v1.4 新增 — 灵魂条款)

**Validator 24**(meta):硬约束激活频率监控

每次 run 写一个"硬约束触发日志":

```python
constraint_activations = {
    "validator_1_stop_loss_overridden": False,
    "validator_2_position_capped": False,
    "validator_3_entry_size_normalized": False,
    "validator_4_protection_blocked": False,
    "validator_5_none_grade_blocked": False,
    "validator_6_thesis_lock": False,
    "validator_7_invalidation_check": False,
    "validator_8_break_objectivity": False,
    "validator_9_break_distance": False,
    "validator_10_grade_lock": False,
    "validator_11_direction_lock": False,
    "validator_12_evidence_real": False,
    "validator_13_objective_evidence": False,
    "validator_14_counter_argument": False,
    "validator_15_confidence_capped": True,  # 这次激活了
    "validator_15_capped_value": 0.65,        # 限制后的值
    "validator_16_change_mind": False,
    "validator_17_stop_tightening": False,
    "validator_18_14d_fuse_active": False,
    "validator_19_60d_cap": False,
    "validator_20_consecutive_fuse": False,
    "validator_21_soft_resistance": False,
    "validator_22_3day_fail": False,
    "validator_23_conflict_missing": False,
    "position_cap_compressed": 0.49,  # 实际压缩值
    "thesis_lock_active": True,
    "in_cooldown": False,
    "cooldown_remaining_hours": 0,
}
```

**字段存储**(v1.4 新增):
- 存入 `strategy_runs.constraint_activations_json` TEXT 字段(JSON serialized)
- 字段格式见上述 Python dict 序列化为 JSON 字符串
- 数据库 schema 改动归属 sprint 1.10-A(随 virtual_account / theses 三表一起加)

**周复盘 AI 用此日志评估**(对应 §3.3.9 weekly_review_analyst 的 `hard_constraint_activation_review` 段):
- 某条触发率 > 5/7 天 → 可能阈值太严,建议放宽
- 某条从不触发(0/7 天)→ 可能阈值太松或该约束没用,建议审视
- `position_cap_compressed` 平均值 < 30% → 可能过度保守
- `thesis_lock_active` 占比过高 → 可能 thesis 太长不出新机会
- **必须**:周复盘 AI 输出对**每条 Validator(1-23)**的激活率统计 + 评估结论(过严/适中/过松/未触发)

**这是"刚刚好"的最后一道保险**。系统能自我察觉硬约束是否在合理频率激活。

---

# 第四部分:状态机简化(v1.4 重写)

## 4.1 状态空间(v1.4 重新设计)

v1.3 沿用 v1.2 的 14 档(LONG/SHORT 镜像 + FLIP_WATCH + PROTECTION + POST_PROTECTION_REASSESS)。
v1.4 简化:

### 4.1.1 thesis 内部 lifecycle(5 档)

```
planned → opened → holding → trim → closed
```

每档含义:
- `planned`:thesis 创建,挂单已下,未触发任何 entry
- `opened`:至少 1 个 entry 挂单已触发,有持仓
- `holding`:持仓满 24 小时 + 走势确认(继承 v1.2 §5.2 的"时间+走势组合"标准)
- `trim`:已触发至少 1 个 take_profit,部分平仓
- `closed`:完全平仓(triggered by stop_loss / 全部 take_profit / break_conditions / 60 天上限)

thesis 内部 direction 字段表示多空(long / short),不再用状态名区分。

### 4.1.2 系统级特殊态(2 档)

- `PROTECTION`:极端事件触发,系统自动应急停,AI 暂停 30 分钟,所有 active thesis 进入 review_pending
- `review_pending`:需要用户介入的兜底状态,触发场景:
  - master AI 连续 3 天失败(Validator 22)
  - thesis 满 60 天未关闭(Validator 19)
  - 连续 2 次 14 天熔断(Validator 20)
  - 极端事件期间(由 PROTECTION 触发)

### 4.1.3 默认态

- `FLAT`:无 active thesis,可以创建新 thesis(若不在冷却/熔断/PROTECTION/review_pending)

### 4.1.4 v1.4 状态空间总览

```
默认态: FLAT
thesis 内部: planned / opened / holding / trim / closed
系统特殊态: PROTECTION / review_pending
冷却态(隐式): 通过 thesis.closed_at + 冷却时长计算
熔断态(隐式): 通过 14d 熔断计数计算
```

### 4.1.5 v1.2 14 档 ↔ v1.4 5 档映射(v1.4 关键澄清)

v1.4 简化的实质是"用 `thesis.direction` 字段消除 LONG/SHORT 镜像,用 `lifecycle_stage` 简化生命周期",不是丢掉建模信息:

| v1.2 14 档(旧) | v1.4 等价表达 |
|---|---|
| FLAT | FLAT(无 active thesis) |
| LONG_PLANNED | active thesis: direction=long, lifecycle_stage=planned |
| LONG_OPEN | active thesis: direction=long, lifecycle_stage=opened |
| LONG_HOLD | active thesis: direction=long, lifecycle_stage=holding |
| LONG_TRIM | active thesis: direction=long, lifecycle_stage=trim |
| LONG_EXIT | thesis status=closed_profit/loss(direction=long) |
| SHORT_PLANNED | active thesis: direction=short, lifecycle_stage=planned |
| SHORT_OPEN | active thesis: direction=short, lifecycle_stage=opened |
| SHORT_HOLD | active thesis: direction=short, lifecycle_stage=holding |
| SHORT_TRIM | active thesis: direction=short, lifecycle_stage=trim |
| SHORT_EXIT | thesis status=closed_profit/loss(direction=short) |
| FLIP_WATCH | 冷却态(thesis.closed_at + 冷却时长内,无 active thesis) |
| PROTECTION | PROTECTION(系统级特殊态,保留) |
| POST_PROTECTION_REASSESS | review_pending(由 PROTECTION 解除时触发) |

**实施迁移工作**(归 sprint 1.10-J):
- 代码层 14 档枚举 → 改为 thesis lifecycle_stage 5 档 + 系统态 2 档
- master_adjudicator.txt prompt 中所有 14 档枚举引用 → 改为 thesis-aware 表述
- state_machine.py 转换层(读旧 14 档字段时映射到 thesis 模型)
- 数据库历史 strategy_runs 行不动(向后兼容,只新增 thesis_id 关联)

## 4.2 状态迁移(v1.4 重写)

### 4.2.1 FLAT → thesis 创建(planned)

条件(全部满足):
- 无 active thesis
- 不在冷却期(上次 thesis 关闭时长 ≥ 冷却时长)
- 不在 14 天熔断期
- 不在 PROTECTION
- 不在 review_pending
- **L3 grade ∈ {A, B, C}**(C 级也允许创建,但 execution_permission 限制为 ambush_only)
- master 通过 Validator 24 全部检查

### 4.2.2 planned → opened

条件:`virtual_orders` 中至少 1 个 entry 类型订单 status=filled。

由挂单引擎自动判定(每次 16:00 跑前 + 持仓期 4h 检查时 + 事件触发时)。

### 4.2.3 opened → holding(继承 v1.2 §5.2 标准)

条件:**时间满 24 小时 + 走势确认至少 1 项**:
- 浮盈 ≥ +2%(做多)/ ≤ -2%(做空)
- 已穿越开仓后第一个 4H 收盘且方向未反转
- 已度过至少一次回撤-反弹小周期
- 价格已达 take_profit 第一档 50% 距离

### 4.2.4 holding → trim

条件:至少 1 个 take_profit 订单 status=filled。

### 4.2.5 trim → closed(止盈完成)

条件:所有 take_profit 订单 status=filled 或剩余持仓 = 0。

### 4.2.6 任意 thesis 状态 → closed(止损/失效/上限)

任一触发 → 立即 closed:
- stop_loss 订单 status=filled(止损触发)
- master AI 评估为 invalidated 且 break_conditions 真实触发(Validator 7 通过)
- thesis 创建满 60 天(Validator 19,进 review_pending,挂单不再调整但仍按计划触发)
- 极端事件(PROTECTION)期间自动平仓

### 4.2.7 closed → 冷却期 → FLAT

冷却时长按反手通道判定(见 §5):
- 通道 A(慢):自然结束 → 3 天冷却
- 通道 B(中):break 触发失效 → 24 小时冷却
- 通道 C(快):满足条件 → 0 冷却

### 4.2.8 任意状态 → PROTECTION(极端事件)

由规则层 §3.2.3 触发。所有 active thesis 进入 review_pending,挂单暂停,AI 调用暂停 30 分钟。

### 4.2.9 PROTECTION → 退出条件

- 极端事件结束(BTC 1H 价格回到 ±10% 以内 + VIX 回落)
- 30 分钟冷静期已过
- 用户手动确认

退出后所有 review_pending thesis 由用户决定:续期 / 平仓 / reset 熔断。

## 4.3 反手 3 档通道(v1.4 落地)

### 4.3.1 通道 A(慢通道,默认)

触发条件:thesis 自然结束(closed_profit / closed_loss)
- 接全部 take_profit → closed_profit
- 触发 stop_loss → closed_loss

冷却:**3 天**(72 小时)

适用:99% 常规情况

### 4.3.2 通道 B(中通道,加速反手)

触发条件:thesis 失效(status=invalidated,即 break_conditions 触发)

冷却:**24 小时**

适用:论点失效但市场未极端

### 4.3.3 通道 C(快通道,紧急反手)

触发条件:**4 个条件分级满足**:
1. 价格击穿 stop_loss(已平仓)
2. L1 regime 完全反转(trend_up → trend_down,不是过渡态)
3. L2 stance 强翻转(confidence ≥ 0.75)
4. L5 极端事件 OR macro_stance 翻转 risk_off

分级逻辑:
- 满足 4/4 → 通道 C(立即反手,0 冷却)
- 满足 3/4 → 通道 C(立即反手,0 冷却)
- 满足 2/4 + L1 regime 完全反转 → 通道 B(24h 冷却)
- 满足 1-2/4 → 维持 thesis,master 可评估为 weakened

### 4.3.4 14 天反复横跳熔断(v1.4 新增)

由 Validator 18 实施:
- 14 天内 thesis 完整周期 ≥ 2 次 → 强制 FLAT 14 天 + critical 告警
- 14 天内通道 C 触发 ≥ 2 次 → 14 天禁用通道 C

### 4.3.5 三条核心纪律(继承 v1.3 §4.3,v1.4 落地)

1. **不允许凭感觉反手**:必须经 thesis 关闭(慢/中/快通道之一)
2. **冷却期强制**:1H 信号永远不能单独触发方向切换
3. **PROTECTION 全局入口,唯一出口经用户确认或 30 分钟冷静期 + 极端事件结束**

---

# 第五部分:虚拟账户 + 挂单引擎 + thesis 生命周期(v1.4 全新)

## 5.1 虚拟账户(virtual_account)

### 5.1.1 设计目的

让 AI 系统有"位置感"——所有后续策略基于真实持仓状态做(浮盈浮亏 / 加仓/减仓/反手判断)。

不接真实交易所账户(用户硬约束:不自动下单)。

### 5.1.2 DB 表结构

```sql
CREATE TABLE virtual_account (
    snapshot_id        TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL UNIQUE,
    snapshot_at_utc    TEXT NOT NULL,
    btc_price_at_snapshot REAL NOT NULL,
    
    -- 资金
    initial_capital    REAL NOT NULL,           -- 100000(永久不变)
    available_cash     REAL NOT NULL,
    
    -- 多头持仓
    long_position_usdt REAL NOT NULL DEFAULT 0,
    long_avg_price     REAL,
    long_btc_amount    REAL NOT NULL DEFAULT 0,
    
    -- 空头持仓
    short_position_usdt REAL NOT NULL DEFAULT 0,
    short_avg_price    REAL,
    short_btc_amount   REAL NOT NULL DEFAULT 0,
    
    -- 收益指标
    total_equity       REAL NOT NULL,
    realized_pnl_total REAL NOT NULL DEFAULT 0,
    unrealized_pnl     REAL NOT NULL DEFAULT 0,
    total_return_pct   REAL NOT NULL DEFAULT 0,
    
    FOREIGN KEY (run_id) REFERENCES strategy_runs(run_id)
);

CREATE INDEX idx_va_time ON virtual_account(snapshot_at_utc);
```

### 5.1.3 初始化

系统首次部署当天:
- snapshot_id, run_id 关联首次 run
- initial_capital = 100000(可配置,通过 config/base.yaml `virtual_account.initial_capital`)
- available_cash = 100000
- 其他字段全 0
- total_equity = 100000
- total_return_pct = 0

### 5.1.4 每次 run 快照

每次 strategy_run 完成后写一行 virtual_account,跟 strategy_runs 1:1 对齐。

### 5.1.5 收益率计算

- 日收益率:今日 total_equity / 昨日 total_equity - 1
- 周/月/年/至今:基于历史快照 total_equity 计算

## 5.2 挂单引擎(virtual_orders)

### 5.2.1 设计目的

精确管理"挂单 → 触发 → 持仓"全流程。所有挂单都是精确价格(不是区间)。

### 5.2.2 DB 表结构

```sql
CREATE TABLE virtual_orders (
    order_id           TEXT PRIMARY KEY,
    thesis_id          TEXT NOT NULL,
    direction          TEXT NOT NULL,           -- long / short
    order_type         TEXT NOT NULL,           -- entry / stop_loss / take_profit
    
    price              REAL NOT NULL,           -- 精确挂单价
    size_pct           REAL NOT NULL,           -- 占总仓百分比
    size_usdt          REAL NOT NULL,           -- = initial_capital × size_pct
    
    status             TEXT NOT NULL,           -- pending / filled / cancelled / expired
    created_at_utc     TEXT NOT NULL,
    expires_at_utc     TEXT NOT NULL,           -- 创建 + 7 天
    
    filled_at_utc      TEXT,
    filled_price       REAL,                    -- = price(等于挂单价)
    filled_btc_amount  REAL,                    -- = size_usdt / filled_price
    
    cancelled_reason   TEXT,                    -- thesis_invalidated / superseded / expired / manual
    
    FOREIGN KEY (thesis_id) REFERENCES theses(thesis_id)
);

CREATE INDEX idx_vo_status ON virtual_orders(status);
CREATE INDEX idx_vo_thesis ON virtual_orders(thesis_id);
```

### 5.2.3 触发逻辑

每次 16:00 主 run 时(也在 4h 健康检查 / 事件触发 / 每小时硬失效位监控时):

```python
def check_orders(active_thesis):
    # 取上次检查至今所有 1H K 线
    klines = get_1h_klines_since(last_check_utc)
    
    for order in active_thesis.pending_orders:
        if order.expires_at_utc < now_utc:
            mark_expired(order)
            continue
        
        for kline in klines:
            # 价格穿过判定:1H low ≤ price ≤ high
            if kline.low <= order.price <= kline.high:
                fill_order(
                    order_id=order.order_id,
                    filled_price=order.price,        # 入场价 = 挂单价
                    filled_at_utc=kline.close_time,
                    filled_btc_amount=order.size_usdt / order.price
                )
                update_virtual_account(...)
                update_thesis_lifecycle_stage(...)
                push_notification(...)
                break
```

### 5.2.4 入场价处理(v1.4 关键)

挂单 = $74568(精确)
1H K 线 low=$73500,high=$76000(穿过 $74568)
- 入场价 = **$74568**(挂单价,不是 1H 收盘价,不是 K 线 high/low)
- 持仓金额 = `initial_capital × size_pct`(例 100000 × 20% = 20000)
- BTC 数量 = `20000 / 74568 = 0.2682 BTC`

### 5.2.5 同 1H 多挂单全触发

1H K 线 high=$76000,low=$70000,2 个挂单 $74568(20%)和 $70666(30%):
- 都满足 low ≤ price ≤ high
- **两个都触发**
- 总持仓 50%,均价 = (20000 × 1 + 30000 × 1) / (20000/74568 + 30000/70666)

### 5.2.6 挂单有效期

默认 **7 天**。过期自动 cancelled,reason=`expired`。

如果 7 天内挂单未触发但 thesis 仍 active(没击穿 break),master 可在下次 16:00 评估时重新出挂单(或确认旧挂单延期,通过新生成同价位挂单实现)。

## 5.3 thesis(论点)生命周期

### 5.3.1 设计目的

把所有挂单/持仓/止盈止损绑到**同一个 thesis**:
- thesis 失效 → 整个 lifecycle 结束
- thesis 期间不允许出反向方向(由 Validator 6 / 11 强制)

### 5.3.2 DB 表结构

```sql
CREATE TABLE theses (
    thesis_id              TEXT PRIMARY KEY,
    created_at_run_id      TEXT NOT NULL,
    created_at_utc         TEXT NOT NULL,
    direction              TEXT NOT NULL,        -- long / short
    
    -- 论点核心(创建后不可变)
    core_logic             TEXT NOT NULL,
    confidence_score       INTEGER NOT NULL,     -- 0-100,master 给
    
    -- 失效条件(3 条客观可判定,Validator 8/9 强制)
    break_conditions       TEXT NOT NULL,        -- JSON: ["1D 收盘跌破 70000", ...]
    
    -- 生命周期阶段
    lifecycle_stage        TEXT NOT NULL,        -- planned / opened / holding / trim / closed
    
    -- 状态
    status                 TEXT NOT NULL,        -- active / invalidated / closed_profit / closed_loss / closed_60d_cap / closed_protection
    invalidated_reason     TEXT,                 -- 失效时填:"1D 跌破 70000 已触发"
    closed_at_utc          TEXT,
    
    -- 评估快照(每次 run 更新)
    last_assessment        TEXT,                 -- fully / mostly / partially / weakened / invalidated
    last_assessment_note   TEXT,
    last_assessment_at_run TEXT,
    
    -- 反手通道(v1.4 新增,closed 时填)
    close_channel          TEXT,                 -- A / B / C
    
    -- 最终结果(closed 时填)
    final_realized_pnl     REAL,
    final_realized_pnl_pct REAL,
    final_outcome          TEXT                  -- profit / loss / breakeven / 60d_cap / protection
);

CREATE INDEX idx_theses_status ON theses(status);
CREATE INDEX idx_theses_created ON theses(created_at_utc);
```

### 5.3.3 创建条件(全部满足)

由 §4.2.1 + Validator 6 共同把守。

### 5.3.4 评估(每天 16:00)

由 master AI mode=evaluate_existing 完成。详细见 §3.3.6。

### 5.3.5 失效条件(任一触发)

- break_conditions 任一客观触发(Validator 7 检查)
- stop_loss 订单触发(规则平仓)
- 60 天上限(Validator 19)
- 极端事件 PROTECTION(规则强制)

### 5.3.6 weakened 状态处理(v1.4 关键)

当 master 评估 still_valid=weakened 时:
- 允许 stop_loss 收紧(Validator 17 限制:同一 thesis 内最多 2 次,不能高于初始距离 50%)
- 允许 take_profit 缩短(部分获利了结)
- **不允许反向**(必须等 invalidated)
- **不允许新加仓**(只允许减仓 / 调 stop)

### 5.3.7 review_pending 三种出口(v1.4 关键)

进入 review_pending 后,挂单仍按 thesis 触发,但不允许新加仓 / 调整 stop。用户介入后 3 种出口:

- **出口 A — 调阈值**:用户调 L3 / break_conditions / 通道 C 阈值,bump rules_version,系统继续跑
- **出口 B — 续期 thesis**:用户手动创建新 thesis 接续旧的(继承 origin_logic 但更新 break_conditions / stop_loss)
- **出口 C — reset 熔断**:用户判断 master 仍可信,手动 reset 14 天熔断 / 60 天上限 / 3 天连续失败计数,系统继续跑

详细 UI 见 §9。

## 5.4 反手 3 档通道(详见 §4.3,这里只列对应字段映射)

| 通道 | thesis.status | thesis.close_channel | 冷却时长 |
|---|---|---|---|
| A 慢通道 | closed_profit / closed_loss | A | 3 天 |
| B 中通道 | invalidated | B | 24 小时 |
| C 快通道 | invalidated | C | 0 |

---

# 第六部分:频率与触发设计(v1.4 重写)

## 6.1 数据收集频率(继承 v1.3 §5.1,不变)

数据采集与 AI 决策解耦:
- 价格:1H/4H/1D/1W
- 衍生品:多数 1H,资金费率 8H
- 链上:多数每天,Exchange Net Flow 每小时
- 宏观:每天

`scheduler.yaml::data_collection: 1h`,**不消耗 AI token**。

## 6.2 AI 决策频率(v1.4)

### 6.2.1 主决策(每天 1 次)

| 触发 | AI 方案 | 频率 | 单次成本 |
|---|---|---|---|
| 每日 16:00 BJT(美东收盘) | 完整 A(6 AI 协作) | 1 次/天 | ~$0.30 |
| 手动触发 | 完整 A | 按需 | ~$0.30 |

### 6.2.2 持仓期辅助(*_OPEN / *_HOLD / *_TRIM)

| 触发 | AI 方案 | 频率 | 单次成本 |
|---|---|---|---|
| 每 4h 整点(持仓期间才跑) | 持仓健康检查(单 AI 简化版) | 6 次/天 | ~$0.05 × 6 |

### 6.2.3 事件触发(v1.4 — 继承 v1.3 双轨设计)

| 触发条件 | 状态 | AI 方案 | 频率(平均) | 单次成本 |
|---|---|---|---|---|
| **价格异动 ±5%(event_price_flat)** | 空仓 / planned / cooldown | 简化 A(应急 AI) | 0-1 次/天 | ~$0.10 |
| **价格异动 ±3%(event_price_holding)** | 持仓中(opened/holding/trim) | 简化 A(应急 AI) | 0-2 次/天 | ~$0.10 |
| **硬失效位击穿(event_invalidation,v1.4 新增)** | 任何状态 | **规则平仓(无 AI)** + 推送 critical 告警 | 罕见 | $0 |
| 价格触及 stop_loss | opened/holding/trim | 规则平仓(无 AI) | 罕见 | $0 |

**双轨阈值的逻辑**(继承 v1.3):
- 空仓时风险低,5% 才需要响应,避免无意义 AI 消耗
- 持仓时风险高,3% 就要重新评估持仓 thesis
- 硬失效位击穿是 v1.4 新增的"规则平仓"机制,不调 AI 直接处理(快且零成本)

**节流**:
- 同类事件 7200 秒(2h)内只触发一次(`event_cooldown_seconds: 7200`)
- 距上次主 AI 介入 < 1800 秒(30 分钟)时跳过事件触发(`skip_if_recent_scheduled_seconds: 1800`)
- 防止主 AI 介入完成后立刻又被价格扰动重新触发,造成噪音

**事件日历角色澄清**(继承 v1.3 §2.7 决策):
- 事件日历(FOMC/CPI/NFP/PCE)在 v1.3 已确定**仅参考显示,不参与策略评分**
- v1.4 新增的 `event_invalidation` 触发是**价格层信号**(硬失效位被击穿),不是事件日历驱动
- 事件日历只在网页"未来 72H 事件"区显示,master AI prompt 也会接收作为背景参考(L5 输入),但不直接触发任何策略动作
- v1.4 不恢复"事件日历驱动决策"机制

### 6.2.4 周复盘(v1.4 新增)

| 触发 | AI 方案 | 频率 | 单次成本 |
|---|---|---|---|
| 每周日 22:00 BJT | weekly_review_analyst(单 AI) | 1 次/周 | ~$0.15 |

### 6.2.5 PROTECTION / review_pending

按规则处理,AI 调用暂停。

### 6.2.6 总成本估算(v1.4)

按 30% 持仓 / 70% 空仓比例(继承 v1.3 估算):

```
空仓期(70%):
  每日完整 A:30 × 0.7 × $0.30 = ~$6.30/月
  ±5% 异动触发:5 × $0.10 = ~$0.50/月

持仓期(30%):
  每日完整 A:30 × 0.3 × $0.30 = ~$2.70/月
  4h 健康检查:6 × 30 × 0.3 × $0.05 = ~$2.70/月
  ±3% 异动触发:8 × $0.10 = ~$0.80/月

周复盘:
  4 × $0.15 = ~$0.60/月

AI 重试(失败时,平均按 5%/月触发):
  ~$0.50/月

总计:~$14.10/月 ≈ $14/月
```

跟 v1.3 估算 $13-15 完全一致。v1.4 新增的 weekly_review 成本几乎被双轨阈值精细化抵消。

## 6.3 AI 重试机制(v1.4 新增)

### 6.3.1 层级依赖图

```
L1 (AI) ──┬──► L2 (AI) ──┬──► L3 (AI) ──┬──► Master (AI)
          │              │              │
          ├──► L4 (AI)   ┤              │
          │  规则给候选    │              │
          │              │              │
          └──► L5 (AI) ──┘              │
```

短路规则:
- L1 失败 → L2/L3/Master 全部短路,L4/L5 仍跑
- L2 失败 → L3/Master 短路,L4/L5 仍跑
- L3 失败 → Master 短路,L4/L5 仍跑
- **L4 失败 → Master 短路**(L4 给的 stop_loss / position_cap_pct 缺失,master 无法生成 trade_plan)
- L5 失败 → Master 仍跑(用规则化 macro fallback,macro_headwind_score=0)
- Master 失败 → 无策略输出,但可重试

### 6.3.2 重试策略

- **重试间隔**:**指数退避**(5 / 10 / 20 分钟)
- **单层重试**:最多 3 次(共 35 分钟)
- **整次窗口**:**2 小时**(BJT 16:00-18:00)
- **网页显示**:失败层显示"AI 介入失败,重试中(第 N 次)"

### 6.3.3 超时处理(BJT 18:00 仍未成功)

- 放弃,fallback 保留上次策略
- 推送 critical 告警(明确告知用户哪层失败)
- 等明天 BJT 16:00 重试
- 连续 3 天失败 → Validator 22 触发 review_pending

### 6.3.4 网页显示(v1.4 重要)

失败时网页必须**清楚告诉用户**:
- 哪层失败(L1 / L2 / L3 / L5 / Master)
- 重试次数
- 失败原因(timeout / api_error / parse_error / validation_failed)
- 当前用的是哪次成功 run 的策略(如果走 fallback)

不能用模糊的"无机会"误导用户。

## 6.4 fallback thesis-aware 改造(v1.4)

### 6.4.1 v1.3 老 fallback(已废弃)

v1.3 §3.2.5 写"AI 失败 → fallback 走规则模板,permission 强制 watch"。**v1.4 改**。

### 6.4.2 v1.4 新 fallback

| 场景 | fallback 行为 |
|---|---|
| 有 active thesis + master 失败 | 保留 thesis 不评估,挂单仍按计划触发,等下次重试 |
| 无 active thesis + master 失败 | silent(不创建新 thesis),等下次重试 |
| 有 active thesis + L1/L2/L3 失败 | 同"master 失败"处理 |
| L5 失败 | Master 仍跑,用规则化 macro fallback(macro_headwind_score=0) |
| 数据降级 Level 2+ | 不调 AI,所有 thesis 进入 review_pending,等数据恢复 |

**绝对不允许 fallback 创建 / 关闭 thesis**(避免规则错误关键决策)。

---

# 第七部分:策略输出模型 StrategyState v1.4

## 7.1 设计原则(继承 v1.3 + v1.4 调整)

1. 扁平与嵌套的平衡:业务块嵌套,块内字段扁平
2. 所有字段"可回放":每个值独立理解
3. 枚举全部预定义
4. 为网页展示预留叙事字段
5. **v1.4 新增**:为 v1.5 backtest 兼容预留

## 7.2 完整字段结构

详细字段不重复列举(过于冗长),核心结构:

### Block 1:meta(继承 v1.3,删 cold_start)

| 字段 | 类型 | 备注 |
|---|---|---|
| schema_version | string | "v1.4.0" |
| run_id | string | 唯一 |
| previous_run_id | string | |
| generated_at_bjt | string | |
| generated_at_utc | string | |
| reference_timestamp_utc | string | |
| system_version | string | |
| rules_version | string | |
| run_mode | enum | live / backtest / replay / dry_run |
| run_trigger | enum | scheduled / event_price / event_invalidation / manual / weekly_review |
| ai_model_actual | string | 从中转站响应读 |
| ~~cold_start~~ | ~~bool~~ | **v1.4 删除** |

### Block 2:data_health(继承 v1.3,不变)

### Block 3:market_snapshot(继承 v1.3 + v1.4 增 ATH)

### Block 4:layer_outputs(L1/L2/L3/L4/L5,继承 v1.3)

### Block 5:thesis_evaluation(v1.4 新增)

```json
{
  "active_thesis_id": "...",
  "mode": "evaluate_existing | new_thesis | silent_cooldown",
  "thesis_assessment": {...} | null,
  "new_thesis": {...} | null,
  "silent_reason": "..." | null
}
```

### Block 6:trade_plan(继承 v1.3,v1.4 改:精确价格挂单)

```json
{
  "direction": "long | short",
  "confidence_score": 85,
  "entry_orders": [
    {"price": 74568, "size_pct": 20, "order_id": "..."},
    {"price": 70666, "size_pct": 30, "order_id": "..."}
  ],
  "stop_loss": {"price": 63000, "size_pct": 100, "order_id": "..."},
  "take_profit": [
    {"price": 85000, "size_pct": 30, "order_id": "..."},
    {"price": 90000, "size_pct": 40, "order_id": "..."}
  ]
}
```

### Block 7:virtual_account_snapshot(v1.4 新增)

```json
{
  "snapshot_id": "...",
  "total_equity": 103250,
  "available_cash": 50000,
  "long_position_usdt": 50000,
  "long_avg_price": 74568,
  "long_btc_amount": 0.6747,
  "unrealized_pnl": 750,
  "realized_pnl_total": 2500,
  "total_return_pct": 0.0325
}
```

### Block 8:constraint_activations(v1.4 新增,Meta 约束)

详见 §3.4.9。每条 Validator 是否激活 + meta 统计字段。

### Block 9:fallback_info(继承 v1.3)

### Block 10:narrative(继承 v1.3,5 段推演)

---

# 第八部分:复盘、监控与回测

## 8.1 周复盘(v1.4 新增,详见 §3.3.9)

每周日 22:00 BJT 自动跑 weekly_review_analyst。输出 4 段 JSON:performance / system_health / strategy_quality / adjustment_recommendations + hard_constraint_activation_review。

复盘结果:
- **不自动改参数**(系统硬纪律)
- 网页"周复盘"模块展示
- critical 级别建议 → 推送告警
- 用户根据建议**手动**调阈值/prompt
- 调整必须 bump rules_version

## 8.2 过度保守监控(S3,v1.4 新增)

- **连续 30 天无 thesis 创建 → warning 告警**
- **连续 60 天无 thesis 创建 → critical + 用户介入审视 L3 阈值**
- 由规则层每天 16:00 跑前检查 + 写入 alerts 表

## 8.3 回测验收(继承 v1.3 §7,v1.4 不阻塞)

v1.3 §7 提的"M26 三场景回测"(2020 主升 / 2022 主跌 / 2023 震荡)在 v1.3 sprint 1.11 已经实施。

**v1.4 不在主线 sprint 重做回测**,但要求:
- v1.4 schema 兼容 v1.5 backtest 重放(虚拟账户字段 / thesis 字段都可重放)
- v1.5 sprint 单独做"用真实 AI 输出回测"

## 8.4 监控告警(v1.4 强化)

新增告警事件:
- thesis_created
- thesis_closed_profit / closed_loss / closed_invalidated / closed_60d_cap
- channel_c_used
- 14d_fuse_triggered
- 14d_fuse_consecutive(进 review_pending)
- 60d_thesis_cap(进 review_pending)
- review_pending_entered
- review_pending_resolved
- master_3day_fail(进 review_pending)
- weekly_review_critical_recommendation
- hard_constraint_anomaly(meta 约束发现某条触发率异常)

---

# 第九部分:网页与 API 设计(v1.4)

## 9.1 v1.4 网页改造原则

**v1.4 硬约束**:
- **风格锁定**:audit-card / font-mono / 12 卡平铺
- **只加新模块,不改任何现有 UI**
- 现有 12 卡 + 五层分析 6 卡保留

## 9.2 新增 5 个模块(v1.4)

按从上到下顺序插入(不改现有模块位置):

### 9.2.1 模块 1:虚拟账户面板

位置:在"AI 策略建议"下方,"五层分析"上方。

字段:
- 总资产 / 初始资金
- 总收益(USDT + %)
- 日 / 周 / 月 / 年 / 至今收益率
- 可用现金 / 持仓金额
- 浮盈浮亏 / 已实现
- 30 天资金曲线小图

### 9.2.2 模块 2:当前 thesis 卡

位置:虚拟账户面板下方。

字段:
- thesis_id / direction / confidence_score / lifecycle_stage
- 创建时间 + 已持续天数
- core_logic
- last_assessment + reasoning
- break_conditions(3 条)+ 各条距当前距离 + "失效预警"标记
- AI 思考变化(对比上次 run)

### 9.2.3 模块 3:挂单 + 持仓状态

位置:thesis 卡下方。

字段:
- 已成交订单(精确价 / 仓位 / BTC 量 / 时间)
- 待触发挂单(精确价 / 仓位 / 距当前距离 / 剩余有效期)
- stop_loss(价 / 距当前距离 / 触发后亏损)
- take_profit(价 / 仓位 / 距当前距离)

### 9.2.4 模块 4:thesis 历史时间线

位置:在"五层分析"下方。

字段:
- 每个历史 thesis(active 在最上)
- thesis_id / direction / confidence / 状态
- 创建时间 / 关闭时间 / 持续天数
- 实现盈亏 + %
- close_channel(A/B/C)

### 9.2.5 模块 5:周复盘报告

位置:页面底部,与"事件日历"同级。

字段:
- 报告生成时间(每周日 22:00)
- performance summary(7 天数据)
- system health diagnosis(critical / warning / info 分级)
- adjustment recommendations(按优先级排序)

## 9.3 review_pending 强提醒(S5,v1.4 新增)

进入 review_pending 时:
- **网页顶部红色横幅**(无法忽视)
- 数据健康灯变红
- 推送 critical 告警(v1.0 后接电报)
- 用户必须介入才能解除(出口 A/B/C 之一)

## 9.4 失败状态显示(v1.4 改造)

替换当前模糊的"无机会"显示。详见 §6.3.4。

## 9.5 API 接口清单(v1.4)

### 继承 v1.3 现有

1. `GET /api/strategy/current`
2. `GET /api/strategy/stream`
3. `GET /api/strategy/history`
4. `GET /api/strategy/runs/{run_id}`
5. `GET /api/evidence/card/{card_id}/history`
6. `GET /api/system/health`
7. `POST /api/system/run-now`

### v1.4 新增

8. `GET /api/account/current` - virtual_account 最新快照
9. `GET /api/account/history?days=30` - 资金曲线历史
10. `GET /api/account/returns` - 各周期收益率
11. `GET /api/theses/active` - 当前 active thesis
12. `GET /api/theses/history?limit=20` - 历史 thesis 列表
13. `GET /api/theses/{thesis_id}` - 单个 thesis 详情
14. `GET /api/orders/pending` - 当前 pending 挂单
15. `GET /api/orders/history?days=30` - 历史挂单
16. `GET /api/review/weekly/latest` - 最新周复盘
17. `GET /api/review/weekly/history?limit=10` - 复盘历史
18. `POST /api/review_pending/resolve` - 解除 review_pending(出口 A/B/C)

### 修改的 API

`GET /api/strategy/current` 增加返回字段:
- account_summary
- active_thesis(摘要)
- position_summary
- pending_orders_summary

保留现有字段(向后兼容)。

---

# 第十部分:工程落地(v1.4)

## 10.1 技术栈(继承 v1.3,不变)

- Python 3.11+
- FastAPI
- SQLite(v0.x)→ PostgreSQL(v1.0)
- pandas + numpy
- APScheduler
- HTML + Alpine.js + Tailwind
- anthropic Python SDK 经 novaiapi 中转(OpenAI compatible)
- 时区:zoneinfo

## 10.2 中转站配置(继承 v1.3,不变)

`.env` 现有配置:
- `OPENAI_API_BASE=https://us.novaiapi.com/v1`
- `OPENAI_API_KEY=...`
- `OPENAI_MODEL=claude-sonnet-4-5-20250929`
- `BTC_USE_ORCHESTRATOR=true`

## 10.3 项目目录结构(v1.4 新增 3 个表 + 5 个模块)

继承 v1.3 现有,新增:
- `src/strategy/virtual_account.py`(虚拟账户管理)
- `src/strategy/orders_engine.py`(挂单引擎)
- `src/strategy/thesis_manager.py`(thesis 生命周期)
- `src/ai/agents/weekly_review_analyst.py`
- `src/data/storage/dao.py` 加 VirtualAccountDAO / VirtualOrdersDAO / ThesesDAO

## 10.4 配置文件清理(v1.4 修复)

### 10.4.1 scheduler.yaml 改造

```yaml
jobs:
  pipeline_run:
    enabled: true
    cron:                       # 改为 cron 触发(v1.3 是 interval: 4h)
      hour: 8                   # UTC 08:00 = BJT 16:00
      minute: 0
    misfire_grace_time: 600
    coalesce: true
    max_instances: 1

  data_collection:
    enabled: true
    interval: '1h'              # 不变
    misfire_grace_time: 300
    coalesce: true

  weekly_review:                # v1.4 新增
    enabled: true
    cron:
      day_of_week: 'sun'
      hour: 14                  # UTC 14:00 = BJT 22:00
      minute: 0
    misfire_grace_time: 1800

  hard_invalidation_monitor:    # v1.4 新增
    enabled: true
    interval: '1h'              # 每小时检查一次硬失效位
    misfire_grace_time: 60

  position_health_check:        # v1.4 新增(持仓期才跑)
    enabled: true
    interval: '4h'
    misfire_grace_time: 300
    # 内部判断:无持仓时直接返回,不调 AI
```

### 10.4.2 base.yaml 删除冲突段

**删除** `base.yaml::runtime.scheduled.cron_hours_utc: [0, 4, 8, 12, 16, 20]`(跟 scheduler.yaml 冲突)。

scheduler.yaml 是唯一权威源。

### 10.4.3 base.yaml 新增

```yaml
virtual_account:
  initial_capital: 100000
  currency: "USDT"

thesis:
  max_duration_days: 60         # Validator 19
  break_conditions_min: 3       # Validator 8
  break_conditions_distance:
    price_max_pct: 0.20          # Validator 9
    indicator_max_pct: 0.15
    event_no_limit: true

cooldown:
  channel_a_days: 3
  channel_b_hours: 24
  channel_c_hours: 0

fuse:
  rolling_days: 14
  thesis_cycles_threshold: 2    # Validator 18
  channel_c_threshold: 2
  fuse_duration_days: 14
  consecutive_fuse_threshold: 2 # Validator 20

review_pending:
  master_consecutive_fail_days: 3  # Validator 22
  no_thesis_warn_days: 30        # S3 warning
  no_thesis_critical_days: 60    # S3 critical

ai_retry:
  intervals_minutes: [5, 10, 20]   # 指数退避
  max_attempts_per_layer: 3
  total_window_hours: 2

event_trigger:
  # 双轨设计(继承 v1.3 §5.2):空仓时风险低,5% 才响应;持仓时风险高,3% 就响应
  price_pct_flat: 0.05              # 空仓 / planned / cooldown 状态
  price_pct_holding: 0.03           # 持仓中(opened/holding/trim)
  event_cooldown_seconds: 7200      # 同类事件 2h 节流
  skip_if_recent_scheduled_seconds: 1800   # 距上次主 AI 介入 < 30min 跳过
```

## 10.5 v1.4 sprint 实施路径

| Sprint | 内容 | 工作量 | 前置 |
|---|---|---|---|
| **1.10-A** | DB 表 + DAO(virtual_account / virtual_orders / theses)+ 单测 | 2 天 | — |
| **1.10-B** | 虚拟账户管理 + 挂单引擎 + 触发判定 | 2 天 | 1.10-A |
| **1.10-C** | thesis 生命周期 + 反手 3 档通道 + 14 天熔断 + 60 天上限 | 2.5 天 | 1.10-B |
| **1.10-D** | master AI thesis-aware 改造 + System Prompt 重写 | 1.5 天 | 1.10-C |
| **1.10-E** | Validator 24 条 + meta 约束记录 | 1 天 | 1.10-D |
| **1.10-F** | AI 重试机制(指数退避 + 短路依赖 + 2h 窗口) | 2 天 | 1.10-E |
| **1.10-G** | 事件触发(±3% + event_invalidation + 硬失效位 cron) | 2 天 | 1.10-F |
| **1.10-H** | weekly_review_analyst + S3 过度保守监控 | 1.5 天 | 1.10-G |
| **1.10-I** | 网页加 5 模块 + review_pending 红色横幅 + 失败状态显示 | 1.5 天 | 1.10-H |
| **1.10-J** | 配置文件统一 + 旧逻辑清理(详见 §11.2):scheduler.yaml 主策略 `interval: 4h` → `cron: hour: 8`(BJT 16:00)/ 删 base.yaml 冲突段 / 删 observation_classifier / 删 cold_start / 删 account_state / 删 14 档老逻辑 / 全项目 grep "4h" 引用清理 | 1.5 天 | 1.10-I |
| **1.10-K** | hard constraints 调研(SSH 看 prompt 现状)+ prompt 优化 | 1 天 | 1.10-J |
| **1.10-L** | 端到端测试 + 上线 | 1 天 | 1.10-K |
| **总计** | | **19.5 天**(3-4 周) | |

## 10.6 工程纪律(继承 v1.3 §9,不变)

- **§X 删除纪律**:旧代码必须删除,不堆叠
- **§Y commit 即 push**:不允许累积本地 commit
- **§Z 端到端 DB 行数 / 字段值断言**:不允许只 mock `.called=True`

---

# 第十一部分:v1.4 删除清单(明确去掉的旧逻辑)

按 §X 删除纪律,以下旧逻辑必须删除:

## 11.1 v1.2 残留(应该 v1.3 已删,v1.4 sprint 调研确认)

- 5 个组合因子(TruthTrend / BandPosition / Crowding / MacroHeadwind / EventRisk)对应代码:
  - `src/composite/truth_trend.py`(若仍存在)
  - `src/composite/band_position.py`
  - `src/composite/crowding.py`
  - `src/composite/macro_headwind.py`
  - `src/composite/event_risk.py`
- 这 5 个 composite 的人读模板代码
- 这 5 个 composite 的网页卡片 emitter
- 5 个组合因子相关的 thresholds.yaml 段

> **v1.4 sprint 1.10-J 必须 SSH 调研确认**:这些代码是否还在被实际调用,如果没被调用但代码还在,按 §X 删除。

## 11.2 v1.4 明确删除

- `cold_start` 字段及所有相关逻辑
- `observation_category` / `observation_classifier` 整套机制(disciplined / watchful / possibly_suppressed / cold_start_warming_up)
- `account_state` 真实账户假设(account_has_long / entry_zone_filled_confirmed_1h 等)
- 14 档状态机的 POST_PROTECTION_REASSESS / FLIP_WATCH 老逻辑
- `base.yaml::runtime.scheduled.cron_hours_utc`(跟 scheduler.yaml 冲突)
- **`scheduler.yaml::pipeline_run: interval: '4h'` 旧配置**(改为 cron `hour: 8`,即 BJT 16:00 一次,**v1.4 主策略不再每 4 小时跑**,避免无意义 AI token 消耗)
- **代码层任何依赖"主策略每 4h 触发"假设的逻辑**:
  - `src/scheduler/jobs.py::job_pipeline_run` 注释 / 文档字符串中提及"每 4 小时"
  - `src/pipeline/strategy_state_builder.py` 中 `run_trigger="scheduled"` 路径里假设 4h 间隔的任何死代码
  - `config/scheduler.yaml` 注释中提及"每 4 小时执行一次"的描述
  - 任何 unit test fixture / mock 假设 4h 触发节奏

> **v1.4 sprint 1.10-J 必须做**:不是简单改配置,而是**全项目 grep "4h" / "每 4 小时" / "interval: 4h"**,凡是涉及主策略触发节奏的引用都改/删。`position_health_check: interval: '4h'`(持仓期健康检查)是**保留的合法 4h 任务**,不要误删。

## 11.3 v1.4 重写

- `src/ai/agents/master_adjudicator.py`(master AI 改 thesis-aware)
  <!-- 1.10-J commit 8 修:原 §11.3 写 src/ai/adjudicator.py 是路径错误,真路径在 agents/ 子目录 -->
- master AI System Prompt
- `src/ai/validator.py`(从 10 条扩展到 24 条)
  <!-- 1.10-J commit 8 修:原 §11.3 写 src/decision/validator.py 是路径错误,真路径在 src/ai/ -->
- `src/strategy/state_machine.py`(14 档简化为 thesis lifecycle)
- 网页 12 卡精简(已重复字段移除)

## 11.4 v1.4 新增(原本没有)

- 3 张 DB 表(virtual_account / virtual_orders / theses)+ DAO
- 4 个 strategy 模块(virtual_account / orders_engine / thesis_manager / fuse_monitor)
- 1 个 AI agent(weekly_review_analyst)
- 配置项(virtual_account / thesis / cooldown / fuse / review_pending / ai_retry / event_trigger)

## 11.5 v1.4 实施期发现的修订项(Sprint 1.10-L 归档)

本节记录 v1.4 实施期(Sprint 1.10-A → 1.10-L)中发现并已修复 / 标记的设计层修订项。

### 修订项 1 — V24 写入通路 1.10-E 实施漏洞 + 1.10-L commit 11a 修复

**背景**:1.10-E 引入 Validator 24 条 + 28 字段 meta(§3.4.9),设计意图是
独立 SQL 列 `strategy_runs.constraint_activations_json` 方便周复盘 AI 聚合
(`weekly_review_input_builder._aggregate_constraint_activations`)。

**实施漏洞**(1.10-E 起 4+ sprint 静默失效):
- migration 011 加列 ✅
- `dao.py:StrategyStateDAO.insert_state` 写入逻辑完整 ✅(但生产不走该路径)
- 生产走 `state_builder._run_v13_orchestrator` 路径 → 经
  `_orchestrator_mapper._map_orchestrator_result_to_state` 映射 →
  **mapped 输出 17 列遗漏 `constraint_activations_json`** ❌
- INSERT 17 列不写 → DB 138 行全 NULL(SSH 真核确认)
- `orchestrator.result["constraint_activations"]` 算好后被 mapper 静默丢弃
- 0 错误日志(systemd 1h 检查)

**Sprint 1.10-L commit 11a 修复**:
- `_orchestrator_mapper.py`:mapped 加 `constraint_activations_json` 字段
  (`json.dumps(ca, ensure_ascii=False, default=str)`)
- `state_builder._run_v13_orchestrator`:INSERT SQL 17 → 18 列 + params
- `tests/pipeline/test_orchestrator_mapper.py`:test_returns_all_17 → 18 + 5 新单测
- `dao.py` 老路径不破(K-A commit 2 review 过)
- `weekly_review_input_builder._aggregate_constraint_activations` 已有
  `WHERE constraint_activations_json IS NOT NULL` 跳过 NULL 老历史保护

**真接通验证**(用户 SSH 跑 `scripts/run_pipeline_once.py --trigger manual`):
- run_id `753cd250...`,V meta 1181 字符 JSON 完整 28 字段
- 累计:null=138, has_data=1, total=139(老 138 不可回填)
- 1.10-E 设计意图首次真接通,v1.4 完整版而非半残版

### 修订项 2 — lifecycle ↔ thesis 表 FK 关联缺失(future v1.5b 标记)

**背景**:`lifecycles` 表无 `thesis_id` 字段(`schema.sql` 早期设计),
跟 `theses` 表无 FK 关联。

**绕过方案**(K-A commit 5 + 1.10-L commit 5):
- `lifecycle_manager._archive_lifecycle` 不能直接拿 thesis_id
- 用 `ThesesDAO.get_active(self.conn)` 找当前唯一 active thesis
- 利用 v1.4 §5.3.1 主线锁 + Validator 6 单 active 强制保证

**限制**:
- 若未来支持多 active thesis(多策略并行),`get_active` 路径失效(返不确定)
- 性能上每次 archive 多 1 次 SQL 查询(主线锁下可接受)
- lifecycle 跟 thesis 是两套独立轨道,缺乏 SQL 层一致性约束

**v1.5b 启动时考虑**:
- `lifecycles` 表加 `thesis_id` 字段(schema migration)
- `_create_pending_lifecycle` 创建时记录关联 thesis_id
- `_archive_lifecycle` 直接读 `lifecycle.thesis_id` 而不走 `get_active`
- FK 约束保证一致性

### 修订项 3 — PROTECTION 全局入口 §4.2.8 部分实施(future 完整接通)

**1.10-L commit 1-3 实施**(P0 #1 P1A 双向):
- ✅ 进 PROTECTION 时 active thesis 进 review_pending(`protection_handler.on_protection_entered`)
- ✅ 退 PROTECTION 时 system_state='review_pending'(commit 7 镜像 + commit 8 网页)

**未完整实施**(留 future):
- ❌ §4.2.8 "挂单暂停" — orders_engine 未读 system_state 阻断挂单
- ❌ §4.2.8 "AI 调用暂停 30 分钟" — scheduler 未读 PROTECTION 状态阻断 cron
- ❌ `check_protection_exit_conditions` 未被 caller 自动消费(留用户手动确认 + 后续 sprint 自动检测)
- ❌ thesis_manager 反手出口未真接通 — close → cooldown 状态接通(commit 7 测过),
  但 master AI 在 cooldown 结束后真创建反手 thesis 的 e2e 留 future(架构已就绪:
  `master_input_builder.is_in_cooldown` 已消费,Validator 6 主线锁约束)

---

# 第十二部分:v1.4 修订清单(28 条对照表)

按主题分组,索引到上述章节。

## 第一组:核心机制新增(8 条)

- M1:virtual_account 虚拟账户(§5.1)
- M2:挂单引擎精确价格(§5.2)
- M3:thesis 主线锁(§5.3)
- M4:反手分级 + 冷却期(§4.3)
- M5:14 天反复横跳熔断(§4.3.4 + Validator 18)
- M6:fallback thesis-aware 改造(§6.4)
- M7:AI 重试机制(§6.3)
- M8:事件触发(继承 v1.3 §5.2 双轨设计):**空仓 ±5% / 持仓 ±3% event_price** + v1.4 新增 **event_invalidation 硬失效位击穿(规则平仓)**(§6.2.3)

## 第二组:边界保护 S1-S5 + 6 细化(11 条)

- S1:60 天 thesis 上限(Validator 19)
- S2:break_conditions 距离合理性(Validator 9)
- S3:过度保守监控(§8.2)
- S4:连续熔断保护(Validator 20)
- S5:review_pending 强提醒(§9.3)
- 细化 1:weakened stop 收紧上限(Validator 17)
- 细化 2:通道 C 分级满足(§4.3.3)
- 细化 3:review_pending 三种出口(§5.3.7)
- 细化 4:break_conditions 距离每日监控(模块 2 网页显示)
- 细化 5:master 软抗拒识别(Validator 21)
- 细化 6:事件触发节流(`event_cooldown_seconds: 7200` / `skip_if_recent_scheduled_seconds: 1800`)

## 第三组:可靠性机制(2 条)

- M9:master AI 连续 3 天失败兜底(Validator 22)
- M10:周复盘 weekly_review_analyst(§3.3.9 + §8.1)

## 第四组:运营节奏(1 条)

- M11:每天 BJT 16:00 一次主决策(§6.2.1 + §10.4.1)

## 第五组:Hard Constraints 增强(3 条)

- M12:L1-L5 输出加 reasoning + objective_evidence(§3.3 各层)
- M13:master AI thesis-aware 改造(§3.3.6)
- M14:Validator 24 条强化(§3.4)— 含 meta 约束第 24 条(§3.4.9)

## 第六组:网页改造(1 条)

- M15:5 个新模块,风格不变(§9.2)

## 第七组:旧逻辑清理(2 条)

- M16:删除 observation_category 整套(§11.2)
- M17:删除 cold_start + 14 档老逻辑简化(§11.2 + §4.1)

---

# 附录 A:术语表(v1.4 新增 / 修改)

| 术语 | 含义 |
|---|---|
| thesis | 一个完整的交易论点,从创建到关闭,包含 break_conditions |
| active_thesis | 当前正在生效的 thesis(同时只能 1 个) |
| break_conditions | thesis 失效的客观条件(3 条,可程序化判断) |
| weakened | thesis 评估状态,论点削弱但未失效,允许调 stop |
| invalidated | thesis 评估状态,论点失效,thesis 关闭 |
| review_pending | 系统级特殊状态,需要用户介入 |
| 慢通道 / 中通道 / 快通道 | 反手 3 档通道(冷却 3 天 / 24h / 0) |
| 14 天熔断 | 反复横跳保护机制 |
| 60 天上限 | thesis 最长持续时间 |
| meta 约束 | Validator 第 24 条,硬约束激活频率监控 |
| virtual_account | 虚拟账户(initial_capital 100,000 USDT) |
| weekly_review_analyst | 周复盘 AI agent |
| event_price | ±3% 价格异动事件触发 |
| event_invalidation | 硬失效位击穿事件触发 |
| objective_evidence | AI 输出必须引用的客观数据字段值 |
| confidence_score | thesis 创建时的置信度 0-100,跟 L3 grade 对齐 |

继承 v1.2 / v1.3 其他术语不变。

---

# 附录 B:核心设计原则(v1.4 总览)

## v1.4 三层各司其职(灵魂)

- **AI 决定"是什么"**:regime / stance / grade / direction / 综合判断
- **规则决定"输出格式 + 客观依据 + 自洽性"**:Validator + schema + objective_evidence + 数学算的指标
- **thesis 决定"何时允许改主意"**:break_conditions + 冷却期 + 主线锁

## "刚刚好"标准

硬约束设计的"刚刚好":
- 单条:保护资金安全 + 防 AI 乱来,缺一不可
- 总体数量:不重叠 / 不矛盾 / 互补
- 激活频率:由 Validator 24(meta)监控,周复盘 AI 评估,人工调整

## 不变的核心原则(继承 v1.3)

- 数据真实性
- §X 删除纪律
- §Y commit 即 push
- §Z 端到端 DB 真实断言
- 质量第一,不为成本妥协

---

# 附录 C:系统不做的事(v1.4 明确范围边界)

## 继承 v1.2 / v1.3

- 不做自动执行(不下单到真实交易所)
- 不做多币种(只 BTC)
- 不做现货/合约区分(用户自选)
- 不做杠杆计算(用户自决)
- 不做跨交易所套利
- 不做多账户或多用户支持
- 不做全库加密
- 不做自动化部署 CI/CD
- 不做高可用集群
- 不做机器学习级别的异常检测
- 不做自适应放宽标准
- **不做复盘结果自动反哺决策层参数**(必须人工介入)

## v1.4 明确

- 不做实盘和回测同表(完全分开,v1.5 单独做 backtest_*)
- 不做 thesis 自动续期(必须用户介入 review_pending 出口 B)
- 不做 14 天熔断自动 reset(必须用户介入 review_pending 出口 C)
- 不做 master AI 综合判断改 grade(L3 是唯一权威)

---

**v1.4 文档结束。**

进入编码实施阶段时,代码必须严格对齐本文档。任何实现偏差必须先在文档层修订,再改代码。

规则表修订必须 bump rules_version。架构层修订必须先文档、后代码、再测试。

实施 sprint 路径见 §10.5。
