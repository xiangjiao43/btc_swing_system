# fix_glassnode_health_status_stale_failure_display

## 1. 任务目标

修复系统自检中 Glassnode 仍显示“配额用尽 / 抓取失败”的问题。

本轮重点不是判断 UI 文案，而是从 collector、`fetch_attempts`、实际链上数据入库、API freshness 聚合、前端显示链路查真实原因，并修正健康聚合逻辑。

本轮没有改 Layer A / Layer B 策略逻辑，没有改交易逻辑，没有跑完整 AI pipeline，没有真实交易。

## 2. 读取文件

- `AGENTS.md`
- `scripts/check_glassnode_health.py`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/_classify_failure.py`
- `src/data/freshness.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `src/pipeline/state_builder.py`
- `src/api/routes/strategy.py`
- `src/api/routes/data_sources.py`
- `web/assets/app.js`
- `web/index.html`
- `tests/test_classify_fetch_failure.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/test_api_data_sources_freshness.py`
- `tests/test_sprint_d_freshness_and_stale.py`
- `tests/test_collector_retry_skip.py`
- `docs/codex_reports/audit_glassnode_quota_failure_root_cause.md`

## 3. 当前网页“配额用尽”来源链路

完整链路如下：

1. Glassnode collector 在 `src/data/collectors/glassnode.py` 中请求多个 endpoint。
2. `src/scheduler/jobs.py::job_collect_onchain` 对所有 Glassnode fetcher 逐个运行。
3. 如果其中某个 endpoint 失败，`gn_first_exc` 会保留第一个异常。
4. job 结束时 `_record_fetch_attempt(...)` 写入一条 bucket 级别 `fetch_attempts`：
   - source = `glassnode_onchain`
   - status = `failure`
   - failure_reason = `quota_exceeded`
   - rows_upserted = 成功写入行数
5. `src/data/freshness.py::compute_source_freshness` 读取最新 `fetch_attempts`。
6. `/api/data_sources/freshness` 返回 `failure_reason_label`。
7. `web/index.html` + `web/assets/app.js` 在系统自检数据源列显示：
   - `display_name`
   - `failure_reason_label`
   - `sourceAgeLabel(src)`

所以网页显示“Glassnode 链上 / 配额用尽 / 2.7 小时前抓取失败”的直接原因是：最新一条 `fetch_attempts` 被标为 `failure + quota_exceeded`。

## 4. 对应旧失败记录详情

只读查询生产服务器 `/home/ubuntu/btc_swing_system/data/btc_strategy.db`：

```text
id: 429
source: glassnode_onchain
attempted_at_utc: 2026-05-15T00:36:04.578768Z
status: failure
failure_reason: quota_exceeded
rows_upserted: 869
duration_ms: 64556
error endpoint: /v1/metrics/indicators/puell_multiple
error summary: HTTP 429 on puell_multiple
```

关键点：

- 这条记录不是“整个 Glassnode 都失败”。
- 同一轮实际已经写入 `rows_upserted=869` 行链上数据。
- 失败集中在 `puell_multiple` 这类单个 endpoint。
- 旧聚合逻辑只看 `status=failure`，没有区分“全失败”和“部分成功”。

## 5. 最近成功数据

生产库里多项 Glassnode 指标在同一轮有新数据：

| metric | latest_inserted | latest_captured |
|---|---|---|
| hodl_waves_more_10y | 2026-05-15T00:36:04Z | 2026-05-14 |
| cdd | 2026-05-15T00:36:03Z | 2026-05-14 |
| ssr | 2026-05-15T00:36:02Z | 2026-05-14 |
| exchange_balance | 2026-05-15T00:35:13Z | 2026-05-14 |
| percent_supply_in_profit | 2026-05-15T00:35:12Z | 2026-05-14 |
| mvrv | 2026-05-15T00:35:06Z | 2026-05-14 |
| exchange_net_flow | 2026-05-15T00:35:05Z | 2026-05-14 |
| nupl | 2026-05-15T00:35:03Z | 2026-05-14 |
| mvrv_z_score | 2026-05-15T00:35:02Z | 2026-05-14 |

这说明系统自检不应把整个 Glassnode 源显示成“配额用尽 / 抓取失败”。

## 6. 最新 Glassnode health check 结果

运行生产服务器命令：

```bash
.venv/bin/python scripts/check_glassnode_health.py
```

脱敏结果：

| metric | endpoint | status | latest_value_present |
|---|---|---:|---:|
| mvrv | `/v1/metrics/market/mvrv` | ok | true |
| lth_sopr | `/v1/metrics/indicators/sopr_more_155` | ok | true |
| reserve_risk | `/v1/metrics/indicators/reserve_risk` | ok | true |

额外只读检查最近失败 endpoint：

| metric | endpoint | status | latest_value_present |
|---|---|---:|---:|
| puell_multiple | `/v1/metrics/indicators/puell_multiple` | ok | true |

结论：当前 Glassnode API 可访问，不能继续显示为整体“配额用尽”。

## 7. 是否真的是配额用尽

不是整体配额用尽。

更准确的情况是：

1. 某一次 Glassnode bucket 采集里，`puell_multiple` endpoint 当时返回了 `HTTP 429`。
2. 但同一轮其他 Glassnode endpoint 成功写入了 869 行数据。
3. 旧系统把 bucket 级别状态显示成 `failure + quota_exceeded`。
4. 前端据此显示“Glassnode 链上 / 配额用尽 / 抓取失败”。

也就是说，旧显示把“单点 endpoint 异常”扩大成“整个 Glassnode 链上数据源失败”。

## 8. 修复的 aggregation 规则

修改 `src/data/freshness.py`：

1. 新增 `partial` 状态。
2. 最新 attempt 是 failure，但 `rows_upserted > 0` 且数据不 stale：
   - 显示 `partial`
   - 中文标签显示“部分异常”
   - 保留原始 `failure_reason` 和 `error_message` 给 tooltip / 审计用
3. 最新 attempt 是 failure，但失败之后已有更新的一手数据：
   - 显示 `success`
   - 不让旧失败继续污染当前系统自检
4. `last_success_at_utc` 在 failure 时不再只看历史 `fetch_attempts success`，而是和真实数据表 fallback 取更新者。

## 9. 修复的前端文案规则

修改 `web/assets/app.js` 和 `web/index.html`：

1. `partial` 显示 amber 状态，而不是红色失败。
2. `partial` 年龄显示为：
   - `X 分钟前部分异常`
   - `X 小时前部分异常`
3. 系统自检显示“部分异常” badge。
4. 只有真实 `quota_exceeded` 且整体 failure 时，才保持红色“配额用尽”。

## 10. 修复 onchain skip 规则

修改 `src/scheduler/jobs.py`：

旧逻辑：

- 今天只要有 `glassnode_onchain + quota_exceeded` 失败，就跳过后续链上采集。

新逻辑：

- 只有 `quota_exceeded` 且 `rows_upserted=0`，才视为全源 quota，才跳过后续采集。
- 如果 `rows_upserted > 0`，说明是部分成功，不阻止后续重试。

这避免一条部分失败记录让当天后续 Glassnode 采集一直被跳过。

## 11. 是否影响原始数据因子

不影响。

本轮没有修改原始数据因子的数值、plain_reading、抓取时间、factor_coverage 或 Layer A / Layer B 输入逻辑。

各因子自己的状态仍然独立展示。

## 12. 测试命令和结果

```bash
uv run pytest -q tests/test_classify_fetch_failure.py tests/test_api_data_sources_freshness.py tests/test_sprint_d_freshness_and_stale.py tests/test_collector_retry_skip.py
```

结果：68 passed。

```bash
uv run pytest -q tests/test_web_modules_4_5_rp_failure.py tests/test_web_modules_1_2_3.py tests/web_helpers/test_normalize_state.py
```

结果：139 passed。

## 13. 是否影响高风险区域

- 是否影响 Layer A：否。
- 是否影响 Layer B：否。
- 是否影响原始数据因子：否。
- 是否影响虚拟账户：否。
- 是否影响真实交易：否。
- 是否跑完整 pipeline：否。
- 是否清空数据库：否。

## 14. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 路径 / 位置 | 原因 |
|---|---|---|
| “只要 latest fetch_attempts=failure 就全源失败”的旧显示假设 | `src/data/freshness.py` | 会把部分成功的 Glassnode 采集误显示为全源配额用尽 |
| “今日 quota 失败即跳过后续链上采集”的旧判断 | `src/scheduler/jobs.py` | 未区分 rows_upserted=0 的全失败和 rows_upserted>0 的部分成功 |

## 15. 风险和未完成

1. 历史 DB 里的旧 `fetch_attempts` 行不会被改写；本轮是让 API 聚合和前端显示时正确解释它。
2. `fetch_attempts` 仍是 bucket 级别记录，不是 endpoint 级别记录。后续若要更精细，可以新增 endpoint-level 失败摘要。
3. 生产网页需要服务器 pull + restart 后才会使用新聚合规则。

## 16. 用户后续命令

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
sudo systemctl restart btc-strategy.service
```

如需刷新数据源状态，可运行：

```bash
.venv/bin/python scripts/check_glassnode_health.py
```

本轮不需要跑完整 pipeline。

刷新网页：

```text
http://124.222.89.86/
```

## 17. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待提交后填写 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

