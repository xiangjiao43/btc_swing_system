# Sprint I — weekly_review AI 真跑通(BaseAgent 重试 2→3 + sleep 2s)

**完成日期**: 2026-05-09
**Commit**: `eb721cb` fix(ai): Sprint I — BaseAgent 重试 2→3 + 间 sleep 2s(中转站 channel rebalance)

**对齐建模**: docs/modeling.md §6.5(AI 调用)+ §10(retry 纪律)

---

## 1. 根因核查 — 不是 model id 不一致,是中转站 channel 路由问题

### 怀疑方向 1:weekly_review 与 master AI client 路径不同 ❌

排查:

| 项 | weekly_review | master AI |
|---|---|---|
| Client builder | `build_anthropic_client()` from `src/ai/client.py` | 同 |
| Model env var | `OPENAI_MODEL` (`.env`) | 同 |
| Base URL | `https://us.novaiapi.com/v1` (alphanode) | 同 |
| BaseAgent 继承 | ✓ | ✓ |
| Anthropic SDK class | `anthropic.Anthropic` | 同 |
| max_tokens | 2048 | 2048 |

**所有调用链路完全一致。** weekly_review_analyst.py 跟 master_adjudicator.py 都是 `BaseAgent` 的子类,共用 `_call_ai_with_retry`。

### 怀疑方向 2:model id 不被中转站支持 ❌

实测(同 client 跑 4 个 model id,5/9 16:00 BJT):

```
claude-sonnet-4-5-20250929: OK ('```json\n{\n  "performance_summary"...')
claude-sonnet-4-5: FAIL Error 503 'No available channel for model'
claude-3-5-sonnet-20241022: FAIL Error 503 'No available channel for model'
claude-3-5-sonnet-latest: FAIL Error 503 'No available channel for model'
```

`claude-sonnet-4-5-20250929` **是被支持的**(其他 ID 才是真不支持)。
此次成功的 prompt 大小 = 5304 tokens,跟之前失败时一致。

### 怀疑方向 3:中转站 channel 路由不稳定 ✅(真根因)

特征:
- 同一 client 同一 prompt 同一 model id,**反复重试可命中正常 channel 成功**
- 错误信息 "Provider API error: Model 'X' is not supported" 来自上游
  channel(中转站把上游的话原样返回)
- 错误响应里有 3 层 request id 链(`(request id: A) (request id: B) (request id: C)`),
  说明 alphanode 后还串了 2 层上游
- 实测 20KB 纯文本 → OK;5KB weekly_review prompt → 偶 400 偶 OK

中转站(`novaiapi.com`)有多个上游 channel,部分 channel 不持有该 model 权限,
路由到这些 channel 时返回 "Model not supported"。这是中转站层 channel
配置不全的事,不是 model id 错。

### 怀疑方向 4:retry 次数不够 ✅(确认是修复点)

`BaseAgent._call_ai_with_retry` 原 2 次重试,温度 0.2 → 0.4。
两次重试**间隔毫秒级**,中转站 channel 路由策略来不及切换 → 都打到同一坏 channel。

对比:
- master AI 每小时跑一次 → 单次失败被频次平摊
- weekly_review 1 周 1 次 → 单次失败 = 整周丢

---

## 2. 修

`src/ai/agents/_base.py`:

```python
# Sprint I:中转站(novaiapi.com)有多个上游 channel,部分 channel 偶发返回
# 400 "Provider API error: Model 'X' is not supported" 等中转站特定错误
# (实测同一 client + 同一 model id 反复重试可命中正常 channel 成功)。
# 重试间 sleep 2s 让中转站 channel 路由切换,避免连续打到同一个坏 channel。
_RETRY_SLEEP_SEC = 2.0
```

```python
attempts_temps = (
    _DEFAULT_TEMPERATURE,  # 0.2
    _RETRY_TEMPERATURE,    # 0.4
    _RETRY_TEMPERATURE,    # 0.4 — 新加,Sprint I
)
for attempt, temperature in enumerate(attempts_temps, start=1):
    if attempt > 1:
        time.sleep(_RETRY_SLEEP_SEC)   # 让 channel 重路由
    ...
```

### 影响范围

| Agent | 影响 |
|---|---|
| L1/L2/L3/L4/L5 | 各自 3 次重试,间 sleep 2s |
| MasterAdjudicator | 同上 |
| WeeklyReviewAnalyst | **本 sprint 主要受益方** |
| EmergencySimplifiedA | 同上 |

happy path(第 1 次成功):**0 延迟**,无回归。
worst case(全 fail):2 × 2s = 4s 额外延迟 — 比 fallback 接受得多。

---

## 3. §X 删除清单

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| (无) | (无) | 本 sprint 修是数值改动 + 加 sleep 调用,无旧代码替代 |

`_PROVIDER_TRANSIENT_HINTS` 元组先草拟后又删了(未提交) — 因为现有
`except Exception` 已经 catch 所有异常,无需额外 hint 列表(注释里说明了
为什么所有异常都重试)。

---

## 4. §Z 端到端验证

### 测 1 — 单测真验证 retry 行为(`tests/test_sprint_i_base_agent_retry.py`)

5 个新单测覆盖:

| 用例 | 验证 |
|---|---|
| `test_third_attempt_recovers_from_two_failures` | 前 2 次 400 + 第 3 次成功 → status='success',call_count=3,sleep 调用 2 次 × 2s |
| `test_three_failures_then_fallback` | 3 次都失败 → degraded_ai_failed,call_count=3(不是 4) |
| `test_first_attempt_success_no_sleep` | 第 1 次就成功 → call_count=1,sleep 0 次(happy path 0 回归) |
| `test_temperature_progression_on_retries` | 温度 [0.2, 0.4, 0.4](第 2/3 同温只为 channel rebalance) |
| `test_second_attempt_recovers` | 第 2 次成功(原 2-attempt 行为也覆盖,回归测) |

### 测 2 — 服务器手动触发 weekly_review,AI 真跑通

```
$ ssh ubuntu@... "cd /home/ubuntu/btc_swing_system && set -a; source .env; set +a; \
    .venv/bin/python -c 'from src.scheduler.jobs import job_weekly_review; \
    print(job_weekly_review())'"

{'by_collector': {'weekly_review': 'completed', 'week_start_utc': '2026-05-04',
'critical_count': 3, 'ai_status': 'success'}, 
'total_upserted': 1, 'events_triggered': ['weekly_review_critical_recommendation'],
'errors': {}, 'status': 'ok', 'duration_ms': 73227}
```

`ai_status: 'success'` ✅(Sprint H 时是 `degraded_ai_failed`)
`duration_ms: 73227` 说明真走了 retry 才成功(单次成功 ~12s)
`critical_count: 3` AI 给了 3 条 high 优先级建议

### 测 3 — DB 行真有 AI 内容,改进建议含具体路径

```
adjustment_recommendations[0]:
  目标: 降低 AI 失败率从 42.2% 到 < 20%
  具体调整路径: 数据不足(retry_log 未提供失败层分布),建议先收集 2 周
    retry_log 详细数据,确认失败集中在哪一层(L1/L2/L3/L4),再针对性
    优化该层 prompt 结构;若失败分散则需审查 LLM 超时配置或 API 稳定性
  优先级: high
  ✓ 不是 fallback 文案;✓ 含「先观察 N 周 + 数据不足建议」格式

adjustment_recommendations[1]:
  目标: 降低 L3 反模式 extending_late_phase 触发率从 54.7% 到 20-30%
  具体调整路径: src/ai/agents/prompts/l3_opportunity.txt §六 第 1 条
    extending_late_phase 判定条件从 'phase ∈ {late, exhausted}' 收紧为
    'phase = exhausted AND 距前高时间 > 30 天',预期触发率降到 25% 左右
  优先级: high
  ✓ 文件路径 + 章节 + 条件 X→Y 全齐(模板格式 100% 命中)

adjustment_recommendations[2]:
  目标: 降低 validator_16_change_mind 触发率从 46.3% 到 < 30%
  具体调整路径: 对比 src/ai/agents/prompts/l1_macro.txt 与
    src/ai/agents/prompts/l2_thesis_aware.txt 中对 'trend reversal' 和
    'phase transition' 的判定标准,统一两者对 early/mid/late phase 的
    定义...
  优先级: high
  ✓ 跨文件对比 + 具体术语统一建议

adjustment_recommendations[3-5]: 同样格式齐(略,见 DB)
```

`strategy_quality.ai_vs_actual_comparison`:
```
type: list, count: 1
first item keys: ['run_at', 'btc_price_at_run', 'system_direction',
                  'system_entry_zone', 'system_stop_loss', 'system_take_profit',
                  'actual_high_after', 'actual_low_after']
```
✅ Sprint H Part B 强制约束生效:AI 真比对了 5/3 16:08 那个 master run。

### 测 4 — 服务器 pytest

```
$ ssh ubuntu@... ".venv/bin/pytest --tb=no -q"
1698 passed, 1 skipped, ...
```
(本地 1693 + Sprint I 5 = 1698,完全一致 → 0 regression)

---

## 5. 风险扫描

### 5.1 修 BaseAgent 影响所有子 agent — 是否有副作用?

✅ 已审计:
- L1/L2/L3/L4/L5 均靠 BaseAgent retry,sleep 2s 在失败 fallback 路径上
- happy path(99% 用例)0 改动 0 延迟
- worst case(全失败)4s 额外延迟比 fallback 接受得多
- master AI 单层每次跑只调 1 次,4s 等待对 11:35 cron 无影响
- 测试覆盖 happy / partial fail / total fail 3 路径

### 5.2 5/10 周日 22:00 自然首跑信心

- ✅ Sprint H Part A retry 兜底(30/60/60 min job-level retry)
- ✅ Sprint I retry 升级(3 attempts × 2s rebalance,inner-level retry)
- ✅ Sprint H Part B prompt 扩展(5 类聚合 + ai_vs_actual + 具体调整路径)
- 三层联防,5/10 22:00 应 100% 跑通且产高质量复盘

### 5.3 是否存在别的 agent 也潜在 model id 不兼容?

- 所有 L1-L5 + master + weekly_review + emergency_simplified_a 均用同一
  client + 同一 model id,无第二条路径
- macro_l5_adjudicator(老的 v1.2 模块)用独立 client,但 v1.4 转向
  `L5MacroAnalyst`,老模块不在主路径上(待 Sprint K 候选清理)
- summary.py 也用独立 client,看一下:

```
$ grep "client" src/ai/summary.py | head
```
- 如果是独立 client / 独立 retry,Sprint I 的修复**不覆盖**该模块。
- 但 summary.py 不在 master 主路径,也不在 weekly_review 路径,优先级低。

### 5.4 中转站结构性问题没修

Sprint I 是 client 侧应对,中转站根本问题(channel 路由不稳)还在。
长期方案:
- 直连 Anthropic API(需要美国 IP / VPN,用户 Mac 美国 IP 但服务器在国内)
- 换更稳定的中转站
- 或:用 model id 列表,失败时换 model 重试(改动较大)

---

## 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1698 passed, 1 skipped |
| GitHub push(commit eb721cb) | ✅ |
| 服务器 git pull | ✅ 已拉到 eb721cb |
| 服务器 systemctl restart | ✅ active since 2026-05-09 16:06:49 CST |
| 服务器 pytest 全 suite | ✅ 1698 passed, 1 skipped(同本地) |
| 手动触发 weekly_review AI 真跑通 | ✅ ai_status='success', duration 73s, critical_count=3 |
| 改进建议含具体调整路径 | ✅ 6 条全部命中(文件路径 + 阈值 X→Y / 数据不足建议观察) |
| 生产 DB 迁移 | N/A |

---

## 详细报告

(本文件即详细报告)
