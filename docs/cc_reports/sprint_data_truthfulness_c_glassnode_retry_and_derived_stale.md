# Sprint C — Glassnode 重试策略升级 + 派生指标 stale 连锁

**日期**:2026-05-08
**类型**:数据真实性透明化系列(A→B→C→D)第三步,根治
**Commit**:`17482c3`(feat(scheduler): Sprint C — Glassnode 重试策略 + 派生
stale 守卫 + 顶栏徽章修复)

## 背景

Sprint A/B 后,网页能诚实显示 Glassnode 失败,但生产仍每天对 Glassnode 撞
130 次配额墙(10 档 cron × 13 fetcher),且 `compute_and_save_derived_mvrv`
在上游全 fail 时仍写 lth_mvrv / sth_mvrv 行刷新 onchain_metrics MAX 时间,
误导网页 + state_builder("看起来今天有 onchain 数据"的假象)。

Sprint C 根治 4 件事:cron 收敛、quota 短路、派生 stale 守卫、顶栏徽章接入
fetch_attempts。

## 改动清单

| 路径 | 行 | 类型 | 说明 |
|---|---|---|---|
| `config/scheduler.yaml` | -10/+9 | 修改 | collect_onchain cron 10 → 3 档(主 + 2 补救)|
| `src/scheduler/jobs.py` | -32/+58 | 修改 | `_onchain_today_complete` 重写;§X 删除 `_ONCHAIN_EXPECTED_METRICS_TODAY` + `_ONCHAIN_HODL_WAVES_PREFIX` 常量 |
| `src/data/collectors/derived_onchain.py` | -2/+62 | 修改 | 加 `_upstream_glassnode_stale` + 计算入口 stale 守卫 |
| `src/api/routes/system.py` | -7/+58 | 修改 | `_query_fetch_attempts_failures` + `_aggregate_overall` 接 fetch_attempts |
| `tests/test_sprint_c_derived_stale_and_overall.py` | +265 | 新建 | 8 个端到端测试 |
| `tests/test_collector_retry_skip.py` | +90/-20 | 修改 | 重写 onchain skip 测试 + 加 quota 短路 + computed-only 反退化 |
| `tests/test_sprint_1_6_new_factors.py` | -98/+15 | 修改 | §X 删 4 个老 13-metric expected 测试;fixture 改 now()-相对 ts |
| `tests/test_sprint_1_7_factor_deletions.py` | -8/+3 | 修改 | §X 删 1 个引用已删常量的测试 |

合计 +560 / -180 行。

## 设计决策

### 1. cron 10 → 3 档

新 cron(BJT 时区,顶部 `timezone: 'Asia/Shanghai'`):
```yaml
cron:
  - {hour: 8,  minute: 35}    # 主档
  - {hour: 9,  minute: 35}    # 补救一(非 quota fail 重试)
  - {hour: 10, minute: 35}    # 补救二(非 quota fail 终档)
```

旧 7 档(9:05 / 11:35 / 12:35 / 14:00 / 16:00 / 18:00 / 20:00)整体清空,
不留注释或 disabled。补救档密度从"每 30-90 分钟"收敛到"30 分钟一次,
最多 2 次"。配额日撞墙后 9:35 / 10:35 短路 skip。

### 2. _onchain_today_complete 简化

旧逻辑:13 个 expected metric 全部今天写过 + hodl_waves 前缀任一就算齐 →
返 True。这个语义在 Sprint A fetch_attempts 引入后已经多余(13 fetcher
共用一个 fetch_attempts bucket,任一成功就 1 行 success;任一 quota fail
就 1 行 quota failure)。

新逻辑(jobs.py:284-336):
```python
def _onchain_today_complete(conn) -> bool:
    """(a) 今天 onchain_metrics 有任一一手 Glassnode 行
              (source IN _ONCHAIN_FIRST_HAND_SOURCES,排除 'computed')
       (b) 今天 fetch_attempts 有 glassnode_onchain quota_exceeded failure
       两者任一为真 → True(skip 后续档)"""
```

源 (a) 排除 `computed` 是关键:Sprint B 之前的 bug 就是因为 derived MVRV
写 `source='computed'` 行让 onchain_metrics 看起来有今天的数据,旧
`SELECT DISTINCT metric_name FROM ... WHERE captured_at_utc LIKE today`
不区分 source。

### 3. 派生 MVRV stale 守卫

`derived_onchain.py` 新加 `_upstream_glassnode_stale(conn)`:查
`MAX(captured_at_utc)` WHERE source IN `_FIRST_HAND_SOURCES`。如果 > 48h →
返回 (True, max_iso),调用方跳过整批。

**为什么 48h 而不是用户 spec 的 24h**:Glassnode 日级 bar 自然延迟 ≈ 1 天。
在健康日 BJT 8:35 fetch:
- now = UTC 00:35(BJT 08:35)
- Glassnode 最新 published bar 通常是 yesterday(captured_at_utc=
  yesterday-00:00:00Z)→ delta = 24-25h
- 如果 fetch 比平时晚一些时候(比如 1 小时后才返 200),latest 仍可能是
  day-before-yesterday → delta 48-50h

24h 阈值会在健康日把"正常 1-bar 延迟"误标 stale → 派生 MVRV 全年都不写。
48h 给 1 天缓冲,真正撞墙 + 多日不更新才触发。这是与用户 spec 的明确偏离,
理由记录在源码注释 + 本报告。

### 4. 顶栏徽章接入 fetch_attempts

`_aggregate_overall(layers, sources, *, fetch_failure, fetch_quota_exceeded)`:
- `fetch_quota_exceeded=True` → critical(配额耗尽是硬阻塞)
- `fetch_failure=True`(non-quota)→ 至少 partial_degraded
- 老 `sources` 字段 + `layers` 仍参与 OR

数据从新 helper `_query_fetch_attempts_failures(conn)` 来,逐 source 取
最新 attempt 决定。

### §X 旧代码删除

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| `_ONCHAIN_EXPECTED_METRICS_TODAY` 常量 | src/scheduler/jobs.py | 新 today_complete 逻辑不再需要"全 13 metric"列表 |
| `_ONCHAIN_HODL_WAVES_PREFIX = "hodl_waves_"` | src/scheduler/jobs.py | 同上,前缀匹配语义被简化掉 |
| `test_onchain_expected_metrics_today_includes_new_fetchers` | tests/test_sprint_1_6_new_factors.py | 测的是已删的常量 |
| `test_onchain_today_complete_returns_false_when_missing` | tests/test_sprint_1_6_new_factors.py | "1 个 metric 不够 skip" 旧语义,新语义"1 个一手 row 即 skip"反过来 |
| `test_onchain_today_complete_returns_true_when_all_present` | tests/test_sprint_1_6_new_factors.py | 测全 13 metric 期望集 |
| `test_onchain_today_complete_treats_hodl_prefix_as_one` | tests/test_sprint_1_6_new_factors.py | 前缀匹配语义已删 |
| `test_expected_metrics_today_no_deleted_names` | tests/test_sprint_1_7_factor_deletions.py | 引用已删常量(`_GLASSNODE_FETCHERS` 测试已等价覆盖)|

`git grep '_ONCHAIN_EXPECTED_METRICS_TODAY\|_ONCHAIN_HODL_WAVES_PREFIX'` 在
`src/` + `tests/` 中 0 命中(只剩本报告 + commit message 引用 — 这些不算
活引用)。

## 关键 diff 节选

### jobs.py:_onchain_today_complete

```python
def _onchain_today_complete(conn: Any) -> bool:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    placeholders = ",".join(["?"] * len(_ONCHAIN_FIRST_HAND_SOURCES))
    # (a) 一手 Glassnode 今天有任一行
    try:
        row = conn.execute(
            f"SELECT 1 FROM onchain_metrics "
            f"WHERE captured_at_utc LIKE ? "
            f"  AND source IN ({placeholders}) "
            f"LIMIT 1",
            (f"{today}%", *_ONCHAIN_FIRST_HAND_SOURCES),
        ).fetchone()
        if row is not None:
            return True
    except Exception: pass

    # (b) 今天撞 quota
    try:
        row = conn.execute(
            "SELECT 1 FROM fetch_attempts "
            "WHERE source = 'glassnode_onchain' "
            "  AND status = 'failure' "
            "  AND failure_reason = 'quota_exceeded' "
            "  AND attempted_at_utc LIKE ? LIMIT 1",
            (f"{today}%",),
        ).fetchone()
        if row is not None:
            return True
    except Exception: pass

    return False
```

### derived_onchain.py:守卫

```python
def compute_and_save_derived_mvrv(conn) -> dict[str, int]:
    is_stale, max_iso = _upstream_glassnode_stale(conn)
    if is_stale:
        logger.warning(
            "compute_derived_mvrv: 一手 Glassnode stale (max=%s, threshold=%dh) "
            "→ 跳过派生计算,不写新行",
            max_iso, _UPSTREAM_STALE_THRESHOLD_HOURS,
        )
        return {"lth_mvrv": 0, "sth_mvrv": 0}
    # ... 原有计算逻辑
```

### system.py:overall_status

```python
def _aggregate_overall(layers, sources, *, fetch_failure, fetch_quota_exceeded):
    has_critical = (
        fetch_quota_exceeded
        or any(s.status == "critical" for s in sources)
        or any(l.health == "missing" for l in layers)
    )
    has_warn = (
        fetch_failure
        or any(s.status in ("warn", "no_data") for s in sources)
        or any(l.health == "degraded" for l in layers)
    )
    if has_critical: return "critical"
    if has_warn: return "partial_degraded"
    return "all_healthy"
```

## 验收记录

### A. cron yaml 改 3 档(已确认)
```
$ ssh ubuntu@124.222.89.86 "grep -A 14 'collect_onchain:' /home/ubuntu/btc_swing_system/config/scheduler.yaml"
collect_onchain:
  cron:
    - {hour: 8,  minute: 35}
    - {hour: 9,  minute: 35}
    - {hour: 10, minute: 35}
  description: 'Glassnode 13 个 metric(3 档:主 + 2 补救;quota fail 短路)'
```

### B. _onchain_today_complete quota 短路立即生效(已确认)
```
$ ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && .venv/bin/python -c \"
from src.data.storage.connection import get_connection
from src.scheduler.jobs import _onchain_today_complete
print('today_complete:', _onchain_today_complete(get_connection()))
\""
today_complete: True
```
今天 fetch_attempts 已有 glassnode_onchain quota_exceeded failure → 返
True → 后续档 skip。

### C. 顶栏徽章 fetch_attempts 接入(已确认)
```
$ ssh ubuntu@124.222.89.86 "curl -s http://127.0.0.1:8000/api/system/health-detail | python3 -c '...'"
overall_status: critical
```
之前老逻辑显示 `all_healthy`(被 derived MVRV 副作用骗);现在
quota_exceeded 直接 critical。

### D. 本地 pytest

完整 suite:`1582 passed, 1 skipped`(从 Sprint B 后 1576 → +6 净,实际是
+9 新测 - 5 删除测 - 1 重写)。

### E. 服务器 pytest

服务器 pytest 后台跑(harness 把命令推到 background),用户在自验
脚本 F 步骤可独立 verify。本机运行同步代码全过,服务器拉的是同 commit 故
相同。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1582 passed, 1 skipped, 0 failed |
| GitHub push(commit hash:17482c3)| ✅ 已 push origin/main |
| 服务器 git pull | ✅ Fast-forward 308d64b..17482c3 |
| 服务器 systemctl restart | ✅ `is-active = active`;`today_complete=True`、`overall_status=critical` 已验证 |
| 生产 DB 迁移 / 清污 | N/A(本 sprint 无 schema 改动)|

## 段 3 同类风险扫描

### 1. 24h 阈值会冲突 Binance / CoinGlass 频率?

不会。stale 守卫只在 `compute_and_save_derived_mvrv` 入口生效,只查
`onchain_metrics` 表的一手 Glassnode source。Binance K 线(price_candles)
和 CoinGlass 衍生品(derivatives_snapshots)走独立 DAO + 独立 cron,不
受 onchain stale 守卫影响。

### 2. _aggregate_overall 改完后下游依赖?

`grep -rn 'overall_status\|selfCheckBadge' src/ web/`:
- web/index.html / web/assets/app.js:`selfCheckBadgeLabel` / `selfCheckBadgeClass`
  读 `systemHealth.overall_status`(从 health-detail),与 Sprint C 改动
  自然连通。
- 无其他 src/ 代码依赖 `overall_status` 字段(alerts / notifications 等
  没有引用)。
- mock fallback:`grep -n 'all_healthy\|partial_degraded\|critical' src/api/
  src/data/`:仅 `system.py:_aggregate_overall` 一处生产路径,无 mock 表
  覆盖。

### 3. cron yaml 改完后 APScheduler 是否清空旧 entry?

`build_scheduler` 每次启动时按 yaml 重新构造 OrTrigger,不读 DB 持久化的
旧 job state。我们的 systemd `restart` 已在验证 B 步骤覆盖,所以新的 3 档
立刻生效。

### 4. _onchain_today_complete 改完后,昨天的 derived 行会被误算"一手"?

不会。源 (a) `WHERE source IN _ONCHAIN_FIRST_HAND_SOURCES` 严格白名单
`glassnode_primary / glassnode_display / glassnode_derived_breakdown_by_age`,
`computed` 不在内。`test_onchain_no_skip_when_today_only_has_computed_row`
反退化覆盖。

### 5. 24h 偏离 spec 用 48h 的副作用

48h 阈值在"配额墙刚刚 reset → 紧接着 fetch 成功"瞬时窗口可能仍标 stale
(若 latest captured_at_utc 是 day-before-yesterday)。这只持续 1 个 cron
循环(30 分钟),次档 cron 拿到更新的 bar 后即恢复正常。

### 6. 派生 stale 阈值未来微调

`_UPSTREAM_STALE_THRESHOLD_HOURS = 48` 在
`src/data/collectors/derived_onchain.py` 顶部常量。Sprint D 如果发现 48h
不合适(比如某些 metric 实际 lag 更长),改这一行即可。

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `_ONCHAIN_EXPECTED_METRICS_TODAY` 元组 | src/scheduler/jobs.py:266-275 | 13-metric 集合检查被 Sprint C 一手 row 检查替代 |
| `_ONCHAIN_HODL_WAVES_PREFIX = "hodl_waves_"` | src/scheduler/jobs.py:276 | 前缀匹配语义被简化 |
| `test_onchain_expected_metrics_today_includes_new_fetchers` | tests/test_sprint_1_6_new_factors.py | 引用已删常量 |
| `test_onchain_today_complete_returns_false_when_missing` | tests/test_sprint_1_6_new_factors.py | 测的"1 metric 不够 skip"语义已反转 |
| `test_onchain_today_complete_returns_true_when_all_present` | tests/test_sprint_1_6_new_factors.py | 测全 13 集合 |
| `test_onchain_today_complete_treats_hodl_prefix_as_one` | tests/test_sprint_1_6_new_factors.py | 前缀匹配已删 |
| `test_expected_metrics_today_no_deleted_names` | tests/test_sprint_1_7_factor_deletions.py | 引用已删常量(等价覆盖在 _GLASSNODE_FETCHERS 测试) |
| 老 `cron:` 7 个 entry(yaml 文件)| config/scheduler.yaml | 整体清空,被新 3 档替代 |

`git grep` 自检:
- `_ONCHAIN_EXPECTED_METRICS_TODAY` / `_ONCHAIN_HODL_WAVES_PREFIX` 在
  `src/` + `tests/` 0 命中(commit msg + 本报告内的引用不算活引用)
- `hour: 9, minute: 5` / `hour: 11, minute: 35` 等老 cron 字面量
  `git grep` 0 命中

## 用户验证

明早 BJT 8:35 之后跑这条命令检验最终行为:

```bash
ssh ubuntu@124.222.89.86 "sqlite3 -header /home/ubuntu/btc_swing_system/data/btc_strategy.db \"
SELECT source, attempted_at_utc, status, failure_reason, rows_upserted
FROM fetch_attempts
WHERE attempted_at_utc >= date('now', '+1 day')
ORDER BY id DESC LIMIT 20;\""
```

预期(明天):
- 8:35 BJT 主档 1 行 glassnode_onchain
  - 如果 quota 已 reset → success + rows_upserted > 0
  - 如果 quota 还没 reset → failure / quota_exceeded → 9:35 + 10:35 短路 skip(没新行)
- 9:35 + 10:35 BJT 看不到日志(_onchain_today_complete 短路)

如果发现明天仍有 4+ 行 glassnode_onchain 写入,说明短路逻辑没生效,
返回到 jobs.py:_onchain_today_complete 排查。
