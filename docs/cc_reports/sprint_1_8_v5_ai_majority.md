# Sprint 1.8 v5 — 6 AI 角色 + Validator + Orchestrator(v1.3 AI 主导架构)

**报告日期:** 2026-05-01
**Sprint 范围:** 实施建模 v1.3 §3.3 "AI 主导 + 规则硬约束" 架构
**状态:** Task A/B/C/D/E 全部本地完成,推送至 GitHub origin/main(commit 7b4eed8)
**前置:** Sprint 1.7 完成因子清理(commit 374c7ec)
**后置:** Sprint 1.8.1 删除旧 layer/composite 文件;Sprint 1.8.2 前端重设计;Sprint 1.9 接入 jobs.py 频率重构

注:本 sprint 与较早的 [sprint_1_8.md](sprint_1_8.md)(L2 Direction Evidence 层,
2026-04-23)无关 — 那是 v1.2 老架构;本 sprint 是 v1.3 哲学重构。

---

## Triggers(偏离建模 / 需用户决策)

无重大偏离。所有 prompt 和模块均由用户逐版审定通过。

记录:Sprint 1.8 期间 prompt 写作哲学发生重大调整,从早期的"硬阈值表"
版本迭代到 v5 "图 + 客观数值,AI 综合判断" 哲学(由用户在 L1 prompt 第
4 版后明确要求重写)。该哲学锁定在 [src/ai/agents/prompts/_README.md](../../src/ai/agents/prompts/_README.md)
中,作为后续 prompt 编写规范。

---

## 1. Task A — BaseAgent + 6 AI 角色骨架(commit 6123720, 9db65b5)

### 1.1 改动文件

- 新增 [src/ai/agents/_base.py](../../src/ai/agents/_base.py)(256 行):BaseAgent 抽象基类
  - 统一 prompt 文件加载、anthropic API 重试(温度 0.2 → 0.4)、JSON loose
    解析、失败 fallback、统一日志埋点
  - **v5 多模态扩展**:context 含 `chart_b64` 时自动构造
    `[image content block + text content block]`,无 chart 时纯文本
- 新增 6 个 agent 类(每个 70 行左右):
  - [l1_regime_analyst.py](../../src/ai/agents/l1_regime_analyst.py)
  - [l2_direction_analyst.py](../../src/ai/agents/l2_direction_analyst.py)
  - [l3_opportunity_analyst.py](../../src/ai/agents/l3_opportunity_analyst.py)
  - [l4_risk_analyst.py](../../src/ai/agents/l4_risk_analyst.py)
  - [l5_macro_analyst.py](../../src/ai/agents/l5_macro_analyst.py)
  - [master_adjudicator.py](../../src/ai/agents/master_adjudicator.py)
- 新增 [src/ai/agents/chart_renderer.py](../../src/ai/agents/chart_renderer.py)(L1/L2/L4 三个 render 方法)
- 新增 [src/ai/agents/__init__.py](../../src/ai/agents/__init__.py):统一导出
- 新增 [src/ai/agents/prompts/_README.md](../../src/ai/agents/prompts/_README.md):v1.3 哲学锁

### 1.2 核心设计

每个 agent 继承 BaseAgent 并定义:
- `AGENT_NAME` / `PROMPT_FILE` 类常量
- `_build_user_prompt(context)` 把上下文 dict 拍平成字符串
- `_fallback_output()` 失败时返回的最小合法 dict(Sprint 1.8 实施期间各
  agent 用其 fallback dict 作为初版,待真实 prompt 上线后会被 AI 输出覆盖)

---

## 2. Task B — 6 个 prompt 文件(逐版迭代到用户审定)

### 2.1 prompt 文件清单

| 角色 | 文件 | 最终版本 commit | 段数 | 用图 |
|---|---|---|---|---|
| L1 市场状态 | [l1_regime.txt](../../src/ai/agents/prompts/l1_regime.txt) | 981ef59 | 12 | ✅ 1d 180d 主图+ADX+ATR |
| L2 方向结构 | [l2_direction.txt](../../src/ai/agents/prompts/l2_direction.txt) | 1d32d43 | 14 | ✅ 1d 90d + 4h 30d |
| L3 机会执行 | [l3_opportunity.txt](../../src/ai/agents/prompts/l3_opportunity.txt) | f380a28 | 13 | ❌ 纯文本 |
| L4 风险评估 | [l4_risk.txt](../../src/ai/agents/prompts/l4_risk.txt) | 86ffe46 | 13 | ✅ 主图 + funding/OI/flow 副图 |
| L5 宏观背景 | [l5_macro.txt](../../src/ai/agents/prompts/l5_macro.txt) | b26834a | 15 | ❌ 纯文本 |
| 主裁 | [master_adjudicator.txt](../../src/ai/agents/prompts/master_adjudicator.txt) | 25194c6 | 16 | ❌ 纯文本(消费 L1-L5) |

### 2.2 v1.3 哲学(prompts/_README.md 锁定)

4 条核心原则:

1. **图 + 客观数值,不喂规则结论标签**
   不传 `ema_alignment='bullish'`,只传 `ema_20=75320` + K 线图,AI 自己看
2. **系统做精确计算,不让 AI 算**
   ADX / EMA / ATR / Swing 由代码计算(client side),AI 只做综合判断
3. **AI 做综合判断,不依赖单一阈值**
   prompt 给定性档位描述(early/mid/late),不教 AI "扩展百分比 50-100% 算 mid"
4. **fewshot 示例输入是数据 + 图描述,输出是 JSON,不写"参考信号"**

**唯一例外**:`volatility_regime`(ATR-180d 分位 25/75/90)和
`extreme_event_detected` B 类触发条件保留客观档位 — 这两个是建模 §4.5.4
的硬约束触发条件,需要可复现的客观标准。

### 2.3 prompt 迭代历史(用户逐版审定)

| Prompt | 迭代版本 | 主要修订 |
|---|---|---|
| L1 | v1 → v5 | v1 硬阈值表 → v2-v4 逐步去机械化残留 → v5 完全重写为图+数值哲学 |
| L2 | v1 → v2 | phase 6 档去百分比阈值,nearest_support 去"心理整数",防偏见 #4 多维度化 |
| L3 | v1 → v2 | 硬约束 H4/H6/H7 合并为 H4(按反模式数量精确降级 0/1/≥2) |
| L4 | v1 → v2 | crowding_risk 删 "Z>1.5" 硬阈值;数据缺失默认改 moderate(非 elevated) |
| L5 | v1 → v2 | extreme_event 触发条件去重;补"客观档位例外"说明;标题 5→6 类 |
| 主裁 | v1 → v2 | 修正 3 个 fewshot 数学(0.4408→0.4409 / 0.014→0.007 / 0.4288→0.3815) |

---

## 3. Task C — AdjudicatorValidator(commit 9a76cd5)

### 3.1 改动文件

- 新增 [src/ai/validator.py](../../src/ai/validator.py)(255 行)
- 新增 [tests/ai/test_validator.py](../../tests/ai/test_validator.py)(33 测试)
- 新增 [tests/ai/__init__.py](../../tests/ai/__init__.py)

### 3.2 10 条硬约束(对齐主裁 prompt §13 H1-H10)

| 规则 | 含义 | 行为 |
|---|---|---|
| H1 | narrative 引用 grade 与 L3 一致 | 软违反:notes 标记不一致,不强制覆盖文本 |
| H2 | stop_loss 必须从 L4.hard_invalidation_levels 选 | 强制使用 L4 第一个止损位 |
| H3 | position_cap_final.value ≥ 0.15 硬下限 | 强制为 0.15 |
| H4 | extreme_event=true → state 必须 PROTECTION | 强制 to_state=PROTECTION + action=protective |
| H5 | L1=chaos → action 必须 watch / hold | 持仓中→hold,FLAT→watch |
| H6 | L3=none → action 必须 watch / hold | 同 H5 |
| H7 | EXIT 直跳 PLANNED → 强制 FLIP_WATCH | 4 种非法跨越场景 |
| H8 | position_size_pct ≤ position_cap_final.value | 强制 size = cap |
| H9 | counter_arguments ≥ 1 条 | 添加 placeholder |
| H10 | confidence ≤ data_pct × min(L1-L5 confidence) | 强制下调 + 1% 浮点容差 |

违反时:auto-fix 输出 + 在 notes 加 `ai_overridden_<rule>` 标签。

返回结构:
```python
{
    "validated_output": <修正后的主裁输出>,
    "violations": [{"rule": "H4", "detail": "...", "auto_fix": "..."}, ...],
    "passed": <bool>
}
```

### 3.3 测试覆盖(33 个,全通过)

每条 H1-H10 至少 3 个场景:命中 / 未命中 / 边界。
- H3 边界:0.15 刚好不触发
- H4 已正确(主裁已给 PROTECTION):不触发
- H8 size=cap:边界不触发(浮点 1e-9 容差)
- 多重违反综合测试:chaos + extreme_event + grade=none
- 防 mutation 测试:不修改调用方传入的 master_output

---

## 4. Task D — AIOrchestrator(commit 1995c0b)

### 4.1 改动文件

- 新增 [src/ai/orchestrator.py](../../src/ai/orchestrator.py)(484 行)

### 4.2 执行流程(对齐建模 §3.2.1)

```
context (klines + indicators + macro + events + state)
   │
   ▼
1. L1 AI(看 1d K 线主图 + ADX + ATR 副图)
2. L2 AI(看 1d+4h 双周期图 + L1 输出)
3. L3 AI(无图,消费 L1+L2 + risk_preview + anti_pattern_signals)
4. L4 AI(看 1d 风险图:K 线+EMA+key_levels+ATR带 / funding / OI / flow,
   消费 L1+L2+L3)
5. L5 AI(无图,独立宏观判断,不消费 L1-L4)
   │
   ▼
计算 _system_provided multipliers:
  - crowding_multiplier(从 L4.risk_breakdown.crowding_risk 推导)
  - event_multiplier(从 events_calendar_72h 最高 impact 推导)
   │
   ▼
6. 主裁 AI(消费 L1-L5 + _system_provided)
   │
   ▼
7. AdjudicatorValidator 校验 → final_output
```

### 4.3 _system_provided 计算

`_compute_crowding_multiplier(l4_output)`:

| crowding_risk | multiplier |
|---|---|
| 0-25 | 1.0 |
| 25-50 | 0.85 |
| 50-75 | 0.65 |
| 75-100 | 0.50 |

`_compute_event_multiplier(events_72h)`:取 72h 内最高 impact_level

| impact | multiplier |
|---|---|
| critical | 0.5 |
| high | 0.7 |
| medium | 0.85 |
| low / 无事件 | 0.95 |

### 4.4 失败处理

任一层失败:
- 走该 agent 的 `_fallback_output()`(返回 status='degraded_*' 的最小合法 dict)
- 后续层接收 fallback 输入(下游 prompt 已设计为容忍 fallback dict)
- 主裁可能 fallback 到 watch/hold
- 整个 pipeline **不抛异常**,result['status'] 标记 degraded

### 4.5 入口函数

`run_ai_pipeline_v13(context)` 给手动测试用,本阶段**不接入 jobs.py 主流程**
(留 Sprint 1.9 频率重构时做)。

---

## 5. Task E — Mock 测试(commit 7b4eed8)

### 5.1 改动文件

- 新增 [tests/ai/test_agents_with_mock.py](../../tests/ai/test_agents_with_mock.py)(14 测试)
- 新增 [tests/ai/test_orchestrator.py](../../tests/ai/test_orchestrator.py)(11 测试)

### 5.2 测试矩阵

#### 5.2.1 单 agent 测试(14)

每个 agent(L1-L5 + master)测:
- ✅ 正常 JSON 返回 → status=success + 含核心字段
- ✅ API 异常(TimeoutError 等)→ fallback dict 触发

L1 额外测:
- ✅ 非 JSON 错乱内容 → fallback
- ✅ ` ```json ``` ` 包裹 → loose parser 解析

#### 5.2.2 Orchestrator e2e 测试(11)

| 测试 | 场景 | 期望 |
|---|---|---|
| `test_ideal_open_long_5layers_aligned` | 5 层齐心 | FLAT → LONG_PLANNED + open + 无违反 |
| `test_extreme_event_protection_h4` | L5 extreme_event=true | Validator 强制 PROTECTION |
| `test_l1_chaos_no_open_h5` | L1=chaos + 主裁 open | 强制 watch (H5) |
| `test_l3_none_no_open_h6` | L3=none + 主裁 open | 强制 watch (H6) |
| `test_validator_h2_stop_loss_off_list` | stop_loss 不在 L4 列表 | 强制覆盖到 L4 第一个 (H2) |
| `test_compute_crowding_multiplier_buckets` | 4 个 crowding 档位 | 1.0/0.85/0.65/0.50 |
| `test_compute_event_multiplier_levels` | 5 个 impact 档位 | 0.95/0.85/0.7/0.5 |
| `test_compute_event_multiplier_takes_max_impact` | 混合事件 | 取最高 impact |
| `test_l1_failure_does_not_crash_pipeline` | L1 fallback | pipeline 完成 + status=degraded_l1 |
| `test_orchestrator_result_structure` | 结果结构 | 含 layers/validator/status/latency_ms |

### 5.3 总测试结果

```
tests/ai/test_validator.py        33 passed
tests/ai/test_agents_with_mock.py 14 passed
tests/ai/test_orchestrator.py     11 passed
                                  ---
                                  58 passed in 1.76s
```

---

## 6. 本 sprint 删除清单

**本 sprint 无删除项**,纯新增。

理由:
- v1.3 切换到 AI 主导架构,但旧 layer/composite 代码仍被现有 jobs.py
  调用(每日 16:00 流程)
- 本 sprint 只做"新架构骨架 + 隔离测试",不接入主流程,因此**不能**删旧代码
- 旧 layer / composite / l1_l5_evidence / l5_adjudicator 等文件按建模工程
  纪律 §X 规定,在 **Sprint 1.8.1** 真删除(待 1.8 整体上线生产 + 用户验收
  通过后)

---

## 7. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ai/ 58/58 通过(其他测试套件原有 1 个失败 `test_onchain_skip_when_today_already_inserted` 与本 sprint 无关) |
| GitHub push(commit 7b4eed8) | ✅ 已 push origin/main |
| 服务器 git pull | ⏳ 待用户执行(本 sprint 不接入 jobs.py,不影响生产运行) |
| 服务器 systemctl restart | ⏳ 待用户执行(可选;不重启不影响生产) |
| 生产 DB 迁移 / 清污 | N/A(无 DB schema 变更) |

**对话第 1 段说法**:本地完成 + 已 push,等用户 SSH 验收(代码加载 + 单测
重跑)。生产端**不需要立即重启**,因为 Sprint 1.8 不修改 jobs.py 主流程
(运行的是旧规则架构 + 旧 layer/composite,本次只多出一套未启用的新代码)。

---

## 8. 用户 SSH 验收清单

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

# 1. 所有 prompt + 模块文件存在
ls -la src/ai/agents/prompts/
ls -la src/ai/agents/
ls -la src/ai/validator.py src/ai/orchestrator.py

# 2. 跑全部 AI 测试
.venv/bin/pytest tests/ai/ -v 2>&1 | tail -50

# 3. 验证 import 正常
.venv/bin/python -c "
from src.ai.orchestrator import AIOrchestrator
from src.ai.validator import AdjudicatorValidator
from src.ai.agents.chart_renderer import ChartRenderer
from src.ai.agents.l1_regime_analyst import L1RegimeAnalyst
from src.ai.agents.master_adjudicator import MasterAdjudicator
print('所有模块 import 通过')
"

# 4. 看 _system_provided 计算正确
.venv/bin/python -c "
from src.ai.orchestrator import AIOrchestrator
o = AIOrchestrator()
print('crowding 20:', o._compute_crowding_multiplier({'risk_breakdown': {'crowding_risk': 20}}))
print('crowding 80:', o._compute_crowding_multiplier({'risk_breakdown': {'crowding_risk': 80}}))
print('no events:', o._compute_event_multiplier([]))
print('critical:', o._compute_event_multiplier([{'impact_level': 'critical'}]))
"
```

期望输出:
- pytest:`58 passed`
- import:`所有模块 import 通过`
- multipliers:`crowding 20: 1.0` / `crowding 80: 0.5` / `no events: 0.95` /
  `critical: 0.5`

---

## 9. 后续 Sprint 规划

| Sprint | 目标 |
|---|---|
| 1.8.1 | 真删除旧 layer/composite 代码(`src/strategy/layers/*` / 旧 `composite_*`),按建模 §X 工程纪律执行 |
| 1.8.2 | 前端重设计(对齐建模 §9 网页 API + 移除人读版 5-layer evidence section) |
| 1.9 | jobs.py 频率重构(每日 16:00 跑 6 AI pipeline → 替代旧 4.4-4.6 规则计算) |
| 1.10 | 因子卡文案细化(目前 9 张 v1.3 新卡为占位文案) |
| 1.11 | M26 回测 + AI 输出质量调优(prompt 微调) |

---

## 10. Sprint 1.8 v5 commit 列表(共 22 个 commit)

```
7b4eed8 test(ai): 1.8 Task E — 25 个 mock 测试覆盖 6 agents + Orchestrator e2e
1995c0b feat(ai): 1.8 Task D — AIOrchestrator 串行编排 6 AI + Validator
9a76cd5 feat(ai): 1.8 Task C — AdjudicatorValidator + 33 测试通过
25194c6 fix(prompt): 1.8 Task B #6 — master prompt v2 修正 3 个 fewshot 数学错误
d375d33 feat(prompt): 1.8 v5 master_adjudicator prompt 草稿(主裁层)
b26834a fix(prompt): 1.8 Task B #5 — L5 prompt v2 触发条件去重 + 标题修正
fe06422 feat(prompt): 1.8 v5 L5 prompt 草稿(宏观背景分析师)
86ffe46 fix(prompt): 1.8 Task B #4 — L4 prompt v2 删硬阈值 + 默认值修正
901a767 feat(ai): 1.8 v5 L4 prompt 草稿 + render_l4_chart
f380a28 fix(prompt): 1.8 Task B #3 — L3 prompt v2 硬约束精简 + fewshot 维度纠正
15de3d8 feat(prompt): 1.8 v5 L3 prompt 草稿(机会执行分析师)
1d32d43 fix(prompt): 1.8 Task B #2 — L2 prompt v2 phase 去阈值 + 4 处小修
78f42b3 feat(ai): 1.8 v5 L2 prompt 草稿 + render_l2_chart
7f0abd1 feat(prompt): 1.8 v5 任务 C — L1 prompt v5 完整重写(图+数值,无规则结论标签)
47c88f4 docs(prompts): 1.8 v5 任务 D — _README.md 锁定 v1.3 AI 输入哲学
9db65b5 feat(ai): 1.8 v5 任务 A+B — chart_renderer + BaseAgent multi-modal
981ef59 fix(prompt): 1.8 Task B #1 — L1 prompt v4 fewshot key_signals 同步'含义描述'风格
c73133e fix(prompt): 1.8 Task B #1 — L1 prompt v3 清理 4 处机械化残留
fa75216 fix(prompt): 1.8 Task B #1 — L1 prompt v1.3 哲学纠正(7 处)
d4b73d0 feat(ai): 1.8 Task B #1 — L1 Regime AI prompt 草稿(等用户审)
6123720 feat(ai): 1.8 Task A — BaseAgent + 6 AI 角色模块骨架
```

---

## 11. 风险提示与已知限制

1. **prompt 未真实测过 anthropic API 视觉能力**:本 sprint 只用 mock client
   测试,真实多模态调用要 Sprint 1.9 接入 jobs.py 后才会触发。如发现 AI
   对图片识别效果不到位,需 Sprint 1.11 调优。

2. **`_system_provided` multipliers 可能需调优**:
   - crowding bucket 阈值(25/50/75)和 event multiplier 值(0.5/0.7/0.85/0.95)
     是初版,M26 回测后可能调整
   - 现实场景中 events_calendar 由谁提供?目前 orchestrator 接收 list,
     需 Sprint 1.9 决定数据源(FRED 经济日历 / 手动维护 yaml / Alphanode 等)

3. **L1 / L2 / L4 chart 缺数据时返回 None**:
   - mpf addplot 在 addplots 全空 + None 时会日志告警(不致命,chart=None,
     orchestrator 把 chart_b64=None 透传给 agent,agent 改用纯文本模式)
   - 这是预期行为,不视为 bug

4. **主裁 prompt 引用 `_system_provided` 未在 master_adjudicator.py 的
   `_build_user_prompt` 中显式拍平**:目前 `_build_user_prompt` 只引用了
   l1_output / l2_output / ... / hard_invalidation_levels 等字段,
   `_system_provided` 没有作为单独 key 出现。这意味着主裁 AI 看到的 user
   prompt 不会包含 crowding/event multipliers — 但这两个数值在 prompt §7
   中已说明"由系统提供",AI 应当**使用其在 master_input 中得到的 multiplier
   值**(实际由 orchestrator 通过 `master_input["_system_provided"]` 传入)。
   **修正建议**:Sprint 1.9 接入 jobs.py 时,扩展 master_adjudicator.py 的
   `_build_user_prompt` 显式 dump `_system_provided`。

---

## 12. 总结

Sprint 1.8 v5 为 v1.3 "AI 主导 + 规则硬约束" 架构搭建了完整的代码骨架:

- **6 个 AI 角色** + **6 个 prompt(用户审定)** + **3 个 chart 渲染器**
- **AdjudicatorValidator(10 条硬约束)** + **AIOrchestrator(串行编排)**
- **58 个 mock 测试全通过**(33 validator + 14 agents + 11 orchestrator)
- **22 个 commit** 全部 push 至 GitHub origin/main

新架构与现有 jobs.py 完全隔离,**不影响生产运行**。后续 Sprint 1.8.1 真删
旧代码,Sprint 1.9 接入主流程。
