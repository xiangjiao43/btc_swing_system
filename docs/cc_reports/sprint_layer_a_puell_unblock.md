# Sprint 1.6.2 — Puell 持续失败根治(细粒度 today_complete + 429 拆分 + cron 错峰)

**日期**:2026-05-17
**目标**:把上一份 `sprint_layer_a_puell_root_cause.md` 定位的 3 个独立设计缺陷一次性修掉,让 puell_multiple(以及任何其他 fetcher)单点失败时,后续 cron 档能自动重试单一 fetcher,不再被"任一一手 source 有行就 skip 全 job"的旧逻辑锁死。

---

## 1. 改动文件清单

| 文件 | 改动 |
|---|---|
| [src/scheduler/jobs.py](src/scheduler/jobs.py#L319-L420) | **方案 1B 核心**:删除老的 `_ONCHAIN_FIRST_HAND_SOURCES` 白名单;新增 `_FETCHER_TO_REPRESENTATIVE_METRIC` 字典(22 个 fetcher → 代表 metric 一一映射,hodl_waves 特例用 `hodl_waves_more_10y`);新增 `_fetcher_completed_today()` per-fetcher 完整性检查;新增 `_truly_quota_exceeded_today()`(真月度配额短路);重写 `_onchain_today_complete()` → 22 个 fetcher 全部代表 metric 都今天有行才 True。`job_collect_onchain` 内部循环:每个 fetcher 跑前检查 `_fetcher_completed_today` → True 就 skip 不浪费 HTTP。返回 payload 加 `fetcher_fetched_count` / `fetcher_skipped_count` 诊断字段。`fetched_count == 0` 时不写 `fetch_attempts`(无真正 fetch) |
| [src/data/collectors/_classify_failure.py](src/data/collectors/_classify_failure.py#L80-L90) | **方案 2**:拆 429。规则反转 — 先看正文关键字(quota / rate limit / 配额 / ratelimit)→ `quota_exceeded`(真配额,触发短路);否则裸 429 → `rate_limited`(新增 reason,瞬时限流,不触发短路、可重试)。下游 `_truly_quota_exceeded_today` 只匹配 `failure_reason='quota_exceeded'` → 自然兼容,瞬时限流不再误触发整 job 短路 |
| [src/data/freshness.py](src/data/freshness.py#L84) | `_FAILURE_REASON_LABELS` 新增 `"rate_limited": "瞬时限流"`,健康面板显示真实原因 |
| [config/scheduler.yaml](config/scheduler.yaml#L100-L114) | **方案 3 错峰**:`collect_onchain` cron 从 `08:35 / 09:35 / 10:35` 改为 `09:30 / 10:30`(= UTC 01:30 / 02:30,避开 00:00-01:00 UTC Glassnode daily refresh 高峰)。3 档收敛到 2 档:per-fetcher skip 让 2 档够用 |
| [tests/test_collector_retry_skip.py](tests/test_collector_retry_skip.py#L224-L341) | 旧 `test_onchain_skip_when_today_has_first_hand_row`(老语义)→ 改名为 `test_onchain_partial_today_keeps_other_fetchers_running` + 重写断言:整 job 不 skip,GlassnodeCollector 被实例化,1 fetcher 命中 per-fetcher skip(`fetcher_skipped_count=1`),其他 21 个被 fetch(`fetcher_fetched_count=21`)。**新增** `test_onchain_skip_when_all_fetchers_completed_today`:种全部 22 个代表 metric → 整 job skip,collector 0 次实例化。旧 `test_onchain_no_skip_when_today_only_has_computed_row`(老 source 白名单语义)→ 改名为 `test_onchain_today_complete_false_when_any_fetcher_missing` + 重写为 puell 缺时 `_onchain_today_complete` 返 False、`_fetcher_completed_today` 单 fetcher 粒度断言 |
| [tests/test_classify_fetch_failure.py](tests/test_classify_fetch_failure.py#L34-L65) | 旧 `test_http_429_classified_as_quota`(裸 429 → quota)→ 改为 `test_http_429_bare_classified_as_rate_limited`(裸 429 → rate_limited)。**新增** `test_http_429_with_quota_keyword_in_body_classified_as_quota`(429 + 正文带 quota 关键字仍归 quota)。中文/英文 "配额" / "rate limit" 关键字测试保持原断言不变 |
| [tests/test_collector_retry_skip.py:469-484](tests/test_collector_retry_skip.py#L469-L484) | OrTrigger 子触发器数量 `collect_onchain: 3 → 2`(配套 yaml 改动)|
| [tests/test_scheduler_2_7_a_cron.py:127-135](tests/test_scheduler_2_7_a_cron.py#L127-L135) | `test_collect_onchain_at_0835_bjt` → 重命名 `test_collect_onchain_cron_offpeak_at_0930_1030_bjt` + 断言新错峰时间 |

## 2. 设计决策记录

### 2.1 为什么用"代表 metric" 而不是"全部 22 metric 都今天有行"

每个 fetcher 写一个或多个 metric。绝大多数 fetcher 写**1 个 metric**(fetch_mvrv_z_score → mvrv_z_score 一条)。例外是 `fetch_hodl_waves` 一次拉 12 个 bucket(hodl_waves_24h / hodl_waves_1d_1w / ... / hodl_waves_more_10y),要么全部成功要么全部失败(同一 HTTP 响应解出来)。

代表 metric 选择:
- 21 个 fetcher 用规则 `metric_name == fetcher_name[len("fetch_"):]` 一一对应
- `fetch_hodl_waves` 特例:选 `hodl_waves_more_10y` 作代表(长尾 bucket,真实 endpoint 成功的话一定有)

这避免了"22 个 fetcher 写 33 个 metric,只要其中任一 metric 有就算 fetcher 完成"的复杂性。语义清晰:每个 fetcher 1 个代表 metric,查到 = fetcher 今天跑过。

### 2.2 为什么把 _truly_quota_exceeded_today 单拆,而不是直接在 _onchain_today_complete 里检

两层语义:
- **真 quota_exceeded** → 整 job skip(不再浪费 HTTP,因为已撞月度墙)
- **22 fetcher 全 complete** → 整 job skip(已无事可做)

两层用不同 SQL,分开 helper 更清晰 + 单测可分别 patch。

### 2.3 _classify_failure 反转规则:先看关键字而非先看状态码

旧逻辑:`if status == 429 or _has_quota_keyword(raw): return "quota_exceeded"` — **优先级一致**,只要任一命中就归 quota。
新逻辑:**先**看正文关键字(更精确),没关键字才看状态码:
- 关键字命中 → quota_exceeded(真月度,即使不是 429 也归;比如 alphanode 返 200 但 body 是 "您的配额已用尽")
- 否则 429 → rate_limited(瞬时,可重试)
- 否则状态码精确分类(401/403/404/5xx/4xx)

### 2.4 为什么 cron 从 3 档改 2 档

旧 3 档(08:35 / 09:35 / 10:35)同时撞 daily refresh 高峰 + 锁死在 today_complete 旧逻辑下"任一档成功后续就 skip"。修复后,per-fetcher skip 让"成功的不重抓、失败的下档自动 retry",2 档(错峰后)足够;3 档反而冗余浪费 cron 调度。如果未来 alphanode 高峰变更或单 fetcher 失败概率上升,加第 3 档简单。

---

## 3. 测试覆盖(用户特别要求的两场景)

### 场景 A — "21 个成功 1 个失败时后续档确实会重试那 1 个"
- 测试:`test_onchain_partial_today_keeps_other_fetchers_running`
- 模拟:第一档已写 mvrv_z_score 一行(代表 fetch_mvrv_z_score 完成),其他 21 个代表 metric 全部缺失。模拟第二档 cron 触发。
- 断言:整 job 不 skip ✅;`fetch_mvrv_z_score` 不被调(per-fetcher skip)✅;其他 21 个被调(`fetcher_fetched_count == 21`)✅;`fetcher_skipped_count == 1` ✅

### 场景 B — "全部成功时后续档正常 skip 不浪费调用"
- 测试:`test_onchain_skip_when_all_fetchers_completed_today`
- 模拟:种 22 个 fetcher 全部代表 metric 今天的行。模拟下一档 cron 触发。
- 断言:`result["status"] == "skipped"` ✅;**`GlassnodeCollector` 0 次实例化**(0 HTTP 浪费)✅;`reason` 含 "today" ✅

### 配套测试
- `test_onchain_today_complete_false_when_any_fetcher_missing`:种 21 个、puell 缺 → `_onchain_today_complete()` 返 False;`_fetcher_completed_today("fetch_puell_multiple")` 返 False、`_fetcher_completed_today("fetch_mvrv_z_score")` 返 True
- `test_http_429_bare_classified_as_rate_limited`:裸 429 → rate_limited(不再误归 quota)
- `test_http_429_with_quota_keyword_in_body_classified_as_quota`:429 + 正文 quota 字样 → 仍归 quota(真配额边界保留)
- `test_collect_onchain_cron_offpeak_at_0930_1030_bjt`:yaml cron 时间正确
- `test_or_trigger_registers_all_cron_times`:OrTrigger 子触发器数量改 2

## 4. 测试结果

```
.venv/bin/python -m pytest --tb=line -q
1 failed, 1878 passed, 1 skipped, 672 warnings in 46.97s
```

- 1878 通过(比上一 sprint +3,因新增 3 个测试)
- 唯一失败 `test_collect_klines_1h_kline_succeeds_derivatives_fail`:多次 sprint 报告记录过的上游遗留(commit `16cad4f` `_classify_failure` 改 `api_error` → `provider_error` 后未同步更新断言),与本次完全无关

## 5. 上线后预期效果

### 5.1 puell_multiple 解锁路径

1. 服务器 git pull + systemctl restart 后,APScheduler 重读 yaml,采用新 09:30 / 10:30 cron
2. **次日 09:30 BJT(= 01:30 UTC)** 第一档触发(已避开 00:35 UTC 高峰)
3. 22 个 fetcher 全跑(_fetcher_completed_today 都返 False,因为是当天第一次)
4. 假设 puell 仍失败(罕见 — alphanode 现在测正常),其他 21 个 fetcher 成功
5. **10:30 第二档**:`_onchain_today_complete()` 返 False(puell 代表 metric 今天没行)→ 整 job 不 skip
6. 循环 22 fetcher:21 个命中 per-fetcher skip(代表 metric 今天有行)→ skipped_count=21;**只 puell 真正调 fetch_puell_multiple**(fetched_count=1)
7. puell 这次大概率成功(错峰 + alphanode 高峰已过)→ 整天补救完毕

**HTTP 用量**:正常情况下每天 ~22 HTTP(主档全跑成功),补救档 0 HTTP。puell 失败时主档 22 + 补救档 1 = 23 HTTP/天;月用量 ~690-720,**远低于 1700 配额**。

### 5.2 健康面板诚实化

之前任何 429 都显示"配额耗尽 critical",误导用户以为续费没生效。现在:
- 真配额(正文带 quota 关键字)→ 仍 critical
- 瞬时限流(裸 429)→ warn(后续档自动重试,通常下档就好)

## 6. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(1878 通过 + 1 上游遗留 + 1 skipped;3 个新测试覆盖用户要求的两场景)|
| GitHub 推送 | ❌ 本报告完后立即 commit + push |
| 服务器 git pull | ❌ 待用户执行 |
| 服务器 systemctl restart | ❌ **必需** — APScheduler 启动时一次性读 yaml,不重启不会用新 cron 时间。restart 后下次 09:30 BJT 自动触发新流程 |
| 生产 DB schema 迁移 | N/A(纯逻辑修复,无 schema 改动)|

## 7. 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `_ONCHAIN_FIRST_HAND_SOURCES` tuple(3 项)| `src/scheduler/jobs.py:319-323`(旧)| Sprint C 的"任一一手 source 有行就 skip 全 job"语义被推翻,白名单不再用到 |
| `_onchain_today_complete` 内基于 `source IN ...` 的 (a) 分支查询(20 行)| `src/scheduler/jobs.py:340-360`(旧)| 替换为细粒度循环 |
| 裸 429 → quota_exceeded 的一刀切逻辑 | `_classify_failure.py:80` 旧 `if status == 429 or _has_quota_keyword(raw)` | 替换为先看关键字再看状态码 |
| 旧 cron `08:35 / 09:35 / 10:35` 3 档(撞 daily refresh 高峰)| `config/scheduler.yaml:107-110`(旧)| 替换为错峰 `09:30 / 10:30` 2 档 |
| 测试 `test_onchain_no_skip_when_today_only_has_computed_row` 老 source 语义 | `tests/test_collector_retry_skip.py` 旧 | 替换为 `test_onchain_today_complete_false_when_any_fetcher_missing`(新 fetcher 粒度语义)|
| 测试 `test_onchain_skip_when_today_has_first_hand_row` 老语义 | 同上 | 替换为 `test_onchain_partial_today_keeps_other_fetchers_running`(新行为)|

**自检 `git grep`**:
- `git grep "_ONCHAIN_FIRST_HAND_SOURCES"` 在 src/ tests/ = 0 ✅
- `git grep "first_hand_row"` = 0(测试名也删干净)
- `git grep "rate_limited"` 在 src/ tests/ docs/ = 多处(新增的正向引用),包含 `freshness.py` 标签、`_classify_failure.py` 注释、新测试

## 8. 风险提示

1. **`_fetcher_completed_today` 对未在映射表里的 fetcher 返 False**(保守) — 新加 fetcher 时,如果不更新 `_FETCHER_TO_REPRESENTATIVE_METRIC`,该 fetcher 永远不会被 per-fetcher skip,会每档都被重抓(+ HTTP 浪费但语义正确)。新加 fetcher 时要同步加映射条目。
2. **真月度配额耗尽场景仍由 `_truly_quota_exceeded_today` 短路**,但分类前提是 alphanode/Glassnode 在错误正文里写出 quota / 配额 / rate limit 字样。如果某天 alphanode 真月度配额耗尽但返裸 429 不带任何关键字 → 会被分类为 rate_limited → 后续档继续 retry → 直到全 22 fetcher 都裸 429 → 仍然不会触发 quota 短路。**这种边界情况下系统会做 22-66 次无效重试**,但不会真撞数据完整性。
3. **生产 DB 旧 `failure_reason='quota_exceeded'` 行不变**(历史 fetch_attempts 已记的不会被回写)。`_truly_quota_exceeded_today` 仍可能匹配到历史那些误归 quota 的行 → 但只在当天 attempted_at_utc 才匹配,跨天自动失效。所以**今天之内,如果服务器之前有过误归 quota 的失败行**,可能造成今天整 job 被短路一次。**手动修复方案**:服务器上 `sqlite3 ... "UPDATE fetch_attempts SET failure_reason='rate_limited' WHERE source='glassnode_onchain' AND failure_reason='quota_exceeded' AND attempted_at_utc LIKE date('now')||'%';"`,但这只在极端情况下需要,默认不做。
