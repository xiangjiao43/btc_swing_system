# fix_glassnode_partial_health_detail_and_recovery

## 1. 任务目标

修复 Glassnode 系统自检“部分异常”不够具体的问题，并让已经恢复的 endpoint 不再长期污染 source health。

本轮不改 Layer A / Layer B 策略逻辑，不改交易逻辑，不跑完整 pipeline，不清空数据库，不泄露 key。

## 2. 读取文件

- `AGENTS.md`
- `scripts/check_glassnode_health.py`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/_classify_failure.py`
- `src/data/freshness.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `src/api/models.py`
- `src/api/routes/data_sources.py`
- `web/assets/app.js`
- `web/index.html`
- `tests/test_api_data_sources_freshness.py`
- `tests/test_classify_fetch_failure.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`
- `docs/codex_reports/fix_glassnode_health_status_stale_failure_display.md`

## 3. 具体异常 metric

生产只读查询确认，旧失败记录的异常来自：

- metric：`puell_multiple`
- 展示名：`Puell Multiple`
- endpoint：`/v1/metrics/indicators/puell_multiple`
- HTTP status：`429`
- source：`glassnode_onchain`
- rows_upserted：`869`

这说明当时并不是整个 Glassnode 失败，而是 `puell_multiple` 单点 endpoint 异常。

## 4. 失败 endpoint

失败 endpoint：

```text
/v1/metrics/indicators/puell_multiple
```

旧错误摘要：

```text
HTTP 429 on puell_multiple
```

或者完整 collector 错误里包含：

```text
https://api.alphanode.work/v1/metrics/indicators/puell_multiple
```

本轮新增了解析逻辑，同时兼容完整 endpoint 和短格式 `HTTP 429 on puell_multiple`。

## 5. 失败 HTTP status

失败 HTTP status 是 `429`。

显示规则保持：

- `429`：限流 / 配额相关
- `403`：权限不足 / 套餐不支持
- `404`：接口不存在 / 配置错误
- `timeout`：请求超时
- `unknown`：抓取失败

## 6. 是否已经恢复

当前 health check 已显示：

- `mvrv` ok
- `lth_sopr` ok
- `reserve_risk` ok
- `puell_multiple` ok

因此当前 `puell_multiple` endpoint 已恢复。

本轮修改 `scripts/check_glassnode_health.py`：

- 默认加入 `puell_multiple` 检查。
- 将脱敏检查结果写入：

```text
~/pipeline_logs/glassnode_health_check_latest.json
```

后端 freshness 聚合会读取这个文件。如果健康检查时间晚于旧失败时间，且对应 metric / endpoint 为 ok，就把 source health 恢复为 `success`，不再让旧失败污染系统自检主状态。

## 7. 为什么之前显示部分异常

上一轮已经把“全源失败”修成了“部分异常”，原因是：

- 最新 `fetch_attempts` 是 failure。
- 但 `rows_upserted=869`，说明同轮已有大量成功数据。

旧问题是：虽然能显示“部分异常”，但不告诉用户是哪一个 endpoint 出问题，也没有 health check 恢复机制。

## 8. 修复后的显示逻辑

### 8.1 partial detail

`/api/data_sources/freshness` 为数据源新增 detail 字段：

- `display_label`
- `main_failure_metric`
- `main_failure_metric_label`
- `main_failure_endpoint`
- `main_failure_http_status`
- `main_failure_age_label`
- `latest_success_after_failure`
- `recovered`

例如 partial 时可返回：

```json
{
  "status": "partial",
  "display_label": "部分异常：Puell Multiple 429",
  "main_failure_metric": "puell_multiple",
  "main_failure_endpoint": "/v1/metrics/indicators/puell_multiple",
  "main_failure_http_status": 429
}
```

### 8.2 recovered

如果后续正式采集或 health check 已经证明这个 endpoint ok：

- `status` 恢复为 `success`
- `recovered=true`
- 旧失败只保留在 detail / tooltip 审计字段，不作为主状态

### 8.3 前端显示

系统自检数据源列：

- partial 显示具体文案，如 `部分异常：Puell Multiple 429`
- tooltip 显示 metric、endpoint、HTTP status、失败时间
- recovered 后显示正常，不再黄/红

## 9. 改动文件

- `scripts/check_glassnode_health.py`
- `src/data/freshness.py`
- `src/api/models.py`
- `src/api/routes/data_sources.py`
- `web/assets/app.js`
- `web/index.html`
- `tests/test_api_data_sources_freshness.py`
- `tests/test_sprint_d_freshness_and_stale.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `docs/codex_reports/fix_glassnode_partial_health_detail_and_recovery.md`

## 10. 测试命令和结果

```bash
uv run pytest -q tests/test_api_data_sources_freshness.py tests/test_classify_fetch_failure.py tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：169 passed。

```bash
uv run pytest -q tests/test_sprint_d_freshness_and_stale.py tests/test_collector_retry_skip.py
```

结果：39 passed。

## 11. 是否影响策略逻辑

- 是否影响 Layer A 策略逻辑：否。
- 是否影响 Layer B 策略逻辑：否。
- 是否影响原始数据因子：否。
- 是否影响虚拟账户：否。
- 是否影响真实交易：否。

## 12. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 路径 / 位置 | 原因 |
|---|---|---|
| 泛泛“部分异常”但无 metric / endpoint / HTTP detail 的显示方式 | `src/data/freshness.py`、`web/index.html` | 用户无法判断具体异常来源 |
| health check 只打印不留恢复证据的旧方式 | `scripts/check_glassnode_health.py` | 后端无法知道旧 endpoint 是否已恢复 |

## 13. 风险和未完成

1. health check 缓存不是数据库记录，只是 `~/pipeline_logs/glassnode_health_check_latest.json`。如果服务器重建或文件删除，恢复判断会回到 DB / 正式采集记录。
2. 目前仅对已知 Glassnode metric 做 endpoint 推断映射；未知 metric 仍会尽量从错误文本解析。
3. 更长期的理想方案是记录 endpoint-level fetch_attempts，而不是 source bucket 级别一条记录。

## 14. 用户后续命令

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

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待提交后填写 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

