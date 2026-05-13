# layer_a_web_factor_display_consistency_fix

## 1. 任务目标

修复 Layer A 新增因子在「原始数据因子」模块中的显示一致性：

- 每张因子卡统一展示数值、抓取时间、状态说明。
- 缺失 / 未接入 / 数据受限不再占用“抓取时间”的位置。
- 保持原始数据因子模块现有卡片、折叠、badge、字体、字号、颜色和布局。
- 不改 Layer B 五层分析模块。
- 不改「大周期策略」模块和 Layer A AI 判断逻辑。

## 2. 改动文件

- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`

## 3. 显示一致性修复说明

原问题：

- Layer A 部分不可用因子会把 `proxy_endpoint_404` / `uncertain_rate_limited` 这类状态放进时间位置。
- 有些因子有数值但状态不是 `available` 时，数值容易被隐藏。
- 原始数据因子卡片左下角仍显示“影响”，但 Layer A 新因子更需要显示“状态”。

本轮修复：

- 新增 `layerAFactorStatusLabel()`：把 Layer A context 的 `status` 和 freshness 转为用户可读状态。
- 新增 `factorStatusLabel()` / `factorStatusLine()`：原始因子卡片统一显示状态行。
- Layer A 新因子现在：
  - `current_value`：只要 context 有真实 `actual_value` 就显示数值。
  - `fetched_at_bjt`：只显示真实抓取/入库时间或数据点时间，不再显示 unavailable 状态。
  - `status_label`：显示 `可用`、`unavailable / 未接入`、`unavailable / 数据受限`、`unavailable / 数据过期` 等。
- 更新 `app.js` 版本参数为 `layer-a-factor-display-20260513`，避免浏览器继续加载旧 JS。

## 4. Layer A context 映射字段

本轮没有改 Layer A context builder。上一轮已让 context 提供：

- `actual_value`
- `status`
- `fetched_at_utc`
- `fetched_at_bjt`
- `captured_at_utc`
- `as_of`

本轮只修前端如何读取和展示这些字段，不改变 AI 输入、不改变交易判断。

## 5. 测试命令和结果

已运行：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

结果：`117 passed`

```bash
uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_normalize.py tests/test_layer_a_spot_validator.py tests/test_layer_a_orchestrator_integration.py
```

结果：`24 passed`

```bash
git diff --check
```

结果：通过

## 6. pipeline run 结果

本地执行：

```bash
uv run python scripts/run_pipeline_once.py --trigger manual
```

结果：300 秒超时，日志无有效输出。该现象与上一轮一致，更像本地 AI/API 等待过长。本轮改动是网页显示逻辑，最终以服务器 pipeline / API 验证为准。

服务器 pipeline：待部署后补充。

## 7. 最新 run_id

待服务器 pipeline / API 验证后补充。

## 8. 网页截图

待服务器部署验证后补充。若公网仍由 Basic Auth / 网关保护，自动截图会记录认证保护页，并用服务器本机 API/HTML 结果作为技术验证。

## 9. 是否影响 Layer B / 虚拟账户 / 真实交易

- 是否影响 Layer B：否。本轮没有修改 L1-L5、Master、Validator、thesis、C 级机会。
- 是否影响虚拟账户：否。
- 是否影响真实交易：否。
- 是否影响 Layer A AI 判断：否。本轮只改网页展示 helper。

## 10. 删除清单 / 废弃清单

本轮无替代关系，无删除项。原因：本轮为网页显示一致性修复，没有引入替代模块或替代交易逻辑。

## 11. 风险和未完成

- 旧浏览器缓存可能仍显示旧 JS；本轮已更新 app.js 版本参数，用户刷新后应加载新版本。
- 公网自动访问如果被认证保护，自动截图无法看到登录后的页面，需要用户登录后肉眼确认。
- 本地 pipeline 超时，服务器验证完成后需要补充最终 run_id 和网页验证结果。

## 12. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash) | 待执行 |
| 服务器 git pull | 待执行 |
| 服务器 systemctl restart | 待执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待执行 |

## 13. 审查包路径

待生成。
