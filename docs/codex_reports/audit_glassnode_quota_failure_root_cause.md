# audit_glassnode_quota_failure_root_cause

## 1. 任务目标

只读审计并低风险修复网页系统自检中 Glassnode 显示“配额用尽”的根因，重点确认这是否真的来自 Glassnode quota，而不是代码把其他错误误映射成 quota。

本轮不改 Layer A / Layer B 策略逻辑，不改交易逻辑，不跑完整 pipeline，不触碰真实交易。

## 2. 读取文件

- `AGENTS.md`
- `config/data_sources.yaml`
- `config/data_catalog.yaml`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/_classify_failure.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `src/data/freshness.py`
- `src/pipeline/state_builder.py`
- `src/ai/spot_cycle_context_builder.py`
- `src/api/routes/data_sources.py`
- `src/api/routes/strategy.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_classify_fetch_failure.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/test_sprint_c_derived_stale_and_overall.py`
- `tests/test_collector_retry_skip.py`

## 3. UI “配额用尽”字段来源

网页这句：

`Glassnode 链上 / 配额用尽 / 2.3 小时前抓取失败`

来源链路如下：

1. `src/data/collectors/glassnode.py`
   - Glassnode collector 请求 endpoint。
   - 非 200 响应会抛出类似 `HTTP 403 ...`、`HTTP 404 ...`、`HTTP 429 ...` 的异常。

2. `src/scheduler/jobs.py`
   - collector job 捕获异常。
   - `_record_fetch_attempt(...)` 调用 `classify_fetch_failure(first_exc)`。
   - 分类结果写入 `fetch_attempts.failure_reason`。

3. `src/data/freshness.py`
   - `compute_source_freshness(...)` 读取最新 `fetch_attempts`。
   - `_FAILURE_REASON_LABELS` 把 `quota_exceeded` 映射成中文“配额用尽”。

4. `src/api/routes/data_sources.py`
   - `/api/data_sources/freshness` 返回 `failure_reason_label`。

5. `web/assets/app.js` + `web/index.html`
   - 前端显示 `src.display_name`、`src.failure_reason_label`、`sourceAgeLabel(src)`。
   - 所以如果后端给的是 `failure_reason=quota_exceeded`，网页就会显示“配额用尽”。

## 4. 真实根因判断

本轮发现旧分类逻辑存在误判：

```python
if status in (403, 429) or _has_quota_keyword(raw):
    return "quota_exceeded", msg
```

这意味着：

- HTTP 429：确实可能是限流 / 配额。
- HTTP 403：更常见含义是套餐不支持、endpoint 权限不足、认证权限不够。
- 旧代码把 HTTP 403 也显示为“配额用尽”，这是不准确的。

因此，网页显示“配额用尽”不一定代表真实 quota exhausted；很可能是某个 Glassnode endpoint 返回 403 后被错误映射。

## 5. 最近失败状态可见性

本地 SQLite `fetch_attempts` 表为空，无法从本地 DB 还原生产最近一次 Glassnode 失败的 HTTP code。

直接访问生产 `/api/data_sources/freshness` 和 `/api/system/health` 返回 Basic Auth 保护，当前本地环境无法直接读取生产最新失败行。

因此，本轮不能声称已经看到生产最近失败的原始 HTTP code。能确认的是：代码层存在 403 → quota 的误分类 bug，且这条链路足以解释网页误显示“配额用尽”。

## 6. Glassnode 最小健康检查结果

运行命令：

```bash
uv run python scripts/check_glassnode_health.py
```

脱敏结果摘要：

| metric | endpoint | status | latest_value_present |
|---|---|---:|---:|
| mvrv | `/v1/metrics/market/mvrv` | ok | true |
| lth_sopr | `/v1/metrics/indicators/sopr_more_155` | ok | true |
| reserve_risk | `/v1/metrics/indicators/reserve_risk` | ok | true |

配置摘要：

- base_url host：`https://api.alphanode.work`
- API key：`exists, hidden`
- timeout：15 秒

结论：当前配置下至少这 3 个 Glassnode endpoint 可正常访问。它们能返回数据，所以“Glassnode 当前整体配额用尽”这个判断不成立。

## 7. 哪些 endpoint 成功 / 失败

本轮实际最小检查成功：

- `mvrv`
- `lth_sopr`
- `reserve_risk`

本轮没有发现这 3 个 endpoint 失败。

仍无法确认生产 UI 当时对应的是哪个 endpoint 失败，因为当前生产 API 需要认证，本地 DB 没有最近 `fetch_attempts` 行。

## 8. 是否真的 quota exhausted

当前证据不支持“整体配额用尽”。

更准确的判断：

- 如果真实 HTTP status 是 429，才应显示“限流 / 配额用尽”。
- 如果真实 HTTP status 是 403，应显示“套餐不支持 / 权限不足”。
- 如果真实 HTTP status 是 404，应显示“接口不存在 / 配置错误”。
- 如果是 timeout，应显示“请求超时”。

旧代码会把 403 误显示为“配额用尽”，这是本轮确认的主要问题。

## 9. 本轮修复

### 9.1 错误分类

修改 `src/data/collectors/_classify_failure.py`：

- `401` → `auth_error`
- `403` → `permission_denied`
- `404` → `endpoint_not_found`
- `429` 或 quota/rate-limit 文案 → `quota_exceeded`
- `5xx` → `provider_error`
- `requests.Timeout` → `timeout`
- 其他网络异常 → `network_error`

### 9.2 中文显示文案

修改 `src/data/freshness.py`：

- `auth_error` → `API key 无效 / 未授权`
- `permission_denied` → `套餐不支持 / 权限不足`
- `endpoint_not_found` → `接口不存在 / 配置错误`
- `provider_error` → `服务异常`
- `timeout` → `请求超时`

只有 `quota_exceeded` 继续显示为“配额用尽”。

### 9.3 前端 badge

修改 `web/assets/app.js`：

- `quota_exceeded` 仍保留红色严重提示。
- `auth_error` / `permission_denied` / `endpoint_not_found` / `provider_error` / `timeout` 显示为 amber warning。

### 9.4 健康检查脚本

新增 `scripts/check_glassnode_health.py`：

- 使用项目当前 Glassnode 配置。
- 不输出 API key。
- 只测 3 个低成本 endpoint。
- 输出脱敏 JSON。

## 10. 删除清单 / 废弃清单

| 删除 / 废弃对象 | 路径 / 位置 | 原因 |
|---|---|---|
| 403 归类为 `quota_exceeded` 的旧假设 | `src/data/collectors/_classify_failure.py`、`tests/test_classify_fetch_failure.py` | 403 不等于配额用尽，可能是套餐或 endpoint 权限问题 |

## 11. 测试命令和结果

```bash
uv run pytest -q tests/test_classify_fetch_failure.py tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：157 passed。

```bash
uv run pytest -q tests/test_sprint_c_derived_stale_and_overall.py tests/test_collector_retry_skip.py
```

结果：27 passed。

```bash
uv run python scripts/check_glassnode_health.py
```

结果：3 个 Glassnode endpoint 均 `ok`。

## 12. 是否影响高风险区域

- 是否影响 Layer A 策略逻辑：否。
- 是否影响 Layer B 策略逻辑：否。
- 是否影响虚拟账户：否。
- 是否影响真实交易：否。
- 是否跑完整 pipeline：否。
- 是否读取或输出 API key：否。

## 13. 风险和未完成

1. 本轮修复会影响未来新的 fetch_attempts 分类，但不会自动改写历史 DB 里已经写成 `quota_exceeded` 的旧失败行。
2. 如果生产网页短时间内仍显示旧“配额用尽”，可能是历史 fetch_attempts 行尚未被新采集覆盖。
3. 当前 Glassnode source 是按 bucket 写一条 `fetch_attempts`，一个 endpoint 失败可能让整个 `glassnode_onchain` 显示 failure。未来可增强为 endpoint-level 失败摘要，避免“部分失败”被误解成全源失败。
4. 生产最近一次真实失败 HTTP code 当前未能直接读取，因为生产 API 有 Basic Auth，本地 DB 没有相关行。

## 14. 下一步建议

1. 服务器拉取本次修复后，等待下一次 Glassnode 采集或手动运行安全采集，让新的错误分类覆盖旧状态。
2. 如果还出现失败，运行：

```bash
.venv/bin/python scripts/check_glassnode_health.py
```

把脱敏输出用于判断到底是 403、404、429、timeout 还是服务异常。

3. 后续可以增加 endpoint-level source health，把 Glassnode 显示成“部分异常 + 具体 endpoint 原因”，而不是只显示一个总失败原因。

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待提交后填写 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |

