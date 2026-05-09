# Sprint H — weekly_review retry + prompt 扩展

**完成日期**: 2026-05-09
**Commits**:
- Part A: `c7552f5` feat(scheduler): Sprint H Part A — weekly_review 加 retry(共享 ai_retry 间隔)
- Part B: `ede2152` feat(weekly_review): Sprint H Part B — input + prompt 扩展(反模式/L3-L4 分布/价格走势/AI vs 实际)

**对齐建模**: docs/modeling.md §3.3.9(weekly_review)+ §8.1(复盘)+ §10(retry/调度纪律)

---

## Part A — weekly_review retry 兜底(已合并 c7552f5)

### 现状(修复前)

`docs/cc_reports/weekly_review_audit_trigger_retry.md` 审计核心结论:
- weekly_review 单层 fallback,**无 retry 无 push**;一次失败整周丢
- 与 master AI 11:35 cron 形成对比:master AI fail 走 [30,60,60]+3h retry + Bark push;
  weekly_review fail 啥都没有

### 改动

#### 1. `src/scheduler/jobs.py` 新增 retry wrapper

```python
def _enqueue_weekly_review(delay_sec, attempt, retry_start_utc):
    """放下次 retry 到 _active_scheduler(cron yaml 启动时绑定)。"""
    sched = _active_scheduler
    if sched is None:
        return False
    next_run = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
    sched.add_job(
        func=job_weekly_review_with_retry,
        trigger="date", run_date=next_run,
        kwargs={"attempt": attempt, "retry_start_utc": retry_start_utc},
        id=f"weekly_review_retry_{attempt}_{int(next_run.timestamp())}",
        replace_existing=False,
    )
    return True


def job_weekly_review_with_retry(attempt=1, retry_start_utc=None):
    """共享 ai_retry: intervals=[30,60,60], window_total_minutes=180。
    
    与 pipeline_run_with_retry 的差别:这里 max_attempts_per_layer=4(主跑+3次 retry),
    backoff 用 attempt 直接索引(不是 attempt+1),所以第一次 retry = intervals[0]=30min。
    """
    result = job_weekly_review()
    ai_status = (result.get("by_collector") or {}).get("ai_status")
    weekly_status = (result.get("by_collector") or {}).get("weekly_review")
    failed = ai_status != "success" or weekly_status == "input_builder_failed"
    if not failed:
        return result
    
    policy = RetryPolicy.from_yaml_config(
        get_retry_policy_config(get_base_config()),
        max_attempts_per_layer=4,  # 主跑 + 3 次 retry
    )
    if attempt >= policy.max_attempts_per_layer:
        result["retry_exhausted"] = True
        return result
    if retry_start_utc:
        elapsed = ...  # check 3h 窗口
        if elapsed > policy.window_total_minutes * 60:
            result["retry_exhausted"] = True
            return result
    
    delay_sec = policy.compute_backoff_seconds(attempt)  # attempt=1 → intervals[0] = 30min
    if _enqueue_weekly_review(delay_sec, attempt + 1, retry_start_utc or now_utc()):
        result["retry_scheduled"] = True
        result["retry_next_attempt"] = attempt + 1
        result["retry_next_delay_sec"] = delay_sec
    return result
```

#### 2. `_JOB_FUNCTIONS` 注册更新

```python
_JOB_FUNCTIONS = {
    ...
    "weekly_review": job_weekly_review_with_retry,        # 生产 cron yaml 用此 key
    "weekly_review_no_retry": job_weekly_review,           # 单测 / 直调留无 retry 入口
}
```

### 时间表(对齐用户需求)

| Attempt | 时机 | 触发条件 |
|---|---|---|
| 1 (主跑) | 周日 22:00 BJT | scheduler.yaml::weekly_review cron |
| 2 (retry 1) | 22:30 (+30min) | attempt=1 fail |
| 3 (retry 2) | 23:30 (+60min) | attempt=2 fail |
| 4 (retry 3) | 0:30 (+60min) | attempt=3 fail |
| 放弃 | 1:00 (+30min) | attempt=4 仍 fail 或超 3h 窗口 |

无跨日补偿 — 周日 1:00 之后失败的整周复盘自然丢。

### Part A 单测覆盖(`tests/test_sprint_h_part_a_weekly_review_retry.py`)

10 个用例:
- AI 成功 → 不 retry
- attempt=1 fail → schedule attempt=2 at +1800s(30min)
- attempt=2 fail → schedule attempt=3 at +3600s(60min)
- attempt=3 fail → schedule attempt=4 at +3600s(60min)
- attempt=4 fail → `retry_exhausted=True`
- retry_start_utc 超 3h → `retry_exhausted=True`
- input_builder_failed → 走 retry(transient DB 也算可恢复)
- `_enqueue_weekly_review` 无 scheduler → False
- `_enqueue_weekly_review` 有 scheduler → 真 add_job
- `_JOB_FUNCTIONS["weekly_review"]` → wrapper

---

## Part B — input + prompt 扩展(已合并 ede2152)

### 背景

`docs/cc_reports/weekly_review_audit.md` P0 候选:周复盘缺 5 类关键聚合
- 反模式触发率(L3 5 类)
- L3 opportunity_grade 分布
- L4 risk_tier 分布
- BTC 实际走势(price_candles 1d)
- master 真跑通且给 trade_plan 的 run(用于 AI vs 实际对比)

且 prompt 给的 adjustment_recommendations 没强制要求「具体调整路径」,
AI 容易给「降低 AI 失败率」这种空泛建议。

### 改动

#### 1. `src/ai/weekly_review_input_builder.py` 加 5 类聚合

```python
def _aggregate_anti_pattern_signals(rows):
    """5 类 L3 反模式 7 天触发率。
    
    extending_late_phase / against_long_cycle / chasing_breakout_no_pullback
    / failing_at_resistance / after_extreme_event_no_reset
    """
    return {
        "total_runs_with_l3": ...,
        "anti_pattern_counts": {flag: count, ...},
        "trigger_rates": {flag: "X.X%", ...},
        "top_flag": ("flag_name", count) or None,
    }


def _aggregate_l3_grade_distribution(rows):
    """{A, B, C, none, empty} 计数。"""

def _aggregate_l4_risk_tier_distribution(rows):
    """{low, moderate, elevated, extreme, empty} 计数。"""

def _aggregate_weekly_price_action(start_dt, end_dt):
    """price_candles 1d 7 天 K 线 + 周涨跌幅 + 最大日内回撤。
    
    返:
    - daily: [{date, open, high, low, close, volume}, ...]
    - week_open / week_close / week_high / week_low
    - week_pct_change
    - max_intra_drawdown_pct(用周高点回撤算)
    """

def _aggregate_master_runs_with_trade_plan(rows):
    """master AI 真跑通且 v1.3 有 trade_plan 或 v1.4 有 new_thesis 的 run 列表。
    
    跳过 fallback_level=level_1/level_2 的 fallback 输出。
    返:[{run_at, mode, opportunity_grade, regime, phase, stance, 
          entry_zone, stop_loss, take_profit_zones, trade_plan_dump,
          new_thesis_id, narrative}, ...]
    """
```

5 个聚合都接到 `build_weekly_review_input` 返回 dict:
```python
return {
    "window": {...},
    "performance_summary_raw": {...},
    "thesis_lifecycle": {...},
    "virtual_orders_aggregate": {...},
    "retry_log_aggregate": {...},
    "virtual_account_window": {...},
    "fuse_and_states": {...},
    "hard_constraint_activation_raw": {...},
    "anti_pattern_signals": {...},                   # 新
    "l3_grade_distribution": {...},                  # 新
    "l4_risk_tier_distribution": {...},              # 新
    "weekly_price_action": {...},                    # 新
    "master_runs_with_trade_plan": [...],            # 新
    "context": {...},
}
```

#### 2. `src/ai/agents/weekly_review_analyst.py` _build_user_prompt 加 5 段

prompt 变 12 段(原 7 + 新 5):
- §8 反模式触发率 + 阈值评估指引(>40% 偏松 / <5% 阈值合理 / =0 prompt 不清)
- §9 L3 grade 分布 + 期望分布(A 1-2/年、B 1-2/月、C 3-4/月)
- §10 L4 risk_tier 分布 + 期望分布(low+moderate 占多数,elevated < 30%)
- §11 BTC 实际走势(price_candles 1d 7 天 + 中立性纪律)
- §12 master_runs_with_trade_plan + ai_vs_actual_comparison 子段输出要求

新增「中立性纪律」: 中长线 1 周样本不足以判 AI 准/错,
评估只针对关键位(止损/止盈/入场区)合理性。

新增「具体调整路径」强制约束:
- 阈值改动: `<文件>:<行号> 的 X 阈值从 Y 改为 Z` 格式
- 或观察期: `建议先观察 N 周后调整,理由 ...` 格式
- **不许**「降低 AI 失败率」式空泛建议(若数据不足不能给具体值,
  优先级用 low + 写「先观察 N 周」)

#### 3. `src/ai/agents/prompts/weekly_review_analyst.txt` 加 Sprint H Part B 段

末尾追加 95 行,包含:
- 5 段新 input 描述(对应 §8-§12)
- ai_vs_actual_comparison JSON schema 示例(用 5/3 16:08 B 级 master run 当模板,
  含 direction_assessment / entry_zone_assessment / stop_loss_assessment / 
  take_profit_zones_assessment / overall + 中立性 reasoning)
- 「具体调整路径」字段两种格式(具体阈值 / 数据不足建议观察)
- 明文禁「降低 AI 失败率」式建议

### Part B 单测覆盖(`tests/test_sprint_h_part_b_input_extension.py`)

10 个用例:
1. `test_anti_pattern_aggregate_counts_per_flag` — 3 runs seeded extending_late_phase,
   trigger_rate 100% / top_flag 命中
2. `test_l3_grade_distribution` — 8 runs A/B/B/C/C/C/none/none → counts 对得上
3. `test_l4_risk_tier_distribution` — 6 runs 4 档分布
4. `test_weekly_price_action` — 6 days 1d K 线,week_pct_change/high/low 正确
5. `test_weekly_price_action_empty` — 空 DB 返 daily=[] / week_*=None
6. `test_master_runs_with_trade_plan_v13` — v1.3 schema 含 trade_plan 三件套
7. `test_master_runs_excludes_fallback` — fallback_level=level_2 排除
8. `test_build_weekly_review_input_includes_5_new_fields` — 集成断言 5 个新 key
   都在 build_weekly_review_input 返回的 dict 里(JSON 解析,**不是** mock.called)
9. `test_prompt_includes_new_sections` — agent._build_user_prompt 字符串
   含「反模式触发率」「L3 opportunity_grade 分布」「L4 risk_tier 分布」
   「BTC 实际走势」「master 真跑通」「ai_vs_actual_comparison」「中立性」
   「具体调整路径」
10. `test_prompt_txt_contains_sprint_h_section` — 物理 prompt .txt 文件含
    「Sprint H Part B」「ai_vs_actual_comparison」「具体调整路径」「反模式触发率」

---

## §X 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| (无) | (无) | 本 sprint 纯新增功能 + 改 1 个 yaml-key 路由(weekly_review → wrapper),无旧函数 / 类被替代 |

`_JOB_FUNCTIONS["weekly_review"]` 从 `job_weekly_review` 改成
`job_weekly_review_with_retry` — `job_weekly_review` 没删,留作
`_JOB_FUNCTIONS["weekly_review_no_retry"]` 给单测用,且 wrapper 内部直接调它。
不算"被替代"。

---

## §Z 端到端断言记录

- 5 类聚合 — 真插数据库行(strategy_runs / price_candles)再调
  `build_weekly_review_input`,JSON 解析返 dict 断言新 key 存在 +
  内容正确(test 1-8)
- prompt 内容 — 直接断言字符串包含 8 个关键短语(test 9)
- prompt .txt 文件 — 物理读文件断言 4 个关键短语(test 10)
- 不是 .called / mock 桩

---

## 验收记录

### 本地测试

```
$ .venv/bin/python -m pytest tests/test_sprint_h_part_a_weekly_review_retry.py tests/test_sprint_h_part_b_input_extension.py -q
20 passed in X.XXs

$ .venv/bin/python -m pytest --tb=short -q
1693 passed, 1 skipped, 648 warnings in 10.27s
```

0 regression,所有原有测试通过。

### 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1693 passed |
| GitHub push(commits c7552f5 + ede2152) | ✅ |
| 服务器 git pull | ⏳ 待用户执行 |
| 服务器 systemctl restart | ⏳ 待用户执行 |
| 生产 DB 迁移 | N/A — 本 sprint 无 schema 改动 |

待用户 SSH 执行命令:
```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main
sudo systemctl restart btc-swing-api
sudo systemctl restart btc-swing-scheduler

# 服务器 pytest 强制重跑(强制项 §F)
.venv/bin/python -m pytest -q
# 期望:1693 passed, 1 skipped(本地一致)

# 手动触发 weekly_review 验证新字段(.env 装 set -a 加载)
set -a; source .env; set +a
.venv/bin/python -c "
from src.scheduler.jobs import job_weekly_review
from src.storage.database import default_database
job_weekly_review()

# 查最新行的 5 个新字段
import json
db = default_database()
row = db.execute('select input_json_compact from weekly_review_runs order by week_start_utc desc limit 1').fetchone()
inp = json.loads(row[0])
for k in ['anti_pattern_signals', 'l3_grade_distribution',
          'l4_risk_tier_distribution', 'weekly_price_action',
          'master_runs_with_trade_plan']:
    print(f'{k}: {bool(inp.get(k))}')
"
```

---

## 未覆盖项 / 风险提示

1. **服务器 pytest 待跑** — 强制项 §F,本地 1693 passed 但服务器 Python 环境
   可能 lock 不一致;需用户 SSH 跑 `.venv/bin/python -m pytest -q`,
   期望同样 1693 passed。

2. **手动触发 5/4 那周 input 待验证** — 本地无生产 DB,只能服务器跑;
   预期新 5 个 key 都在 weekly_review_runs.input_json_compact 里。

3. **5/10 周日 22:00 自然首跑** — 自然 UPSERT 覆盖,不做手动 backfill
   (用户明确禁止)。届时 retry 兜底 + 新 prompt 一起首次生产端运行。

4. **scheduler 启动期 _active_scheduler 全局** — `_enqueue_weekly_review`
   依赖 `jobs._active_scheduler`(scheduler/main.py 启动时绑定);
   单测有 autouse fixture 隔离全局,生产端 scheduler 不会重启 ≥ 1 次/天,
   理论上稳。如果出现 scheduler 重启时正在 retry → 那次 retry 任务会丢
   (新 scheduler 的 _active_scheduler 拿不到老的 add_job),但这与
   master AI retry 的局限相同,不是 Part A 引入的回归。

---

## 详细报告

(本文件即详细报告)

---

## 附录 — 服务器部署 + 验证(2026-05-09 收尾)

### 1. 部署:git pull + restart ✓

```
$ ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && git pull && \
    sudo systemctl restart btc-strategy.service && sleep 5 && \
    sudo systemctl status btc-strategy.service --no-pager | head -15"

c8f7bf4..0f75ad5  main  ->  origin/main
Fast-forward (11 files changed, +2157)
● btc-strategy.service - active (running) since Sat 2026-05-09 15:39:15 CST; 5s ago
```

### 2. 服务器 pytest 全 suite ✓

```
$ ssh ubuntu@124.222.89.86 ".venv/bin/pytest --tb=no -q"
1693 passed, 1 skipped, 648 warnings in 143.93s (0:02:23)
```

跟本地完全一致。

### 3. 5 个新字段实测填齐 ✓(直接调 build_weekly_review_input)

注:`weekly_reviews` 表 schema 只存 `output_json` 不存 input。所以验证方式
是直接调 `build_weekly_review_input(conn)` dump 5 字段:

```
=== 5 new fields ===
  anti_pattern_signals: present=True size=4
  l3_grade_distribution: present=True size=5
  l4_risk_tier_distribution: present=True size=5
  weekly_price_action: present=True size=7
  master_runs_with_trade_plan: present=True size=1

=== anti_pattern_signals ===
{
  "total_runs_with_l3": 65,
  "anti_pattern_counts": {
    "extending_late_phase": 35,
    "failing_at_resistance": 1
  },
  "trigger_rates": {
    "extending_late_phase": 0.5385,
    "failing_at_resistance": 0.0154
  },
  "top_flag": "extending_late_phase"
}

=== l3_grade_distribution ===
{ "A": 0, "B": 10, "C": 4, "none": 51, "empty": 0 }

=== l4_risk_tier_distribution ===
{ "low": 0, "moderate": 13, "elevated": 44, "extreme": 0, "empty": 8 }

=== weekly_price_action summary ===
daily_count: 8
week_open: 78191.9
week_close: 80331.3
week_pct_change: 2.736
max_intra_drawdown_pct: -4.457

=== master_runs_with_trade_plan count ===
count: 1
first run keys: ['generated_at_bjt', 'btc_price_at_run', 'l3_grade',
                 'l4_risk_tier', 'schema', 'master_direction', 'entry_zone',
                 'stop_loss', 'take_profit_zones', 'position_size_pct']
```

5 字段全部真填,结构对。注意 `master_runs_with_trade_plan` 只有 1 条 —
跟 Sprint G 审计结论一致(过去 7 天只有 5/3 16:08 那一次成功 B 级 master)。

### 4. AI 真出 → fallback ✗(暴露独立生产问题)

```
$ ssh ubuntu@... ".venv/bin/python -c 'from src.scheduler.jobs \
    import job_weekly_review; print(job_weekly_review())'"

weekly_review_analyst: attempt 1 failed: Error code: 400 - Provider API error:
Model 'claude-sonnet-4-5-20250929' is not supported.
weekly_review_analyst: attempt 2 failed: Error code: 400 - Provider API error:
Model 'claude-sonnet-4-5-20250929' is not supported.
{'by_collector': {'weekly_review': 'completed', 'week_start_utc': '2026-05-04',
'critical_count': 1, 'ai_status': 'degraded_ai_failed'}, ...}
```

DB row 上传成功(`week_start_utc=2026-05-04` 真插了),但 `output_json`
是 fallback 内容(`status: degraded_ai_failed`,7 段 JSON 结构齐但 AI 没产文本)。

**由于 AI 没真跑,无法验证「AI 真给的 adjustment_recommendations 是否含
具体调整路径」**。fallback 第 1 条建议是 hardcoded `{
"目标": "恢复周复盘 AI 正常运行",
"建议": "检查 anthropic API key + 中转站状态",
"优先级": "high",
"影响": "周复盘缺失,无法发现硬约束阈值过严/过松问题"
}` — 这是 fallback 文案,不是 AI 真给的「具体路径」格式。

#### 4.1 根因 — model id 不对

`claude-sonnet-4-5-20250929` 在 alphanode 中转站不支持。需要查
`base.yaml::weekly_review_analyst.model` 改成中转站支持的 id(可能是
`claude-sonnet-4-5` 或 `claude-haiku-4-5-20251001`)。

这是一个**独立生产问题**,**不属于 Sprint H 范围**。Sprint H 改的是
input + prompt 文本,model id 在 yaml 配置里。建议 Sprint I 候选:
- 列 alphanode 实际支持的 Anthropic model id
- 改 base.yaml 所有 agent 的 model 字段对齐
- 1 次试跑 manual trigger 验 AI 真出非 fallback

#### 4.2 master AI 用 claude-sonnet-4-5-20250929 跑通了 ✓

5/9 中午 11:35 master AI(同 model id)成功跑完 — 见 `master_runs_with_trade_plan`
里的 5/3 run 数据。说明 alphanode 对该 model id 的支持**不稳定 / 限速 /
某个时间窗口才支持**。需要 alphanode 客服侧确认。

或者:weekly_review 走的是 anthropic Python SDK(直连 anthropic.com),
master 走的是 OpenAI SDK 兼容 endpoint(alphanode 中转)— 两边对 model id
的支持不同。需查 BaseAgent.run() 走的是哪个 client。

### 部署四件事清单(更新)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1693 passed |
| GitHub push(commits c7552f5 + ede2152 + 0f75ad5) | ✅ |
| 服务器 git pull | ✅ 已拉到 0f75ad5 |
| 服务器 systemctl restart | ✅ active since 2026-05-09 15:39:15 CST |
| 服务器 pytest 全 suite | ✅ 1693 passed, 1 skipped(同本地) |
| 5 字段填齐验证 | ✅ 真数据有内容(详见附录 §3) |
| AI 真跑(非 fallback)| ❌ model id 不支持,走 fallback |
| 生产 DB 迁移 | N/A |

### 后续 backlog(进 Sprint I 候选)

1. **修 weekly_review_analyst model id**(必跑)— alphanode 不支持
   `claude-sonnet-4-5-20250929`,需查支持列表 + 改 yaml + 重测。
2. **5/10 周日 22:00 自然首跑** — 即使 model id 修了,需观察 22:00
   是否真触发 + retry 兜底是否真 enqueue + AI 真出含具体路径。
3. **scheduler 重启时正排队的 retry 任务丢失** — 局限,与 master AI retry 相同。
