# Sprint F.2 — master AI retry 间隔放宽

**日期**:2026-05-09 BJT
**类型**:Sprint F backlog 第 2 项,只调配置不动逻辑
**Commit**:`3b29a8a`

## 背景

Sprint F.1 把 `pipeline_run_regular` 改成 BJT 11:35 每日 1 档 + 删 event_onchain
enqueue 后,master AI 失败的 retry 策略仍是 v1.4 老配置 5/10/20 分钟 + 2h
窗口。用户决策中长线场景 5min/10min 间隔过密(API 抖动通常需要更长缓冲),
改 30/60/60 + 3h。

## 改动清单

| 路径 | 行 | 类型 | 说明 |
|---|---|---|---|
| `config/base.yaml` | -2 / +6 | 修改 | `ai_retry.intervals_minutes` [5,10,20] → [30,60,60];`total_window_hours` 2 → 3;注释加 Sprint F.2 时间表 |
| `tests/test_retry_policy.py` | -16 / +20 | 修改 | 6 个 test_backoff_* + 4 个 test_window_* + test_loads_from_base_yaml_defaults 全部更新具体数字断言 |
| `tests/test_jobs_retry.py` | -3 / +5 | 修改 | test_with_retry_error_schedules_retry 600 → 3600;test_with_retry_outside_2h_window → outside_3h_window |

合计 3 文件,+50 / -43 行。

## 关键 diff

### `config/base.yaml`

```diff
 ai_retry:
-  # 指数退避间隔(分钟):第 1/2/3 次重试分别等 5 / 10 / 20 分钟
-  intervals_minutes: [5, 10, 20]
+  # Sprint F.2(2026-05-09)用户决策:5/10/20 间隔 + 2h 窗口对中长线太密。
+  # 改为 30/60/60 分钟 + 3h 窗口。预期重试时间表(假设 BJT 11:35 失败):
+  #   12:05 retry 1(+30min) → 13:05 retry 2(+60min)
+  #   → 14:05 retry 3(+60min) → 14:35 放弃,等次日 11:35。
+  intervals_minutes: [30, 60, 60]
   max_attempts_per_layer: 3
-  total_window_hours: 2
+  total_window_hours: 3
```

### 重试时间表(BJT 11:35 master 失败场景)

| 事件 | 时刻 | 距 11:35 |
|---|---|---|
| 主档跑(失败) | 11:35 | 0 |
| Retry 1 | 12:05 | +30 min |
| Retry 2(若 1 失败) | 13:05 | +90 min |
| Retry 3(若 2 失败) | 14:05 | +150 min |
| 放弃(retry_exhausted)| 14:35(实际边界)| +180 min = 3h 整 |
| 次日主档 | 次日 11:35 | +24h |

注:窗口边界严格 `<` 3h(`is_within_window` 用 `< total_window_hours`),
所以 3h 整刚好越界。retry_3 是 14:05,14:35 之前完成 OK。

## ai_retry 配置真被读取的核实

`grep RetryPolicy._load_config src/ai/retry_policy.py:82-90`:
```python
@staticmethod
def _load_config() -> dict[str, Any]:
    if not _BASE_YAML.exists(): return {}
    try:
        with open(_BASE_YAML, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return {}
```

`__init__` 读取(line 64-80):
```python
cfg = self._load_config()
ai_retry = cfg.get("ai_retry") or {}
self.intervals_minutes = (
    intervals_minutes or ai_retry.get("intervals_minutes") or _DEFAULT_INTERVALS_MIN
)
self.max_attempts_per_layer = (
    max_attempts_per_layer or ai_retry.get("max_attempts_per_layer") or _DEFAULT_MAX_ATTEMPTS
)
self.total_window_hours = (
    total_window_hours or ai_retry.get("total_window_hours") or _DEFAULT_WINDOW_HOURS
)
```

✅ **真读 base.yaml**,改 yaml 立即生效;_DEFAULT 仅 yaml 缺 key 时兜底,
不构成"死代码 + yaml 装饰"问题。`test_loads_from_base_yaml_defaults` 测试
本就在校验"yaml 真生效",Sprint F.2 已更新断言到新值。

## 测试更新策略(per 用户指令"直接改具体数字")

### `test_retry_policy.py` 改 11 处:
- `test_backoff_first_attempt_5min` → `_30min`,assert 300 → 1800
- `test_backoff_second_attempt_10min` → `_60min`,assert 600 → 3600
- `test_backoff_third_attempt_20min` → `_60min`(重名 _60min 是 attempt=3),
  assert 1200 → 3600
- `test_backoff_over_max_returns_none`:fixture `[5,10,20]` → `[30,60,60]`
- `test_backoff_uses_last_when_intervals_short`:fixture `[5]` → `[30]`,
  300 → 1800
- 4 个 `test_window_*`:`total_window_hours=2` → `3`,边界 ts 更新
- `test_should_retry_attempt_within_max_and_window`:同
- `test_should_retry_outside_window_no`:11h cutoff → 12h(确保越界)
- `test_loads_from_base_yaml_defaults`:assert `[30,60,60]` + window=3

### `test_jobs_retry.py` 改 2 处:
- `test_with_retry_error_schedules_retry`:expected `delay_sec=600` → `3600`
- `test_with_retry_outside_2h_window` → `_outside_3h_window`:start 3h 前 → 4h 前

## 验收记录

### 本地 pytest

`tests/test_retry_policy.py + test_jobs_retry.py`:31 passed
完整 suite:`1662 passed, 1 skipped, 0 failed`

### 服务器部署

- Fast-forward `bca6240..3b29a8a`
- systemd `is-active = active`
- `grep -A 9 '^ai_retry:' config/base.yaml` 服务器侧确认新配置生效

### 服务器 pytest(F 强制项)

(后台跑中,通常 ~140s,完成后填具体行数)

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1662 passed, 0 failed |
| GitHub push(commit hash:3b29a8a)| ✅ 已 push origin/main |
| 服务器 git pull | ✅ Fast-forward 成功 |
| 服务器 systemctl restart | ✅ is-active = active |
| 服务器 pytest 全 suite | ⏳ 后台跑中(预期同本地 1662 passed) |

## 段 3 同类风险扫描

### 1. 总窗口 3h(11:35-14:35)是否跟下午其他 cron 冲突?

检查 `config/scheduler.yaml` cron 列表:
- `collect_klines_1h`:每整点 :00 → 12:00 / 13:00 / 14:00 落在窗口内,但**不影响**(retry add_job 是独立 date trigger,与 cron 各自独立调度)
- `collect_klines_daily`:补救档 12:01 / 14:01 → 不冲突
- `collect_macro`:06-12 BJT,12:00 是最后一档 → 不冲突
- `collect_onchain`:08:35 / 9:35 / 10:35 → 全在 11:35 之前,不冲突
- 没有其他 16:00 之前的 AI cron(position_health_check Sprint E disabled)

**结论:窗口扩到 3h 与现有 cron 无冲突**。

### 2. APScheduler 重启会不会丢失已排队的 retry?

APScheduler 默认 jobstore 是 memory(`scheduler.add_jobstore` 没显式指定
SQLAlchemyJobStore 等持久化)。retry add_job 用 `trigger="date"`,**memory
jobstore + systemd restart = 已排队 retry 全部丢失**。

**风险评估**:本次 systemd restart 在 BJT ~02:00(用户操作时刻),不在
11:35-14:35 retry 窗口内,**没有 retry 被丢失**。如果以后用户在 11:35-14:35
窗口期间 restart,会丢 retry,但概率低且影响仅"当天 master 失败时不会
自动重试,只能等次日"。**留 Sprint G backlog**,补 jobstore 持久化或加
"启动时检查 strategy_runs 是否有 retry_exhausted=False 但 retry_log
不完整的"逻辑。

### 3. ai_retry 配置真被代码读取(非死代码)

✅ 已核实 — `RetryPolicy._load_config` 直接 open base.yaml;`__init__`
按优先级 `init 参数 > yaml > _DEFAULT_*` 取值。`grep` 确认 yaml 改动 →
RetryPolicy 实例化时立即生效。

### 4. retry 写 strategy_runs.retry_log_json,网页 aiFailureStatus 读它

`grep retry_log_json src/`:
- `src/scheduler/jobs.py`:`job_pipeline_run_with_retry` 末尾把
  retry_log 写入 result(经 _orchestrator_mapper 持久化到
  `strategy_runs.retry_log_json` 列)
- `web/assets/app.js:222-260` `aiFailureStatus()` 读它

新 30/60/60 间隔下,网页"重试中(第 N 次)"红条会比之前持续更久(原来
最长 20min 看到一次,现在最长 60min 一直显示)— 这是**预期行为**,不是 bug,
用户开网页看到红条 30min+ 别误以为系统卡住。

### 5. 没动其他 retry 路径

`grep -rn 'BaseAgent.*retry' src/`:`src/ai/agents/_base.py:_call_ai_with_retry`
是 sub-agent 单调用 2-attempt 即时重试(API 网络抖动用),**与 orchestrator 层
异步重试是不同层**。Sprint F.2 不动它,所以 sub-agent 单次 API 失败仍
立即(50ms-2s)retry 1 次,不受本 sprint 影响。

## 本 sprint 删除清单

**本 sprint 无替代关系,无删除项**(纯配置调整 + 测试断言更新,无代码 / 函数 /
模块替代)。

`git grep '5, 10, 20\|total_window_hours: 2\|total_window_hours=2'` 在
`src/` + `tests/` + `config/` 中应只剩注释 / `_DEFAULT_*` 默认值兜底
(yaml 缺失时才用,不会被生产生效)。
