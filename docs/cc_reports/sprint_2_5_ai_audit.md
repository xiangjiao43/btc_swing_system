# Sprint 2.5 — 全代码库 AI 接入点审计

**Date:** 2026-04-25
**Branch:** main · HEAD = `b67a75a`
**Type:** audit only(零代码改动)
**触发:** 用户记忆建模有 2 处 AI 接管点,需对照 d8999c4 偷偷引入双段 AI 的教训

---

## 1. 扫描方法

### 扫描范围
- `src/` 全部 (.py)
- `scripts/` 全部 (.py)
- `migrations/` 全部 (.sql / .py)
- 跳过 `tests/`, `docs/`, `web/`, `config/`, `data/`

### 扫描模式(7 种 grep)
| # | 模式 | 命中文件 | 命中数 |
|---|---|---|---|
| 1 | `^(from |import )(anthropic|openai)` | (无;均通过 `src.ai.client` 间接 import) | 0 |
| 2 | `Anthropic\(|OpenAI\(` | `src/ai/client.py:66` | 1(builder,非调用点) |
| 3 | `\.messages\.create|\.completions\.create` | adjudicator / summary / review | **3** |
| 4 | `ANTHROPIC_API_KEY|ANTHROPIC_BASE_URL` | (无;走 `OPENAI_API_KEY` env var 的 anthropic 中转) | 0 |
| 5 | `novaiapi.com` | `src/ai/__init__.py:1`、`src/ai/summary.py:5`(注释提及) | 2(注释) |
| 6 | `_SYSTEM_PROMPT|system_prompt|user_prompt` | adjudicator / summary / review | 长 prompt 字符串均归属上方 3 个调用点 |
| 7 | `from (\.|src)\.ai|from \.\.ai` | state_builder / review | 2(import 链,非新增调用点) |

---

## 2. 完整 AI 调用点清单

| # | 文件:行 | 函数 / 类 | 引入 commit | 引入日期 | Sprint | 流程位置 | 输出去向 | 当前是否触发 | 建模授权 | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `src/ai/adjudicator.py:359` | `AIAdjudicator._call_ai_decide` (`client.messages.create`) | `184d394` | 2026-04-24 | 1.14a | **阶段 4 AI 裁决**(L1-L5 + composite + observation 全跑完后) | `state.adjudicator.{action, direction, narrative, trade_plan, primary_drivers, ...}` → 写 DB `strategy_runs.full_state_json`;前端 Region 1 "策略说明"渲染 `state.ai_verdict.narrative` | ⚠ 当前生产因 cold_start + L3.grade=none 走规则路径,AI 实际未被调用(`_should_call_ai` returns False) | §2.3 表格:`最终裁决 \| AI 主导,程序约束`<br>§2.5:`AI 只参与"综合裁决" (stance/regime/phase/opportunity/permission/trade_plan)`<br>§6.1-§6.8:专章定义 AI 裁决契约 + System Prompt 终稿 | ✅ 设计内 |
| 2 | `src/ai/summary.py:220` | `call_ai_summary` (`client.messages.create`) | `d672154` | 2026-04-23 | 1.11b | **阶段 3.5**(L1-L5 evidence 全部产出后,在 adjudicator 之前) | `state.context_summary.summary_text` → 写 DB;**未被前端渲染**(grep `summary_text|context_summary` in `web/` 0 命中) | ⚠ 当前生产 `pipeline.degraded_stages=["ai_summary"]` 表明该 stage 在跑,但本地 grep 显示 cold_start 状态下也试图调,失败后存 `summary_text=null` | §2.3 表格:`复盘分析 \| 程序为主,AI 辅助 \| 规则归因 + 文字总结`(但这是周复盘,不是每次 pipeline)<br>§6.8 "第 5 层宏观摘要 AI Prompt 终稿":定义了一个用于 L5 层内部的 AI prompt | **⚠️ 模糊** — 见下方"模糊项详述" |
| 3 | `src/review/generator.py:254` | `_default_ai_narrative` (`client.messages.create`) | `aa48773` | 2026-04-24 | 1.16b | **复盘流程**(独立于主 pipeline,由 `scripts/run_kpi_once.py` 触发,周复盘报告生成时) | weekly review markdown 文件 → Sprint 2.4 后通过 `/api/review/{lifecycle_id}` 接出 | ⚠ 当前未配定时,只在手动 run_kpi_once.py 时触发 | §2.3 表格:`复盘分析 \| 程序为主,AI 辅助 \| 规则归因 + 文字总结` — **直接对应** | ✅ 设计内 |

### 关联模块

| 文件 | 角色 | 备注 |
|---|---|---|
| `src/ai/client.py` | `build_anthropic_client()` builder | 唯一 `Anthropic()` 实例化点。3 个调用点全部经由此 builder 拿 client。**不是独立 AI 调用点**,是依赖。 |
| `src/ai/__init__.py` | 包 docstring 提及 novaiapi 中转 | 文档字符串,非代码调用 |
| `config/prompts/adjudicator_system.txt` | 历史 prompt 文件 | **当前未被代码加载**(`adjudicator.py` 改用 inline `_SYSTEM_PROMPT`,该文件成为冗余)。审计建议下次清理 |
| `src/data/collectors/coinglass.py` / `glassnode.py` | 提到 alphanode 中转 | 那是 K 线 / 链上数据 API 中转,**不是 AI 调用** |

---

## 3. 建模 AI 授权白名单(从 modeling.md 抽取)

按章节顺序,modeling.md 明文授权 AI 介入的位置:

| 建模位置 | 内容 | 授权类型 | 对应当前实现 |
|---|---|---|---|
| §2.3 表格 行 8 | `L5 背景事件 \| AI \| 涉及语义理解` | **L5 evidence layer 应由 AI 实现** | ⚠ **反向偏离**:`src/evidence/layer5_macro.py` 完全规则化(基于 DXY / US10Y / VIX / 纳指数值规则),无 AI 介入 |
| §2.3 表格 行 11 | `最终裁决 \| AI 主导,程序约束 \| 多维权衡 + 叙事` | **adjudicator 必须由 AI 主导** | ✅ `src/ai/adjudicator.py` 调用点 #1 |
| §2.3 表格 行 13 | `复盘分析 \| 程序为主,AI 辅助 \| 规则归因 + 文字总结` | **复盘可由 AI 辅助生成文字** | ✅ `src/review/generator.py` 调用点 #3 |
| §2.5 双轨原则 #5 | `AI 只参与"综合裁决"(stance / regime / phase / opportunity / permission / trade_plan),不参与因子解释、不参与规则转述` | **唯一允许的 AI 出口** | 与 §2.3 行 11 一致;明确禁止 d8999c4 那种"AI 写组合因子叙事" |
| §6.1-§6.8 整章 | "AI 裁决契约与 Prompt 终稿" 完整定义 | **adjudicator 的输入契约 / 输出契约 / system prompt / user prompt** | ✅ 对应调用点 #1 |
| §6.8 "第 5 层宏观摘要 AI Prompt 终稿" | 定义"宏观分析助手"角色,产出 Layer5Output schema | **L5 内部使用 AI 做事件摘要** | ⚠ **未实现**:`src/evidence/layer5_macro.py` 不调 AI,`src/ai/summary.py` 调 AI 但是另一种用途(读 L1-L5 全部产 3 段中文摘要,不是产 Layer5Output schema) |

---

## 4. 模糊项详述:`src/ai/summary.py`(调用点 #2)

### 现状
- 文件 docstring(行 1-11):`证据链 AI 摘要(Sprint 1.11c) 将 L1-L5 的 EvidenceReport 聚合成 prompt … 写入 StrategyState.context_summary`
- system prompt(行 42-50):`你是一位专业的加密资产策略分析师,为一套 BTC 中长线低频波段交易辅助系统撰写证据链摘要。… 严格 3 段,每段 ≤ 120 字`
- 流程位置:在 adjudicator 之前调用,把 5 层 evidence 全部喂给 AI 让它产出"3 段中文摘要"
- 落地:`state.context_summary.summary_text`(写 DB)
- 渲染:**未在前端渲染**(grep 确认 `web/` 目录 0 命中 `summary_text` / `context_summary`)

### 与建模的不匹配

| 维度 | 建模 §6.8 期望 | 实际 `src/ai/summary.py` |
|---|---|---|
| 角色 | "宏观分析助手"(只看宏观数据 / 新闻) | "策略分析师"(看 L1-L5 全部 evidence) |
| 输入 | 当天结构化宏观数据 + 新闻 | 5 层 EvidenceReport 全部 |
| 输出 schema | Layer5Output(事件类别 / 严重程度 / 影响方向) | 3 段中文段落,非结构化 |
| 调用方 | L5 evidence layer 内部 | pipeline 阶段 3.5(独立 stage) |

也与 §2.3 表格"L5 背景事件 \| AI"不完全对应 — §2.3 想让 AI 做 L5 内部判定,实际 L5 是规则,AI 调用变成了"L1-L5 跑完后再加一层 AI 摘要"。

### 与 §2.5 双轨原则的关系
- §2.5 #5:`AI 只参与"综合裁决"`
- summary.py 输出的 `context_summary.summary_text` 不被前端渲染,所以 **没有违反"人读版严禁 AI 生成"**
- 但 summary.py 输出可能被 adjudicator 用作输入(影响"综合裁决")— 需复查 adjudicator 是否读 `state.context_summary.summary_text` 进它的 facts

### 复查结果
`grep "context_summary" src/ai/adjudicator.py` → 命中 1 行(行 614):`facts["context_summary_status"] = (strategy_state.get("context_summary") or {}).get("status")`。
**只读 status,不读 summary_text**。说明 summary.py 的产出在当前主 pipeline **既不进 adjudicator 也不进前端,实际是悬空数据,只写 DB 备查**。

### 整改选项(供用户决定)

- **A 选项**:删除 `src/ai/summary.py` + 它在 pipeline 的 stage(`state_builder.py:452-477`)。理由:该 AI 调用既不被 adjudicator 消费也不被前端渲染,是历史遗留浪费。每次 pipeline 都白调一次 AI。
- **B 选项**:把 summary.py 重构成 modeling §6.8 真正想要的"L5 宏观摘要",移到 `src/evidence/layer5_macro.py` 内部。这才是 §2.3 行 8 "L5 背景事件 \| AI" 的真实意图。
- **C 选项**:保持现状,在 modeling.md 加注释说明"summary.py 是 v1.1 的实现选择,与 §6.8 不严格对应,作为历史归档,无实际下游消费"。

---

## 5. 反向偏离:modeling 写要 AI,代码却没 AI

| 建模位置 | 期望 | 现状 | 整改建议 |
|---|---|---|---|
| §2.3 表格行 8 + §6.8 整段 | L5 由 AI 主导(读宏观数据 + 新闻产出 Layer5Output) | `src/evidence/layer5_macro.py` 纯规则,无 AI | 这是**架构级缺口**,不是代码失控。需用户决定:(1) 接 §6.8 的 L5 AI;或 (2) 修订 §2.3 + §6.8 把 L5 改为规则化 |

---

## 6. 审计结论

### 数字总结
- ✅ 设计内 AI 调用点:**2**(adjudicator + review.generator)
- ⚠️ 模糊 AI 调用点:**1**(summary.py — 与 §6.8 不严格匹配,不被消费)
- ❌ **计划外** AI 调用点:**0**(d8999c4 引入的双段 AI 分析已在 b67a75a 切除)
- 反向偏离(应该有 AI 但没有):**1**(L5 evidence layer)

### 用户记忆的"2 处 AI 接管点"对应关系
- 第 1 处(用户记得):**最终策略裁决** = 调用点 #1 ✅
- 第 2 处(用户忘记):极可能是 §2.3 行 8 的 **L5 背景事件 / 宏观摘要**,但当前实现分裂为:
  - `summary.py` 实际跑了一个"L1-L5 总摘要" AI(模糊项)
  - `layer5_macro.py` L5 本身却没 AI(反向偏离)
  - `review.generator` 是**第 3 处**的 AI(复盘文字),建模 §2.3 行 13 也明文授权

### 是否触发"停下问用户"
- **0 计划外** → 按用户原指令"任务 X 如发现'计划外'AI 调用点,停下问用户后再做任务 2/Y" 不触发停下
- 1 模糊 + 1 反向偏离 → 在最终 4 段汇报中明示,继续做任务 2/Y

---

## 7. 给用户的决定项(可异步处理,不阻塞 2/Y)

1. `src/ai/summary.py` 整改:A / B / C 三选项请你定
2. L5 evidence layer 是否要按 §2.3 + §6.8 改为 AI 驱动 — 这是 sprint 级架构决定
3. 是否清理 `config/prompts/adjudicator_system.txt`(冗余文件,代码未加载)
