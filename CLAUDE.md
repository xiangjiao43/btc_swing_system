# BTC Swing System - CLAUDE.md

## 项目唯一权威蓝本

docs/modeling.md 是项目的唯一建模蓝本,任何代码改动都必须严格对齐它。

每次开始工作前,先读 docs/modeling.md 相关章节:
- §2(架构)/ §3(数据)/ §4(证据层)/ §5(状态机)
- §6(AI 裁决)/ §7(StrategyState)/ §8(复盘)
- §9(网页 API)/ §10(工程落地)

## 用户身份与目标

- 用户是代码小白,非工程师,在借用的 Mac 上开发
- 目标:BTC 中长线低频双向波段交易辅助系统
- 不做自动交易,系统只输出策略建议,用户自己决定是否下单
- 最终运行在云服务器,用户通过手机/电脑浏览器访问

## 双轨输出原则(每次开发必读 — 建模 §2.5)

**核心**:同一份"系统初步分析"数据必须产出两个版本:
- **机读版** → AI 裁决器(JSON / 结构化字段;在 `src/ai/adjudicator.py` prompt 上下文里)
- **人读版** → 用户网页(中文叙述,规则化拼接;`inject_plain_readings()` / `inject_pillars()` / `inject_composite_composition()` 等"人类视图层")

**5 条硬约束**:
1. 两份信息源同一(同一批数据)
2. 人读版必须由规则化代码生成(查阈值表 + 拼接模板 + 引用建模规则原文)
3. 人读版严禁由 AI 生成 — 避免 AI 改写造成失真
4. 人读版严禁直接展示机读版 JSON 原文 — 那不是给人看的
5. AI 只参与"综合裁决"(stance / regime / phase / opportunity / permission / trade_plan),不参与因子解释、不参与规则转述

**合规 AI 出口清单**:
- **#1 综合裁决** — `src/ai/adjudicator.py`,产 trade_plan + narrative,已实施
- **#2 L5 宏观综合判断** — 规划中,实施待 Sprint 2.6(前置:macro collector 修复)。详见建模 §6.8 末段

**设计意图**:用户打开网页是来"审计系统",不是来"看 AI 报告"。

## 系统硬纪律(不可违反)

1. 数据源(§3.6):
   - K 线:币安(但用户美国 IP 访问 api.binance.com 被封 451,目前通过 CoinGlass 中转站 api.alphanode.work 获取 K 线,需要未来对齐建模要求)
   - 衍生品:币安 + CoinGlass 并用(建模要求),目前只有 CoinGlass
   - 链上:Glassnode 通过 alphanode 中转(x-key header)
   - 宏观:Yahoo Finance 直连(经常被限速 429)+ FRED 备用

2. 执行顺序硬规则(§3.2.1):
   阶段 1 数据采集 → 阶段 2 证据层 L1→L2→L3→L4→L5 → 阶段 3 Observation 分类 → 阶段 4 AI 裁决 → 阶段 5 校验输出
   不允许交错,不允许跨阶段并发,不允许读上次运行的结论。

3. L3 是纯规则判档层(§4.4.2):
   禁止 "score += X" 式的加权计算,只能用查找表 + 硬条件函数。

4. opportunity_grade 单一来源(§4.4.6):
   L3 是唯一产出点。AI 输出必须原样引用,程序校验拒绝不一致。

5. hard_invalidation_levels 唯一权威(§4.5.4):
   AI trade_plan.stop_loss 必须从 L4 给出的价位中选,不能另设或修改。

6. 1H 数据白名单(§4.4.8):
   L1/L2/组合因子禁止读 1H 数据。只有执行确认、硬失效预警、事件触发能读。

7. 14 档状态机(§5.1,严格对齐,不能自行改名):
   FLAT / LONG_PLANNED / LONG_OPEN / LONG_HOLD / LONG_TRIM / LONG_EXIT
   SHORT_PLANNED / SHORT_OPEN / SHORT_HOLD / SHORT_TRIM / SHORT_EXIT
   FLIP_WATCH / PROTECTION / POST_PROTECTION_REASSESS

8. position_cap 串行合成(§4.5.5):
   基础 70% → × L4 risk → × Crowding → × Macro → × EventRisk,硬下限 15%

9. execution_permission 归并(§4.5.6):
   每个因子产出建议档位,取最严档位。A 级缓冲:grade=A + regime 稳定时 permission 不得严于 cautious_open。

10. AI 裁决 System Prompt(§6.5 终稿):
    严格使用建模给定的 System Prompt,包含 10 条纪律 + 核心决策原则 + 身份定位。

## 与用户协作规则

1. 汇报格式:严格按下方「CC 输出协议」执行(每次任务完成后必读)
2. Triggers 标注:任何偏离建模的自主决策都要在 docs/cc_reports/sprint_X_Y.md 顶部 Triggers 段标出
3. 每个子任务立即 commit,不等整个 Sprint 做完才 commit(避免中途中断丢失)
4. .env 文件是用户的,CC 绝对不能覆盖或删除(之前 Sprint 1.2 有过事故,已承诺)
5. 遇到架构级歧义立即停下问用户,不自由发挥

## CC 输出协议(每次任务完成后必读)

每完成一个任务后必须做以下两件事:

### 任务 1:写完整交付报告到文件
- 文件路径:`docs/cc_reports/sprint_<编号>.md`(编号见任务名,如 `sprint_2_5a.md`;若同 Sprint 多批次用 `sprint_2_5a_batch_2.md`)
- 内容:完整改动文件列表、关键 diff、设计决策、验收记录、部署日志、未覆盖项、风险提示
- 这份报告会被 commit 到 git,作为项目工件永久归档

### 任务 2:在对话里只输出"简短 3 段 + 1 行报告路径"
严格按以下 4 段格式,**不要超出范围**:

**段 1 — 一句话结果**
例:"Sprint 2.5-A 完成,改了 web/index.html 8+/5-,部署到生产 PID 437107"

**段 2 — 需要用户决策的地方**
- 如有,列 1-2-3 条,每条一行,不超过 50 字
- 没有就写:"无决策点"

**段 3 — 可能未覆盖的建模要求 / 风险提示**
- 如有,列 1-2-3 条,每条一行
- 没有就写:"全部覆盖"

**段 4(固定一行)— 报告路径**
"详细报告:`docs/cc_reports/sprint_<编号>.md`"

### 禁止行为

- ❌ 不要在对话里贴完整 diff(贴到报告文件里)
- ❌ 不要在对话里贴 grep / curl / systemctl 等验证命令的输出(贴到报告文件里)
- ❌ 不要在对话里展示 TODO 列表的进度
- ❌ 不要主动跑 Playwright / 截图 / 视觉自验证(用户会自己看)
- ❌ 不要把临时验证产物(截图、日志、测试输出)提交到 git
- ❌ 不要写长段说明文字解释"我做了什么意义重大"

### 允许行为

- ✅ 报告文件里可以详细写
- ✅ 对话里可以简短引用关键 commit hash、文件名、行号
- ✅ 遇到关键决策点(建模/代码冲突)必须停下问用户 — 这种情况优先于本协议

## 技术栈(建模 §10.1)

- 语言:Python 3.11+
- 后端:FastAPI
- 数据库:SQLite
- 调度:APScheduler
- 前端:HTML + Alpine.js + Tailwind(不用 React)
- AI SDK:anthropic Python SDK(不用 openai SDK,当前 Sprint 1 用错了,Sprint 1.5 修)
- 时区:Python zoneinfo

## Sprint 1 现状(截至 2026-04-24)

Sprint 1.1-1.16 做完,但多处偏离建模。Sprint 1.5 正在做一致性修复(看 docs/cc_reports/sprint_1_5_*.md 了解状态)。
